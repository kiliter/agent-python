"""内部模型与前端数据结构（frontend/src/types/platform.ts）之间的转换。

#Created By AiCoding(codex)
存储用英文枚举（string/enum/date、placeholder/empty/value），前端展示用中文标签，在这里互转。
"""

from __future__ import annotations

import re
from typing import Any

from jinja2 import meta, nodes

from ..domain.api_contract import ApiContract, fixed_params
from ..domain.jinja_env import BodySyntaxError, parse_body
from ..domain.resources import ResourceSet, _RESERVED_FIELD_NAMES
from ..domain.skill import Skill
from ..domain.template import FieldDef, InputDef, Template
from ..store.fsutil import fmt_time
from ..store.service import ResourceState

TYPE_TO_LABEL = {"string": "文本", "enum": "枚举", "date": "日期"}
LABEL_TO_TYPE = {v: k for k, v in TYPE_TO_LABEL.items()}
MISSING_TO_LABEL = {"placeholder": "保留占位", "empty": "置空", "value": "默认值"}
LABEL_TO_MISSING = {v: k for k, v in MISSING_TO_LABEL.items()}
PRESETS = {r"^1\d{10}$": "手机号 (^1\\d{10}$)", r"^\d{14}$": "yyyyMMddHHmmss (^\\d{14}$)",
           r"^\d{8}$": "yyyyMMdd (^\\d{8}$)"}
_PRESET_TO_PATTERN = {v: k for k, v in PRESETS.items()}


def dash(value: Any) -> str:
    return "—" if value in (None, "") else str(value)


_FALLBACK_TOKEN_RE = re.compile(
    r"""('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""
    r"""|(\|\s*[A-Za-z_][A-Za-z0-9_]*)"""
    r"""|(\.\s*[^\W\d]\w*)"""
    r"""|([^\W\d]\w*)""",
    re.UNICODE,
)


# ============================================================================ 字段
def body_usage(body: str) -> dict[str, int]:
    """统计正文中每个名字出现的次数（{{ }} / {{- -}} 输出与 {% %} / {%- -%} 条件都算）。"""
    counts: dict[str, int] = {}
    if not body:
        return counts
    try:
        tree = parse_body(body)
        undeclared = set(meta.find_undeclared_variables(tree))
        for node in tree.find_all(nodes.Name):
            if node.ctx == "load" and node.name in undeclared:
                counts[node.name] = counts.get(node.name, 0) + 1
        return counts
    except BodySyntaxError:
        pass

    for m in re.finditer(r"\{\{[+-]?([\s\S]*?)[+-]?\}\}", body):
        for tm in _FALLBACK_TOKEN_RE.finditer(m.group(1)):
            ident = tm.group(4)
            if ident and ident not in _RESERVED_FIELD_NAMES:
                counts[ident] = counts.get(ident, 0) + 1
    for m in re.finditer(r"\{%[+-]?([\s\S]*?)[+-]?%\}", body):
        first = True
        for tm in _FALLBACK_TOKEN_RE.finditer(m.group(1)):
            ident = tm.group(4)
            if not ident:
                continue
            if first:
                first = False
                continue
            if ident not in _RESERVED_FIELD_NAMES:
                counts[ident] = counts.get(ident, 0) + 1
    return counts


def ref_by_fields(tpl: Template) -> dict[str, list[str]]:
    """哪些字段的说明里提到了某个字段（删除字段前提示用）。"""
    names = [f.name for f in tpl.definition.fields]
    result: dict[str, list[str]] = {n: [] for n in names}
    for f in tpl.definition.fields:
        for n in names:
            if n != f.name and n in (f.description or ""):
                result[n].append(f.name)
    return result


def field_to_dto(f: FieldDef, usage: dict[str, int] | None = None, ref_by: list[str] | None = None,
                 run: dict[str, Any] | None = None, from_template: str | None = None) -> dict[str, Any]:
    """FieldDef → 前端 TemplateField。run 为某次运行中该字段的结果。"""
    dto: dict[str, Any] = {
        "name": f.name, "visible": f.visible, "type": TYPE_TO_LABEL.get(f.type, "文本"), "enumValues": list(f.values),
        "evidenceType": f.evidence, "whenMissing": MISSING_TO_LABEL.get(f.whenMissing, "保留占位"),
        "defaultValue": f.defaultValue, "description": f.description, "format": f.format, "quoteWhole": f.quoteWhole,
        "bodyUsageCount": (usage or {}).get(f.name, 0), "refByFields": ref_by or [],
        "runStatus": "not_found", "runValue": "", "evidenceLabel": "", "evidenceTarget": {"tab": "doc"},
        "reasoning": "",
    }
    if from_template:
        dto["fromTemplate"] = from_template
    if run:
        run_status = run.get("status") or run.get("runStatus") or "not_found"
        raw_val = run.get("value") if "value" in run else run.get("runValue")
        run_val = "" if raw_val is None else str(raw_val)
        raw_rendered = run.get("renderedValue")
        rendered_val = "" if raw_rendered is None else str(raw_rendered)
        dto.update({
            "runStatus": run_status,
            "runValue": run_val if run_status == "found" else (
                "（置空）" if f.whenMissing == "empty" else rendered_val),
            "evidenceLabel": run.get("evidenceLabel", ""), "evidenceTarget": run.get("evidenceTarget") or {"tab": "doc"},
            "reasoning": run.get("reasoning", ""), "retried": bool(run.get("retried", False)),
            "validationFailed": bool(run.get("validationFailed", False)), "shown": bool(run.get("shown", False)),
            "evidence": run.get("evidence") or [],
        })
    return dto


def dto_to_field(d: dict[str, Any]) -> dict[str, Any]:
    """前端 TemplateField → FieldDef 字段字典（忽略运行结果相关属性）。"""
    ftype = LABEL_TO_TYPE.get(d.get("type", ""), d.get("type") or "string")
    missing = LABEL_TO_MISSING.get(d.get("whenMissing", ""), d.get("whenMissing") or "placeholder")
    raw_vals = d.get("enumValues") if d.get("enumValues") is not None else (d.get("values") or [])
    out = {
        "name": str(d.get("name", "")).strip(), "visible": bool(d.get("visible", True)), "type": ftype,
        "values": [str(v) for v in raw_vals if v is not None] if ftype == "enum" and isinstance(raw_vals, list) else [],
        "evidence": d.get("evidenceType") or d.get("evidence") or "quote", "whenMissing": missing,
        "defaultValue": "" if d.get("defaultValue") is None else str(d["defaultValue"]),
        "description": "" if d.get("description") is None else str(d["description"]),
        "quoteWhole": bool(d.get("quoteWhole", False)),
    }
    if d.get("format"):
        out["format"] = str(d["format"])
    return out


# ============================================================================ 入参
def input_to_dto(i: InputDef) -> dict[str, Any]:
    preset = PRESETS.get(i.pattern or "", None) if i.pattern else "无格式限制"
    if preset is None:
        preset = f"自定义正则 ({i.pattern})"
    return {"key": i.key, "required": i.required, "preset": preset, "pattern": i.pattern or "",
            "desc": i.description, "sample": i.sample}


def dto_to_input(d: dict[str, Any]) -> dict[str, Any]:
    pattern = d.get("pattern")
    if pattern is None:
        preset = d.get("preset") or "无格式限制"
        if preset in _PRESET_TO_PATTERN:
            pattern = _PRESET_TO_PATTERN[preset]
        elif preset in ("无格式限制", "自定义正则"):
            pattern = None
        else:
            m = re.search(r"\((\^.*\$)\)\s*$", preset)
            pattern = m.group(1) if m else None
    return {"key": str(d.get("key", "")).strip(), "required": bool(d.get("required", False)),
            "pattern": pattern or None, "description": d.get("desc") or d.get("description") or "",
            "sample": d.get("sample") or ""}


# ============================================================================ 列表项
def status_fields(state: ResourceState) -> dict[str, Any]:
    return {"status": state.status, "baseRev": dash(state.base_rev), "onlineRev": dash(state.online_rev),
            "lastPublishedAt": fmt_time(state.last_published_at, "从未发布"), "publisher": state.publisher or (
                (state.draft or {}).get("updatedBy") or "—")}


def template_item(tpl: Template, state: ResourceState, rs: ResourceSet, stats: dict[str, Any],
                  cases_count: int) -> dict[str, Any]:
    s = (stats.get("templates") or {}).get(str(tpl.id)) or {}
    runs = int(s.get("runs", 0))
    return {
        "id": tpl.id, "name": tpl.name, "description": tpl.definition.description, **status_fields(state),
        "skills": list(tpl.definition.skills),
        "skillNames": [(rs.skills[sid].title if sid in rs.skills else sid) for sid in tpl.definition.skills],
        "casesCount": cases_count, "runs7d": runs,
        "successRate": f"{s.get('success', 0) * 100 / runs:.1f}%" if runs else "—",
        "draftRevision": (state.draft or {}).get("revision"),
    }


def skill_item(skill: Skill, state: ResourceState, ref_templates: list[str], stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": skill.id, "name": skill.title, "description": skill.meta.description, **status_fields(state),
        "refsCount": len(ref_templates), "refTemplates": ref_templates,
        "loads7d": int((stats.get("skills") or {}).get(skill.id, 0)), "apis": list(skill.meta.apis),
        "draftRevision": (state.draft or {}).get("revision"),
    }


def api_item(api: ApiContract, state: ResourceState, refs: list[str], stats: dict[str, Any]) -> dict[str, Any]:
    calls = (stats.get("apis") or {}).get(api.name) or []
    n = len(calls)
    fail = sum(1 for ok, _ in calls if not ok)
    avg = int(sum(ms for _, ms in calls) / n) if n else None
    props = api.input.get("properties") or {}
    required = set(api.input.get("required") or [])
    is_json = api.connector == "unified-gateway-json"
    return {
        "name": api.name, "title": api.title, "description": api.description,
        "connector": api.connector,
        "format": "JSON" if is_json else "XML",
        "type": "统一网关 JSON" if is_json else "统一网关 XML",
        "headers": dict(getattr(api, "headers", None) or {}),
        "idempotent": api.idempotent,
        "processCode": api.processCode, **status_fields(state), "refs": refs, "calls7d": f"{n:,}",
        "failRate": f"{fail * 100 / n:.2f}%" if n else "0.00%", "avgMs": f"{avg} ms" if avg is not None else "—",
        "timeoutMs": api.timeoutMs, "retry": api.retry.maxAttempts,
        "params": [{"name": k, "type": v.get("type", "string"), "pattern": v.get("pattern", ""),
                    "required": k in required, "desc": v.get("description", "")} for k, v in props.items()],
        "fixedParams": fixed_params(api.request),
        "draftRevision": (state.draft or {}).get("revision"),
    }


def run_record(item: dict[str, Any]) -> dict[str, Any]:
    """运行摘要 → 前端 RunRecord（同时保留原始字段方便新前端使用）。"""
    tpl_id = item.get("templateId")
    tpl_prefix = "" if tpl_id is None else str(tpl_id)
    dur_ms = int(item.get("durationMs") or 0)
    return {
        "runId": str(item.get("runId") or ""), "startTime": fmt_time(item.get("startTime")),
        "template": f"{tpl_prefix} {item.get('templateName', '')}".strip(),
        "templateId": tpl_id, "mobile": item.get("mobile", ""), "busiName": item.get("busiName", ""),
        "status": item.get("status") or "FAILED", "foundRatio": f"{item.get('found', 0)} / {item.get('total', 0)}",
        "duration": f"{dur_ms / 1000:.1f} 秒", "durationMs": dur_ms,
        "rounds": f"{item.get('rounds', 0)} 轮", "rev": item.get("rev") or "—", "entry": item.get("entry") or "上游调用",
        "error": item.get("error"), "retries": item.get("retries", 0), "batchNo": item.get("batchNo"),
    }


def release_dto(entry: dict[str, Any], live: str | None) -> dict[str, Any]:
    return {"rev": entry["rev"], "type": entry.get("type"), "time": fmt_time(entry.get("time")),
            "operator": entry.get("operator"), "summary": entry.get("summary"), "note": entry.get("note", ""),
            "isLive": entry["rev"] == live, "base": entry.get("base"), "changes": entry.get("changes", [])}


def sms_records(api_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """兼容旧前端：把第一个接口结果转成 SmsRecord 列表。"""
    if not api_results or not isinstance(api_results[0], dict):
        return []
    first = api_results[0]
    records = first.get("records")
    if not isinstance(records, list):
        return []
    result_id = first.get("resultId", "")
    out = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        out.append({"row": rec.get("row"), "smsSendTime": rec.get("smsSendTime", ""), "sendPort": rec.get("sendPort", ""),
                    "sendType": rec.get("sendType", ""), "smsContent": rec.get("smsContent", ""),
                    "resultId": result_id})
    return out


def document_lines(document: str) -> list[dict[str, Any]]:
    return [{"line": i + 1, "text": t} for i, t in enumerate(document.splitlines())]
