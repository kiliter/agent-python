"""运行记录「非找到字段」确定性归因摘要与按需 AI 总结。

#Created By AiCoding(codex)
设计原则：
  1. 零业务硬编码：所有归因规则仅依赖通用字段状态（shown/visible/whenMissing/validationFailed/reasoning）、
     当次运行的接口调用结果（apiResults）与校验退回记录（validationRounds），不写死任何业务或接口名。
  2. 确定性即时可见：detail_view 与离线导出 HTML 实时计算聚类摘要，历史记录无需迁移即可直接展示。
  3. 按需 AI 总结与缓存：用户主动触发时调用当前模型提炼自然语言摘要并写回 <runId>.json，避免拖慢主运行链路。
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic_ai import Agent

from ..store.fsutil import fmt_time, now_iso

# ============================================================================ 归因分类定义
_CATEGORY_META: dict[str, dict[str, Any]] = {
    "api_error": {
        "label": "外部接口调用失败",
        "severity": "danger",
        "order": 1,
    },
    "validation_failed": {
        "label": "证据校验未通过降级",
        "severity": "danger",
        "order": 2,
    },
    "api_no_data": {
        "label": "接口未查到相关记录",
        "severity": "warning",
        "order": 3,
    },
    "not_in_source": {
        "label": "原文或记录中无该信息",
        "severity": "info",
        "order": 4,
    },
    "dependency_missing": {
        "label": "依赖前置字段缺失",
        "severity": "warning",
        "order": 5,
    },
    "other": {
        "label": "其他未找到原因",
        "severity": "info",
        "order": 6,
    },
    "condition_skipped": {
        "label": "条件分支未命中已跳过",
        "severity": "muted",
        "order": 7,
    },
}

_CONDITION_SKIP_RE = re.compile(
    r"(展示条件不满足|不满足[^。；\n]{0,30}展示条件|条件不满足[^。；\n]{0,16}跳过|条件分支未命中|无需展示)"
)
_API_ERROR_RE = re.compile(
    r"(ok\s*=\s*false|返回码|调用失败|接口[^。；\n]{0,24}(失败|报错|异常|超时)|连接超时|响应超时|网关[^。；\n]{0,16}(失败|错误|异常))"
)
_API_NO_DATA_RE = re.compile(
    r"(count\s*=\s*0|无记录|未查到|没有查到|未匹配到|无数据|返回\s*0\s*条|0\s*条记录|没有属于本次业务的单据)"
)
_DEPENDENCY_RE = re.compile(
    r"(为\s*not_found|未能确定|未取得|缺失|没有可回退来源|前置字段|依赖字段)"
)
_NOT_IN_SOURCE_RE = re.compile(
    r"(未记载|不含|不包含|未提及|未出现|未找到|无匹配|不满足[^。；\n]{0,20}规则|按[^。；\n]{0,12}规则不得|不得[^。；\n]{0,16}(代替|猜测|作为)|无法提取|没有具体)"
)


def _clip(text: str, limit: int = 130) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip())
    if len(s) <= limit:
        return s
    return s[:limit].rstrip("，,、；; ") + "…"


def _is_found(field: dict[str, Any]) -> bool:
    return (field.get("status") or field.get("runStatus") or "not_found") == "found"


def _normalize_when_missing(raw: Any) -> str:
    val = str(raw or "placeholder").strip()
    mapping = {"保留占位": "placeholder", "置空": "empty", "默认值": "value"}
    return mapping.get(val, val or "placeholder")


def _extract_api_signals(api_results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从当次运行 apiResults 提取失败接口与空结果接口清单（按接口名+错误去重）。"""
    failed_map: dict[tuple[str, str], dict[str, Any]] = {}
    empty_map: dict[str, dict[str, Any]] = {}

    for item in api_results:
        if not isinstance(item, dict):
            continue
        api_name = str(item.get("api") or "").strip()
        title = str(item.get("title") or api_name).strip()
        rid = str(item.get("resultId") or "").strip()
        if not api_name:
            continue
        if not bool(item.get("ok", True)):
            err = _clip(str(item.get("error") or "接口返回失败"), 120)
            key = (api_name, err)
            if key not in failed_map:
                failed_map[key] = {
                    "api": api_name,
                    "title": title,
                    "error": err,
                    "resultIds": [rid] if rid else [],
                    "count": 1,
                }
            else:
                failed_map[key]["count"] += 1
                if rid and rid not in failed_map[key]["resultIds"]:
                    failed_map[key]["resultIds"].append(rid)
        else:
            records = item.get("records") if isinstance(item.get("records"), list) else []
            if bool(item.get("noData")) or len(records) == 0:
                if api_name not in empty_map:
                    empty_map[api_name] = {
                        "api": api_name,
                        "title": title,
                        "resultIds": [rid] if rid else [],
                        "count": 1,
                    }
                else:
                    empty_map[api_name]["count"] += 1
                    if rid and rid not in empty_map[api_name]["resultIds"]:
                        empty_map[api_name]["resultIds"].append(rid)

    return list(failed_map.values()), list(empty_map.values())


def _extract_validation_issues(validation_rounds: list[Any]) -> dict[str, str]:
    """提取每个字段在校验退回轮次中最后一次的具体退回原因。"""
    latest: dict[str, str] = {}
    for rnd in validation_rounds:
        if not isinstance(rnd, list):
            continue
        for item in rnd:
            if not isinstance(item, dict):
                continue
            fname = str(item.get("field") or "").strip()
            msg = str(item.get("message") or "").strip()
            if fname and msg:
                latest[fname] = msg
    return latest


def _mentions_any_api(text: str, apis: list[dict[str, Any]]) -> list[str]:
    """返回推理文本中显式提到的接口名列表。"""
    if not text or not apis:
        return []
    low = text.lower()
    matched: list[str] = []
    for a in apis:
        api_name = a["api"]
        title = a["title"]
        rids = a.get("resultIds") or []
        hit = api_name.lower() in low or (title and title in text) or any(rid and rid in text for rid in rids)
        if hit and api_name not in matched:
            matched.append(api_name)
    return matched


def _classify_field(
    field: dict[str, Any],
    *,
    failed_apis: list[dict[str, Any]],
    empty_apis: list[dict[str, Any]],
    val_issues: dict[str, str],
    other_missing_names: set[str],
) -> tuple[str, list[str], str]:
    """将单个非找到字段归入确定性原因分类，返回 (category, related_apis, brief_reason)。"""
    name = str(field.get("name") or "")
    visible = bool(field.get("visible", True))
    shown = bool(field.get("shown", False))
    val_failed = bool(field.get("validationFailed", False))
    reasoning = str(field.get("reasoning") or "").strip()

    # 1. 条件分支未命中跳过（不展示在报告中，也不属于校验失败）
    if visible and not shown and not val_failed:
        brief = _clip(reasoning) if reasoning else "模板展示条件未命中，该字段未出现在报告中。"
        return "condition_skipped", [], brief
    if not shown and not val_failed and reasoning and _CONDITION_SKIP_RE.search(reasoning):
        return "condition_skipped", [], _clip(reasoning)

    # 2. 证据校验未通过降级
    if val_failed:
        vmsg = val_issues.get(name, "")
        if vmsg and reasoning and vmsg not in reasoning:
            brief = _clip(f"校验退回：{vmsg}；{reasoning}", 150)
        elif vmsg:
            brief = _clip(f"证据校验未通过：{vmsg}", 150)
        else:
            brief = _clip(reasoning or "重试耗尽后仍未通过平台证据校验，已自动降级为未找到。", 150)
        return "validation_failed", [], brief

    # 3. 外部接口调用失败（优先于空结果，捕获真实阻塞根因）
    if failed_apis:
        hit_failed = _mentions_any_api(reasoning, failed_apis)
        if hit_failed or (reasoning and _API_ERROR_RE.search(reasoning)):
            apis = hit_failed or [a["api"] for a in failed_apis]
            brief = _clip(reasoning) if reasoning else f"接口 {', '.join(apis)} 调用失败，无法取得数据。"
            return "api_error", apis, brief

    # 4. 外部接口调用成功但返回 0 条记录
    if empty_apis:
        hit_empty = _mentions_any_api(reasoning, empty_apis)
        if hit_empty or (reasoning and _API_NO_DATA_RE.search(reasoning)):
            apis = hit_empty or [a["api"] for a in empty_apis]
            brief = _clip(reasoning) if reasoning else f"接口 {', '.join(apis)} 未查到符合条件的记录。"
            return "api_no_data", apis, brief

    # 5. 依赖其他未找到字段（例如前置控制字段/上游字段缺失）
    if reasoning and _DEPENDENCY_RE.search(reasoning):
        dep_hits = [n for n in other_missing_names if n != name and n in reasoning]
        if dep_hits:
            return "dependency_missing", [], _clip(reasoning)

    # 6. 原文/记录中无该信息（已查到单据或接口数据，但未记载或规则未命中）
    if reasoning and _NOT_IN_SOURCE_RE.search(reasoning):
        return "not_in_source", [], _clip(reasoning)

    # 7. 兜底
    if not reasoning:
        return "other", [], "模型未填写具体未找到说明。"
    return "other", [], _clip(reasoning)


def _normalize_ai_summary(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    return {
        "text": text,
        "generatedAt": fmt_time(str(raw.get("generatedAt") or "")),
        "generatedAtIso": str(raw.get("generatedAt") or ""),
        "model": str(raw.get("model") or ""),
        "operator": str(raw.get("operator") or ""),
    }


def _build_group_summary(
    code: str,
    fields: list[dict[str, Any]],
    *,
    failed_apis: list[dict[str, Any]],
    empty_apis: list[dict[str, Any]],
) -> str:
    n = len(fields)
    names_preview = "、".join(f["name"] for f in fields[:4]) + (" 等" if n > 4 else "")
    if code == "api_error":
        api_desc = "；".join(f"{a['api']}（{a['error']}）" for a in failed_apis[:2])
        return f"{n} 个字段（{names_preview}）受外部接口报错影响：{api_desc}" if api_desc else f"{n} 个字段受外部接口调用失败影响。"
    if code == "validation_failed":
        return f"{n} 个字段（{names_preview}）在证据核验重试后仍未通过，平台已自动降级为未找到。"
    if code == "api_no_data":
        api_desc = "、".join(f"{a['api']}（{a['title']}）" if a["title"] != a["api"] else a["api"] for a in empty_apis[:2])
        return f"{n} 个字段（{names_preview}）因查询接口 {api_desc} 返回 0 条记录而无可用依据。" if api_desc else f"{n} 个字段因接口未查到记录而缺失。"
    if code == "not_in_source":
        return f"{n} 个字段（{names_preview}）在已获取的单据或接口记录中未记载或未命中提取规则，按防幻觉规则未做猜测。"
    if code == "dependency_missing":
        return f"{n} 个字段（{names_preview}）依赖的前置字段缺失，无法继续推导或回退。"
    if code == "condition_skipped":
        return f"{n} 个字段（{names_preview}）因模板展示条件未命中而跳过，未出现在最终报告中，不影响成稿完整性。"
    return f"{n} 个字段（{names_preview}）未能找到有效证据。"


def _build_headline(
    *,
    non_found_count: int,
    shown_missing_count: int,
    default_fallback_count: int,
    skipped_count: int,
    groups: list[dict[str, Any]],
    failed_apis: list[dict[str, Any]],
    empty_apis: list[dict[str, Any]],
) -> str:
    if non_found_count == 0:
        return "全部字段均已找到，无缺失项。"
    if shown_missing_count == 0 and default_fallback_count == 0 and skipped_count == non_found_count:
        return f"报告需展示字段均已找到；另有 {skipped_count} 个字段因条件分支未命中已跳过，不影响最终成稿。"

    parts: list[str] = [f"共 {non_found_count} 个字段非找到状态"]
    impact_bits: list[str] = []
    if shown_missing_count > 0:
        impact_bits.append(f"{shown_missing_count} 项直接影响报告展示")
    if default_fallback_count > 0:
        impact_bits.append(f"{default_fallback_count} 项已走默认值兜底")
    if skipped_count > 0:
        impact_bits.append(f"{skipped_count} 项因条件未命中跳过")
    if impact_bits:
        parts.append("（" + "，".join(impact_bits) + "）")

    core_reasons: list[str] = []
    for g in groups:
        code = g["code"]
        if code == "condition_skipped":
            continue
        cnt = g["count"]
        if code == "api_error" and failed_apis:
            first_api = failed_apis[0]
            core_reasons.append(f"接口报错（{cnt} 项，{first_api['api']}）")
        elif code == "api_no_data" and empty_apis:
            first_empty = empty_apis[0]
            core_reasons.append(f"接口无记录（{cnt} 项，{first_empty['api']}）")
        else:
            core_reasons.append(f"{g['label']}（{cnt} 项）")

    if core_reasons:
        return "".join(parts) + "；主要原因：" + "、".join(core_reasons) + "。"
    return "".join(parts) + "。"


def _build_plain_text(summary: dict[str, Any]) -> str:
    lines: list[str] = [summary["headline"]]
    for rc in summary.get("rootCauses") or []:
        lines.append(f"- [{rc['title']}] {rc['detail']}")
    for g in summary.get("groups") or []:
        lines.append(f"\n【{g['label']}（{g['count']} 项）】{g['summary']}")
        for f in g.get("fields") or []:
            tag = "报告展示缺失" if f["shown"] and not f["hasDefaultFallback"] else (
                "默认值兜底" if f["hasDefaultFallback"] else ("中间控制字段" if not f["visible"] else "未展示")
            )
            lines.append(f"  · {f['name']}（{tag}）：{f['briefReason']}")
    ai = summary.get("aiSummary")
    if isinstance(ai, dict) and ai.get("text"):
        lines.append(f"\n【AI 总结（{ai.get('model') or 'LLM'}）】\n{ai['text']}")
    return "\n".join(lines).strip()


def build_missing_summary(run: dict[str, Any]) -> dict[str, Any]:
    """根据运行记录实时计算「非找到字段」确定性归因摘要（零额外模型调用）。#Created By AiCoding(codex)"""
    raw_fields = [f for f in (run.get("fields") or []) if isinstance(f, dict) and f.get("name")]
    api_results = [r for r in (run.get("apiResults") or []) if isinstance(r, dict)]
    validation_rounds = run.get("validationRounds") if isinstance(run.get("validationRounds"), list) else []

    total_fields = len(raw_fields)
    found_count = sum(1 for f in raw_fields if _is_found(f))
    non_found = [f for f in raw_fields if not _is_found(f)]
    ai_summary = _normalize_ai_summary(run.get("missingSummaryAi"))

    if not non_found:
        empty_res: dict[str, Any] = {
            "totalFields": total_fields,
            "foundCount": found_count,
            "nonFoundCount": 0,
            "impactedCount": 0,
            "shownMissingCount": 0,
            "defaultFallbackCount": 0,
            "skippedCount": 0,
            "headline": "全部字段均已找到，无缺失项。",
            "rootCauses": [],
            "groups": [],
            "aiSummary": ai_summary,
        }
        empty_res["plainText"] = _build_plain_text(empty_res)
        return empty_res

    failed_apis, empty_apis = _extract_api_signals(api_results)
    val_issues = _extract_validation_issues(validation_rounds)
    other_missing_names = {str(f["name"]) for f in non_found}

    grouped: dict[str, list[dict[str, Any]]] = {}
    shown_missing_count = 0
    default_fallback_count = 0
    skipped_count = 0
    api_error_fields: dict[str, list[str]] = {}
    api_empty_fields: dict[str, list[str]] = {}

    for f in non_found:
        fname = str(f["name"])
        visible = bool(f.get("visible", True))
        shown = bool(f.get("shown", False))
        when_missing = _normalize_when_missing(f.get("whenMissing"))
        has_default = when_missing == "value"
        val_failed = bool(f.get("validationFailed", False))
        retried = bool(f.get("retried", False))

        code, related_apis, brief = _classify_field(
            f,
            failed_apis=failed_apis,
            empty_apis=empty_apis,
            val_issues=val_issues,
            other_missing_names=other_missing_names,
        )

        if code == "condition_skipped":
            skipped_count += 1
        elif has_default:
            default_fallback_count += 1
        elif shown:
            shown_missing_count += 1

        if code == "api_error":
            for a in related_apis:
                api_error_fields.setdefault(a, []).append(fname)
        elif code == "api_no_data":
            for a in related_apis:
                api_empty_fields.setdefault(a, []).append(fname)

        grouped.setdefault(code, []).append({
            "name": fname,
            "visible": visible,
            "shown": shown,
            "whenMissing": when_missing,
            "hasDefaultFallback": has_default,
            "validationFailed": val_failed,
            "retried": retried,
            "category": code,
            "relatedApis": related_apis,
            "briefReason": brief,
            "reasoning": str(f.get("reasoning") or "").strip(),
            "evidenceLabel": str(f.get("evidenceLabel") or ""),
            "evidenceTarget": f.get("evidenceTarget") if isinstance(f.get("evidenceTarget"), dict) else {"tab": "doc"},
        })

    # 按严重程度排序分组；组内将「直接影响报告展示」的字段排在前面
    groups: list[dict[str, Any]] = []
    for code, flist in sorted(grouped.items(), key=lambda kv: _CATEGORY_META[kv[0]]["order"]):
        flist.sort(key=lambda item: (0 if (item["shown"] and not item["hasDefaultFallback"]) else 1, item["name"]))
        meta = _CATEGORY_META[code]
        groups.append({
            "code": code,
            "label": meta["label"],
            "severity": meta["severity"],
            "count": len(flist),
            "summary": _build_group_summary(code, flist, failed_apis=failed_apis, empty_apis=empty_apis),
            "fields": flist,
        })

    # 提炼高层根因标签（供顶部一眼扫清问题）
    root_causes: list[dict[str, Any]] = []
    for a in failed_apis:
        affected = api_error_fields.get(a["api"], [])
        times = f"（调用 {a['count']} 次均失败）" if a["count"] > 1 else ""
        root_causes.append({
            "code": "api_error",
            "severity": "danger",
            "title": f"接口报错 · {a['api']}",
            "detail": f"{a['error']}{times}",
            "affectedCount": len(affected),
            "affectedFields": affected,
        })
    for a in empty_apis:
        affected = api_empty_fields.get(a["api"], [])
        if affected or any(g["code"] in ("api_no_data", "api_error") for g in groups):
            root_causes.append({
                "code": "api_no_data",
                "severity": "warning",
                "title": f"接口无记录 · {a['api']}",
                "detail": f"「{a['title']}」调用成功但返回 0 条记录",
                "affectedCount": len(affected),
                "affectedFields": affected,
            })
    if "validation_failed" in grouped:
        vfields = [x["name"] for x in grouped["validation_failed"]]
        root_causes.append({
            "code": "validation_failed",
            "severity": "danger",
            "title": "证据校验未通过",
            "detail": f"{len(vfields)} 个字段未通过平台强证据校验被降级：{('、'.join(vfields[:4]))}",
            "affectedCount": len(vfields),
            "affectedFields": vfields,
        })
    if "not_in_source" in grouped:
        sfields = [x["name"] for x in grouped["not_in_source"]]
        root_causes.append({
            "code": "not_in_source",
            "severity": "info",
            "title": "原文无对应记载",
            "detail": f"{len(sfields)} 个字段在已有单据或记录中未找到对应内容：{('、'.join(sfields[:4]))}",
            "affectedCount": len(sfields),
            "affectedFields": sfields,
        })

    impacted_count = len(non_found) - skipped_count
    headline = _build_headline(
        non_found_count=len(non_found),
        shown_missing_count=shown_missing_count,
        default_fallback_count=default_fallback_count,
        skipped_count=skipped_count,
        groups=groups,
        failed_apis=failed_apis,
        empty_apis=empty_apis,
    )

    result: dict[str, Any] = {
        "totalFields": total_fields,
        "foundCount": found_count,
        "nonFoundCount": len(non_found),
        "impactedCount": impacted_count,
        "shownMissingCount": shown_missing_count,
        "defaultFallbackCount": default_fallback_count,
        "skippedCount": skipped_count,
        "headline": headline,
        "rootCauses": root_causes,
        "groups": groups,
        "aiSummary": ai_summary,
    }
    result["plainText"] = _build_plain_text(result)
    return result


# ============================================================================ 按需 AI 深度总结
_AI_SYSTEM_PROMPT = """你是报告核查平台的运行诊断助手。
请根据提供的单次运行事实，对所有「非找到状态」的填充字段做一份清晰、简明、完全忠于事实的中文情况摘要。

严格要求：
1. 只能依据提供的数据事实总结，严禁编造任何未出现的字段名、接口名、错误码、时间或业务结论。
2. 优先聚焦「报告需要展示但缺失」和「校验未通过」的字段，归纳共同根因（例如接口报错导致级联缺失、未查到单据、原文未记载等）；对「条件分支未命中已跳过」的字段只需一句带过，说明不影响成稿。
3. 控制在 260 字以内，使用简洁的三段式 Markdown：
   - **核心结论**：1~2 句话说明整体缺失情况与最主要原因。
   - **归因明细**：按根因合并列出受影响字段（每条一行，避免把每个字段的推理长文重复抄一遍）。
   - **建议处理**：1~2 条具体可执行的排查或补录建议。
"""


def _build_ai_prompt_payload(run: dict[str, Any], det_summary: dict[str, Any]) -> str:
    """组装脱敏、结构化的事实上下文，供大模型总结未找到原因。"""
    api_briefs = []
    for r in run.get("apiResults") or []:
        if not isinstance(r, dict):
            continue
        recs = r.get("records") if isinstance(r.get("records"), list) else []
        api_briefs.append({
            "resultId": r.get("resultId"),
            "api": r.get("api"),
            "title": r.get("title"),
            "ok": bool(r.get("ok", True)),
            "count": len(recs),
            "noData": bool(r.get("noData", False)),
            "error": _clip(str(r.get("error") or ""), 200) if r.get("error") else None,
        })

    non_found_fields = []
    for g in det_summary.get("groups") or []:
        for f in g.get("fields") or []:
            non_found_fields.append({
                "name": f["name"],
                "shown": f["shown"],
                "visible": f["visible"],
                "whenMissing": f["whenMissing"],
                "validationFailed": f["validationFailed"],
                "category": g["label"],
                "reasoning": _clip(f.get("reasoning") or f.get("briefReason") or "", 320),
            })

    payload = {
        "runId": run.get("runId"),
        "template": f"#{run.get('templateId')} {run.get('templateName') or ''}".strip(),
        "status": run.get("status"),
        "runError": _clip(str(run.get("error") or ""), 200) if run.get("error") else None,
        "hasInputDocument": bool(str(run.get("document") or "").strip()),
        "stats": {
            "totalFields": det_summary["totalFields"],
            "foundCount": det_summary["foundCount"],
            "nonFoundCount": det_summary["nonFoundCount"],
            "shownMissingCount": det_summary["shownMissingCount"],
            "defaultFallbackCount": det_summary["defaultFallbackCount"],
            "skippedCount": det_summary["skippedCount"],
        },
        "apiResults": api_briefs,
        "validationRounds": run.get("validationRounds") or [],
        "nonFoundFields": non_found_fields,
    }
    return "请根据以下单次运行事实，生成「非找到字段」原因摘要总结：\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)


async def generate_ai_missing_summary(
    run: dict[str, Any],
    *,
    model: Any,
    model_settings: dict[str, Any] | None,
    model_name: str,
    operator: str,
) -> dict[str, Any]:
    """调用当前大模型按需生成未找到字段摘要，返回可直接持久化至运行记录的字典。#Created By AiCoding(codex)"""
    det_summary = build_missing_summary(run)
    user_prompt = _build_ai_prompt_payload(run, det_summary)

    # 总结任务不需要工具、温度略低保证客观克制，限制 max_tokens 控速防冗长
    settings: dict[str, Any] = dict(model_settings or {})
    settings.pop("parallel_tool_calls", None)
    settings["temperature"] = min(float(settings.get("temperature", 0.2)), 0.2)
    cur_max = settings.get("max_tokens")
    settings["max_tokens"] = min(int(cur_max), 800) if cur_max else 800

    agent: Agent[None, str] = Agent(model, instructions=_AI_SYSTEM_PROMPT)
    res = await agent.run(user_prompt, model_settings=settings)
    text = str(res.output or "").strip()
    if not text:
        raise ValueError("大模型返回空的摘要内容")

    return {
        "text": text,
        "generatedAt": now_iso(),
        "model": str(model_name or ""),
        "operator": str(operator or ""),
    }
