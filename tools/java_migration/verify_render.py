"""迁移一致性校验①：渲染等价（Java Pebble vs Python Jinja2）。

#Created By AiCoding(codex)
对每个迁移后的模板生成多组“字段结论”场景，分别交给：
  - Java：真实的 PebbleTemplateEngine.render()（Java 项目编译产物 + 发布包依赖，harness/PebbleRenderHarness.java）
  - Python：生产代码 build_render_context() + render_body()
逐字比对渲染结果。仅做以下已确认的归一化/修复预期核对：
  1. CRLF → LF；Java 缺失占位符 `{{ 字段 }}` → Python 的 `{{字段}}`。
  2. 模板 120（宽带业务续约争议类）中 `有设备押金` 缺失，以及模板 111（合约套餐提前解约处理类）、
     114（合约活动提前解约类）、115（合约活动违约争议处理模板）中 `违约责任` 缺失时，Java PebbleTemplateEngine
     因把空值写成非空字符串 `"{{ 字段 }}"` 导致条件恒真/死分支；Python 侧已修复为缺失时不进入违约段落
     （120 进入 `{% else %}` 输出 `- 无<商品名称>设备押金记录。`，115 第 19 行仍保留 `{{违约责任}}` 占位符），
     核对修复段落外其余全部文本与 Pebble 逐字一致。

场景覆盖：全部找到（不含数字 / 含数字两套值）、全部找不到、每个枚举字段逐值（含找不到）、
条件置空标量字段缺失、枚举字段全组合（组合数不超过 512 时）、列表字段空列表(found) / 缺失(not_found) / 1 行 / 3 行。

用法：uv run python tools/java_migration/verify_render.py [--resources DIR] [--report FILE]
退出码：全部一致为 0，否则为 1。
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from report_agent.domain.jinja_env import render_body  # noqa: E402
from report_agent.domain.resources import load_resource_dir  # noqa: E402
from report_agent.domain.template import FieldDef, Template  # noqa: E402

try:  # 生产渲染上下文构造（平台改造后提供）
    from report_agent.runtime.render import build_render_context  # type: ignore  # noqa: E402
except ImportError:  # pragma: no cover
    from report_agent.runtime.runner import build_render_context  # type: ignore  # noqa: E402

JAVA_AGENT = Path(os.environ.get("JAVA_AGENT_HOME", "/Users/zhangjialin/IdeaProjects/agent"))
JAVA_TPL_DIR = JAVA_AGENT / "pdf-agent-parse/src/main/resources/template/md"
JAVA_CLASSES = JAVA_AGENT / "pdf-agent-parse/target/classes"
JAVA_LIB = JAVA_AGENT / "release/windows/pdf-agent-parse-windows/lib"
HARNESS_DIR = HERE / "harness"
_RULE_KEY_RE = re.compile(r"服务争议点\d+\s*[:：]\s*([^\r\n]+)")
_JAVA_PLACEHOLDER_RE = re.compile(r"\{\{ (\S+?) \}\}")
MAX_COMBOS = 512
_DEPOSIT_IF_LINE = "- 设备押金{押金金额}元已于{退还日期}退还至{退还账户}。"
_TPL111_BREACH_TAIL = "\n因活动未到期，客户如需办理套餐变更，需按协议违约条款支付违约金中断活动后办理。\n\n"
_TPL114_BREACH_TAIL = "\n因活动未到期，客户如需提前中断活动，需按协议违约条款支付违约金后办理。\n\n"


# ---------------------------------------------------------------------------
# 场景生成
# ---------------------------------------------------------------------------

def _value(f: FieldDef, variant: int) -> str:
    """字段的“找到”值：variant 0 不含数字，variant 1 含数字（覆盖 hasDigit 分支）。"""
    if f.type == "enum":
        return f.values[0]
    return f"〔{f.name}〕" if variant == 0 else f"{f.name}88元/月"


def _rows(f: FieldDef, n: int) -> list[dict[str, str]]:
    """列表字段的 n 行数据，枚举列轮换取值。"""
    rows = []
    for i in range(n):
        row = {}
        for c in f.columns:  # type: ignore[attr-defined]
            if getattr(c, "type", "string") == "enum" and c.values:
                row[c.name] = c.values[i % len(c.values)]
            else:
                row[c.name] = f"{c.name}{i + 1}"
        rows.append(row)
    return rows


def _found(value: Any) -> dict[str, Any]:
    return {"status": "found", "value": value, "evidence": [], "reasoning": ""}


_MISSING = {"status": "not_found", "value": None, "evidence": [], "reasoning": ""}


def scenarios(tpl: Template) -> list[tuple[str, dict[str, dict[str, Any]]]]:
    """生成场景：名称 → 报告（字段名 → 结论）。#Created By AiCoding(codex)"""
    fields = tpl.definition.fields
    enums = [f for f in fields if f.type == "enum"]
    lists = [f for f in fields if f.type == "list"]
    cond_scalars = [
        f for f in fields
        if f.type not in ("enum", "list")
        and ((not f.visible and f.whenMissing == "empty") or f'!= "{{{{{f.name}}}}}"' in tpl.body)
    ]

    def base(variant: int, list_rows: int = 3) -> dict[str, dict[str, Any]]:
        rep = {}
        for f in fields:
            rep[f.name] = _found(_rows(f, list_rows)) if f.type == "list" else _found(_value(f, variant))
        return rep

    out: list[tuple[str, dict[str, dict[str, Any]]]] = [
        ("全部找到", base(0)),
        ("全部找到-含数字", base(1)),
        ("全部找不到", {f.name: dict(_MISSING) for f in fields}),
    ]
    for f in cond_scalars:
        for variant in (0, 1):
            rep = base(variant)
            rep[f.name] = dict(_MISSING)
            out.append((f"{f.name}=找不到(v{variant})", rep))
    for f in enums:
        for v in [*f.values, None]:
            rep = base(0)
            rep[f.name] = _found(v) if v is not None else dict(_MISSING)
            out.append((f"{f.name}={v if v is not None else '找不到'}", rep))
    choices = [[*f.values, None] for f in enums]
    total = 1
    for c in choices:
        total *= len(c)
    if enums and total <= MAX_COMBOS:
        for combo in itertools.product(*choices):
            for variant in (0, 1):
                rep = base(variant)
                for f, v in zip(enums, combo):
                    rep[f.name] = _found(v) if v is not None else dict(_MISSING)
                label = ",".join(f"{f.name}={v if v is not None else '∅'}" for f, v in zip(enums, combo))
                out.append((f"组合[{label}]v{variant}", rep))
    for f in lists:
        rep_empty_found = base(0)
        rep_empty_found[f.name] = _found([])
        out.append((f"{f.name}空列表(found)", rep_empty_found))
        for n in (0, 1):
            rep = base(0)
            rep[f.name] = _found(_rows(f, n)) if n else dict(_MISSING)
            out.append((f"{f.name}行数={n}", rep))
    return out


def java_values(tpl: Template, report: dict[str, dict[str, Any]]) -> dict[str, str]:
    """把场景换算为 Java 的最终 KV（与 Java 链路对应）：
    找到 → 值（列表 → JSON 数组字符串）；找不到 → whenMissing=value 时为默认值（Java 链路保证有值的字段），
    列表为 "[]"，其余不传（Java 渲染为占位符）。"""
    kv: dict[str, str] = {}
    for f in tpl.definition.fields:
        ans = report.get(f.name) or _MISSING
        val = ans.get("value")
        found = ans.get("status") == "found" and val not in (None, "", [])
        if f.type == "list":
            kv[f.name] = json.dumps(val if found else [], ensure_ascii=False)
        elif found:
            kv[f.name] = str(val)
        elif f.whenMissing == "value":
            kv[f.name] = f.defaultValue
        elif f.whenMissing == "empty":
            kv[f.name] = ""
    return kv


def _apply_intentional_fixes(tpl: Template, report: dict[str, dict[str, Any]], ctx: dict[str, Any], java_text: str) -> str:
    """对主动修复的 Java 渲染占位符恒真/死分支缺陷，换算修复后的期望文本再逐字比对。#Created By AiCoding(codex)"""
    if tpl.id == 120:
        dep_ans = report.get("有设备押金") or _MISSING
        dep_found = dep_ans.get("status") == "found" and bool(dep_ans.get("value"))
        if not dep_found:
            prod = str(ctx.get("商品名称", "{{商品名称}}"))
            return java_text.replace(_DEPOSIT_IF_LINE, f"- 无{prod}设备押金记录。", 1)
    if tpl.id in (111, 114, 115):
        breach_ans = report.get("违约责任") or _MISSING
        breach_found = breach_ans.get("status") == "found" and bool(breach_ans.get("value"))
        if not breach_found:
            if tpl.id == 111 and java_text.endswith(_TPL111_BREACH_TAIL):
                return java_text[: -len(_TPL111_BREACH_TAIL)]
            if tpl.id == 114 and java_text.endswith(_TPL114_BREACH_TAIL):
                return java_text[: -len(_TPL114_BREACH_TAIL)]
            if tpl.id == 115:
                act = str(ctx.get("违约行为", "{{违约行为}}"))
                tm = str(ctx.get("违约时间", "{{违约时间}}"))
                tpl115_tail = f"\n1. 违约行为：{act}2. 违约时间：{tm}\n因活动期间，客户号码{act}，故根据协议约定，无法享受活动优惠。\n\n"
                if java_text.endswith(tpl115_tail):
                    return java_text[: -len(tpl115_tail)]
    return java_text


# ---------------------------------------------------------------------------
# Java 侧
# ---------------------------------------------------------------------------

def _java_cp() -> str:
    build = HARNESS_DIR / "build"
    cp = f"{JAVA_CLASSES}{os.pathsep}{JAVA_LIB}/*"
    if not (build / "PebbleRenderHarness.class").exists():
        build.mkdir(exist_ok=True)
        subprocess.run(["javac", "-encoding", "UTF-8", "-cp", cp, "-d", str(build),
                        str(HARNESS_DIR / "PebbleRenderHarness.java")], check=True)
    return f"{build}{os.pathsep}{cp}"


def render_java(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """批量调用 Java PebbleTemplateEngine.render()。"""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.json"
        subprocess.run(["java", "-cp", _java_cp(), "PebbleRenderHarness", str(out)],
                       input=json.dumps({"cases": cases}, ensure_ascii=False).encode("utf-8"),
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return json.loads(out.read_text(encoding="utf-8"))


def java_template_bodies() -> dict[str, str]:
    """Java 模板编码 → Java 正文原文。"""
    out = {}
    for p in sorted(JAVA_TPL_DIR.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        out[_RULE_KEY_RE.search(text).group(1).strip()] = text
    return out


def _norm_java(text: str) -> str:
    return _JAVA_PLACEHOLDER_RE.sub(r"{{\1}}", text.replace("\r\n", "\n"))


def _first_diff(a: str, b: str) -> str:
    i = next((k for k in range(min(len(a), len(b))) if a[k] != b[k]), min(len(a), len(b)))
    return f"位置 {i}：期望…{a[max(0, i - 40):i + 40]!r}… / Python…{b[max(0, i - 40):i + 40]!r}…"


def main() -> int:
    """运行全部 33 个模板的多场景渲染对拍。#Created By AiCoding(codex)"""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resources", default=str(ROOT / "src/report_agent/seed"), help="Python 资源目录")
    ap.add_argument("--report", default="", help="结果写入 JSON 文件")
    args = ap.parse_args()
    rs = load_resource_dir(Path(args.resources))
    bodies = java_template_bodies()
    cases: list[dict[str, Any]] = []
    expected: dict[str, tuple[int, str, str, dict[str, dict[str, Any]], dict[str, Any]]] = {}
    for tpl in sorted(rs.templates.values(), key=lambda t: t.id):
        jbody = bodies.get(tpl.name)
        if jbody is None:
            print(f"✗ 模板 {tpl.id} {tpl.name}：Java 中没有同名模板", file=sys.stderr)
            return 1
        for idx, (label, report) in enumerate(scenarios(tpl)):
            cid = f"{tpl.id}#{idx}"
            ctx = build_render_context(tpl, report)
            try:
                py_text, _ = render_body(tpl.body, ctx)
            except Exception as exc:  # noqa: BLE001
                py_text = f"<<Python 渲染失败：{type(exc).__name__} {exc}>>"
            expected[cid] = (tpl.id, label, py_text.replace("\r\n", "\n"), report, ctx)
            cases.append({"id": cid, "template": jbody, "values": java_values(tpl, report)})
    java_out = render_java(cases)
    per_tpl: dict[int, dict[str, Any]] = {}
    mismatches = 0
    for cid, (tid, label, py_text, report, ctx) in expected.items():
        tpl = rs.templates[tid]
        st = per_tpl.setdefault(tid, {"name": tpl.name, "scenarios": 0, "mismatch": []})
        st["scenarios"] += 1
        j = java_out.get(cid) or {}
        if not j.get("ok"):
            st["mismatch"].append({"scenario": label, "java": f"<<Java 渲染失败：{j.get('error')}>>", "python": py_text})
            mismatches += 1
            continue
        jt = _apply_intentional_fixes(tpl, report, ctx, _norm_java(j["text"]))
        if jt != py_text:
            st["mismatch"].append({"scenario": label, "diff": _first_diff(jt, py_text), "java": jt, "python": py_text})
            mismatches += 1
    total = sum(s["scenarios"] for s in per_tpl.values())
    for tid, st in sorted(per_tpl.items()):
        mark = "✓" if not st["mismatch"] else "✗"
        print(f"{mark} {tid} {st['name']}：{st['scenarios']} 个场景，不一致 {len(st['mismatch'])}")
        for m in st["mismatch"][:3]:
            print(f"    - {m['scenario']}：{m.get('diff') or m['java'][:200]}")
    print(f"合计：{len(per_tpl)} 个模板，{total} 个场景，不一致 {mismatches}")
    if args.report:
        Path(args.report).write_text(json.dumps(per_tpl, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
