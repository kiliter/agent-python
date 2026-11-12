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

JAVA_RES = Path("/Users/zhangjialin/IdeaProjects/agent/pdf-agent-parse/src/main/resources")
TPL_DIR = JAVA_RES / "template/md"
RULE_DIR = JAVA_RES / "agent/rule"


def pebble_to_jinja(text: str) -> str:
    """Pebble → Jinja2 的机械语法转换（仅 elseif → elif）。"""
    return re.sub(r"\{%(-?)\s*elseif\b", r"{%\1 elif", text)


def load_rules(code: str) -> dict[str, str]:
    """读取规则文件，返回 字段 → 规则原文。"""
    p = RULE_DIR / f"{code}.rule"
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for item in data.get("rule") or []:
        for k, v in item.items():
            out[str(k).strip()] = str(v)
    return out


def analyze(text: str) -> dict:
    """解析正文：输出变量、条件变量与比较字面量、循环。"""
    env = Environment()
    tree = env.parse(pebble_to_jinja(text))
    printed: list[str] = []
    for out in tree.find_all(nodes.Output):
        for n in out.find_all(nodes.Name):
            if n.name not in printed:
                printed.append(n.name)
    compares: dict[str, list[str]] = {}
    tests: dict[str, list[str]] = {}
    for c in tree.find_all(nodes.Compare):
        left = c.expr
        for op in c.ops:
            if isinstance(op.expr, nodes.Const):
                key = left.name if isinstance(left, nodes.Name) else (
                    f"{left.node.name}.{left.attr}" if isinstance(left, nodes.Getattr) else str(left))
                compares.setdefault(key, [])
                if op.expr.value not in compares[key]:
                    compares[key].append(op.expr.value)
    for t in tree.find_all(nodes.Test):
        if isinstance(t.node, nodes.Name):
            tests.setdefault(t.node.name, []).append(t.name)
    loops = {}
    for f in tree.find_all(nodes.For):
        attrs = sorted({g.attr for g in f.find_all(nodes.Getattr)
                        if isinstance(g.node, nodes.Name) and g.node.name == f.target.name})
        loops[f.iter.name] = attrs
    return {"printed": printed, "compares": compares, "tests": tests, "loops": loops}


def main() -> None:
    fm = yaml.safe_load((JAVA_RES / "agent/config/field-mappings.yml").read_text(encoding="utf-8"))
    mappings = {k.strip("[]"): v for k, v in fm["field-mappings"]["mappings"].items()}
    result = []
    for p in sorted(TPL_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        first = text.splitlines()[0]
        code = re.search(r"服务争议点\d+\s*[:：]\s*(.+)", first).group(1).strip()
        info = analyze(text)
        rules = load_rules(code)
        variables = list(dict.fromkeys(info["printed"] + list(info["compares"].keys()) + list(info["tests"].keys())
                                       + list(info["loops"].keys())))
        variables = [v for v in variables if "." not in v and v != "item"]
        result.append({
            "file": p.name, "code": code, "variables": variables, **info,
            "rules": rules,
            "rulesWithoutVar": [k for k in rules if k not in variables],
            "mapping": {v: mappings.get(v) for v in variables if mappings.get(v)},
        })
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
