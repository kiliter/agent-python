"""组装模型指令：全局系统提示词（可在管理端编辑） + 平台生成的本次任务说明。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import re

from ..domain.jinja_env import body_field_conditions
from ..domain.template import FieldDef
from .deps import RunDeps
from .output_model import EVIDENCE_LABEL

TYPE_LABEL = {"string": "文本", "enum": "枚举", "date": "日期", "list": "列表"}
MISSING_LABEL = {"placeholder": "保留占位", "empty": "置空", "value": "默认值"}
_JAVA_RULE_NOTE_RE = re.compile(r"\n+原规则（Java）：")

EVIDENCE_RULES = """## 证据填写规则（平台会逐条核对，不通过会退回重填）
- 原文引用（quote）：evidence 写 {"type":"api","resultId":"r1","row":3,"column":"smsContent"}（row 用 query_result 返回的 row），
  或 {"type":"document","quote":"从单据逐字复制的片段"}。value 必须逐字出自引用的原文；标注“整条原样引用”的字段，value 必须与该列完整一致，一个字符也不能增删。
- 入参（input）：evidence 写 {"type":"input","key":"入参名"}，入参必须非空且 value 与入参完全相同。
- 推导（derive）：evidence 列出全部真实依据（api / document / input / tool / field），reasoning 写明推导过程；
  用 format_date 得到的值必须引用它的 callId（{"type":"tool","callId":"t5"}），value 直接使用工具输出；
  严禁将 load_skill、空字符串入参或状态为 not_found 的前置字段作为 found 结论的唯一证据。
- 列表字段（类型为列表）：value 是行对象数组，如 [{"列名1":"值","列名2":"值"}]，每行必须包含且只包含该字段列出的全部列，枚举列只能填可选值；
  有匹配记录时，evidence 要覆盖每一行的出处（每条接口记录写一个 {"type":"api","resultId":"r1","row":3,"column":"该记录的任一列"}，或单据片段），
  原文引用的列表字段每个非空文本单元格都必须逐字出现在被引用的某条接口记录（任一列）或单据片段中。
  接口调用成功且确无匹配记录时，应提交 status="found"、value=[]，并在 evidence 中附上结果为 0 条的查询证据（如 total=0 的 query_result 或 count=0 的 call_api 的 {"type":"tool","callId":"t2"}，或原始记录为 0 条的 {"type":"api","resultId":"r1","row":0,"column":""}）；
  仅当缺少必要入参、前置依赖缺失或接口调用失败无法获知结果时，才提交 status="not_found"、value=null。
- 找不到：status 填 not_found，value 填 null，reasoning 写明查过什么、为什么找不到。不要为了“填满”而编造或退而求其次。"""


def _list_columns_line(f: FieldDef) -> str:
    """列表字段的列说明（给模型看）。#Created By AiCoding(codex)"""
    lines = ["- 列（value 中每行对象的键，全部必填）："]
    for c in f.columns:
        line = f"  - {c.name}：{'枚举' if c.type == 'enum' else '文本'}"
        if c.type == "enum" and c.values:
            line += f"（可选值：{'、'.join(c.values)}）"
        if c.description.strip():
            line += f"；{c.description.strip()}"
        lines.append(line)
    return "\n".join(lines)


_EQ_BRANCH_RE = re.compile(r'^\s*\(?([A-Za-z0-9_\u4e00-\u9fff]+)\s*==\s*"([^"]+)"\)?\s*$')


def _covers_all_enum_values(cond_text: str, deps: tuple[str, ...], by_name: dict[str, FieldDef]) -> bool:
    """判断形如 `(争议类型 == "业务") 或 (争议类型 == "营销活动")` 的分支集合是否覆盖该枚举字段全部可选值。

    #Created By AiCoding(codex)
    全覆盖说明只要枚举字段有合法取值就必然展示，视为无条件必查字段，避免多余提示。
    """
    if len(deps) != 1:
        return False
    dep_field = by_name.get(deps[0])
    if dep_field is None or dep_field.type != "enum" or not dep_field.values:
        return False
    branches = [b.strip() for b in cond_text.split(" 或 ") if b.strip()]
    matched_vals: set[str] = set()
    for br in branches:
        m = _EQ_BRANCH_RE.match(br)
        if not m or m.group(1) != dep_field.name:
            return False
        matched_vals.add(m.group(2))
    return set(dep_field.values).issubset(matched_vals)


def _resolve_skippable_conditions(
    body: str,
    fields: list[FieldDef],
) -> dict[str, tuple[str, tuple[str, ...]]]:
    """结合模板正文 AST 与字段间说明引用，保守算出允许按条件跳过查询的字段表。

    #Created By AiCoding(codex)
    1. 仅保留模板定义中存在的字段；
    2. 排除覆盖了单个枚举字段全部可选值的字段（如同时出现在 业务 与 营销活动 两个分支）；
    3. 若某字段被另一个无条件必查字段的说明引用（如「字段名」），保守降级为必查。
    """
    raw = body_field_conditions(body)
    if not raw:
        return {}
    by_name = {f.name: f for f in fields}
    conds: dict[str, tuple[str, tuple[str, ...]]] = {
        k: v
        for k, v in raw.items()
        if k in by_name and not _covers_all_enum_values(v[0], v[1], by_name)
    }
    if not conds:
        return {}

    # 不动点传播：若某无条件必查字段（非 conds 中字段）在其说明中引用了 conds 里的某个字段名，则移除该字段
    changed = True
    while changed:
        changed = False
        required_fields = [f for f in fields if f.name not in conds]
        for cand in list(conds.keys()):
            needle = f"「{cand}」"
            needle_alt = f"字段{cand}"
            if any(needle in (rf.description or "") or needle_alt in (rf.description or "") for rf in required_fields):
                conds.pop(cand, None)
                changed = True
    return conds


def _build_condition_guide(
    fields: list[FieldDef],
    conds: dict[str, tuple[str, tuple[str, ...]]],
) -> str:
    """将条件字段按触发条件归组，生成精炼的执行顺序提示块。#Created By AiCoding(codex)"""
    if not conds:
        return ""
    control_vars: list[str] = []
    grouped: dict[str, list[str]] = {}
    for f in fields:
        info = conds.get(f.name)
        if not info:
            continue
        cond_text, deps = info
        for dv in deps:
            if dv not in control_vars:
                control_vars.append(dv)
        grouped.setdefault(cond_text, []).append(f.name)

    lines = [
        "### 条件分支与按需查询（可跳过未命中分支）",
        f"- 建议优先确定分支控制字段：{'、'.join(control_vars)}。",
    ]
    for cond_text, fnames in grouped.items():
        lines.append(f"- 仅当 `{cond_text}` 时需要查询：{'、'.join(fnames)}")
    lines.append(
        "- 未命中分支的字段：**无需加载其专属 Skill，也无需调用接口或筛选**；"
        "交卷时该键直接提交 status=\"not_found\"、value=null、evidence=[]，reasoning 写明“展示条件不满足，跳过”即可。"
    )
    return "\n".join(lines)


def _field_line(f: FieldDef, *, condition: str | None = None) -> str:
    parts = [f"### {f.name}",
             f"- {'显示在报告中' if f.visible else '中间字段（不直接显示，供正文条件或其它字段使用）'}；类型：{TYPE_LABEL[f.type]}"
             + (f"（可选值：{'、'.join(f.values)}）" if f.type == "enum" else "")
             + ("（value 为行对象数组；接口调用成功确无记录时提交 status=found, value=[] 并附查询证据；缺少入参或接口失败时提交 not_found）"
                if f.is_list else "")
             + (f"；格式：{f.format}" if f.format else ""),
             f"- 证据类型：{EVIDENCE_LABEL[f.evidence]}" + ("（整条原样引用）" if f.quoteWhole else "")]
    if condition:
        parts.append(
            f"- 展示条件：仅当 `{condition}` 时展示（不满足时无需加载对应 Skill 或查询，直接提交 not_found 并注明“展示条件不满足，跳过”）"
        )
    if f.is_list:
        parts.append(_list_columns_line(f))
    if f.description:
        cleaned_desc = _JAVA_RULE_NOTE_RE.split(f.description, maxsplit=1)[0].strip()
        if cleaned_desc:
            parts.append(f"- 说明：{cleaned_desc}")
    return "\n".join(parts)


def build_task_instructions(deps: RunDeps) -> str:
    """本次任务说明。"""
    submit = ("所有字段都有结论后，调用 submit_report 一次提交全部字段。" if deps.settings.agent_output_mode == "tool"
              else "需要查询或计算时调用工具；所有字段都有结论后，直接输出一个 JSON 对象一次提交全部字段"
                   "（键为字段名，结构见后面的 JSON Schema），不要输出其它文字，也不要用 Markdown 代码块包裹。")
    tpl = deps.template.definition
    rs = deps.resources
    declared_keys = {i.key for i in tpl.inputs}
    raw_inputs = deps.inputs or {}
    input_items = [
        f"- {i.key}：{'（未传入）' if i.key not in raw_inputs else (str(raw_inputs[i.key]).strip() if raw_inputs[i.key] is not None else '') or '（空）'}"
        + (f"（{i.description.strip()}）" if i.description.strip() else "")
        for i in tpl.inputs
    ]
    for k, v in raw_inputs.items():
        if k not in declared_keys and v is not None and str(v).strip():
            input_items.append(f"- {k}：{str(v).strip()}")
    input_lines = "\n".join(input_items) or "（无）"
    skill_lines = "\n".join(
        f"- {sid}（{rs.skills[sid].title}）：{rs.skills[sid].meta.description}"
        for sid in deps.allowed_skills if sid in rs.skills
    ) or "（无，只能从入参和单据中取值）"
    api_lines = "\n".join(
        f"- {a}（{rs.apis[a].title}）" for a in deps.allowed_apis if a in rs.apis
    ) or "（无）"
    conds = _resolve_skippable_conditions(deps.template.body, tpl.fields)
    cond_guide = _build_condition_guide(tpl.fields, conds)
    fields = "\n\n".join(
        _field_line(f, condition=conds[f.name][0] if f.name in conds else None)
        for f in tpl.fields
    ) or "（无）"
    fields_header = (
        f"## 字段定义（共 {len(tpl.fields)} 个；交卷需包含全部键，但展示条件不满足的字段可跳过查询直接提交 not_found）"
        if conds
        else f"## 字段定义（共 {len(tpl.fields)} 个，全部都要给出结论）"
    )
    cond_section = f"\n{cond_guide}\n\n" if cond_guide else "\n"
    document = deps.document.strip() or "（上游没有提供单据）"
    tpl_desc = tpl.description.strip()
    return f"""## 本次任务
- 模板：{tpl.name}{f"（{tpl_desc}）" if tpl_desc else ""}
- 入参：
{input_lines}
- 可用 Skill（只能加载这些；仅加载本次实际需要查询的分支所对应的 Skill）：
{skill_lines}
- 可调用接口（调用前先读相关 Skill）：
{api_lines}

{fields_header}{cond_section}{fields}

{EVIDENCE_RULES}

## 交卷
{submit}

<document>
{document}
</document>"""


USER_PROMPT = "请按模板定义查清每个字段的值并提交。"
