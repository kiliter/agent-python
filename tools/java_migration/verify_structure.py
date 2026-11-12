"""迁移一致性校验②：结构与规则一致性（静态检查，不调用模型）。

#Created By AiCoding(codex)
检查项：
  S1 模板集合：Python 模板与 Java 模板一一对应，ID 与 Java 资源库（template_ids.yaml）一致，名称 = Java 模板编码。
  S2 正文：Python 正文 == Java 正文经转换（elseif→elif、null→none、CRLF→LF，以及模板 115 违约责任占位符守卫）的结果，逐字相同。
  S3 字段集合：Python 字段 == Java 正文变量 ∪ Java 隐式依赖字段（规则中 {{X}} 引用、映射为 SKILL 的字段），
     且隐式依赖字段为中间字段（visible=false）；正文直接输出的字段 visible=true。
  S4 规则：Java 规则中每条“正文变量: 规则”的原文都逐字出现在对应 Python 字段说明中。
  S5 Skill：Java 字段映射为 SKILL 的字段，其 Skill（及 Java 依赖 Skill）都在 Python 模板的 skills 中，
     且 Python 资源中存在同名 Skill；Skill 声明的接口都存在。
  S6 列表字段：Java 正文 for 循环中 item.xxx 用到的属性都是 Python 列表字段的列。
  S7 发布校验：Python 资源集合 validate_all() 零 error 且零 warning。
  S8 占位符恒真分支门禁（AST）：扫描全部 body.md.j2 的 nodes.If 条件——若引用了 whenMissing=="placeholder" 的字段做真值判断或
     != "" / != none 比较，必须同时排除 "{{字段名}}"（或仅使用 is hasDigit / 具体字面量 == / in），否则直接报错。
  S9 枚举比较字面量门禁（AST）：扫描 enum 字段（含列表 enum 列）在 nodes.Compare 中的常量字面量是否在 values 内；
     除已显式登记的 Java 原模板历史问题白名单外，任何未知失配直接报错。
用法：uv run python tools/java_migration/verify_structure.py [--resources DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jinja2 import nodes

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import generate as gen  # noqa: E402
from report_agent.domain.jinja_env import parse_body  # noqa: E402
from report_agent.domain.resources import load_resource_dir, validate_all  # noqa: E402
from report_agent.domain.template import Template  # noqa: E402

# 源自上游 Java 原模板（增值业务扣费争议处理模板.md 第 38 行）的历史枚举失配白名单，已登记待业务侧确认。
KNOWN_UPSTREAM_ENUM_MISMATCHES: dict[tuple[int, str], frozenset[str]] = {
    (116, "受理渠道"): frozenset({"合作方平台", "电视端", "APP", "短信", "一级电渠"}),
}


def _flatten_and(expr: nodes.Expr) -> list[nodes.Expr]:
    """展开顶层 and 合取项列表。#Created By AiCoding(codex)"""
    if isinstance(expr, nodes.And):
        return [*_flatten_and(expr.left), *_flatten_and(expr.right)]
    return [expr]


def _excludes_placeholder(conjuncts: list[nodes.Expr], field_name: str) -> bool:
    """检查合取项中是否显式排除了占位符字面量 '{{字段名}}'。#Created By AiCoding(codex)"""
    ph = f"{{{{{field_name}}}}}"
    for item in conjuncts:
        if not isinstance(item, nodes.Compare) or len(item.ops) != 1:
            continue
        op = item.ops[0]
        if op.op == "ne":
            if (isinstance(item.expr, nodes.Name) and item.expr.name == field_name
                    and isinstance(op.expr, nodes.Const) and op.expr.value == ph):
                return True
            if (isinstance(item.expr, nodes.Const) and item.expr.value == ph
                    and isinstance(op.expr, nodes.Name) and op.expr.name == field_name):
                return True
        if op.op == "notin" and isinstance(item.expr, nodes.Name) and item.expr.name == field_name \
                and isinstance(op.expr, (nodes.List, nodes.Tuple)):
            vals = [x.value for x in op.expr.items if isinstance(x, nodes.Const)]
            if ph in vals:
                return True
    return False


def _is_safe_placeholder_expr(expr: nodes.Expr, field_name: str) -> bool:
    """在不带 `!= '{{字段名}}'` 守卫时，判断子表达式对 placeholder 字段的引用是否天然排除占位符。#Created By AiCoding(codex)"""
    ph = f"{{{{{field_name}}}}}"
    if isinstance(expr, (nodes.And, nodes.Or)):
        return _is_safe_placeholder_expr(expr.left, field_name) and _is_safe_placeholder_expr(expr.right, field_name)
    # 若该分支根本未引用目标字段，则不影响目标字段安全性
    refs = [n for n in expr.find_all(nodes.Name) if n.ctx == "load" and n.name == field_name]
    if not refs:
        return True
    # 1) `字段 is hasDigit`（字段名自身不含数字时，占位符 '{{字段}}' 必为 False）
    if (isinstance(expr, nodes.Test) and expr.name == "hasDigit"
            and isinstance(expr.node, nodes.Name) and expr.node.name == field_name
            and not any(ch.isdigit() for ch in field_name)):
        return True
    # 2) `字段 == '具体字面量'` 或 `字段 in ['字面量1', ...]`（且字面量不等于 '{{字段}}'）
    if isinstance(expr, nodes.Compare) and len(expr.ops) == 1:
        op = expr.ops[0]
        if op.op == "eq":
            if (isinstance(expr.expr, nodes.Name) and expr.expr.name == field_name
                    and isinstance(op.expr, nodes.Const) and op.expr.value != ph):
                return True
            if (isinstance(expr.expr, nodes.Const) and expr.expr.value != ph
                    and isinstance(op.expr, nodes.Name) and op.expr.name == field_name):
                return True
        if op.op == "in" and isinstance(expr.expr, nodes.Name) and expr.expr.name == field_name \
                and isinstance(op.expr, (nodes.List, nodes.Tuple)) \
                and all(isinstance(x, nodes.Const) and x.value != ph for x in op.expr.items):
            return True
    return False


def check_s8_placeholder_if_guards(tpl: Template, tag: str) -> list[str]:
    """S8：拦截 whenMissing=='placeholder' 字段在 If 条件中未排除 '{{字段名}}' 的恒真分支。#Created By AiCoding(codex)"""
    errs: list[str] = []
    tree = parse_body(tpl.body)
    placeholder_fields = {
        f.name: f for f in tpl.definition.fields if not f.is_list and f.whenMissing == "placeholder"
    }
    for if_node in tree.find_all(nodes.If):
        referenced = sorted({
            n.name for n in if_node.test.find_all(nodes.Name)
            if n.ctx == "load" and n.name in placeholder_fields
        })
        if not referenced:
            continue
        conjuncts = _flatten_and(if_node.test)
        for fname in referenced:
            if _excludes_placeholder(conjuncts, fname):
                continue
            if _is_safe_placeholder_expr(if_node.test, fname):
                continue
            errs.append(
                f"S8 {tag} 第 {if_node.lineno} 行：字段「{fname}」配置为 whenMissing=placeholder，"
                f"在 {{% if %}} 条件中做真值或非空判断但未排除占位符 \"{{{{{fname}}}}}\"，会导致缺失时分支恒真"
            )
    return errs


def _extract_compared_consts(op_name: str, expr: nodes.Expr) -> list[str]:
    """提取 Compare 右侧（或左侧）参与比较的字符串字面量。#Created By AiCoding(codex)"""
    if op_name in ("eq", "ne") and isinstance(expr, nodes.Const) and isinstance(expr.value, str):
        return [expr.value]
    if op_name in ("in", "notin") and isinstance(expr, (nodes.List, nodes.Tuple)):
        return [x.value for x in expr.items if isinstance(x, nodes.Const) and isinstance(x.value, str)]
    return []


def check_s9_enum_compare_literals(tpl: Template, tag: str) -> tuple[list[str], list[str]]:
    """S9：校验 enum 字段（及列表 enum 列）在 Compare 中的字面量是否属于可选值集合。#Created By AiCoding(codex)"""
    errs: list[str] = []
    whitelisted_notes: list[str] = []
    tree = parse_body(tpl.body)
    enum_fields = {f.name: set(f.values) for f in tpl.definition.fields if f.type == "enum"}
    list_enum_cols: dict[str, dict[str, set[str]]] = {
        f.name: {c.name: set(c.values) for c in f.columns if c.type == "enum"}
        for f in tpl.definition.fields if f.is_list
    }

    # 1) 顶层 enum 字段比较
    for cmp_node in tree.find_all(nodes.Compare):
        if isinstance(cmp_node.expr, nodes.Name) and cmp_node.expr.ctx == "load" and cmp_node.expr.name in enum_fields:
            fname = cmp_node.expr.name
            allowed = enum_fields[fname]
            ph = f"{{{{{fname}}}}}"
            for op in cmp_node.ops:
                for lit in _extract_compared_consts(op.op, op.expr):
                    if op.op == "ne" and lit in ("", ph):
                        continue
                    if lit not in allowed:
                        known = KNOWN_UPSTREAM_ENUM_MISMATCHES.get((tpl.id, fname), frozenset())
                        if lit in known:
                            whitelisted_notes.append(
                                f"S9 [已知上游白名单] {tag} 第 {cmp_node.lineno} 行：字段「{fname}」比较历史 Java 字面量 "
                                f"{lit!r}（可选值 {sorted(allowed)}，待业务侧确认）"
                            )
                        else:
                            errs.append(
                                f"S9 {tag} 第 {cmp_node.lineno} 行：枚举字段「{fname}」比较字面量 {lit!r} "
                                f"不在 values {sorted(allowed)} 内"
                            )
        elif len(cmp_node.ops) == 1 and isinstance(cmp_node.expr, nodes.Const) and isinstance(cmp_node.expr.value, str):
            op = cmp_node.ops[0]
            if op.op in ("eq", "ne") and isinstance(op.expr, nodes.Name) and op.expr.name in enum_fields:
                fname = op.expr.name
                lit = cmp_node.expr.value
                allowed = enum_fields[fname]
                ph = f"{{{{{fname}}}}}"
                if not (op.op == "ne" and lit in ("", ph)) and lit not in allowed:
                    known = KNOWN_UPSTREAM_ENUM_MISMATCHES.get((tpl.id, fname), frozenset())
                    if lit in known:
                        whitelisted_notes.append(
                            f"S9 [已知上游白名单] {tag} 第 {cmp_node.lineno} 行：字段「{fname}」比较历史 Java 字面量 "
                            f"{lit!r}（可选值 {sorted(allowed)}，待业务侧确认）"
                        )
                    else:
                        errs.append(
                            f"S9 {tag} 第 {cmp_node.lineno} 行：枚举字段「{fname}」比较字面量 {lit!r} "
                            f"不在 values {sorted(allowed)} 内"
                        )

    # 2) 列表字段循环内 enum 列比较
    for loop_node in tree.find_all(nodes.For):
        if not (isinstance(loop_node.iter, nodes.Name) and loop_node.iter.name in list_enum_cols
                and isinstance(loop_node.target, nodes.Name)):
            continue
        list_name = loop_node.iter.name
        loop_var = loop_node.target.name
        col_map = list_enum_cols[list_name]
        for cmp_node in loop_node.find_all(nodes.Compare):
            if (isinstance(cmp_node.expr, nodes.Getattr)
                    and isinstance(cmp_node.expr.node, nodes.Name)
                    and cmp_node.expr.node.name == loop_var
                    and cmp_node.expr.attr in col_map):
                cname = cmp_node.expr.attr
                allowed = col_map[cname]
                for op in cmp_node.ops:
                    for lit in _extract_compared_consts(op.op, op.expr):
                        if op.op == "ne" and lit == "":
                            continue
                        if lit not in allowed:
                            errs.append(
                                f"S9 {tag} 第 {cmp_node.lineno} 行：列表「{list_name}」枚举列「{cname}」比较字面量 "
                                f"{lit!r} 不在 values {sorted(allowed)} 内"
                            )
    return errs, whitelisted_notes


def main() -> int:
    """执行模板结构、规则、AST 静态门禁与发布校验（要求 0 errors, 0 warnings）。#Created By AiCoding(codex)"""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resources", default=str(ROOT / "src/report_agent/seed"), help="Python 资源目录")
    args = ap.parse_args()
    rs = load_resource_dir(Path(args.resources))
    ids = gen.load_template_ids()
    mappings = gen.load_field_mappings()
    deps = gen.load_skill_dependencies()
    errors: list[str] = []
    s9_notes: list[str] = []
    checked = 0

    java = {}
    for p in sorted(gen.TPL_DIR.glob("*.md")):
        raw = p.read_text(encoding="utf-8")
        java[gen._RULE_KEY_RE.search(raw).group(1).strip()] = raw

    # S1
    py_by_name = {t.name: t for t in rs.templates.values()}
    if set(java) != set(py_by_name):
        errors.append(f"S1 模板集合不一致：仅 Java {sorted(set(java) - set(py_by_name))}，仅 Python {sorted(set(py_by_name) - set(java))}")
    if set(ids) != set(java):
        errors.append(f"S1 template_ids.yaml 与 Java 模板不一致：{sorted(set(ids) ^ set(java))}")

    for code, raw in sorted(java.items(), key=lambda kv: ids.get(kv[0], 0)):
        tpl = py_by_name.get(code)
        if tpl is None:
            continue
        checked += 1
        tag = f"{tpl.id} {code}"
        if tpl.id != ids.get(code):
            errors.append(f"S1 {tag}：ID {tpl.id} 与 Java 资源库 {ids.get(code)} 不一致")
        # S2
        expected_body = gen.pebble_to_jinja(raw, code=code)
        if tpl.body.replace("\r\n", "\n") != expected_body:
            errors.append(f"S2 {tag}：正文与 Java 正文的转换结果不一致")
        # S3
        info = gen.BodyInfo(expected_body)
        rules = gen.load_rules(code)
        java_vars = set(info.all_vars)
        implicit = set()
        for v in java_vars:
            for dep in gen._RULE_VAR_RE.findall(rules.get(v, "") or ""):
                dep = dep.strip()
                if dep not in java_vars and (mappings.get(dep) or {}).get("sourceType") == "SKILL" and dep in {
                        f.name for f in tpl.definition.fields}:
                    implicit.add(dep)
        py_fields = {f.name: f for f in tpl.definition.fields}
        if set(py_fields) != java_vars | implicit:
            errors.append(f"S3 {tag}：字段集合不一致：缺少 {sorted((java_vars | implicit) - set(py_fields))}，"
                          f"多出 {sorted(set(py_fields) - java_vars - implicit)}")
        for name, f in py_fields.items():
            should_visible = name in info.printed
            if f.visible != should_visible:
                errors.append(f"S3 {tag}：字段「{name}」visible={f.visible}，应为 {should_visible}")
        # S4
        for name, rule in rules.items():
            if name in py_fields and rule.strip() not in py_fields[name].description:
                errors.append(f"S4 {tag}：字段「{name}」说明中缺少 Java 规则原文")
        # S5
        need: list[str] = []
        for name in java_vars | implicit:
            mp = mappings.get(name) or {}
            if mp.get("sourceType") == "SKILL" and mp.get("skillName"):
                need.append(mp["skillName"])
        need = gen.expand_skill_deps(need, deps)
        missing_skills = [s for s in need if s not in tpl.definition.skills]
        if missing_skills:
            errors.append(f"S5 {tag}：Java 需要的 Skill 未列入 skills：{missing_skills}")
        for s in tpl.definition.skills:
            if s not in rs.skills:
                errors.append(f"S5 {tag}：Skill「{s}」在 Python 资源中不存在")
        # S6
        for list_name, attrs in info.loops.items():
            f = py_fields.get(list_name)
            if f is None or f.type != "list":
                errors.append(f"S6 {tag}：循环变量「{list_name}」不是列表字段")
                continue
            cols = {c.name for c in f.columns}
            if set(attrs) - cols:
                errors.append(f"S6 {tag}：列表「{list_name}」缺少列 {sorted(set(attrs) - cols)}")
        # S8 & S9
        errors.extend(check_s8_placeholder_if_guards(tpl, tag))
        s9_errs, notes = check_s9_enum_compare_literals(tpl, tag)
        errors.extend(s9_errs)
        s9_notes.extend(notes)

    for s in rs.skills.values():
        for api in s.meta.apis:
            if api not in rs.apis:
                errors.append(f"S5 Skill「{s.id}」引用的接口「{api}」不存在")

    # S7：要求发布校验零 error 且零 warning
    issues = validate_all(rs)
    warnings = [i for i in issues if i.level == "warning"]
    for i in issues:
        errors.append(f"S7 [{i.level}] {i.kind}:{i.key} {i.code} {i.message}")

    for note in s9_notes:
        print(f"  ℹ {note}")
    print(f"检查模板 {checked} 个，Skill {len(rs.skills)} 个，接口 {len(rs.apis)} 个；"
          f"发布校验 error {len(issues) - len(warnings)} 条，warning {len(warnings)} 条")
    if errors:
        print(f"✗ 不一致 {len(errors)} 项：")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("✓ 结构、AST 静态门禁（S8/S9）与规则一致性检查全部通过（0 errors, 0 warnings）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
