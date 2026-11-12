"""接口层公共工具：取组件容器、统一错误、SSE 推送。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from ..container import Container
from ..runtime.runner import AgentRunner, InputValidationError, RunRequest, TemplateUnavailable
from ..runtime.workspace import queue_listener

log = logging.getLogger(__name__)
_BG_TASKS: set[asyncio.Task[Any]] = set()


def container(request: Request) -> Container:
    return request.app.state.container


def operator(request: Request) -> str:
    user = getattr(request.state, "user", None)
    return user.displayName if user else "system"


def bad_request(message: str, code: str = "BAD_REQUEST", **details: Any) -> HTTPException:
    return HTTPException(400, detail={"code": code, "message": message, **details})


def not_found(message: str) -> HTTPException:
    return HTTPException(404, detail={"code": "NOT_FOUND", "message": message})


def _sse(kind: str, data: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def sse_run(runner: AgentRunner, req: RunRequest, shape: Callable[[dict[str, Any]], dict[str, Any]]) -> StreamingResponse:
    """以 SSE 推送运行过程事件，最后推送 final（shape 处理后的结果）或 error。
    客户端断开不会取消运行，运行记录照常写入。"""
    queue: asyncio.Queue = asyncio.Queue()

    async def worker() -> None:
        try:
            out = await runner.run(req, listener=queue_listener(queue))
            await queue.put(("final", shape(out)))
        except InputValidationError as exc:
            await queue.put(("error", {"code": "INVALID_INPUT", "message": str(exc), "errors": exc.errors}))
        except TemplateUnavailable as exc:
            await queue.put(("error", {"code": "TEMPLATE_UNAVAILABLE", "message": str(exc)}))
        except Exception as exc:  # noqa: BLE001
            log.exception("SSE 运行异常")
            await queue.put(("error", {"code": "INTERNAL_ERROR", "message": f"{type(exc).__name__}: {exc}"}))

    task = asyncio.create_task(worker())
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)

    async def gen():
        yield ": connected\n\n"
        while True:
            try:
                kind, data = await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield _sse(kind, data)
            if kind in ("final", "error"):
                break
        await task

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
