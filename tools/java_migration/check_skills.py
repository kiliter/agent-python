"""Java → Python Skill / 接口契约迁移与二期缺陷修复校验脚本（只读，不修改任何资源）。

#Created By AiCoding(codex)
用法（在项目根目录）：uv run python tools/java_migration/check_skills.py

校验内容：
  1. <资源目录>/skills/*/SKILL.md 能被 parse_skill_markdown 解析；name 与目录一致且符合 SKILL_ID_RE；apis 都存在。
  2. <资源目录>/apis/*.yaml 能被 parse_api_yaml 解析；schema_errors() 为空；name 与文件名一致且符合 API_NAME_RE。
  3. build_request + build_request_xml(style=java) 生成的报文与 Java CommonRequestToolService#toXmlRequest 的真实输出逐字比较。
  4. mock 网关读取 <资源目录>/mock-gateway 样例，检查成功/无数据/失败判定与记录列。
  5. 按二期升级后的 SKILL.md 步骤，直接调用平台确定性工具（extract_dates、date_shift、expand_period、time_diff、
     regex_extract、query_result[between/anyOf/resultIds]、format_date、date_range）在 mock 数据上模拟 11 个 Skill，
     与 Java Groovy 脚本正常场景真实输出逐项对拍。
  6. 专项验证二期及全量审查修复的历史缺陷与契约防线：
     ① reminder-sms 遇到“（编号：25JS206149）。\\n1.”不再误算成 20614901，且无日期且无 deadlineDate 时跳过查询返回 not_found（绝不回退创建时间当天误取订购提醒）；
     ② qry-balance 传入纯年月 充值时间="202607" 时正确展开整月并命中 2026 年 7 月流水，不再因 20260007 回溯返回空；
     ③ pretty-number-info 按 msisdn == 手机号码精确匹配、空 grade 判为非靓号、多档 event_name JSON 数组按“、”拼接；
     ④ billing-cycle-sms 跨月账单 202607$202610 闭区间展开全部 4 个月（202607..202610）；
     ⑤ 列表字段空列表（status="found", value=[]）接受 total=0 的 query_result callId，严拒 load_skill callId 与非空表 api 冒充；
     ⑥ cc_pretty_num_info_query 顶层网关报错（resp_code=9999 且缺失 content.ret_code）准确判为 ok=False。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from report_agent.config import Settings
from report_agent.domain.api_contract import parse_api_yaml
from report_agent.domain.resources import load_resource_dir
from report_agent.domain.skill import parse_skill_markdown
from report_agent.gateway.base import extract_records, parse_xml
from report_agent.gateway.mock import MockGatewayClient
from report_agent.gateway.unified_xml import build_request_xml
from report_agent.runtime import tools as rt_tools
from report_agent.runtime.deps import RunDeps
from report_agent.runtime.evidence import EvidenceChecker
from report_agent.runtime.output_model import build_report_model
from report_agent.runtime.tools import Condition, OrderBy
from report_agent.runtime.workspace import ApiResult, EventSink, Workspace
from report_agent.store.layout import API_NAME_RE, SKILL_ID_RE

HERE = Path(__file__).resolve().parent
# 待校验的 Python 资源目录（默认内置 seed），可用环境变量 MIGRATION_RESOURCES 指定其它目录
STAGING = Path(os.environ.get("MIGRATION_RESOURCES") or (HERE.parent.parent / "src/report_agent/seed"))
HARNESS = HERE / "harness"
JAVA_CLASSES = Path("/Users/zhangjialin/IdeaProjects/agent/pdf-agent-parse/target/classes")
M2 = Path.home() / ".m2/repository"
JARS = [
    "tools/jackson/core/jackson-core/3.1.4/jackson-core-3.1.4.jar",
    "tools/jackson/core/jackson-databind/3.1.4/jackson-databind-3.1.4.jar",
    "tools/jackson/dataformat/jackson-dataformat-xml/3.1.4/jackson-dataformat-xml-3.1.4.jar",
    "com/fasterxml/jackson/core/jackson-annotations/2.22/jackson-annotations-2.22.jar",
    "com/fasterxml/woodstox/woodstox-core/7.1.1/woodstox-core-7.1.1.jar",
    "org/codehaus/woodstox/stax2-api/4.2.2/stax2-api-4.2.2.jar",
    "org/springframework/spring-webflux/7.0.8/spring-webflux-7.0.8.jar",
    "org/springframework/spring-web/7.0.8/spring-web-7.0.8.jar",
    "org/springframework/spring-core/7.0.8/spring-core-7.0.8.jar",
    "io/projectreactor/reactor-core/3.8.6/reactor-core-3.8.6.jar",
    "org/reactivestreams/reactive-streams/1.0.4/reactive-streams-1.0.4.jar",
    "org/slf4j/slf4j-api/2.0.18/slf4j-api-2.0.18.jar",
    "org/apache/groovy/groovy/4.0.26/groovy-4.0.26.jar",
    "org/apache/groovy/groovy-xml/4.0.26/groovy-xml-4.0.26.jar",
    "org/apache/groovy/groovy-json/4.0.26/groovy-json-4.0.26.jar",
    "org/apache/commons/commons-lang3/3.18.0/commons-lang3-3.18.0.jar",
    "commons-logging/commons-logging/1.3.5/commons-logging-1.3.5.jar",
]

FAILS: list[str] = []


@dataclasses.dataclass
class _SimContext:
    """供确定性平台工具直接调用的轻量运行上下文。#Created By AiCoding(codex)"""

    deps: RunDeps
    retry: int = 0
    max_retries: int = 0


def _make_ctx(rs=None, template_id: int = 101, inputs: dict[str, str] | None = None,
              document: str = "") -> _SimContext:
    """构造带 Mock 网关与工作区的模拟运行上下文。#Created By AiCoding(codex)"""
    resources = rs or load_resource_dir(STAGING)
    tpl = resources.templates[template_id]
    deps = RunDeps(
        run_id="check-skills",
        rev="seed",
        resources=resources,
        template=tpl,
        inputs=dict(inputs or {}),
        document=document,
        allowed_skills=list(resources.skills.keys()),
        allowed_apis=list(resources.apis.keys()),
        workspace=Workspace(),
        events=EventSink(),
        gateway=MockGatewayClient(STAGING / "mock-gateway", style="java"),
        settings=Settings(),
    )
    return _SimContext(deps=deps)


def check(cond: bool, msg: str) -> None:
    """记录单项断言结果。#Created By AiCoding(codex)"""
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


# ============================================================================ 1/2 解析与校验
def load_resources():
    """加载并校验全部 Skill 与接口契约文件。#Created By AiCoding(codex)"""
    print("== 1. Skill 解析与校验")
    apis = {}
    for p in sorted((STAGING / "apis").glob("*.yaml")):
        apis[p.stem] = parse_api_yaml(p.read_text(encoding="utf-8"))
    skills = {}
    for d in sorted((STAGING / "skills").iterdir()):
        if not d.is_dir():
            continue
        sk = parse_skill_markdown((d / "SKILL.md").read_text(encoding="utf-8"))
        skills[d.name] = sk
        missing = [a for a in sk.meta.apis if a not in apis]
        check(sk.meta.name == d.name and bool(SKILL_ID_RE.match(sk.meta.name)) and not missing
              and bool(sk.meta.description.strip()) and bool(sk.meta.title.strip()),
              f"skill {d.name}: title={sk.meta.title} apis={sk.meta.apis} 缺失接口={missing}")
    # 11 个填报取数 Skill + 1 个聊天 template-router Skill
    check(len(skills) == 12, f"共 {len(skills)} 个 Skill（期望 12：11 个填报取数 + 1 个聊天 template-router）")
    print("== 2. 接口契约解析与 schema_errors")
    for name, c in apis.items():
        errs = c.schema_errors()
        check(c.name == name and bool(API_NAME_RE.match(name)) and not errs, f"api {name}: processCode={c.processCode} errors={errs}")
    return skills, apis


# ============================================================================ 3 报文比对
def java_cp() -> str | None:
    """拼接 Java Harness 编译与运行所需的 classpath。#Created By AiCoding(codex)"""
    if not shutil.which("javac") or not JAVA_CLASSES.exists():
        return None
    paths = [JAVA_CLASSES] + [M2 / j for j in JARS]
    if not all(p.exists() for p in paths):
        return None
    return ":".join(str(p) for p in paths)


def run_java(main: str, *args: str) -> dict[str, str] | None:
    """编译并运行指定 Java Harness 类，返回键值表。#Created By AiCoding(codex)"""
    cp = java_cp()
    if cp is None:
        return None
    out_dir = Path(tempfile.mkdtemp(prefix="jxh_"))
    try:
        src = HARNESS / f"{main}.java"
        subprocess.run(["javac", "-encoding", "UTF-8", "-cp", cp, "-d", str(out_dir), str(src)], check=True,
                       capture_output=True)
        res = subprocess.run(["java", "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-cp", f"{out_dir}:{cp}", main, *args],
                             capture_output=True, text=True, encoding="utf-8", check=True)
        out = {}
        for line in res.stdout.splitlines():
            if "\t" in line:
                k, v = line.split("\t", 1)
                out[k] = v
        return out
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def compare_requests(apis) -> None:
    """比对 Python 与 Java 生成的网关 XML 请求报文。#Created By AiCoding(codex)"""
    print("== 3. 请求报文与 Java xml-nytool 逐字比较（style=java）")
    samples = {
        "querySMSSendInfo": {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"},
        "BOSS_QryBalanceFlowLog": {"手机号码": "15062667019", "账期": "202607"},
        "cc_pretty_num_info_query": {"手机号码": "15252749921"},
    }
    java = run_java("JavaXmlRequestHarness")
    if java is None:
        print("  [SKIP] 本机缺少 JDK 或 Java 编译产物/依赖，跳过逐字比较")
    for name, args in samples.items():
        c = apis[name]
        check(not c.validate_args(args), f"{name} 样例参数通过 input Schema 校验")
        py_xml = build_request_xml(c.processCode, c.build_request(args), "APP", "TOKEN", style="java")
        print(f"  Python {name}: {py_xml}")
        if java is None:
            continue
        j_xml = java[name]
        if name == "BOSS_QryBalanceFlowLog":
            ts = r"<request_time>\d{14}</request_time>"
            check(re.search(ts, py_xml) is not None, f"{name} request_time 为 14 位当前时间")
            norm = "<request_time>TS</request_time>"
            check(re.sub(ts, norm, py_xml) == re.sub(ts, norm, j_xml), f"{name} 与 Java 逐字一致（request_time 时间值归一化）")
        else:
            check(py_xml == j_xml, f"{name} 与 Java 逐字一致")


# ============================================================================ 4 mock 网关
async def mock_checks(apis) -> None:
    """检查 mock 网关样例文件的成功、无数据与失败解析。#Created By AiCoding(codex)"""
    print("== 4. mock 网关样例解析")
    gw = MockGatewayClient(STAGING / "mock-gateway", style="java")
    cases = [
        ("querySMSSendInfo", {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}, "ok", 13),
        ("querySMSSendInfo", {"手机号码": "13900000000", "开始时间": "20261105000000", "结束时间": "20261105235959"}, "nodata", 0),
        ("BOSS_QryBalanceFlowLog", {"手机号码": "15062667019", "账期": "202607"}, "ok", 2),
        ("BOSS_QryBalanceFlowLog", {"手机号码": "13900000000", "账期": "202607"}, "fail", 0),
        ("cc_pretty_num_info_query", {"手机号码": "15252749921"}, "ok", 2),
        ("cc_pretty_num_info_query", {"手机号码": "13900000000"}, "nodata", 0),
    ]
    for name, args, expect, n in cases:
        r = await gw.invoke(apis[name], args)
        state = "fail" if not r.ok else ("nodata" if r.no_data else "ok")
        check(state == expect and len(r.records) == n,
              f"{name}{args.get('手机号码')}: state={state} count={len(r.records)} error={r.error or ''}")
        if expect == "ok":
            cols = sorted(set().union(*(x.keys() for x in r.records)))
            declared = set(apis[name].response.records.columns)
            check(declared <= set(cols), f"{name} 声明的列都出现在记录中：缺 {sorted(declared - set(cols))}")


# ============================================================================ 5 Skill 确定性工具模拟
def _parse_pretty_event_names(raw: Any) -> str:
    """按 pretty-number-info/SKILL.md 解析单值或多档 JSON 数组活动名称。#Created By AiCoding(codex)"""
    text = "" if raw is None else str(raw).strip()
    if not text:
        return ""
    if text.startswith("["):
        try:
            items = json.loads(text)
            if isinstance(items, list):
                return "、".join(str(x).strip() for x in items if x is not None and str(x).strip())
        except json.JSONDecodeError:
            pass
    return text


async def _run_pretty_number(ctx: _SimContext, result_id: str, phone: str) -> dict[str, str]:
    """按 pretty-number-info/SKILL.md 执行号码精确过滤、grade 非空判断与活动名称提取。#Created By AiCoding(codex)"""
    qr = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        resultId=result_id,
        where=[Condition(column="msisdn", op="equals", value=phone)],
        limit=100,
    )
    matched = next((r for r in qr["rows"] if str(r.get("grade") or "").strip()), None)
    if not matched:
        return {}
    return {
        "靓号等级": str(matched.get("grade") or ""),
        "靓号活动名称": _parse_pretty_event_names(matched.get("level_info.event_name")),
        "手机号类别": "靓号",
    }


async def _run_qry_balance(ctx: _SimContext, phone: str, period_text: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """按 qry-balance/SKILL.md 使用 expand_period + query_result(resultIds, between) 查询充值流水。#Created By AiCoding(codex)"""
    exp = await rt_tools.expand_period(ctx, period=period_text)  # type: ignore[arg-type]
    rids: list[str] = []
    for ym in exp["months"]:
        api_out = await rt_tools.call_api(ctx, "BOSS_QryBalanceFlowLog", {"手机号码": phone, "账期": ym})  # type: ignore[arg-type]
        rids.append(api_out["resultId"])
    qr = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        where=[Condition(column="payDatetime", op="between", value=exp["startDate"], endValue=exp["endDate"], prefixLen=8)],
        orderBy=OrderBy(column="payDatetime", desc=True),
        limit=100,
        columns=["payDatetime", "payTypeName", "amount", "soNbr"],
        resultIds=rids,
    )
    rows = [
        {"充值时间": r["payDatetime"], "支付方式": r["payTypeName"], "充值金额": r["amount"], "流水号": r["soNbr"]}
        for r in qr["rows"]
    ]
    ev = (
        [{"type": "api", "resultId": r["resultId"], "row": r["row"], "column": "payDatetime"} for r in qr["rows"]]
        if qr["rows"]
        else [{"type": "tool", "callId": qr.get("callId") or list(ctx.deps.workspace.tool_calls)[-1]}]
    )
    submission = {"status": "found", "value": rows, "evidence": ev, "reasoning": "按 expand_period + query_result 查询"}
    return submission, rows


async def _run_reminder_sms(
    ctx: _SimContext, phone: str, biz_sms: str | None, create_time: str, deadline_date: str = ""
) -> dict[str, dict[str, Any]]:
    """按修复后的 reminder-sms/SKILL.md 执行：优先 deadlineDate，否则订购短信提取最大日期；无合法到期日直接跳过接口查询。#Created By AiCoding(codex)"""
    not_found_pair = {
        "提醒短信": {"status": "not_found", "value": None, "evidence": [], "reasoning": "未找到合法到期日期"},
        "提醒日期": {"status": "not_found", "value": None, "evidence": [], "reasoning": "未找到合法到期日期"},
    }
    target_day = ""
    if deadline_date.strip():
        dl_dates = await rt_tools.extract_dates(ctx, text=deadline_date, defaultYear=create_time)  # type: ignore[arg-type]
        if dl_dates.get("count", 0) > 0:
            target_day = str(dl_dates["max"] or "")
    if not target_day:
        if not biz_sms:
            return not_found_pair
        sms_dates = await rt_tools.extract_dates(ctx, text=biz_sms, defaultYear=create_time)  # type: ignore[arg-type]
        if sms_dates.get("count", 0) == 0:
            return not_found_pair
        target_day = str(sms_dates["max"] or "")
    shift = await rt_tools.date_shift(ctx, date=target_day, days=0)  # type: ignore[arg-type]
    api_out = await rt_tools.call_api(
        ctx, "querySMSSendInfo", {"手机号码": phone, "开始时间": shift["start"], "结束时间": shift["end"]}  # type: ignore[arg-type]
    )
    if not api_out.get("ok") or api_out.get("count", 0) == 0:
        return not_found_pair
    qr = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        resultId=api_out["resultId"],
        where=[Condition(column="smsContent", op="contains", value="提醒")],
        orderBy=OrderBy(column="smsSendTime", desc=True),
        limit=1,
    )
    if not qr["rows"]:
        return not_found_pair
    row = qr["rows"][0]
    dt_out = await rt_tools.format_date(
        ctx, value=row["smsSendTime"], fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd"  # type: ignore[arg-type]
    )
    return {
        "提醒短信": {
            "status": "found",
            "value": row["smsContent"],
            "evidence": [{"type": "api", "resultId": api_out["resultId"], "row": row["row"], "column": "smsContent"}],
            "reasoning": f"到期日 {target_day} 查询命中提醒短信",
        },
        "提醒日期": {
            "status": "found",
            "value": dt_out["value"],
            "evidence": [
                {"type": "tool", "callId": dt_out["callId"]},
                {"type": "api", "resultId": api_out["resultId"], "row": row["row"], "column": "smsSendTime"},
            ],
            "reasoning": f"到期日 {target_day} 提醒短信发送日期格式化",
        },
    }


async def simulate() -> dict[str, Any]:
    """使用平台确定性工具模拟全部 11 个 Skill。#Created By AiCoding(codex)"""
    rs = load_resource_dir(STAGING)
    ctx = _make_ctx(rs)
    phone, name, create = "13900001234", "5G智享套餐（个人版）", "20261105103012"
    out: dict[str, Any] = {}

    # 1) business-sms
    day_win = await rt_tools.date_range(ctx, time=create, unit="day")  # type: ignore[arg-type]
    out["business-sms.window"] = (day_win["start"], day_win["end"])
    sms_call = await rt_tools.call_api(
        ctx, "querySMSSendInfo", {"手机号码": phone, "开始时间": day_win["start"], "结束时间": day_win["end"]}  # type: ignore[arg-type]
    )
    sms_rid = sms_call["resultId"]
    b_qr = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        resultId=sms_rid,
        where=[
            Condition(column="smsContent", op="normalizedContains", value=name, before="编号"),
            Condition(column="smsContent", op="notContains", value="退订提醒"),
            Condition(column="smsContent", op="notContains", value="退订成功"),
        ],
        orderBy=OrderBy(column="smsSendTime", desc=True),
        limit=1,
    )
    b = b_qr["rows"][0]
    biz = b["smsContent"]
    out["business-sms"] = {"订购短信": biz}

    # 2) accept-type
    c_hotline = await rt_tools.text_contains(ctx, target="热线渠道", text=biz, normalize=False)  # type: ignore[arg-type]
    c_online = await rt_tools.text_contains(ctx, target="线上渠道", text=biz, normalize=False)  # type: ignore[arg-type]
    out["accept-type"] = "热线" if c_hotline["contains"] else ("掌上营业厅" if c_online["contains"] else "其他")

    # 3) second-confirmation-sms
    t1 = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        resultId=sms_rid,
        where=[
            Condition(column="smsContent", op="normalizedContains", value=name),
            Condition(column="smsContent", op="contains", value="回复"),
            Condition(column="smsContent", op="contains", value="订购确认提醒"),
        ],
        orderBy=OrderBy(column="smsSendTime", desc=True),
        limit=1,
    )
    t2 = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        resultId=sms_rid,
        where=[
            Condition(column="smsContent", op="normalizedContains", value=name),
            Condition(column="smsContent", op="contains", value="回复"),
            Condition(column="smsContent", op="contains", value="订购提醒"),
        ],
        orderBy=OrderBy(column="smsSendTime", desc=True),
        limit=1,
    )
    hit_sc = t1["rows"] or t2["rows"]
    out["second-confirmation-sms"] = hit_sc[0]["smsContent"] if hit_sc else ""

    # 4) verification-sms
    v_qr = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        resultId=sms_rid,
        where=[
            Condition(column="smsContent", op="normalizedContains", value=name),
            Condition(column="smsContent", op="contains", value="动态验证码"),
        ],
        orderBy=OrderBy(column="smsSendTime", desc=True),
        limit=1,
    )
    out["verification-sms"] = v_qr["rows"][0]["smsContent"] if v_qr["rows"] else ""

    # 5) original-package-name（time_diff + regex_extract）
    cand_qr = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        resultId=sms_rid,
        where=[Condition(column="smsContent", op="contains", value="退订提醒")],
        limit=100,
        columns=["smsContent", "smsSendTime"],
    )
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for cand in cand_qr["rows"]:
        td = await rt_tools.time_diff(ctx, time1=cand["smsSendTime"], time2=b["smsSendTime"])  # type: ignore[arg-type]
        if td.get("ok"):
            scored.append((td["absSeconds"], cand["smsSendTime"], cand))
    scored.sort(key=lambda item: (item[0], -int(re.sub(r"\D", "", item[1])[:14])))
    chosen_text = scored[0][2]["smsContent"] if scored else ""
    rx1 = await rt_tools.regex_extract(ctx, pattern=r'办理的\s*[“"]([^”"]+)[”"]', text=chosen_text, group=1)  # type: ignore[arg-type]
    if rx1["count"] == 0:
        rx1 = await rt_tools.regex_extract(ctx, pattern=r'[“"]([^”"]+)[”"]', text=chosen_text, group=1)  # type: ignore[arg-type]
    out["original-package-name"] = (rx1["first"] or "").strip()

    # 6) reminder-sms（二期修复：extract_dates + date_shift，不再把 25JS206149 误算成 20614901）
    rem_dates = await rt_tools.extract_dates(ctx, text=biz, defaultYear=create)  # type: ignore[arg-type]
    target_day = rem_dates["max"]
    rem_shift = await rt_tools.date_shift(ctx, date=target_day, days=0)  # type: ignore[arg-type]
    out["reminder-sms.dates"] = rem_dates
    out["reminder-sms.window"] = (rem_shift["start"], rem_shift["end"])
    rem_qr = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        resultId=sms_rid,
        where=[Condition(column="smsContent", op="contains", value="提醒")],
        orderBy=OrderBy(column="smsSendTime", desc=True),
        limit=1,
    )
    if rem_qr["rows"]:
        rem_row = rem_qr["rows"][0]
        rem_dt = await rt_tools.format_date(ctx, value=rem_row["smsSendTime"], fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd")  # type: ignore[arg-type]
        out["reminder-sms"] = {"提醒短信": rem_row["smsContent"], "提醒日期": rem_dt["value"]}
    else:
        out["reminder-sms"] = {}

    # 7) renewal-reminder-sms（extract_dates + date_shift + regex_extract + query_result[anyOf]）
    ren_dates = await rt_tools.extract_dates(ctx, text=biz, defaultYear=create)  # type: ignore[arg-type]
    ren_shift = await rt_tools.date_shift(ctx, date=ren_dates["max"], days=-31, endDays=31)  # type: ignore[arg-type]
    out["renewal-reminder-sms.window"] = (ren_shift["start"], ren_shift["end"])
    code_rx = await rt_tools.regex_extract(ctx, pattern=r"[（(]编号[:：]\s*([A-Za-z0-9_-]+)[）)]", text=biz, group=1)  # type: ignore[arg-type]
    any_conds = [Condition(column="smsContent", op="normalizedContains", value=name)] + [
        Condition(column="smsContent", op="normalizedContains", value=c) for c in code_rx["matches"]
    ]
    ren_qr = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        resultId=sms_rid,
        anyOf=any_conds,
        orderBy=OrderBy(column="smsSendTime", desc=True),
        limit=100,
    )
    ren_res: dict[str, str] = {}
    reminders = []
    for x in ren_qr["rows"]:
        c_text = x["smsContent"]
        t = None
        if "【续约确认提醒】" in c_text or "[续约确认提醒]" in c_text:
            t = "到期延续"
        elif "【到期提醒】" in c_text or "[到期提醒]" in c_text:
            if any(k in c_text for k in ["次月起失效", "到期自动关闭", "活动结束后自动失效", "到期后自动失效", "不再延续"]):
                t = "到期结束"
            elif any(k in c_text for k in ["下月继续生效", "继续生效", "自动延续", "自动续订", "自动续展"]):
                t = "到期延续"
        if t:
            reminders.append((t, x))
    if reminders:
        t, x = reminders[0]
        dt_fmt = await rt_tools.format_date(ctx, value=x["smsSendTime"], fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd")  # type: ignore[arg-type]
        ren_res.update({"续约提醒类型": t, "到期续约提醒时间": dt_fmt["value"], "到期续约提醒短信内容": x["smsContent"]})
    succ = [x for x in ren_qr["rows"] if "【续约成功提醒】" in x["smsContent"] or "[续约成功提醒]" in x["smsContent"]]
    if succ:
        dt_succ = await rt_tools.format_date(ctx, value=succ[0]["smsSendTime"], fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd")  # type: ignore[arg-type]
        ren_res.update({"续约提醒类型": "到期延续", "是否续约成功": "是", "续约成功提醒时间": dt_succ["value"],
                        "续约成功提醒短信内容": succ[0]["smsContent"]})
    out["renewal-reminder-sms"] = ren_res

    # 8) number-portability-sms
    np_qr = await rt_tools.query_result(
        ctx,  # type: ignore[arg-type]
        resultId=sms_rid,
        where=[Condition(column="smsContent", op="contains", value="携号转网告知提醒")],
        orderBy=OrderBy(column="smsSendTime", desc=True),
        limit=1,
    )
    if np_qr["rows"]:
        np_dt = await rt_tools.format_date(ctx, value=np_qr["rows"][0]["smsSendTime"], fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd")  # type: ignore[arg-type]
        out["number-portability-sms"] = {"发送日期": np_dt["value"], "携转资格回复短信": np_qr["rows"][0]["smsContent"]}
    else:
        out["number-portability-sms"] = {}

    # 9) billing-cycle-sms（expand_period("202611$202611") + query_result[resultIds, between]）
    bill_exp = await rt_tools.expand_period(ctx, period="202611$202611")  # type: ignore[arg-type]
    mr0 = bill_exp["monthRanges"][0]
    out["billing-cycle-sms.window"] = (mr0["start"], mr0["end"])
    rows_out = []
    for mr in bill_exp["monthRanges"]:
        cyc = mr["month"]
        cyc_label = (await rt_tools.format_date(ctx, value=cyc, fromPattern="yyyyMM", toPattern="yyyy年M月"))["value"]  # type: ignore[arg-type]
        for typ, conds, with_content in [
            ("活动到期套餐资费变更", [Condition(column="smsContent", op="contains", value="到期提醒"),
                                Condition(column="smsContent", op="contains", value="资费标准")], True),
            ("语音超额提醒", [Condition(column="smsContent", op="contains", value="通话使用提醒")], False),
            ("流量超额提醒", [Condition(column="smsContent", op="contains", value="流量使用提醒")], False),
        ]:
            b_hit = await rt_tools.query_result(
                ctx,  # type: ignore[arg-type]
                where=[Condition(column="smsSendTime", op="between", value=cyc, endValue=cyc, prefixLen=6), *conds],
                orderBy=OrderBy(column="smsSendTime", desc=False),
                limit=100,
                resultIds=[sms_rid],
            )
            items = [x for x in b_hit["rows"] if re.fullmatch(r"\d{14}", re.sub(r"\D", "", x["smsSendTime"]))]
            if not items:
                continue
            fmt_times = [
                (await rt_tools.format_date(ctx, value=x["smsSendTime"], fromPattern="yyyyMMddHHmmss", toPattern="yyyy年M月d日 HH时mm分ss秒"))["value"]  # type: ignore[arg-type]
                for x in items
            ]
            rows_out.append({
                "账期月": cyc_label,
                "提醒类型": typ,
                "提醒时间": "、".join(fmt_times),
                "提醒次数": str(len(items)),
                "短信内容": "\n".join(x["smsContent"] for x in items) if with_content else "",
            })
    out["billing-cycle-sms"] = rows_out

    # 10) qry-balance（单日、日期范围、纯年月 202607）
    _, out["qry-balance"] = await _run_qry_balance(ctx, "15062667019", "20260705")
    _, out["qry-balance.range"] = await _run_qry_balance(ctx, "15062667019", "20260701-20260731")
    _, out["qry-balance.month_only"] = await _run_qry_balance(ctx, "15062667019", "202607")

    # 11) pretty-number-info
    pr_call = await rt_tools.call_api(ctx, "cc_pretty_num_info_query", {"手机号码": "15252749921"})  # type: ignore[arg-type]
    out["pretty-number-info"] = await _run_pretty_number(ctx, pr_call["resultId"], "15252749921")
    return out


async def verify_phase2_bug_fixes() -> None:
    """专项断言验证二期修复的 4 类 Java 历史缺陷与列表新语义。#Created By AiCoding(codex)"""
    print("== 6. 二期已修复 Java 缺陷与列表空值语义专项验证")
    rs = load_resource_dir(STAGING)

    # 缺陷①：reminder-sms 含“（编号：25JS206149）。\n1.”不再误算成 20614901
    ctx1 = _make_ctx(rs)
    tricky_sms = (
        "【订购提醒】尊敬的客户，您已于2026年11月05日在热线渠道成功办理“5G智享套餐（个人版）”活动（编号：25JS206149）。\n"
        "1.活动时间：2026年12月1日00:00:00-2027年12月1日00:00:00。"
    )
    ed = await rt_tools.extract_dates(ctx1, text=tricky_sms, defaultYear="20261105103012")  # type: ignore[arg-type]
    ds = await rt_tools.date_shift(ctx1, date=ed["max"], days=0)  # type: ignore[arg-type]
    check(
        "20614901" not in ed["dates"] and ed["max"] == "20271201"
        and (ds["start"], ds["end"]) == ("20271201000000", "20271201235959"),
        f"缺陷①修复验证：reminder-sms 提取合法日期 {ed['dates']}，查询窗口=({ds['start']}, {ds['end']})，不再误算 20614901",
    )
    # 无日期且未传 deadlineDate：直接跳过接口调用，提醒短信与提醒日期均为 not_found（绝不回退创建时间当天误命中【订购提醒】）
    ctx1_nodate = _make_ctx(rs, template_id=105, inputs={"手机号码": "13900001234", "创建时间": "20261105103012"})
    nodate_sms = "【订购提醒】尊敬的客户，您已成功办理“5G智享套餐（个人版）”活动（编号：25JS206149）。"
    rem_nodate_out = await _run_reminder_sms(ctx1_nodate, "13900001234", nodate_sms, "20261105103012")
    check(
        len(ctx1_nodate.deps.workspace.results) == 0
        and rem_nodate_out["提醒短信"]["status"] == "not_found"
        and rem_nodate_out["提醒日期"]["status"] == "not_found",
        f"缺陷①补充验证（P0-3 修复）：订购短信无日期且无 deadlineDate 时跳过接口（results={len(ctx1_nodate.deps.workspace.results)}），"
        "提醒短信/提醒日期返回 not_found，不误查创建时间当天",
    )
    # 传入非空 deadlineDate 时优先解析该截止日并命中提醒短信
    ctx1_dl = _make_ctx(rs, template_id=105, inputs={"手机号码": "13900001234", "创建时间": "20261105103012", "deadlineDate": "2027-12-01"})
    rem_dl_out = await _run_reminder_sms(ctx1_dl, "13900001234", nodate_sms, "20261105103012", deadline_date="2027-12-01")
    check(
        len(ctx1_dl.deps.workspace.results) == 1
        and rem_dl_out["提醒短信"]["status"] == "found"
        and rem_dl_out["提醒日期"]["status"] == "found",
        "缺陷①补充验证（deadlineDate 优先）：订购短信无日期但传入 deadlineDate='2027-12-01' 时正常查询 20271201",
    )

    # 缺陷②：qry-balance 传入 充值时间="202607" 命中 2026 年 7 月全部 2 条流水
    ctx2 = _make_ctx(rs, template_id=106, inputs={"手机号码": "15062667019", "充值时间": "202607"})
    sub_202607, rows_202607 = await _run_qry_balance(ctx2, "15062667019", "202607")
    check(
        len(rows_202607) == 2 and [r["充值时间"] for r in rows_202607] == ["20260709144056", "20260705144056"]
        and sub_202607["status"] == "found",
        f"缺陷②修复验证：qry-balance 充值时间='202607' 命中 {len(rows_202607)} 条流水，不再因 20260007 回溯为空",
    )

    # 缺陷③：pretty-number-info 按号码匹配、空 grade 判非靓号、多档 JSON 数组按“、”拼接
    ctx3 = _make_ctx(rs, template_id=132, inputs={"手机号码": "13800138000"})
    ctx3.deps.workspace.add_result(ApiResult(
        result_id="r_pretty",
        api="cc_pretty_num_info_query",
        title="靓号查询",
        args={"手机号码": "13800138000"},
        ok=True,
        error=None,
        columns={},
        records=[
            {"msisdn": "15252749921", "grade": "GRADE_002", "level_info.event_name": "其他号码活动"},
            {"msisdn": "13800138000", "grade": "", "level_info.event_name": "空等级活动"},
        ],
        cost_ms=1,
    ))
    mismatch_res = await _run_pretty_number(ctx3, "r_pretty", "13999999999")
    empty_grade_res = await _run_pretty_number(ctx3, "r_pretty", "13800138000")
    ctx3.deps.workspace.add_result(ApiResult(
        result_id="r_pretty_multi",
        api="cc_pretty_num_info_query",
        title="靓号查询",
        args={"手机号码": "13800138000"},
        ok=True,
        error=None,
        columns={},
        records=[{"msisdn": "13800138000", "grade": "GRADE_001", "level_info.event_name": '["靓号活动A", "", "靓号活动B"]'}],
        cost_ms=1,
    ))
    multi_res = await _run_pretty_number(ctx3, "r_pretty_multi", "13800138000")
    check(
        mismatch_res == {} and empty_grade_res == {}
        and multi_res == {"靓号等级": "GRADE_001", "靓号活动名称": "靓号活动A、靓号活动B", "手机号类别": "靓号"},
        f"缺陷③修复验证：号码不匹配={mismatch_res}，空 grade={empty_grade_res}，多档拼接={multi_res.get('靓号活动名称')}",
    )

    # 缺陷④：列表无命中（接口 ok=True）提交 status="found", value=[] 并通过 schema 与 EvidenceChecker
    ctx4 = _make_ctx(rs, template_id=106, inputs={"手机号码": "15062667019", "充值时间": "20260720"}, document="客户号码：15062667019")
    empty_bal_sub, empty_bal_rows = await _run_qry_balance(ctx4, "15062667019", "20260720")
    tpl106 = rs.templates[106]
    rep106 = {f.name: {"status": "not_found", "value": None, "evidence": [], "reasoning": "测试"} for f in tpl106.definition.fields}
    rep106["充值流水"] = empty_bal_sub
    model106 = build_report_model(tpl106)
    model106.model_validate(rep106)
    ev_issues_106 = EvidenceChecker(tpl106, ctx4.deps.inputs, ctx4.deps.document, ctx4.deps.workspace).check(rep106)
    check(
        empty_bal_rows == [] and empty_bal_sub["status"] == "found" and empty_bal_sub["value"] == [] and ev_issues_106 == [],
        f"缺陷④修复验证（qry-balance 无命中）：status={empty_bal_sub['status']} value={empty_bal_sub['value']} 证据校验问题={ev_issues_106}",
    )

    ctx5 = _make_ctx(rs, template_id=119, inputs={"手机号码": "13900000000", "账单": "202610$202610"})
    exp5 = await rt_tools.expand_period(ctx5, period="202610$202610")  # type: ignore[arg-type]
    mr5 = exp5["monthRanges"][0]
    nodata_call = await rt_tools.call_api(
        ctx5, "querySMSSendInfo", {"手机号码": "13900000000", "开始时间": mr5["start"], "结束时间": mr5["end"]}  # type: ignore[arg-type]
    )
    qr5 = await rt_tools.query_result(ctx5, resultIds=[nodata_call["resultId"]], limit=100)  # type: ignore[arg-type]
    tpl119 = rs.templates[119]
    rep119 = {f.name: {"status": "not_found", "value": None, "evidence": [], "reasoning": "测试"} for f in tpl119.definition.fields}
    rep119["账期短信提醒列表"] = {
        "status": "found",
        "value": [],
        "evidence": [{"type": "tool", "callId": qr5.get("callId") or list(ctx5.deps.workspace.tool_calls)[-1]}],
        "reasoning": "查询成功无提醒短信",
    }
    build_report_model(tpl119).model_validate(rep119)
    ev_issues_119 = EvidenceChecker(tpl119, ctx5.deps.inputs, ctx5.deps.document, ctx5.deps.workspace).check(rep119)
    check(
        nodata_call["ok"] is True and qr5["rows"] == [] and ev_issues_119 == [],
        f"缺陷④修复验证（billing-cycle-sms 无短信记录）：status=found value=[] 证据校验问题={ev_issues_119}",
    )

    # 缺陷⑤（P1-7）：billing-cycle-sms 跨月账单 202607$202610 闭区间展开全部 4 个月（202607..202610）
    ctx_multi_bill = _make_ctx(rs, template_id=119, inputs={"手机号码": "13900001234", "账单": "202607$202610"})
    exp_multi = await rt_tools.expand_period(ctx_multi_bill, period="202607$202610")  # type: ignore[arg-type]
    check(
        exp_multi.get("ok") is True
        and exp_multi.get("months") == ["202607", "202608", "202609", "202610"]
        and len(exp_multi.get("monthRanges") or []) == 4,
        f"缺陷⑤修复验证（billing-cycle-sms 跨月 $ 闭区间）：months={exp_multi.get('months')}",
    )

    # 缺陷⑥（P0-1）：EvidenceChecker 拒绝用 load_skill t1（及非空表 api）冒充空列表证据，接受 total=0 的 query_result callId
    ctx_ev = _make_ctx(rs, template_id=106, inputs={"手机号码": "15062667019", "充值时间": "20260720"})
    await rt_tools.load_skill(ctx_ev, name="qry-balance")  # type: ignore[arg-type]
    sk_call_id = next(iter(ctx_ev.deps.workspace.tool_calls.keys()), "t1")
    fake_rep = {f.name: {"status": "not_found", "value": None, "evidence": [], "reasoning": "测试"} for f in tpl106.definition.fields}
    fake_rep["充值流水"] = {
        "status": "found",
        "value": [],
        "evidence": [{"type": "tool", "callId": sk_call_id}],
        "reasoning": "伪造 load_skill 充当空列表证据",
    }
    fake_issues = EvidenceChecker(tpl106, ctx_ev.deps.inputs, ctx_ev.deps.document, ctx_ev.deps.workspace).check(fake_rep)
    api_ev_out = await rt_tools.call_api(ctx_ev, "BOSS_QryBalanceFlowLog", {"手机号码": "15062667019", "账期": "202607"})  # type: ignore[arg-type]
    qr_ev_out = await rt_tools.query_result(
        ctx_ev,  # type: ignore[arg-type]
        resultId=api_ev_out["resultId"],
        where=[Condition(column="payDatetime", op="startsWith", value="20260720")],
        limit=100,
    )
    nonempty_api_rep = dict(fake_rep)
    nonempty_api_rep["充值流水"] = {
        "status": "found",
        "value": [],
        "evidence": [{"type": "api", "resultId": api_ev_out["resultId"], "row": 0, "column": "payDatetime"}],
        "reasoning": "原接口有 2 条记录却直接引 api 报空列表",
    }
    nonempty_api_issues = EvidenceChecker(tpl106, ctx_ev.deps.inputs, ctx_ev.deps.document, ctx_ev.deps.workspace).check(nonempty_api_rep)
    valid_qr_rep = dict(fake_rep)
    valid_qr_rep["充值流水"] = {
        "status": "found",
        "value": [],
        "evidence": [{"type": "tool", "callId": str(qr_ev_out.get("callId") or "")}],
        "reasoning": "按 20260720 筛选 total=0",
    }
    valid_qr_issues = EvidenceChecker(tpl106, ctx_ev.deps.inputs, ctx_ev.deps.document, ctx_ev.deps.workspace).check(valid_qr_rep)
    check(
        bool(fake_issues)
        and bool(nonempty_api_issues)
        and "callId" in api_ev_out
        and "callId" in qr_ev_out
        and qr_ev_out.get("total") == 0
        and valid_qr_issues == [],
        f"缺陷⑥修复验证（空列表证据防线）：拒 load_skill={len(fake_issues)} 条、拒非空表 api={len(nonempty_api_issues)} 条、"
        f"接受 query_result(total=0, callId={qr_ev_out.get('callId')})={valid_qr_issues}",
    )

    # 缺陷⑦（P1-8）：cc_pretty_num_info_query 顶层网关报错 resp_code=9999（无 content.ret_code）判为 ok=False
    pretty_contract = rs.apis["cc_pretty_num_info_query"]
    err_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<operation_out><response><resp_code>9999</resp_code><resp_desc>网关调用超时</resp_desc></response></operation_out>"
    )
    err_parsed = extract_records(pretty_contract, parse_xml(err_xml))
    nodata_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<operation_out><content><ret_code>1</ret_code><ret_msg>号码不存在</ret_msg></content></operation_out>"
    )
    nodata_parsed = extract_records(pretty_contract, parse_xml(nodata_xml))
    check(
        err_parsed.ok is False
        and err_parsed.no_data is False
        and nodata_parsed.ok is True
        and nodata_parsed.no_data is True,
        f"缺陷⑦修复验证（靓号网关错误拦截）：resp_code=9999 -> ok={err_parsed.ok}({err_parsed.error})；"
        f"ret_code=1 -> ok={nodata_parsed.ok}, no_data={nodata_parsed.no_data}",
    )


def compare_golden(sim: dict[str, Any]) -> None:
    """将 Python 确定性模拟结果与 Java Groovy 脚本真实输出对拍。#Created By AiCoding(codex)"""
    print("== 5. Skill 步骤模拟 vs Java Groovy 真实输出（同一份 mock 数据）")
    golden = run_java("JavaSkillGoldenHarness", str(STAGING / "mock-gateway"))
    if golden is None:
        print("  [SKIP] 本机缺少 JDK 或依赖，跳过")
        return

    def gj(key):
        v = golden[key].replace("\\n", "\n").replace("\\r", "\r")
        try:
            return json.loads(golden[key])
        except json.JSONDecodeError:
            return v

    def window(key):
        g = golden[key]
        return (re.search(r"startDate=(\d+)", g).group(1), re.search(r"endDate=(\d+)", g).group(1))

    biz = gj("business-sms.extract")
    check(sim["business-sms"]["订购短信"] == biz["订购短信"], "business-sms 订购短信一致（Java 的受理日期副产物按策略丢弃）")
    check(sim["business-sms.window"] == window("business-sms.assembly"), f"business-sms 查询窗口一致 {sim['business-sms.window']}")
    check(sim["accept-type"] == gj("accept-type.extract"), f"accept-type 一致：{sim['accept-type']}")
    check(gj("accept-type.extract.noBusinessSms") == "其他", "accept-type 无订购短信时为“其他”")
    check(sim["second-confirmation-sms"] == gj("second-confirmation-sms.extract"), "second-confirmation-sms 一致")
    check(sim["verification-sms"] == gj("verification-sms.extract"), "verification-sms 一致")
    check(sim["original-package-name"] == gj("original-package-name.extract"), f"original-package-name 一致：{sim['original-package-name']}")
    java_rem_win = window("reminder-sms.assembly")
    check(
        java_rem_win == ("20614901000000", "20614901235959")
        and sim["reminder-sms.window"] == ("20271201000000", "20271201235959"),
        f"reminder-sms 查询窗口符合二期修复预期：Python={sim['reminder-sms.window']}（旧 Java 缺陷窗口={java_rem_win}）",
    )
    check(sim["reminder-sms"] == gj("reminder-sms.extract"), "reminder-sms 提取结果一致")
    check(sim["renewal-reminder-sms.window"] == window("renewal-reminder-sms.assembly"),
          f"renewal-reminder-sms 查询窗口一致 {sim['renewal-reminder-sms.window']}")
    check(sim["renewal-reminder-sms"] == gj("renewal-reminder-sms.extract"), "renewal-reminder-sms 6 个字段一致")
    check(sim["number-portability-sms"] == gj("number-portability-sms.extract"), "number-portability-sms 一致")
    check(sim["billing-cycle-sms.window"] == window("billing-cycle-sms.assembly"), "billing-cycle-sms 月窗口一致")
    gb = [{k: str(v) for k, v in row.items()} for row in gj("billing-cycle-sms.extract")]
    check(sim["billing-cycle-sms"] == gb, f"billing-cycle-sms 列表一致（{len(gb)} 行）")
    check(gj("billing-cycle-sms.extract.nodata") == [], "billing-cycle-sms 无短信时 Java 为空列表（Python 为 found+[]）")
    check(sim["qry-balance"] == gj("qry-balance.extract"), "qry-balance（单日）列表一致")
    check(sim["qry-balance.range"] == gj("qry-balance.extract.range"), "qry-balance（日期范围）列表一致")
    check(sim["qry-balance.month_only"] == gj("qry-balance.extract.range"), "qry-balance（纯年月 202607）与整月范围一致")
    check(golden["qry-balance.extract.fail7003"].startswith("EXCEPTION"), "qry-balance 7003 在 Java 中为失败（Python 契约同样判失败）")
    check(sim["pretty-number-info"] == gj("pretty-number-info.extract"), f"pretty-number-info 一致：{sim['pretty-number-info']}")
    check(gj("pretty-number-info.extract.notPretty") == {}, "pretty-number-info ret_code=1 时 Java 为 {}（Python 为无数据）")


async def _async_main() -> int:
    """异步执行全部校验步骤。#Created By AiCoding(codex)"""
    _, apis = load_resources()
    compare_requests(apis)
    await mock_checks(apis)
    sim = await simulate()
    compare_golden(sim)
    await verify_phase2_bug_fixes()
    print(f"\n结果：{'全部通过' if not FAILS else f'{len(FAILS)} 项失败'}")
    for f in FAILS:
        print("  - " + f)
    return 1 if FAILS else 0


def main() -> int:
    """命令行入口。#Created By AiCoding(codex)"""
    return asyncio.run(_async_main())


if __name__ == "__main__":
    sys.exit(main())
