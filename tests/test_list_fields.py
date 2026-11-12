"""Pebble 对齐渲染（trim_blocks / 输出标签换行 / hasDigit）与列表字段（type=list）测试。

#Created By AiCoding(codex)
全部使用内联小模板，不依赖生产内置资源。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer

from jinja2.exceptions import SecurityError

from report_agent.domain.jinja_env import TrackedList, _PlaceholderUndefined, _test_has_digit, printed_variables, render_body
from report_agent.domain.resources import ResourceSet, validate_template
from report_agent.domain.template import Template, dump_template_yaml, parse_template_yaml
from report_agent.runtime.evidence import EvidenceChecker
from report_agent.runtime.output_model import build_report_model, report_to_dict
from report_agent.runtime.prompt import _field_line
from report_agent.runtime.render import build_render_context
from report_agent.runtime.runner import RunRequest
from report_agent.runtime.workspace import ApiResult, Workspace

TEMPLATE_YAML = """
id: 2001
name: 列表字段测试
inputs:
  - key: 客户号码
    required: true
fields:
  - name: 客户号码
    evidence: input
    description: 等于入参客户号码
  - name: 充值流水
    type: list
    evidence: quote
    whenMissing: empty
    description: 客户的充值记录
    columns:
      - name: 充值时间
        description: 充值时间
      - name: 支付方式
      - name: 充值金额
  - name: 账期短信提醒列表
    type: list
    evidence: derive
    whenMissing: empty
    description: 账期内的超额提醒短信
    columns:
      - name: 提醒类型
        type: enum
        values: [活动到期套餐资费变更, 语音超额提醒, 流量超额提醒]
      - name: 账期月
      - name: 提醒次数
"""

BODY = (
    "{% for item in 充值流水 %}\n"
    "{{客户号码}}于{{item.充值时间}}通过{{item.支付方式}}充值{{item.充值金额}}元\n"
    "{% endfor %}"
    "{% for item in 账期短信提醒列表 %}{% if item.提醒类型 == \"语音超额提醒\" %}{{item.账期月}}语音提醒{{item.提醒次数}}次\n"
    "{% elif item.提醒类型 == \"流量超额提醒\" %}{{item.账期月}}流量提醒{{item.提醒次数}}次\n{% endif %}{% endfor %}"
    "完毕"
)

DOCUMENT = "充值记录：2026-11-01 10:00:00 微信 50元；2026-11-03 12:00:00 支付宝 30元。"


def _tpl(body: str = BODY, yaml_text: str = TEMPLATE_YAML) -> Template:
    return Template(definition=parse_template_yaml(yaml_text), body=body)


def _rows_recharge() -> list[dict[str, str]]:
    return [{"充值时间": "2026-11-01 10:00:00", "支付方式": "微信", "充值金额": "50"},
            {"充值时间": "2026-11-03 12:00:00", "支付方式": "支付宝", "充值金额": "30"}]


def _rows_remind() -> list[dict[str, str]]:
    return [{"提醒类型": "语音超额提醒", "账期月": "202610", "提醒次数": "2"},
            {"提醒类型": "流量超额提醒", "账期月": "202611", "提醒次数": "1"},
            {"提醒类型": "活动到期套餐资费变更", "账期月": "202611", "提醒次数": "1"}]


def _report(recharge=None, remind=None) -> dict:
    nf = {"status": "not_found", "value": None, "evidence": [], "reasoning": "无"}
    return {
        "客户号码": {"status": "found", "value": "13900001234", "evidence": [{"type": "input", "key": "客户号码"}],
                     "reasoning": ""},
        "充值流水": recharge if recharge is not None else nf,
        "账期短信提醒列表": remind if remind is not None else nf,
    }


def _workspace() -> Workspace:
    ws = Workspace()
    ws.add_result(ApiResult("r1", "queryRecharge", "充值", {}, True, None, {}, [
        {"payTime": "2026-11-01 10:00:00", "payType": "微信", "amount": "50.00", "orderNo": "A1"},
        {"payTime": "2026-11-03 12:00:00", "payType": "支付宝", "amount": "30", "orderNo": "A2"},
    ], 1))
    return ws


# ============================================================================ Pebble 对齐渲染
def _lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def test_pebble_newline_trimming_examples_from_java():
    """与 Java PebbleTemplateEngine 实测结果一致：每个标签（含 {{ }}）后紧跟的一个换行被去掉。"""
    text, _ = render_body("{{ a }}\nX{# c #}\nY", {"a": "v"})
    assert _lf(text) == "vXY"
    text, used = render_body("A\r\n{% if x == '1' %}\r\nB{{ y }}\r\n{% endif %}\r\nC", {"x": "1"})
    assert _lf(text) == "A\nB{{y}}C" and used == {"y"}


def test_trim_blocks_only_one_newline_and_no_lstrip():
    text, _ = render_body("A\n  {% if x %}\n\nB{{x}}\n\nC{% endif %}\n", {"x": "1"})
    # {% if %} 后去掉一个换行（保留第二个）；块前缩进保留（不开启 lstrip_blocks）；{{x}} 后只去一个换行
    assert text == "A\n  \nB1\nC"


def test_literal_braces_in_text_are_untouched():
    text, _ = render_body("a }}\nb {{x}}", {"x": "1"})
    assert text == "a }}\nb 1"


def test_has_digit_test():
    assert _test_has_digit("129元/月") is True
    assert _test_has_digit("１２元") is True          # 全角数字也是 Unicode 数字
    assert _test_has_digit("免费") is False
    assert _test_has_digit("") is False
    assert _test_has_digit(None) is False
    assert _test_has_digit(_PlaceholderUndefined(name="标准资费")) is False
    assert _test_has_digit(5) is True
    body = "{% if 标准资费 is hasDigit %}资费{{标准资费}}{% else %}无资费{% endif %}"
    assert render_body(body, {})[0] == "无资费"                     # 缺失字段不抛异常
    ctx = build_render_context(_tpl("", """
id: 1
name: t
fields:
  - name: 标准资费
"""), None)
    assert render_body(body, ctx)[0] == "无资费"                    # 占位符 {{标准资费}} 不含数字
    assert render_body(body, {"标准资费": "10元/月"})[0] == "资费10元/月"


# ============================================================================ 定义与校验
def test_list_field_yaml_round_trip():
    defn = parse_template_yaml(TEMPLATE_YAML)
    again = parse_template_yaml(dump_template_yaml(defn))
    assert again == defn
    f = again.field("账期短信提醒列表")
    assert f.type == "list" and f.column_names() == ["提醒类型", "账期月", "提醒次数"]
    assert f.columns[0].type == "enum" and f.columns[0].values[1] == "语音超额提醒"
    with pytest.raises(ValidationError):
        parse_template_yaml(TEMPLATE_YAML.replace("      - name: 支付方式", "      - name: 支付方式\n        foo: 1"))


def test_valid_list_template_has_no_errors():
    issues = validate_template(_tpl(), ResourceSet())
    assert [i for i in issues if i.level == "error"] == []


def _codes(yaml_text: str, body: str = BODY) -> set[str]:
    return {i.code for i in validate_template(_tpl(body, yaml_text), ResourceSet()) if i.level == "error"}


def test_list_field_definition_errors():
    bad = TEMPLATE_YAML.replace("    evidence: quote\n    whenMissing: empty", "    evidence: input\n    whenMissing: placeholder")
    assert {"LIST_EVIDENCE", "LIST_WHEN_MISSING"} <= _codes(bad)
    bad = TEMPLATE_YAML.replace("      - name: 支付方式\n      - name: 充值金额\n", "      - name: 充值时间\n      - name: 充值金额\n")
    assert "COLUMN_DUPLICATE" in _codes(bad)
    bad = TEMPLATE_YAML.replace("        values: [活动到期套餐资费变更, 语音超额提醒, 流量超额提醒]\n", "")
    assert "COLUMN_ENUM_EMPTY" in _codes(bad)
    bad = TEMPLATE_YAML.replace("      - name: 支付方式", "      - name: 1支付方式")
    assert "COLUMN_NAME" in _codes(bad)
    bad = TEMPLATE_YAML.replace("      - name: 支付方式", "      - name: items")
    assert "COLUMN_NAME" in _codes(bad)
    no_cols = """
id: 2001
name: t
fields:
  - name: 充值流水
    type: list
    whenMissing: empty
    description: x
"""
    assert "LIST_NO_COLUMNS" in _codes(no_cols, "{% for item in 充值流水 %}{% endfor %}")
    cols_on_string = """
id: 2001
name: t
fields:
  - name: 订购短信
    description: x
    columns:
      - name: a
"""
    assert "COLUMNS_NOT_LIST" in _codes(cols_on_string, "{{订购短信}}")


def test_loop_variable_is_not_undefined_and_columns_are_checked():
    codes = _codes(TEMPLATE_YAML, BODY.replace("{{item.支付方式}}", "{{item.付款方式}}"))
    assert "BODY_UNDEFINED_FIELD" not in codes
    assert "LIST_COLUMN_UNDEFINED" in codes
    issues = validate_template(_tpl(BODY.replace("item.提醒次数}}次\n{% elif", "item[\"次数\"]}}次\n{% elif")),
                               ResourceSet())
    msg = next(i for i in issues if i.code == "LIST_COLUMN_UNDEFINED")
    assert "账期短信提醒列表" in msg.message and "次数" in msg.message and msg.line == 3
    # for 遍历非列表字段报错
    assert "FOR_NON_LIST" in _codes(TEMPLATE_YAML, BODY + "{% for c in 客户号码 %}{{c}}{% endfor %}")
    # 循环外使用 item 仍是未定义字段
    assert "BODY_UNDEFINED_FIELD" in _codes(TEMPLATE_YAML, BODY + "{{item.充值时间}}")
    # 内层同名循环变量遍历另一个列表时，不按外层列表的列校验
    nested = "{% for item in 充值流水 %}{% for item in 账期短信提醒列表 %}{{item.账期月}}{% endfor %}{{item.支付方式}}{% endfor %}"
    assert "LIST_COLUMN_UNDEFINED" not in _codes(TEMPLATE_YAML, nested + BODY)


# ============================================================================ 交卷结构
def test_report_model_for_list_fields():
    model = build_report_model(_tpl())
    good = _report({"status": "found", "value": _rows_recharge(), "evidence": [{"type": "document", "quote": DOCUMENT}]},
                   {"status": "found", "value": _rows_remind(), "evidence": [{"type": "document", "quote": DOCUMENT}]})
    parsed = model.model_validate(good)
    dumped = report_to_dict(parsed)
    assert dumped["充值流水"]["value"] == _rows_recharge()
    assert model.model_validate(dumped) is not None                              # 往返校验（重试降级时会用到）
    bad_enum = json.loads(json.dumps(good))
    bad_enum["账期短信提醒列表"]["value"][0]["提醒类型"] = "其它"
    with pytest.raises(ValidationError):
        model.model_validate(bad_enum)
    extra_col = json.loads(json.dumps(good))
    extra_col["充值流水"]["value"][0]["流水号"] = "x"
    with pytest.raises(ValidationError):
        model.model_validate(extra_col)
    missing_col = json.loads(json.dumps(good))
    del missing_col["充值流水"]["value"][0]["支付方式"]
    with pytest.raises(ValidationError):
        model.model_validate(missing_col)
    # quote / derive 列表字段在 Schema 层均允许提交空数组 value=[] 并附带 tool / api（默认 row=0, column=""）证据
    empty_ok = _report(
        {"status": "found", "value": [], "evidence": [{"type": "tool", "callId": "t1"}]},
        {"status": "found", "value": [], "evidence": [{"type": "api", "resultId": "r0"}]},
    )
    parsed_empty = model.model_validate(empty_ok)
    dumped_empty = report_to_dict(parsed_empty)
    assert dumped_empty["充值流水"]["value"] == []
    assert dumped_empty["账期短信提醒列表"]["value"] == []

    schema = model.model_json_schema()
    desc = schema["properties"]["充值流水"]["description"]
    assert "列表" in desc and "充值时间" in desc and "支付方式" in desc and "[]" in desc


def test_report_model_native_strict_schema():
    schema = build_report_model(_tpl()).model_json_schema()
    transformer = OpenAIJsonSchemaTransformer(schema, strict=True)
    strict = transformer.walk()
    assert transformer.is_strict_compatible
    text = json.dumps(strict, ensure_ascii=False)
    assert "oneOf" not in text
    rows = [d for d in strict.get("$defs", {}).values() if set(d.get("properties", {})) == {"提醒类型", "账期月", "提醒次数"}]
    assert rows and rows[0]["additionalProperties"] is False
    assert set(rows[0]["required"]) == {"提醒类型", "账期月", "提醒次数"}
    assert rows[0]["properties"]["提醒类型"]["enum"] == ["活动到期套餐资费变更", "语音超额提醒", "流量超额提醒"]


def test_prompt_describes_list_columns():
    line = _field_line(_tpl().definition.field("账期短信提醒列表"))
    assert "类型：列表" in line and "提醒类型：枚举" in line and "语音超额提醒" in line and "账期月" in line


# ============================================================================ 证据校验
def _check(report: dict, ws: Workspace | None = None) -> list:
    return EvidenceChecker(_tpl(), {"客户号码": "13900001234"}, DOCUMENT, ws or _workspace()).check(report)


def test_list_evidence_pass_with_api_records_and_document():
    api_ev = [{"type": "api", "resultId": "r1", "row": 0, "column": "payTime"},
              {"type": "api", "resultId": "r1", "row": 1, "column": "orderNo"}]
    assert _check(_report({"status": "found", "value": _rows_recharge(), "evidence": api_ev})) == []
    doc_ev = [{"type": "document", "quote": DOCUMENT}]
    assert _check(_report({"status": "found", "value": _rows_recharge(), "evidence": doc_ev},
                          {"status": "found", "value": _rows_remind(), "evidence": doc_ev})) == []


def test_empty_list_evidence_semantics():
    """合法空列表（status='found', value=[]）允许引用 tool / 0 行 api / document，且拒绝空证据与失败证据。"""
    ws = _workspace()
    ws.add_result(ApiResult("r_empty", "queryRecharge", "充值空结果", {}, True, None, {}, [], 1, no_data=True))
    ws.add_result(ApiResult("r_fail", "queryRecharge", "充值失败", {}, False, "7003 系统忙", {}, [], 1))
    t_ok = ws.record_call("query_result", {"resultId": "r_empty"}, {"total": 0, "rows": []}, 10, ok=True)
    t_fail = ws.record_call("call_api", {"name": "queryRecharge"}, {"ok": False}, 12, ok=False)

    # 1. quote 与 derive 列表字段均允许在 value=[] 时引用成功工具 callId、0 行成功接口 resultId 或单据片段
    assert _check(
        _report(
            {"status": "found", "value": [], "evidence": [{"type": "tool", "callId": t_ok.call_id}]},
            {"status": "found", "value": [], "evidence": [{"type": "api", "resultId": "r_empty", "row": 0, "column": ""}]},
        ),
        ws,
    ) == []
    assert _check(
        _report(
            {"status": "found", "value": [], "evidence": [{"type": "api", "resultId": "r_empty"}]},
            {"status": "found", "value": [], "evidence": [{"type": "document", "quote": DOCUMENT}]},
        ),
        ws,
    ) == []

    # 2. 空列表缺少证据、引用失败工具或失败接口、引用不存在片段均不通过
    issues_no_ev = _check(_report({"status": "found", "value": [], "evidence": []}), ws)
    assert any(i.field == "充值流水" and "缺少证据" in i.message for i in issues_no_ev)

    issues_bad_tool = _check(
        _report({"status": "found", "value": [], "evidence": [{"type": "tool", "callId": t_fail.call_id}]}),
        ws,
    )
    assert any(i.field == "充值流水" and "执行失败" in i.message for i in issues_bad_tool)

    issues_bad_api = _check(
        _report({"status": "found", "value": [], "evidence": [{"type": "api", "resultId": "r_fail"}]}),
        ws,
    )
    assert any(i.field == "充值流水" and "调用失败" in i.message for i in issues_bad_api)

    # 3. 非空 quote 列表字段仍然严格禁止引用 tool 证据
    issues_nonempty_tool = _check(
        _report({"status": "found", "value": _rows_recharge(), "evidence": [{"type": "tool", "callId": t_ok.call_id}]}),
        ws,
    )
    assert any(i.field == "充值流水" and "原文引用字段" in i.message for i in issues_nonempty_tool)


def test_list_evidence_failures():
    api_ev = [{"type": "api", "resultId": "r1", "row": 0, "column": "payTime"}]
    issues = _check(_report({"status": "found", "value": _rows_recharge(), "evidence": api_ev}))
    msgs = [i.message for i in issues if i.field == "充值流水"]
    assert any("第 2 行" in m and "充值时间" in m for m in msgs), msgs   # 第 2 行没有引用出处
    assert any("第 2 行" in m and "支付方式" in m for m in msgs)

    rows = _rows_recharge()
    rows[0]["充值金额"] = "99"
    issues = _check(_report({"status": "found", "value": rows, "evidence": [
        {"type": "api", "resultId": "r1", "row": 0, "column": "payTime"},
        {"type": "api", "resultId": "r1", "row": 1, "column": "payTime"}]}))
    assert any("第 1 行" in i.message and "充值金额" in i.message and "99" in i.message for i in issues)

    issues = _check(_report({"status": "found", "value": "not-a-list", "evidence": api_ev}))
    assert any("value 必须是数组" in i.message for i in issues)

    issues = _check(_report({"status": "found", "value": [{"充值时间": "2026-11-01 10:00:00"}], "evidence": api_ev}))
    assert any("第 1 行" in i.message and "缺少列" in i.message for i in issues)

    bad_enum = _rows_remind()
    bad_enum[0]["提醒类型"] = "其它"
    issues = _check(_report(None, {"status": "found", "value": bad_enum,
                                   "evidence": [{"type": "document", "quote": DOCUMENT}]}))
    assert any(i.field == "账期短信提醒列表" and "不在可选范围" in i.message for i in issues)

    issues = _check(_report({"status": "found", "value": _rows_recharge(), "evidence": [
        {"type": "api", "resultId": "r9", "row": 0, "column": "payTime"}]}))
    assert any("r9 不存在" in i.message for i in issues)

    issues = _check(_report(None, {"status": "found", "value": _rows_remind(),
                                   "evidence": [{"type": "document", "quote": "单据里没有的话"}]}))
    assert any("单据中找不到片段" in i.message for i in issues)


# ============================================================================ 渲染与 TrackedList 追踪
def test_render_list_loop_with_attributes_and_enum_comparison():
    tpl = _tpl()
    report = _report({"status": "found", "value": _rows_recharge(), "evidence": []},
                     {"status": "found", "value": _rows_remind(), "evidence": []})
    text, used = render_body(tpl.body, build_render_context(tpl, report))
    assert text == ("13900001234于2026-11-01 10:00:00通过微信充值50元\n"
                    "13900001234于2026-11-03 12:00:00通过支付宝充值30元\n"
                    "202610语音提醒2次\n202611流量提醒1次\n完毕")
    assert used == {"客户号码", "充值流水", "账期短信提醒列表"}
    assert {"充值流水", "账期短信提醒列表"} <= printed_variables(tpl.body)


def test_tracked_list_tracks_iteration_only_on_active_for_branch():
    tpl = _tpl()
    ctx = build_render_context(tpl, _report())
    assert isinstance(ctx["充值流水"], TrackedList) and ctx["充值流水"].missing is True
    assert ctx["充值流水"] == [] and ctx["账期短信提醒列表"] == []

    # 生效分支执行了 {% for %}：虽遍历 0 行，仍将列表字段记入 used
    text, used = render_body(tpl.body, ctx)
    assert text == "完毕" and used == {"充值流水", "账期短信提醒列表"}

    # 仅做 {% if 列表字段 %} 布尔判断而不进入 {% for %} 时，不记入 used
    if_only_body = "{% if 充值流水 %}{% for item in 充值流水 %}{{item.充值金额}}{% endfor %}{% else %}无流水{% endif %}"
    text_if, used_if = render_body(
        if_only_body,
        build_render_context(
            tpl,
            _report({"status": "found", "value": [], "evidence": []}),
        ),
    )
    assert text_if == "无流水" and "充值流水" not in used_if

    # {% for %} 位于未命中的条件分支内：__iter__ 未执行，不记入 used
    unhit_branch_body = "{% if 客户号码 == '00000000000' %}{% for item in 充值流水 %}{{item.充值金额}}{% endfor %}{% endif %}完毕"
    text_unhit, used_unhit = render_body(unhit_branch_body, build_render_context(tpl, _report()))
    assert text_unhit == "完毕" and "充值流水" not in used_unhit

    # 沙箱环境禁止修改 TrackedList
    with pytest.raises(SecurityError):
        render_body("{{ 充值流水.append('x') }}", build_render_context(tpl, _report()))


# ============================================================================ 端到端
def _submit_model(report: dict) -> FunctionModel:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart("submit_report", report)])

    return FunctionModel(fn, model_name="list-submit")


@pytest.mark.parametrize("mode", ["with_rows", "empty_found", "missing_not_found"])
async def test_run_with_list_fields_end_to_end(container, mode):
    tpl = _tpl()
    container.service.save_template(tpl, "tester", action="create")
    doc_ev = [{"type": "document", "quote": DOCUMENT}]
    if mode == "with_rows":
        report = _report(
            {"status": "found", "value": _rows_recharge(), "evidence": doc_ev},
            {"status": "found", "value": _rows_remind(), "evidence": doc_ev},
        )
    elif mode == "empty_found":
        report = _report(
            {"status": "found", "value": [], "evidence": doc_ev},
            {"status": "found", "value": [], "evidence": doc_ev},
        )
    else:
        report = _report()

    container.runner.model = _submit_model(report)
    out = await container.runner.run(
        RunRequest(2001, {"客户号码": "13900001234"}, DOCUMENT, entry="试运行", target="draft")
    )
    by_name = {f["name"]: f for f in out["fields"]}
    rec = by_name["充值流水"]
    assert [c["name"] for c in rec["columns"]] == ["充值时间", "支付方式", "充值金额"]

    if mode == "with_rows":
        assert out["status"] == "SUCCESS", (out["error"], out["missingShown"])
        assert out["missingShown"] == []
        assert rec["status"] == "found" and rec["value"] == _rows_recharge() and rec["shown"] is True
        assert json.loads(rec["renderedValue"]) == _rows_recharge()
        assert "通过支付宝充值30元" in out["report"]
    elif mode == "empty_found":
        assert out["status"] == "SUCCESS", (out["error"], out["missingShown"])
        assert out["missingShown"] == []
        assert rec["status"] == "found" and rec["value"] == [] and rec["shown"] is True
        assert rec["renderedValue"] == "[]"
        assert out["report"] == "完毕"
    else:
        assert out["status"] == "PARTIAL"
        assert set(out["missingShown"]) == {"充值流水", "账期短信提醒列表"}
        assert rec["status"] == "not_found" and rec["value"] is None and rec["shown"] is True
        assert rec["renderedValue"] == ""
        assert out["report"] == "完毕"
    json.dumps(out, ensure_ascii=False)                                         # 运行记录可序列化

    from report_agent.api.run_views import detail_view, report_view

    detail = detail_view(out)
    dto = next(f for f in detail["fields"] if f["name"] == "充值流水")
    assert dto["type"] == "列表" and [c["name"] for c in dto["columns"]] == ["充值时间", "支付方式", "充值金额"]
    if mode == "with_rows":
        assert json.loads(dto["runValue"]) == _rows_recharge() and dto["runRows"] == _rows_recharge()
    elif mode == "empty_found":
        assert dto["runStatus"] == "found" and dto["runValue"] == "[]" and dto["runRows"] == []
    else:
        assert dto["runStatus"] == "not_found" and dto["runValue"] == "（置空）" and dto["runRows"] == []
    upstream = next(f for f in report_view(out)["fields"] if f["name"] == "充值流水")
    expected_val = _rows_recharge() if mode == "with_rows" else ([] if mode == "empty_found" else None)
    assert upstream["value"] == expected_val and "columns" in upstream


async def test_unhit_branch_missing_list_keeps_run_success(container):
    """未命中的条件分支内的 {% for %} 不会触发迭代追踪，列表字段 not_found 仍保持 SUCCESS。"""
    unhit_body = (
        "{% if 客户号码 == '00000000000' %}\n"
        "{% for item in 充值流水 %}{{item.充值金额}}{% endfor %}"
        "{% else %}号码{{客户号码}}{% endif %}"
    )
    tpl = _tpl(body=unhit_body)
    container.service.save_template(tpl, "tester", action="create")
    container.runner.model = _submit_model(_report())
    out = await container.runner.run(
        RunRequest(2001, {"客户号码": "13900001234"}, DOCUMENT, entry="试运行", target="draft")
    )
    assert out["status"] == "SUCCESS"
    assert out["missingShown"] == []
    by_name = {f["name"]: f for f in out["fields"]}
    assert by_name["充值流水"]["shown"] is False
    assert out["report"] == "号码13900001234"


def test_field_dto_round_trip_with_columns():
    from report_agent.api.dto import dto_to_field, field_to_dto
    from report_agent.domain.template import FieldDef

    f = _tpl().definition.field("账期短信提醒列表")
    dto = field_to_dto(f)
    assert dto["columns"][0] == {"name": "提醒类型", "type": "枚举",
                                 "enumValues": ["活动到期套餐资费变更", "语音超额提醒", "流量超额提醒"], "description": ""}
    assert FieldDef.model_validate(dto_to_field(dto)) == f
