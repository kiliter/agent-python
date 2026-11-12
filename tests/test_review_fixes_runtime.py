"""代码审查修复专项回归测试（fix-runtime：证据防线、确定性原语、网关/Jinja2 加固与运行时性能优化）。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import statistics
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from report_agent.config import Settings
from report_agent.domain.api_contract import parse_api_yaml
from report_agent.domain.jinja_env import TrackedValue, render_body
from report_agent.domain.resources import ResourceSet, validate_template
from report_agent.domain.skill import Skill, SkillMeta
from report_agent.domain.template import ColumnDef, FieldDef, InputDef, Template, TemplateDef
from report_agent.gateway.base import ApiCallResult, extract_json_records, parse_xml
from report_agent.gateway.unified_xml import UnifiedGatewayXmlClient
from report_agent.runtime.deps import RunDeps
from report_agent.runtime.evidence import EvidenceChecker, get_document_index, locate_quote_in_document
from report_agent.runtime.prompt import _field_line, build_task_instructions
from report_agent.runtime.runner import RunRequest, _DynamicLimiter
from report_agent.runtime.text_tools import (
    MAX_REGEX_TEXT_LENGTH,
    date_range as pure_date_range,
    expand_period as pure_expand_period,
    extract_dates as pure_extract_dates,
    normalize_text as pure_normalize_text,
    regex_extract as pure_regex_extract,
    safe_regex_compile,
)
from report_agent.runtime.tools import (
    Condition,
    call_api,
    format_date,
    load_skill,
    query_result,
    text_contains,
)
from report_agent.runtime.workspace import ApiResult, EventSink, Workspace
from scripted_model import ORDER_SMS, build_report


def _ctx(deps: RunDeps, *, retry: int = 0, max_retries: int = 1) -> RunContext[RunDeps]:
    """构造测试用 RunContext。#Created By AiCoding(codex)"""
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), prompt="", retry=retry, max_retries=max_retries)


class _CountingGateway:
    """统计网关调用次数并支持模拟慢响应与首轮失败的测试网关。#Created By AiCoding(codex)"""

    def __init__(self, *, delay_s: float = 0.0, fail_first: bool = False) -> None:
        self.calls: int = 0
        self.delay_s = delay_s
        self.fail_first = fail_first

    async def invoke(self, contract: Any, args: dict[str, Any]) -> ApiCallResult:
        self.calls += 1
        cur = self.calls
        if self.delay_s > 0:
            await asyncio.sleep(self.delay_s)
        if self.fail_first and cur == 1:
            return ApiCallResult(ok=False, error="9999 临时超时", cost_ms=5)
        return ApiCallResult(
            ok=True,
            records=[{"smsContent": "【提醒】尊敬的客户，测试短信", "sendTime": "20261105100000"}],
            cost_ms=3,
            raw="<operation_out/>",
        )

    async def aclose(self) -> None:
        return None


def _sms_contract(*, idempotent: bool = True):
    return parse_api_yaml(
        f"""
name: querySMSSendInfo
title: 短信记录查询
connector: unified-gateway-xml
processCode: querySMSSendInfo
idempotent: {"true" if idempotent else "false"}
input:
  type: object
  required: [手机号码, 开始时间, 结束时间]
  additionalProperties: false
  properties:
    手机号码:
      type: string
    开始时间:
      type: string
    结束时间:
      type: string
request:
  content:
    userMobile: ${{手机号码}}
    startDate: ${{开始时间}}
    endDate: ${{结束时间}}
response:
  success:
    path: response.resp_code
    equals: "0000"
  records:
    path: content.smsList
    columns:
      smsContent: 短信内容
      sendTime: 发送时间
"""
    )


# ============================================================================ 1. callId 补齐与幂等去重
async def test_call_api_and_query_result_call_id_and_idempotent_dedup(tmp_path: Path):
    contract = _sms_contract(idempotent=True)
    non_idem = _sms_contract(idempotent=False).model_copy(update={"name": "nonIdemApi"})
    gw = _CountingGateway(delay_s=0.02, fail_first=True)
    tpl = Template(definition=TemplateDef(id=9001, name="测试", fields=[FieldDef(name="结论", evidence="derive")]))
    settings = Settings(_env_file=None, data_dir=tmp_path / "data")
    rs = ResourceSet(templates={9001: tpl}, apis={"querySMSSendInfo": contract, "nonIdemApi": non_idem})
    deps = RunDeps(
        run_id="r_idem",
        rev="r1",
        settings=settings,
        resources=rs,
        template=tpl,
        allowed_skills=[],
        allowed_apis=["querySMSSendInfo", "nonIdemApi"],
        inputs={},
        document="",
        gateway=gw,
        workspace=Workspace(),
        events=EventSink(),
    )
    args_a = {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}
    args_b = {"结束时间": "20261105235959", "手机号码": "13900001234", "开始时间": "20261105000000"}

    # 1) 首次调用失败：返回字典包含 callId，且 ok=False 结果绝不写入幂等缓存
    first_fail = await call_api(_ctx(deps), "querySMSSendInfo", args_a)
    assert first_fail["ok"] is False and first_fail["callId"] == "t1" and first_fail["resultId"] == "r1"
    assert gw.calls == 1

    # 2) 并发发起两次相同参数（键序不同）的幂等调用：共享同一个在途请求，网关只再调 1 次，各自拥有独立 callId
    out1, out2 = await asyncio.gather(
        call_api(_ctx(deps), "querySMSSendInfo", args_a),
        call_api(_ctx(deps), "querySMSSendInfo", args_b),
    )
    assert gw.calls == 2
    assert out1["ok"] is True and out2["ok"] is True
    assert out1["resultId"] == "r2" and out2["resultId"] == "r2"
    assert {out1["callId"], out2["callId"]} == {"t2", "t3"}
    assert list(deps.workspace.results.keys()) == ["r1", "r2"]

    # 3) 后续串行再次调用相同幂等接口：直接命中已完成缓存，网关调用次数仍保持 2
    out3 = await call_api(_ctx(deps), "querySMSSendInfo", args_a)
    assert gw.calls == 2
    assert out3["resultId"] == "r2" and out3["callId"] == "t4"

    # 4) idempotent=False 的接口每次均真实请求网关
    await call_api(_ctx(deps), "nonIdemApi", args_a)
    await call_api(_ctx(deps), "nonIdemApi", args_a)
    assert gw.calls == 4

    # 5) query_result 在单表失败、单表成功与多表合并分支均返回 callId
    q_fail = await query_result(_ctx(deps), resultId="r1")
    assert q_fail["ok"] is False and q_fail["callId"] == "t7"
    q_ok = await query_result(_ctx(deps), resultId="r2")
    assert q_ok["total"] == 1 and q_ok["callId"] == "t8"


# ============================================================================ 2. 空列表证据防线收紧
def test_empty_list_evidence_strict_validation():
    tpl = Template(
        definition=TemplateDef(
            id=9002,
            name="空列表防线模板",
            inputs=[InputDef(key="手机号码", required=True)],
            fields=[
                FieldDef(
                    name="充值流水",
                    type="list",
                    evidence="quote",
                    columns=[ColumnDef(name="充值时间"), ColumnDef(name="金额")],
                ),
            ],
        ),
        body="{% for r in 充值流水 %}{{r.金额}}{% endfor %}",
    )
    ws = Workspace()
    ws.add_result(ApiResult("r_nonempty", "queryRecharge", "有数据", {}, True, None, {}, [{"payTime": "1", "amt": "2"}], 1))
    ws.add_result(ApiResult("r_empty", "queryRecharge", "无数据", {}, True, None, {}, [], 1, no_data=True))
    t_skill = ws.record_call("load_skill", {"name": "recharge-flow"}, {"title": "充值流水"}, 1)
    t_norm = ws.record_call("normalize_text", {"text": "abc"}, {"value": "abc"}, 2)
    t_api_nonempty = ws.record_call("call_api", {"name": "queryRecharge"}, {"resultId": "r_nonempty", "count": 1}, 3)
    t_api_zero = ws.record_call("call_api", {"name": "queryRecharge"}, {"resultId": "r_empty", "count": 0}, 4)
    t_qr_nonempty = ws.record_call("query_result", {"resultId": "r_nonempty"}, {"total": 1, "rows": [0]}, 5)
    t_qr_zero = ws.record_call("query_result", {"resultId": "r_nonempty"}, {"total": 0, "rows": []}, 6)

    checker = EvidenceChecker(tpl, {"手机号码": "13900001234"}, "单据原文说明：无充值", ws)

    def _chk(ev: list[dict[str, Any]]):
        return checker.check({"充值流水": {"status": "found", "value": [], "evidence": ev}})

    # 拦截 load_skill、非查询工具、条数 > 0 的工具、原始记录 > 0 的 api 以及负数行号
    assert any("load_skill" in i.message for i in _chk([{"type": "tool", "callId": t_skill.call_id}]))
    assert any("不是数据查询工具" in i.message for i in _chk([{"type": "tool", "callId": t_norm.call_id}]))
    assert any("不为 0" in i.message for i in _chk([{"type": "tool", "callId": t_api_nonempty.call_id}]))
    assert any("不为 0" in i.message for i in _chk([{"type": "tool", "callId": t_qr_nonempty.call_id}]))
    assert any("query_result" in i.message for i in _chk([{"type": "api", "resultId": "r_nonempty", "row": 0}]))
    assert any("row" in i.message for i in _chk([{"type": "api", "resultId": "r_empty", "row": -999}]))

    # 允许 count=0 的 call_api、total=0 的 query_result、0 行 api（row 省略或为 0）
    assert _chk([{"type": "tool", "callId": t_api_zero.call_id}]) == []
    assert _chk([{"type": "tool", "callId": t_qr_zero.call_id}]) == []
    assert _chk([{"type": "api", "resultId": "r_empty", "row": 0, "column": ""}]) == []
    assert _chk([{"type": "api", "resultId": "r_empty"}]) == []


# ============================================================================ 3. _check_ref_exists、环外入环与全量 not_found 级联
async def test_ref_exists_cycle_tail_and_self_reported_not_found_cascade(container, case_c01):
    tpl = Template(
        definition=TemplateDef(
            id=9003,
            name="引用与级联防线模板",
            inputs=[InputDef(key="手机号码", required=True), InputDef(key="备注", required=False)],
            fields=[
                FieldDef(name="前置短信", type="string", evidence="quote"),
                FieldDef(name="备用渠道", type="string", evidence="input"),
                FieldDef(name="一级推导", type="string", evidence="derive"),
                FieldDef(name="二级推导", type="string", evidence="derive"),
                FieldDef(name="环节点A", type="string", evidence="derive"),
                FieldDef(name="环节点B", type="string", evidence="derive"),
                FieldDef(name="环外节点C", type="string", evidence="derive"),
            ],
        ),
        body="{{一级推导}}-{{二级推导}}",
    )
    ws = Workspace()
    t_skill = ws.record_call("load_skill", {"name": "s1"}, {"title": "技能"}, 1)
    t_dates = ws.record_call("extract_dates", {"text": "x"}, {"dates": [], "count": 0}, 2)
    checker = EvidenceChecker(tpl, {"手机号码": "13900001234", "备注": "   "}, "单据：正常", ws)

    nf = {"status": "not_found", "value": None, "evidence": []}
    report = {
        "前置短信": nf,
        "备用渠道": {"status": "found", "value": "热线", "evidence": [{"type": "input", "key": "备注"}]},
        "一级推导": {
            "status": "found",
            "value": "结论1",
            "evidence": [{"type": "field", "name": "前置短信"}, {"type": "tool", "callId": t_dates.call_id}],
        },
        "二级推导": {
            "status": "found",
            "value": "结论2",
            "evidence": [{"type": "field", "name": "一级推导"}, {"type": "tool", "callId": t_skill.call_id}],
        },
        "环节点A": {
            "status": "found",
            "value": "A",
            "evidence": [{"type": "document", "quote": "单据：正常"}, {"type": "field", "name": "环节点B"}],
        },
        "环节点B": {
            "status": "found",
            "value": "B",
            "evidence": [{"type": "document", "quote": "单据：正常"}, {"type": "field", "name": "环节点A"}],
        },
        "环外节点C": {
            "status": "found",
            "value": "C",
            "evidence": [{"type": "document", "quote": "单据：正常"}, {"type": "field", "name": "环节点A"}],
        },
    }
    issues = checker.check(report)
    by_field: dict[str, list[str]] = {}
    for item in issues:
        by_field.setdefault(item.field, []).append(item.message)

    assert any("为空" in m for m in by_field["备用渠道"])
    assert any("状态为 not_found" in m for m in by_field["一级推导"])
    assert any("状态为 not_found" in m for m in by_field["二级推导"])
    assert any("load_skill" in m for m in by_field["二级推导"])
    # C -> A <-> B：环外节点 C 同样报告循环依赖
    for cyc_node in ("环节点A", "环节点B", "环外节点C"):
        assert any("循环依赖" in m for m in by_field[cyc_node]), cyc_node

    # 端到端验证：入参自动 .strip() + 模型自报前置字段 not_found 时下游衍生字段全量级联降级（含 salvage 路径）
    tpl_1001 = container.service.template_online(1001)
    assert tpl_1001 is not None
    container.service.save_template(
        Template(
            definition=tpl_1001.definition.model_copy(
                update={
                    "id": 9004,
                    "name": "自报not_found级联模板",
                    "fields": [
                        *tpl_1001.definition.fields,
                        FieldDef(name="短信衍生结论", visible=True, type="string", evidence="derive"),
                        FieldDef(name="短信二级衍生", visible=True, type="string", evidence="derive"),
                    ],
                }
            ),
            body=tpl_1001.body + "\n{{短信衍生结论}}/{{短信二级衍生}}",
        ),
        "tester",
        action="create",
    )

    seen_mobile: list[str] = []

    def self_nf_model(messages, info):
        n = sum(1 for m in messages if isinstance(m, ModelResponse))
        if n == 0:
            return ModelResponse(parts=[ToolCallPart("call_api", {"name": "querySMSSendInfo", "args": {
                "手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}})])
        if n == 1:
            return ModelResponse(parts=[ToolCallPart("format_date", {"value": "20261105", "fromPattern": "yyyyMMdd",
                                                                     "toPattern": "yyyy年M月d号"})])
        rep = build_report(ORDER_SMS, "t2")
        # 模型主动把“订购短信”报为 not_found，却在下游“短信衍生结论 -> 短信二级衍生”中悬空引用它提交 found
        rep["订购短信"] = {"status": "not_found", "value": None, "evidence": [], "reasoning": "未查到订购短信"}
        rep["短信衍生结论"] = {
            "status": "found",
            "value": "虚构衍生1",
            "evidence": [{"type": "field", "name": "订购短信"}],
        }
        rep["短信二级衍生"] = {
            "status": "found",
            "value": "虚构衍生2",
            "evidence": [{"type": "field", "name": "短信衍生结论"}],
        }
        # 故意漏填“二次确认短信”以覆盖 _salvage_partial_report 路径
        rep.pop("二次确认短信")
        return ModelResponse(parts=[TextPart("{}"), ToolCallPart("submit_report", rep)])

    orig_model = container.runner.model
    container.runner.model = FunctionModel(self_nf_model)
    try:
        noisy_inputs = {**case_c01["inputs"], "手机号码": "  13900001234  "}
        out = await container.runner.run(RunRequest(9004, noisy_inputs, case_c01["documentText"], target="draft"))
        seen_mobile.append(out["inputs"]["手机号码"])
    finally:
        container.runner.model = orig_model

    assert seen_mobile == ["13900001234"]
    fields_map = {f["name"]: f for f in out["fields"]}
    assert fields_map["短信衍生结论"]["status"] == "not_found" and fields_map["短信衍生结论"]["validationFailed"] is True
    assert fields_map["短信二级衍生"]["status"] == "not_found" and fields_map["短信二级衍生"]["validationFailed"] is True
    # 回退链 [受理网点(not_found), 受理渠道(found)] 有真实有效支撑源，保持 found
    assert fields_map["受理方式"]["status"] == "found" and fields_map["受理方式"]["value"] == "热线"


# ============================================================================ 4. 确定性原语、防 ReDoS 与批量工具
async def test_deterministic_primitives_redos_and_batch_tools(tmp_path: Path):
    # 1) extract_dates：拒绝无“日/号”后缀的套餐名/月租/折扣数字
    noisy = "您于2026年10月办理：2026年10月5G特惠包，2026年10月20元月租，享2026年10月8折优惠"
    assert pure_extract_dates(noisy)["dates"] == []
    assert pure_extract_dates(noisy + "，将于2026年10月31日到期（11月1号续订）", defaultYear=2026)["dates"] == [
        "20261031",
        "20261101",
    ]

    # 2) date_range：带前缀单数字月/日分隔日期精确解析 + unit="month" 支持 6 位年月
    assert pure_date_range("受理时间：2026-1-12 03:04:05", "day") == ("20260112000000", "20260112235959")
    assert pure_date_range("办理日期：2026年1月5号", "day") == ("20260105000000", "20260105235959")
    assert pure_date_range("202610", "month") == ("20261001000000", "20261031235959")
    assert pure_date_range("2026-2", "month") == ("20260201000000", "20260228235959")
    assert pure_date_range("2028/02", "month") == ("20280201000000", "20280229235959")
    assert pure_date_range("2026年11月", "month") == ("20261101000000", "20261130235959")
    with pytest.raises(ValueError):
        pure_date_range("202610", "day")
    with pytest.raises(ValueError):
        pure_date_range("手机号13920261005", "day")

    # 3) expand_period：2 段 $ 展开闭区间，多段或其它分隔符去重并升序排列
    assert pure_expand_period("202607$202610")["months"] == ["202607", "202608", "202609", "202610"]
    assert pure_expand_period("2026-11, 2026-09, 2026-10")["months"] == ["202609", "202610", "202611"]
    with pytest.raises(ValueError, match="超过上限"):
        pure_expand_period("202201$202601")

    # 4) safe_regex_compile 防 ReDoS 语法树拦截 + regex_extract 文本长度上限
    for dangerous in (r"(a+)+", r"([a-z]*)*", r"(?:a|b+){2,}", r"(a?)+", r"(a{1,3})+"):
        with pytest.raises(ValueError, match="回溯风险"):
            safe_regex_compile(dangerous)
    assert safe_regex_compile(r"^\d+(?:\.\d+)?$").fullmatch("12.5") is not None
    with pytest.raises(ValueError, match="超过安全上限"):
        pure_regex_extract(r"\d+", "1" * (MAX_REGEX_TEXT_LENGTH + 1), group=0)

    # 5) text_contains 默认剥离折行空白，而底层 normalize_text 默认行为不变
    tpl = Template(definition=TemplateDef(id=9005, name="工具集测试", fields=[FieldDef(name="格式化日期", evidence="derive")]))
    s1 = Skill(meta=SkillMeta(name="skill-a", title="技能A", description="A", apis=[]), body="说明A", markdown="说明A")
    s2 = Skill(meta=SkillMeta(name="skill-b", title="技能B", description="B", apis=[]), body="说明B", markdown="说明B")
    deps = RunDeps(
        run_id="r_tools",
        rev="r1",
        settings=Settings(_env_file=None, data_dir=tmp_path / "data"),
        resources=ResourceSet(templates={9005: tpl}, skills={"skill-a": s1, "skill-b": s2}),
        template=tpl,
        allowed_skills=["skill-a", "skill-b"],
        allowed_apis=[],
        inputs={},
        document="业务名称：\n5G智享套餐\n（个人版）",
        gateway=_CountingGateway(),
        workspace=Workspace(),
        events=EventSink(),
    )
    assert pure_normalize_text("a b\nc") == "a b\nc"
    tc = await text_contains(_ctx(deps), target="5G智享套餐（个人版）")
    assert tc["contains"] is True and tc["normalizedTarget"] == "5G智享套餐个人版"

    # 6) query_result：0 行结果与投影列 columns 均严格校验已知列名
    deps.workspace.add_result(
        ApiResult("r_zero", "querySMS", "空表", {}, True, None, {"smsContent": "内容", "sendTime": "时间"}, [], 1)
    )
    with pytest.raises(ModelRetry, match="typoCol"):
        await query_result(
            _ctx(deps, retry=0, max_retries=1),
            resultId="r_zero",
            where=[Condition(column="typoCol", op="equals", value="x")],
        )
    with pytest.raises(ModelRetry, match="badProjection"):
        await query_result(_ctx(deps, retry=0, max_retries=1), resultId="r_zero", columns=["badProjection"])

    # 7) format_date：ValueError 走 _fail_or_retry + 支持批量 values 并兼容 VALUE_TOOLS 核验
    with pytest.raises(ModelRetry):
        await format_date(_ctx(deps, retry=0, max_retries=1), value="bad", fromPattern="yyyyMMdd", toPattern="yyyy-MM-dd")
    exhausted_fd = await format_date(
        _ctx(deps, retry=1, max_retries=1), value="bad", fromPattern="yyyyMMdd", toPattern="yyyy-MM-dd"
    )
    assert exhausted_fd["ok"] is False and "callId" in exhausted_fd

    batch_fd = await format_date(
        _ctx(deps),
        fromPattern="yyyyMMdd",
        toPattern="yyyy年M月d号",
        values=["20261005", "20261106"],
    )
    assert batch_fd["ok"] is True and batch_fd["values"] == ["2026年10月5号", "2026年11月6号"]
    checker = EvidenceChecker(tpl, {}, "", deps.workspace)
    assert (
        checker.check(
            {
                "格式化日期": {
                    "status": "found",
                    "value": "2026年11月6号",
                    "evidence": [{"type": "tool", "callId": batch_fd["callId"]}],
                }
            }
        )
        == []
    )
    assert checker.check(
        {
            "格式化日期": {
                "status": "found",
                "value": "2026年12月1号",
                "evidence": [{"type": "tool", "callId": batch_fd["callId"]}],
            }
        }
    )

    # 8) load_skill：批量加载多个白名单 Skill 与越权拦截
    merged_skills = await load_skill(_ctx(deps), names=["skill-a", "skill-b"])
    assert "技能A" in merged_skills and "技能B" in merged_skills
    assert deps.workspace.loaded_skills == ["skill-a", "skill-b"]
    with pytest.raises(ModelRetry):
        await load_skill(_ctx(deps, retry=0, max_retries=1), names=["skill-a", "unauthorized-skill"])


# ============================================================================ 5. 网关 JSON 列表点分列、ret_msg 与并发信号量
async def test_gateway_json_list_dotted_ret_msg_and_concurrency_semaphore():
    json_contract = parse_api_yaml(
        """
name: queryActivityJson
title: 营销活动查询
connector: unified-gateway-json
processCode: queryActivityJson
input:
  type: object
  properties: {}
request: {}
response:
  success:
    path: response.ret_code
    equals: "0"
  records:
    mode: object
    path: content
    columns:
      level_info.event_name: 档位名称
      single_info.code: 单元素编码
"""
    )
    payload_ok = {
        "response": {"ret_code": "0"},
        "content": {
            "level_info": [{"event_name": "档位一"}, {"event_name": "档位二"}],
            "single_info": [{"code": "C01"}],
        },
    }
    res_ok = extract_json_records(json_contract, payload_ok)
    assert res_ok.ok is True and res_ok.error is None and res_ok.no_data is False
    assert len(res_ok.records) == 1
    assert res_ok.records[0]["level_info.event_name"] == '["档位一","档位二"]'
    assert res_ok.records[0]["single_info.code"] == "C01"

    payload_err = {"response": {"ret_code": "5001", "ret_msg": "下游账管服务超时"}}
    res_err = extract_json_records(json_contract, payload_err)
    assert res_err.ok is False and res_err.error is not None
    assert "5001" in res_err.error and "下游账管服务超时" in res_err.error

    # parse_xml 单遍正常解析 + CDATA 内 <!DOCTYPE html> 放行 + 真实 DOCTYPE 拦截
    assert parse_xml("<root><item><![CDATA[<!DOCTYPE html>你好]]></item></root>").findtext("item") == "<!DOCTYPE html>你好"
    with pytest.raises(ET.ParseError, match="DOCTYPE"):
        parse_xml('<!DOCTYPE foo [<!ENTITY x "1">]><root/>')

    # UnifiedGatewayXmlClient 并发信号量保护
    active = 0
    peak = 0

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.03)
        active -= 1
        return httpx.Response(
            200,
            text="<operation_out><response><resp_code>0000</resp_code></response><content/></operation_out>",
        )

    xml_client = UnifiedGatewayXmlClient(
        base_url="http://mock-gw",
        app_id="APP",
        access_token="TOK",
        max_concurrency=2,
    )
    await xml_client._client.aclose()
    xml_client._client = httpx.AsyncClient(transport=httpx.MockTransport(slow_handler))
    try:
        sms = _sms_contract()
        await asyncio.gather(
            *(
                xml_client.invoke(
                    sms,
                    {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"},
                )
                for _ in range(6)
            )
        )
    finally:
        await xml_client.aclose()
    assert peak <= 2


# ============================================================================ 6. Jinja2 过滤器追踪、LRU 并发隔离与静态告警
async def test_jinja_filter_tracking_lru_isolation_and_list_if_warning():
    val_missing = TrackedValue("{{订购短信}}", "订购短信", missing=True)
    text, used = render_body("短信：{{ [订购短信] | join(',') }}", {"订购短信": val_missing})
    assert text == "短信：{{订购短信}}" and used == {"订购短信"}

    text_trim, used_trim = render_body("{{ 订购短信 | trim }}", {"订购短信": TrackedValue("  内容  ", "订购短信")})
    assert text_trim == "内容" and used_trim == {"订购短信"}

    # 同一模板并发渲染：共享预编译 Template 对象但各自 _ACTIVE_USED 互不串扰
    shared_body = "{% if 分支 == 'A' %}{{字段A}}{% else %}{{字段B}}{% endif %}"

    async def _render_one(branch: str) -> tuple[str, set[str]]:
        await asyncio.sleep(0)
        return render_body(
            shared_body,
            {
                "分支": branch,
                "字段A": TrackedValue("值A", "字段A"),
                "字段B": TrackedValue("值B", "字段B"),
            },
        )

    results = await asyncio.gather(*(_render_one("A" if i % 2 == 0 else "B") for i in range(20)))
    for i, (rendered, u) in enumerate(results):
        if i % 2 == 0:
            assert rendered == "值A" and u == {"字段A"}
        else:
            assert rendered == "值B" and u == {"字段B"}

    # resources.py 对 {% if 列表字段 %} 给出 LIST_IN_IF_CONDITION 告警
    warn_tpl = Template(
        definition=TemplateDef(
            id=9006,
            name="列表条件告警模板",
            fields=[
                FieldDef(name="充值流水", type="list", evidence="quote", columns=[ColumnDef(name="金额")]),
            ],
        ),
        body="{% if 充值流水 %}{% for r in 充值流水 %}{{r.金额}}{% endfor %}{% endif %}",
    )
    res_issues = validate_template(warn_tpl, ResourceSet(templates={9006: warn_tpl}))
    assert any(i.code == "LIST_IN_IF_CONDITION" and i.level == "warning" for i in res_issues)


# ============================================================================ 7. 运行时默认配置、提示词精简、缓存与动态限流器
async def test_runtime_defaults_prompt_cache_doc_index_and_dynamic_limiter(container, case_c01, tmp_path: Path):
    # 1) 默认配置已调优为 tool_calls_limit=120 且 parallel_tool_calls=True
    default_settings = Settings(_env_file=None, data_dir=tmp_path / "d")
    assert default_settings.agent_tool_calls_limit == 120
    assert default_settings.llm_parallel_tool_calls is True

    # 2) prompt.py 剥离“原规则（Java）：”历史对照文本，并展示未在 tpl.inputs 声明的非空附加传入参数
    f_with_java = FieldDef(
        name="到期提醒短信",
        type="string",
        evidence="quote",
        description="核查到期提醒短信原文。\n\n原规则（Java）：assembly.groovy 第 80 行巴拉巴拉",
    )
    line = _field_line(f_with_java)
    assert "核查到期提醒短信原文。" in line and "原规则（Java）" not in line

    tpl_1001 = container.service.template_online(1001)
    assert tpl_1001 is not None
    deps = RunDeps(
        run_id="r_prompt",
        rev="r1",
        settings=default_settings,
        resources=ResourceSet(templates={1001: tpl_1001}),
        template=tpl_1001,
        allowed_skills=[],
        allowed_apis=[],
        inputs={**case_c01["inputs"], "deadlineDate": "20261201", "空白附加项": "   "},
        document="单据正文",
        gateway=_CountingGateway(),
        workspace=Workspace(),
        events=EventSink(),
    )
    instructions = build_task_instructions(deps)
    assert "deadlineDate：20261201" in instructions
    assert "空白附加项" not in instructions

    # 3) DocumentIndex 在同一 Workspace 上惰性复用
    ws_doc = Workspace()
    long_doc = "第一行\n第二行：办理业务 5G智享套餐\n第三行：鉴权方式 服务密码\n" * 20
    idx1 = get_document_index(ws_doc, long_doc)
    idx2 = get_document_index(ws_doc, long_doc)
    assert idx1 is idx2
    locs = locate_quote_in_document(long_doc, "办理业务   5G智享套餐", index=idx1)
    assert len(locs) == 20 and locs[0]["line"] == 2

    # 4) AgentRunner 按 (rev, tpl.id, bundle.seq) 缓存线上 (report_model, agent)，更换 model 后自动失效
    container.runner._agent_cache.clear()
    out_a = await container.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"]))
    assert out_a["status"] == "SUCCESS"
    assert len(container.runner._agent_cache) == 1
    first_key = next(iter(container.runner._agent_cache.keys()))
    cached_pair = container.runner._agent_cache[first_key]
    out_b = await container.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"]))
    assert out_b["status"] == "SUCCESS"
    assert container.runner._agent_cache[first_key] is cached_pair

    # 5) _DynamicLimiter：热重载下调上限时不突破在途并发，跨线程上调上限时即时唤醒排队协程
    limiter = _DynamicLimiter(3)
    assert limiter._value == 3
    entered = 0
    max_seen = 0
    release_first_wave = asyncio.Event()

    async def _worker(wave: int) -> None:
        nonlocal entered, max_seen
        async with limiter:
            entered += 1
            max_seen = max(max_seen, limiter.inflight)
            if wave == 1:
                await release_first_wave.wait()
            else:
                await asyncio.sleep(0.01)

    w1 = [asyncio.create_task(_worker(1)) for _ in range(3)]
    while limiter.inflight < 3:
        await asyncio.sleep(0.005)
    # 已有 3 个在途请求时把上限热更新下调为 1：新来的协程绝不能趁机进入使并发冲到 4
    await asyncio.to_thread(limiter.set_limit, 1)
    assert limiter._value == 0
    w2 = asyncio.create_task(_worker(2))
    await asyncio.sleep(0.02)
    assert entered == 3 and max_seen == 3

    release_first_wave.set()
    await asyncio.gather(*w1, w2)
    assert entered == 4 and limiter.inflight == 0

    # 跨线程上调上限立即唤醒等待队列
    hold = asyncio.Event()

    async def _hold_slot() -> None:
        async with limiter:
            await hold.wait()

    h1 = asyncio.create_task(_hold_slot())
    while limiter.inflight < 1:
        await asyncio.sleep(0.005)
    h2 = asyncio.create_task(_hold_slot())
    await asyncio.sleep(0.01)
    assert limiter.inflight == 1
    await asyncio.to_thread(limiter.set_limit, 2)
    await asyncio.sleep(0.02)
    assert limiter.inflight == 2
    hold.set()
    await asyncio.gather(h1, h2)
    assert limiter.inflight == 0 and limiter._value == 2


# ============================================================================ 8. 列表 quote 证据去重展开与毫秒级检索性能
def test_list_field_quote_evidence_dedup_and_perf():
    tpl = Template(
        definition=TemplateDef(
            id=9008,
            name="列表高性能核验模板",
            fields=[
                FieldDef(
                    name="充值流水",
                    type="list",
                    evidence="quote",
                    columns=[
                        ColumnDef(name="流水号"),
                        ColumnDef(name="短信摘要"),
                        ColumnDef(name="金额"),
                        ColumnDef(name="自动续订"),
                    ],
                )
            ],
        ),
        body="{% for r in 充值流水 %}{{r.流水号}}{% endfor %}",
    )
    ws = Workspace()
    records = [
        {
            "serial_no": f"ORD202611{i:04d}",
            "sms_body": f"尊敬的客户，您于2026年11月  \n\t  办理第 {i} 笔咪咕定向流量包，扣费成功。",
            "fee_yuan": f"{10 + i}.00",
            "auto_renew": True if i % 2 == 0 else False,
            "extra_col_1": f"渠道扩展信息-{i}-掌上营业厅办理记录详情",
            "extra_col_2": f"备注说明-{i}-无异常退费记录",
        }
        for i in range(50)
    ]
    ws.results["r1"] = ApiResult(
        result_id="r1",
        api="qryPayLog",
        title="充值记录查询",
        args={},
        ok=True,
        columns=list(records[0].keys()),
        records=records,
        error=None,
        cost_ms=1,
    )

    rows = [
        {
            "流水号": f"ORD202611{i:04d}",
            # 触发空白折叠子串匹配
            "短信摘要": f"2026年11月 办理第 {i} 笔咪咕定向流量包",
            # 触发 Decimal 数值等价（"10" vs "10.00"）
            "金额": str(10 + i),
            # 触发 bool 大小写兼容等价（"true"/"false" vs True/False）
            "自动续订": "true" if i % 2 == 0 else "false",
        }
        for i in range(50)
    ]
    # 150 条 api 证据（每行被多列重复引用 3 次）
    evidence = [
        {"type": "api", "resultId": "r1", "row": i % 50, "column": col}
        for col in ("serial_no", "sms_body", "fee_yuan")
        for i in range(50)
    ]
    report_ok = {"充值流水": {"status": "found", "value": rows, "evidence": evidence, "reasoning": ""}}
    checker = EvidenceChecker(tpl, {}, "", ws)

    # 预热一次后测 5 次中位耗时，验证 < 2ms 级别（留 CI 抖动余量断言 < 5ms）
    assert checker.check(report_ok) == []
    timings_ms: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        assert checker.check(report_ok) == []
        timings_ms.append((time.perf_counter() - t0) * 1000.0)
    assert statistics.median(timings_ms) < 5.0

    # 篡改单格无出处文本必须精准拦截
    bad_rows = [dict(r) for r in rows]
    bad_rows[49]["短信摘要"] = "不存在的伪造短信摘要"
    report_bad = {"充值流水": {"status": "found", "value": bad_rows, "evidence": evidence, "reasoning": ""}}
    errs = checker.check(report_bad)
    assert len(errs) == 1 and "第 50 行" in errs[0].message
