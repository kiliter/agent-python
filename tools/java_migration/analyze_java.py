"""Java 模板分析：列出每个模板的变量、条件比较值、规则、字段来源映射。

#Created By AiCoding(codex)
仅用于迁移前的人工审查，输出 JSON 到 stdout。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, nodes

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _java_env import (  # noqa: E402
    JAVA_FIELD_MAPPINGS as FIELD_MAPPINGS,
    JAVA_RULE_DIR as RULE_DIR,
    JAVA_TPL_DIR as TPL_DIR,
)

_TAG_RE = re.compile(r"\{%.*?%\}", re.DOTALL)


def pebble_to_jinja(text: str) -> str:
    """Pebble → Jinja2 的机械语法转换（{% %} 标签内 elseif → elif、null → none，统一 LF）。"""

    def _fix_tag(m: re.Match[str]) -> str:
        tag = m.group(0)
        tag = re.sub(r"^\{%(-?)(\s*)elseif\b", r"{%\1\2elif", tag)
        tag = re.sub(r"\bnull\b", "none", tag)
        return tag

    return _TAG_RE.sub(_fix_tag, text.replace("\r\n", "\n").replace("\r", "\n"))


def load_rules(code: str) -> dict[str, str]:
    """读取规则文件，返回 字段 → 规则原文。"""
    p = RULE_DIR / f"{code}.rule"
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for item in data.get("rule") or []:
        for k, v in item.items():
            out[str(k).strip()] = "" if v is None else str(v)
    return out


def _expr_key(expr: nodes.Expr) -> str | None:
    """提取比较表达式一侧的变量键名（含 item.列 与 item['列']）。"""
    if isinstance(expr, nodes.Name):
        return expr.name
    if isinstance(expr, nodes.Getattr) and isinstance(expr.node, nodes.Name):
        return f"{expr.node.name}.{expr.attr}"
    if (
        isinstance(expr, nodes.Getitem)
        and isinstance(expr.node, nodes.Name)
        and isinstance(expr.arg, nodes.Const)
        and isinstance(expr.arg.value, str)
    ):
        return f"{expr.node.name}.{expr.arg.value}"
    return None


def analyze(text: str) -> dict:
    """解析正文：输出变量、条件变量与比较字面量、循环（保序合并多循环同名列表列）。"""
    env = Environment()
    tree = env.parse(pebble_to_jinja(text))
    loops: dict[str, list[str]] = {}
    loop_targets: set[str] = set()
    for f in tree.find_all(nodes.For):
        if not isinstance(f.target, nodes.Name):
            continue
        loop_targets.add(f.target.name)
        if not isinstance(f.iter, nodes.Name):
            continue
        attrs = loops.setdefault(f.iter.name, [])
        for sub in f.find_all((nodes.Getattr, nodes.Getitem)):
            col: str | None = None
            if isinstance(sub, nodes.Getattr) and isinstance(sub.node, nodes.Name) and sub.node.name == f.target.name:
                col = sub.attr
            elif (
                isinstance(sub, nodes.Getitem)
                and isinstance(sub.node, nodes.Name)
                and sub.node.name == f.target.name
                and isinstance(sub.arg, nodes.Const)
                and isinstance(sub.arg.value, str)
            ):
                col = sub.arg.value
            if col and col not in attrs:
                attrs.append(col)

    printed: list[str] = []
    for out in tree.find_all(nodes.Output):
        for n in out.find_all(nodes.Name):
            if n.ctx == "load" and n.name not in loop_targets and n.name != "none" and n.name not in printed:
                printed.append(n.name)

    conditions: list[str] = []
    for br in tree.find_all((nodes.If, nodes.CondExpr)):
        test_names = [br.test] if isinstance(br.test, nodes.Name) else []
        test_names.extend(br.test.find_all(nodes.Name))
        for n in test_names:
            if n.ctx == "load" and n.name not in loop_targets and n.name != "none" and n.name not in conditions:
                conditions.append(n.name)

    compares: dict[str, list[object]] = {}
    tests: dict[str, list[str]] = {}
    for c in tree.find_all(nodes.Compare):
        lhs = c.expr
        for op in c.ops:
            rhs = op.expr
            lkey = _expr_key(lhs)
            rkey = _expr_key(rhs)
            if lkey and isinstance(rhs, nodes.Const):
                bucket = compares.setdefault(lkey, [])
                if rhs.value not in bucket:
                    bucket.append(rhs.value)
            elif rkey and op.op in ("eq", "ne") and isinstance(lhs, nodes.Const):
                bucket = compares.setdefault(rkey, [])
                if lhs.value not in bucket:
                    bucket.append(lhs.value)
            lhs = rhs
    for t in tree.find_all(nodes.Test):
        if isinstance(t.node, nodes.Name):
            bucket_t = tests.setdefault(t.node.name, [])
            if t.name not in bucket_t:
                bucket_t.append(t.name)
    return {
        "printed": printed,
        "conditions": conditions,
        "compares": compares,
        "tests": tests,
        "loops": loops,
    }


def main() -> None:
    fm = yaml.safe_load(FIELD_MAPPINGS.read_text(encoding="utf-8"))
    mappings = {k.strip().strip("[]"): v for k, v in fm["field-mappings"]["mappings"].items()}
    result = []
    for p in sorted(TPL_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        first = text.splitlines()[0]
        code = re.search(r"服务争议点\d+\s*[:：]\s*(.+)", first).group(1).strip()
        info = analyze(text)
        rules = load_rules(code)
        variables = list(
            dict.fromkeys(
                info["printed"]
                + info["conditions"]
                + list(info["compares"].keys())
                + list(info["tests"].keys())
                + list(info["loops"].keys())
            )
        )
        variables = [v for v in variables if "." not in v and v not in ("item", "none")]
        result.append(
            {
                "file": p.name,
                "code": code,
                "variables": variables,
                **info,
                "rules": rules,
                "rulesWithoutVar": [k for k in rules if k not in variables],
                "mapping": {v: mappings.get(v) for v in variables if mappings.get(v)},
            }
        )
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
