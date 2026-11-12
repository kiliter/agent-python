"""Java 模板 → Python 模板迁移生成器。

#Created By AiCoding(codex)
输入：
  - Java 模板正文 template/md/*.md（与资源库 AGENT_TEMPLATE_CFG 的已发布内容一致，ID 来自 template_ids.yaml）
  - Java 规则 agent/rule/<模板编码>.rule、字段来源 agent/config/field-mappings.yml、Skill 依赖 agent/skills/*/SKILL.md
  - 本目录 field_catalog.yaml（字段语义映射表）
输出（默认 src/report_agent/seed/templates/<id>/）：template.yaml + body.md.j2，以及本目录 TEMPLATES.md 对照表。

正文只做机械语法转换（Pebble → Jinja2）：elseif → elif、null → none，其余字符原样保留（换行统一为 LF）。
可重复执行：python tools/java_migration/generate.py [--out DIR]
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, nodes

HERE = Path(__file__).resolve().parent
JAVA_RES = Path("/Users/zhangjialin/IdeaProjects/agent/pdf-agent-parse/src/main/resources")
TPL_DIR = JAVA_RES / "template/md"
RULE_DIR = JAVA_RES / "agent/rule"
SKILL_DIR = JAVA_RES / "agent/skills"
FIELD_MAPPINGS = JAVA_RES / "agent/config/field-mappings.yml"

_RULE_KEY_RE = re.compile(r"服务争议点\d+\s*[:：]\s*([^\r\n]+)")
_RULE_VAR_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_TAG_RE = re.compile(r"\{%.*?%\}", re.DOTALL)
# YAML 折叠块（>-）把换行变成空格；中文字符/全角标点之间的这类空格是多余的，生成时去掉
_CJK = r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef“”‘’]"
_CJK_SPACE_RE = re.compile(rf"(?<={_CJK}) (?={_CJK})")

# 模板入参定义：key → (说明, 示例)。是否出现在某个模板中由 need_inputs 决定（入参以当前系统为准，不定义与正文字段重名的“客户号码”入参）。
INPUT_DEFS: dict[str, tuple[str, str]] = {
    "手机号码": ("客户手机号，11 位", "13900001234"),
    "业务名称": ("本次争议的业务、套餐或活动名称", "5G智享套餐（个人版）"),
    "创建时间": ("工单创建时间 yyyyMMddHHmmss，短信类 Skill 以它为查询基准", "20261105103012"),
    "业务月份": ("业务办理日期 yyyyMMdd；受理渠道为热线、掌上营业厅时用作受理日期", "20261105"),
    "账单": ("账单起止月份，格式 yyyyMM$yyyyMM，起止月份均包含在查询范围内", "202610$202610"),
    "充值号码": ("充值的手机号码，11 位", "13900001234"),
    "充值时间": ("充值时间：支持 yyyyMMdd、yyyyMM（整月）或日期/账期范围（如 yyyyMMdd-yyyyMMdd）", "20260705"),
    "extraInfo": ("上游附加信息（JSON 文本），可能包含充值号码、办理日期、手机号等", '{"充值号码":"13900001234","办理日期":"20260705"}'),
}

# Skill 需要的入参（与 seed/skills 中各 Skill 的“需要的入参”保持一致）。
SKILL_INPUTS: dict[str, list[str]] = {
    "business-sms": ["手机号码", "业务名称", "创建时间"],
    "accept-type": [],
    "second-confirmation-sms": ["手机号码", "业务名称", "创建时间"],
    "verification-sms": ["手机号码", "业务名称", "创建时间"],
    "reminder-sms": ["手机号码", "业务名称", "创建时间"],
    "renewal-reminder-sms": ["手机号码", "业务名称", "创建时间"],
    "number-portability-sms": ["手机号码", "创建时间"],
    "original-package-name": ["手机号码", "业务名称", "创建时间"],
    "billing-cycle-sms": ["手机号码", "账单"],
    "qry-balance": ["手机号码", "充值号码", "充值时间", "extraInfo"],
    "pretty-number-info": ["手机号码"],
}

# 字段本身直接需要的入参（input / derive 证据引用的入参）。
FIELD_INPUTS: dict[str, list[str]] = {
    "商品名称": ["业务名称"],
    "业务名称": ["业务名称"],
    "受理日期": ["业务名称", "业务月份"],
    "客户手机号": ["extraInfo", "手机号码"],
    "客户号码": ["手机号码"],
}
FIELD_INPUTS_OVERRIDE: dict[tuple[str, str], list[str]] = {
    ("充值争议处理通用模板", "客户号码"): ["extraInfo", "充值号码", "手机号码"],
    ("充值错号处理类", "客户号码"): ["extraInfo", "充值号码", "手机号码"],
    ("套餐费用争议类", "客户号码"): [],
}
INPUT_ORDER = list(INPUT_DEFS.keys())


# ---------------------------------------------------------------------------
# Java 源读取
# ---------------------------------------------------------------------------

def pebble_to_jinja(text: str) -> str:
    """Pebble → Jinja2 机械转换：只改 {% %} 标签内的 elseif / null，正文文本不动；换行统一为 LF。"""

    def fix_tag(m: re.Match[str]) -> str:
        tag = m.group(0)
        tag = re.sub(r"^\{%(-?)(\s*)elseif\b", r"{%\1\2elif", tag)
        tag = re.sub(r"\bnull\b", "none", tag)
        return tag

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _TAG_RE.sub(fix_tag, text)


def load_template_ids() -> dict[str, int]:
    """模板编码 → Java 资源库中的模板 ID（template_ids.yaml，取自 AGENT_TEMPLATE_CFG）。"""
    data = yaml.safe_load((HERE / "template_ids.yaml").read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in data["templates"].items()}


def load_rules(code: str) -> dict[str, str]:
    """读取规则文件，返回 字段 → 规则原文（与 Java ClasspathAgentResourceSource 一样按 YAML 解析）。"""
    p = RULE_DIR / f"{code}.rule"
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for item in data.get("rule") or []:
        for k, v in item.items():
            out[str(k).strip()] = "" if v is None else str(v)
    return out


def load_field_mappings() -> dict[str, dict]:
    """字段来源映射，字段名去掉中括号。"""
    fm = yaml.safe_load(FIELD_MAPPINGS.read_text(encoding="utf-8"))
    return {k.strip().strip("[]"): v for k, v in fm["field-mappings"]["mappings"].items()}


def load_skill_dependencies() -> dict[str, list[str]]:
    """Java Skill 的 dependencies（frontmatter）。"""
    out: dict[str, list[str]] = {}
    for sdir in sorted(SKILL_DIR.glob("*/")):
        md = sdir / "SKILL.md"
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8").replace("\r\n", "\n")
        m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        meta = yaml.safe_load(m.group(1)) if m else {}
        out[sdir.name] = [str(d) for d in (meta.get("dependencies") or [])]
    return out


class BodyInfo:
    """正文结构：输出变量、条件变量、循环变量及其属性。"""

    def __init__(self, body: str) -> None:
        tree = Environment().parse(body)
        self.printed: list[str] = []
        self.loops: dict[str, list[str]] = {}
        loop_targets: set[str] = set()
        for f in tree.find_all(nodes.For):
            loop_targets.add(f.target.name)
            attrs: list[str] = []
            for g in f.find_all(nodes.Getattr):
                if isinstance(g.node, nodes.Name) and g.node.name == f.target.name and g.attr not in attrs:
                    attrs.append(g.attr)
            self.loops[f.iter.name] = attrs
            if isinstance(f.iter, nodes.Name) and f.iter.name not in self.printed and f.iter.name not in loop_targets:
                if any(True for _ in f.find_all(nodes.Output)):
                    self.printed.append(f.iter.name)
        for out in tree.find_all(nodes.Output):
            for n in out.find_all(nodes.Name):
                if n.name not in self.printed and n.name not in loop_targets:
                    self.printed.append(n.name)
        self.all_vars: list[str] = []
        for n in tree.find_all(nodes.Name):
            if n.ctx == "load" and n.name not in loop_targets and n.name not in self.all_vars and n.name != "none":
                self.all_vars.append(n.name)


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------

def build_field(name: str, code: str, catalog: dict, rules: dict[str, str], visible: bool) -> dict:
    """按映射表生成一个字段定义（template.yaml 中的一项）。"""
    base = dict(catalog["fields"].get(name) or {})
    if not base:
        raise SystemExit(f"field_catalog.yaml 缺少字段「{name}」（模板 {code}）")
    base.update((catalog.get("overrides") or {}).get(code, {}).get(name) or {})
    guide = _CJK_SPACE_RE.sub("", str(base.pop("guide", "")).strip())
    base.pop("skills", None)
    rule = rules.get(name)
    desc = guide
    if rule:
        desc = f"{guide}\n原规则（Java）：{rule.strip()}" if guide else f"原规则（Java）：{rule.strip()}"
    elif not guide:
        desc = f"从单据中摘取「{name}」。"
    field: dict = {"name": name}
    if not visible:
        field["visible"] = False
    ftype = base.get("type", "string")
    if ftype != "string":
        field["type"] = ftype
    if ftype == "enum":
        field["values"] = list(base["values"])
    if ftype == "list":
        field["columns"] = [dict(c) for c in base["columns"]]
    field["evidence"] = base.get("evidence", "quote")
    if base.get("quoteWhole"):
        field["quoteWhole"] = True
    wm = base.get("whenMissing", "placeholder")
    if wm != "placeholder":
        field["whenMissing"] = wm
    if wm == "value":
        field["defaultValue"] = str(base.get("defaultValue", ""))
    field["description"] = desc
    return field


def field_skills(name: str, code: str, catalog: dict) -> list[str]:
    """字段需要的 Skill（映射表 skills；覆盖项中可改）。"""
    base = dict(catalog["fields"].get(name) or {})
    base.update((catalog.get("overrides") or {}).get(code, {}).get(name) or {})
    return list(base.get("skills") or [])


def expand_skill_deps(skills: list[str], deps: dict[str, list[str]]) -> list[str]:
    """按 Java Skill dependencies 递归展开（保持顺序）。"""
    out: list[str] = []
    stack = list(skills)
    while stack:
        s = stack.pop(0)
        if s in out:
            continue
        out.append(s)
        stack.extend(deps.get(s, []))
    return out


def generate_one(path: Path, ids: dict[str, int], catalog: dict, mappings: dict[str, dict],
                 deps: dict[str, list[str]]) -> tuple[dict, str, dict]:
    """生成一个模板，返回（template.yaml 数据，正文，对照信息）。"""
    raw = path.read_text(encoding="utf-8")
    m = _RULE_KEY_RE.search(raw)
    if not m:
        raise SystemExit(f"{path.name} 首行没有“服务争议点N:”")
    code = m.group(1).strip()
    tid = ids[code]
    body = pebble_to_jinja(raw)
    info = BodyInfo(body)
    rules = load_rules(code)

    names = list(info.all_vars)
    # Java 隐式依赖：规则中 {{X}} 引用的、映射为 SKILL 的非正文字段，Java 会执行对应 Skill；迁移为中间字段。
    implicit: list[str] = []
    for fname in list(names):
        for dep in _RULE_VAR_RE.findall(rules.get(fname, "") or ""):
            dep = dep.strip()
            mp = mappings.get(dep) or {}
            if (dep not in names and dep not in implicit and mp.get("sourceType") == "SKILL"
                    and dep in catalog["fields"]):
                implicit.append(dep)
    fields = [build_field(n, code, catalog, rules, n in info.printed) for n in names]
    fields += [build_field(n, code, catalog, rules, False) for n in implicit]

    # 列表字段：列定义必须覆盖正文中 item.xxx 的全部属性
    for f in fields:
        if f.get("type") == "list":
            cols = {c["name"] for c in f["columns"]}
            missing = [a for a in info.loops.get(f["name"], []) if a not in cols]
            if missing:
                raise SystemExit(f"模板 {code} 列表字段 {f['name']} 缺少列 {missing}")

    skills: list[str] = []
    for n in names + implicit:
        for s in field_skills(n, code, catalog):
            if s not in skills:
                skills.append(s)
    skills = expand_skill_deps(skills, deps)

    need_inputs: set[str] = set()
    for n in names + implicit:
        need_inputs.update(FIELD_INPUTS_OVERRIDE.get((code, n), FIELD_INPUTS.get(n, [])))
    for s in skills:
        need_inputs.update(SKILL_INPUTS.get(s, []))
    inputs = [{"key": k, "required": False, "description": INPUT_DEFS[k][0], "sample": INPUT_DEFS[k][1]}
              for k in INPUT_ORDER if k in need_inputs]

    data = {
        "id": tid,
        "name": code,
        "description": f"迁移自 Java 模板「{code}」（资源库模板 ID {tid}），正文与规则以 Java 为准。",
        "skills": skills,
        "inputs": inputs,
        "fields": fields,
    }
    report = {
        "id": tid, "code": code, "file": path.name, "fields": len(fields), "implicit": implicit,
        "rules": len(rules), "rulesIgnored": [k for k in rules if k not in names],
        "skills": skills, "inputs": [i["key"] for i in inputs],
        "lists": [f["name"] for f in fields if f.get("type") == "list"],
    }
    return data, body, report


def dump_yaml(data: dict) -> str:
    """输出 template.yaml（中文不转义、保持字段顺序）。"""
    header = "# #Created By AiCoding(codex) 由 tools/java_migration/generate.py 从 Java 模板生成，请勿手工修改后再重新生成\n"
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(HERE.parent.parent / "src/report_agent/seed"), help="资源根目录（其下重建 templates/）")
    args = ap.parse_args()
    out_root = Path(args.out)
    catalog = yaml.safe_load((HERE / "field_catalog.yaml").read_text(encoding="utf-8"))
    ids = load_template_ids()
    mappings = load_field_mappings()
    deps = load_skill_dependencies()
    reports = []
    tdir_root = out_root / "templates"
    # 模板目录整体重建：以 Java 模板为准，旧模板（如测试模板）不保留
    if tdir_root.exists():
        shutil.rmtree(tdir_root)
    tdir_root.mkdir(parents=True, exist_ok=True)
    for path in sorted(TPL_DIR.glob("*.md")):
        data, body, report = generate_one(path, ids, catalog, mappings, deps)
        tdir = tdir_root / str(data["id"])
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "template.yaml").write_text(dump_yaml(data), encoding="utf-8")
        (tdir / "body.md.j2").write_text(body, encoding="utf-8")
        reports.append(report)
    if len(reports) != len(ids):
        raise SystemExit(f"Java 模板 {len(reports)} 个，与 template_ids.yaml 的 {len(ids)} 个不一致")
    lines = ["<!-- #Created By AiCoding(codex) 由 generate.py 生成 -->", "# 模板迁移对照表", "",
             "| ID | 模板（Java 编码） | 字段数 | 中间字段（Java 隐式依赖） | 列表字段 | Skill | 入参 | 未使用的 rule（Java 同样忽略） |",
             "|---|---|---|---|---|---|---|---|"]
    for r in sorted(reports, key=lambda x: x["id"]):
        lines.append(f"| {r['id']} | {r['code']} | {r['fields']} | {'、'.join(r['implicit']) or '-'} | "
                     f"{'、'.join(r['lists']) or '-'} | {', '.join(r['skills']) or '-'} | {'、'.join(r['inputs']) or '-'} | "
                     f"{'、'.join(r['rulesIgnored']) or '-'} |")
    (HERE / "TEMPLATES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"生成 {len(reports)} 个模板 → {tdir_root}", file=sys.stderr)


if __name__ == "__main__":
    main()
