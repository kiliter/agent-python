"""把运行结果整理成接口返回结构（试运行、运行详情、上游调用三种视图）。

#Created By AiCoding(codex)
"""

from __future__ import annotations

from typing import Any

from ..domain.template import FieldDef, TemplateDef
from .dto import document_lines, field_to_dto, run_record, sms_records


def _source(f: dict[str, Any]) -> str:
    return f.get("evidenceLabel") or ""


def detail_view(o: dict[str, Any], with_messages: bool = False) -> dict[str, Any]:
    """完整视图：管理端试运行结果和运行记录详情共用（对缺失或历史破损字段具备容错能力）。"""
    defn = None
    if o.get("templateDef"):
        try:
            defn = TemplateDef.model_validate(o["templateDef"])
        except Exception:  # noqa: BLE001 - 历史记录的模板定义结构可能已演进或破损
            defn = None
    by_name = {f.name: f for f in defn.fields} if defn else {}
    raw_fields = [f for f in (o.get("fields") or []) if isinstance(f, dict) and f.get("name")]
    fields = []
    for fo in raw_fields:
        fname = str(fo["name"])
        fd = by_name.get(fname)
        if fd is None:
            fd = FieldDef(name=fname, visible=bool(fo.get("visible", True)))
        fields.append(field_to_dto(fd, run=fo))
    inputs = o.get("inputs") if isinstance(o.get("inputs"), dict) else {}
    found_count = int(o.get("foundCount") if o.get("foundCount") is not None
                      else sum(1 for f in raw_fields if (f.get("status") or f.get("runStatus")) == "found"))
    total_count = int(o.get("totalCount") if o.get("totalCount") is not None else len(raw_fields))
    duration_ms = int(o.get("durationMs") or 0)
    rounds = int(o.get("rounds") or 0)
    val_rounds = o.get("validationRounds") if isinstance(o.get("validationRounds"), list) else []
    api_results = o.get("apiResults") if isinstance(o.get("apiResults"), list) else []
    doc_text = str(o.get("document") or "")
    extra = o.get("extra") if isinstance(o.get("extra"), dict) else {}
    summary = {
        "runId": str(o.get("runId") or ""), "startTime": o.get("startTime") or "",
        "templateId": o.get("templateId"), "templateName": o.get("templateName") or "",
        "rev": o.get("rev") or "—", "entry": o.get("entry") or "上游调用", "status": o.get("status") or "FAILED",
        "mobile": inputs.get("手机号码", ""), "busiName": inputs.get("业务名称", ""),
        "found": found_count, "total": total_count, "durationMs": duration_ms, "rounds": rounds,
        "error": o.get("error"), "retries": len(val_rounds), "batchNo": o.get("batchNo") or extra.get("batchNo"),
    }
    view = {
        "runId": summary["runId"], "status": summary["status"], "error": o.get("error"), "rev": summary["rev"],
        "target": o.get("target") or "online", "entry": summary["entry"], "operator": o.get("operator") or "",
        "record": run_record(summary),
        "durationSec": round(duration_ms / 1000, 1), "rounds": rounds,
        "apiCallCount": len(api_results), "foundCount": found_count, "totalCount": total_count,
        "missingShown": o.get("missingShown") or [], "retriedFields": sorted(
            {f["name"] for f in raw_fields if f.get("retried")}),
        "report": str(o.get("report") or ""), "fields": fields, "inputs": inputs,
        "documentText": doc_text, "documentLines": document_lines(doc_text),
        "apiResults": api_results, "smsRecords": sms_records(api_results),
        "toolCalls": o.get("toolCalls") or [], "events": o.get("events") or [], "usage": o.get("usage") or {},
        "skillsLoaded": o.get("skillsLoaded") or [], "validationRounds": val_rounds,
        "model": o.get("model"),
    }
    if with_messages:
        view["messages"] = o.get("messages")
    return view


def report_view(o: dict[str, Any]) -> dict[str, Any]:
    """上游调用的精简视图。"""
    raw_fields = [f for f in (o.get("fields") or []) if isinstance(f, dict) and f.get("name")]
    return {
        "runId": str(o.get("runId") or ""), "status": o.get("status") or "FAILED",
        "templateId": o.get("templateId"), "rev": o.get("rev") or "—",
        "report": str(o.get("report") or ""), "error": o.get("error"),
        "fields": [{"name": f["name"], "visible": bool(f.get("visible", True)), "shown": bool(f.get("shown", False)),
                    "status": f.get("status") or f.get("runStatus") or "not_found", "value": f.get("value"),
                    "source": _source(f),
                    "reason": f.get("reasoning") if (f.get("status") or f.get("runStatus")) != "found" else None}
                   for f in raw_fields],
        "missingShown": o.get("missingShown") or [], "durationMs": int(o.get("durationMs") or 0),
    }
