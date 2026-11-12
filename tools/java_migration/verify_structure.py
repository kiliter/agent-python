"""迁移一致性校验②：结构与规则一致性（静态检查，不调用模型）。

#Created By AiCoding(codex)
检查项：
  S1 模板集合：Python 模板与 Java 模板一一对应，ID 与 Java 资源库（template_ids.yaml）一致，名称 = Java 模板编码。
  S2 正文：Python 正文 == Java 正文经机械转换（elseif→elif、null→none、CRLF→LF）的结果，逐字相同。
  S3 字段集合：Python 字段 == Java 正文变量 ∪ Java 隐式依赖字段（规则中 {{X}} 引用、映射为 SKILL 的字段），
     且隐式依赖字段为中间字段（visible=false）；正文直接输出的字段 visible=true。
  S4 规则：Java 规则中每条“正文变量: 规则”的原文都逐字出现在对应 Python 字段说明中。
  S5 Skill：Java 字段映射为 SKILL 的字段，其 Skill（及 Java 依赖 Skill）都在 Python 模板的 skills 中，
     且 Python 资源中存在同名 Skill；Skill 声明的接口都存在。
  S6 列表字段：Java 正文 for 循环中 item.xxx 用到的属性都是 Python 列表字段的列。
  S7 发布校验：Python 资源集合 validate_all() 零 error 且零 warning。
用法：uv run python tools/java_migration/verify_structure.py [--resources DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import generate as gen  # noqa: E402
from report_agent.domain.resources import load_resource_dir, validate_all  # noqa: E402


def main() -> int:
    """执行模板结构、规则与发布校验（要求 0 errors, 0 warnings）。#Created By AiCoding(codex)"""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resources", default=str(ROOT / "src/report_agent/seed"), help="Python 资源目录")
    args = ap.parse_args()
    rs = load_resource_dir(Path(args.resources))
    ids = gen.load_template_ids()
    mappings = gen.load_field_mappings()
    deps = gen.load_skill_dependencies()
    errors: list[str] = []
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
        expected_body = gen.pebble_to_jinja(raw)
        if tpl.body.replace("\r\n", "\n") != expected_body:
            errors.append(f"S2 {tag}：正文与 Java 正文的机械转换结果不一致")
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

    for s in rs.skills.values():
        for api in s.meta.apis:
            if api not in rs.apis:
                errors.append(f"S5 Skill「{s.id}」引用的接口「{api}」不存在")

    # S7：要求发布校验零 error 且零 warning
    issues = validate_all(rs)
    warnings = [i for i in issues if i.level == "warning"]
    for i in issues:
        errors.append(f"S7 [{i.level}] {i.kind}:{i.key} {i.code} {i.message}")

    print(f"检查模板 {checked} 个，Skill {len(rs.skills)} 个，接口 {len(rs.apis)} 个；"
          f"发布校验 error {len(issues) - len(warnings)} 条，warning {len(warnings)} 条")
    if errors:
        print(f"✗ 不一致 {len(errors)} 项：")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("✓ 结构与规则一致性检查全部通过（0 errors, 0 warnings）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
