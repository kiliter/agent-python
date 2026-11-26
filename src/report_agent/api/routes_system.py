"""认证、发布版本、运行记录、上游填写接口。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any
from urllib.parse import quote
import weakref

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..runtime.composite import CompositeItemRequest, CompositeRunner, CompositeRunRequest
from ..runtime.runner import RunRequest
from ..store.fsutil import fmt_time, now_iso
from ..store.layout import SAFE_ID_RE, ref_from_tree_path
from ..store.releases import ReleaseNotFound
from ..store.runs import _percentile
from ..store.service import SP_REF, api_ref, skill_ref, tpl_ref
from .auth import (
    COOKIE_NAME,
    DUMMY_PASSWORD_HASH,
    MAX_PASSWORD_LEN,
    MAX_USERNAME_LEN,
    User,
    require_report_key,
    require_user,
    verify_password,
    verify_request_user,
)
from .common import bad_request, container, not_found, operator, sse_run
from .dto import release_dto, run_record
from .missing_summary import build_missing_summary, generate_ai_missing_summary
from .run_export import render_runs_replay_html
from .run_views import detail_view, report_view

auth_router = APIRouter(prefix="/api/v1")
admin_router = APIRouter(prefix="/api/v1", tags=["发布版本 / 运行记录"], dependencies=[Depends(require_user)])
report_router = APIRouter(prefix="/api/v1", tags=["上游调用"], dependencies=[Depends(require_report_key)])


# ============================================================================ 系统健康
@auth_router.get("/health", tags=["系统"])
def api_health(request: Request) -> dict[str, Any]:
    """API 命名空间只读健康检查（兼容 /healthz 并补充版本与网关摘要）。"""
    c = container(request)
    return {
        "status": "UP",
        "liveRev": c.releases.live_rev(),
        "totalReleases": len(c.releases.entries()),
        "gatewayMode": c.settings.gateway_mode,
        "time": now_iso(),
    }


# ============================================================================ 认证
# 按当前事件循环隔离登录并发信号量：限制 PBKDF2（60 万次迭代）并发线程占用，同时避免跨事件循环绑定异常
_LOGIN_MAX_CONCURRENCY = 4
_LOGIN_SEMS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _login_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _LOGIN_SEMS.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(_LOGIN_MAX_CONCURRENCY)
        _LOGIN_SEMS[loop] = sem
    return sem


def _client_ip(request: Request) -> str | None:
    """提取直连客户端 IP（不盲信可伪造的代理头，防绕过限流或伪造封禁）。"""
    client = request.client
    return client.host if client and client.host else None


class LoginBody(BaseModel):
    username: str
    password: str


@auth_router.post("/auth/login", tags=["认证"])
async def login(request: Request, response: Response, body: LoginBody) -> dict[str, Any]:
    guard = request.app.state.login_guard
    users = request.app.state.users
    username = body.username.strip()
    if not username or not body.password:
        raise bad_request("用户名和密码不能为空")
    if len(username) > MAX_USERNAME_LEN:
        raise bad_request(f"用户名长度不能超过 {MAX_USERNAME_LEN} 个字符", "INVALID_USERNAME")
    client_ip = _client_ip(request)
    guard.check(username, client_ip=client_ip)
    if len(body.password) > MAX_PASSWORD_LEN:
        guard.fail(username, known_user=False, client_ip=client_ip)
        raise HTTPException(401, detail={"code": "INVALID_CREDENTIALS", "message": "用户名或密码错误"})

    def _verify_credentials() -> tuple[dict[str, Any] | None, bool, bool]:
        rec_local = users.get(username)
        raw_hash = rec_local.get("passwordHash") if rec_local else None
        valid_hash = isinstance(raw_hash, str) and bool(raw_hash)
        matched = verify_password(body.password, raw_hash if valid_hash else DUMMY_PASSWORD_HASH)
        return rec_local, valid_hash, matched

    async with _login_semaphore():
        rec, has_valid_hash, pw_ok = await asyncio.to_thread(_verify_credentials)

    if not rec or not has_valid_hash or not pw_ok:
        guard.fail(username, known_user=rec is not None, client_ip=client_ip)
        raise HTTPException(401, detail={"code": "INVALID_CREDENTIALS", "message": "用户名或密码错误"})
    guard.success(username, client_ip=client_ip)
    user = User(username, rec.get("displayName") or username, rec.get("role") or "")
    token = request.app.state.tokens.issue(user)
    settings = container(request).settings
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.admin_token_ttl_s,
        httponly=True,
        samesite="strict",
        secure=settings.admin_cookie_secure,
        path="/",
    )
    return {"token": token, "username": user.username, "displayName": user.displayName, "role": user.role}


@auth_router.post("/auth/logout", tags=["认证"])
def logout(request: Request, response: Response) -> dict[str, Any]:
    verified = verify_request_user(request)
    if verified is not None:
        request.app.state.tokens.revoke(verified[1])
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@auth_router.get("/auth/me", tags=["认证"])
def me(user: User = Depends(require_user)) -> dict[str, Any]:
    return {"username": user.username, "displayName": user.displayName, "role": user.role}


# ============================================================================ 发布版本
@admin_router.get("/releases")
def list_releases(request: Request, limit: int = 100) -> list[dict[str, Any]]:
    if limit < 1:
        raise bad_request("分页大小 limit 必须大于等于 1", "INVALID_LIMIT")
    c = container(request)
    live = c.releases.live_rev()
    entries = c.releases.entries()
    n = min(limit, 1000)
    return [release_dto(e, live) for e in reversed(entries[-n:])]


@admin_router.get("/releases/diff")
def release_diff(request: Request, a: str, b: str) -> dict[str, Any]:
    """两个版本之间变化的资源（a → b）。"""
    a, b = a.strip(), b.strip()
    if not a or not b:
        raise bad_request("对比版本号 a 和 b 不能为空", "INVALID_RELEASE")
    c = container(request)
    try:
        ea, eb = c.releases.entry(a), c.releases.entry(b)
    except ReleaseNotFound as exc:
        raise not_found(f"版本 {exc} 不存在") from exc
    if a == b or ea["commit"] == eb["commit"]:
        return {"a": a, "b": b, "changes": []}
    changes: dict[tuple[str, str], dict[str, Any]] = {}
    for ns in c.repo.diff_name_status(ea["commit"], eb["commit"]):
        ref = ref_from_tree_path(ns.path)
        if ref is None:
            continue
        key = (ref.kind, ref.key)
        kind = {"A": "added", "D": "removed"}.get(ns.status, "modified")
        prev = changes.get(key)
        if prev and prev["change"] != kind:
            kind = "modified"
        changes[key] = {
            "kind": ref.kind,
            "key": ref.key,
            "label": ref.label(),
            "change": kind,
            "files": [*(prev["files"] if prev else []), ns.path],
        }
    return {"a": a, "b": b, "changes": list(changes.values())}


@admin_router.get("/releases/{rev}")
def get_release(request: Request, rev: str) -> dict[str, Any]:
    c = container(request)
    try:
        return release_dto(c.releases.entry(rev), c.releases.live_rev())
    except ReleaseNotFound as exc:
        raise not_found(f"版本 {rev} 不存在") from exc


class SwitchBody(BaseModel):
    targetRev: str
    reason: str


@admin_router.post("/releases/emergency-switch")
def emergency_switch(request: Request, body: SwitchBody) -> dict[str, Any]:
    """紧急把线上切到历史版本。之后的发布以切换后的版本为基准。"""
    c = container(request)
    if not body.reason.strip():
        raise bad_request("必须填写紧急切换原因")
    try:
        c.releases.entry(body.targetRev)
    except ReleaseNotFound as exc:
        raise not_found(f"版本 {body.targetRev} 不存在") from exc
    c.publisher.emergency_switch(body.targetRev, operator(request), body.reason)
    return {"activeRev": c.releases.live_rev()}


# ============================================================================ 运行记录
@admin_router.get("/runs")
def list_runs(
    request: Request,
    dateFrom: date | None = None,
    dateTo: date | None = None,
    mobile: str = "",
    templateId: int | None = None,
    template: str = "",
    status: str = "",
    entry: str = "",
    batchNo: str = "",
    q: str = "",
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """按条件查询运行摘要（默认最近 7 天，最新在前），支持 offset + limit 分页。"""
    if limit < 1:
        raise bad_request("分页大小 limit 必须大于等于 1", "INVALID_LIMIT")
    if offset < 0:
        raise bad_request("分页偏移量 offset 不能小于 0", "INVALID_OFFSET")
    if dateFrom and dateTo and dateFrom > dateTo:
        raise bad_request("开始日期不能晚于结束日期", "INVALID_DATE_RANGE")
    if templateId is not None and templateId <= 0:
        raise bad_request("模板编号必须为正整数", "INVALID_TEMPLATE_ID")
    c = container(request)
    mobile_q = mobile.strip()
    tpl_q = template.strip()
    batch_q = batchNo.strip()
    kw = q.strip().lower()

    def pred(item: dict[str, Any]) -> bool:
        run_id = str(item.get("runId") or "")
        if mobile_q and mobile_q not in (item.get("mobile") or "") and mobile_q not in run_id:
            return False
        if templateId is not None and item.get("templateId") != templateId:
            return False
        if tpl_q and tpl_q not in f"{item.get('templateId')} {item.get('templateName', '')}":
            return False
        if status and status != "ALL" and item.get("status") != status:
            return False
        if entry and entry != "ALL" and item.get("entry") != entry:
            return False
        if batch_q and batch_q != (item.get("batchNo") or ""):
            return False
        if kw:
            haystack = " ".join(
                str(item.get(k) or "")
                for k in ("runId", "busiName", "templateName", "mobile", "batchNo", "entry", "error")
            ).lower()
            if kw not in haystack:
                return False
        return True

    return [run_record(i) for i in c.runs.list(dateFrom, dateTo, limit=min(limit, 2000), predicate=pred, offset=offset)]


class ExportRunsHtmlBody(BaseModel):
    runIds: list[str] = Field(default_factory=list, description="待导出的运行编号列表（支持多选，上限 50 条）")
    title: str | None = Field(default=None, description="可选自定义导出页标题")


@admin_router.post("/runs/export-html")
def export_runs_html(request: Request, body: ExportRunsHtmlBody) -> Response:
    """将选中的一条或多条运行记录导出为单页离线 ChatUI 模拟回放 HTML（零外部依赖）。#Created By AiCoding(codex)"""
    c = container(request)
    dedup_ids: list[str] = []
    seen: set[str] = set()
    for raw_id in body.runIds:
        rid = str(raw_id or "").strip()
        if not rid or rid in seen:
            continue
        if not SAFE_ID_RE.match(rid):
            raise bad_request(f"运行记录编号格式不合法：{rid}", "INVALID_RUN_ID")
        seen.add(rid)
        dedup_ids.append(rid)

    if not dedup_ids:
        raise bad_request("请至少选择一条要导出的运行记录", "EMPTY_RUN_IDS")
    if len(dedup_ids) > 50:
        raise bad_request("单次最多导出 50 条运行记录", "TOO_MANY_RUN_IDS")

    loaded: list[dict[str, Any]] = []
    for rid in dedup_ids:
        rec = c.runs.get(rid)
        if rec is not None:
            loaded.append(rec)
    if not loaded:
        raise not_found("所选运行记录均不存在或已过期清理")

    try:
        _, live_rs = c.service.live()
    except Exception:  # noqa: BLE001
        live_rs = None

    html_doc = render_runs_replay_html(loaded, resources=live_rs, title=body.title)
    if len(loaded) == 1:
        filename = f"agent-replay-{loaded[0].get('runId', 'run')}.html"
    else:
        stamp = now_iso()[:16].replace("-", "").replace(":", "").replace("T", "-")
        filename = f"agent-replay-{len(loaded)}条-{stamp}.html"
    encoded = quote(filename)
    return Response(
        content=html_doc.encode("utf-8"),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"agent-replay.html\"; filename*=UTF-8''{encoded}",
            "X-Exported-Count": str(len(loaded)),
        },
    )


@admin_router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str, withMessages: bool = False) -> dict[str, Any]:
    if not SAFE_ID_RE.match(run_id):
        raise bad_request("运行记录编号格式不合法", "INVALID_RUN_ID")
    run = container(request).runs.get(run_id)
    if run is None:
        raise not_found(f"运行记录 {run_id} 不存在")
    return detail_view(run, with_messages=withMessages)


class AiMissingSummaryBody(BaseModel):
    force: bool = Field(default=False, description="是否忽略已缓存的 AI 总结强制重新生成")


@admin_router.post("/runs/{run_id}/missing-summary/ai")
async def summarize_missing_fields_ai(
    request: Request,
    run_id: str,
    body: AiMissingSummaryBody | None = None,
) -> dict[str, Any]:
    """按需调用当前模型对单条运行记录的非找到字段生成自然语言摘要，并缓存至记录文件。#Created By AiCoding(codex)"""
    if not SAFE_ID_RE.match(run_id):
        raise bad_request("运行记录编号格式不合法", "INVALID_RUN_ID")
    c = container(request)
    run = c.runs.get(run_id)
    if run is None:
        raise not_found(f"运行记录 {run_id} 不存在")

    det = build_missing_summary(run)
    if det["nonFoundCount"] == 0:
        raise bad_request("本次运行所有字段均已找到，无需生成未找到原因摘要", "NO_MISSING_FIELDS")

    force = bool(body.force) if body is not None else False
    if not force and det.get("aiSummary"):
        return {**det, "cached": True}

    op = operator(request)
    try:
        ai_obj = await generate_ai_missing_summary(
            run,
            model=c.runner.model,
            model_settings=c.runner.model_settings,
            model_name=c.settings.llm_model,
            operator=op,
        )
    except Exception as exc:  # noqa: BLE001 - 对外屏蔽内部堆栈，仅返回可读错误
        raise HTTPException(
            502,
            detail={"code": "AI_SUMMARY_FAILED", "message": f"生成 AI 总结失败：{type(exc).__name__}"},
        ) from exc

    updated = await asyncio.to_thread(c.runs.update_detail, run_id, {"missingSummaryAi": ai_obj})
    if updated is not None:
        return {**build_missing_summary(updated), "cached": False}
    # 极端情况（如仅从 index 恢复的降级记录无 json 文件）：仍返回当次生成结果
    return {**build_missing_summary({**run, "missingSummaryAi": ai_obj}), "cached": False}


# ============================================================================ 系统运行可观测概览
@admin_router.get("/system/overview")
def system_overview(request: Request, days: int = 7) -> dict[str, Any]:
    """平台只读可观测概览：聚合资产规模、版本基线、运行成功率、字段命中率与接口耗时分布。"""
    if days < 1 or days > 365:
        raise bad_request("统计窗口天数 days 必须在 1 到 365 之间", "INVALID_DAYS")
    c = container(request)
    live_rev, live_rs = c.service.live()
    overlay = c.service.overlay()
    overlay_templates = list(overlay.templates.values())
    entries = c.releases.entries()
    live_entry = next((e for e in reversed(entries) if e["rev"] == live_rev), None) if live_rev else None
    win = c.runs.window_stats(days=days)

    tpl_counts = {"total": 0, "published": 0, "draft": 0, "publishedDraft": 0, "offline": 0, "totalCases": 0}
    template_stats: list[dict[str, Any]] = []
    for key in c.service.keys("template"):
        tid = int(key)
        tpl = overlay.templates.get(tid) or live_rs.templates.get(tid)
        if tpl is None:
            continue
        st = c.service.state(tpl_ref(tid), live_rs)
        cases_cnt = c.cases.count(tid)
        tpl_counts["total"] += 1
        tpl_counts["totalCases"] += cases_cnt
        if st.status == "PUBLISHED":
            tpl_counts["published"] += 1
        elif st.status == "PUBLISHED_DRAFT":
            tpl_counts["published"] += 1
            tpl_counts["publishedDraft"] += 1
        elif st.status == "OFFLINE":
            tpl_counts["offline"] += 1
        else:
            tpl_counts["draft"] += 1
        ts = (win.get("templates") or {}).get(str(tid)) or {}
        runs_n = int(ts.get("runs", 0))
        ok_n = int(ts.get("success", 0))
        template_stats.append({
            "id": tid,
            "name": tpl.name,
            "status": st.status,
            "runs": runs_n,
            "success": ok_n,
            "partial": int(ts.get("partial", 0)),
            "failed": int(ts.get("failed", 0)),
            "successRate": round(ok_n * 100 / runs_n, 1) if runs_n else 0.0,
            "successRateText": f"{ok_n * 100 / runs_n:.1f}%" if runs_n else "—",
            "avgDurationMs": int(ts.get("avgDurationMs", 0)),
            "p95DurationMs": int(ts.get("p95DurationMs", 0)),
            "casesCount": cases_cnt,
        })

    skill_counts = {"total": 0, "published": 0, "draft": 0, "publishedDraft": 0}
    skill_stats: list[dict[str, Any]] = []
    for sid in c.service.keys("skill"):
        sk = overlay.skills.get(sid) or live_rs.skills.get(sid)
        if sk is None:
            continue
        st = c.service.state(skill_ref(sid), live_rs)
        skill_counts["total"] += 1
        if st.status == "PUBLISHED":
            skill_counts["published"] += 1
        elif st.status == "PUBLISHED_DRAFT":
            skill_counts["published"] += 1
            skill_counts["publishedDraft"] += 1
        else:
            skill_counts["draft"] += 1
        refs_n = sum(1 for t in overlay_templates if sid in t.definition.skills)
        skill_stats.append({
            "id": sid,
            "name": sk.title,
            "status": st.status,
            "loads": int((win.get("skills") or {}).get(sid, 0)),
            "refsCount": refs_n,
        })

    api_counts = {"total": 0, "published": 0, "draft": 0, "publishedDraft": 0}
    api_stats: list[dict[str, Any]] = []
    for name in c.service.keys("api"):
        api = overlay.apis.get(name) or live_rs.apis.get(name)
        if api is None:
            continue
        st = c.service.state(api_ref(name), live_rs)
        api_counts["total"] += 1
        if st.status == "PUBLISHED":
            api_counts["published"] += 1
        elif st.status == "PUBLISHED_DRAFT":
            api_counts["published"] += 1
            api_counts["publishedDraft"] += 1
        else:
            api_counts["draft"] += 1
        calls = (win.get("apis") or {}).get(name) or []
        calls_n = len(calls)
        fail_n = sum(1 for ok, _ in calls if not ok)
        latencies = sorted(ms for _, ms in calls)
        api_stats.append({
            "name": name,
            "title": api.title,
            "status": st.status,
            "calls": calls_n,
            "successCalls": calls_n - fail_n,
            "failedCalls": fail_n,
            "failRate": round(fail_n * 100 / calls_n, 2) if calls_n else 0.0,
            "avgMs": int(sum(latencies) / calls_n) if calls_n else 0,
            "p95Ms": _percentile(latencies, 0.95),
        })

    return {
        "status": "UP",
        "generatedAt": now_iso(),
        "windowDays": days,
        "release": {
            "liveRev": live_rev,
            "totalReleases": len(entries),
            "lastPublishedAt": fmt_time(live_entry.get("time"), "从未发布") if live_entry else "从未发布",
            "lastOperator": live_entry.get("operator", "—") if live_entry else "—",
        },
        "resources": {
            "templates": tpl_counts,
            "skills": skill_counts,
            "apis": api_counts,
            "systemPromptStatus": c.service.state(SP_REF, live_rs).status,
        },
        "runs": win["summary"],
        "templateStats": template_stats,
        "skillStats": skill_stats,
        "apiStats": api_stats,
        "runtime": {
            "model": c.settings.llm_model,
            "gatewayMode": c.settings.gateway_mode,
            "maxConcurrentRuns": c.settings.agent_max_concurrent_runs,
        },
    }


# ============================================================================ 上游填写
class ReportBody(BaseModel):
    templateId: int | None = Field(
        default=None,
        description="模板编号；不传或为 null 时自动使用 template-router 路由匹配",
    )
    params: dict[str, Any] = Field(default_factory=dict, description="模板入参")
    document: str = Field(default="", description="单据全文（上游已提取的文本）")
    batchNo: str | None = None


def _report_request(body: ReportBody) -> RunRequest:
    if body.templateId is not None and body.templateId <= 0:
        raise bad_request("模板编号必须为正整数", "INVALID_TEMPLATE_ID")
    return RunRequest(
        template_id=body.templateId,
        inputs={k: "" if v is None else str(v) for k, v in body.params.items()},
        document=body.document,
        entry="上游调用",
        target="online",
        operator="upstream",
        extra={"batchNo": body.batchNo} if body.batchNo else {},
    )


@report_router.post("/reports")
async def create_report(request: Request, body: ReportBody) -> dict[str, Any]:
    """同步填写一份报告。"""
    out = await container(request).runner.run(_report_request(body))
    return report_view(out)


@report_router.post("/reports/stream")
async def create_report_stream(request: Request, body: ReportBody):
    """SSE 填写：过程事件 event=event，最终结果 event=final。"""
    return sse_run(container(request).runner, _report_request(body), report_view)


class CompositeItemBody(BaseModel):
    templateId: int | None = Field(
        default=None,
        description="模板编号；不传或为 null 时自动路由匹配",
    )
    label: str = ""
    params: dict[str, Any] = Field(default_factory=dict, description="该商品专属入参（覆盖工单公共参数）")
    document: str | None = Field(default=None, description="可选该商品独立单据正文；留空沿用工单级 document")


class CompositeReportBody(BaseModel):
    order: dict[str, Any] = Field(default_factory=dict, description="工单级公共参数（如平台流水号、手机号码、申诉内容等）")
    document: str = Field(default="", description="工单级共用单据正文")
    items: list[CompositeItemBody] = Field(default_factory=list, description="多商品/多模板子项列表")
    polish: bool = Field(default=False, description="是否在 Jinja2 确定性拼装后再执行大模型二次润色")
    polishInstruction: str = Field(default="", description="可选二次润色口径要求")
    batchNo: str | None = None


class CompositePolishBody(BaseModel):
    markdown: str = Field(description="待二次润色的确定性拼装汇总报告正文")
    order: dict[str, Any] = Field(default_factory=dict, description="可选工单公共信息")
    instruction: str = Field(default="", description="可选润色要求")


@report_router.post("/reports/composite")
async def create_composite_report(request: Request, body: CompositeReportBody) -> dict[str, Any]:
    """复合工单填写：单号码多商品匹配多模板并发核查，Jinja2 确定性拼装并可选大模型二次润色。#Created By AiCoding(codex)"""
    if not body.items:
        raise bad_request("items 至少需要包含 1 个业务子项", "EMPTY_ITEMS")
    for idx, it in enumerate(body.items, start=1):
        if it.templateId is not None and it.templateId <= 0:
            raise bad_request(f"第 {idx} 项模板编号必须为正整数", "INVALID_TEMPLATE_ID")
    req = CompositeRunRequest(
        order={str(k): "" if v is None else str(v) for k, v in body.order.items()},
        document=body.document,
        items=[
            CompositeItemRequest(
                template_id=it.templateId,
                label=it.label,
                params={str(k): "" if v is None else str(v) for k, v in it.params.items()},
                document=it.document,
            )
            for it in body.items
        ],
        polish=body.polish,
        polish_instruction=body.polishInstruction,
        entry="上游调用",
        target="online",
        operator="upstream",
        batch_no=body.batchNo,
    )
    return await CompositeRunner(container(request).runner).run(req)


@report_router.post("/reports/composite/polish")
async def polish_composite_report(request: Request, body: CompositePolishBody) -> dict[str, Any]:
    """对已拼装的复合工单报告执行大模型二次润色（标记未经证据校验，保留原版可溯源）。#Created By AiCoding(codex)"""
    if not body.markdown.strip():
        raise bad_request("待润色的报告正文不能为空", "EMPTY_MARKDOWN")
    polished = await CompositeRunner(container(request).runner).polish_markdown(
        body.markdown,
        order=body.order,
        instruction=body.instruction,
    )
    return {"markdown": polished, "verified": False}
