"""接口层公共工具：取组件容器、统一错误、共享请求体与资源历史/校验、SSE 推送。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Literal

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..container import Container
from ..domain.resources import Issue
from ..runtime.runner import AgentRunner, InputValidationError, RunRequest, TemplateUnavailable
from ..runtime.workspace import queue_listener
from ..store.fsutil import fmt_time
from ..store.layout import ResourceRef
from ..store.service import ResourceState

log = logging.getLogger(__name__)
_BG_TASKS: set[asyncio.Task[Any]] = set()

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class PublishBody(BaseModel):
    """通用草稿发布请求体。"""

    note: str = ""


class RollbackBody(BaseModel):
    """通用历史版本回退请求体。"""

    targetRev: str
    mode: Literal["draft_only", "publish_now"] = "draft_only"
    reason: str = ""


def container(request: Request) -> Container:
    return request.app.state.container


def operator(request: Request) -> str:
    user = getattr(request.state, "user", None)
    return user.displayName if user else "system"


def bad_request(message: str, code: str = "BAD_REQUEST", **details: Any) -> HTTPException:
    return HTTPException(400, detail={"code": code, "message": message, **details})


def not_found(message: str) -> HTTPException:
    return HTTPException(404, detail={"code": "NOT_FOUND", "message": message})


def parse_expected_revision(raw: Any) -> int | None:
    """校验可选草稿乐观锁版本号（允许 None 或非负整数）。"""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise bad_request("草稿乐观锁版本号 revision 必须是非负整数", "INVALID_REVISION")
    return raw


def check_rollback_reason(body: RollbackBody) -> None:
    """直接回退上线模式（publish_now）强制要求填写回退原因。"""
    if body.mode == "publish_now" and not body.reason.strip():
        raise bad_request("直接回退上线必须填写原因")


def resource_revisions(c: Container, ref: ResourceRef) -> list[dict[str, Any]]:
    """构造指定资源的历史变更版本列表（标出当前线上生效版本）。"""
    online = c.releases.online_change(ref)
    return [
        {
            "rev": e["rev"],
            "type": e.get("type"),
            "operator": e.get("operator"),
            "time": fmt_time(e.get("time")),
            "note": e.get("note") or e.get("summary"),
            "summary": e.get("summary"),
            "online": bool(online and online["rev"] == e["rev"]),
        }
        for e in c.releases.history(ref)
    ]


def validation_result_with_drift(
    issues: list[Issue],
    state: ResourceState,
    **extra: Any,
) -> dict[str, Any]:
    """统一格式化资源校验错误、告警与草稿基线漂移提示。"""
    drift = bool(state.draft and state.online_rev and state.base_rev and state.base_rev != state.online_rev)
    return {
        "errors": [i.to_dict() for i in issues if i.level == "error"],
        "warnings": [i.to_dict() for i in issues if i.level == "warning"],
        "drift": {"baseRev": state.base_rev, "onlineRev": state.online_rev} if drift else None,
        **extra,
    }


def sse_frame(kind: str, data: Any, *, event_id: Any = None) -> str:
    """构造单帧标准 SSE 文本（可选附带 id 字段供断线续接）。"""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    if event_id is not None:
        return f"id: {event_id}\nevent: {kind}\ndata: {payload}\n\n"
    return f"event: {kind}\ndata: {payload}\n\n"


# 保留历史内部别名，兼容外部或测试直接引用
_sse = sse_frame


def sse_run(runner: AgentRunner, req: RunRequest, shape: Callable[[dict[str, Any]], dict[str, Any]]) -> StreamingResponse:
    """以 SSE 推送运行过程事件，最后推送 final（shape 处理后的结果）或 error。
    客户端断开不会取消运行，运行记录照常写入。"""
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

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
            yield sse_frame(kind, data)
            if kind in ("final", "error"):
                break
        await task

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)
