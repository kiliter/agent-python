"""二期新增确定性平台工具（extract_dates / date_shift / expand_period / time_diff / regex_extract）与 query_result 增强单元测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from report_agent.config import Settings
from report_agent.domain.resources import ResourceSet
from report_agent.domain.template import FieldDef, Template, TemplateDef
from report_agent.runtime.deps import RunDeps
from report_agent.runtime.evidence import VALUE_TOOLS, EvidenceChecker
from report_agent.runtime.text_tools import (
    date_shift as pure_date_shift,
    expand_period as pure_expand_period,
    extract_dates as pure_extract_dates,
    regex_extract as pure_regex_extract,
    time_diff as pure_time_diff,
)
from report_agent.runtime.tools import (
    Condition,
    OrderBy,
    build_tools,
    date_shift,
    expand_period,
    extract_dates,
    query_result,
    regex_extract,
    time_diff,
)
from report_agent.runtime.workspace import ApiResult, EventSink, Workspace


class _DummyGateway:
    """不发网络请求的空网关桩。#Created By AiCoding(codex)"""

    async def invoke(self, contract, args: dict):  # pragma: no cover - 本文件不走网关调用
        raise AssertionError("不应调用网关")

    async def aclose(self) -> None:
        return None


def _make_deps(tmp_path: Path, document: str = "") -> RunDeps:
    """构造测试用 RunDeps。#Created By AiCoding(codex)"""
    settings = Settings(_env_file=None, data_dir=tmp_path / "data", llm_api_key="test")
    tpl = Template(
        definition=TemplateDef(
            id=3001,
            name="确定性工具测试模板",
            fields=[FieldDef(name="结论", type="string", evidence="derive", description="测试结论")],
        ),
        body="{{结论}}",
    )
    return RunDeps(
        run_id="run_det_1",
        rev="test",
        settings=settings,
        resources=ResourceSet(templates={3001: tpl}),
        template=tpl,
        allowed_skills=[],
        allowed_apis=[],
        inputs={},
        document=document,
        gateway=_DummyGateway(),
        workspace=Workspace(),
        events=EventSink(),
    )


def _ctx(deps: RunDeps, *, retry: int = 0, max_retries: int = 1) -> RunContext[RunDeps]:
    """构造 Pydantic AI RunContext。#Created By AiCoding(codex)"""
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), prompt="", retry=retry, max_retries=max_retries)


def test_value_tools_invariant_and_registered_tools():
    """VALUE_TOOLS 必须保持仅有 format_date，切勿把返回字典的新工具混入其中。"""
    assert VALUE_TOOLS == {"format_date"}
    tool_names = [t.name for t in build_tools(2)]
    assert tool_names == [
        "load_skill",
        "call_api",
        "query_result",
        "normalize_text",
        "text_contains",
        "date_range",
        "format_date",
        "extract_dates",
        "date_shift",
        "expand_period",
        "time_diff",
        "regex_extract",
    ]


# ============================================================================ 1. extract_dates
async def test_extract_dates_rules_and_calendar_validation(tmp_path: Path):
    sms = (
        "尊敬的客户，您已于2026年11月05日在热线渠道成功办理“5G智享套餐”活动（编号：25JS206149）。\n"
        "1.活动时间：2026年12月1日00:00:00-2027-12-01 00:00:00，备份日期 2026/08/09 与 2026.08.15 及独立 20260930。\n"
        "干扰项：手机号 13920261005、流水号 20260705144056294894、时间戳 20261105103012、"
        "非法日历 2026年2月30日、2026-02-29、20614901、混合分隔符 2026-10/05、金额 2026年10月159元。"
    )
    res = pure_extract_dates(sms)
    assert res["dates"] == ["20261105", "20261201", "20271201", "20260809", "20260815", "20260930"]
    assert res["sorted"] == ["20260809", "20260815", "20260930", "20261105", "20261201", "20271201"]
    assert res["min"] == "20260809"
    assert res["max"] == "20271201"
    assert res["count"] == 6

    # 闰年 2 月 29 日合法，平年 2 月 29 日剔除
    assert pure_extract_dates("2028-02-29 vs 2027-02-29")["dates"] == ["20280229"]

    # defaultYear 补全无年份的 M月d日/号，且绝不拆解带年份片段（含非法的 2025年2月29日）
    text_md = "您于11月6号收到通知，原活动2027年12月1日到期，错误记录2025年2月29日，次月3月15日复核，重复11月06日。"
    res_md = pure_extract_dates(text_md, defaultYear="20241105103012")
    assert res_md["dates"] == ["20241106", "20271201", "20240315"]
    assert res_md["min"] == "20240315" and res_md["max"] == "20271201"
    assert pure_extract_dates("将于5月20日生效", defaultYear="2026-10-05")["dates"] == ["20260520"]
    assert pure_extract_dates("将于5月20日生效", defaultYear=2026)["dates"] == ["20260520"]
    assert pure_extract_dates("无任何日期", defaultYear="19912345678") == {
        "dates": [], "sorted": [], "min": None, "max": None, "count": 0,
    }

    # 工具层：text=None 时扫描单据全文并登记 callId，可作为 derive 证据引用
    deps = _make_deps(tmp_path, document="工单记录：客户反映 10月8日 收到扣费短信，2026-10-01 办理套餐。")
    tool_out = await extract_dates(_ctx(deps), text=None, defaultYear="20261009090000")
    assert tool_out["ok"] is True and tool_out["callId"] == "t1"
    assert tool_out["dates"] == ["20261008", "20261001"]
    assert deps.workspace.tool_calls["t1"].args["text"] == "<单据全文>"

    checker = EvidenceChecker(deps.template, {}, deps.document, deps.workspace)
    issues = checker.check({
        "结论": {
            "status": "found",
            "value": "已核实",
            "evidence": [{"type": "tool", "callId": "t1"}, {"type": "document", "quote": "10月8日"}],
        }
    })
    assert issues == []


# ============================================================================ 2. date_shift
async def test_date_shift_formats_windows_and_errors(tmp_path: Path):
    assert pure_date_shift("20280801", days=-31, endDays=31) == {
        "baseDate": "20280801",
        "date": "20280701",
        "endDate": "20280901",
        "start": "20280701000000",
        "end": "20280901235959",
    }
    assert pure_date_shift("20261105103012", days=0)["start"] == "20261105000000"
    assert pure_date_shift("2026-3-1", days=-1)["date"] == "20260228"
    assert pure_date_shift("2028/03/01", days=-1)["date"] == "20280229"
    assert pure_date_shift("2026.10.5", days=2)["end"] == "20261007235959"
    assert pure_date_shift("2026年10月5号", days=0)["baseDate"] == "20261005"

    deps = _make_deps(tmp_path)
    out = await date_shift(_ctx(deps), date="2026-11-05", days=-1, endDays=1)
    assert out == {
        "callId": "t1",
        "ok": True,
        "baseDate": "20261105",
        "date": "20261104",
        "endDate": "20261106",
        "start": "20261104000000",
        "end": "20261106235959",
    }

    # start_dt > end_dt 触发重试，重试耗尽返回结构化错误
    with pytest.raises(ModelRetry):
        await date_shift(_ctx(deps, retry=0, max_retries=1), date="20261105", days=5, endDays=1)
    fallback = await date_shift(_ctx(deps, retry=1, max_retries=1), date="20261105", days=5, endDays=1)
    assert fallback["ok"] is False and "不能晚于" in fallback["error"]


# ============================================================================ 3. expand_period
async def test_expand_period_months_ranges_and_single_values(tmp_path: Path):
    # 1. $ 闭区间（2 段有序）与多段/多分隔符账期列表（离散去重并统一按月份升序排列）
    p_dollar_range = pure_expand_period("202607$202610")
    assert p_dollar_range["months"] == ["202607", "202608", "202609", "202610"]
    assert p_dollar_range["startDate"] == "20260701" and p_dollar_range["endDate"] == "20261031"

    p_dollar = pure_expand_period("202611$202610$202611")
    assert p_dollar["months"] == ["202610", "202611"]
    assert p_dollar["startDate"] == "20261001" and p_dollar["endDate"] == "20261130"
    assert p_dollar["startTime"] == "20261001000000" and p_dollar["endTime"] == "20261130235959"
    assert p_dollar["monthRanges"][0] == {
        "month": "202610",
        "startDate": "20261001",
        "endDate": "20261031",
        "start": "20261001000000",
        "end": "20261031235959",
    }

    p_semi = pure_expand_period("2026-09; 2026年10月,202611")
    assert p_semi["months"] == ["202609", "202610", "202611"]

    # 2. 纯年月（彻底修复 Java 把 202607 回溯为 20260007 的问题）
    for raw_ym in ("202607", "2026-07", "2026/7", "2026年7月"):
        p_ym = pure_expand_period(raw_ym)
        assert p_ym["months"] == ["202607"]
        assert p_ym["startDate"] == "20260701" and p_ym["endDate"] == "20260731"

    # 3. 单一日期与时间戳（精确到当日，不把 2026-07-05 内部连字符误拆为区间）
    for raw_day in ("20260705", "20260705103000", "2026-07-05", "2026年7月5日"):
        p_day = pure_expand_period(raw_day)
        assert p_day["months"] == ["202607"]
        assert p_day["startDate"] == "20260705" and p_day["endDate"] == "20260705"
        assert p_day["monthRanges"][0]["endDate"] == "20260731"

    # 4. 各种区间连接符（紧凑日期区间、带连字符日期区间、纯年月跨年区间）
    p_r1 = pure_expand_period("20260705-20260808")
    assert p_r1["months"] == ["202607", "202608"]
    assert p_r1["startDate"] == "20260705" and p_r1["endDate"] == "20260808"

    p_r2 = pure_expand_period("2026-07-05 - 2026-08-08")
    assert p_r2["months"] == ["202607", "202608"]
    assert p_r2["startDate"] == "20260705" and p_r2["endDate"] == "20260808"

    p_r3 = pure_expand_period("2026-07-05-2026-08-08")
    assert p_r3["months"] == ["202607", "202608"]
    assert p_r3["startDate"] == "20260705" and p_r3["endDate"] == "20260808"

    p_r4 = pure_expand_period("202611-202702")
    assert p_r4["months"] == ["202611", "202612", "202701", "202702"]
    assert p_r4["startDate"] == "20261101" and p_r4["endDate"] == "20270228"

    # 5. 非法输入与跨度超限报错
    with pytest.raises(ValueError, match="超过上限"):
        pure_expand_period("202301~202602")
    with pytest.raises(ValueError, match="不能晚于"):
        pure_expand_period("20260808至20260705")
    with pytest.raises(ValueError):
        pure_expand_period("202613")

    deps = _make_deps(tmp_path)
    tool_res = await expand_period(_ctx(deps), period="202610$202611")
    assert tool_res["ok"] is True and tool_res["callId"] == "t1" and tool_res["months"] == ["202610", "202611"]


# ============================================================================ 4. time_diff
async def test_time_diff_precision_and_formats(tmp_path: Path):
    assert pure_time_diff("20260512100010", "20260512100002") == {
        "diffSeconds": 8,
        "absSeconds": 8,
        "later": "time1",
    }
    assert pure_time_diff("2026-05-12 09:59:59", "2026/05/12 10:00:02") == {
        "diffSeconds": -3,
        "absSeconds": 3,
        "later": "time2",
    }
    assert pure_time_diff("20260512100002", "2026-5-12 10:00:02") == {
        "diffSeconds": 0,
        "absSeconds": 0,
        "later": "equal",
    }

    deps = _make_deps(tmp_path)
    out = await time_diff(_ctx(deps), time1="20260512095959", time2="20260512100002")
    assert out == {"callId": "t1", "ok": True, "diffSeconds": -3, "absSeconds": 3, "later": "time2"}

    with pytest.raises(ModelRetry):
        await time_diff(_ctx(deps, retry=0, max_retries=1), time1="bad", time2="20260512100002")


# ============================================================================ 5. regex_extract
async def test_regex_extract_groups_fallback_and_dedup(tmp_path: Path):
    sms = "【退订提醒】您已经中断了2023年6月办理的“最近原套餐”活动（编号：25JS206149），关联（编号：25JS999999）与（编号：25JS206149）。"
    r_pkg = pure_regex_extract(r'办理的\s*[“"]([^”"]+)[”"]', sms, group=1)
    assert r_pkg == {"matches": ["最近原套餐"], "allMatches": ["最近原套餐"], "first": "最近原套餐", "count": 1}

    r_codes = pure_regex_extract(r"[（(]编号[:：]\s*([A-Za-z0-9_-]+)[）)]", sms)
    assert r_codes == {
        "matches": ["25JS206149", "25JS999999"],
        "allMatches": ["25JS206149", "25JS999999", "25JS206149"],
        "first": "25JS206149",
        "count": 2,
    }

    # 模型未写捕获组括号而默认 group=1 时自动退回整段匹配 group=0
    r_nogroup = pure_regex_extract(r"25JS\d+", sms, group=1)
    assert r_nogroup["matches"] == ["25JS206149", "25JS999999"]

    # 显式传入超出捕获组数量的 group（如 group=2）报错
    with pytest.raises(ValueError, match="捕获组"):
        pure_regex_extract(r"(25JS\d+)", sms, group=2)

    deps = _make_deps(tmp_path, document="设备串号：IMEI-88990011")
    out = await regex_extract(_ctx(deps), pattern=r"IMEI-(\d+)", text=None)
    assert out == {"callId": "t1", "ok": True, "matches": ["88990011"], "allMatches": ["88990011"], "first": "88990011", "count": 1}


# ============================================================================ 6. query_result 增强
async def test_query_result_enhanced_operators_anyof_and_multi_results(tmp_path: Path):
    deps = _make_deps(tmp_path)
    deps.workspace.add_result(
        ApiResult(
            "r1",
            "BOSS_QryBalanceFlowLog",
            "7月充值",
            {"账期": "202607"},
            True,
            None,
            {"payDatetime": "充值时间", "payTypeName": "支付方式", "amount": "金额", "soNbr": "流水号"},
            [
                {"payDatetime": "20260705144056", "payTypeName": "和包支付", "amount": "5000", "soNbr": "S1"},
                {"payDatetime": "20260729091000", "payTypeName": "微信支付", "amount": "3000", "soNbr": "S2"},
                {"payDatetime": "bad", "payTypeName": "异常记录", "amount": "100", "soNbr": "S_BAD"},
            ],
            5,
        )
    )
    deps.workspace.add_result(
        ApiResult(
            "r2",
            "BOSS_QryBalanceFlowLog",
            "8月充值",
            {"账期": "202608"},
            True,
            None,
            {"payDatetime": "充值时间", "payTypeName": "支付方式", "amount": "金额", "soNbr": "流水号"},
            [
                {"payDatetime": "20260802112030", "payTypeName": "支付宝", "amount": "2000", "soNbr": "S3"},
                {"payDatetime": "20260819180000", "payTypeName": "掌厅", "amount": "1000", "soNbr": "S4"},
            ],
            6,
        )
    )
    deps.workspace.add_result(
        ApiResult("r3", "BOSS_QryBalanceFlowLog", "9月无数据", {"账期": "202609"}, True, None, {}, [], 3, no_data=True)
    )
    deps.workspace.add_result(
        ApiResult("r_fail", "BOSS_QryBalanceFlowLog", "失败账期", {"账期": "202610"}, False, "7003 系统忙", {}, [], 4)
    )

    # 1. 多结果合并 + between + prefixLen=8（自动忽略不足 8 位的 "bad"）+ 跨月倒序
    merged = await query_result(
        _ctx(deps),
        where=[Condition(column="payDatetime", op="between", value="20260720", endValue="20260810", prefixLen=8)],
        orderBy=OrderBy(column="payDatetime", desc=True),
        columns=["payDatetime", "amount", "soNbr"],
        resultIds=["r1", "r2", "r3"],
    )
    assert merged == {
        "callId": "t1",
        "resultIds": ["r1", "r2", "r3"],
        "total": 2,
        "rows": [
            {"payDatetime": "20260802112030", "amount": "2000", "soNbr": "S3", "resultId": "r2", "row": 0},
            {"payDatetime": "20260729091000", "amount": "3000", "soNbr": "S2", "resultId": "r1", "row": 1},
        ],
    }

    # 2. 单结果向后兼容 + startsWith + anyOf（OR 条件）+ 返回 callId
    single = await query_result(
        _ctx(deps),
        "r1",
        where=[Condition(column="payDatetime", op="startsWith", value="202607")],
        anyOf=[
            Condition(column="payTypeName", op="contains", value="和包"),
            Condition(column="soNbr", op="equals", value="S2"),
        ],
        orderBy=OrderBy(column="payDatetime", desc=False),
    )
    assert set(single.keys()) == {"callId", "resultId", "total", "rows"}
    assert single["callId"] == "t2" and single["resultId"] == "r1" and single["total"] == 2
    assert [r["row"] for r in single["rows"]] == [0, 1]
    assert "resultId" not in single["rows"][0]

    # 3. 多结果中存在 ok=False 的接口结果时返回结构化失败（含 callId），不静默吞掉失败月份
    failed_merge = await query_result(_ctx(deps), resultIds=["r1", "r_fail"])
    assert failed_merge["callId"] == "t3" and failed_merge["ok"] is False and "r_fail" in failed_merge["error"]

    # 4. 不存在的 resultId 或缺失 endValue 的 between 条件触发 ModelRetry
    with pytest.raises(ModelRetry):
        await query_result(_ctx(deps, retry=0, max_retries=1), resultIds=["r1", "r_missing"])
    with pytest.raises(ModelRetry):
        await query_result(
            _ctx(deps, retry=0, max_retries=1),
            resultId="r1",
            where=[Condition(column="payDatetime", op="between", value="20260701")],
        )
