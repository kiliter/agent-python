"""按 example-run 演示脚本行动的假模型（不调用真实大模型）。

#Created By AiCoding(codex)
用于单元测试和本地联调：依次加载 Skill → 计算日期 → 查短信 → 筛选 → 转换日期 →
第一次交卷故意截掉订购短信末尾签名（触发证据校验退回）→ 第二次交卷改正。
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

ORDER_SMS = ("【业务办理成功提醒】尊敬的客户，您已通过热线渠道成功办理5G智享套餐（个人版），129元/月，次月1日生效。"
             "编号：JS2026110500321，业务1：国内通用流量40GB【中国移动心级服务，让爱连接】")
CONFIRM_SMS = ("【订购确认提醒】尊敬的客户，您正在通过热线渠道办理5G智享套餐（个人版），资费129元/月，次月生效。"
               "请在24小时内回复“是”确认办理。【中国移动心级服务，让爱连接】")


def _returns(messages: list[ModelMessage], tool: str) -> list[Any]:
    out = []
    for m in messages:
        for p in getattr(m, "parts", []):
            if isinstance(p, ToolReturnPart) and p.tool_name == tool:
                out.append(p.content)
    return out


def _responses(messages: list[ModelMessage]) -> int:
    return sum(1 for m in messages if isinstance(m, ModelResponse))


def build_report(order_sms: str, date_call: str) -> dict[str, Any]:
    nf = lambda reason: {"status": "not_found", "value": None, "evidence": [], "reasoning": reason}  # noqa: E731
    api = lambda row: [{"type": "api", "resultId": "r1", "row": row, "column": "smsContent"}]  # noqa: E731
    return {
        "订购短信": {"status": "found", "value": order_sms, "evidence": api(3), "reasoning": "编号前包含业务名称"},
        "二次确认短信": {"status": "found", "value": CONFIRM_SMS, "evidence": api(1), "reasoning": "含订购确认提醒"},
        "验证码短信": nf("当天没有同时包含业务名称和“动态验证码”的短信"),
        "受理渠道": {"status": "found", "value": "热线", "evidence": api(3), "reasoning": "订购短信包含“热线渠道”"},
        "争议类型": {"status": "found", "value": "业务",
                 "evidence": [{"type": "document", "quote": "办理业务：5G智享套餐(个人版)"}],
                 "reasoning": "单据是套餐办理受理单"},
        "受理网点": nf("单据中没有受理网点"),
        "鉴权方式": {"status": "found", "value": "服务密码", "evidence": [{"type": "document", "quote": "鉴权方式：服务密码"}]},
        "标准资费": {"status": "found", "value": "129元/月", "evidence": [{"type": "document", "quote": "标准资费：129元/月"}]},
        "业务套餐内容": {"status": "found", "value": "每月国内通用流量40GB、国内通话500分钟",
                   "evidence": [{"type": "document", "quote": "套餐内容：每月国内通用流量40GB、国内通话500分钟"}]},
        "活动时间": nf("争议类型为业务"),
        "活动内容": nf("争议类型为业务"),
        "客户承诺": nf("争议类型为业务"),
        "商品名称": {"status": "found", "value": "5G智享套餐（个人版）", "evidence": [{"type": "input", "key": "业务名称"}]},
        "受理日期": {"status": "found", "value": "2026年11月5号",
                 "evidence": [{"type": "input", "key": "业务月份"}, {"type": "tool", "callId": date_call}],
                 "reasoning": "受理渠道为热线，取业务月份转换"},
        "受理方式": {"status": "found", "value": "热线",
                 "evidence": [{"type": "field", "name": "受理网点"}, {"type": "field", "name": "受理渠道"}],
                 "reasoning": "受理网点为空，取受理渠道"},
        "是否录音": {"status": "found", "value": "|录音", "evidence": [{"type": "field", "name": "受理渠道"}]},
        "业务名称": {"status": "found", "value": "5G智享套餐（个人版）", "evidence": [{"type": "input", "key": "业务名称"}]},
    }


def scripted(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    step = _responses(messages)
    if step == 0:
        return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "business-sms-check"}),
                                    ToolCallPart("load_skill", {"name": "document-match"})])
    if step == 1:
        return ModelResponse(parts=[ToolCallPart("date_range", {"time": "20261105103012", "unit": "day"}),
                                    ToolCallPart("text_contains", {"target": "5G智享套餐（个人版）", "extraChars": " \n"})])
    if step == 2:
        rng = _returns(messages, "date_range")[0]
        return ModelResponse(parts=[ToolCallPart("call_api", {"name": "querySMSSendInfo", "args": {
            "手机号码": "13900001234", "开始时间": rng["start"], "结束时间": rng["end"]}})])
    if step == 3:
        biz = "5G智享套餐（个人版）"
        return ModelResponse(parts=[
            ToolCallPart("query_result", {"resultId": "r1", "where": [
                {"column": "smsContent", "op": "normalizedContains", "value": biz, "before": "编号"},
                {"column": "smsContent", "op": "notContains", "value": "退订提醒"},
                {"column": "smsContent", "op": "notContains", "value": "退订成功"}],
                "orderBy": {"column": "smsSendTime", "desc": True}, "limit": 1}),
            ToolCallPart("query_result", {"resultId": "r1", "where": [
                {"column": "smsContent", "op": "normalizedContains", "value": biz},
                {"column": "smsContent", "op": "contains", "value": "回复"}]}),
            ToolCallPart("query_result", {"resultId": "r1", "where": [
                {"column": "smsContent", "op": "normalizedContains", "value": biz},
                {"column": "smsContent", "op": "contains", "value": "动态验证码"}]}),
        ])
    if step == 4:
        return ModelResponse(parts=[TextPart("订购短信为第 3 行，受理渠道为热线。"),
                                    ToolCallPart("format_date", {"value": "20261105", "fromPattern": "yyyyMMdd",
                                                                 "toPattern": "yyyy年M月d号"})])
    date_call = _returns(messages, "format_date")[0]["callId"]
    if step == 5:
        truncated = ORDER_SMS.replace("【中国移动心级服务，让爱连接】", "")
        return ModelResponse(parts=[ToolCallPart("submit_report", build_report(truncated, date_call))])
    return ModelResponse(parts=[ToolCallPart("submit_report", build_report(ORDER_SMS, date_call))])


def scripted_model() -> FunctionModel:
    return FunctionModel(scripted, model_name="scripted-demo")
