"""嵌入式聊天选模板窗口接口路由（/api/v1/chat/*）。

#Created By AiCoding(codex)
严格对应 docs/chat-embed-api.md §2 与 §4。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..chat.service import ChatCaller, ChatError, ChatService
from .auth import require_report_key, verify_request_user
from .common import SSE_HEADERS, container, sse_frame

log = logging.getLogger(__name__)

chat_router = APIRouter(prefix="/api/v1/chat", tags=["聊天窗口"])

_KEEPALIVE_S = 15.0
_EOF = object()


def _verify_admin_caller(request: Request) -> ChatCaller | None:
    verified = verify_request_user(request)
    if verified is None:
        return None
    user, _ = verified
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


def _extract_expected_sid(request: Request, session_id_query: str | None = None) -> str | None:
    """从可选请求头 X-Chat-Session-Id 或查询参数 sessionId 提取预期会话 ID，防止跨会话越权。#Created By AiCoding(codex)"""
    hdr_sid = (request.headers.get("x-chat-session-id") or "").strip()
    qry_sid = (session_id_query or "").strip()
    if hdr_sid and qry_sid and hdr_sid != qry_sid:
        raise ChatError(404, "RUN_NOT_FOUND", "运行记录不存在")
    return hdr_sid or qry_sid or None


def _sse_chat_stream(
    source_factory: Callable[[], AsyncIterator[tuple[str, Any]]],
    *,
    task_name: str,
    log_label: str,
    terminal_kinds: frozenset[str],
    with_step_id: bool = False,
) -> StreamingResponse:
    """将聊天服务的异步事件迭代器包装为带心跳保活、统一异常帧与断连取消清理的 SSE 响应。"""
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for kind, data in source_factory():
                await queue.put((kind, data))
        except asyncio.CancelledError:
            raise
        except ChatError as exc:
            await queue.put(("error", {"code": exc.code, "message": exc.message, **exc.details}))
        except Exception:  # noqa: BLE001
            log.exception("聊天 SSE 流异常 %s", log_label)
            await queue.put(("error", {"code": "INTERNAL_ERROR", "message": "服务内部错误，请稍后重试"}))
        finally:
            await queue.put(_EOF)

    task = asyncio.create_task(pump(), name=task_name)

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
                if with_step_id and kind == "step" and isinstance(data, dict):
                    yield sse_frame("step", data, event_id=data.get("seq", ""))
                else:
                    yield sse_frame(kind, data)
                if kind in terminal_kinds:
                    break
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


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


@chat_router.post("/sessions/{sid}/compact")
async def compact_chat_session(
    request: Request,
    sid: str,
    caller: ChatCaller = Depends(require_chat_caller),
) -> dict[str, Any]:
    """手动触发对话上下文滚动压缩（保留最近原文消息，归档更早对话为记忆摘要）。"""
    return await _chat(request).compact_session(sid, caller=caller)


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
    return _sse_chat_stream(
        lambda: svc.send_message(sid, body.text, auto=body.auto, caller=caller),
        task_name=f"chat-msg-{sid[:8]}",
        log_label=f"sid={sid}",
        terminal_kinds=frozenset({"done"}),
    )


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

    return _sse_chat_stream(
        lambda: svc.stream_events(
            run_id,
            after=effective_after,
            include_raw=includeRaw,
            raw_after=effective_raw_after,
            caller=caller,
            expected_sid=expected_sid,
        ),
        task_name=f"chat-events-{run_id[:12]}",
        log_label=f"runId={run_id}",
        terminal_kinds=frozenset({"final", "error"}),
        with_step_id=True,
    )


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
