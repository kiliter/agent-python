"""运行记录单页 HTML 离线导出器（零外部依赖：ChatUI 模拟回放 + 运行记录 4 页签证据溯源双视图）。

#Created By AiCoding(codex)
将一条或多条 RunStore 运行记录打包为单个离线可用的 .html 文件：
- 内联全部 CSS / SVG / Vanilla JS / Markdown 渲染器，无任何 CDN 或外部脚本依赖；
- 每条运行记录均同时支持两种视图一键切换：
  1) 「Chat 模拟回放」：复刻 ChatUI 单栏对话流、自动路由卡片、可折叠思考状态条（精简步骤 ↔ 原样记录）、流式成稿报告卡片；
  2) 「运行记录详情」：复刻工作台 RunsView 四大页签（报告 / 字段结果与证据左右分栏联动溯源 / 智能体时间线 / 输入与单据）。
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from ..chat.steps import events_to_steps
from ..domain.resources import ResourceSet
from ..store.fsutil import fmt_time, now_iso
from .dto import document_lines, safe_int
from .missing_summary import build_missing_summary

_MAX_RAW_STR_LEN = 2400
_MAX_CELL_STR_LEN = 12000
_MAX_DOC_CHARS = 50000


def _clip_str(val: Any, limit: int = _MAX_RAW_STR_LEN) -> str:
    text = str(val or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，共 {len(text)} 字符）"


def _sanitize_raw_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """原样保留 ProcessEvent 的平铺结构（对齐 RawEventsTimeline.vue / timelineFormat.ts）。

    #Created By AiCoding(codex)
    后端 ProcessEvent.to_dict() 将 tool/callId/args/result/text/skills/apis/issues/candidates 等字段
    平铺在顶层；这里完整保留全部字段（兼容历史可能存在的嵌套 data），仅对超长字符串或超大嵌套做温和裁剪。
    """
    out: list[dict[str, Any]] = []
    for idx, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        # 兼容嵌套 data 与标准平铺事件
        merged: dict[str, Any] = {}
        nested = ev.get("data")
        if isinstance(nested, dict):
            merged.update(nested)
        for k, v in ev.items():
            if k != "data":
                merged[k] = v

        clean: dict[str, Any] = {
            "seq": safe_int(merged.get("seq"), idx + 1) or (idx + 1),
            "type": str(merged.get("type") or ""),
            "atMs": max(0, safe_int(merged.get("atMs", merged.get("at_ms", 0)), 0)),
            "round": max(0, safe_int(merged.get("round", 0), 0)),
        }
        for k, v in merged.items():
            if k in ("seq", "type", "atMs", "at_ms", "round"):
                continue
            if k in ("raw", "pdfText") and isinstance(v, str):
                clean[k] = _clip_str(v, 1000)
            else:
                clean[k] = _clip_json_val(v, _MAX_RAW_STR_LEN)
        out.append(clean)
    return out


def _sanitize_api_results(api_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """保留用于证据溯源检查器的接口返回记录与脱敏请求预览，剔除冗余 raw 原始大报文。"""
    out: list[dict[str, Any]] = []
    for res in api_results:
        if not isinstance(res, dict):
            continue
        records_out: list[dict[str, Any]] = []
        for idx, rec in enumerate(res.get("records") or []):
            if not isinstance(rec, dict):
                continue
            row_dict: dict[str, Any] = {}
            for ck, cv in rec.items():
                if isinstance(cv, str):
                    row_dict[str(ck)] = _clip_str(cv, _MAX_CELL_STR_LEN)
                elif isinstance(cv, (dict, list)):
                    row_dict[str(ck)] = _clip_str(json.dumps(cv, ensure_ascii=False), _MAX_CELL_STR_LEN)
                else:
                    row_dict[str(ck)] = "" if cv is None else cv
            row_dict.setdefault("row", idx)
            records_out.append(row_dict)
        cols = res.get("columns") if isinstance(res.get("columns"), dict) else {}
        args = res.get("args") if isinstance(res.get("args"), dict) else {}
        out.append({
            "resultId": str(res.get("resultId") or ""),
            "api": str(res.get("api") or ""),
            "title": str(res.get("title") or res.get("api") or ""),
            "args": {str(k): "" if v is None else str(v) for k, v in args.items()},
            "ok": bool(res.get("ok", True)),
            "error": str(res.get("error") or "") if res.get("error") else "",
            "costMs": safe_int(res.get("costMs"), 0),
            "noData": bool(res.get("noData", False)),
            "columns": {str(k): str(v) for k, v in cols.items()},
            "records": records_out,
            "requestPreview": _clip_str(res.get("requestPreview") or "", 4000),
        })
    return out


def _clip_json_val(val: Any, limit: int = 2400) -> Any:
    """保留原始 JSON 结构（dict/list/标量），仅对超长字符串或超大嵌套做温和裁剪，便于纯 JSON 导出。"""
    if isinstance(val, str):
        return _clip_str(val, limit)
    if isinstance(val, dict):
        dumped = json.dumps(val, ensure_ascii=False)
        if len(dumped) <= limit * 2:
            return val
        return {str(k): _clip_json_val(v, max(400, limit // 2)) for k, v in val.items()}
    if isinstance(val, list):
        dumped = json.dumps(val, ensure_ascii=False)
        if len(dumped) <= limit * 2:
            return val
        return [_clip_json_val(item, max(300, limit // 2)) for item in val[:50]]
    return val


def _sanitize_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """保留结构化工具调用记录（callId/tool/args/output/atMs/ok），供证据检查器、时间线与纯 JSON 导出共用。"""
    out: list[dict[str, Any]] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        out.append({
            "callId": str(tc.get("callId") or ""),
            "tool": str(tc.get("tool") or ""),
            "args": _clip_json_val(tc.get("args"), 2000),
            "output": _clip_json_val(tc.get("output"), 2400),
            "atMs": safe_int(tc.get("atMs"), 0),
            "ok": bool(tc.get("ok", True)),
        })
    return out


def _build_steps(run: dict[str, Any], resources: ResourceSet | None) -> list[dict[str, Any]]:
    """复用 chat.steps.events_to_steps 生成与 ChatUI 完全一致的脱敏中文步骤列表。"""
    raw_events = run.get("events") or []
    steps = events_to_steps(raw_events, resources=resources)
    status = str(run.get("status") or "SUCCESS")
    duration_ms = safe_int(run.get("durationMs"), 0)
    last_ms = steps[-1]["atMs"] if steps else 0
    end_ms = max(last_ms, duration_ms)

    if not steps or steps[-1].get("icon") not in ("done", "error"):
        next_seq = (steps[-1]["seq"] + 1) if steps else 1
        if status == "SUCCESS":
            steps.append({
                "seq": next_seq,
                "atMs": end_ms,
                "icon": "done",
                "text": "核查完成，已通过平台证据校验并生成报告",
                "ok": True,
            })
        elif status == "PARTIAL":
            miss = run.get("missingShown") or []
            hint = f"（{len(miss)} 项展示字段缺失）" if miss else "（部分字段待人工补齐）"
            steps.append({
                "seq": next_seq,
                "atMs": end_ms,
                "icon": "warn",
                "text": f"核查完成{hint}，已生成报告草稿",
                "ok": True,
            })
        else:
            steps.append({
                "seq": next_seq,
                "atMs": end_ms,
                "icon": "error",
                "text": "本次核查执行失败",
                "ok": False,
            })
    return steps


def build_replay_item(run: dict[str, Any], resources: ResourceSet | None = None) -> dict[str, Any]:
    """将单条 RunStore 记录转为离线双视图 HTML 所需的标准化 JSON 结构。#Created By AiCoding(codex)"""
    fields_out: list[dict[str, Any]] = []
    for f in run.get("fields") or []:
        if not isinstance(f, dict):
            continue
        val = f.get("value")
        if isinstance(val, list):
            val_text = "[]" if not val else json.dumps(val, ensure_ascii=False)
        elif isinstance(val, dict):
            val_text = json.dumps(val, ensure_ascii=False)
        elif val is None:
            val_text = ""
        else:
            val_text = str(val)
        raw_rendered = f.get("renderedValue")
        if raw_rendered is None:
            rendered_text = ""
        elif isinstance(raw_rendered, (list, dict)):
            rendered_text = json.dumps(raw_rendered, ensure_ascii=False)
        else:
            rendered_text = str(raw_rendered)
        ev_target = f.get("evidenceTarget")
        field_entry: dict[str, Any] = {
            "name": str(f.get("name") or ""),
            "visible": bool(f.get("visible", True)),
            "shown": bool(f.get("shown", False)),
            "type": str(f.get("type") or "string"),
            "evidenceType": str(f.get("evidenceType") or "derive"),
            "whenMissing": str(f.get("whenMissing") or "placeholder"),
            "status": str(f.get("status") or "not_found"),
            # 保留原生 value（list 字段维持数组结构供纯 JSON 导出），展示用文本独立存 displayValue
            "value": _clip_json_val(val, _MAX_CELL_STR_LEN),
            "displayValue": _clip_str(val_text, _MAX_CELL_STR_LEN),
            "renderedValue": _clip_str(rendered_text, _MAX_CELL_STR_LEN),
            "evidence": f.get("evidence") if isinstance(f.get("evidence"), list) else [],
            "evidenceLabel": str(f.get("evidenceLabel") or ""),
            "evidenceTarget": dict(ev_target) if isinstance(ev_target, dict) else {"tab": "doc"},
            "reasoning": _clip_str(f.get("reasoning") or "", 800),
            "retried": bool(f.get("retried", False)),
            "validationFailed": bool(f.get("validationFailed", False)),
        }
        if isinstance(f.get("columns"), list):
            field_entry["columns"] = _clip_json_val(f["columns"], _MAX_RAW_STR_LEN)
        fields_out.append(field_entry)

    inputs_raw = run.get("inputs") if isinstance(run.get("inputs"), dict) else {}
    inputs = {str(k): "" if v is None else str(v) for k, v in inputs_raw.items()}
    doc_raw = str(run.get("document") or "")
    if len(doc_raw) > _MAX_DOC_CHARS:
        doc_text = doc_raw[:_MAX_DOC_CHARS] + f"\n…（单据原文共 {len(doc_raw)} 字，导出预览已截取前 {_MAX_DOC_CHARS} 字）"
    else:
        doc_text = doc_raw

    routing_raw = run.get("routing")
    routing = dict(routing_raw) if isinstance(routing_raw, dict) else None
    tpl_def_raw = run.get("templateDef")
    tpl_def = dict(tpl_def_raw) if isinstance(tpl_def_raw, dict) else None
    extra = run.get("extra") if isinstance(run.get("extra"), dict) else {}
    usage = run.get("usage") if isinstance(run.get("usage"), dict) else {}
    val_rounds = run.get("validationRounds") if isinstance(run.get("validationRounds"), list) else []

    return {
        "runId": str(run.get("runId") or ""),
        "startTime": fmt_time(str(run.get("startTime") or "")),
        "templateId": run.get("templateId"),
        "templateName": str(run.get("templateName") or ""),
        "templateDef": tpl_def,
        "rev": str(run.get("rev") or "—"),
        "entry": str(run.get("entry") or "运行记录"),
        "model": str(run.get("model") or ""),
        "operator": str(run.get("operator") or ""),
        "batchNo": str(run.get("batchNo") or extra.get("batchNo") or ""),
        "status": str(run.get("status") or "FAILED"),
        "error": str(run.get("error") or "") if run.get("error") else "",
        "durationMs": safe_int(run.get("durationMs"), 0),
        "rounds": safe_int(run.get("rounds"), 0),
        "foundCount": safe_int(run.get("foundCount"), 0),
        "totalCount": safe_int(run.get("totalCount"), 0),
        "missingShown": [str(x) for x in (run.get("missingShown") or [])],
        "skillsLoaded": [str(x) for x in (run.get("skillsLoaded") or [])],
        "usage": {
            "requests": safe_int(usage.get("requests"), 0),
            "toolCalls": safe_int(usage.get("toolCalls"), 0),
            "inputTokens": safe_int(usage.get("inputTokens"), 0),
            "outputTokens": safe_int(usage.get("outputTokens"), 0),
        },
        "validationRounds": val_rounds,
        "inputs": inputs,
        "document": doc_text,
        "documentChars": len(doc_raw),
        "documentLines": document_lines(doc_text),
        "routing": routing,
        "steps": _build_steps(run, resources),
        "rawEvents": _sanitize_raw_events(run.get("events") or []),
        "apiResults": _sanitize_api_results(run.get("apiResults") or []),
        "toolCalls": _sanitize_tool_calls(run.get("toolCalls") or []),
        "fields": fields_out,
        "missingSummary": build_missing_summary(run),
        "report": str(run.get("report") or ""),
    }


def _safe_inline_json(obj: Any) -> str:
    """安全内联至 HTML <script type="application/json">，彻底消除 </script> 与行分隔符注入。"""
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_runs_replay_html(
    runs: list[dict[str, Any]],
    *,
    resources: ResourceSet | None = None,
    title: str | None = None,
) -> str:
    """生成零外部依赖的单页双视图（ChatUI 模拟回放 + 运行记录 4 页签详情）HTML。#Created By AiCoding(codex)"""
    items = [build_replay_item(r, resources=resources) for r in runs]
    page_title = (title or "").strip()
    if not page_title:
        if len(items) == 1:
            one = items[0]
            biz = one["inputs"].get("业务名称") or one["templateName"] or one["runId"]
            page_title = f"智能填报助手 · 运行回放 - {biz}"
        else:
            page_title = f"智能填报助手 · 运行回放（共 {len(items)} 笔）"

    payload = {
        "title": page_title,
        "exportedAt": fmt_time(now_iso()),
        "count": len(items),
        "runs": items,
    }
    safe_title = html.escape(page_title, quote=True)
    safe_json = _safe_inline_json(payload)
    replacements = {"__PAGE_TITLE__": safe_title, "__REPLAY_PAYLOAD__": safe_json}
    return re.sub(r"__(?:PAGE_TITLE|REPLAY_PAYLOAD)__", lambda m: replacements[m.group(0)], _HTML_TEMPLATE)


# ============================================================================ 单页离线双视图 HTML 模板
# 严格零外链：所有样式、SVG 图标、Markdown 渲染器、Chat 回放引擎与运行记录 4 页签证据检查器全部内联。
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<!-- #Created By AiCoding(codex) 单页离线运行回放与运行记录详情（零外部依赖） -->
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>__PAGE_TITLE__</title>
<style>
:root {
  color-scheme: light;
  --gpt-bg: #ffffff;
  --gpt-bg-subtle: #fafafa;
  --gpt-bg-muted: #f4f4f5;
  --gpt-bg-hover: #eceef1;
  --gpt-border: #e4e4e7;
  --gpt-border-strong: #d4d4d8;
  --gpt-ink: #18181b;
  --gpt-ink-secondary: #52525b;
  --gpt-ink-muted: #71717a;
  --gpt-accent: #2563eb;
  --gpt-accent-hover: #1d4ed8;
  --gpt-accent-soft: #eff6ff;
  --gpt-accent-border: #bfdbfe;
  --gpt-emerald: #10b981;
  --gpt-emerald-bg: #ecfdf5;
  --gpt-emerald-border: #a7f3d0;
  --gpt-emerald-ink: #047857;
  --gpt-amber: #b45309;
  --gpt-amber-strong: #d97706;
  --gpt-amber-bg: #fffbeb;
  --gpt-amber-border: #fde68a;
  --gpt-coral: #dc2626;
  --gpt-coral-bg: #fef2f2;
  --gpt-coral-border: #fecaca;
  --gpt-hl-bg: #fef3c7;
  --gpt-hl-border: #f59e0b;
  --gpt-shadow-xs: 0 1px 2px rgba(15, 23, 42, 0.05);
  --gpt-shadow-md: 0 12px 32px rgba(15, 23, 42, 0.12);
  --gpt-font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
  --gpt-font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; height: 100%; overflow: hidden;
  background: var(--gpt-bg); color: var(--gpt-ink);
  font-family: var(--gpt-font-sans); font-size: 13px; line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
.mono { font-family: var(--gpt-font-mono); }
button { font-family: inherit; }

/* 整体壳层 */
.app-shell { display: flex; width: 100vw; height: 100vh; overflow: hidden; background: var(--gpt-bg); }

/* 左侧会话列表 */
.sidebar {
  width: 284px; flex-shrink: 0; height: 100%;
  border-right: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle);
  display: flex; flex-direction: column;
  transition: width 0.2s ease, opacity 0.18s ease;
}
.sidebar.is-hidden { width: 0; border-right: none; overflow: hidden; opacity: 0; }
.sb-head { padding: 12px 12px 10px; border-bottom: 1px solid var(--gpt-border); display: flex; flex-direction: column; gap: 8px; }
.sb-title-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.sb-title { font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px; }
.sb-count { font-size: 11px; padding: 1px 6px; border-radius: 999px; background: var(--gpt-accent-soft); color: var(--gpt-accent); font-weight: 600; }
.sb-search {
  width: 100%; height: 30px; padding: 0 9px; border-radius: 7px;
  border: 1px solid var(--gpt-border); background: #fff; color: var(--gpt-ink); font-size: 12px; outline: none;
}
.sb-search:focus { border-color: var(--gpt-accent); box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.12); }
.sb-filter-row { display: flex; gap: 4px; }
.sb-chip {
  flex: 1; height: 24px; border: 1px solid var(--gpt-border); background: #fff;
  color: var(--gpt-ink-secondary); border-radius: 6px; font-size: 11px; cursor: pointer;
}
.sb-chip.active { background: var(--gpt-accent); color: #fff; border-color: var(--gpt-accent); font-weight: 600; }
.sb-list { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.sb-item {
  width: 100%; text-align: left; padding: 9px 10px; border-radius: 9px;
  border: 1px solid transparent; background: transparent; cursor: pointer;
  display: flex; flex-direction: column; gap: 4px; flex-shrink: 0; transition: all 0.14s ease;
}
.sb-item:hover { background: #fff; border-color: var(--gpt-border); }
.sb-item.active { background: #fff; border-color: var(--gpt-accent-border); box-shadow: 0 2px 8px rgba(37, 99, 235, 0.08); }
.sb-item-top { display: flex; align-items: center; gap: 6px; min-width: 0; }
.sb-item-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; font-size: 12.5px; }
.sb-item-sub { display: flex; align-items: center; justify-content: space-between; gap: 6px; font-size: 11px; color: var(--gpt-ink-muted); }
.sb-item-tpl { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sb-foot { padding: 8px 12px; border-top: 1px solid var(--gpt-border); font-size: 11px; color: var(--gpt-ink-muted); display: flex; justify-content: space-between; }

/* 右侧主舞台 */
.chat-stage { flex: 1; min-width: 0; height: 100%; display: flex; flex-direction: column; position: relative; background: #fff; }

/* 顶栏 */
.topbar {
  height: 50px; flex-shrink: 0; padding: 0 14px;
  border-bottom: 1px solid var(--gpt-border);
  background: rgba(255, 255, 255, 0.94); backdrop-filter: blur(8px);
  display: flex; align-items: center; justify-content: space-between; gap: 10px; z-index: 20;
}
.tb-brand { display: flex; align-items: center; gap: 8px; min-width: 0; }
.brand-logo {
  width: 26px; height: 26px; border-radius: 7px; flex-shrink: 0;
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  display: inline-flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25);
}
.tb-title { font-size: 14px; font-weight: 600; white-space: nowrap; }

/* 顶栏核心：Chat 模拟回放 <-> 运行记录详情 切换器 */
.mode-switch {
  display: inline-flex; padding: 3px; border-radius: 9px;
  background: var(--gpt-bg-muted); border: 1px solid var(--gpt-border); flex-shrink: 0;
}
.mode-btn {
  height: 26px; padding: 0 11px; border: none; background: transparent; border-radius: 6px;
  font-size: 12px; font-weight: 500; color: var(--gpt-ink-secondary); cursor: pointer;
  display: inline-flex; align-items: center; gap: 5px; transition: all 0.14s ease;
}
.mode-btn.active { background: #fff; color: var(--gpt-accent); font-weight: 600; box-shadow: var(--gpt-shadow-xs); }

.tb-controls { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.pill-btn {
  height: 28px; padding: 0 10px; border-radius: 999px;
  border: 1px solid var(--gpt-border); background: #fff; color: var(--gpt-ink-secondary);
  font-size: 12px; font-weight: 500; cursor: pointer;
  display: inline-flex; align-items: center; gap: 5px; transition: all 0.14s ease;
}
.pill-btn:hover { background: var(--gpt-bg-muted); border-color: var(--gpt-border-strong); color: var(--gpt-ink); }
.pill-btn.primary { background: var(--gpt-accent); border-color: var(--gpt-accent); color: #fff; }
.pill-btn.primary:hover { background: var(--gpt-accent-hover); }
.speed-seg { display: inline-flex; padding: 2px; border-radius: 999px; background: var(--gpt-bg-muted); border: 1px solid var(--gpt-border); }
.speed-btn { height: 22px; padding: 0 7px; border: none; background: transparent; border-radius: 999px; font-size: 11.5px; color: var(--gpt-ink-secondary); cursor: pointer; }
.speed-btn.active { background: #fff; color: var(--gpt-accent); font-weight: 600; box-shadow: var(--gpt-shadow-xs); }

/* 视图容器 */
.view-pane { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.view-pane.is-hidden { display: none; }

/* ==================== 视图 A：Chat 模拟回放 ==================== */
.chat-scroll { flex: 1; overflow-y: auto; padding: 22px 20px 28px; scroll-behavior: smooth; }
.chat-stream { max-width: 920px; margin: 0 auto; display: flex; flex-direction: column; gap: 18px; }
@keyframes fadeUp { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
.msg-row { display: flex; gap: 10px; animation: fadeUp 0.22s ease both; }
.msg-row.is-user { justify-content: flex-end; }
.msg-avatar {
  width: 28px; height: 28px; border-radius: 8px; flex-shrink: 0; margin-top: 2px;
  background: linear-gradient(135deg, #2563eb 0%, #0ea5e9 100%);
  color: #fff; display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.2);
}
.msg-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.user-bubble {
  max-width: 78%; padding: 10px 14px; border-radius: 16px 16px 4px 16px;
  background: #2563eb; color: #fff; font-size: 13px; line-height: 1.6;
  box-shadow: 0 2px 8px rgba(37, 99, 235, 0.18);
}
.user-bubble-title { font-weight: 600; margin-bottom: 5px; }
.user-kv-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.user-kv-tag { font-size: 11.5px; padding: 2px 8px; border-radius: 999px; background: rgba(255,255,255,0.16); color: #fff; border: 1px solid rgba(255,255,255,0.24); }
.user-appeal { margin-top: 7px; padding: 6px 9px; border-radius: 8px; background: rgba(255,255,255,0.14); font-size: 12px; color: #f8fafc; }

.route-card { border: 1px solid var(--gpt-accent-border); background: #f8faff; border-radius: 10px; padding: 9px 12px; display: flex; flex-direction: column; gap: 6px; }
.route-head { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; font-size: 12.5px; }
.route-pill { padding: 1px 7px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--gpt-accent); color: #fff; }
.route-conf { padding: 1px 7px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--gpt-emerald-bg); border: 1px solid var(--gpt-emerald-border); color: var(--gpt-emerald-ink); }
.route-reason { font-size: 12px; color: var(--gpt-ink-secondary); line-height: 1.5; }

.thinking-bar { border-radius: 10px; border: 1px solid var(--gpt-border); background: var(--gpt-bg-subtle); overflow: hidden; }
.thinking-bar.st-running { border-color: var(--gpt-accent-border); background: #f8faff; }
.thinking-bar.is-expanded { box-shadow: var(--gpt-shadow-xs); }
.thinking-bar-head { padding: 8px 11px; display: flex; align-items: center; justify-content: space-between; gap: 8px; cursor: pointer; user-select: none; }
.thinking-bar-head:hover { background: rgba(24,24,27,0.025); }
.tb-left { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0; overflow: hidden; font-size: 12.5px; color: var(--gpt-ink-secondary); }
.tb-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--gpt-ink-muted); }
.dot-success { background: var(--gpt-emerald); }
.dot-partial { background: var(--gpt-amber-strong); }
.dot-failed { background: var(--gpt-coral); }
.spin { animation: spin 0.9s linear infinite; color: var(--gpt-accent); flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }
.tb-summary { font-weight: 600; color: var(--gpt-ink); flex-shrink: 0; }
.tb-sep { color: var(--gpt-border-strong); flex-shrink: 0; }
.tb-tpl { display: inline-flex; align-items: center; gap: 4px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.tb-meta { font-size: 11.5px; color: var(--gpt-ink-muted); flex-shrink: 0; }
.runid-chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px; border-radius: 6px; border: 1px solid var(--gpt-border); background: #fff; color: var(--gpt-ink-muted); font-size: 11px; cursor: pointer; max-width: 195px; }
.runid-chip:hover { border-color: var(--gpt-accent-border); color: var(--gpt-accent); background: var(--gpt-accent-soft); }
.thinking-bar-body { border-top: 1px solid var(--gpt-border); background: #fff; }
.trace-toolbar { padding: 6px 11px; border-bottom: 1px solid var(--gpt-border); background: var(--gpt-bg-subtle); display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.trace-caption { font-size: 11.5px; color: var(--gpt-ink-muted); }
.trace-seg { display: inline-flex; padding: 2px; border-radius: 7px; background: var(--gpt-bg-muted); }
.seg-btn { border: none; background: transparent; padding: 3px 9px; border-radius: 5px; font-size: 11.5px; color: var(--gpt-ink-secondary); cursor: pointer; }
.seg-btn.active { background: #fff; color: var(--gpt-ink); font-weight: 600; box-shadow: var(--gpt-shadow-xs); }
.steps-list { padding: 8px 12px; display: flex; flex-direction: column; gap: 5px; max-height: 380px; overflow-y: auto; overscroll-behavior: contain; }
.step-row { display: flex; align-items: flex-start; gap: 8px; font-size: 12.5px; padding: 4px 6px; border-radius: 6px; flex-shrink: 0; animation: fadeUp 0.18s ease both; }
.step-row:hover { background: var(--gpt-bg-subtle); }
.step-ic { width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px; }
.step-ic.ic-done, .step-ic.ic-check { color: var(--gpt-emerald); }
.step-ic.ic-warn { color: var(--gpt-amber-strong); }
.step-ic.ic-error { color: var(--gpt-coral); }
.step-ic.ic-api, .step-ic.ic-skill, .step-ic.ic-start { color: var(--gpt-accent); }
.step-ic.ic-filter, .step-ic.ic-tool { color: var(--gpt-ink-secondary); }
.step-txt { flex: 1; word-break: break-word; }
.step-txt.is-fail { color: var(--gpt-coral); }
.step-at { font-size: 11px; color: var(--gpt-ink-muted); flex-shrink: 0; margin-top: 2px; }

.raw-list { padding: 10px 12px; display: flex; flex-direction: column; gap: 10px; max-height: 520px; overflow-y: auto; overscroll-behavior: contain; }
.raw-round { border: 1px solid var(--gpt-border); border-radius: 9px; background: #fff; flex-shrink: 0; }
.raw-round.oc-pass { border-color: var(--gpt-emerald-border); }
.raw-round.oc-warn { border-color: var(--gpt-amber-border); }
.raw-round.oc-err { border-color: var(--gpt-coral-border); }
.raw-round-head { padding: 7px 11px; background: var(--gpt-bg-subtle); border-bottom: 1px solid var(--gpt-border); border-radius: 8px 8px 0 0; font-size: 12px; font-weight: 600; color: var(--gpt-ink-secondary); display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.raw-round.oc-pass .raw-round-head { background: var(--gpt-emerald-bg); color: var(--gpt-emerald-ink); border-bottom-color: var(--gpt-emerald-border); }
.raw-round.oc-warn .raw-round-head { background: var(--gpt-amber-bg); color: var(--gpt-amber); border-bottom-color: var(--gpt-amber-border); }
.raw-round.oc-err .raw-round-head { background: var(--gpt-coral-bg); color: var(--gpt-coral); border-bottom-color: var(--gpt-coral-border); }
.raw-round-body { padding: 9px 11px; display: flex; flex-direction: column; gap: 8px; }
.tl-init-box { padding: 8px 10px; border-radius: 7px; background: var(--gpt-bg-subtle); border: 1px solid var(--gpt-border); display: flex; flex-direction: column; gap: 5px; font-size: 12px; }
.tl-init-row { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.tl-skill-chip { display: inline-flex; align-items: center; gap: 3px; padding: 1px 7px; border-radius: 999px; background: var(--gpt-accent-soft); border: 1px solid var(--gpt-accent-border); color: var(--gpt-accent); font-size: 11px; font-weight: 500; }
.tl-thought { padding: 7px 10px; border-radius: 7px; background: #f8fafc; border-left: 3px solid var(--gpt-accent-border); font-size: 12.5px; color: var(--gpt-ink); white-space: pre-wrap; word-break: break-word; line-height: 1.6; }
.tl-thought.is-clamped { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.tl-tool-card { border: 1px solid var(--gpt-border); border-radius: 8px; background: #fff; flex-shrink: 0; }
.tl-tool-card.is-failed { border-color: var(--gpt-coral-border); background: #fffafa; }
.tl-tool-head { width: 100%; border: none; background: transparent; padding: 7px 10px; display: flex; align-items: center; gap: 6px; cursor: pointer; text-align: left; font-size: 12px; color: var(--gpt-ink); flex-wrap: nowrap; }
.tl-tool-head:hover { background: var(--gpt-bg-subtle); border-radius: 7px; }
.tl-tool-chev { width: 14px; flex-shrink: 0; color: var(--gpt-ink-muted); font-size: 11px; text-align: center; }
.tl-tool-code { padding: 1px 6px; border-radius: 4px; background: var(--gpt-accent-soft); color: var(--gpt-accent); font-weight: 600; font-size: 11px; flex-shrink: 0; }
.tl-tool-code.is-err { background: var(--gpt-coral-bg); color: var(--gpt-coral); }
.tl-tool-cn { font-weight: 600; color: var(--gpt-ink); flex-shrink: 0; }
.tl-tool-sum { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--gpt-ink-secondary); font-size: 11.5px; }
.tl-tool-cid { font-size: 11px; color: var(--gpt-ink-muted); flex-shrink: 0; }
.tl-tool-st { font-size: 10.5px; padding: 1px 6px; border-radius: 999px; font-weight: 600; flex-shrink: 0; }
.tl-tool-st.ok { background: var(--gpt-emerald-bg); color: var(--gpt-emerald-ink); }
.tl-tool-st.err { background: var(--gpt-coral-bg); color: var(--gpt-coral); }
.tl-tool-detail { border-top: 1px dashed var(--gpt-border); padding: 8px 10px; display: flex; flex-direction: column; gap: 8px; background: var(--gpt-bg-subtle); border-radius: 0 0 7px 7px; }
.tl-json-head { display: flex; align-items: center; justify-content: space-between; font-size: 11px; font-weight: 600; color: var(--gpt-ink-secondary); margin-bottom: 4px; }
.tl-issues { display: flex; flex-direction: column; gap: 5px; margin-top: 4px; }
.tl-issue-row { padding: 5px 8px; border-radius: 6px; background: #fff; border: 1px solid var(--gpt-coral-border); font-size: 12px; display: flex; gap: 8px; }
.tl-issue-row.warn { border-color: var(--gpt-amber-border); }
.tl-cand-list { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.tl-cand-item { padding: 4px 8px; border-radius: 6px; background: #fff; border: 1px solid var(--gpt-border); font-size: 11.5px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tl-cand-item.selected { border-color: var(--gpt-accent-border); background: var(--gpt-accent-soft); }
.raw-pre { margin: 0; padding: 6px 8px; border-radius: 6px; background: #fff; border: 1px solid var(--gpt-border); font-family: var(--gpt-font-mono); font-size: 11px; color: var(--gpt-ink-secondary); white-space: pre-wrap; word-break: break-all; max-height: 220px; overflow-y: auto; }

.report-mini-card { border: 1px solid var(--gpt-border); border-radius: 12px; background: #fff; box-shadow: var(--gpt-shadow-xs); overflow: hidden; animation: fadeUp 0.24s ease both; }
.rmc-top { padding: 10px 13px; border-bottom: 1px solid var(--gpt-border); background: var(--gpt-bg-subtle); display: flex; align-items: center; justify-content: space-between; gap: 10px; cursor: pointer; }
.rmc-title-group { display: flex; align-items: center; gap: 7px; min-width: 0; flex: 1; }
.rmc-icon-badge { width: 24px; height: 24px; border-radius: 6px; flex-shrink: 0; background: var(--gpt-accent-soft); color: var(--gpt-accent); display: inline-flex; align-items: center; justify-content: center; }
.rmc-id { font-size: 12px; font-weight: 600; color: var(--gpt-accent); }
.rmc-title { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status-badge { padding: 1px 7px; border-radius: 999px; font-size: 11px; font-weight: 600; display: inline-flex; align-items: center; gap: 3px; flex-shrink: 0; }
.badge-emerald { background: var(--gpt-emerald-bg); border: 1px solid var(--gpt-emerald-border); color: var(--gpt-emerald-ink); }
.badge-amber { background: var(--gpt-amber-bg); border: 1px solid var(--gpt-amber-border); color: var(--gpt-amber); }
.badge-coral { background: var(--gpt-coral-bg); border: 1px solid var(--gpt-coral-border); color: var(--gpt-coral); }
.badge-blue { background: var(--gpt-accent-soft); border: 1px solid var(--gpt-accent-border); color: var(--gpt-accent); }
.badge-muted { background: var(--gpt-bg-muted); border: 1px solid var(--gpt-border); color: var(--gpt-ink-muted); }
.rmc-tools { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.mini-btn { height: 25px; padding: 0 8px; border-radius: 6px; border: 1px solid var(--gpt-border); background: #fff; color: var(--gpt-ink-secondary); font-size: 11.5px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; }
.mini-btn:hover { border-color: var(--gpt-accent-border); color: var(--gpt-accent); background: var(--gpt-accent-soft); }
.mini-btn.active { background: var(--gpt-accent); color: #fff; border-color: var(--gpt-accent); }
.rmc-body { padding: 14px 16px; font-size: 13.5px; line-height: 1.75; color: var(--gpt-ink); }
.rmc-body.is-raw { font-family: var(--gpt-font-mono); font-size: 12px; white-space: pre-wrap; background: var(--gpt-bg-subtle); line-height: 1.6; }
.rmc-body h1, .rmc-body h2, .rmc-body h3 { margin: 10px 0 6px; font-weight: 600; }
.rmc-body p { margin: 6px 0; }
.rmc-body hr { border: none; border-top: 1px solid var(--gpt-border); margin: 12px 0; }
.rmc-body ul { margin: 6px 0; padding-left: 20px; }
.rmc-body blockquote { margin: 8px 0; padding: 6px 12px; border-left: 3px solid var(--gpt-accent-border); background: var(--gpt-bg-subtle); color: var(--gpt-ink-secondary); }
.rmc-body code { padding: 1px 5px; border-radius: 4px; background: var(--gpt-bg-muted); font-family: var(--gpt-font-mono); font-size: 12px; }
.rmc-body pre { padding: 10px 12px; border-radius: 8px; background: var(--gpt-bg-subtle); border: 1px solid var(--gpt-border); overflow-x: auto; font-size: 12px; }
.rmc-foot { padding: 7px 14px; border-top: 1px solid var(--gpt-border); background: var(--gpt-bg-subtle); display: flex; align-items: center; justify-content: space-between; font-size: 11.5px; color: var(--gpt-ink-muted); flex-wrap: wrap; gap: 6px; }
.cursor-blink { display: inline-block; width: 7px; height: 14px; background: var(--gpt-accent); vertical-align: -2px; margin-left: 2px; animation: blink 0.8s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }

.bottom-dock { flex-shrink: 0; padding: 10px 20px 14px; background: linear-gradient(180deg, rgba(255,255,255,0) 0%, #fff 28%); }
.dock-box { max-width: 920px; margin: 0 auto; border: 1px solid var(--gpt-border-strong); border-radius: 20px; background: #fff; box-shadow: 0 4px 16px rgba(15,23,42,0.06); padding: 8px 14px; display: flex; flex-direction: column; gap: 6px; }
.dock-progress-track { height: 3px; border-radius: 999px; background: var(--gpt-bg-muted); overflow: hidden; }
.dock-progress-fill { height: 100%; background: var(--gpt-accent); width: 0%; transition: width 0.25s ease; }
.dock-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.dock-status { font-size: 12px; color: var(--gpt-ink-secondary); display: flex; align-items: center; gap: 6px; }
.dock-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

/* ==================== 视图 B：运行记录详情（复刻 RunsView 4 页签） ==================== */
.rd-head {
  flex-shrink: 0; padding: 10px 18px 0; border-bottom: 1px solid var(--gpt-border);
  background: var(--gpt-bg-subtle); display: flex; flex-direction: column; gap: 8px;
}
.rd-meta-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.rd-meta-left { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.rd-chip {
  font-size: 11.5px; padding: 2px 8px; border-radius: 5px;
  background: #fff; border: 1px solid var(--gpt-border); color: var(--gpt-ink-secondary);
}
.rd-alert {
  padding: 6px 10px; border-radius: 7px; font-size: 12px;
  display: flex; align-items: center; gap: 6px;
}
.rd-alert.warn { background: var(--gpt-amber-bg); border: 1px solid var(--gpt-amber-border); color: var(--gpt-amber); }
.rd-alert.err { background: var(--gpt-coral-bg); border: 1px solid var(--gpt-coral-border); color: var(--gpt-coral); }
.rd-tabs { display: flex; align-items: center; gap: 20px; border-top: 1px solid var(--gpt-border); }
.rd-tab {
  border: none; background: transparent; padding: 9px 2px 10px; font-size: 13px; font-weight: 500;
  color: var(--gpt-ink-secondary); cursor: pointer; position: relative;
  display: inline-flex; align-items: center; gap: 6px;
}
.rd-tab:hover { color: var(--gpt-ink); }
.rd-tab.active { color: var(--gpt-accent); font-weight: 600; }
.rd-tab.active::after {
  content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px;
  background: var(--gpt-accent); border-radius: 2px 2px 0 0;
}
.rd-tab-badge { font-size: 11px; padding: 0 6px; line-height: 17px; border-radius: 4px; background: var(--gpt-bg-muted); color: var(--gpt-ink-secondary); }
.rd-tab.active .rd-tab-badge { background: var(--gpt-accent-soft); color: var(--gpt-accent); }

.rd-body { flex: 1; min-height: 0; overflow: hidden; display: flex; flex-direction: column; background: var(--gpt-bg-subtle); }

/* 页签 1：正式报告单 */
.rd-report-wrap { flex: 1; overflow-y: auto; padding: 18px 22px 28px; }
.rd-sheet {
  max-width: 1020px; margin: 0 auto; background: #fff; border: 1px solid var(--gpt-border);
  border-top: 3px solid var(--gpt-accent); border-radius: 10px; box-shadow: var(--gpt-shadow-xs);
  padding: 18px 24px 24px;
}
.rd-sheet-bar {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;
  padding-bottom: 10px; margin-bottom: 14px; border-bottom: 1px solid var(--gpt-border);
  font-size: 12px; color: var(--gpt-ink-muted);
}
.rd-field-pills {
  margin-top: 16px; padding-top: 12px; border-top: 1px dashed var(--gpt-border);
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.rd-field-pill {
  font-size: 11.5px; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--gpt-accent-border);
  background: var(--gpt-accent-soft); color: var(--gpt-accent); cursor: pointer;
}
.rd-field-pill:hover { background: var(--gpt-accent); color: #fff; }

/* 页签 2：字段结果与证据（左右分栏联动） */
.rd-split { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(380px, 1fr) minmax(380px, 1.05fr); gap: 12px; padding: 12px 16px; overflow: hidden; }
.rd-panel { background: #fff; border: 1px solid var(--gpt-border); border-radius: 10px; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.rd-panel-head {
  padding: 9px 12px; border-bottom: 1px solid var(--gpt-border); background: var(--gpt-bg-subtle);
  display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;
}
.rd-panel-title { font-size: 12.5px; font-weight: 600; color: var(--gpt-ink); }
.rd-panel-scroll { flex: 1; overflow: auto; }

.field-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.field-table th, .field-table td { padding: 8px 10px; border-bottom: 1px solid var(--gpt-border); text-align: left; vertical-align: top; }
.field-table th { background: var(--gpt-bg-subtle); color: var(--gpt-ink-secondary); font-weight: 600; position: sticky; top: 0; z-index: 2; }
.field-row { cursor: pointer; transition: background 0.12s; }
.field-row:hover { background: var(--gpt-bg-subtle); }
.field-row.is-active { background: var(--gpt-accent-soft); box-shadow: inset 3px 0 0 var(--gpt-accent); }

.ev-subtabs { display: flex; gap: 4px; }
.ev-subtab {
  height: 25px; padding: 0 9px; border-radius: 6px; border: 1px solid var(--gpt-border);
  background: #fff; color: var(--gpt-ink-secondary); font-size: 11.5px; cursor: pointer;
}
.ev-subtab.active { background: var(--gpt-accent); color: #fff; border-color: var(--gpt-accent); font-weight: 600; }

.api-res-pills { padding: 8px 10px; border-bottom: 1px solid var(--gpt-border); display: flex; gap: 6px; flex-wrap: wrap; background: #fff; }
.api-res-meta { padding: 8px 12px; background: var(--gpt-bg-subtle); border-bottom: 1px solid var(--gpt-border); font-size: 11.5px; color: var(--gpt-ink-secondary); display: flex; flex-direction: column; gap: 4px; }
.api-data-table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
.api-data-table th, .api-data-table td { padding: 6px 8px; border-bottom: 1px solid var(--gpt-border); border-right: 1px solid var(--gpt-border); vertical-align: top; max-width: 420px; word-break: break-word; white-space: pre-wrap; }
.api-data-table th { background: var(--gpt-bg-subtle); position: sticky; top: 0; font-weight: 600; }
.api-data-table tr.hl-row { background: var(--gpt-hl-bg); }
.api-data-table td.hl-cell { background: #fde68a; outline: 2px solid var(--gpt-hl-border); outline-offset: -2px; }

.doc-lines { font-family: var(--gpt-font-mono); font-size: 12px; padding: 8px 0; }
.doc-line { display: flex; gap: 10px; padding: 2px 12px; line-height: 1.6; }
.doc-line.hl-line { background: var(--gpt-hl-bg); border-left: 3px solid var(--gpt-hl-border); padding-left: 9px; }
.doc-lno { width: 42px; flex-shrink: 0; color: var(--gpt-ink-muted); text-align: right; user-select: none; }
.doc-ltxt { flex: 1; white-space: pre-wrap; word-break: break-word; }

/* 页签 3：智能体时间线 */
.rd-tl-wrap { flex: 1; min-height: 0; overflow-y: auto; padding: 14px 18px 24px; }
.rd-tl-inner { max-width: 1040px; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }
.rd-tl-inner > * { flex-shrink: 0; }
.rd-kpi-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 8px; }
.rd-kpi { background: #fff; border: 1px solid var(--gpt-border); border-radius: 8px; padding: 8px 11px; }
.rd-kpi-lbl { font-size: 11px; color: var(--gpt-ink-muted); }
.rd-kpi-val { font-size: 15px; font-weight: 700; color: var(--gpt-ink); margin-top: 2px; }

/* 页签 4：输入与单据 */
.rd-inp-wrap { flex: 1; min-height: 0; overflow-y: auto; padding: 14px 18px 24px; }
.rd-inp-inner { max-width: 1040px; margin: 0 auto; display: flex; flex-direction: column; gap: 12px; }
.rd-inp-inner > * { flex-shrink: 0; }

/* 非找到字段情况摘要卡片 */
.mfs-wrap { max-width: 980px; margin: 0 auto 12px; }
.mfs-card { background: #fff; border: 1px solid var(--gpt-amber-border); border-left: 3px solid var(--gpt-amber); border-radius: 10px; overflow: hidden; box-shadow: var(--gpt-shadow-sm); }
.mfs-card.is-calm { border-color: var(--gpt-border); border-left-color: var(--gpt-ink-muted); }
.mfs-card.is-compact { border-radius: 0; border-left: none; border-right: none; border-top: none; box-shadow: none; border-bottom: 1px solid var(--gpt-border); }
.mfs-fields-wrap { flex-shrink: 0; max-height: 220px; overflow-y: auto; }
.mfs-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 12px; background: var(--gpt-amber-bg); cursor: pointer; flex-wrap: wrap; }
.mfs-card.is-calm .mfs-head { background: var(--gpt-bg-subtle); }
.mfs-head-left { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-width: 0; }
.mfs-title { font-size: 12.5px; font-weight: 600; color: var(--gpt-ink); }
.mfs-badge { font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--gpt-border); background: #fff; color: var(--gpt-ink-secondary); }
.mfs-badge.danger { background: var(--gpt-coral-bg); border-color: var(--gpt-coral-border); color: var(--gpt-coral); }
.mfs-badge.info { background: #eef4ff; border-color: #c7d9ff; color: var(--gpt-accent); }
.mfs-headline { padding: 7px 12px; font-size: 12.5px; line-height: 1.55; color: var(--gpt-ink); border-top: 1px solid var(--gpt-border); }
.mfs-body { padding: 0 12px 10px; display: flex; flex-direction: column; gap: 8px; }
.mfs-rcs { display: flex; flex-wrap: wrap; gap: 6px; }
.mfs-rc { display: inline-flex; align-items: center; gap: 6px; padding: 4px 9px; border-radius: 6px; font-size: 11.5px; border: 1px solid var(--gpt-border); background: var(--gpt-bg-subtle); }
.mfs-rc.sev-danger { background: var(--gpt-coral-bg); border-color: var(--gpt-coral-border); }
.mfs-rc.sev-warning { background: var(--gpt-amber-bg); border-color: var(--gpt-amber-border); }
.mfs-rc-t { font-weight: 600; white-space: nowrap; }
.mfs-rc.sev-danger .mfs-rc-t { color: var(--gpt-coral); }
.mfs-rc.sev-warning .mfs-rc-t { color: var(--gpt-amber); }
.mfs-ai { background: #f4f7ff; border: 1px solid #c7d9ff; border-radius: 8px; padding: 8px 10px; font-size: 12px; line-height: 1.6; }
.mfs-ai-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; font-weight: 600; color: var(--gpt-accent); font-size: 12px; }
.mfs-grp { border: 1px solid var(--gpt-border); border-radius: 7px; background: var(--gpt-bg-subtle); overflow: hidden; }
.mfs-grp.sev-danger { border-color: var(--gpt-coral-border); }
.mfs-grp.sev-warning { border-color: var(--gpt-amber-border); }
.mfs-grp-head { padding: 6px 10px; display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; cursor: pointer; font-size: 12px; }
.mfs-grp-chips { display: flex; gap: 4px; flex-wrap: wrap; }
.mfs-chip { font-size: 11px; padding: 1px 7px; border-radius: 4px; border: 1px solid var(--gpt-border); background: #fff; color: var(--gpt-ink); cursor: pointer; }
.mfs-chip:hover { border-color: var(--gpt-accent); color: var(--gpt-accent); }
.mfs-grp-list { border-top: 1px solid var(--gpt-border); background: #fff; }
.mfs-frow { display: flex; align-items: flex-start; gap: 10px; padding: 6px 10px; border-bottom: 1px solid var(--gpt-border); font-size: 12px; cursor: pointer; }
.mfs-frow:last-child { border-bottom: none; }
.mfs-frow:hover { background: var(--gpt-bg-hover); }
.mfs-fkey { width: 146px; flex-shrink: 0; font-weight: 600; color: var(--gpt-ink); }
.mfs-frea { flex: 1; min-width: 0; color: var(--gpt-ink-secondary); line-height: 1.5; word-break: break-word; }

/* 弹窗 & Toast */
.modal-mask { position: fixed; inset: 0; background: rgba(15,23,42,0.35); z-index: 50; display: none; align-items: center; justify-content: center; padding: 24px; }
.modal-mask.open { display: flex; }
.modal-card { width: min(860px, 100%); max-height: 86vh; background: #fff; border-radius: 14px; border: 1px solid var(--gpt-border); box-shadow: var(--gpt-shadow-md); display: flex; flex-direction: column; overflow: hidden; }
.modal-head { padding: 12px 16px; border-bottom: 1px solid var(--gpt-border); background: var(--gpt-bg-subtle); display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.modal-title { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.modal-body { padding: 14px 16px; overflow-y: auto; flex: 1; }
.kv-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.kv-table th, .kv-table td { padding: 7px 9px; border-bottom: 1px solid var(--gpt-border); text-align: left; vertical-align: top; }
.kv-table th { background: var(--gpt-bg-subtle); color: var(--gpt-ink-secondary); font-weight: 600; position: sticky; top: 0; }
.kv-table tr.hl-row { background: var(--gpt-hl-bg); }
.toast { position: fixed; top: 62px; left: 50%; transform: translateX(-50%) translateY(-8px); padding: 6px 14px; border-radius: 999px; background: #18181b; color: #fff; font-size: 12px; opacity: 0; pointer-events: none; transition: all 0.18s ease; z-index: 90; }
.toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

@media (max-width: 960px) {
  .rd-split { grid-template-columns: 1fr; overflow-y: auto; }
  .sidebar { position: fixed; left: 0; top: 0; bottom: 0; z-index: 40; box-shadow: var(--gpt-shadow-md); }
}
</style>
</head>
<body>
<div class="app-shell">
  <!-- 左侧运行记录列表（多条时默认展示） -->
  <aside id="sidebar" class="sidebar">
    <div class="sb-head">
      <div class="sb-title-row">
        <span class="sb-title">运行记录列表 <span id="sb-count" class="sb-count">0</span></span>
        <button id="btn-hide-sb" type="button" class="mini-btn">收起</button>
      </div>
      <input id="sb-search" class="sb-search" placeholder="搜索业务名 / 手机号 / 模板 / 编号…" />
      <div class="sb-filter-row" id="sb-filters">
        <button type="button" class="sb-chip active" data-st="ALL">全部</button>
        <button type="button" class="sb-chip" data-st="SUCCESS">成功</button>
        <button type="button" class="sb-chip" data-st="PARTIAL">部分</button>
        <button type="button" class="sb-chip" data-st="FAILED">失败</button>
      </div>
    </div>
    <div id="sb-list" class="sb-list"></div>
    <div class="sb-foot">
      <span id="sb-exported-at" class="mono"></span>
      <button id="btn-export-all-json" type="button" class="mini-btn" title="将当前 HTML 内的全部运行记录导出为纯 JSON 文件">导出全部 JSON</button>
    </div>
  </aside>

  <!-- 右侧主舞台 -->
  <main class="chat-stage">
    <header class="topbar">
      <div class="tb-brand">
        <button id="btn-toggle-sb" type="button" class="pill-btn" style="display:none">☰ 列表</button>
        <span class="brand-logo" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8L12 3z"/>
            <path d="M5 19l1-2 2-1-2-1-1-2-1 2-2 1 2 1 1 2z"/>
          </svg>
        </span>
        <span class="tb-title">智能填报助手</span>
        <div class="mode-switch" role="tablist" aria-label="视图切换">
          <button type="button" id="mode-chat" class="mode-btn active" data-view="chat">Chat 模拟回放</button>
          <button type="button" id="mode-detail" class="mode-btn" data-view="detail">运行记录详情</button>
        </div>
      </div>

      <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
        <div class="tb-controls" id="chat-controls">
          <div class="speed-seg" role="group" aria-label="回放速度">
            <button type="button" class="speed-btn active" data-speed="1">1x</button>
            <button type="button" class="speed-btn" data-speed="2">2x</button>
            <button type="button" class="speed-btn" data-speed="4">4x</button>
            <button type="button" class="speed-btn" data-speed="0">瞬间</button>
          </div>
          <button id="btn-pause" type="button" class="pill-btn">暂停</button>
          <button id="btn-replay" type="button" class="pill-btn primary">重播</button>
          <button id="btn-inputs" type="button" class="pill-btn">入参 (<span id="inputs-count">0</span>)</button>
        </div>
        <button id="btn-export-json" type="button" class="pill-btn" title="一键导出当前运行记录的完整纯 JSON（含 templateDef / usage / toolCalls / apiResults）">导出 JSON</button>
      </div>
    </header>

    <!-- 视图 A：Chat 模拟回放 -->
    <div id="pane-chat" class="view-pane">
      <section id="chat-scroll" class="chat-scroll">
        <div id="chat-stream" class="chat-stream"></div>
      </section>
      <footer class="bottom-dock">
        <div class="dock-box">
          <div class="dock-progress-track"><div id="dock-progress" class="dock-progress-fill"></div></div>
          <div class="dock-row">
            <div id="dock-status" class="dock-status">准备就绪</div>
            <div class="dock-actions">
              <button id="btn-prev" type="button" class="mini-btn" style="display:none">← 上一条</button>
              <button id="btn-next" type="button" class="mini-btn" style="display:none">下一条 →</button>
              <button id="btn-go-detail" type="button" class="mini-btn">查看运行记录详情 →</button>
              <button id="btn-instant" type="button" class="mini-btn">跳过动画直接看成稿</button>
            </div>
          </div>
        </div>
      </footer>
    </div>

    <!-- 视图 B：运行记录详情（复刻工作台 4 页签 + 左右分栏证据联动） -->
    <div id="pane-detail" class="view-pane is-hidden">
      <div id="rd-head" class="rd-head"></div>
      <div id="rd-body" class="rd-body"></div>
    </div>
  </main>
</div>

<!-- 弹窗 -->
<div id="modal-mask" class="modal-mask" role="dialog" aria-modal="true">
  <div class="modal-card">
    <div class="modal-head">
      <div id="modal-title" class="modal-title"></div>
      <div style="display:flex;gap:6px;align-items:center">
        <button id="modal-copy" type="button" class="mini-btn" style="display:none">复制内容</button>
        <button id="modal-close" type="button" class="mini-btn">关闭 ✕</button>
      </div>
    </div>
    <div id="modal-body" class="modal-body"></div>
  </div>
</div>

<div id="toast" class="toast"></div>

<script id="agent-replay-payload" type="application/json">__REPLAY_PAYLOAD__</script>
<script>
(function () {
  const payload = JSON.parse(document.getElementById('agent-replay-payload').textContent || '{}');
  const runs = Array.isArray(payload.runs) ? payload.runs : [];

  const els = {
    sidebar: document.getElementById('sidebar'),
    sbCount: document.getElementById('sb-count'),
    sbList: document.getElementById('sb-list'),
    sbSearch: document.getElementById('sb-search'),
    sbFilters: document.getElementById('sb-filters'),
    sbExportedAt: document.getElementById('sb-exported-at'),
    btnHideSb: document.getElementById('btn-hide-sb'),
    btnToggleSb: document.getElementById('btn-toggle-sb'),
    modeChat: document.getElementById('mode-chat'),
    modeDetail: document.getElementById('mode-detail'),
    chatControls: document.getElementById('chat-controls'),
    paneChat: document.getElementById('pane-chat'),
    paneDetail: document.getElementById('pane-detail'),
    rdHead: document.getElementById('rd-head'),
    rdBody: document.getElementById('rd-body'),
    btnPause: document.getElementById('btn-pause'),
    btnReplay: document.getElementById('btn-replay'),
    btnInputs: document.getElementById('btn-inputs'),
    btnExportJson: document.getElementById('btn-export-json'),
    btnExportAllJson: document.getElementById('btn-export-all-json'),
    inputsCount: document.getElementById('inputs-count'),
    chatScroll: document.getElementById('chat-scroll'),
    chatStream: document.getElementById('chat-stream'),
    dockProgress: document.getElementById('dock-progress'),
    dockStatus: document.getElementById('dock-status'),
    btnPrev: document.getElementById('btn-prev'),
    btnNext: document.getElementById('btn-next'),
    btnGoDetail: document.getElementById('btn-go-detail'),
    btnInstant: document.getElementById('btn-instant'),
    modalMask: document.getElementById('modal-mask'),
    modalTitle: document.getElementById('modal-title'),
    modalBody: document.getElementById('modal-body'),
    modalCopy: document.getElementById('modal-copy'),
    modalClose: document.getElementById('modal-close'),
    toast: document.getElementById('toast'),
  };

  let activeIdx = 0;
  let activeView = 'chat'; // 'chat' | 'detail'
  let detailTab = 'report'; // 'report' | 'fields' | 'timeline' | 'inputs'
  let detailReportRaw = false;
  let detailFieldFilter = 'all'; // 'all' | 'found' | 'not_found' | 'shown'
  let selectedFieldName = '';
  let evTab = 'api'; // 'api' | 'doc' | 'input'
  let activeApiResultId = '';
  let evHighlight = null; // { tab, resultId, row, column, line, endLine, key, callId }

  let filterStatus = 'ALL';
  let searchKw = '';
  let speed = 1;
  let paused = false;
  let playGen = 0;
  let traceExpanded = true;
  let traceMode = 'steps';
  let reportRawMode = false;
  let modalCopyPayload = '';

  const STATUS_TEXT = { SUCCESS: '核查成功', PARTIAL: '部分缺失', FAILED: '核查失败' };
  const EV_TYPE_LABEL = { quote: '原文引用', input: '入参', derive: '推导' };

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function showToast(msg) {
    els.toast.textContent = msg;
    els.toast.classList.add('show');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => els.toast.classList.remove('show'), 2200);
  }
  async function copyText(text, label) {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); document.body.removeChild(ta);
      }
      showToast(label || '已复制到剪贴板');
    } catch { showToast('复制失败，请手动选中复制'); }
  }
  function downloadJson(obj, filename) {
    try {
      const text = JSON.stringify(obj, null, 2);
      const blob = new Blob([text], { type: 'application/json;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1200);
      showToast('已导出 JSON：' + filename);
    } catch {
      showToast('导出 JSON 失败');
    }
  }
  function fmtJsonVal(v) {
    if (v == null) return '';
    return typeof v === 'string' ? v : JSON.stringify(v);
  }
  function fmtDur(ms) {
    const n = Number(ms) || 0;
    return n <= 0 ? '0.0s' : (n / 1000).toFixed(1) + 's';
  }
  function statusBadgeHtml(status) {
    if (status === 'SUCCESS') return '<span class="status-badge badge-emerald">核查成功</span>';
    if (status === 'PARTIAL') return '<span class="status-badge badge-amber">部分缺失</span>';
    return '<span class="status-badge badge-coral">核查失败</span>';
  }
  function iconSvg(kind) {
    const map = {
      start: '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20 6 4"/></svg>',
      skill: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
      api: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
      filter: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>',
      tool: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
      check: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>',
      warn: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      error: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
      done: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>',
      spinner: '<svg width="14" height="14" class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>',
      spark: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8L12 3z"/></svg>',
      doc: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>',
    };
    return map[kind] || map.tool;
  }

  function renderMarkdown(md) {
    const lines = String(md || '').replace(/\r\n/g, '\n').split('\n');
    const out = [];
    let inCode = false, codeBuf = [], inList = false;
    function inlineFmt(s) {
      let t = esc(s);
      t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
      t = t.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      t = t.replace(/(https?:\/\/[^\s<]+)/g, '<span class="mono" style="color:#2563eb">$1</span>');
      return t;
    }
    function flushList() { if (inList) { out.push('</ul>'); inList = false; } }
    for (const rawLine of lines) {
      if (rawLine.trim().startsWith('```')) {
        flushList();
        if (!inCode) { inCode = true; codeBuf = []; }
        else { out.push('<pre>' + esc(codeBuf.join('\n')) + '</pre>'); inCode = false; }
        continue;
      }
      if (inCode) { codeBuf.push(rawLine); continue; }
      const trimmed = rawLine.trim();
      if (!trimmed) { flushList(); continue; }
      if (/^-{3,}$/.test(trimmed) || /^\*{3,}$/.test(trimmed)) { flushList(); out.push('<hr/>'); continue; }
      const hm = trimmed.match(/^(#{1,3})\s+(.+)$/);
      if (hm) { flushList(); out.push('<h' + hm[1].length + '>' + inlineFmt(hm[2]) + '</h' + hm[1].length + '>'); continue; }
      if (/^>\s?/.test(trimmed)) { flushList(); out.push('<blockquote>' + inlineFmt(trimmed.replace(/^>\s?/, '')) + '</blockquote>'); continue; }
      if (/^[-*+]\s+/.test(trimmed)) {
        if (!inList) { out.push('<ul>'); inList = true; }
        out.push('<li>' + inlineFmt(trimmed.replace(/^[-*+]\s+/, '')) + '</li>');
        continue;
      }
      flushList();
      out.push('<p>' + inlineFmt(rawLine) + '</p>');
    }
    flushList();
    if (inCode) out.push('<pre>' + esc(codeBuf.join('\n')) + '</pre>');
    return out.join('');
  }

  /* ==================== 与项目 timelineFormat.ts / RawEventsTimeline.vue 100% 对齐的原样时间线 ==================== */
  const OUTCOME_TYPES = new Set(['report_rejected', 'report_accepted', 'report_degraded', 'run_failed', 'route_failed']);
  const TOOL_LABELS = {
    load_skill: '加载技能', list_templates: '检索模板', get_template: '查看模板',
    call_api: '调用接口', query_result: '结果筛选', normalize_text: '文本清洗',
    text_contains: '单据匹配', date_range: '日期窗口', format_date: '日期转换',
    extract_dates: '提取日期', date_shift: '日期偏移', expand_period: '展开账期',
    time_diff: '时间差计算', regex_extract: '正则提取',
  };
  const QUERY_OPS = {
    equals: '等于', contains: '包含', notContains: '不包含',
    normalizedContains: '清洗后包含', normalizedNotContains: '清洗后不包含',
    startsWith: '前缀为', between: '介于',
  };
  const rawFoldState = {}; // key -> boolean（展开工具详情或长思考文本）

  function asObj(v) { return (v && typeof v === 'object' && !Array.isArray(v)) ? v : {}; }
  function asStr(v) { return v == null ? '' : (typeof v === 'string' ? v : JSON.stringify(v)); }
  function clipStr(s, n) { const t = String(s || ''); return t.length > n ? t.slice(0, n) + '…' : t; }
  function isEvFailed(e) { const r = asObj(e.result); return e.ok === false || r.ok === false || Boolean(r.error); }

  function fmtQueryConds(args) {
    const a = asObj(args);
    const fmtOne = (raw) => {
      const c = asObj(raw);
      const col = asStr(c.column), op = QUERY_OPS[c.op] || asStr(c.op);
      const mods = [];
      if (c.before) mods.push(`“${asStr(c.before)}”之前`);
      if (typeof c.prefixLen === 'number' && c.prefixLen > 0) mods.push(`前${c.prefixLen}位`);
      const ms = mods.length ? `（${mods.join('，')}）` : '';
      return c.op === 'between' ? `${col}${ms} ${op} [${asStr(c.value)} ~ ${asStr(c.endValue)}]` : `${col}${ms} ${op} “${asStr(c.value)}”`;
    };
    const parts = [];
    if (Array.isArray(a.where) && a.where.length) parts.push(a.where.map(fmtOne).join(' 并且 '));
    if (Array.isArray(a.anyOf) && a.anyOf.length) {
      const orExpr = a.anyOf.map(fmtOne).join(' 或者 ');
      parts.push(a.anyOf.length > 1 ? `(${orExpr})` : orExpr);
    }
    const ord = asObj(a.orderBy);
    const ordTxt = ord.column ? `，按 ${asStr(ord.column)} ${ord.desc === false ? '升序' : '倒序'}` : '';
    return (parts.length ? parts.join(' 并且 ') : '无筛选条件') + ordTxt;
  }

  function describeTool(e) {
    const tool = e.tool || '';
    const cn = TOOL_LABELS[tool] || tool || '工具调用';
    const a = asObj(e.args), r = asObj(e.result);
    const failed = isEvFailed(e);
    const err = r.error ? asStr(r.error) : (failed ? '执行失败' : '');
    let sum = '';
    if (tool === 'load_skill') {
      const names = [];
      if (typeof a.name === 'string' && a.name.trim()) names.push(a.name.trim());
      if (Array.isArray(a.names)) a.names.forEach((x) => { const s = asStr(x).trim(); if (s && !names.includes(s)) names.push(s); });
      const docs = [];
      if (typeof a.doc === 'string' && a.doc.trim()) docs.push(a.doc.trim());
      if (Array.isArray(a.docs)) a.docs.forEach((x) => { const s = asStr(x).trim(); if (s && !docs.includes(s)) docs.push(s); });
      const titles = asStr(r.title) || (Array.isArray(r.titles) ? r.titles.map(asStr).filter(Boolean).join('、') : '');
      const base = (names.join('、') || '—') + (docs.length ? ` [${docs.join('、')}]` : '');
      sum = failed ? `${base} 失败：${err}` : (titles ? `${base}（${titles}）` : base);
    } else if (tool === 'call_api') {
      const apiName = asStr(a.name);
      if (failed) sum = `${apiName} 失败：${err}`;
      else {
        const cnt = r.count !== undefined ? `${asStr(r.count)} 条` : '完成';
        const cost = r.costMs !== undefined ? ` · ${asStr(r.costMs)}ms` : '';
        const rid = r.resultId ? ` → ${asStr(r.resultId)}` : '';
        sum = `${apiName}${rid}（${cnt}${cost}）`;
      }
    } else if (tool === 'query_result') {
      const rids = Array.isArray(a.resultIds) ? a.resultIds.map(asStr).filter(Boolean) : (a.resultId ? [asStr(a.resultId)] : []);
      const tgt = rids.join(' + ') || '结果集';
      sum = failed ? `${tgt} 失败：${err}` : `${tgt} [${clipStr(fmtQueryConds(a), 48)}] → 找到 ${asStr(r.total ?? 0)} 条`;
    } else if (tool === 'text_contains') {
      sum = failed ? `失败：${err}` : `查找 “${clipStr(asStr(a.target), 30)}” → ${r.contains ? '找到' : '未找到'}`;
    } else if (tool === 'date_range') {
      sum = failed ? `${asStr(a.time)} 失败：${err}` : `${asStr(a.time)} (${asStr(a.unit)}) → ${asStr(r.start)} ~ ${asStr(r.end)}`;
    } else if (tool === 'format_date') {
      sum = failed ? `失败：${err}` : `${clipStr(asStr(a.value ?? a.values), 24)} → ${clipStr(asStr(r.value ?? r.values), 28)}`;
    } else if (tool === 'extract_dates') {
      const cnt = Number(r.count ?? (Array.isArray(r.dates) ? r.dates.length : 0));
      sum = failed ? `失败：${err}` : (cnt > 0 ? `提取 ${cnt} 个日期（${asStr(r.min)} ~ ${asStr(r.max)}）` : '未提取到合法日期（0 个）');
    } else if (tool === 'date_shift') {
      sum = failed ? `失败：${err}` : `${asStr(a.date)} 偏移 ${asStr(a.days ?? 0)} 天 → ${asStr(r.date || r.start)}`;
    } else if (tool === 'expand_period') {
      const ms = Array.isArray(r.months) ? r.months.map(asStr).join('、') : asStr(r.startDate);
      sum = failed ? `失败：${err}` : `${clipStr(asStr(a.period), 20)} → ${ms}`;
    } else if (tool === 'time_diff') {
      sum = failed ? `失败：${err}` : `相差 ${asStr(r.diffSeconds ?? r.absSeconds)} 秒`;
    } else if (tool === 'regex_extract') {
      const cnt = Number(r.count ?? 0);
      sum = failed ? `失败：${err}` : (cnt > 0 ? `找到 ${cnt} 项（首项：“${clipStr(asStr(r.first), 30)}”）` : '未找到（0 项）');
    } else if (tool === 'normalize_text') {
      sum = failed ? `失败：${err}` : `“${clipStr(asStr(r.value), 44)}”`;
    } else if (tool === 'list_templates') {
      sum = failed ? `失败：${err}` : `返回 ${asStr(r.count ?? r.total ?? (Array.isArray(e.result) ? e.result.length : ''))} 个在线模板`;
    } else if (tool === 'get_template') {
      sum = failed ? `失败：${err}` : `#${asStr(a.templateId ?? a.id ?? r.id)} ${asStr(r.name ?? r.templateName)}`;
    } else {
      sum = failed ? `失败：${err}` : clipStr(asStr(a), 56);
    }
    return { tool, cn, failed, sum };
  }

  function formatRoundTitle(g) {
    if (g.round === 0) {
      if (g.items.some((e) => e.type === 'route_started' || e.type === 'route_completed')) return '自动路由 · 模板匹配与启动';
      if (g.items.some((e) => e.type === 'run_started')) return '初始化 · 启动核查运行';
    }
    const labels = [];
    const add = (s) => { if (!labels.includes(s)) labels.push(s); };
    for (const e of g.items) {
      if (e.type === 'model_text') add('推理说明');
      else if (e.type === 'tool') {
        if (e.tool === 'load_skill') add('加载技能');
        else if (e.tool === 'list_templates' || e.tool === 'get_template') add('检索模板');
        else if (e.tool === 'call_api') add('接口查询');
        else if (e.tool === 'query_result') add('记录筛选');
        else add('确定性工具计算');
      }
    }
    if (!labels.length) labels.push('请求大模型');
    return `第 ${g.round} 轮 · ${labels.join('、')}`;
  }

  function renderRawEventsHtml(rawEvents, uptoIndex, scopeKey) {
    const visible = rawEvents.slice(0, uptoIndex).slice().sort((a, b) => (a.seq || 0) - (b.seq || 0));
    if (!visible.length) return '<div style="padding:18px;text-align:center;color:var(--gpt-ink-muted);font-size:12px">暂无原样运行事件记录</div>';
    const byRound = new Map();
    for (const e of visible) {
      const rnd = e.round || 0;
      if (!byRound.has(rnd)) byRound.set(rnd, { round: rnd, atMs: e.atMs || 0, items: [], outcomes: [] });
      const g = byRound.get(rnd);
      if (OUTCOME_TYPES.has(e.type)) g.outcomes.push(e);
      else if (e.type !== 'model_request') g.items.push(e);
    }

    const parts = [];
    for (const g of byRound.values()) {
      if (g.items.length > 0 || g.outcomes.length === 0) {
        const itemsHtml = !g.items.length
          ? '<div style="font-size:12px;color:var(--gpt-ink-muted)">已请求大模型，等待结构化响应…</div>'
          : g.items.map((e, idx) => {
              const fkey = `${scopeKey}_${e.seq || idx}`;
              if (e.type === 'route_started') {
                return `<div class="tl-init-box">
                  <div class="tl-init-row"><strong>开始自动路由匹配模板</strong>${e.rev ? `<span class="rd-chip mono">${esc(e.rev)}</span>` : ''}</div>
                  <div class="tl-init-row"><span style="color:var(--gpt-ink-muted)">路由技能：</span>${e.routerSkill ? `<span class="tl-skill-chip">${esc(e.routerSkill)}</span>` : '<span style="color:var(--gpt-ink-muted)">未配置（回退检索在线模板）</span>'}</div>
                </div>`;
              }
              if (e.type === 'route_completed') {
                const cands = Array.isArray(e.candidates) ? e.candidates : [];
                return `<div class="tl-init-box" style="background:#f8faff;border-color:var(--gpt-accent-border)">
                  <div class="tl-init-row">
                    <span>命中模板：</span><strong>#${esc(e.templateId)} ${esc(e.templateName || '')}</strong>
                    ${e.confidence ? `<span class="route-conf">置信度 ${esc(e.confidence)}</span>` : ''}
                    ${e.durationMs != null ? `<span class="rd-chip mono">${fmtDur(e.durationMs)}</span>` : ''}
                  </div>
                  ${e.reason ? `<div style="color:var(--gpt-ink-secondary)"><strong>命中理由：</strong>${esc(e.reason)}</div>` : ''}
                  ${cands.length ? `<div class="tl-cand-list">${cands.map((c) => `<div class="tl-cand-item ${c.templateId === e.templateId ? 'selected' : ''}"><span class="mono" style="font-weight:600">#${esc(c.templateId)}</span><span>${esc(c.templateName || '')}</span><span class="status-badge badge-blue">${esc(c.level || '')}</span><span style="color:var(--gpt-ink-secondary)">${esc(c.reason || '')}</span></div>`).join('')}</div>` : ''}
                </div>`;
              }
              if (e.type === 'run_started') {
                const sks = Array.isArray(e.skills) ? e.skills : [];
                const apis = Array.isArray(e.apis) ? e.apis : [];
                return `<div class="tl-init-box">
                  <div class="tl-init-row"><span>模板：</span><strong>#${esc(e.templateId || '—')} ${esc(e.templateName || '')}</strong>${e.rev ? `<span class="rd-chip mono">${esc(e.rev)}</span>` : ''}</div>
                  <div class="tl-init-row"><span style="color:var(--gpt-ink-muted)">允许技能：</span>${sks.length ? sks.map((s) => `<span class="tl-skill-chip">${esc(s)}</span>`).join('') : '<span style="color:var(--gpt-ink-muted)">无</span>'}</div>
                  <div class="tl-init-row"><span style="color:var(--gpt-ink-muted)">授权 API：</span>${apis.length ? apis.map((a) => `<span class="rd-chip mono">${esc(a)}</span>`).join('') : '<span style="color:var(--gpt-ink-muted)">无</span>'}</div>
                </div>`;
              }
              if (e.type === 'model_text') {
                const txt = String(e.text || '');
                const isLong = txt.length > 160;
                const open = Boolean(rawFoldState['txt_' + fkey]);
                return `<div>
                  <div class="tl-thought ${isLong && !open ? 'is-clamped' : ''}">${esc(txt)}</div>
                  ${isLong ? `<button type="button" class="mini-btn" style="margin-top:4px" data-tl-fold="txt_${esc(fkey)}">${open ? '收起思考' : '展开全部思考'}</button>` : ''}
                </div>`;
              }
              if (e.type === 'tool') {
                const m = describeTool(e);
                const open = Boolean(rawFoldState['tool_' + fkey]);
                const argsPretty = JSON.stringify(e.args != null ? e.args : {}, null, 2);
                const resPretty = JSON.stringify(e.result !== undefined ? e.result : null, null, 2);
                return `<div class="tl-tool-card ${m.failed ? 'is-failed' : ''}">
                  <button type="button" class="tl-tool-head" data-tl-fold="tool_${esc(fkey)}">
                    <span class="tl-tool-chev">${open ? '▾' : '▸'}</span>
                    <span class="tl-tool-code mono ${m.failed ? 'is-err' : ''}">${esc(m.tool)}</span>
                    <span class="tl-tool-cn">${esc(m.cn)}</span>
                    <span class="tl-tool-sum" title="${esc(m.sum)}">${esc(m.sum)}</span>
                    ${e.callId ? `<span class="tl-tool-cid mono">#${esc(e.callId)}</span>` : ''}
                    <span class="tl-tool-st ${m.failed ? 'err' : 'ok'}">${m.failed ? '失败' : '成功'}</span>
                  </button>
                  ${open ? `<div class="tl-tool-detail">
                    <div>
                      <div class="tl-json-head"><span>入参 args</span><button type="button" class="mini-btn" data-tl-copy="${esc(argsPretty)}">复制</button></div>
                      <pre class="raw-pre">${esc(argsPretty)}</pre>
                    </div>
                    <div>
                      <div class="tl-json-head"><span>返回 result</span><button type="button" class="mini-btn" data-tl-copy="${esc(resPretty)}">复制</button></div>
                      <pre class="raw-pre">${esc(resPretty)}</pre>
                    </div>
                  </div>` : ''}
                </div>`;
              }
              return `<div class="tl-init-box"><span class="mono" style="font-weight:600">${esc(e.type)}</span><pre class="raw-pre">${esc(JSON.stringify(e, null, 2))}</pre></div>`;
            }).join('');

        parts.push(`<div class="raw-round">
          <div class="raw-round-head"><span>${esc(formatRoundTitle(g))}</span><span class="mono">+${fmtDur(g.atMs)}</span></div>
          <div class="raw-round-body">${itemsHtml}</div>
        </div>`);
      }

      for (const o of g.outcomes) {
        const cls = o.type === 'report_accepted' ? 'oc-pass' : (o.type === 'report_degraded' ? 'oc-warn' : 'oc-err');
        const headTitle =
          o.type === 'report_accepted' ? `第 ${g.round} 轮 · 证据核验通过` :
          o.type === 'report_degraded' ? `第 ${g.round} 轮 · 降级按未找到处理` :
          o.type === 'report_rejected' ? `第 ${g.round} 轮 · 证据校验退回重填` :
          o.type === 'route_failed' ? '自动路由 · 模板匹配失败' : `第 ${g.round} 轮 · 运行终止失败`;
        const msg =
          o.type === 'report_accepted' ? `第 ${o.attempt || 1} 次提交全部通过字段证据一致性核验。` :
          o.type === 'report_rejected' ? `第 ${o.attempt || 1} 次提交被证据校验器退回重填：` :
          o.type === 'report_degraded' ? `重试耗尽，以下字段降级按缺失处理：${(o.fields || []).join('、') || '—'}` :
          o.type === 'route_failed' ? `自动路由失败：${o.error || o.reason || '未匹配到可用模板'}` :
          `运行失败：${o.error || '未知错误'}`;
        const issues = Array.isArray(o.issues) ? o.issues : [];
        const issuesHtml = issues.length ? `<div class="tl-issues">${issues.map((iss) =>
          `<div class="tl-issue-row ${o.type === 'report_degraded' ? 'warn' : ''}"><strong>${esc(iss.field || '')}</strong><span>${esc(iss.message || '')}</span></div>`
        ).join('')}</div>` : '';

        parts.push(`<div class="raw-round ${cls}">
          <div class="raw-round-head"><span>${esc(headTitle)}</span><span class="mono">+${fmtDur(o.atMs)}</span></div>
          <div class="raw-round-body"><div style="font-size:12.5px;font-weight:600">${esc(msg)}</div>${issuesHtml}</div>
        </div>`);
      }
    }
    return parts.join('');
  }

  function bindRawTimelineEvents(container, rerenderFn) {
    container.querySelectorAll('[data-tl-fold]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const k = btn.getAttribute('data-tl-fold');
        if (!k) return;
        rawFoldState[k] = !rawFoldState[k];
        rerenderFn();
      });
    });
    container.querySelectorAll('[data-tl-copy]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        copyText(btn.getAttribute('data-tl-copy') || '', '已复制 JSON');
      });
    });
  }

  function filteredRunIndices() {
    const kw = searchKw.trim().toLowerCase();
    const res = [];
    runs.forEach((r, idx) => {
      if (filterStatus !== 'ALL' && r.status !== filterStatus) return;
      if (kw) {
        const hay = [
          r.runId, r.templateId, r.templateName,
          r.inputs && r.inputs['业务名称'], r.inputs && r.inputs['手机号码'], r.inputs && r.inputs['申诉内容']
        ].filter(Boolean).join(' ').toLowerCase();
        if (!hay.includes(kw)) return;
      }
      res.push(idx);
    });
    return res;
  }

  function renderSidebar() {
    els.sbCount.textContent = String(runs.length);
    els.sbExportedAt.textContent = payload.exportedAt || '';
    const multi = runs.length > 1;
    els.btnPrev.style.display = multi ? '' : 'none';
    els.btnNext.style.display = multi ? '' : 'none';
    if (!multi) {
      els.sidebar.classList.add('is-hidden');
      els.btnToggleSb.style.display = 'none';
      return;
    }
    const indices = filteredRunIndices();
    if (!indices.length) {
      els.sbList.innerHTML = '<div style="padding:20px;text-align:center;color:var(--gpt-ink-muted);font-size:12px">无匹配运行记录</div>';
      return;
    }
    els.sbList.innerHTML = indices.map((idx) => {
      const r = runs[idx];
      const biz = (r.inputs && r.inputs['业务名称']) || r.templateName || r.runId;
      const mobile = (r.inputs && r.inputs['手机号码']) || '';
      const dotCls = 'dot-' + String(r.status || 'failed').toLowerCase();
      return `<button type="button" class="sb-item ${idx === activeIdx ? 'active' : ''}" data-idx="${idx}">
        <div class="sb-item-top">
          <span class="dot ${esc(dotCls)}"></span>
          <span class="sb-item-name" title="${esc(biz)}">${esc(biz)}</span>
          <span class="mono" style="font-size:11px;color:var(--gpt-ink-muted)">${fmtDur(r.durationMs)}</span>
        </div>
        <div class="sb-item-sub">
          <span class="sb-item-tpl">#${esc(r.templateId || '—')} ${esc(r.templateName || '')}</span>
          <span class="mono">${esc(mobile)}</span>
        </div>
      </button>`;
    }).join('');
    els.sbList.querySelectorAll('.sb-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        const nextIdx = Number(btn.getAttribute('data-idx'));
        if (Number.isFinite(nextIdx)) selectRun(nextIdx, false);
      });
    });
  }

  function switchView(view, targetDetailTab) {
    activeView = view;
    if (targetDetailTab) detailTab = targetDetailTab;
    els.modeChat.classList.toggle('active', view === 'chat');
    els.modeDetail.classList.toggle('active', view === 'detail');
    els.paneChat.classList.toggle('is-hidden', view !== 'chat');
    els.paneDetail.classList.toggle('is-hidden', view !== 'detail');
    els.chatControls.style.display = view === 'chat' ? 'flex' : 'none';
    if (view === 'detail') {
      renderDetailView();
    }
  }

  /* ==================== 视图 B：运行记录详情（复刻 RunsView 4 页签 + 证据联动） ==================== */
  function jumpToFieldEvidence(fieldName) {
    const run = runs[activeIdx];
    if (!run) return;
    const f = (run.fields || []).find((x) => x.name === fieldName);
    selectedFieldName = fieldName;
    if (f && f.evidenceTarget) {
      evHighlight = f.evidenceTarget;
      evTab = f.evidenceTarget.tab || 'doc';
      if (evTab === 'api' && f.evidenceTarget.resultId) {
        activeApiResultId = f.evidenceTarget.resultId;
      }
    } else {
      evHighlight = null;
    }
    switchView('detail', 'fields');
  }

  function renderDetailHead(run) {
    const routingBanner = run.routing ? `
      <div class="route-card" style="padding:7px 11px">
        <div class="route-head">
          <span class="route-pill">自动路由命中</span>
          <strong class="mono">#${esc(run.routing.templateId || run.templateId)}</strong>
          <strong>${esc(run.routing.templateName || run.templateName)}</strong>
          <span class="route-conf">置信度 ${esc(run.routing.confidence || '高')}</span>
          ${run.routing.durationMs ? `<span class="mono" style="font-size:11px;color:var(--gpt-ink-muted)">${fmtDur(run.routing.durationMs)}</span>` : ''}
          ${run.routing.reason ? `<span class="route-reason">${esc(run.routing.reason)}</span>` : ''}
        </div>
      </div>` : '';

    const errBanner = run.error ? `<div class="rd-alert err">运行失败：${esc(run.error)}</div>` : '';
    const msCount = (run.missingSummary && run.missingSummary.nonFoundCount) || 0;
    const missBanner = (run.missingShown && run.missingShown.length)
      ? `<div class="rd-alert warn" style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
          <span>报告中显示但未找到证据的字段：${esc(run.missingShown.join('、'))}</span>
          ${msCount && detailTab !== 'missing' ? '<button type="button" class="mini-btn" id="rd-jump-missing">查看缺失摘要 →</button>' : ''}
        </div>` : '';
    const missTabBtn = msCount ? `
        <button type="button" class="rd-tab ${detailTab === 'missing' ? 'active' : ''}" data-dtab="missing">
          <span>缺失摘要</span><span class="rd-tab-badge mono">${msCount} 项</span>
        </button>` : '';

    els.rdHead.innerHTML = `
      <div class="rd-meta-row">
        <div class="rd-meta-left">
          <button type="button" class="runid-chip mono" id="rd-copy-id" title="点击复制运行编号">${esc(run.runId)}</button>
          ${statusBadgeHtml(run.status)}
          <span class="rd-chip">#${esc(run.templateId || '—')} ${esc(run.templateName)}</span>
          <span class="rd-chip mono">${fmtDur(run.durationMs)}</span>
          <span class="rd-chip mono">${run.rounds || 0} 轮</span>
          ${run.model ? `<span class="rd-chip mono">${esc(run.model)}</span>` : ''}
          <span class="rd-chip mono">${esc(run.rev)}</span>
          <span class="rd-chip">${esc(run.entry)}</span>
          ${run.batchNo ? `<span class="rd-chip mono">批次 ${esc(run.batchNo)}</span>` : ''}
        </div>
        <div style="display:flex;gap:6px">
          <button type="button" class="mini-btn" id="rd-export-json">导出当前 JSON</button>
          <button type="button" class="mini-btn" id="rd-to-chat">← 回到 Chat 模拟回放</button>
        </div>
      </div>
      ${routingBanner}${errBanner}${missBanner}
      <div class="rd-tabs" role="tablist">
        <button type="button" class="rd-tab ${detailTab === 'report' ? 'active' : ''}" data-dtab="report">
          <span>报告</span><span class="rd-tab-badge">成稿</span>
        </button>
        <button type="button" class="rd-tab ${detailTab === 'fields' ? 'active' : ''}" data-dtab="fields">
          <span>字段结果与证据</span><span class="rd-tab-badge mono">${run.foundCount}/${run.totalCount}</span>
        </button>
        ${missTabBtn}
        <button type="button" class="rd-tab ${detailTab === 'timeline' ? 'active' : ''}" data-dtab="timeline">
          <span>智能体时间线</span><span class="rd-tab-badge mono">${(run.rawEvents || []).length} 事件</span>
        </button>
        <button type="button" class="rd-tab ${detailTab === 'inputs' ? 'active' : ''}" data-dtab="inputs">
          <span>输入与单据</span><span class="rd-tab-badge mono">${Object.keys(run.inputs || {}).length} 项</span>
        </button>
      </div>`;

    els.rdHead.querySelector('#rd-copy-id').addEventListener('click', () => copyText(run.runId, '已复制运行编号'));
    const jumpMissBtn = els.rdHead.querySelector('#rd-jump-missing');
    if (jumpMissBtn) jumpMissBtn.addEventListener('click', () => { detailTab = 'missing'; renderDetailView(); });
    els.rdHead.querySelector('#rd-export-json').addEventListener('click', () => downloadJson(run, `run-${run.runId || 'detail'}.json`));
    els.rdHead.querySelector('#rd-to-chat').addEventListener('click', () => switchView('chat'));
    els.rdHead.querySelectorAll('.rd-tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        detailTab = btn.getAttribute('data-dtab') || 'report';
        renderDetailView();
      });
    });
  }

  function renderMissingSummaryHtml(run, mode) {
    const ms = run.missingSummary;
    if (!ms || !ms.nonFoundCount) return '';
    const isFull = mode === 'full';
    const calm = (ms.impactedCount || 0) === 0;
    const expKey = 'mfs_' + (isFull ? 'full_' : 'rep_') + run.runId;
    // 独立「缺失摘要」页签常驻展开；「报告」页签默认收起为单行紧凑条，避免挤压报告正文
    const isExp = isFull ? true : (expKey in rawFoldState ? !!rawFoldState[expKey] : false);
    const badges = [
      ms.shownMissingCount > 0 ? `<span class="mfs-badge danger mono">影响报告 ${ms.shownMissingCount} 项</span>` : '',
      ms.defaultFallbackCount > 0 ? `<span class="mfs-badge info mono">默认值兜底 ${ms.defaultFallbackCount} 项</span>` : '',
      ms.skippedCount > 0 ? `<span class="mfs-badge mono">条件跳过 ${ms.skippedCount} 项</span>` : '',
      `<span class="mfs-badge mono">共 ${ms.nonFoundCount}/${ms.totalFields} 非找到</span>`,
    ].filter(Boolean).join('');

    let bodyHtml = '';
    if (isExp) {
      const rcs = (ms.rootCauses || []).map((rc) =>
        `<div class="mfs-rc sev-${esc(rc.severity || 'info')}"><span class="mfs-rc-t">${esc(rc.title)}</span><span>${esc(rc.detail)}</span></div>`
      ).join('');
      const ai = ms.aiSummary;
      const aiHtml = ai && ai.text ? `
        <div class="mfs-ai">
          <div class="mfs-ai-head">
            <span>AI 总结${ai.model ? ` · <span class="mono" style="font-weight:400;font-size:11px">${esc(ai.model)}</span>` : ''}${ai.generatedAt ? ` <span class="mono" style="font-weight:400;font-size:11px;color:var(--gpt-ink-muted)">${esc(ai.generatedAt)}</span>` : ''}</span>
            <button type="button" class="mini-btn" data-mfs-copy-ai="1">复制 AI 总结</button>
          </div>
          <div class="rmc-body" style="padding:0;font-size:12px">${renderMarkdown(ai.text)}</div>
        </div>` : '';
      const groupsHtml = (ms.groups || []).map((g) => {
        const gKey = expKey + '_g_' + g.code;
        const gExp = gKey in rawFoldState ? !!rawFoldState[gKey] : g.code !== 'condition_skipped';
        const chips = (g.fields || []).map((f) =>
          `<button type="button" class="mfs-chip" data-mfs-field="${esc(f.name)}">${esc(f.name)}</button>`
        ).join('');
        const listHtml = gExp ? `<div class="mfs-grp-list">${(g.fields || []).map((f) =>
          `<div class="mfs-frow" data-mfs-field="${esc(f.name)}">
            <div class="mfs-fkey">${esc(f.name)}</div>
            <div class="mfs-frea">${esc(f.briefReason || f.reasoning || '—')}</div>
          </div>`
        ).join('')}</div>` : '';
        return `<div class="mfs-grp sev-${esc(g.severity || 'info')}">
          <div class="mfs-grp-head" data-mfs-gtoggle="${esc(gKey)}">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;min-width:0;flex:1">
              <span style="font-weight:600">${gExp ? '▾' : '▸'} ${esc(g.label)}</span>
              <span class="mono" style="font-size:11px;color:var(--gpt-ink-muted)">${g.count} 项</span>
              <span style="color:var(--gpt-ink-secondary)">${esc(g.summary || '')}</span>
            </div>
            <div class="mfs-grp-chips">${chips}</div>
          </div>
          ${listHtml}
        </div>`;
      }).join('');
      bodyHtml = `<div class="mfs-body">${rcs ? `<div class="mfs-rcs">${rcs}</div>` : ''}${aiHtml}${groupsHtml}</div>`;
    }

    const card = `<section class="mfs-card ${calm ? 'is-calm' : ''}">
      <div class="mfs-head" ${isFull ? 'style="cursor:default"' : `data-mfs-toggle="${esc(expKey)}"`}>
        <div class="mfs-head-left">
          <span class="mfs-title">${isFull ? '' : (isExp ? '▾ ' : '▸ ')}非找到字段情况摘要</span>
          ${badges}
        </div>
        <button type="button" class="mini-btn" data-mfs-copy="1">复制摘要</button>
      </div>
      <div class="mfs-headline">${esc(ms.headline || '')}</div>
      ${bodyHtml}
    </section>`;
    return `<div class="mfs-wrap">${card}</div>`;
  }

  function renderDetailMissingTab(run) {
    const ms = run.missingSummary;
    const inner = (ms && ms.nonFoundCount)
      ? renderMissingSummaryHtml(run, 'full')
      : '<div style="text-align:center;color:var(--gpt-ink-muted);padding:48px 0;font-size:13px">本次运行所有字段均已找到，无缺失项。</div>';
    els.rdBody.innerHTML = `<div class="rd-tl-wrap">${inner}</div>`;
    bindMissingSummaryEvents(els.rdBody, run, () => renderDetailMissingTab(run));
  }

  function bindMissingSummaryEvents(container, run, repaintFn) {
    if (!container) return;
    const ms = run.missingSummary;
    container.querySelectorAll('[data-mfs-toggle]').forEach((el) => {
      el.addEventListener('click', (ev) => {
        if (ev.target && ev.target.closest('button')) return;
        const k = el.getAttribute('data-mfs-toggle');
        const cur = k in rawFoldState ? !!rawFoldState[k] : false;
        rawFoldState[k] = !cur;
        repaintFn();
      });
    });
    container.querySelectorAll('[data-mfs-gtoggle]').forEach((el) => {
      el.addEventListener('click', (ev) => {
        if (ev.target && ev.target.closest('button')) return;
        const k = el.getAttribute('data-mfs-gtoggle');
        const defOpen = !k.endsWith('_g_condition_skipped');
        const cur = k in rawFoldState ? !!rawFoldState[k] : defOpen;
        rawFoldState[k] = !cur;
        repaintFn();
      });
    });
    container.querySelectorAll('[data-mfs-field]').forEach((el) => {
      el.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const fname = el.getAttribute('data-mfs-field') || '';
        if (fname) jumpToFieldEvidence(fname);
      });
    });
    const copyBtn = container.querySelector('[data-mfs-copy]');
    if (copyBtn && ms) {
      copyBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        copyText(ms.plainText || ms.headline || '', '已复制未找到字段摘要');
      });
    }
    const copyAiBtn = container.querySelector('[data-mfs-copy-ai]');
    if (copyAiBtn && ms && ms.aiSummary) {
      copyAiBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        copyText(ms.aiSummary.text || '', '已复制 AI 缺失总结');
      });
    }
  }

  function renderDetailReportTab(run) {
    const shownFields = (run.fields || []).filter((f) => f.shown && f.status === 'found');
    const pillsHtml = shownFields.length ? `
      <div class="rd-field-pills">
        <span style="font-size:11.5px;color:var(--gpt-ink-muted)">点击字段溯源证据：</span>
        ${shownFields.map((f) => `<button type="button" class="rd-field-pill" data-fname="${esc(f.name)}">${esc(f.name)}</button>`).join('')}
      </div>` : '';

    els.rdBody.innerHTML = `<div class="rd-report-wrap">
      ${renderMissingSummaryHtml(run, 'report')}
      <div class="rd-sheet">
        <div class="rd-sheet-bar">
          <div>模板 <strong>#${esc(run.templateId || '—')} ${esc(run.templateName)}</strong> · 版本 <span class="mono">${esc(run.rev)}</span> · 开始时间 <span class="mono">${esc(run.startTime)}</span></div>
          <div style="display:flex;gap:6px">
            <button type="button" class="mini-btn" id="rd-rep-mode">${detailReportRaw ? '渲染视图' : 'Markdown 原文'}</button>
            <button type="button" class="mini-btn" id="rd-rep-copy">复制报告</button>
          </div>
        </div>
        <div class="rmc-body ${detailReportRaw ? 'is-raw' : ''}" style="padding:0">${
          run.report ? (detailReportRaw ? esc(run.report) : renderMarkdown(run.report)) : '<div style="text-align:center;color:var(--gpt-ink-muted);padding:36px 0">暂无成稿报告</div>'
        }</div>
        ${pillsHtml}
      </div>
    </div>`;

    bindMissingSummaryEvents(els.rdBody, run, () => renderDetailReportTab(run));
    els.rdBody.querySelector('#rd-rep-mode').addEventListener('click', () => { detailReportRaw = !detailReportRaw; renderDetailReportTab(run); });
    els.rdBody.querySelector('#rd-rep-copy').addEventListener('click', () => copyText(run.report || '', '已复制报告 Markdown'));
    els.rdBody.querySelectorAll('.rd-field-pill').forEach((b) => {
      b.addEventListener('click', () => jumpToFieldEvidence(b.getAttribute('data-fname') || ''));
    });
  }

  function renderEvidenceInspectorContent(run) {
    const apiResults = run.apiResults || [];
    const docLines = run.documentLines || [];
    const inputs = run.inputs || {};
    const toolCalls = run.toolCalls || [];

    if (evTab === 'api') {
      if (!apiResults.length) {
        return '<div style="padding:28px;text-align:center;color:var(--gpt-ink-muted);font-size:12px">本次运行未调用外部网关接口</div>';
      }
      const cur = apiResults.find((r) => r.resultId === activeApiResultId) || apiResults[0];
      activeApiResultId = cur.resultId;
      const pills = apiResults.map((r) =>
        `<button type="button" class="mini-btn ${r.resultId === cur.resultId ? 'active' : ''}" data-rid="${esc(r.resultId)}">
          <span class="mono">${esc(r.resultId)}</span> ${esc(r.title)} (${(r.records || []).length})
        </button>`
      ).join('');
      const colKeys = Object.keys(cur.columns || {});
      const sampleRec = (cur.records || [])[0] || {};
      const headers = colKeys.length ? colKeys : Object.keys(sampleRec).filter((k) => k !== 'row');
      const hlRow = (evHighlight && evHighlight.tab === 'api' && evHighlight.resultId === cur.resultId) ? evHighlight.row : null;
      const hlCol = (evHighlight && evHighlight.tab === 'api' && evHighlight.resultId === cur.resultId) ? evHighlight.column : null;

      const rowsHtml = (cur.records || []).map((rec, idx) => {
        const rNum = rec.row != null ? Number(rec.row) : idx;
        const isHl = hlRow !== null && Number(hlRow) === rNum;
        const tds = headers.map((h) => {
          const isCellHl = isHl && hlCol && hlCol === h;
          return `<td class="${isCellHl ? 'hl-cell' : ''}">${esc(rec[h] == null ? '' : rec[h])}</td>`;
        }).join('');
        return `<tr class="${isHl ? 'hl-row' : ''}" data-api-row="${rNum}"><td class="mono" style="color:var(--gpt-ink-muted)">${rNum}</td>${tds}</tr>`;
      }).join('');

      return `
        <div class="api-res-pills">${pills}</div>
        <div class="api-res-meta">
          <div><strong>${esc(cur.api)}</strong>（${esc(cur.title)}） · 状态：${cur.ok ? '<span style="color:var(--gpt-emerald-ink)">成功</span>' : `<span style="color:var(--gpt-coral)">失败 ${esc(cur.error)}</span>`} · 耗时 <span class="mono">${cur.costMs}ms</span> · 共 ${(cur.records || []).length} 行</div>
          <div class="mono" style="font-size:11px">入参：${esc(JSON.stringify(cur.args || {}))}</div>
          ${cur.requestPreview ? `<details><summary style="cursor:pointer;color:var(--gpt-accent)">查看脱敏请求报文预览</summary><pre class="raw-pre" style="margin-top:4px">${esc(cur.requestPreview)}</pre></details>` : ''}
        </div>
        ${(cur.records || []).length
          ? `<table class="api-data-table"><thead><tr><th style="width:42px">#</th>${headers.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rowsHtml}</tbody></table>`
          : '<div style="padding:20px;text-align:center;color:var(--gpt-ink-muted);font-size:12px">接口返回 0 条记录</div>'}`;
    }

    if (evTab === 'doc') {
      if (!docLines.length) {
        return '<div style="padding:28px;text-align:center;color:var(--gpt-ink-muted);font-size:12px">上游未直接传入单据正文（若单据来自网关接口，请切至「接口返回」查看）</div>';
      }
      const sLine = (evHighlight && evHighlight.tab === 'doc' && evHighlight.line) ? Number(evHighlight.line) : null;
      const eLine = (evHighlight && evHighlight.tab === 'doc' && evHighlight.endLine) ? Number(evHighlight.endLine) : sLine;
      return `<div class="doc-lines">${docLines.map((ln, idx) => {
        const lno = Number(ln.line != null ? ln.line : (ln.no != null ? ln.no : idx + 1));
        const isHl = sLine !== null && lno >= sLine && lno <= (eLine || sLine);
        return `<div class="doc-line ${isHl ? 'hl-line' : ''}" data-doc-line="${lno}"><span class="doc-lno">L${String(lno).padStart(3, '0')}</span><span class="doc-ltxt">${esc(ln.text)}</span></div>`;
      }).join('')}</div>`;
    }

    // input & tool
    const hlKey = (evHighlight && evHighlight.tab === 'input' && evHighlight.key) ? evHighlight.key : null;
    const hlCall = (evHighlight && evHighlight.tab === 'input' && evHighlight.callId) ? evHighlight.callId : null;
    const inpRows = Object.entries(inputs).map(([k, v]) =>
      `<tr class="${hlKey === k ? 'hl-row' : ''}" data-inp-key="${esc(k)}"><td class="mono" style="font-weight:600;width:120px">${esc(k)}</td><td style="word-break:break-word">${esc(v || '—')}</td></tr>`
    ).join('');
    const toolRows = toolCalls.map((tc) =>
      `<tr class="${hlCall === tc.callId ? 'hl-row' : ''}" data-call-id="${esc(tc.callId)}">
        <td class="mono" style="width:62px">${esc(tc.callId)}</td>
        <td class="mono" style="width:120px;font-weight:600">${esc(tc.tool)}</td>
        <td style="font-size:11px;word-break:break-all"><div class="mono">${esc(fmtJsonVal(tc.args))}</div><div style="color:var(--gpt-ink-muted);margin-top:3px">→ ${esc(fmtJsonVal(tc.output))}</div></td>
      </tr>`
    ).join('');
    return `
      <div style="padding:10px 12px">
        <div style="font-weight:600;font-size:12px;margin-bottom:6px">工单入参</div>
        <table class="kv-table"><thead><tr><th>参数名</th><th>参数值</th></tr></thead><tbody>${inpRows || '<tr><td colspan="2" style="color:var(--gpt-ink-muted)">无入参</td></tr>'}</tbody></table>
        <div style="font-weight:600;font-size:12px;margin:14px 0 6px">平台工具调用记录（共 ${toolCalls.length} 次）</div>
        <table class="kv-table"><thead><tr><th>ID</th><th>工具</th><th>入参与返回</th></tr></thead><tbody>${toolRows || '<tr><td colspan="3" style="color:var(--gpt-ink-muted)">无工具调用</td></tr>'}</tbody></table>
      </div>`;
  }

  function renderDetailFieldsTab(run) {
    const allFields = run.fields || [];
    const filtered = allFields.filter((f) => {
      if (detailFieldFilter === 'found') return f.status === 'found';
      if (detailFieldFilter === 'not_found') return f.status !== 'found';
      if (detailFieldFilter === 'shown') return f.shown;
      return true;
    });
    if (!selectedFieldName && filtered.length) {
      const firstFound = filtered.find((f) => f.status === 'found') || filtered[0];
      selectedFieldName = firstFound.name;
      if (firstFound.evidenceTarget) {
        evHighlight = firstFound.evidenceTarget;
        evTab = firstFound.evidenceTarget.tab || ((run.apiResults || []).length ? 'api' : 'doc');
        if (evTab === 'api' && firstFound.evidenceTarget.resultId) activeApiResultId = firstFound.evidenceTarget.resultId;
      }
    }

    const fieldRowsHtml = filtered.map((f) => {
      const isAct = f.name === selectedFieldName;
      const stBadge = f.status === 'found'
        ? '<span class="status-badge badge-emerald">已找到</span>'
        : '<span class="status-badge badge-amber">未找到</span>';
      const roleTag = f.shown
        ? '<span class="status-badge badge-blue">报告展示</span>'
        : (f.visible ? '<span class="status-badge badge-muted">未触发分支</span>' : '<span class="status-badge badge-muted">控制字段</span>');
      const retryTag = f.retried ? '<span class="status-badge badge-amber">已重试</span>' : '';
      const failTag = f.validationFailed ? '<span class="status-badge badge-coral">校验降级</span>' : '';
      const dispVal = (f.displayValue != null && f.displayValue !== '') ? f.displayValue : fmtJsonVal(f.value);
      return `<tr class="field-row ${isAct ? 'is-active' : ''}" data-fname="${esc(f.name)}">
        <td style="width:130px">
          <div style="font-weight:600">${esc(f.name)}</div>
          <div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px">${roleTag}${retryTag}${failTag}</div>
          <div style="font-size:11px;color:var(--gpt-ink-muted);margin-top:2px">${esc(EV_TYPE_LABEL[f.evidenceType] || f.evidenceType)}</div>
        </td>
        <td style="width:74px">${stBadge}</td>
        <td style="max-width:220px;word-break:break-word;white-space:pre-wrap">${esc(dispVal || '—')}</td>
        <td style="font-size:11.5px;color:var(--gpt-ink-secondary);word-break:break-word">
          ${f.evidenceLabel ? `<div style="color:var(--gpt-accent);margin-bottom:3px">${esc(f.evidenceLabel)}</div>` : ''}
          <div>${esc(f.reasoning || '—')}</div>
        </td>
      </tr>`;
    }).join('');

    els.rdBody.innerHTML = `<div class="rd-split">
      <div class="rd-panel">
        <div class="rd-panel-head">
          <span class="rd-panel-title">字段核验结果（点击行联动定位右侧证据）</span>
          <div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap">
            ${(run.missingSummary && run.missingSummary.nonFoundCount) ? `<button type="button" class="mini-btn" id="rd-fields-to-missing">缺失摘要 (${run.missingSummary.nonFoundCount}) →</button>` : ''}
            <button type="button" class="mini-btn ${detailFieldFilter === 'all' ? 'active' : ''}" data-ff="all">全部 (${allFields.length})</button>
            <button type="button" class="mini-btn ${detailFieldFilter === 'found' ? 'active' : ''}" data-ff="found">已找到</button>
            <button type="button" class="mini-btn ${detailFieldFilter === 'not_found' ? 'active' : ''}" data-ff="not_found">未找到</button>
            <button type="button" class="mini-btn ${detailFieldFilter === 'shown' ? 'active' : ''}" data-ff="shown">仅展示</button>
          </div>
        </div>
        <div class="rd-panel-scroll">
          <table class="field-table">
            <thead><tr><th>字段</th><th>状态</th><th>核验值</th><th>证据与推理说明</th></tr></thead>
            <tbody>${fieldRowsHtml || '<tr><td colspan="4" style="text-align:center;padding:24px;color:var(--gpt-ink-muted)">无符合条件的字段</td></tr>'}</tbody>
          </table>
        </div>
      </div>

      <div class="rd-panel">
        <div class="rd-panel-head">
          <span class="rd-panel-title">证据溯源检查器</span>
          <div class="ev-subtabs">
            <button type="button" class="ev-subtab ${evTab === 'api' ? 'active' : ''}" data-evtab="api">接口返回 (${(run.apiResults || []).length})</button>
            <button type="button" class="ev-subtab ${evTab === 'doc' ? 'active' : ''}" data-evtab="doc">单据原文 (${(run.documentLines || []).length}行)</button>
            <button type="button" class="ev-subtab ${evTab === 'input' ? 'active' : ''}" data-evtab="input">入参与工具</button>
          </div>
        </div>
        <div class="rd-panel-scroll" id="ev-inspector-scroll">${renderEvidenceInspectorContent(run)}</div>
      </div>
    </div>`;

    const toMissBtn = els.rdBody.querySelector('#rd-fields-to-missing');
    if (toMissBtn) toMissBtn.addEventListener('click', () => { detailTab = 'missing'; renderDetailView(); });
    els.rdBody.querySelectorAll('[data-ff]').forEach((b) => {
      b.addEventListener('click', () => { detailFieldFilter = b.getAttribute('data-ff') || 'all'; renderDetailFieldsTab(run); });
    });
    els.rdBody.querySelectorAll('.field-row').forEach((tr) => {
      tr.addEventListener('click', () => {
        const fname = tr.getAttribute('data-fname') || '';
        jumpToFieldEvidence(fname);
      });
    });
    els.rdBody.querySelectorAll('[data-evtab]').forEach((b) => {
      b.addEventListener('click', () => { evTab = b.getAttribute('data-evtab') || 'api'; renderDetailFieldsTab(run); });
    });
    els.rdBody.querySelectorAll('[data-rid]').forEach((b) => {
      b.addEventListener('click', () => { activeApiResultId = b.getAttribute('data-rid') || ''; renderDetailFieldsTab(run); });
    });

    // 自动滚动到高亮证据行
    const scrollBox = els.rdBody.querySelector('#ev-inspector-scroll');
    const targetEl = scrollBox && scrollBox.querySelector('.hl-row, .hl-line');
    if (targetEl && targetEl.scrollIntoView) {
      targetEl.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }

  function renderDetailTimelineTab(run) {
    const u = run.usage || {};
    const skillsHtml = (run.skillsLoaded || []).length
      ? (run.skillsLoaded || []).map((s) => `<span class="rd-chip mono">${esc(s)}</span>`).join('')
      : '<span style="color:var(--gpt-ink-muted)">无</span>';
    const valRounds = run.validationRounds || [];
    const valHtml = valRounds.length ? `
      <div class="raw-round" style="border-color:var(--gpt-coral-border)">
        <div class="raw-round-head" style="background:var(--gpt-coral-bg);color:var(--gpt-coral)">
          <span>证据核验退回记录（共 ${valRounds.length} 次重试）</span>
        </div>
        <div style="padding:8px 12px;font-size:12px">
          <pre class="raw-pre">${esc(JSON.stringify(valRounds, null, 2))}</pre>
        </div>
      </div>` : '';

    els.rdBody.innerHTML = `<div class="rd-tl-wrap"><div class="rd-tl-inner">
      <div class="rd-kpi-strip">
        <div class="rd-kpi"><div class="rd-kpi-lbl">核查总耗时</div><div class="rd-kpi-val mono">${fmtDur(run.durationMs)}</div></div>
        <div class="rd-kpi"><div class="rd-kpi-lbl">推理轮次 / 请求数</div><div class="rd-kpi-val mono">${run.rounds || 0} 轮 / ${u.requests || 0} 次</div></div>
        <div class="rd-kpi"><div class="rd-kpi-lbl">工具调用 / 接口调用</div><div class="rd-kpi-val mono">${(run.toolCalls || []).length} / ${(run.apiResults || []).length}</div></div>
        <div class="rd-kpi"><div class="rd-kpi-lbl">Token 消耗（入 / 出）</div><div class="rd-kpi-val mono" style="font-size:13px">${(u.inputTokens || 0).toLocaleString()} / ${(u.outputTokens || 0).toLocaleString()}</div></div>
        <div class="rd-kpi"><div class="rd-kpi-lbl">证据校验重试</div><div class="rd-kpi-val mono">${valRounds.length} 次</div></div>
      </div>
      <div style="background:#fff;border:1px solid var(--gpt-border);border-radius:8px;padding:8px 12px;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap"><span style="font-size:12px;color:var(--gpt-ink-secondary);font-weight:600">已加载 Skill：</span>${skillsHtml}</div>
        <div style="display:flex;gap:6px">
          <button type="button" class="mini-btn" id="rd-tl-expand-all">全部展开工具详情</button>
          <button type="button" class="mini-btn" id="rd-tl-collapse-all">全部收起</button>
        </div>
      </div>
      ${valHtml}
      <div id="rd-tl-events" style="display:flex;flex-direction:column;gap:10px">${renderRawEventsHtml(run.rawEvents || [], (run.rawEvents || []).length, 'rd_' + run.runId)}</div>
    </div></div>`;

    const tlBox = els.rdBody.querySelector('#rd-tl-events');
    const repaintTl = () => {
      tlBox.innerHTML = renderRawEventsHtml(run.rawEvents || [], (run.rawEvents || []).length, 'rd_' + run.runId);
      bindRawTimelineEvents(tlBox, repaintTl);
    };
    bindRawTimelineEvents(tlBox, repaintTl);
    els.rdBody.querySelector('#rd-tl-expand-all').addEventListener('click', () => {
      (run.rawEvents || []).forEach((e, idx) => {
        if (e.type === 'tool') rawFoldState[`tool_rd_${run.runId}_${e.seq || idx}`] = true;
        if (e.type === 'model_text') rawFoldState[`txt_rd_${run.runId}_${e.seq || idx}`] = true;
      });
      repaintTl();
    });
    els.rdBody.querySelector('#rd-tl-collapse-all').addEventListener('click', () => {
      (run.rawEvents || []).forEach((e, idx) => {
        delete rawFoldState[`tool_rd_${run.runId}_${e.seq || idx}`];
        delete rawFoldState[`txt_rd_${run.runId}_${e.seq || idx}`];
      });
      repaintTl();
    });
  }

  function renderDetailInputsTab(run) {
    const entries = Object.entries(run.inputs || {});
    const rows = entries.map(([k, v]) =>
      `<tr><td class="mono" style="width:160px;font-weight:600">${esc(k)}</td><td style="word-break:break-word;white-space:pre-wrap">${esc(v || '—')}</td></tr>`
    ).join('');
    const docLines = run.documentLines || [];
    const tplDef = run.templateDef;
    const tplDefHtml = tplDef ? `
      <div class="rd-panel">
        <div class="rd-panel-head">
          <span class="rd-panel-title">模板定义快照（templateDef · #${esc(tplDef.id || run.templateId || '—')} ${esc(tplDef.name || '')}）</span>
          <button type="button" class="mini-btn" id="rd-copy-tpldef">复制 templateDef JSON</button>
        </div>
        <div style="padding:10px 12px;display:flex;flex-direction:column;gap:8px;font-size:12px">
          ${tplDef.description ? `<div style="color:var(--gpt-ink-secondary)">${esc(tplDef.description)}</div>` : ''}
          <div><strong>绑定 Skill：</strong>${(tplDef.skills || []).map((s) => `<span class="rd-chip mono">${esc(s)}</span>`).join(' ') || '无'}</div>
          <div><strong>声明入参：</strong>${(tplDef.inputs || []).length} 项 · <strong>定义字段：</strong>${(tplDef.fields || []).length} 项</div>
          <details>
            <summary style="cursor:pointer;color:var(--gpt-accent);font-weight:500">展开完整 templateDef JSON</summary>
            <pre class="raw-pre" style="margin-top:6px;max-height:320px">${esc(JSON.stringify(tplDef, null, 2))}</pre>
          </details>
        </div>
      </div>` : '';

    els.rdBody.innerHTML = `<div class="rd-inp-wrap"><div class="rd-inp-inner">
      <div class="rd-panel">
        <div class="rd-panel-head">
          <span class="rd-panel-title">结构化工单入参（${entries.length} 项）</span>
          <button type="button" class="mini-btn" id="rd-copy-inp">复制入参 JSON</button>
        </div>
        <div style="padding:4px 0">
          <table class="kv-table"><thead><tr><th>参数名</th><th>参数值</th></tr></thead><tbody>${rows || '<tr><td colspan="2" style="color:var(--gpt-ink-muted);text-align:center">无入参</td></tr>'}</tbody></table>
        </div>
      </div>
      <div class="rd-panel">
        <div class="rd-panel-head">
          <span class="rd-panel-title">上游传入单据原文（${run.documentChars || 0} 字 · ${docLines.length} 行）</span>
          ${run.document ? '<button type="button" class="mini-btn" id="rd-copy-doc">复制单据全文</button>' : ''}
        </div>
        ${docLines.length
          ? `<div class="doc-lines">${docLines.map((ln, idx) => {
              const lno = Number(ln.line != null ? ln.line : (ln.no != null ? ln.no : idx + 1));
              return `<div class="doc-line"><span class="doc-lno">L${String(lno).padStart(3, '0')}</span><span class="doc-ltxt">${esc(ln.text)}</span></div>`;
            }).join('')}</div>`
          : '<div style="padding:24px;text-align:center;color:var(--gpt-ink-muted);font-size:12px">上游未传入单据正文（若运行期间通过接口拉取了单据，请在「字段结果与证据 → 接口返回」查看）</div>'}
      </div>
      ${tplDefHtml}
    </div></div>`;
    els.rdBody.querySelector('#rd-copy-inp').addEventListener('click', () => copyText(JSON.stringify(run.inputs || {}, null, 2), '已复制入参 JSON'));
    const copyDocBtn = els.rdBody.querySelector('#rd-copy-doc');
    if (copyDocBtn) copyDocBtn.addEventListener('click', () => copyText(run.document || '', '已复制单据全文'));
    const copyTplBtn = els.rdBody.querySelector('#rd-copy-tpldef');
    if (copyTplBtn) copyTplBtn.addEventListener('click', () => copyText(JSON.stringify(tplDef, null, 2), '已复制 templateDef JSON'));
  }

  function renderDetailView() {
    const run = runs[activeIdx];
    if (!run) return;
    if (detailTab === 'missing' && !(run.missingSummary && run.missingSummary.nonFoundCount)) {
      detailTab = 'report';
    }
    renderDetailHead(run);
    if (detailTab === 'report') renderDetailReportTab(run);
    else if (detailTab === 'fields') renderDetailFieldsTab(run);
    else if (detailTab === 'missing') renderDetailMissingTab(run);
    else if (detailTab === 'timeline') renderDetailTimelineTab(run);
    else renderDetailInputsTab(run);
  }

  /* ==================== 视图 A：Chat 模拟运行状态机 ==================== */
  async function sleepStep(ms, gen, instant) {
    if (instant || speed === 0 || ms <= 0) return gen === playGen;
    let remaining = Math.round(ms / speed);
    const slice = 40;
    while (remaining > 0) {
      if (gen !== playGen) return false;
      if (paused || activeView !== 'chat') {
        await new Promise((r) => setTimeout(r, 80));
        continue;
      }
      const curSpeed = speed;
      if (curSpeed === 0) return gen === playGen;
      const step = Math.min(slice, remaining);
      await new Promise((r) => setTimeout(r, step));
      remaining -= step;
    }
    return gen === playGen;
  }

  function openModal(titleHtml, bodyHtml, copyPayload) {
    els.modalTitle.innerHTML = titleHtml;
    els.modalBody.innerHTML = bodyHtml;
    modalCopyPayload = copyPayload || '';
    els.modalCopy.style.display = modalCopyPayload ? '' : 'none';
    els.modalMask.classList.add('open');
  }
  function closeModal() { els.modalMask.classList.remove('open'); }

  function openInputsModal(run) {
    const entries = Object.entries(run.inputs || {});
    const table = entries.length
      ? `<table class="kv-table"><thead><tr><th style="width:140px">参数名</th><th>参数值</th></tr></thead><tbody>` +
        entries.map(([k, v]) => `<tr><td class="mono" style="font-weight:600">${esc(k)}</td><td style="word-break:break-word">${esc(v || '—')}</td></tr>`).join('') +
        `</tbody></table>`
      : '<div style="color:var(--gpt-ink-muted);padding:10px 0">本次运行未传入结构化入参。</div>';
    const docHtml = run.document
      ? `<div style="margin-top:12px;border:1px solid var(--gpt-border);border-radius:8px;overflow:hidden"><div style="padding:7px 11px;background:var(--gpt-bg-subtle);font-size:12px;font-weight:600">申告单据原文（${run.documentChars || run.document.length} 字）</div><pre class="raw-pre" style="border:none;border-radius:0;max-height:260px">${esc(run.document)}</pre></div>`
      : '';
    openModal(`工单入参与单据原文 <span class="mono" style="font-size:11.5px;color:var(--gpt-ink-muted)">${esc(run.runId)}</span>`, table + docHtml, JSON.stringify(run.inputs || {}, null, 2));
  }

  function openReportPreviewModal(run) {
    openModal(
      `完整报告正文 <span class="mono" style="font-size:12px;color:var(--gpt-accent)">#${esc(run.templateId || '—')} ${esc(run.templateName)}</span>`,
      `<div class="rmc-body" style="padding:4px 2px">${renderMarkdown(run.report)}</div>`,
      run.report || '',
    );
  }

  async function selectRun(idx, instantOverride) {
    if (!runs.length) {
      els.chatStream.innerHTML = '<div style="text-align:center;padding:60px 20px;color:var(--gpt-ink-muted)">导出包内暂无运行记录</div>';
      return;
    }
    activeIdx = Math.max(0, Math.min(idx, runs.length - 1));
    playGen += 1;
    const gen = playGen;
    paused = false;
    els.btnPause.textContent = '暂停';
    traceExpanded = true;
    reportRawMode = false;
    selectedFieldName = '';
    evHighlight = null;
    activeApiResultId = '';

    const run = runs[activeIdx];
    const instant = Boolean(instantOverride);

    renderSidebar();
    const inpEntries = Object.entries(run.inputs || {}).filter(([, v]) => String(v || '').trim());
    els.inputsCount.textContent = String(inpEntries.length);
    els.btnPrev.disabled = activeIdx <= 0;
    els.btnNext.disabled = activeIdx >= runs.length - 1;
    if (activeView === 'detail') renderDetailView();

    els.dockProgress.style.width = '4%';
    els.dockStatus.textContent = '正在加载工单上下文…';
    els.chatStream.innerHTML = '';

    const biz = run.inputs['业务名称'] || run.templateName || '申告工单';
    const kvTags = [];
    if (run.inputs['手机号码']) kvTags.push(`号码 ${run.inputs['手机号码']}`);
    if (run.inputs['业务月份']) kvTags.push(`业务日期 ${run.inputs['业务月份']}`);
    if (run.inputs['创建时间']) kvTags.push(`建单 ${run.inputs['创建时间']}`);
    kvTags.push(run.routing ? '自动匹配模板' : `指定模板 #${run.templateId || '—'}`);

    const userRow = document.createElement('div');
    userRow.className = 'msg-row is-user';
    userRow.innerHTML = `<div class="user-bubble">
      <div class="user-bubble-title">请核查并填写「${esc(biz)}」的申告报告</div>
      <div class="user-kv-tags">${kvTags.map((t) => `<span class="user-kv-tag mono">${esc(t)}</span>`).join('')}</div>
      ${run.inputs['申诉内容'] ? `<div class="user-appeal"><strong>客户申诉：</strong>${esc(run.inputs['申诉内容'])}</div>` : ''}
    </div>`;
    els.chatStream.appendChild(userRow);
    els.chatScroll.scrollTop = els.chatScroll.scrollHeight;

    if (!(await sleepStep(360, gen, instant))) return;

    const aiRow = document.createElement('div');
    aiRow.className = 'msg-row';
    aiRow.innerHTML = `<div class="msg-avatar">${iconSvg('spark')}</div><div class="msg-body" id="ai-body"></div>`;
    els.chatStream.appendChild(aiRow);
    const aiBody = aiRow.querySelector('#ai-body');

    if (run.routing) {
      els.dockStatus.textContent = '正在通过 template-router 自动匹配最优模板…';
      els.dockProgress.style.width = '14%';
      const routeEl = document.createElement('div');
      routeEl.className = 'route-card';
      routeEl.innerHTML = `<div class="route-head">
        <span class="route-pill">自动路由命中</span>
        <strong class="mono">#${esc(run.routing.templateId || run.templateId)}</strong>
        <strong>${esc(run.routing.templateName || run.templateName)}</strong>
        <span class="route-conf">置信度 ${esc(run.routing.confidence || '高')}</span>
        ${run.routing.durationMs ? `<span class="mono" style="font-size:11px;color:var(--gpt-ink-muted)">${fmtDur(run.routing.durationMs)}</span>` : ''}
      </div>${run.routing.reason ? `<div class="route-reason">${esc(run.routing.reason)}</div>` : ''}`;
      aiBody.appendChild(routeEl);
      els.chatScroll.scrollTop = els.chatScroll.scrollHeight;
      if (!(await sleepStep(500, gen, instant))) return;
    }

    const steps = run.steps || [];
    const rawEvents = run.rawEvents || [];
    const tb = document.createElement('div');
    tb.className = 'thinking-bar st-running is-expanded';
    tb.innerHTML = `
      <div class="thinking-bar-head" id="tb-head">
        <div class="tb-left">
          <span id="tb-lead-ic">${iconSvg('spinner')}</span>
          <span id="tb-summary" class="tb-summary">正在核查…</span>
          <span class="tb-sep">·</span>
          <span class="tb-tpl"><span class="mono">#${esc(run.templateId || '—')}</span><span>${esc(run.templateName)}</span></span>
          <span class="tb-sep">·</span>
          <span id="tb-timer" class="tb-meta mono">0.0s</span>
          <span class="tb-sep">·</span>
          <span id="tb-ratio" class="tb-meta">核出 0/${run.totalCount || 0}</span>
        </div>
        <div class="tb-right">
          <button type="button" class="runid-chip mono" id="tb-copy-id" title="复制运行编号">${esc(run.runId)}</button>
          <span id="tb-fold" style="font-size:11.5px;color:var(--gpt-ink-muted)">收起 ▴</span>
        </div>
      </div>
      <div class="thinking-bar-body" id="tb-body">
        <div class="trace-toolbar">
          <span id="trace-caption" class="trace-caption">正在执行业务核查与平台强证据核验…</span>
          <div style="display:flex;align-items:center;gap:6px">
            <button type="button" class="mini-btn" id="tb-open-fields">字段证据溯源 →</button>
            <div class="trace-seg">
              <button type="button" class="seg-btn ${traceMode === 'steps' ? 'active' : ''}" data-mode="steps">精简步骤</button>
              <button type="button" class="seg-btn ${traceMode === 'raw' ? 'active' : ''}" data-mode="raw">原样运行记录</button>
            </div>
          </div>
        </div>
        <div id="steps-pane" class="steps-list" style="display:${traceMode === 'steps' ? 'flex' : 'none'}"></div>
        <div id="raw-pane" class="raw-list" style="display:${traceMode === 'raw' ? 'flex' : 'none'}"></div>
      </div>`;
    aiBody.appendChild(tb);

    const tbHead = tb.querySelector('#tb-head');
    const tbBody = tb.querySelector('#tb-body');
    const tbFold = tb.querySelector('#tb-fold');
    const tbLeadIc = tb.querySelector('#tb-lead-ic');
    const tbSummary = tb.querySelector('#tb-summary');
    const tbTimer = tb.querySelector('#tb-timer');
    const tbRatio = tb.querySelector('#tb-ratio');
    const traceCaption = tb.querySelector('#trace-caption');
    const stepsPane = tb.querySelector('#steps-pane');
    const rawPane = tb.querySelector('#raw-pane');
    let shownRawCount = 0;

    function paintChatRaw() {
      rawPane.innerHTML = renderRawEventsHtml(rawEvents, shownRawCount || rawEvents.length, 'chat_' + run.runId);
      bindRawTimelineEvents(rawPane, paintChatRaw);
    }

    function syncTraceView() {
      tbBody.style.display = traceExpanded ? '' : 'none';
      tb.classList.toggle('is-expanded', traceExpanded);
      tbFold.textContent = traceExpanded ? '收起 ▴' : '展开 ▾';
      stepsPane.style.display = traceMode === 'steps' ? 'flex' : 'none';
      rawPane.style.display = traceMode === 'raw' ? 'flex' : 'none';
      tb.querySelectorAll('.seg-btn').forEach((b) => b.classList.toggle('active', b.getAttribute('data-mode') === traceMode));
      if (traceMode === 'raw') paintChatRaw();
    }

    tbHead.addEventListener('click', () => { traceExpanded = !traceExpanded; syncTraceView(); });
    tb.querySelector('#tb-copy-id').addEventListener('click', (e) => { e.stopPropagation(); copyText(run.runId, '已复制运行编号'); });
    tb.querySelector('#tb-open-fields').addEventListener('click', (e) => { e.stopPropagation(); switchView('detail', 'fields'); });
    tb.querySelectorAll('.seg-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => { e.stopPropagation(); traceMode = btn.getAttribute('data-mode') || 'steps'; syncTraceView(); });
    });

    let prevAt = 0;
    for (let i = 0; i < steps.length; i += 1) {
      const st = steps[i];
      const delta = Math.max(0, (st.atMs || 0) - prevAt);
      prevAt = st.atMs || prevAt;
      const delay = i === 0 ? 220 : Math.min(820, Math.max(200, Math.round(delta * 0.14)));
      if (!(await sleepStep(delay, gen, instant))) return;

      const rowEl = document.createElement('div');
      rowEl.className = 'step-row';
      rowEl.innerHTML = `
        <span class="step-ic ic-${esc(st.icon || 'tool')}">${iconSvg(st.icon || 'tool')}</span>
        <span class="step-txt ${st.ok === false ? 'is-fail' : ''}">${esc(st.text)}</span>
        <span class="step-at mono">+${fmtDur(st.atMs)}</span>`;
      stepsPane.appendChild(rowEl);
      stepsPane.scrollTop = stepsPane.scrollHeight;

      shownRawCount = Math.min(rawEvents.length, Math.ceil(((i + 1) / Math.max(1, steps.length)) * rawEvents.length));
      if (traceMode === 'raw') { paintChatRaw(); rawPane.scrollTop = rawPane.scrollHeight; }

      tbSummary.textContent = `正在核查 · ${st.text}`;
      tbTimer.textContent = fmtDur(st.atMs);
      traceCaption.textContent = `已执行 ${i + 1}/${steps.length} 步业务核查与证据校验`;
      els.dockProgress.style.width = (18 + Math.round(((i + 1) / Math.max(1, steps.length)) * 58)) + '%';
      els.dockStatus.textContent = `模拟运行中 (${i + 1}/${steps.length}) · ${st.text}`;
      els.chatScroll.scrollTop = els.chatScroll.scrollHeight;
    }

    shownRawCount = rawEvents.length;
    tb.classList.remove('st-running');
    const stLower = String(run.status || 'FAILED').toLowerCase();
    tbLeadIc.innerHTML = `<span class="dot dot-${esc(stLower)}"></span>`;
    tbSummary.textContent = run.status === 'SUCCESS' ? '已完成核查与证据校验' : (run.status === 'PARTIAL' ? '已完成核查（部分字段待人工补齐）' : '核查失败');
    tbTimer.textContent = fmtDur(run.durationMs);
    tbRatio.textContent = `核出 ${run.foundCount}/${run.totalCount}`;
    traceCaption.textContent = `共 ${steps.length} 步 · ${run.rounds || 0} 轮推理 · 耗时 ${fmtDur(run.durationMs)}`;
    if (traceMode === 'raw') paintChatRaw();

    if (!(await sleepStep(300, gen, instant))) return;

    if (run.report) {
      const badgeHtml = run.status === 'SUCCESS'
        ? '<span class="status-badge badge-emerald">已核验</span>'
        : run.status === 'PARTIAL'
          ? `<span class="status-badge badge-amber">缺 ${run.missingShown.length || 1} 项</span>`
          : '<span class="status-badge badge-coral">异常</span>';

      const card = document.createElement('div');
      card.className = 'report-mini-card';
      card.innerHTML = `
        <div class="rmc-top" id="rmc-top">
          <div class="rmc-title-group">
            <span class="rmc-icon-badge">${iconSvg('doc')}</span>
            <span class="rmc-id mono">#${esc(run.templateId || '—')}</span>
            <span class="rmc-title">${esc(run.templateName)}</span>
            ${badgeHtml}
          </div>
          <div class="rmc-tools">
            <button type="button" class="mini-btn" id="btn-rmc-ev">字段与证据</button>
            <button type="button" class="mini-btn" id="btn-rmc-mode">Markdown 原文</button>
            <button type="button" class="mini-btn" id="btn-rmc-copy">复制报告</button>
            <button type="button" class="mini-btn" id="btn-rmc-full">全屏阅读</button>
          </div>
        </div>
        <div class="rmc-body" id="rmc-body"></div>
        <div class="rmc-foot">
          <span>版本 <strong class="mono">${esc(run.rev)}</strong>${run.model ? ` · 模型 <span class="mono">${esc(run.model)}</span>` : ''} · 入口 ${esc(run.entry)}</span>
          <span class="mono">${run.report.replace(/\s+/g, '').length} 字 · ${run.startTime}</span>
        </div>`;
      aiBody.appendChild(card);

      const rmcBody = card.querySelector('#rmc-body');
      const btnMode = card.querySelector('#btn-rmc-mode');
      function paintFullReport() {
        rmcBody.classList.toggle('is-raw', reportRawMode);
        rmcBody.innerHTML = reportRawMode ? esc(run.report) : renderMarkdown(run.report);
        btnMode.textContent = reportRawMode ? '渲染视图' : 'Markdown 原文';
      }
      card.querySelector('#btn-rmc-ev').addEventListener('click', (e) => { e.stopPropagation(); switchView('detail', 'fields'); });
      btnMode.addEventListener('click', (e) => { e.stopPropagation(); reportRawMode = !reportRawMode; paintFullReport(); });
      card.querySelector('#btn-rmc-copy').addEventListener('click', (e) => { e.stopPropagation(); copyText(run.report, '已复制报告 Markdown'); });
      card.querySelector('#btn-rmc-full').addEventListener('click', (e) => { e.stopPropagation(); openReportPreviewModal(run); });
      card.querySelector('#rmc-top').addEventListener('click', () => openReportPreviewModal(run));

      if (instant || speed === 0) {
        paintFullReport();
      } else {
        els.dockStatus.textContent = '正在渲染最终申告报告…';
        const fullText = run.report;
        const chunks = Math.min(28, Math.max(8, Math.ceil(fullText.length / 65)));
        const stepSize = Math.ceil(fullText.length / chunks);
        for (let pos = stepSize; pos < fullText.length; pos += stepSize) {
          if (!(await sleepStep(70, gen, instant))) return;
          rmcBody.innerHTML = renderMarkdown(fullText.slice(0, pos)) + '<span class="cursor-blink"></span>';
          els.dockProgress.style.width = (76 + Math.round((pos / fullText.length) * 22)) + '%';
          els.chatScroll.scrollTop = els.chatScroll.scrollHeight;
        }
        paintFullReport();
      }
    } else if (run.error) {
      const errBox = document.createElement('div');
      errBox.className = 'rd-alert err';
      errBox.textContent = '运行失败：' + run.error;
      aiBody.appendChild(errBox);
    }

    els.dockProgress.style.width = '100%';
    els.dockStatus.innerHTML = `<span class="dot dot-${esc(stLower)}"></span> 回放完成 · ${esc(STATUS_TEXT[run.status] || run.status)}（真实耗时 ${fmtDur(run.durationMs)}，共 ${run.rounds || 0} 轮）`;
    els.chatScroll.scrollTop = els.chatScroll.scrollHeight;
  }

  /* 全局事件绑定 */
  els.modeChat.addEventListener('click', () => switchView('chat'));
  els.modeDetail.addEventListener('click', () => switchView('detail'));
  els.btnGoDetail.addEventListener('click', () => switchView('detail', 'report'));
  els.btnHideSb.addEventListener('click', () => { els.sidebar.classList.add('is-hidden'); els.btnToggleSb.style.display = ''; });
  els.btnToggleSb.addEventListener('click', () => { els.sidebar.classList.remove('is-hidden'); els.btnToggleSb.style.display = 'none'; });
  els.sbSearch.addEventListener('input', () => { searchKw = els.sbSearch.value; renderSidebar(); });
  els.sbFilters.querySelectorAll('.sb-chip').forEach((btn) => {
    btn.addEventListener('click', () => {
      filterStatus = btn.getAttribute('data-st') || 'ALL';
      els.sbFilters.querySelectorAll('.sb-chip').forEach((b) => b.classList.toggle('active', b === btn));
      renderSidebar();
    });
  });
  document.querySelectorAll('.speed-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      speed = Number(btn.getAttribute('data-speed'));
      document.querySelectorAll('.speed-btn').forEach((b) => b.classList.toggle('active', b === btn));
      if (speed === 0) selectRun(activeIdx, true);
    });
  });
  els.btnPause.addEventListener('click', () => { paused = !paused; els.btnPause.textContent = paused ? '继续' : '暂停'; });
  els.btnReplay.addEventListener('click', () => selectRun(activeIdx, false));
  els.btnInstant.addEventListener('click', () => selectRun(activeIdx, true));
  els.btnInputs.addEventListener('click', () => runs[activeIdx] && openInputsModal(runs[activeIdx]));
  els.btnExportJson.addEventListener('click', () => {
    const r = runs[activeIdx];
    if (r) downloadJson(r, `run-${r.runId || 'detail'}.json`);
  });
  els.btnExportAllJson.addEventListener('click', () => {
    downloadJson(payload, `runs-export-${runs.length}条.json`);
  });
  els.btnPrev.addEventListener('click', () => activeIdx > 0 && selectRun(activeIdx - 1, false));
  els.btnNext.addEventListener('click', () => activeIdx < runs.length - 1 && selectRun(activeIdx + 1, false));
  els.modalClose.addEventListener('click', closeModal);
  els.modalMask.addEventListener('click', (e) => { if (e.target === els.modalMask) closeModal(); });
  els.modalCopy.addEventListener('click', () => modalCopyPayload && copyText(modalCopyPayload));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

  renderSidebar();
  selectRun(0, false);
})();
</script>
</body>
</html>
"""
