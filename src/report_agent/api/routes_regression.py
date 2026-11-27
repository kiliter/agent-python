"""全平台回归测试路由：跨模板/自动路由用例总览与 CRUD、基线采纳、SSE 流式单版/双版批量回归与历史批次查询。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..domain.sanitize import sanitize_sensitive_text
from ..runtime.regression import (
    RegressionCaseTarget,
    RegressionMode,
    RegressionRunRequest,
    RegressionRunner,
)
from ..store.cases import CaseDef, CaseStore, parse_case_scope, scope_key
from .auth import require_user
from .common import SSE_HEADERS, bad_request, container, iter_sse_queue, not_found, operator
from .dto import fmt_time, non_empty_expected_count, serialize_expected_value

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/regression", dependencies=[Depends(require_user)], tags=["回归测试"])


def _case_view(
    tid: int | None,
    c: CaseDef,
    tpl_names: dict[int, str],
) -> dict[str, Any]:
    """将单条 CaseDef（固定模板或自动路由）转换为全平台回归视图 DTO。#Created By AiCoding(codex)"""
    sc = scope_key(tid)
    exp_tid = c.expectedTemplateId
    matched_tid = c.lastMatchedTemplateId
    non_empty = non_empty_expected_count(c.expectedValues)
    return {
        "scope": sc,
        "isAuto": tid is None,
        "templateId": tid,
        "templateName": "自动路由" if tid is None else tpl_names.get(tid, f"模板 #{tid}"),
        "id": c.id,
        "name": c.name,
        "source": c.source,
        "expectedCount": f"{non_empty} 项" if non_empty else "—",
        "expectedTemplateId": exp_tid,
        "expectedTemplateName": tpl_names.get(exp_tid, f"模板 #{exp_tid}") if exp_tid else "",
        "lastMatchedTemplateId": matched_tid,
        "lastMatchedTemplateName": tpl_names.get(matched_tid, f"模板 #{matched_tid}") if matched_tid else "",
        "lastResult": c.lastResult,
        "lastRunId": c.lastRunId,
        "updatedAt": fmt_time(c.updatedAt),
        "mobile": c.inputs.get("手机号码", ""),
        "busiName": c.inputs.get("业务名称", ""),
        "createTime": c.inputs.get("创建时间", ""),
        "busiMonth": c.inputs.get("业务月份", ""),
        "appealContent": c.inputs.get("申诉内容", ""),
        "inputs": c.inputs,
        "documentText": c.documentText,
        "expectedValues": c.expectedValues,
    }


def _template_names_map(request: Request) -> dict[int, str]:
    c = container(request)
    rs = c.service.overlay()
    return {tid: tpl.name for tid, tpl in rs.templates.items()}


@router.get("/cases")
def list_all_cases(
    request: Request,
    scope: str = "",
    q: str = "",
) -> list[dict[str, Any]]:
    """列出全平台回归用例（默认同时含自动路由与全部模板用例）。"""
    c = container(request)
    tpl_names = _template_names_map(request)
    clean_scope = (scope or "").strip().lower()
    kw = (q or "").strip().lower()

    if clean_scope:
        tid_filter = parse_case_scope(clean_scope)
        pairs = [(tid_filter, item) for item in c.cases.list(tid_filter)]
    else:
        pairs = c.cases.list_all()

    out: list[dict[str, Any]] = []
    for tid, item in pairs:
        view = _case_view(tid, item, tpl_names)
        if kw:
            hay = " ".join([
                view["id"],
                view["name"],
                view["templateName"],
                view["mobile"],
                view["busiName"],
                view["appealContent"],
                view["source"],
            ]).lower()
            if kw not in hay:
                continue
        out.append(view)
    return out


class CreateGlobalCaseBody(BaseModel):
    templateId: int | None = Field(default=None, description="null 或 0 表示创建未绑定模板的自动路由用例")
    id: str | None = None
    name: str = ""
    source: str = "手工新建"
    inputs: dict[str, Any] = Field(default_factory=dict)
    documentText: str = ""
    expectedValues: dict[str, Any] = Field(default_factory=dict)
    expectedTemplateId: int | None = None
    mobile: str | None = None
    busiName: str | None = None
    createTime: str | None = None
    busiMonth: str | None = None
    appealContent: str | None = None


@router.post("/cases")
def create_global_case(request: Request, body: CreateGlobalCaseBody) -> dict[str, Any]:
    """新建一条自动路由或指定模板回归用例。"""
    c = container(request)
    tid = parse_case_scope(body.templateId)
    data = body.model_dump(exclude={"templateId"}, exclude_none=True)
    case_id = (body.id or "").strip() or c.cases.next_id(tid)
    data["id"] = case_id
    if c.cases.get(tid, case_id) is not None:
        raise bad_request(f"用例编号「{case_id}」已存在", "CASE_EXISTS")
    case = CaseStore.from_payload(data)
    saved = c.cases.save(tid, case)
    c.publisher.audit("case-create", operator(request), {"scope": scope_key(tid), "caseId": saved.id})
    return _case_view(tid, saved, _template_names_map(request))


class UpdateGlobalCaseBody(BaseModel):
    targetTemplateId: int | None = Field(default=None, description="可选：修改归属模板（0 或 auto 表示改为自动路由）")
    changeScope: bool = Field(default=False, description="为 true 时按 targetTemplateId 迁移归属")
    name: str | None = None
    source: str | None = None
    inputs: dict[str, Any] | None = None
    documentText: str | None = None
    expectedValues: dict[str, Any] | None = None
    expectedTemplateId: int | None = None
    clearExpectedTemplate: bool = False
    mobile: str | None = None
    busiName: str | None = None
    createTime: str | None = None
    busiMonth: str | None = None
    appealContent: str | None = None


@router.put("/cases/{scope}/{case_id}")
def update_global_case(
    request: Request,
    scope: str,
    case_id: str,
    body: UpdateGlobalCaseBody,
) -> dict[str, Any]:
    """更新回归用例，可选在自动路由与指定模板间迁移归属。"""
    c = container(request)
    src_tid = parse_case_scope(scope)
    existing = c.cases.get(src_tid, case_id)
    if existing is None:
        raise not_found(f"用例 {case_id} 不存在")

    patch = body.model_dump(exclude={"targetTemplateId", "changeScope", "clearExpectedTemplate"}, exclude_none=True)
    if body.clearExpectedTemplate:
        patch["expectedTemplateId"] = None
    patch["id"] = case_id
    updated = CaseStore.from_payload(patch, base=existing)

    dst_tid = parse_case_scope(body.targetTemplateId) if body.changeScope else src_tid
    saved = c.cases.move(src_tid, case_id, dst_tid, updated=updated)
    c.publisher.audit(
        "case-update",
        operator(request),
        {"scope": scope_key(dst_tid), "fromScope": scope_key(src_tid), "caseId": saved.id},
    )
    return _case_view(dst_tid, saved, _template_names_map(request))


@router.delete("/cases/{scope}/{case_id}")
def delete_global_case(request: Request, scope: str, case_id: str) -> dict[str, Any]:
    """删除回归用例。"""
    c = container(request)
    tid = parse_case_scope(scope)
    if not c.cases.delete(tid, case_id):
        raise not_found(f"用例 {case_id} 不存在")
    c.publisher.audit("case-delete", operator(request), {"scope": scope_key(tid), "caseId": case_id})
    return {"deletedScope": scope_key(tid), "deletedId": case_id}


class AdoptBaselineBody(BaseModel):
    runId: str = Field(description="要采纳为期望基线的运行记录 ID")
    adoptFields: bool = Field(default=True, description="是否将本次运行核出的可见字段写入 expectedValues")
    adoptTemplate: bool = Field(default=True, description="自动路由用例是否同时锁定本次命中模板为 expectedTemplateId")
    onlyField: str | None = Field(default=None, description="仅采纳单个指定字段（从差异抽屉局部采纳）")


@router.post("/cases/{scope}/{case_id}/adopt-baseline")
def adopt_case_baseline(
    request: Request,
    scope: str,
    case_id: str,
    body: AdoptBaselineBody,
) -> dict[str, Any]:
    """一键将某次运行的结果字段（及自动路由命中的模板）采纳为回归期望基线。#Created By AiCoding(codex)"""
    c = container(request)
    tid = parse_case_scope(scope)
    existing = c.cases.get(tid, case_id)
    if existing is None:
        raise not_found(f"用例 {case_id} 不存在")
    run = c.runs.get(body.runId.strip())
    if run is None:
        raise not_found(f"运行记录 {body.runId} 不存在")

    expected = dict(existing.expectedValues or {})
    if body.adoptFields:
        fields = run.get("fields") or []
        for f in fields:
            if not isinstance(f, dict):
                continue
            fname = str(f.get("name") or "").strip()
            if not fname:
                continue
            if body.onlyField and fname != body.onlyField:
                continue
            if (f.get("status") or f.get("runStatus")) == "found":
                expected[fname] = serialize_expected_value(f.get("value"))
            elif body.onlyField and fname == body.onlyField:
                expected.pop(fname, None)

    exp_tid = existing.expectedTemplateId
    matched_tid = run.get("templateId")
    if tid is None and body.adoptTemplate and isinstance(matched_tid, int) and matched_tid > 0:
        exp_tid = matched_tid

    updated = existing.model_copy(update={
        "expectedValues": expected,
        "expectedTemplateId": exp_tid,
        "lastMatchedTemplateId": matched_tid if (tid is None and isinstance(matched_tid, int) and matched_tid > 0) else existing.lastMatchedTemplateId,
        "lastRunId": body.runId.strip(),
    })
    saved = c.cases.save(tid, updated)
    c.publisher.audit(
        "case-adopt-baseline",
        operator(request),
        {"scope": scope_key(tid), "caseId": saved.id, "runId": body.runId.strip(), "onlyField": body.onlyField},
    )
    return _case_view(tid, saved, _template_names_map(request))


class CaseTargetBody(BaseModel):
    scope: str
    caseId: str


class RunRegressionBody(BaseModel):
    cases: list[CaseTargetBody] = Field(default_factory=list, description="待执行用例列表（为空时报错）")
    mode: RegressionMode = Field(default="single", description="single=单版回归；compare=双版对比回归")
    targetA: str = Field(default="online", description="版本 A：online / draft / rN")
    targetB: str | None = Field(default=None, description="版本 B（仅 compare 模式生效）：online / draft / rN")
    maxConcurrency: int | None = Field(default=None, ge=1, le=4)


@router.post("/run/stream")
async def run_regression_stream(request: Request, body: RunRegressionBody):
    """SSE 流式执行单条或批量回归（支持自动路由与双版对比）。#Created By AiCoding(codex)"""
    c = container(request)
    if not body.cases:
        raise bad_request("请至少勾选一条回归用例", "EMPTY_CASES")
    if body.mode == "compare" and not (body.targetB or "").strip():
        raise bad_request("双版对比模式必须指定对比版本 B", "MISSING_TARGET_B")

    req = RegressionRunRequest(
        cases=[RegressionCaseTarget(scope=it.scope, case_id=it.caseId) for it in body.cases],
        mode=body.mode,
        target_a=body.targetA,
        target_b=body.targetB,
        operator=operator(request),
        max_concurrency=body.maxConcurrency,
    )
    reg_runner = RegressionRunner(c.runner, c.cases, c.releases, c.service, c.regressions)

    queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()

    def _emit(ev_name: str, payload: dict[str, Any]) -> None:
        queue.put_nowait((ev_name, payload))

    async def _worker() -> None:
        try:
            await reg_runner.run_batch(req, on_event=_emit)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("批量回归流式运行异常")
            safe_msg = sanitize_sensitive_text(f"{type(exc).__name__}: {exc}", fallback=type(exc).__name__)
            queue.put_nowait(("error", {"code": "REGRESSION_ERROR", "message": safe_msg}))
        finally:
            queue.put_nowait(None)

    async def _gen():
        task: asyncio.Task[None] | None = None
        try:
            task = asyncio.create_task(_worker(), name="regression-sse-worker")
            async for frame in iter_sse_queue(queue, terminal_kinds=()):
                yield frame
        finally:
            if task is not None:
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(_gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/batches")
def list_regression_batches(request: Request, limit: int = 30) -> list[dict[str, Any]]:
    """查询最近保存的回归批次摘要（最新在前）。"""
    return container(request).regressions.list(limit=limit)


@router.get("/batches/{batch_id}")
def get_regression_batch(request: Request, batch_id: str) -> dict[str, Any]:
    """读取指定回归批次的完整结果与逐字段差异明细。"""
    found = container(request).regressions.get(batch_id)
    if found is None:
        raise not_found(f"回归批次 {batch_id} 不存在")
    return found
