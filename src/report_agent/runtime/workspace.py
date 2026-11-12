"""一次运行的工作区：接口结果、工具调用记录、过程事件。

#Created By AiCoding(codex)
接口完整结果只存在工作区，模型拿到的是摘要和 resultId，需要细看时用 query_result 读取。
证据校验时根据 resultId / row / column / callId 回到工作区核对原文。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ApiResult:
    """一次 call_api 的完整结果。"""

    result_id: str
    api: str
    title: str
    args: dict[str, Any]
    ok: bool
    error: str | None
    columns: dict[str, str]
    records: list[dict[str, str]]
    cost_ms: int
    raw: str = ""
    request_preview: str = ""
    no_data: bool = False

    def to_dict(self, with_raw: bool = False) -> dict[str, Any]:
        d = {"resultId": self.result_id, "api": self.api, "title": self.title, "args": dict(self.args), "ok": self.ok,
             "error": self.error, "columns": dict(self.columns),
             "records": [{**r, "row": i} for i, r in enumerate(self.records)],
             "costMs": self.cost_ms, "noData": self.no_data, "requestPreview": self.request_preview}
        if with_raw:
            d["raw"] = self.raw
        return d


@dataclass
class ToolCall:
    """一次平台工具调用。"""

    call_id: str
    tool: str
    args: dict[str, Any]
    output: Any
    at_ms: int
    ok: bool = True


@dataclass
class ProcessEvent:
    """推送给前端的过程事件。"""

    seq: int
    type: str
    at_ms: int
    round: int
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {**self.data, "seq": self.seq, "type": self.type, "atMs": self.at_ms, "round": self.round}


class EventSink:
    """收集过程事件；可选地同时投递到异步队列（SSE）。"""

    def __init__(self, listener: Callable[[ProcessEvent], None] | None = None) -> None:
        self.events: list[ProcessEvent] = []
        self.started = time.monotonic()
        self.round = 0
        self._listener = listener

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

    def emit(self, type_: str, **data: Any) -> ProcessEvent:
        ev = ProcessEvent(seq=len(self.events) + 1, type=type_, at_ms=self.elapsed_ms(), round=self.round, data=data)
        self.events.append(ev)
        if self._listener is not None:
            try:
                self._listener(ev)
            except Exception:  # noqa: BLE001 - 推送失败不影响运行
                pass
        return ev


def queue_listener(queue: asyncio.Queue) -> Callable[[ProcessEvent], None]:
    """把事件放入队列的监听器（SSE 用）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    def _put(item: tuple[str, dict[str, Any]]) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            pass

    def _listen(ev: ProcessEvent) -> None:
        item = ("event", ev.to_dict())
        if loop is not None and not loop.is_closed() and loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                _put(item)
                return
            try:
                loop.call_soon_threadsafe(_put, item)
                return
            except RuntimeError:
                pass
        _put(item)

    return _listen


@dataclass
class Workspace:
    """运行期间的全部中间数据。"""

    results: dict[str, ApiResult] = field(default_factory=dict)
    tool_calls: dict[str, ToolCall] = field(default_factory=dict)
    loaded_skills: list[str] = field(default_factory=list)
    validation_rounds: list[list[dict[str, str]]] = field(default_factory=list)
    _result_seq: int = 0
    _call_seq: int = 0
    _idempotent_cache: dict[tuple[str, str], ApiResult] = field(default_factory=dict, repr=False)
    _idempotent_inflight: dict[tuple[str, str], asyncio.Future[ApiResult]] = field(default_factory=dict, repr=False)
    _doc_index: Any = field(default=None, repr=False)
    _doc_index_source: str | None = field(default=None, repr=False)

    def next_result_id(self) -> str:
        self._result_seq += 1
        return f"r{self._result_seq}"

    def next_call_id(self) -> str:
        self._call_seq += 1
        return f"t{self._call_seq}"

    def add_result(self, result: ApiResult) -> None:
        result.args = dict(result.args or {})
        self.results[result.result_id] = result

    def record_call(self, tool: str, args: dict[str, Any], output: Any, at_ms: int, ok: bool = True) -> ToolCall:
        call = ToolCall(call_id=self.next_call_id(), tool=tool, args=dict(args or {}), output=output,
                        at_ms=max(0, at_ms), ok=ok)
        self.tool_calls[call.call_id] = call
        return call
