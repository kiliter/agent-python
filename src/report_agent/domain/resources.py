"""资源集合：一个发布快照（或叠加草稿后的工作副本）中的全部资源，以及发布前校验。

#Created By AiCoding(codex)
目录结构：
  system-prompt.md
  templates/<id>/template.yaml、body.md.j2、.offline
  skills/<id>/SKILL.md
  apis/<name>.yaml
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from jinja2 import nodes
from pydantic import ValidationError

from .api_contract import ApiContract, parse_api_yaml
from .jinja_env import BodySyntaxError, body_variables, parse_body
from .skill import SKILL_FILE, Skill, SkillParseError, parse_skill_markdown
from .template import (BODY_FILE, OFFLINE_FILE, TEMPLATE_FILE, Template, TemplateDef, body_variable_lines,
                       parse_template_yaml)

log = logging.getLogger(__name__)

SYSTEM_PROMPT_FILE = "system-prompt.md"
ROUTER_SKILL_ID = "template-router"
_ROUTER_TPL_HEADING_RE = re.compile(r"^###\s+(\d{1,10})\b", re.MULTILINE)
ResourceKind = Literal["template", "skill", "api", "system-prompt"]


@dataclass
class Issue:
    """校验问题。level=error 阻止发布，warning 只提示。"""

    level: Literal["error", "warning"]
    code: str
    message: str
    kind: ResourceKind | None = None
    key: str | None = None
    field: str | None = None
    line: int | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ResourceSet:
    """一组资源。load_issues 记录目录中无法解析的文件。"""

    system_prompt: str = ""
    templates: dict[int, Template] = field(default_factory=dict)
    skills: dict[str, Skill] = field(default_factory=dict)
    apis: dict[str, ApiContract] = field(default_factory=dict)
    load_issues: list[Issue] = field(default_factory=list)

    def skill_by_ref(self, ref: str) -> Skill | None:
        """按标识或中文名称查找 Skill。"""
        if ref in self.skills:
            return self.skills[ref]
        return next((s for s in self.skills.values() if s.title == ref), None)

    def allowed_apis(self, template: Template) -> list[str]:
        """模板可调用的接口：其 Skill 声明的接口并集（保持声明顺序）。"""
        seen: list[str] = []
        for sid in template.definition.skills:
            skill = self.skills.get(sid)
            for api in skill.meta.apis if skill else []:
                if api in self.apis and api not in seen:
                    seen.append(api)
        return seen


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def load_template_dir(path: Path) -> Template:
    """读取一个模板目录。"""
    defn = parse_template_yaml((path / TEMPLATE_FILE).read_text(encoding="utf-8"))
    body_path = path / BODY_FILE
    body = body_path.read_text(encoding="utf-8") if body_path.exists() else ""
    return Template(definition=defn, body=body, offline=(path / OFFLINE_FILE).exists())


def _within_root(path: Path, root_resolved: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root_resolved)
    except OSError:
        return False


def load_resource_dir(root: Path) -> ResourceSet:
    """读取整个资源目录。单个资源损坏不影响其它资源，问题记入 load_issues。"""
    rs = ResourceSet()
    root_resolved = root.resolve()
    sp = root / SYSTEM_PROMPT_FILE
    if sp.exists():
        if not _within_root(sp, root_resolved):
            rs.load_issues.append(Issue("error", "LOAD_FAILED", "系统提示词路径越界", "system-prompt", "system-prompt"))
        else:
            try:
                rs.system_prompt = sp.read_text(encoding="utf-8")
            except (ValueError, OSError) as exc:
                rs.load_issues.append(Issue("error", "LOAD_FAILED", f"系统提示词无法读取：{exc}", "system-prompt", "system-prompt"))

    for tdir in sorted((root / "templates").glob("*/")) if (root / "templates").exists() else []:
        if not _within_root(tdir, root_resolved):
            rs.load_issues.append(Issue("error", "LOAD_FAILED", f"模板 {tdir.name} 路径越界", "template", tdir.name))
            continue
        if not (tdir / TEMPLATE_FILE).exists():
            continue
        try:
            tpl = load_template_dir(tdir)
            if str(tpl.id) != tdir.name:
                raise ValueError(f"template.yaml 中的 id={tpl.id} 与目录名 {tdir.name} 不一致")
            rs.templates[tpl.id] = tpl
        except (ValidationError, yaml.YAMLError, ValueError, OSError) as exc:
            rs.load_issues.append(Issue("error", "LOAD_FAILED", f"模板 {tdir.name} 无法读取：{exc}", "template", tdir.name))

    for sdir in sorted((root / "skills").glob("*/")) if (root / "skills").exists() else []:
        if not _within_root(sdir, root_resolved):
            rs.load_issues.append(Issue("error", "LOAD_FAILED", f"Skill {sdir.name} 路径越界", "skill", sdir.name))
            continue
        if not (sdir / SKILL_FILE).exists():
            continue
        try:
            skill = parse_skill_markdown((sdir / SKILL_FILE).read_text(encoding="utf-8"))
            if skill.id != sdir.name:
                raise ValueError(f"frontmatter name={skill.id} 与目录名 {sdir.name} 不一致")
            rs.skills[skill.id] = skill
        except (SkillParseError, ValidationError, yaml.YAMLError, ValueError, OSError) as exc:
            rs.load_issues.append(Issue("error", "LOAD_FAILED", f"Skill {sdir.name} 无法读取：{exc}", "skill", sdir.name))

    for afile in sorted((root / "apis").glob("*.yaml")) if (root / "apis").exists() else []:
        if not _within_root(afile, root_resolved):
            rs.load_issues.append(Issue("error", "LOAD_FAILED", f"接口 {afile.stem} 路径越界", "api", afile.stem))
            continue
        try:
            api = parse_api_yaml(afile.read_text(encoding="utf-8"))
            if api.name != afile.stem:
                raise ValueError(f"name={api.name} 与文件名 {afile.stem} 不一致")
            rs.apis[api.name] = api
        except (ValidationError, yaml.YAMLError, ValueError, OSError) as exc:
            rs.load_issues.append(Issue("error", "LOAD_FAILED", f"接口 {afile.stem} 无法读取：{exc}", "api", afile.stem))
    return rs


def read_offline_marker(path: Path) -> dict | None:
    """读取模板下线标记。"""
    try:
        return json.loads((path / OFFLINE_FILE).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

_BAD_NAME_RE = re.compile(r"[{}%\s]")
_RESERVED_FIELD_NAMES = {
    "true", "false", "none", "True", "False", "None",
    "if", "elif", "else", "endif", "for", "endfor", "in", "and", "or", "not", "is",
    "set", "block", "endblock", "macro", "endmacro", "call", "filter", "import", "from", "include", "extends",
}


def _ast_variable_lines(tree: nodes.Template | None) -> dict[str, list[int]]:
    if tree is None:
        return {}
    out: dict[str, list[int]] = {}
    for node in tree.find_all(nodes.Name):
        if node.ctx == "load" and node.lineno:
            out.setdefault(node.name, []).append(node.lineno)
    return out


def _bad_identifier(name: str) -> bool:
    """字段名/列名是否不合法（与字段名规则一致）。#Created By AiCoding(codex)"""
    return (not name.isidentifier() or name.startswith("_") or name in _RESERVED_FIELD_NAMES
            or bool(_BAD_NAME_RE.search(name)))


def _loop_attr_uses(items: Iterable[nodes.Node], var: str) -> list[tuple[str, int | None]]:
    """收集 items 及其子树中对循环变量 var 的属性/下标访问（var.列名、var["列名"]），返回 (列名, 行号)。

    #Created By AiCoding(codex)
    遇到内层 for 重新绑定同名循环变量时，只检查其迭代表达式，不再进入内层循环体，避免误报。
    """
    out: list[tuple[str, int | None]] = []
    for child in items:
        if isinstance(child, nodes.For) and isinstance(child.target, nodes.Name) and child.target.name == var:
            out.extend(_loop_attr_uses([child.iter], var))
            continue
        if isinstance(child, (nodes.Getattr, nodes.Getitem)) and isinstance(child.node, nodes.Name) \
                and child.node.name == var:
            attr: str | None = None
            if isinstance(child, nodes.Getattr):
                attr = child.attr
            elif isinstance(child.arg, nodes.Const) and isinstance(child.arg.value, str):
                attr = child.arg.value
            if attr is not None:
                out.append((attr, child.lineno))
        out.extend(_loop_attr_uses(child.iter_child_nodes(), var))
    return out


def _list_field_issues(tree: nodes.Template, d: TemplateDef) -> list[tuple[str, str, str, str, int | None]]:
    """校验正文中列表字段的用法，返回 (level, code, message, field, line)。

    #Created By AiCoding(codex)
    - {% for x in 字段 %} 只能遍历 type=list 的字段；
    - 循环体内 x.列名 / x["列名"] 必须是该列表字段声明过的列；
    - 直接输出整个列表（{{列表字段}}）给出警告。
    """
    by_name = {f.name: f for f in d.fields}
    out: list[tuple[str, str, str, str, int | None]] = []
    for loop in tree.find_all(nodes.For):
        it = loop.iter
        if not isinstance(it, nodes.Name) or it.ctx != "load" or it.name not in by_name:
            continue
        fd = by_name[it.name]
        if not fd.is_list:
            out.append(("error", "FOR_NON_LIST", f"正文第 {loop.lineno} 行用 for 循环遍历了非列表字段「{fd.name}」，"
                        "只有 type=list 的字段可以遍历", fd.name, loop.lineno))
            continue
        if not isinstance(loop.target, nodes.Name):
            out.append(("error", "LIST_LOOP_TARGET", f"正文第 {loop.lineno} 行遍历列表字段「{fd.name}」时，"
                        "循环变量只能是单个名称（如 item）", fd.name, loop.lineno))
            continue
        var = loop.target.name
        cols = set(fd.column_names())
        scope: list[nodes.Node] = list(loop.body)
        if loop.test is not None:
            scope.append(loop.test)
        seen: set[tuple[str, int | None]] = set()
        for attr, line in _loop_attr_uses(scope, var):
            if attr in cols or (attr, line) in seen:
                continue
            seen.add((attr, line))
            out.append(("error", "LIST_COLUMN_UNDEFINED",
                        f"正文第 {line} 行使用了列表字段「{fd.name}」中未定义的列：{var}.{attr}"
                        f"（可用列：{'、'.join(fd.column_names()) or '无'}）", fd.name, line))
    for output in tree.find_all(nodes.Output):
        for expr in output.nodes:
            if isinstance(expr, nodes.Name) and expr.ctx == "load" and expr.name in by_name \
                    and by_name[expr.name].is_list:
                out.append(("warning", "LIST_PRINTED", f"正文第 {expr.lineno} 行直接输出了列表字段「{expr.name}」，"
                            "列表字段应使用 {% for item in 字段 %} 逐行输出列", expr.name, expr.lineno))
    seen_if_list: set[tuple[str, int | None]] = set()
    for if_node in tree.find_all(nodes.If):
        test_names = (
            [if_node.test, *if_node.test.find_all(nodes.Name)]
            if isinstance(if_node.test, nodes.Name)
            else list(if_node.test.find_all(nodes.Name))
        )
        for nm in test_names:
            if nm.ctx == "load" and nm.name in by_name and by_name[nm.name].is_list:
                line = nm.lineno or if_node.lineno
                if (nm.name, line) not in seen_if_list:
                    seen_if_list.add((nm.name, line))
                    out.append((
                        "warning",
                        "LIST_IN_IF_CONDITION",
                        f"正文第 {line} 行在条件判断中使用了列表字段「{nm.name}」，当列表缺失（not_found）时仅布尔判断不会触发 PARTIAL 追踪；"
                        f"建议改用 {{% for item in {nm.name} %}}...{{% else %}}...{{% endfor %}}",
                        nm.name,
                        line,
                    ))
    return out


def validate_template(tpl: Template, rs: ResourceSet) -> list[Issue]:
    """校验单个模板：字段定义、正文语法与变量引用、Skill 引用。"""
    key = str(tpl.id)
    out: list[Issue] = []

    def add(level, code, msg, **kw):
        out.append(Issue(level, code, msg, "template", key, **kw))

    d: TemplateDef = tpl.definition
    if not d.name.strip():
        add("error", "NAME_EMPTY", "模板名称不能为空")

    seen_inputs: set[str] = set()
    for inp in d.inputs:
        if not inp.key.strip():
            add("error", "INPUT_KEY_EMPTY", "入参名称不能为空")
        if inp.key in seen_inputs:
            add("error", "INPUT_DUPLICATE", f"入参「{inp.key}」重复定义")
        seen_inputs.add(inp.key)
        if inp.pattern:
            try:
                re.compile(inp.pattern)
            except re.error as exc:
                add("error", "INPUT_PATTERN", f"入参「{inp.key}」的格式正则不合法：{exc}")

    seen_fields: set[str] = set()
    for f in d.fields:
        if _bad_identifier(f.name):
            add("error", "FIELD_NAME", f"字段名「{f.name}」不合法：只能使用中英文、数字和下划线，不能以下划线或数字开头，且不能为模板保留字", field=f.name)
        if f.name in seen_fields:
            add("error", "FIELD_DUPLICATE", f"字段「{f.name}」重复定义", field=f.name)
        if f.name in seen_inputs and f.evidence != "input":
            add("warning", "FIELD_SAME_AS_INPUT", f"字段「{f.name}」与入参同名，但证据类型不是 input", field=f.name)
        seen_fields.add(f.name)
        if f.type == "enum" and not f.values:
            add("error", "ENUM_EMPTY", f"枚举字段「{f.name}」没有可选值", field=f.name)
        if f.whenMissing == "value" and f.type == "enum" and f.defaultValue not in f.values:
            add("error", "DEFAULT_NOT_IN_ENUM", f"字段「{f.name}」的默认值「{f.defaultValue}」不在枚举范围内", field=f.name)
        if f.evidence == "input" and not d.inputs:
            add("error", "INPUT_EVIDENCE_NO_INPUT", f"字段「{f.name}」证据类型为 input，但模板没有定义入参", field=f.name)
        if not f.description.strip():
            add("warning", "FIELD_NO_DESCRIPTION", f"字段「{f.name}」没有说明，模型无法知道如何取值", field=f.name)
        # #Created By AiCoding(codex) 列表字段（type=list）的结构校验
        if f.is_list:
            if not f.columns:
                add("error", "LIST_NO_COLUMNS", f"列表字段「{f.name}」至少需要定义一列 columns", field=f.name)
            seen_cols: set[str] = set()
            for col in f.columns:
                if _bad_identifier(col.name) or hasattr(dict, col.name):
                    add("error", "COLUMN_NAME", f"列表字段「{f.name}」的列名「{col.name}」不合法：只能使用中英文、数字和下划线，"
                        "不能以下划线或数字开头，不能为模板保留字，也不能与 items、keys、values、get 等内置属性重名",
                        field=f.name)
                if col.name in seen_cols:
                    add("error", "COLUMN_DUPLICATE", f"列表字段「{f.name}」的列「{col.name}」重复定义", field=f.name)
                seen_cols.add(col.name)
                if col.type == "enum" and not col.values:
                    add("error", "COLUMN_ENUM_EMPTY", f"列表字段「{f.name}」的枚举列「{col.name}」没有可选值", field=f.name)
                if col.type != "enum" and col.values:
                    add("warning", "COLUMN_VALUES_IGNORED", f"列表字段「{f.name}」的列「{col.name}」不是枚举列，values 将被忽略",
                        field=f.name)
            if f.evidence not in ("quote", "derive"):
                add("error", "LIST_EVIDENCE", f"列表字段「{f.name}」的证据类型只能是 quote 或 derive", field=f.name)
            if f.whenMissing != "empty":
                add("error", "LIST_WHEN_MISSING", f"列表字段「{f.name}」的 whenMissing 必须为 empty（找不到时按空列表渲染）",
                    field=f.name)
            if f.quoteWhole:
                add("error", "LIST_QUOTE_WHOLE", f"列表字段「{f.name}」不支持 quoteWhole", field=f.name)
            if f.values:
                add("error", "LIST_VALUES", f"列表字段「{f.name}」不能填写 values，枚举值请写在列定义中", field=f.name)
        elif f.columns:
            add("error", "COLUMNS_NOT_LIST", f"字段「{f.name}」不是列表字段（type=list），不能定义 columns", field=f.name)

    tree: nodes.Template | None = None
    try:
        tree = parse_body(tpl.body)
        used = body_variables(tpl.body)
    except BodySyntaxError as exc:
        add("error", "BODY_SYNTAX", str(exc), line=exc.lineno)
        used = set()
    lines = body_variable_lines(tpl.body)
    ast_lines = _ast_variable_lines(tree)
    for name in sorted(used - seen_fields):
        line = (lines.get(name) or ast_lines.get(name) or [None])[0]
        where = f"第 {line} 行" if name in lines else (f"第 {line} 行条件判断中" if line else "条件判断中")
        add("error", "BODY_UNDEFINED_FIELD", f"正文{where}使用了未定义的字段：{name}", field=name, line=line)
    for f in d.fields:
        if f.visible and f.name not in used:
            add("warning", "VISIBLE_NOT_IN_BODY", f"字段「{f.name}」标记为显示，但正文没有使用", field=f.name)
    if tree is not None:
        for level, code, msg, fname, line in _list_field_issues(tree, d):
            add(level, code, msg, field=fname, line=line)

    for ref in d.skills:
        if ref not in rs.skills:
            add("error", "SKILL_NOT_FOUND", f"引用的 Skill「{ref}」不存在或未发布")
    if ROUTER_SKILL_ID in d.skills:
        add("warning", "ROUTER_SKILL_IN_TEMPLATE",
            f"「{ROUTER_SKILL_ID}」是聊天路由专用 Skill，不应关联到填报模板")
    if not d.skills:
        add("warning", "NO_SKILL", "模板没有关联任何 Skill，模型只能从入参和单据中取值")
    return out


def validate_skill(skill: Skill, rs: ResourceSet) -> list[Issue]:
    """校验 Skill：引用的接口必须存在；若为聊天路由专用 Skill，交叉核验在线模板覆盖。"""
    out: list[Issue] = []
    for api in skill.meta.apis:
        if api not in rs.apis:
            out.append(Issue("error", "API_NOT_FOUND", f"Skill 引用的接口「{api}」不存在或未发布", "skill", skill.id))
    if not skill.meta.description.strip():
        out.append(Issue("warning", "SKILL_NO_DESCRIPTION", "Skill 缺少 description，模型无法判断何时加载", "skill", skill.id))
    if skill.id == ROUTER_SKILL_ID:
        if skill.meta.apis:
            out.append(Issue(
                "error",
                "ROUTER_SKILL_HAS_APIS",
                f"Skill「{ROUTER_SKILL_ID}」仅用于聊天模板路由，不允许声明业务网关接口",
                "skill",
                skill.id,
            ))
        covered_ids: set[int] = set()
        for m in _ROUTER_TPL_HEADING_RE.finditer(skill.body):
            tid = int(m.group(1))
            if tid in covered_ids:
                continue
            covered_ids.add(tid)
            tpl = rs.templates.get(tid)
            if tpl is None or tpl.offline:
                reason = "已下线" if tpl is not None and tpl.offline else "不存在或未发布"
                out.append(Issue(
                    "error",
                    "ROUTER_TEMPLATE_NOT_FOUND",
                    f"Skill「{ROUTER_SKILL_ID}」引用的模板「{tid}」{reason}",
                    "skill",
                    skill.id,
                ))
        for tpl in sorted(rs.templates.values(), key=lambda t: t.id):
            if not tpl.offline and tpl.id not in covered_ids:
                out.append(Issue(
                    "warning",
                    "ROUTER_TEMPLATE_UNCOVERED",
                    f"在线模板「{tpl.id}（{tpl.name}）」未在 {ROUTER_SKILL_ID} 中维护适用说明",
                    "skill",
                    skill.id,
                ))
    return out


def validate_api(api: ApiContract) -> list[Issue]:
    """校验接口契约本身。"""
    return [Issue("error", "API_SCHEMA", msg, "api", api.name) for msg in api.schema_errors()]


def validate_all(rs: ResourceSet) -> list[Issue]:
    """校验整个资源集合（发布前执行）。"""
    issues = list(rs.load_issues)
    for tpl in rs.templates.values():
        if not tpl.offline:
            issues.extend(validate_template(tpl, rs))
    for skill in rs.skills.values():
        issues.extend(validate_skill(skill, rs))
    for api in rs.apis.values():
        issues.extend(validate_api(api))
    if not rs.system_prompt.strip():
        issues.append(Issue("error", "SYSTEM_PROMPT_EMPTY", "系统提示词不能为空", "system-prompt", "system-prompt"))
    return issues
