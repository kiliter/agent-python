"""全平台批量回归测试存储与执行引擎（支持固定模板与未绑定模板自动路由、单版回归与双版对比）。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import re
import secrets
import threading
import time
from typing import Any, Literal

from ..domain.resources import ResourceSet
from ..store.cases import AUTO_CASE_SCOPE, CaseDef, CaseStore, parse_case_scope, scope_key
from ..store.fsutil import append_jsonl, now_iso, read_json, read_jsonl, write_json
from ..store.layout import REV_RE, SAFE_ID_RE, DataLayout, InvalidResource, ensure_within
from ..store.releases import ReleaseNotFound, ReleaseStore
from ..store.service import ResourceService
from .evidence import scalar_to_str
from .router import TemplateRouteError
from .runner import AgentRunner, InputValidationError, RunRequest, TemplateUnavailable

log = logging.getLogger(__name__)

RegressionMode = Literal["single", "compare"]
_WS_RE = re.compile(r"\s+")
_KEEP_BATCHES = 50


def new_batch_id() -> str:
    """生成短随机回归批次编号。"""
    return f"reg-{int(time.time())}-{secrets.token_hex(3)}"


def _norm_compare(val: str | None) -> str:
    """用于字段期望值/双版差异比对的空白归一化。"""
    return _WS_RE.sub(" ", (val or "").strip())


def _field_val_text(f: dict[str, Any]) -> str:
    """从运行结果字段字典中提取稳定可比对的字符串值。"""
    st = str(f.get("status") or "not_found")
    if st != "found":
        return ""
    raw = f.get("value")
    if isinstance(raw, list):
        return f"[{len(raw)} 行]" if raw else "[]"
    return scalar_to_str(raw).strip()


def _field_ev_text(f: dict[str, Any]) -> str:
    """汇总字段的证据出处与推理摘要，供差异对比抽屉展示。"""
    parts: list[str] = []
    ev_lbl = str(f.get("evidenceLabel") or "").strip()
    if ev_lbl:
        parts.append(f"来源：{ev_lbl}")
    else:
        evs = f.get("evidence") or []
        if isinstance(evs, list) and evs:
            brief = []
            for e in evs[:3]:
                if not isinstance(e, dict):
                    continue
                et = e.get("type")
                if et == "api":
                    brief.append(f"接口 {e.get('resultId')}[row={e.get('row')}].{e.get('column')}")
                elif et == "document":
                    brief.append(f"单据「{str(e.get('quote') or '')[:32]}」")
                elif et == "input":
                    brief.append(f"入参「{e.get('key')}」")
                elif et == "tool":
                    brief.append(f"工具 {e.get('callId')}")
                elif et == "field":
                    brief.append(f"字段「{e.get('name')}」")
            if brief:
                parts.append("来源：" + "；".join(brief))
    reason = str(f.get("reasoning") or "").strip()
    if reason:
        parts.append(f"说明：{reason}")
    return "\n".join(parts) or "—"


def _extract_fields(run_out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """提取运行结果中的全部字段（含控制字段与展示字段，按字段名映射）。"""
    out: dict[str, dict[str, Any]] = {}
    for f in run_out.get("fields") or []:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name") or "").strip()
        if not name:
            continue
        out[name] = f
    return out


class RegressionStore:
    """批量回归批次结果存储：DATA_DIR/regressions/index.jsonl + <batchId>.json。#Created By AiCoding(codex)"""

    def __init__(self, layout: DataLayout, lock: threading.RLock, keep: int = _KEEP_BATCHES) -> None:
        self.layout = layout
        self.lock = lock
        self.keep = max(5, int(keep))

    @property
    def _index_path(self):
        return self.layout.regressions / "index.jsonl"

    def _batch_path(self, batch_id: str):
        if not isinstance(batch_id, str) or not SAFE_ID_RE.match(batch_id):
            raise InvalidResource(f"非法的回归批次编号：{batch_id}")
        return ensure_within(self.layout.regressions, self.layout.regressions / f"{batch_id}.json")

    def save(self, batch: dict[str, Any]) -> None:
        batch_id = str(batch["batchId"])
        p = self._batch_path(batch_id)
        summary = {
            "batchId": batch_id,
            "mode": batch.get("mode"),
            "targetA": batch.get("targetA"),
            "targetALabel": batch.get("targetALabel"),
            "targetB": batch.get("targetB"),
            "targetBLabel": batch.get("targetBLabel"),
            "operator": batch.get("operator", ""),
            "startedAt": batch.get("startedAt", ""),
            "finishedAt": batch.get("finishedAt", ""),
            "durationMs": int(batch.get("durationMs") or 0),
            "totalCases": int(batch.get("totalCases") or 0),
            "executedCases": int(batch.get("executedCases") or 0),
            "passedCases": int(batch.get("passedCases") or 0),
            "diffCases": int(batch.get("diffCases") or 0),
            "routeMismatchCases": int(batch.get("routeMismatchCases") or 0),
            "failedCases": int(batch.get("failedCases") or 0),
            "passRate": batch.get("passRate", 0.0),
            "cancelled": bool(batch.get("cancelled", False)),
        }
        with self.lock:
            self.layout.regressions.mkdir(parents=True, exist_ok=True)
            write_json(p, batch)
            append_jsonl(self._index_path, summary)
            self._prune_old()

    def _prune_old(self) -> None:
        entries = read_jsonl(self._index_path)
        if len(entries) <= self.keep:
            return
        old = entries[: len(entries) - self.keep]
        for item in old:
            bid = str(item.get("batchId") or "")
            if bid and SAFE_ID_RE.match(bid):
                try:
                    bp = self._batch_path(bid)
                    if bp.is_file():
                        bp.unlink()
                except (InvalidResource, OSError):
                    pass

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.lock:
            entries = read_jsonl(self._index_path)
        entries.reverse()
        return entries[: max(1, min(limit, 200))]

    def get(self, batch_id: str) -> dict[str, Any] | None:
        p = self._batch_path(batch_id)
        if not p.is_file():
            return None
        try:
            data = read_json(p)
        except OSError:
            return None
        return data if isinstance(data, dict) else None


@dataclass
class RegressionCaseTarget:
    """单条待执行的回归用例定位键。"""

    scope: str  # "auto" 或正整数模板 ID 字符串
    case_id: str


@dataclass
class RegressionRunRequest:
    """批量回归执行请求。"""

    cases: list[RegressionCaseTarget] = field(default_factory=list)
    mode: RegressionMode = "single"
    target_a: str = "online"
    target_b: str | None = None
    operator: str = ""
    max_concurrency: int | None = None


class RegressionRunner:
    """批量回归编排器：解析快照 → 并发执行固定模板/自动路由用例 → 字段与路由比对 → 回写用例并落盘批次。#Created By AiCoding(codex)"""

    def __init__(
        self,
        runner: AgentRunner,
        cases: CaseStore,
        releases: ReleaseStore,
        service: ResourceService,
        store: RegressionStore,
    ) -> None:
        self.runner = runner
        self.cases = cases
        self.releases = releases
        self.service = service
        self.store = store

    def _resolve_snapshot(self, target: str) -> tuple[str, ResourceSet, str]:
        """将 target（online / draft / rN）解析为 (rev, ResourceSet, 可读标签)。"""
        clean = (target or "online").strip() or "online"
        live = self.releases.live_rev()
        if clean == "online":
            if not live:
                raise ReleaseNotFound("尚未发布任何线上版本")
            return live, self.releases.snapshot(live), f"线上版本 ({live})"
        if clean == "draft":
            rs = self.service.overlay()
            return f"{live or 'r0'}+draft", rs, f"当前草稿 (基于 {live or '未发布'})"
        if REV_RE.match(clean):
            return clean, self.releases.snapshot(clean), f"历史版本 ({clean})"
        raise InvalidResource(f"不支持的回归目标版本：{clean}")

    async def _run_single_target(
        self,
        *,
        tid: int | None,
        case: CaseDef,
        target_name: str,
        snapshot: tuple[str, ResourceSet],
        operator: str,
        batch_id: str,
    ) -> dict[str, Any]:
        """在指定资源快照下执行单条用例（tid=None 时自动走 TemplateRouter 路由）。"""
        t0 = time.monotonic()
        req = RunRequest(
            template_id=tid,
            inputs=dict(case.inputs or {}),
            document=case.documentText or "",
            entry="回归",
            target="draft" if target_name == "draft" else "online",
            operator=operator,
            extra={
                "batchNo": batch_id,
                "caseId": case.id,
                "caseScope": scope_key(tid),
            },
            snapshot_override=snapshot,
        )
        try:
            out = await self.runner.run(req)
        except TemplateRouteError as exc:
            return {
                "status": "FAILED",
                "templateId": None,
                "templateName": "",
                "runId": None,
                "found": 0,
                "total": 0,
                "durationMs": int((time.monotonic() - t0) * 1000),
                "error": f"自动路由未命中模板：{exc}",
                "routing": {"matched": False, "reason": exc.reason, "candidates": exc.candidates},
                "fields": {},
                "report": "",
            }
        except (InputValidationError, TemplateUnavailable) as exc:
            routing = getattr(exc, "routing", None)
            matched_tid = getattr(exc, "template_id", None) or tid
            matched_name = getattr(exc, "template_name", None) or ""
            return {
                "status": "FAILED",
                "templateId": matched_tid,
                "templateName": matched_name,
                "runId": None,
                "found": 0,
                "total": 0,
                "durationMs": int((time.monotonic() - t0) * 1000),
                "error": str(exc),
                "routing": routing,
                "fields": {},
                "report": "",
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("回归执行异常 case=%s target=%s：%s", case.id, target_name, exc)
            return {
                "status": "FAILED",
                "templateId": tid,
                "templateName": "",
                "runId": None,
                "found": 0,
                "total": 0,
                "durationMs": int((time.monotonic() - t0) * 1000),
                "error": f"执行异常：{type(exc).__name__}: {exc}",
                "routing": None,
                "fields": {},
                "report": "",
            }

        all_fields = _extract_fields(out)
        return {
            "status": str(out.get("status") or "FAILED"),
            "templateId": out.get("templateId"),
            "templateName": str(out.get("templateName") or ""),
            "runId": out.get("runId"),
            "found": int(out.get("foundCount") or out.get("found") or 0),
            "total": int(out.get("totalCount") or out.get("total") or 0),
            "missingShown": list(out.get("missingShown") or []),
            "durationMs": int(out.get("durationMs") or int((time.monotonic() - t0) * 1000)),
            "error": out.get("error"),
            "routing": out.get("routing"),
            "fields": all_fields,
            "report": str(out.get("report") or ""),
        }

    def _compare_case(
        self,
        *,
        tid: int | None,
        case: CaseDef,
        mode: RegressionMode,
        res_a: dict[str, Any],
        res_b: dict[str, Any] | None,
        label_a: str,
        label_b: str | None,
        rs_a: ResourceSet,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """根据单版/双版结果计算用例判定结论与字段差异明细列表。"""
        is_auto = tid is None
        sc = scope_key(tid)
        diffs: list[dict[str, Any]] = []
        expected_map = dict(case.expectedValues or {})
        matched_a = res_a.get("templateId")
        matched_b = res_b.get("templateId") if res_b else None
        route_mismatch = False

        # 1. 自动路由期望模板校验与双版路由一致性比对
        if is_auto:
            exp_tid = case.expectedTemplateId
            if exp_tid is not None and matched_a != exp_tid:
                route_mismatch = True
                exp_name = rs_a.templates[exp_tid].name if exp_tid in rs_a.templates else f"#{exp_tid}"
                got_desc = f"#{matched_a} {res_a.get('templateName', '')}".strip() if matched_a else "未命中"
                diffs.append({
                    "scope": sc,
                    "templateId": matched_a,
                    "caseId": case.id,
                    "caseName": case.name or case.id,
                    "field": "自动路由模板",
                    "valA": got_desc,
                    "valB": (
                        f"#{matched_b} {res_b.get('templateName', '')}".strip()
                        if (res_b and matched_b)
                        else ("未命中" if res_b else "—")
                    ),
                    "expected": f"#{exp_tid} {exp_name}",
                    "evA": str((res_a.get("routing") or {}).get("reason") or res_a.get("error") or "—"),
                    "evB": str((res_b.get("routing") or {}).get("reason") or res_b.get("error") or "—") if res_b else "—",
                    "note": f"自动路由命中与期望模板不一致（期望 #{exp_tid}，实际 {got_desc}）",
                    "runIdA": res_a.get("runId"),
                    "runIdB": res_b.get("runId") if res_b else None,
                    "kind": "route_mismatch",
                })
            elif mode == "compare" and res_b is not None and matched_a != matched_b:
                route_mismatch = True
                desc_a = f"#{matched_a} {res_a.get('templateName', '')}".strip() if matched_a else "未命中"
                desc_b = f"#{matched_b} {res_b.get('templateName', '')}".strip() if matched_b else "未命中"
                diffs.append({
                    "scope": sc,
                    "templateId": matched_a,
                    "caseId": case.id,
                    "caseName": case.name or case.id,
                    "field": "自动路由模板",
                    "valA": desc_a,
                    "valB": desc_b,
                    "expected": f"#{exp_tid}" if exp_tid else "",
                    "evA": str((res_a.get("routing") or {}).get("reason") or res_a.get("error") or "—"),
                    "evB": str((res_b.get("routing") or {}).get("reason") or res_b.get("error") or "—"),
                    "note": f"{label_a} 与 {label_b} 自动路由命中了不同模板（{desc_a} vs {desc_b}）",
                    "runIdA": res_a.get("runId"),
                    "runIdB": res_b.get("runId"),
                    "kind": "route_diff",
                })

        # 2. 字段值比对（双版模式对比 A vs B + 期望值；单版模式对比 A vs 期望值）
        fields_a: dict[str, dict[str, Any]] = res_a.get("fields") or {}
        fields_b: dict[str, dict[str, Any]] = (res_b.get("fields") or {}) if res_b else {}
        all_field_names: list[str] = []
        for fname in (*fields_a.keys(), *fields_b.keys(), *expected_map.keys()):
            if fname not in all_field_names:
                all_field_names.append(fname)

        expected_mismatch_count = 0
        version_diff_count = 0
        for fname in all_field_names:
            fa = fields_a.get(fname)
            fb = fields_b.get(fname)
            va = _field_val_text(fa) if fa else ""
            vb = _field_val_text(fb) if fb else ""
            exp = expected_map.get(fname, "")

            if mode == "compare" and res_b is not None:
                ab_diff = _norm_compare(va) != _norm_compare(vb)
                exp_diff = bool(exp) and (_norm_compare(va) != _norm_compare(exp) or _norm_compare(vb) != _norm_compare(exp))
                if ab_diff:
                    version_diff_count += 1
                if exp_diff:
                    expected_mismatch_count += 1
                if ab_diff or exp_diff:
                    notes = []
                    if ab_diff:
                        notes.append(f"{label_a} 与 {label_b} 输出值存在差异")
                    if exp_diff:
                        notes.append("偏离已设定的期望基线值")
                    diffs.append({
                        "scope": sc,
                        "templateId": matched_a,
                        "caseId": case.id,
                        "caseName": case.name or case.id,
                        "field": fname,
                        "valA": va or "（缺失）",
                        "valB": vb or "（缺失）",
                        "expected": exp,
                        "evA": _field_ev_text(fa) if fa else "—",
                        "evB": _field_ev_text(fb) if fb else "—",
                        "note": "；".join(notes),
                        "runIdA": res_a.get("runId"),
                        "runIdB": res_b.get("runId"),
                        "kind": "field_diff",
                    })
            else:
                if exp and _norm_compare(va) != _norm_compare(exp):
                    expected_mismatch_count += 1
                    diffs.append({
                        "scope": sc,
                        "templateId": matched_a,
                        "caseId": case.id,
                        "caseName": case.name or case.id,
                        "field": fname,
                        "valA": va or "（缺失）",
                        "valB": exp,
                        "expected": exp,
                        "evA": _field_ev_text(fa) if fa else "—",
                        "evB": "期望基线值",
                        "note": f"{label_a} 输出与期望值不一致",
                        "runIdA": res_a.get("runId"),
                        "runIdB": None,
                        "kind": "expected_mismatch",
                    })

        # 3. 综合判定单条用例结论
        st_a = res_a.get("status")
        st_b = res_b.get("status") if res_b else None
        if st_a == "FAILED" or (mode == "compare" and st_b == "FAILED"):
            verdict = "失败"
        elif route_mismatch:
            verdict = "路由偏差"
        elif expected_mismatch_count > 0:
            verdict = "偏离期望"
        elif version_diff_count > 0:
            verdict = "有差异"
        elif st_a == "PARTIAL" or (mode == "compare" and st_b == "PARTIAL"):
            verdict = "部分缺失"
        else:
            verdict = "通过"

        summary_row = {
            "scope": sc,
            "templateId": tid,
            "isAuto": is_auto,
            "caseId": case.id,
            "caseName": case.name or case.id,
            "expectedTemplateId": case.expectedTemplateId,
            "verdict": verdict,
            "statusA": st_a,
            "templateIdA": matched_a,
            "templateNameA": res_a.get("templateName") or "",
            "runIdA": res_a.get("runId"),
            "foundA": res_a.get("found", 0),
            "totalA": res_a.get("total", 0),
            "durationMsA": res_a.get("durationMs", 0),
            "errorA": res_a.get("error"),
            "routingA": res_a.get("routing"),
            "statusB": st_b,
            "templateIdB": matched_b,
            "templateNameB": res_b.get("templateName") if res_b else "",
            "runIdB": res_b.get("runId") if res_b else None,
            "foundB": res_b.get("found", 0) if res_b else 0,
            "totalB": res_b.get("total", 0) if res_b else 0,
            "durationMsB": res_b.get("durationMs", 0) if res_b else 0,
            "errorB": res_b.get("error") if res_b else None,
            "diffCount": len(diffs),
            "routeMismatch": route_mismatch,
        }
        return summary_row, diffs

    async def run_batch(
        self,
        req: RegressionRunRequest,
        *,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """执行单版或双版批量回归，并通过 on_event 实时产出进度事件。#Created By AiCoding(codex)"""
        if not req.cases:
            raise InvalidResource("请至少选择一条回归用例")

        rev_a, rs_a, label_a = self._resolve_snapshot(req.target_a)
        snap_a = (rev_a, rs_a)
        snap_b: tuple[str, ResourceSet] | None = None
        label_b: str | None = None
        if req.mode == "compare":
            tb = (req.target_b or "online").strip() or "online"
            rev_b, rs_b, label_b = self._resolve_snapshot(tb)
            snap_b = (rev_b, rs_b)

        resolved_items: list[tuple[int | None, CaseDef]] = []
        for item in req.cases:
            tid = parse_case_scope(item.scope)
            found = self.cases.get(tid, item.case_id)
            if found is None:
                continue
            resolved_items.append((tid, found))
        if not resolved_items:
            raise InvalidResource("所选回归用例不存在或已被删除")

        batch_id = new_batch_id()
        started_at = now_iso()
        t0 = time.monotonic()
        total = len(resolved_items)
        if on_event:
            on_event("batch_start", {
                "batchId": batch_id,
                "mode": req.mode,
                "targetA": req.target_a,
                "targetALabel": label_a,
                "targetB": req.target_b if req.mode == "compare" else None,
                "targetBLabel": label_b,
                "totalCases": total,
                "startedAt": started_at,
            })

        cfg_conc = int(getattr(self.runner.settings, "agent_max_concurrent_runs", 4) or 4)
        conc = max(1, min(req.max_concurrency or cfg_conc, 4))
        sem = asyncio.Semaphore(conc)

        results: list[dict[str, Any]] = []
        all_diffs: list[dict[str, Any]] = []
        done_count = 0
        cancelled = False

        async def _exec_one(idx: int, tid: int | None, case: CaseDef) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            async with sem:
                if on_event:
                    on_event("case_start", {
                        "batchId": batch_id,
                        "index": idx,
                        "total": total,
                        "scope": scope_key(tid),
                        "caseId": case.id,
                        "caseName": case.name or case.id,
                    })
                if req.mode == "compare" and snap_b is not None:
                    res_a, res_b = await asyncio.gather(
                        self._run_single_target(
                            tid=tid, case=case, target_name=req.target_a, snapshot=snap_a,
                            operator=req.operator, batch_id=batch_id,
                        ),
                        self._run_single_target(
                            tid=tid, case=case, target_name=req.target_b or "online", snapshot=snap_b,
                            operator=req.operator, batch_id=batch_id,
                        ),
                    )
                else:
                    res_a = await self._run_single_target(
                        tid=tid, case=case, target_name=req.target_a, snapshot=snap_a,
                        operator=req.operator, batch_id=batch_id,
                    )
                    res_b = None

                row, diffs = self._compare_case(
                    tid=tid, case=case, mode=req.mode,
                    res_a=res_a, res_b=res_b,
                    label_a=label_a, label_b=label_b, rs_a=rs_a,
                )

                # 回写最新状态到用例 YAML，便于列表刷新后持久展示
                def _persist_case() -> None:
                    latest = self.cases.get(tid, case.id) or case
                    updated = latest.model_copy(update={
                        "lastResult": row["verdict"],
                        "lastRunId": row["runIdA"] or latest.lastRunId,
                        "lastMatchedTemplateId": row["templateIdA"] if tid is None else latest.lastMatchedTemplateId,
                    })
                    self.cases.save(tid, updated)

                await asyncio.to_thread(_persist_case)
                return row, diffs

        tasks = [
            asyncio.create_task(_exec_one(i + 1, tid, case))
            for i, (tid, case) in enumerate(resolved_items)
        ]
        try:
            for fut in asyncio.as_completed(tasks):
                row, diffs = await fut
                results.append(row)
                all_diffs.extend(diffs)
                done_count += 1
                if on_event:
                    on_event("case_done", {
                        "batchId": batch_id,
                        "done": done_count,
                        "total": total,
                        "result": row,
                        "diffs": diffs,
                    })
        except asyncio.CancelledError:
            cancelled = True
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        # 按原请求顺序整理 results
        order_idx = {(scope_key(tid), c.id): i for i, (tid, c) in enumerate(resolved_items)}
        results.sort(key=lambda r: order_idx.get((r["scope"], r["caseId"]), 999999))

        passed = sum(1 for r in results if r["verdict"] == "通过")
        failed = sum(1 for r in results if r["verdict"] == "失败")
        route_mis = sum(1 for r in results if r.get("routeMismatch"))
        diff_cases = sum(1 for r in results if r["diffCount"] > 0)
        executed = len(results)
        pass_rate = round((passed * 100.0 / executed), 1) if executed else 0.0

        batch = {
            "batchId": batch_id,
            "mode": req.mode,
            "targetA": req.target_a,
            "targetALabel": label_a,
            "targetB": req.target_b if req.mode == "compare" else None,
            "targetBLabel": label_b,
            "operator": req.operator,
            "startedAt": started_at,
            "finishedAt": now_iso(),
            "durationMs": int((time.monotonic() - t0) * 1000),
            "totalCases": total,
            "executedCases": executed,
            "passedCases": passed,
            "diffCases": diff_cases,
            "routeMismatchCases": route_mis,
            "failedCases": failed,
            "passRate": pass_rate,
            "cancelled": cancelled,
            "results": results,
            "diffs": all_diffs,
        }
        await asyncio.to_thread(self.store.save, batch)
        if on_event:
            on_event("batch_done", batch)
        return batch


__all__ = [
    "AUTO_CASE_SCOPE",
    "RegressionCaseTarget",
    "RegressionMode",
    "RegressionRunRequest",
    "RegressionRunner",
    "RegressionStore",
    "new_batch_id",
]
