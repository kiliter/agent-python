"""嵌入式聊天选模板窗口接口路由（/api/v1/chat/*）。

#Created By AiCoding(codex)
严格对应 docs/chat-embed-api.md §2 与 §4。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..chat.service import ChatCaller, ChatError, ChatService
from .auth import TokenService, require_report_key, token_from_request
from .common import _sse, container

log = logging.getLogger(__name__)

chat_router = APIRouter(prefix="/api/v1/chat", tags=["聊天窗口"])

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
_KEEPALIVE_S = 15.0
_EOF = object()


def _verify_admin_caller(request: Request) -> ChatCaller | None:
    tokens: TokenService = request.app.state.tokens
    token = token_from_request(request)
    verified = tokens.verify(token) if token else None
    if verified is None:
        return None
    user, payload = verified
    request.state.user = user
    request.state.token_payload = payload
    return ChatCaller(kind="user", name=user.displayName or user.username)


def require_chat_caller(request: Request) -> ChatCaller:
    """聊天接口双轨鉴权：显式携带非空 X-API-Key 时先校验 Key 有效性再识别管理端身份；未携带时优先识别管理端登录态。"""
    explicit_key = request.headers.get("x-api-key", "").strip()
    if explicit_key:
        require_report_key(request)
        admin_caller = _verify_admin_caller(request)
        if admin_caller is not None:
            return admin_caller
        return ChatCaller(kind="key", name="chat-embed")

    admin_caller = _verify_admin_caller(request)
    if admin_caller is not None:
        return admin_caller
    require_report_key(request)
    return ChatCaller(kind="key", name="chat-embed")


def _chat(request: Request) -> ChatService:
    svc = container(request).chat
    if svc is None:
        raise RuntimeError("ChatService 尚未初始化")
    return svc


def _sse_with_id(event_id: Any, kind: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"id: {event_id}\nevent: {kind}\ndata: {payload}\n\n"


def _extract_expected_sid(request: Request, session_id_query: str | None = None) -> str | None:
    """从可选请求头 X-Chat-Session-Id 或查询参数 sessionId 提取预期会话 ID，防止跨会话越权。#Created By AiCoding(codex)"""
    hdr_sid = (request.headers.get("x-chat-session-id") or "").strip()
    qry_sid = (session_id_query or "").strip()
    if hdr_sid and qry_sid and hdr_sid != qry_sid:
        raise ChatError(404, "RUN_NOT_FOUND", "运行记录不存在")
    return hdr_sid or qry_sid or None


# ============================================================================ 请求体模型
class OpenSessionBody(BaseModel):
    userId: str = ""
    orderId: str = ""
    inputs: dict[str, Any] | None = Field(default_factory=dict)
    document: str | None = ""
    target: str | None = "online"


class SendMessageBody(BaseModel):
    text: str = ""
    auto: bool = False


class StartRunBody(BaseModel):
    templateId: int
    inputs: dict[str, Any] | None = None


class ConfirmRunBody(BaseModel):
    markdown: str
    acknowledgePartial: bool = False


# ============================================================================ 路由定义
@chat_router.post("/sessions")
async def open_chat_session(
    request: Request,
    body: OpenSessionBody,
    caller: ChatCaller = Depends(require_chat_caller),
) -> dict[str, Any]:
    """创建或恢复 (userId, orderId) 对应的聊天会话。"""
    return await _chat(request).open_session(
        body.userId,
        body.orderId,
        body.inputs,
        body.document,
        body.target or "online",
        caller=caller,
    )


@chat_router.get("/sessions/{sid}")
async def get_chat_session(
    request: Request,
    sid: str,
    caller: ChatCaller = Depends(require_chat_caller),
) -> dict[str, Any]:
    """读取指定聊天会话快照。"""
    return await _chat(request).get_session_view(sid, caller=caller)


@chat_router.post("/sessions/{sid}/messages")
async def send_chat_message(
    request: Request,
    sid: str,
    body: SendMessageBody,
    caller: ChatCaller = Depends(require_chat_caller),
) -> StreamingResponse:
    """发送用户聊天消息或触发打开时自动推荐（SSE：status / message / error / done）。"""
    svc = _chat(request)
    await svc.precheck_message(sid, body.text, auto=body.auto, caller=caller)

    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for kind, data in svc.send_message(sid, body.text, auto=body.auto, caller=caller):
                await queue.put((kind, data))
        except asyncio.CancelledError:
            raise
        except ChatError as exc:
            await queue.put(("error", {"code": exc.code, "message": exc.message, **exc.details}))
        except Exception as exc:  # noqa: BLE001
            log.exception("聊天消息 SSE 流异常 sid=%s", sid)
            await queue.put(("error", {"code": "INTERNAL_ERROR", "message": f"{type(exc).__name__}: {exc}"}))
        finally:
            await queue.put(_EOF)

    task = asyncio.create_task(pump(), name=f"chat-msg-{sid[:8]}")

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_S)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is _EOF:
                    break
                kind, data = item
                yield _sse(kind, data)
                if kind == "done":
                    break
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@chat_router.get("/sessions/{sid}/templates")
async def list_chat_templates(
    request: Request,
    sid: str,
    q: str = "",
    caller: ChatCaller = Depends(require_chat_caller),
) -> list[dict[str, Any]]:
    """获取换模板弹窗的模板列表（推荐模板排前，附带本会话最近运行状态）。"""
    return await _chat(request).list_templates(sid, q=q, caller=caller)


@chat_router.get("/sessions/{sid}/templates/{template_id}")
async def get_chat_template_preview(
    request: Request,
    sid: str,
    template_id: int,
    caller: ChatCaller = Depends(require_chat_caller),
) -> dict[str, Any]:
    """获取指定模板的结构详情、入参当前值、可见字段说明与样例填充预览。#Created By AiCoding(codex)"""
    return await _chat(request).get_template_preview(sid, template_id, caller=caller)


@chat_router.post("/sessions/{sid}/runs")
async def start_chat_run(
    request: Request,
    sid: str,
    body: StartRunBody,
    caller: ChatCaller = Depends(require_chat_caller),
) -> dict[str, Any]:
    """发起指定模板填报运行（缺参时返回 ask_params 卡片，齐全时启动后台任务并返回 RUNNING 卡片）。"""
    msg, session = await _chat(request).start_run(
        sid,
        body.templateId,
        body.inputs,
        caller=caller,
    )
    return {"message": msg, "session": session}


@chat_router.get("/runs/{run_id}/raw")
async def get_chat_run_raw_events(
    request: Request,
    run_id: str,
    sessionId: str | None = None,
    caller: ChatCaller = Depends(require_chat_caller),
) -> dict[str, Any]:
    """按需拉取某次运行的原始过程事件（优先内存通道，淘汰后回退 RunStore）。#Created By AiCoding(codex)"""
    expected_sid = _extract_expected_sid(request, sessionId)
    return await _chat(request).get_run_raw_events(run_id, caller=caller, expected_sid=expected_sid)


@chat_router.get("/runs/{run_id}/events")
async def stream_chat_run_events(
    request: Request,
    run_id: str,
    after: int = 0,
    includeRaw: bool = False,
    rawAfter: int = 0,
    sessionId: str | None = None,
    caller: ChatCaller = Depends(require_chat_caller),
) -> StreamingResponse:
    """订阅运行过程步骤事件流（支持 ?after=N、Last-Event-ID 断线续接及 includeRaw 原样过程事件流）。"""
    svc = _chat(request)
    expected_sid = _extract_expected_sid(request, sessionId)
    await svc.resolve_session_for_run(run_id, caller=caller, expected_sid=expected_sid)

    effective_after = max(0, int(after))
    effective_raw_after = max(0, int(rawAfter))
    raw_last_id = (request.headers.get("last-event-id") or "").strip()
    if raw_last_id:
        try:
            effective_after = max(effective_after, int(raw_last_id))
        except ValueError:
            pass

    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for kind, data in svc.stream_events(
                run_id,
                after=effective_after,
                include_raw=includeRaw,
                raw_after=effective_raw_after,
                caller=caller,
                expected_sid=expected_sid,
            ):
                await queue.put((kind, data))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("聊天运行事件 SSE 流异常 runId=%s", run_id)
        finally:
            await queue.put(_EOF)

    task = asyncio.create_task(pump(), name=f"chat-events-{run_id[:12]}")

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_S)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is _EOF:
                    break
                kind, data = item
                if kind == "step":
                    yield _sse_with_id(data.get("seq", ""), "step", data)
                elif kind == "raw":
                    yield _sse("raw", data)
                elif kind == "final":
                    yield _sse("final", data)
                    break
                else:
                    yield _sse(kind, data)
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@chat_router.post("/runs/{run_id}/cancel")
async def cancel_chat_run(
    request: Request,
    run_id: str,
    sessionId: str | None = None,
    caller: ChatCaller = Depends(require_chat_caller),
) -> dict[str, Any]:
    """手动停止正在进行的模板填报运行。"""
    expected_sid = _extract_expected_sid(request, sessionId)
    return await _chat(request).cancel_run(run_id, caller=caller, expected_sid=expected_sid)


@chat_router.post("/runs/{run_id}/confirm")
async def confirm_chat_run(
    request: Request,
    run_id: str,
    body: ConfirmRunBody,
    sessionId: str | None = None,
    caller: ChatCaller = Depends(require_chat_caller),
) -> dict[str, Any]:
    """确认采用某次运行的报告内容并生成父页面回传 payload。"""
    expected_sid = _extract_expected_sid(request, sessionId)
    return await _chat(request).confirm_run(
        run_id,
        body.markdown,
        acknowledge_partial=body.acknowledgePartial,
        caller=caller,
        expected_sid=expected_sid,
    )
