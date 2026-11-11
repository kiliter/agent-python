"""智能体运行测试：交卷结构、证据校验、端到端运行（脚本化假模型）。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from report_agent.domain.resources import load_resource_dir
from report_agent.domain.template import InputDef, Template, TemplateDef
from report_agent.container import SEED_DIR
from report_agent.runtime.evidence import EvidenceChecker, _values_equivalent, locate_quote_in_document
from report_agent.runtime.output_model import build_report_model
from report_agent.runtime.runner import InputValidationError, RunRequest, _evidence_label, validate_inputs
from report_agent.runtime.workspace import ApiResult, ProcessEvent, Workspace
from scripted_model import CONFIRM_SMS, ORDER_SMS, build_report

RS = load_resource_dir(SEED_DIR)
TPL = RS.templates[1001]


def test_report_model_is_template_specific():
    model = build_report_model(TPL)
    schema = model.model_json_schema()
    assert set(schema["required"]) == {f.name for f in TPL.definition.fields}
    good = build_report(ORDER_SMS, "t9")
    model.model_validate(good)
    bad_enum = {**good, "受理渠道": {**good["受理渠道"], "value": "营业厅"}}
    with pytest.raises(ValidationError):
        model.model_validate(bad_enum)
    bad_evidence = {**good, "订购短信": {**good["订购短信"], "evidence": [{"type": "input", "key": "业务名称"}]}}
    with pytest.raises(ValidationError):
        model.model_validate(bad_evidence)
    missing = {k: v for k, v in good.items() if k != "业务名称"}
    with pytest.raises(ValidationError):
        model.model_validate(missing)


def _workspace() -> Workspace:
    ws = Workspace()
    ws.add_result(ApiResult("r1", "querySMSSendInfo", "短信", {}, True, None, {}, [
        {"smsContent": "无关"}, {"smsContent": CONFIRM_SMS}, {"smsContent": "y"}, {"smsContent": ORDER_SMS}], 1))
    ws.record_call("format_date", {}, {"value": "2026年11月5号"}, 0)
    return ws


def test_evidence_checker():
    inputs = {"手机号码": "13900001234", "业务名称": "5G智享套餐（个人版）", "创建时间": "20261105103012", "业务月份": "20261105"}
    doc = "办理业务：5G智享套餐(个人版)\n鉴权方式：服务密码\n标准资费：129元/月\n套餐内容：每月国内通用流量40GB、国内通话500分钟"
    checker = EvidenceChecker(TPL, inputs, doc, _workspace())
    assert checker.check(build_report(ORDER_SMS, "t1")) == []

    truncated = build_report(ORDER_SMS[:-5], "t1")
    issues = checker.check(truncated)
    assert [i.field for i in issues] == ["订购短信"] and "整条原样引用" in issues[0].message

    wrong_date = build_report(ORDER_SMS, "t1")
    wrong_date["受理日期"]["value"] = "2026年11月05日"
    assert [i.field for i in checker.check(wrong_date)] == ["受理日期"]

    fake_doc = build_report(ORDER_SMS, "t1")
    fake_doc["鉴权方式"]["evidence"] = [{"type": "document", "quote": "鉴权方式：身份证"}]
    fake_doc["鉴权方式"]["value"] = "身份证"
    assert [i.field for i in checker.check(fake_doc)] == ["鉴权方式"]

    wrong_input = build_report(ORDER_SMS, "t1")
    wrong_input["商品名称"]["value"] = "5G智享套餐"
    assert [i.field for i in checker.check(wrong_input)] == ["商品名称"]


async def test_end_to_end_run(container, case_c01):
    out = await container.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"], entry="试运行"))
    assert out["status"] == "SUCCESS", out["error"]
    assert out["rounds"] == 7
    by_name = {f["name"]: f for f in out["fields"]}
    for name, expected in case_c01["expectedValues"].items():
        assert by_name[name]["value"] == expected, name
    assert by_name["订购短信"]["retried"] is True
    assert "2026年11月5号通过热线经服务密码办理" in out["report"]
    assert "{{验证码短信}}" not in out["report"]
    assert [e["type"] for e in out["events"]].count("report_rejected") == 1
    # 运行记录（未启动后台写入时同步写）
    detail = container.runs.get(out["runId"])
    assert detail["status"] == "SUCCESS" and detail["messages"]
    assert container.runs.list()[0]["runId"] == out["runId"]


async def test_input_validation(container):
    with pytest.raises(InputValidationError) as exc:
        await container.runner.run(RunRequest(1001, {"手机号码": "123", "业务名称": "x"}))
    assert any("创建时间" in e for e in exc.value.errors) and any("手机号码" in e for e in exc.value.errors)


async def test_retries_exhausted_degrades_field(container, case_c01):
    """一直提交错误的订购短信：重试用完后该字段按找不到处理，其它字段照常，状态 PARTIAL。"""

    def always_wrong(messages, info):
        n = sum(1 for m in messages if isinstance(m, ModelResponse))
        if n == 0:
            return ModelResponse(parts=[ToolCallPart("call_api", {"name": "querySMSSendInfo", "args": {
                "手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}})])
        if n == 1:
            return ModelResponse(parts=[ToolCallPart("format_date", {"value": "20261105", "fromPattern": "yyyyMMdd",
                                                                     "toPattern": "yyyy年M月d号"})])
        return ModelResponse(parts=[ToolCallPart("submit_report", build_report(ORDER_SMS + "多余", "t2"))])

    container.runner.model = FunctionModel(always_wrong)
    out = await container.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"]))
    by_name = {f["name"]: f for f in out["fields"]}
    assert by_name["订购短信"]["status"] == "not_found" and by_name["订购短信"]["validationFailed"]
    assert by_name["鉴权方式"]["status"] == "found"
    assert out["status"] == "PARTIAL" and "订购短信" in out["missingShown"]
    assert "{{订购短信}}" in out["report"]


async def test_tool_restrictions(container, case_c01):
    """模板没有关联的 Skill 不能加载：工具 Schema 的 enum 中不出现，强行调用会被退回。"""
    seen = {}

    def probe(messages, info):
        tools = {t.name: t for t in info.function_tools}
        seen["enum"] = tools["load_skill"].parameters_json_schema["properties"]["name"]["enum"]
        seen["api_enum"] = tools["call_api"].parameters_json_schema["properties"]["name"]["enum"]
        n = sum(1 for m in messages if isinstance(m, ModelResponse))
        if n == 0:
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "not-allowed"})])
        return ModelResponse(parts=[ToolCallPart("submit_report", build_report(ORDER_SMS, "t1"))])

    container.runner.model = FunctionModel(probe)
    out = await container.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"]))
    assert seen["enum"] == ["business-sms-check", "document-match"]
    assert seen["api_enum"] == ["querySMSSendInfo"]
    assert out["status"] in ("PARTIAL", "SUCCESS", "FAILED")


def test_evidence_whitespace_scalar_types_and_invalid_refs():
    # 标量等价：布尔大小写兼容但严禁 bool 与 0/1 混淆；数值等价但保留前导零业务码差异
    assert _values_equivalent(True, "true") and _values_equivalent(False, "FALSE")
    assert not _values_equivalent(False, 0) and not _values_equivalent(True, 1)
    assert _values_equivalent(129, "129.0") and _values_equivalent(0, "0")
    assert not _values_equivalent("0000", "0")
    assert not _values_equivalent(None, "") and not _values_equivalent("   ", " ")

    # ApiEvidence 禁止布尔值冒充整数行号
    model = build_report_model(TPL)
    good = build_report(ORDER_SMS, "t1")
    bool_row = {**good, "订购短信": {**good["订购短信"],
                                    "evidence": [{"type": "api", "resultId": "r1", "row": True, "column": "smsContent"}]}}
    with pytest.raises(ValidationError):
        model.model_validate(bool_row)

    # 空白归一化（NBSP / 多空格 / CRLF）+ 失败接口结果/失败工具调用/自引用与循环引用拦截
    ws = _workspace()
    ws.add_result(ApiResult("r_fail", "querySMSSendInfo", "短信", {}, False, "网关超时", {},
                            [{"smsContent": ORDER_SMS}], 5))
    ws.record_call("format_date", {}, {"error": "格式错误"}, 1, ok=False)  # t2 (ok=False)

    inputs = {"手机号码": "13900001234", "业务名称": "5G智享套餐（个人版）", "创建时间": "20261105103012", "业务月份": "20261105"}
    ws_doc = "办理业务：5G智享套餐(个人版)\r\n鉴权方式：\u00a0服务\u3000密码\r\n标准资费：129元/月\r\n套餐内容：每月国内通用流量40GB、国内通话500分钟"
    ws_checker = EvidenceChecker(TPL, inputs, ws_doc, ws)
    ws_report = build_report(ORDER_SMS, "t1")
    ws_report["鉴权方式"] = {"status": "found", "value": "服务 密码",
                           "evidence": [{"type": "document", "quote": "鉴权方式： 服务 密码"}]}
    assert ws_checker.check(ws_report) == []

    std_doc = "办理业务：5G智享套餐(个人版)\r\n鉴权方式：服务密码\r\n标准资费：129元/月\r\n套餐内容：每月国内通用流量40GB、国内通话500分钟"
    checker = EvidenceChecker(TPL, inputs, std_doc, ws)

    # 布尔行号直接传给 EvidenceChecker 也会被拦截
    assert [i.field for i in checker.check(bool_row)] == ["订购短信"]

    # 失败的 API 结果不能作为证据
    bad_api_ev = build_report(ORDER_SMS, "t1")
    bad_api_ev["订购短信"]["evidence"] = [{"type": "api", "resultId": "r_fail", "row": 0, "column": "smsContent"}]
    issues = checker.check(bad_api_ev)
    assert [i.field for i in issues] == ["订购短信"] and "调用失败" in issues[0].message

    # 失败的工具调用不能作为证据
    bad_tool_ev = build_report(ORDER_SMS, "t2")
    issues_tool = checker.check(bad_tool_ev)
    assert [i.field for i in issues_tool] == ["受理日期"] and "执行失败" in issues_tool[0].message

    # 字段自引用与互相循环引用必须被拦截
    self_ref = build_report(ORDER_SMS, "t1")
    self_ref["是否录音"]["evidence"] = [{"type": "field", "name": "是否录音"}]
    issues_self = checker.check(self_ref)
    assert [i.field for i in issues_self] == ["是否录音"] and "自身" in issues_self[0].message

    cycle_ref = build_report(ORDER_SMS, "t1")
    cycle_ref["受理方式"]["evidence"] = [{"type": "field", "name": "是否录音"}]
    cycle_ref["是否录音"]["evidence"] = [{"type": "field", "name": "受理方式"}]
    issues_cycle = checker.check(cycle_ref)
    assert {i.field for i in issues_cycle} == {"受理方式", "是否录音"}
    assert all("循环依赖" in i.message for i in issues_cycle)


def test_document_multi_match_offset_and_line_locating():
    doc = (
        "第一段：鉴权方式：服务密码\n"
        "第二段：标准资费：\n  129元/月\n"
        "第三段：鉴权方式：服务密码\n"
    )
    matches = locate_quote_in_document(doc, "鉴权方式：服务密码", value="服务密码")
    assert len(matches) == 2
    assert matches[0]["line"] == 1 and matches[0]["endLine"] == 1
    assert doc[matches[0]["offset"]:matches[0]["endOffset"]] == "鉴权方式：服务密码"
    assert matches[1]["line"] == 4 and matches[1]["endLine"] == 4
    assert doc[matches[1]["offset"]:matches[1]["endOffset"]] == "鉴权方式：服务密码"

    # 跨行 + 多空白归一化偏移定位
    wrapped = locate_quote_in_document(doc, "标准资费： 129元/月", value="129元/月")
    assert len(wrapped) == 1
    assert wrapped[0]["line"] == 2 and wrapped[0]["endLine"] == 3
    assert "129元/月" in doc[wrapped[0]["offset"]:wrapped[0]["endOffset"]]

    ws = _workspace()
    label, target = _evidence_label([{"type": "document", "quote": "鉴权方式：服务密码"}], ws, doc, value="服务密码")
    assert "第 1 行" in label
    assert target["tab"] == "doc" and target["line"] == 1 and target["matchCount"] == 2 and len(target["matches"]) == 2

    # 字段衍生证据可传递定位到底层来源
    full_rep = build_report(ORDER_SMS, "t1")
    f_label, f_target = _evidence_label(full_rep["是否录音"]["evidence"], ws, doc, value="|录音", report=full_rep)
    assert "字段[受理渠道]" in f_label
    assert f_target == {"tab": "api", "resultId": "r1", "row": 3, "column": "smsContent"}


async def test_missing_fields_in_model_output_salvaged_gracefully(container, case_c01):
    """模型交卷漏掉部分字段且重试耗尽时，保留已核验通过的字段，缺失字段自动降级为 not_found（PARTIAL）。"""

    def omit_fields_model(messages, info):
        n = sum(1 for m in messages if isinstance(m, ModelResponse))
        if n == 0:
            return ModelResponse(parts=[ToolCallPart("call_api", {"name": "querySMSSendInfo", "args": {
                "手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}})])
        if n == 1:
            return ModelResponse(parts=[ToolCallPart("format_date", {"value": "20261105", "fromPattern": "yyyyMMdd",
                                                                     "toPattern": "yyyy年M月d号"})])
        partial = build_report(ORDER_SMS, "t2")
        partial.pop("订购短信")
        partial.pop("验证码短信")
        return ModelResponse(parts=[ToolCallPart("submit_report", partial)])

    container.runner.model = FunctionModel(omit_fields_model)
    out = await container.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"]))
    assert out["status"] == "PARTIAL", out["error"]
    assert out["error"] is None
    detail = container.runs.get(out["runId"])
    assert out["usage"]["requests"] >= 3 and detail["messages"]
    by_name = {f["name"]: f for f in out["fields"]}
    assert by_name["订购短信"]["status"] == "not_found" and by_name["订购短信"]["validationFailed"] is True
    assert by_name["验证码短信"]["status"] == "not_found" and by_name["验证码短信"]["validationFailed"] is True
    assert by_name["鉴权方式"]["status"] == "found" and by_name["鉴权方式"]["value"] == "服务密码"
    assert by_name["受理日期"]["status"] == "found" and by_name["受理日期"]["value"] == "2026年11月5号"
    assert any(e["type"] == "report_degraded" for e in out["events"])


async def test_abnormal_tool_calls_and_gateway_exception_degrade_cleanly(container, case_c01):
    """模型持续发出非法工具调用参数或网关抛异常时，重试耗尽后返回结构化失败结果并记录，不崩溃整次运行。"""

    class ExplodingGateway:
        async def invoke(self, contract, args):
            raise RuntimeError("连接池耗尽")

        async def aclose(self):
            return None

    orig_gateway = container.runner.gateway
    container.runner.gateway = ExplodingGateway()
    try:
        def messy_model(messages, info):
            n = sum(1 for m in messages if isinstance(m, ModelResponse))
            if n <= 2:
                return ModelResponse(parts=[
                    ToolCallPart("load_skill", {"name": "forbidden-skill"}),
                    ToolCallPart("date_range", {"time": "bad-time", "unit": "day"}),
                    ToolCallPart("query_result", {"resultId": "r_missing"}),
                ])
            if n == 3:
                return ModelResponse(parts=[ToolCallPart("call_api", {"name": "querySMSSendInfo", "args": {
                    "手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}})])
            rep = build_report(ORDER_SMS, "t1")
            for api_field in ("订购短信", "二次确认短信", "受理渠道", "受理日期", "受理方式", "是否录音"):
                rep[api_field] = {"status": "not_found", "value": None, "evidence": [], "reasoning": "接口异常"}
            return ModelResponse(parts=[ToolCallPart("submit_report", rep)])

        container.runner.model = FunctionModel(messy_model)
        out = await container.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"]))
    finally:
        container.runner.gateway = orig_gateway

    assert out["status"] == "PARTIAL", out["error"]
    assert any(not c["ok"] and c["tool"] == "load_skill" for c in out["toolCalls"])
    assert any(not c["ok"] and c["tool"] == "date_range" for c in out["toolCalls"])
    assert any(not c["ok"] and c["tool"] == "query_result" for c in out["toolCalls"])
    assert len(out["apiResults"]) == 1 and not out["apiResults"][0]["ok"]
    assert "连接池耗尽" in (out["apiResults"][0]["error"] or "")


def test_zero_field_template_and_invalid_input_regex_and_workspace_guards():
    empty_tpl = Template(
        definition=TemplateDef(
            id=9999,
            name="零字段模板",
            inputs=[InputDef(key="手机号", required=True, pattern="[unclosed")],
            fields=[],
        ),
        body="固定正文",
    )
    m = build_report_model(empty_tpl)
    assert m.model_validate({}).model_dump() == {}

    errs = validate_inputs(empty_tpl, {"手机号": "13900001234"})
    assert errs and "正则不合法" in errs[0]

    res = ApiResult("r1", "api", "标题", {}, True, None, {}, [{"row": 999, "smsContent": "x"}], 1)
    assert res.to_dict()["records"][0]["row"] == 0
    ev = ProcessEvent(seq=7, type="tool", at_ms=10, round=1, data={"seq": -1, "type": "hack"})
    assert ev.to_dict()["seq"] == 7 and ev.to_dict()["type"] == "tool"
