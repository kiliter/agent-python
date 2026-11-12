"""正文渲染上下文：把交卷结果整理成 Jinja2 渲染用的字段值。

#Created By AiCoding(codex)
这是生产渲染的唯一路径：runner._finish 与迁移一致性校验脚本（tools/java_migration/verify_render.py）
都通过 build_render_context 构造上下文，再用 domain.jinja_env.render_body 渲染。
  - 普通字段：找到 → TrackedValue(值)；找不到 → 按 whenMissing 渲染（占位 {{字段}} / 空 / 默认值），并标记 missing；
  - 列表字段（type=list）：找到（含合法空列表 []） → TrackedList(行字典列表, 字段名, missing=False)；
    找不到 → TrackedList([], 字段名, missing=True)，在生效分支执行 {% for %} 时记入 used 以触发 PARTIAL 判定。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..domain.jinja_env import TrackedList, TrackedValue
from ..domain.template import FieldDef, Template
from .evidence import scalar_to_str


@dataclass
class FieldRender:
    """单个字段的渲染结果。value 为对外展示的值（文本、行列表或 None），context_value 为放入渲染上下文的值。"""

    found: bool
    value: Any
    rendered: str
    context_value: Any


def missing_value(f: FieldDef) -> str:
    """找不到时渲染的值。"""
    if f.whenMissing == "empty":
        return ""
    if f.whenMissing == "value":
        return f.defaultValue
    return "{{" + f.name + "}}"


def list_rows(f: FieldDef, raw: Any) -> list[dict[str, Any]]:
    """把列表字段的提交值整理为行字典列表（只保留声明的列，非字典行丢弃）。"""
    if not isinstance(raw, list):
        return []
    cols = f.column_names()
    return [{c: row.get(c) for c in cols} for row in raw if isinstance(row, dict)]


def field_render(f: FieldDef, ans: Any) -> FieldRender:
    """按字段定义与该字段的结论（{status, value, ...}，可为 None）计算渲染值。#Created By AiCoding(codex)"""
    ans = ans if isinstance(ans, dict) else {}
    raw_val = ans.get("value")
    if f.is_list:
        if ans.get("status") == "found" and isinstance(raw_val, list):
            rows = list_rows(f, raw_val)
            ctx_rows = [
                {
                    c.name: TrackedValue(
                        "" if isinstance(row.get(c.name), (list, dict)) else scalar_to_str(row.get(c.name)),
                        f.name,
                    )
                    for c in f.columns
                }
                for row in rows
            ]
            return FieldRender(
                True,
                rows,
                json.dumps(rows, ensure_ascii=False),
                TrackedList(ctx_rows, f.name, missing=False),
            )
        return FieldRender(False, None, "", TrackedList([], f.name, missing=True))
    val_str = "" if isinstance(raw_val, (list, dict)) else scalar_to_str(raw_val)
    found = ans.get("status") == "found" and raw_val is not None and not isinstance(raw_val, (list, dict)) and val_str.strip() != ""
    rendered = val_str if found else missing_value(f)
    return FieldRender(found, val_str if found else None, rendered, TrackedValue(rendered, f.name, missing=not found))


def build_render_context(template: Template, report: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """生成正文渲染上下文：字段名 → TrackedValue（普通字段）或行字典列表（列表字段）。

    report 为交卷结果（字段名 → {status, value, evidence, reasoning}），为 None 时全部按找不到处理。
    """
    report = report if isinstance(report, dict) else {}
    return {f.name: field_render(f, report.get(f.name)).context_value for f in template.definition.fields}
