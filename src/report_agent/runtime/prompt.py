"""组装模型指令：全局系统提示词（可在管理端编辑） + 平台生成的本次任务说明。

#Created By AiCoding(codex)
"""

from __future__ import annotations

from ..domain.template import FieldDef
from .deps import RunDeps
from .output_model import EVIDENCE_LABEL

TYPE_LABEL = {"string": "文本", "enum": "枚举", "date": "日期"}
MISSING_LABEL = {"placeholder": "保留占位", "empty": "置空", "value": "默认值"}

EVIDENCE_RULES = """## 证据填写规则（平台会逐条核对，不通过会退回重填）
- 原文引用（quote）：evidence 写 {"type":"api","resultId":"r1","row":3,"column":"smsContent"}（row 用 query_result 返回的 row），
  或 {"type":"document","quote":"从单据逐字复制的片段"}。value 必须逐字出自引用的原文；标注“整条原样引用”的字段，value 必须与该列完整一致，一个字符也不能增删。
- 入参（input）：evidence 写 {"type":"input","key":"入参名"}，value 必须与入参完全相同。
- 推导（derive）：evidence 列出全部依据（api / document / input / tool / field），reasoning 写明推导过程；
  用 format_date 得到的值必须引用它的 callId（{"type":"tool","callId":"t5"}），value 直接使用工具输出。
- 找不到：status 填 not_found，value 填 null，reasoning 写明查过什么、为什么找不到。不要为了“填满”而编造或退而求其次。"""


def _field_line(f: FieldDef) -> str:
    parts = [f"### {f.name}",
             f"- {'显示在报告中' if f.visible else '中间字段（不直接显示，供正文条件或其它字段使用）'}；类型：{TYPE_LABEL[f.type]}"
             + (f"（可选值：{'、'.join(f.values)}）" if f.type == "enum" else "")
             + (f"；格式：{f.format}" if f.format else ""),
             f"- 证据类型：{EVIDENCE_LABEL[f.evidence]}" + ("（整条原样引用）" if f.quoteWhole else "")]
    if f.description:
        parts.append(f"- 说明：{f.description.strip()}")
    return "\n".join(parts)


def build_task_instructions(deps: RunDeps) -> str:
    """本次任务说明。"""
    submit = ("所有字段都有结论后，调用 submit_report 一次提交全部字段。" if deps.settings.agent_output_mode == "tool"
              else "需要查询或计算时调用工具；所有字段都有结论后，直接输出一个 JSON 对象一次提交全部字段"
                   "（键为字段名，结构见后面的 JSON Schema），不要输出其它文字，也不要用 Markdown 代码块包裹。")
    tpl = deps.template.definition
    rs = deps.resources
    input_lines = "\n".join(f"- {i.key}：{deps.inputs.get(i.key, '（未传入）') or '（空）'}"
                            + (f"（{i.description}）" if i.description else "") for i in tpl.inputs) or "（无）"
    skill_lines = "\n".join(
        f"- {sid}（{rs.skills[sid].title}）：{rs.skills[sid].meta.description}"
        for sid in deps.allowed_skills if sid in rs.skills
    ) or "（无，只能从入参和单据中取值）"
    api_lines = "\n".join(
        f"- {a}（{rs.apis[a].title}）" for a in deps.allowed_apis if a in rs.apis
    ) or "（无）"
    fields = "\n\n".join(_field_line(f) for f in tpl.fields) or "（无）"
    document = deps.document.strip() or "（上游没有提供单据）"
    return f"""## 本次任务
- 模板：{tpl.name}{f"（{tpl.description.strip()}）" if tpl.description else ""}
- 入参：
{input_lines}
- 可用 Skill（只能加载这些）：
{skill_lines}
- 可调用接口（调用前先读相关 Skill）：
{api_lines}

## 字段定义（共 {len(tpl.fields)} 个，全部都要给出结论）
{fields}

{EVIDENCE_RULES}

## 交卷
{submit}

<document>
{document}
</document>"""


USER_PROMPT = "请按模板定义查清每个字段的值并提交。"
