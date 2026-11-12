"""domain 与 runtime 核心层审查修复与性能优化专项回归测试。

#Created By AiCoding(codex)
覆盖范围：
1. domain/skill.py：frontmatter 空值、单独 \\r 换行、非字符串 name/apis、重复 apis 去重及 SkillParseError 封装。
2. domain/api_contract.py：混合 int/str 错误路径排序、ReDoS 正则拦截、校验器缓存失效、深层栈遍历与可变占位符隔离。
3. domain/jinja_env.py & domain/resources.py：context 含 self 键不触发形参冲突、嵌套环境 used 隔离、TrackedValue 切分/前后缀追踪、内部软链接逃逸防护、.offline 容错、TemplateAssertionError 转 BODY_SYNTAX 与 AST 诊断分类。
4. domain/template.py & runtime/text_tools.py：深层括号正则防递归溢出、date_range 跳过非法数字串并按最早位置提取、parse_date 拒收布尔值、normalize_text 缓存一致性。
5. runtime/evidence.py & render.py & output_model.py & prompt.py & model_factory.py & workspace.py：自引用字段防伪造支撑与可达环检测、标量字段拒收 list/dict 且不渲染 Python repr、DocumentIndex 缓存、queue_listener 同事件循环直投。
6. runtime/tools.py & runner.py：幂等在途请求 leader 取消后生存协程接管、首轮失败后并发重试共享在途请求、query_result 单/多结果过滤投影一致性、_extract_json_dict 代码块提取、_DynamicLimiter 失效 waiter 清理、not_found 证据清空与取消异常消息保留。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from typing import Any

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from report_agent.config import Settings
from report_agent.domain.api_contract import parse_api_yaml
from report_agent.domain.jinja_env import BodySyntaxError, TrackedValue, body_variables, make_environment, render_body
from report_agent.domain.resources import ResourceSet, load_resource_dir, read_offline_marker, validate_template
from report_agent.domain.skill import SkillParseError, parse_skill_markdown
from report_agent.domain.template import (
    ColumnDef,
    FieldDef,
    InputDef,
    Template,
    TemplateDef,
    safe_regex_compile,
)
from report_agent.gateway.base import ApiCallResult
from report_agent.runtime.deps import RunDeps
from report_agent.runtime.evidence import (
    EvidenceChecker,
    FieldIssue,
    get_document_index,
    has_supporting_real_source,
)
from report_agent.runtime.model_factory import build_model
from report_agent.runtime.output_model import build_report_model
from report_agent.runtime.prompt import build_task_instructions
from report_agent.runtime.render import build_render_context, field_render
from report_agent.runtime.runner import (
    RunRequest,
    _DynamicLimiter,
    _cascade_degraded_fields,
    _extract_json_dict,
    _salvage_partial_report,
)
from report_agent.runtime.text_tools import (
    date_range as pure_date_range,
    normalize_text as pure_normalize_text,
    parse_date,
)
from report_agent.runtime.tools import Condition, OrderBy, call_api, query_result
from report_agent.runtime.workspace import ApiResult, EventSink, Workspace, queue_listener


def _ctx(deps: RunDeps, *, retry: int = 0, max_retries: int = 1) -> RunContext[RunDeps]:
    """构造平台工具单元测试用 RunContext。#Created By AiCoding(codex)"""
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), prompt="", retry=retry, max_retries=max_retries)


def _make_deps(
    tpl: Template,
    *,
    inputs: dict[str, str] | None = None,
    document: str = "",
    gateway: Any = None,
    apis: dict[str, Any] | None = None,
) -> RunDeps:
    """构造轻量级 RunDeps 供证据、挽救与工具测试复用。#Created By AiCoding(codex)"""
    api_map = apis or {}
    return RunDeps(
        run_id="run-review-test",
        rev="r1",
        resources=ResourceSet(templates={tpl.id: tpl}, skills={}, apis=api_map),
        template=tpl,
        inputs=inputs or {},
        document=document,
        allowed_skills=list(tpl.definition.skills),
        allowed_apis=list(api_map.keys()),
        workspace=Workspace(),
        events=EventSink(),
        gateway=gateway,
        settings=Settings(_env_file=None, llm_api_key="test"),
    )


# ---------------------------------------------------------------------------
# 1. domain/skill.py 边界与容错
# ---------------------------------------------------------------------------


def test_parse_skill_markdown_edge_cases() -> None:
    """验证空值字段、单独 \\r 换行、名称去空白与重复 API 保序去重，并拦截非字符串类型。"""
    raw_cr = "---\rname:  demo-skill  \rtitle:\rdescription: null\rapis:\r  - apiA\r  - apiB\r  - apiA\r---\r正文步骤"
    skill = parse_skill_markdown(raw_cr)
    assert skill.id == "demo-skill"
    assert skill.title == "demo-skill"
    assert skill.meta.description == ""
    assert skill.meta.apis == ["apiA", "apiB"]
    assert skill.body == "正文步骤"

    with pytest.raises(SkillParseError, match="缺少 name"):
        parse_skill_markdown("---\n---\n无名正文")

    with pytest.raises(SkillParseError, match="缺少 name"):
        parse_skill_markdown("---\nname: true\n---\n布尔名称")

    with pytest.raises(SkillParseError, match="apis 列表元素必须是字符串"):
        parse_skill_markdown("---\nname: bad-apis\napis:\n  - true\n---\n布尔接口项")


# ---------------------------------------------------------------------------
# 2. domain/api_contract.py 混合路径排序、ReDoS 门禁、缓存失效与深层遍历
# ---------------------------------------------------------------------------


def test_api_contract_mixed_path_errors_and_cache_invalidation() -> None:
    """混合数组下标（int）与对象属性（str）错误路径不得触发 TypeError，且修改 input 后缓存自动更新。"""
    contract = parse_api_yaml(
        """
name: batchApi
title: 批量接口
connector: unified-gateway-json
processCode: batchApi
input:
  type: object
  required: [mobile, items]
  properties:
    mobile:
      type: string
      minLength: 11
    items:
      type: array
      items:
        type: object
        required: [code]
        properties:
          code:
            type: integer
request:
  body:
    mobile: ${mobile}
    items: ${items}
response:
  success:
    path: code
    equals: "0"
"""
    )
    errs = contract.validate_args({"mobile": "139", "items": [{"code": "not-int"}]})
    assert len(errs) >= 2
    assert any("mobile" in e for e in errs)
    assert any("items.0.code" in e for e in errs)

    # 通过 model_copy 替换 input Schema 后，_validator_cache 应按对象标识失效重建
    updated = contract.model_copy(
        update={
            "input": {
                "type": "object",
                "required": ["orderId"],
                "properties": {"orderId": {"type": "string"}},
            }
        }
    )
    updated_errs = updated.validate_args({})
    assert len(updated_errs) == 1
    assert "orderId" in updated_errs[0]


def test_api_contract_redos_pattern_and_request_isolation() -> None:
    """接口契约 Schema 与运行期校验均应拦截嵌套量词 ReDoS，且整块占位符替换不得污染原契约。"""
    contract = parse_api_yaml(
        """
name: redosApi
title: 正则门禁测试
connector: unified-gateway-json
processCode: redosApi
input:
  type: object
  properties:
    bad:
      type: string
      pattern: '(a+)+'
    payload:
      type: object
request:
  body:
    nested: ${payload}
    tags:
      - ${payload}
response:
  success:
    path: ok
    equals: "true"
"""
    )
    schema_errs = contract.schema_errors()
    assert any("嵌套重复量词" in e for e in schema_errs)
    arg_errs = contract.validate_args({"bad": "aaaa"})
    assert any("嵌套重复量词" in e for e in arg_errs)

    # 校验整块可变对象替换后修改返回值不会反向污染入参或契约模板
    src_payload = {"inner": ["x"]}
    built = contract.build_request({"payload": src_payload})
    built["body"]["nested"]["inner"].append("mutated")
    assert src_payload == {"inner": ["x"]}
    assert contract.request["body"]["nested"] == "${payload}"

    # 非 dict 属性声明下 param_hint 不抛异常
    weird = contract.model_copy(update={"input": {"type": "object", "properties": {"x": "invalid"}}})
    assert "x" in weird.param_hint()

    # 深层嵌套请求节点不应触发递归栈溢出，且能检出最内层非法 XML 标签名
    deep: Any = {"123badTag": "leaf"}
    for _ in range(150):
        deep = {"node": deep}
    deep_contract = contract.model_copy(
        update={"connector": "unified-gateway-xml", "processCode": "p", "input": {"type": "object"}, "request": {"content": deep}}
    )
    deep_errs = deep_contract.schema_errors()
    assert any("123badTag" in e for e in deep_errs)


def test_parse_api_yaml_rejects_bad_types() -> None:
    """非法 YAML 结构统一抛出 ValueError。"""
    with pytest.raises(ValueError, match="键值映射对象"):
        parse_api_yaml("- not-a-mapping")


# ---------------------------------------------------------------------------
# 3. domain/jinja_env.py & domain/resources.py 渲染隔离、TrackedValue 与软链接防护
# ---------------------------------------------------------------------------


def test_jinja_env_self_context_nested_used_and_tracked_methods() -> None:
    """context 含 self 键不会触发 render(**context) 形参冲突；嵌套环境 used 互不串扰；TrackedValue 切分保留追踪。"""
    inner_used: set[str] = set()
    inner_env = make_environment(used=inner_used)
    inner_tpl = inner_env.from_string("{{ 内层字段 }}")

    class _NestedHelper:
        def __str__(self) -> str:
            return inner_tpl.render({"内层字段": TrackedValue("内层值", "内层字段")})

    out, outer_used = render_body(
        "{{ 普通字段 }}|{{ 备注.split('，')[0] }}|{{ 渠道.removeprefix('中国移动') }}",
        {
            "self": "不会触发形参冲突",
            "普通字段": TrackedValue("正常值", "普通字段"),
            "备注": TrackedValue("首段，次段", "备注"),
            "渠道": TrackedValue("中国移动掌厅", "渠道"),
            "未输出字段": TrackedValue("隐藏", "未输出字段"),
        },
    )
    assert out == "正常值|首段|掌厅"
    assert outer_used == {"普通字段", "备注", "渠道"}

    # 验证渲染过程中嵌套调用独立 make_environment(used=inner_used) 不会污染外层 outer_used_2
    out2, outer_used_2 = render_body(
        "{{ 外层字段 }}-{{ 子片段 }}",
        {
            "外层字段": TrackedValue("A", "外层字段"),
            "子片段": _NestedHelper(),
        },
    )
    assert out2 == "A-内层值"
    assert outer_used_2 == {"外层字段"}
    assert inner_used == {"内层字段"}


def test_field_render_never_emits_python_repr_for_containers() -> None:
    """标量字段或列表单元格意外出现 list/dict 时不得把 Python repr 拼进报告正文。"""
    tpl = Template(
        definition=TemplateDef(
            id=2001,
            name="容器防御模板",
            fields=[
                FieldDef(name="标量字段", evidence="derive"),
                FieldDef(
                    name="明细列表",
                    type="list",
                    evidence="derive",
                    columns=[ColumnDef(name="标题")],
                ),
            ],
        ),
        body="{{ 标量字段 }}|{% for r in 明细列表 %}{{ r.标题 }}{% endfor %}",
    )
    report = {
        "标量字段": {"status": "found", "value": ["非法数组"], "evidence": [], "reasoning": ""},
        "明细列表": {"status": "found", "value": [{"标题": {"bad": 1}}], "evidence": [], "reasoning": ""},
    }
    ctx = build_render_context(tpl, report)
    text, _ = render_body(tpl.body, ctx)
    assert "['非法数组']" not in text
    assert "{'bad': 1}" not in text
    fr = field_render(tpl.definition.fields[0], {"status": "found", "value": {"k": "v"}})
    assert fr.found is False
    assert fr.rendered == "{{标量字段}}"


def test_resources_inner_symlink_protection_and_ast_diagnostics(tmp_path: Path) -> None:
    """拦截子目录内文件软链接越界读取；兼容异常 .offline 文件；捕获 TemplateAssertionError 并准确分类未定义变量行号。"""
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("SECRET_DATA", encoding="utf-8")

    root = tmp_path / "res_root"
    tpl_dir = root / "templates" / "1001"
    tpl_dir.mkdir(parents=True)
    (tpl_dir / "template.yaml").write_text("id: 1001\nname: 测试模板\nfields: []\n", encoding="utf-8")
    (tpl_dir / "body.md.j2").symlink_to(outside)

    skill_dir = root / "skills" / "s1"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").symlink_to(outside)

    rs = load_resource_dir(root)
    assert rs.templates == {}
    assert rs.skills == {}
    assert any("路径越界" in i.message for i in rs.load_issues)

    # .offline 为非对象 JSON 或损坏字节时安全返回 None，不抛解码异常
    scalar_dir = tmp_path / "scalar_dir"
    scalar_dir.mkdir()
    (scalar_dir / ".offline").write_text("[1, 2, 3]", encoding="utf-8")
    assert read_offline_marker(scalar_dir) is None

    bad_utf8_dir = tmp_path / "bad_utf8_dir"
    bad_utf8_dir.mkdir()
    (bad_utf8_dir / ".offline").write_bytes(b"\xff\xfe\x00")
    assert read_offline_marker(bad_utf8_dir) is None

    # Jinja2 编译期断言错误（如将 loop 作为循环目标）应统一封装为 BodySyntaxError / BODY_SYNTAX，而非 500 崩溃
    with pytest.raises(BodySyntaxError, match="第 1 行语法错误"):
        body_variables("{% for x, loop in 列表 %}{{ loop }}{% endfor %}")
    bad_loop_tpl = Template(
        definition=TemplateDef(id=2003, name="非法循环绑定", fields=[]),
        body="{% for x, loop in 列表 %}{{ loop }}{% endfor %}",
    )
    loop_diags = validate_template(bad_loop_tpl, ResourceSet())
    assert any(d.code == "BODY_SYNTAX" and d.line == 1 for d in loop_diags)

    # 模板静态校验：ReDoS 入参正则、输出表达式拼接未定义字段行号（非“条件判断中”）、元组解包与 for-else 作用域
    tpl = Template(
        definition=TemplateDef(
            id=2002,
            name="静态诊断测试",
            inputs=[InputDef(key="单号", pattern="(a+)+")],
            fields=[
                FieldDef(
                    name="记录表",
                    type="list",
                    evidence="derive",
                    columns=[ColumnDef(name="列名")],
                )
            ],
        ),
        body="第一行\n{{ 未声明字段 ~ '元' }}\n{% for a in 记录表 %}{{ a.列名 }}{% else %}无记录{% endfor %}",
    )
    empty_rs = ResourceSet(templates={2002: tpl}, skills={}, apis={})
    diags = validate_template(tpl, empty_rs)
    msgs = [d.message for d in diags]
    assert any("嵌套重复量词" in m for m in msgs)
    assert any("未声明字段" in m and "第 2 行" in m and "条件判断中" not in m for m in msgs)


# ---------------------------------------------------------------------------
# 4. domain/template.py & runtime/text_tools.py 正则深度、日期提取与归一化
# ---------------------------------------------------------------------------


def test_safe_regex_deep_parentheses_and_date_extraction() -> None:
    """超深括号正则抛 ValueError 而非 RecursionError；date_range 跳过非法 8 位串并按最早出现位置取值。"""
    deep_pat = "(" * 990 + "a" + ")" * 990
    with pytest.raises(ValueError, match="嵌套"):
        safe_regex_compile(deep_pat)

    # 前置 20269999 不是合法日历日期，应自动跳过并提取后续 20261005
    start1, end1 = pure_date_range("订单流水 20269999，办理日期 20261005", "day")
    assert (start1, end1) == ("20261005000000", "20261005235959")

    # 紧凑日期出现在分隔日期之前时，应取文本中最早出现的 20261005 而非后面的 2026-12-31
    start2, end2 = pure_date_range("于 20261005 受理，协议有效期至 2026-12-31", "day")
    assert (start2, end2) == ("20261005000000", "20261005235959")

    start_m, end_m = pure_date_range("账期编号 202619 无效，实际查询 202602 账单与 2026-11 记录", "month")
    assert (start_m, end_m) == ("20260201000000", "20260228235959")

    with pytest.raises(ValueError, match="日期值不能为空"):
        parse_date(True, "yyyyMMdd")  # type: ignore[arg-type]

    assert pure_normalize_text("ＡＢＣ，测试！\u200b#", "#") == "ABC测试"


# ---------------------------------------------------------------------------
# 5. runtime/evidence.py & runner.py & output_model.py & prompt.py & workspace.py
# ---------------------------------------------------------------------------


def test_self_reference_cannot_mask_not_found_dependency_and_cascades() -> None:
    """自引用字段 F -> F 不能充当真实有效证据来掩盖对 not_found 前置字段的悬空依赖，同时检测可达环。"""
    tpl = Template(
        definition=TemplateDef(
            id=3001,
            name="自引用与级联测试",
            fields=[
                FieldDef(name="前置字段", evidence="quote"),
                FieldDef(name="自引用衍生", evidence="derive"),
                FieldDef(name="环节点甲", evidence="derive"),
                FieldDef(name="环节点乙", evidence="derive"),
                FieldDef(name="环外下游", evidence="derive"),
            ],
        ),
        body="{{ 自引用衍生 }}",
    )
    report = {
        "前置字段": {"status": "not_found", "value": None, "evidence": [], "reasoning": "未查到"},
        "自引用衍生": {
            "status": "found",
            "value": "结论",
            "evidence": [
                {"type": "field", "name": "自引用衍生"},
                {"type": "field", "name": "前置字段"},
            ],
            "reasoning": "试图用自身绕过校验",
        },
        "环节点甲": {
            "status": "found",
            "value": "甲",
            "evidence": [{"type": "field", "name": "环节点乙"}],
            "reasoning": "互引",
        },
        "环节点乙": {
            "status": "found",
            "value": "乙",
            "evidence": [{"type": "field", "name": "环节点甲"}],
            "reasoning": "互引",
        },
        "环外下游": {
            "status": "found",
            "value": "丙",
            "evidence": [{"type": "field", "name": "环节点甲"}],
            "reasoning": "指向环",
        },
    }
    assert (
        has_supporting_real_source(
            report["自引用衍生"]["evidence"],
            {"自引用衍生"},
            self_field="自引用衍生",
        )
        is False
    )
    checker = EvidenceChecker(tpl, {}, "", Workspace())
    issues = checker.check(report)
    self_msgs = [i.message for i in issues if i.field == "自引用衍生"]
    assert any("不能引用自身" in m for m in self_msgs)
    assert any("not_found" in m for m in self_msgs)
    assert any(i.field == "环外下游" and "循环依赖" in i.message for i in issues)

    # 级联降级同样应排除 self_field，把悬空依赖 not_found 的自引用字段降级
    failed: set[str] = set()
    cascade_issues: list[FieldIssue] = []
    _cascade_degraded_fields(report, failed, cascade_issues)
    assert "自引用衍生" in failed
    assert report["自引用衍生"]["status"] == "not_found"


def test_scalar_field_rejects_list_or_dict_in_evidence_and_salvage() -> None:
    """标量字段传入数组/字典时在 EvidenceChecker 与 _salvage_partial_report 中均应拒绝并降级为 not_found。"""
    tpl = Template(
        definition=TemplateDef(
            id=3002,
            name="标量类型防线",
            inputs=[InputDef(key="业务名称", required=True)],
            fields=[
                FieldDef(name="合法入参字段", evidence="input"),
                FieldDef(name="错误数组字段", evidence="derive"),
            ],
        ),
        body="{{ 合法入参字段 }}-{{ 错误数组字段 }}",
    )
    deps = _make_deps(tpl, inputs={"业务名称": "5G畅享套餐"}, document="单据内容")
    report_model = build_report_model(tpl)

    checker = EvidenceChecker(tpl, deps.inputs, deps.document, deps.workspace)
    ev_issues = checker.check(
        {
            "合法入参字段": {
                "status": "found",
                "value": "5G畅享套餐",
                "evidence": [{"type": "input", "key": "业务名称"}],
                "reasoning": "取入参",
            },
            "错误数组字段": {
                "status": "found",
                "value": ["a", "b"],
                "evidence": [{"type": "input", "key": "业务名称"}],
                "reasoning": "类型错误",
            },
        }
    )
    assert any(i.field == "错误数组字段" and "标量文本" in i.message for i in ev_issues)

    salvaged = _salvage_partial_report(
        {
            "合法入参字段": {
                "status": "found",
                "value": "5G畅享套餐",
                "evidence": [{"type": "input", "key": "业务名称"}],
                "reasoning": "取入参",
            },
            "错误数组字段": {
                "status": "found",
                "value": ["a", "b"],
                "evidence": [{"type": "input", "key": "业务名称"}],
                "reasoning": "类型错误",
            },
        },
        report_model,
        deps,
    )
    assert salvaged["合法入参字段"]["status"] == "found"
    assert salvaged["错误数组字段"]["status"] == "not_found"
    assert salvaged["错误数组字段"]["value"] is None


def test_document_index_cache_prompt_and_model_factory() -> None:
    """验证 DocumentIndex 定位缓存、草稿重复键交卷模型容错、空白描述裁剪与空密钥兜底。"""
    ws = Workspace()
    doc = "第一行：客户张三\n第二行：资费 39元/月\n第三行：资费 39元/月"
    idx = get_document_index(ws, doc)
    assert idx.lines == ["第一行：客户张三", "第二行：资费 39元/月", "第三行：资费 39元/月"]
    locs1 = idx.locate("第二行：资费 39元/月", value="39元/月")
    locs2 = idx.locate("第二行：资费 39元/月", value="39元/月")
    assert locs1 == locs2
    assert locs1[0]["line"] == 2

    # 草稿态存在重复入参 key 时 build_report_model 不崩溃，且空白 description 不输出空括号“（）”
    tpl = Template(
        definition=TemplateDef(
            id=3003,
            name="草稿容错模板",
            description="   ",
            inputs=[
                InputDef(key="手机号码", description="  "),
                InputDef(key="手机号码", description="重复项"),
                InputDef(key="备注"),
            ],
            fields=[FieldDef(name="客户号码", evidence="input")],
        ),
        body="{{ 客户号码 }}",
    )
    rm = build_report_model(tpl)
    assert any(fi.alias == "客户号码" for fi in rm.model_fields.values())
    deps = _make_deps(tpl, inputs={"手机号码": "   "})
    prompt_text = build_task_instructions(deps)
    assert "（）" not in prompt_text
    assert "- 手机号码：（空）" in prompt_text
    assert "- 备注：（未传入）" in prompt_text

    # 空 API Key 下 build_model 使用 EMPTY 占位，不因空串报错
    m = build_model(Settings(_env_file=None, llm_api_key=""))
    assert m is not None


async def test_eventsink_queue_listener_same_loop_and_closed_loop() -> None:
    """同一事件循环内 emit 应即时入队，且绑定在已关闭独立事件循环上的 queue_listener 不抛 RuntimeError。"""
    q: asyncio.Queue[Any] = asyncio.Queue()
    sink = EventSink(listener=queue_listener(q))
    sink.emit("tool_called", tool="extract_dates")
    kind, payload = q.get_nowait()
    assert kind == "event"
    assert payload["type"] == "tool_called"

    # 在子线程独立事件循环中创建监听器并关闭循环后，主线程触发 emit 仍安全兜底入队
    closed_q: asyncio.Queue[Any] = asyncio.Queue()
    holder: list[Any] = []

    def _build_and_close_in_thread() -> None:
        sub_loop = asyncio.new_event_loop()
        try:
            async def _capture() -> Any:
                return queue_listener(closed_q)

            holder.append(sub_loop.run_until_complete(_capture()))
        finally:
            sub_loop.close()

    t = threading.Thread(target=_build_and_close_in_thread)
    t.start()
    t.join()

    sink_closed = EventSink(listener=holder[0])
    sink_closed.emit("step_after_closed_loop")
    assert closed_q.get_nowait()[1]["type"] == "step_after_closed_loop"


# ---------------------------------------------------------------------------
# 6. runtime/tools.py & runner.py 并发接管、过滤投影、代码块提取与限流器加固
# ---------------------------------------------------------------------------


class _ControllableGateway:
    """支持受控挂起与首轮失败模拟的网关桩。#Created By AiCoding(codex)"""

    def __init__(self, *, fail_first: bool = False) -> None:
        self.calls = 0
        self.fail_first = fail_first
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def invoke(self, contract: Any, args: dict[str, Any]) -> ApiCallResult:
        self.calls += 1
        cur = self.calls
        self.started.set()
        await self.release.wait()
        if self.fail_first and cur == 1:
            return ApiCallResult(ok=False, error="模拟瞬时超时", cost_ms=4)
        return ApiCallResult(
            ok=True,
            records=[
                {"smsContent": "【业务提醒】已成功订购5G套餐！", "sendTime": "20261105100000", "channel": "10086"},
                {"smsContent": "验证码 123456", "sendTime": "20261105090000", "channel": "APP"},
            ],
            cost_ms=3,
            raw="<ok/>",
        )

    async def aclose(self) -> None:
        return None


def _demo_sms_contract() -> Any:
    return parse_api_yaml(
        """
name: querySMSSendInfo
title: 短信查询
connector: unified-gateway-xml
processCode: querySMSSendInfo
idempotent: true
input:
  type: object
  required: [手机号码]
  additionalProperties: false
  properties:
    手机号码:
      type: string
request:
  content:
    mobile: ${手机号码}
response:
  success:
    path: response.code
    equals: "0000"
  records:
    path: content.list
    columns:
      smsContent: 内容
      sendTime: 时间
      channel: 渠道
"""
    )


async def test_call_api_idempotent_leader_cancellation_handoff_and_retry_dedup() -> None:
    """幂等在途请求的首个协程被取消时，并发等待协程应平滑接管完成而非随同报错；首轮失败后重试同样共享在途调用。"""
    contract = _demo_sms_contract()
    tpl = Template(definition=TemplateDef(id=4001, name="并发测试", fields=[]), body="")
    gw = _ControllableGateway()
    deps = _make_deps(tpl, gateway=gw, apis={"querySMSSendInfo": contract})

    task1 = asyncio.create_task(call_api(_ctx(deps), "querySMSSendInfo", {"手机号码": "13900001234"}))
    await gw.started.wait()
    task2 = asyncio.create_task(call_api(_ctx(deps), "querySMSSendInfo", {"手机号码": "13900001234"}))
    await asyncio.sleep(0)

    # 取消首个发起请求的协程 task1（中断其底层在途调用），放行网关后 task2 应自动接管重调并写入唯一结果 r1
    task1.cancel()
    gw.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task1
    res2 = await task2
    assert res2["ok"] is True
    assert res2["resultId"] == "r1"
    assert list(deps.workspace.results.keys()) == ["r1"]
    assert gw.calls == 2

    # 首轮失败不缓存后，两个并发重试请求也应共享同一次在途调用（总调用数 1 + 1 = 2）
    gw_retry = _ControllableGateway(fail_first=True)
    gw_retry.release.set()
    deps_retry = _make_deps(tpl, gateway=gw_retry, apis={"querySMSSendInfo": contract})
    first_fail = await call_api(_ctx(deps_retry), "querySMSSendInfo", {"手机号码": "13900009999"})
    assert first_fail["ok"] is False
    r_a, r_b = await asyncio.gather(
        call_api(_ctx(deps_retry), "querySMSSendInfo", {"手机号码": "13900009999"}),
        call_api(_ctx(deps_retry), "querySMSSendInfo", {"手机号码": "13900009999"}),
    )
    assert r_a["ok"] is True and r_b["ok"] is True
    assert r_a["resultId"] == r_b["resultId"] == "r2"
    assert gw_retry.calls == 2


async def test_query_result_unified_single_and_multi_filtering() -> None:
    """验证单结果与多结果合并查询在归一化过滤、排序、列裁剪及布尔 limit 校验上的一致性。"""
    tpl = Template(definition=TemplateDef(id=4002, name="过滤测试", fields=[]), body="")
    deps = _make_deps(tpl)
    deps.workspace.results["r1"] = ApiResult(
        result_id="r1",
        api="sms",
        title="短信",
        args={},
        ok=True,
        error=None,
        columns={"smsContent": "内容", "sendTime": "时间", "extra": "附加"},
        records=[
            {"smsContent": "尊敬的客户：５Ｇ智享套餐已生效！", "sendTime": "20261105090000", "extra": "A"},
            {"smsContent": "普通账单提醒", "sendTime": "20261105110000", "extra": "B"},
        ],
        cost_ms=1,
    )
    deps.workspace.results["r2"] = ApiResult(
        result_id="r2",
        api="sms",
        title="短信",
        args={},
        ok=True,
        error=None,
        columns={"smsContent": "内容", "sendTime": "时间", "extra": "附加"},
        records=[
            {"smsContent": "5G-智享套餐二次确认", "sendTime": "20261105100000", "extra": "C"},
        ],
        cost_ms=1,
    )

    with pytest.raises(ModelRetry, match="limit 必须是正整数"):
        await query_result(_ctx(deps, retry=0, max_retries=1), resultId="r1", limit=True)  # type: ignore[arg-type]
    bad_bool_limit = await query_result(_ctx(deps, retry=1, max_retries=1), resultId="r1", limit=True)  # type: ignore[arg-type]
    assert bad_bool_limit["ok"] is False

    single = await query_result(
        _ctx(deps),
        resultId="r1",
        where=[Condition(column="smsContent", op="normalizedContains", value="5G智享套餐")],
        columns=["smsContent"],
    )
    assert single["resultId"] == "r1"
    assert single["total"] == 1
    assert single["rows"] == [{"row": 0, "smsContent": "尊敬的客户：５Ｇ智享套餐已生效！"}]

    merged = await query_result(
        _ctx(deps),
        resultIds=["r1", "r2"],
        where=[Condition(column="smsContent", op="normalizedContains", value="5G智享套餐")],
        orderBy=OrderBy(column="sendTime", direction="desc"),
        columns=["sendTime"],
    )
    assert merged["resultIds"] == ["r1", "r2"]
    assert merged["total"] == 2
    assert [(r["resultId"], r["sendTime"]) for r in merged["rows"]] == [
        ("r2", "20261105100000"),
        ("r1", "20261105090000"),
    ]


async def test_extract_json_dict_and_dynamic_limiter_resilience() -> None:
    """_extract_json_dict 可跳过前置带花括号说明提取代码块 JSON；_DynamicLimiter 自动清理失效/关循环 waiter。"""
    fenced = '思考过程：客户提到 {套餐争议}，下面给出最终结果：\n```json\n{"字段A": {"status": "found"}}\n```'
    assert _extract_json_dict(fenced) == {"字段A": {"status": "found"}}

    limiter = _DynamicLimiter(1)
    # 注入一个来自已关闭事件循环的失效 Future，验证 set_limit 与 __aenter__ 均不会崩溃或死锁
    dead_loop = asyncio.new_event_loop()
    dead_fut = dead_loop.create_future()
    dead_loop.close()
    limiter._waiters.append(dead_fut)
    limiter.set_limit(2)

    async with limiter:
        assert limiter.inflight == 1
    assert limiter.inflight == 0


async def test_runner_clears_not_found_evidence_and_preserves_cancelled_error(container: Any, case_c01: dict) -> None:
    """运行产物中 not_found 字段不应残留未经核验的伪造证据，且取消运行时保留原始 CancelledError 实例。"""
    doc_text = case_c01.get("documentText") or case_c01.get("document") or ""

    # 1. 模型为 not_found 字段塞入伪造证据，交卷后最终运行详情中的 evidence 必须清空为 []
    def _not_found_with_stale_ev_model(messages: list[Any], info: Any) -> ModelResponse:
        tpl_fields = container.releases.live_snapshot()[1].templates[1001].definition.fields
        payload: dict[str, Any] = {}
        for f in tpl_fields:
            if f.evidence == "input":
                payload[f.name] = {
                    "status": "found",
                    "value": case_c01["inputs"]["业务名称"],
                    "evidence": [{"type": "input", "key": "业务名称"}],
                    "reasoning": "取入参",
                }
            else:
                payload[f.name] = {
                    "status": "not_found",
                    "value": None,
                    "evidence": [{"type": "document", "quote": "不存在的伪造引用"}],
                    "reasoning": "未找到",
                }
        return ModelResponse(parts=[ToolCallPart(tool_name="submit_report", args=payload, tool_call_id="call-1")])

    container.runner.model = FunctionModel(_not_found_with_stale_ev_model)
    out = await container.runner.run(
        RunRequest(template_id=1001, inputs=case_c01["inputs"], document=doc_text, entry="试运行")
    )
    for f_out in out["fields"]:
        if f_out["status"] == "not_found":
            assert f_out["evidence"] == []
            assert f_out["evidenceLabel"] == ""

    # 2. 模型执行中抛出带说明的 CancelledError 时，原样透传而非丢失原因
    def _cancel_model(messages: list[Any], info: Any) -> ModelResponse:
        raise asyncio.CancelledError("user-aborted-stream")

    container.runner.model = FunctionModel(_cancel_model)
    with pytest.raises(asyncio.CancelledError, match="user-aborted-stream"):
        await container.runner.run(
            RunRequest(template_id=1001, inputs=case_c01["inputs"], document=doc_text, entry="试运行")
        )
