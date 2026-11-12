"""聊天窗口后台运行管理器：单会话并发互斥、实时步骤广播、断线重放与手动取消。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..domain.resources import ResourceSet
from ..runtime.runner import AgentRunner, InputValidationError, RunRequest, TemplateUnavailable
from ..runtime.workspace import ProcessEvent
from ..store.runs import new_run_id
from .steps import StepMapper, _sanitize_error

log = logging.getLogger(__name__)


@dataclass
class RunCompletion:
    """单次聊天后台运行的终态结果，交由 ChatService 更新会话并生成 final 消息。"""

    run_id: str
    session_id: str
    outcome: dict[str, Any] | None
    error: str | None
    error_code: str | None
    cancelled: bool
    steps: list[dict[str, Any]]
    duration_ms: int


@dataclass
class _RunChannel:
    """单次运行的内存事件通道（运行中实时推送 + 结束后短期重放）。"""

    run_id: str
    session_id: str
    mapper: StepMapper
    cond: asyncio.Condition
    loop: asyncio.AbstractEventLoop
    started_mono: float
    task: asyncio.Task[None] | None = None
    done: bool = False
    finished_mono: float | None = None
    final_message: dict[str, Any] | None = None
    saw_run_failed: bool = False
    notify_scheduled: bool = False
    notify_tasks: set[asyncio.Task[None]] = field(default_factory=set)
    raw_events: list[dict[str, Any]] = field(default_factory=list)


class ChatRunManager:
    """管理聊天窗口触发的智能体后台运行任务、SSE 步骤流订阅与取消。"""

    _MAX_DONE_CHANNELS = 256

    def __init__(self, runner: AgentRunner, keep_done_s: float = 600.0) -> None:
        self.runner = runner
        self.keep_done_s = max(0.0, float(keep_done_s))
        self._channels: OrderedDict[str, _RunChannel] = OrderedDict()
        self._active_by_session: dict[str, str] = {}

    def _evict_expired(self) -> None:
        """按保留时长与最大容量淘汰已结束的历史运行通道。"""
        now = time.monotonic()
        done_ids: list[str] = []
        for rid, ch in list(self._channels.items()):
            if not ch.done:
                continue
            if ch.finished_mono is not None and (now - ch.finished_mono) > self.keep_done_s:
                self._channels.pop(rid, None)
            else:
                done_ids.append(rid)
        overflow = len(done_ids) - self._MAX_DONE_CHANNELS
        for rid in done_ids[: max(0, overflow)]:
            self._channels.pop(rid, None)

    def has_active_run(self, session_id: str) -> str | None:
        """返回该会话当前正在运行的 run_id，无则返回 None。"""
        rid = self._active_by_session.get(session_id)
        if rid is None:
            return None
        if self.is_running(rid):
            return rid
        self._active_by_session.pop(session_id, None)
        return None

    def is_running(self, run_id: str) -> bool:
        """判断指定 run_id 当前是否仍在运行中（含收尾落盘阶段）。"""
        ch = self._channels.get(run_id)
        return bool(ch is not None and not ch.done and ch.task is not None and not ch.task.done())

    def session_for_run(self, run_id: str) -> str | None:
        """返回内存中记录的 run_id -> session_id 映射。"""
        self._evict_expired()
        ch = self._channels.get(run_id)
        return ch.session_id if ch is not None else None

    def get_steps(self, run_id: str) -> list[dict[str, Any]] | None:
        """返回当前已产生的步骤列表副本；通道不存在时返回 None。"""
        self._evict_expired()
        ch = self._channels.get(run_id)
        if ch is None:
            return None
        return [dict(s) for s in ch.mapper.steps]

    def get_raw_events(self, run_id: str) -> list[dict[str, Any]] | None:
        """返回通道中的原始过程事件深拷贝列表；通道不存在时返回 None。#Created By AiCoding(codex)"""
        self._evict_expired()
        ch = self._channels.get(run_id)
        if ch is None:
            return None
        return copy.deepcopy(ch.raw_events)

    def _schedule_notify(self, ch: _RunChannel) -> None:
        """从同步事件监听器安全调度一次异步 Condition.notify_all() 广播。"""
        if ch.done or ch.notify_scheduled:
            return
        ch.notify_scheduled = True

        async def _pulse() -> None:
            try:
                async with ch.cond:
                    ch.notify_scheduled = False
                    ch.cond.notify_all()
            finally:
                ch.notify_scheduled = False

        def _spawn() -> None:
            if ch.done:
                ch.notify_scheduled = False
                return
            t = ch.loop.create_task(_pulse())
            ch.notify_tasks.add(t)
            t.add_done_callback(ch.notify_tasks.discard)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is ch.loop:
            _spawn()
        elif ch.loop.is_running():
            ch.loop.call_soon_threadsafe(_spawn)
        else:
            ch.notify_scheduled = False

    def start(
        self,
        session_id: str,
        req: RunRequest,
        *,
        resources: ResourceSet | None,
        on_complete: Callable[[RunCompletion], Awaitable[dict[str, Any]]],
    ) -> str:
        """校验单会话互斥并启动后台运行，返回 run_id。"""
        if self.has_active_run(session_id) is not None:
            raise RuntimeError("RUN_IN_PROGRESS")
        self._evict_expired()
        if not req.run_id:
            req.run_id = new_run_id()
        run_id = req.run_id

        loop = asyncio.get_running_loop()
        ch = _RunChannel(
            run_id=run_id,
            session_id=session_id,
            mapper=StepMapper(resources=resources),
            cond=asyncio.Condition(),
            loop=loop,
            started_mono=time.monotonic(),
        )
        # 在返回前同步登记活跃通道，杜绝订阅或二次启动请求出现竞态窗口
        self._channels[run_id] = ch
        self._channels.move_to_end(run_id)
        self._active_by_session[session_id] = run_id
        ch.task = loop.create_task(self._execute(ch, req, on_complete), name=f"chat-run-{run_id}")
        return run_id

    async def _execute(
        self,
        ch: _RunChannel,
        req: RunRequest,
        on_complete: Callable[[RunCompletion], Awaitable[dict[str, Any]]],
    ) -> None:
        outcome: dict[str, Any] | None = None
        error: str | None = None
        error_code: str | None = None
        cancelled = False

        def _on_event(ev: ProcessEvent) -> None:
            if ev.type == "run_failed":
                ch.saw_run_failed = True
            ch.raw_events.append(ev.to_dict())
            ch.mapper.feed(ev)
            self._schedule_notify(ch)

        try:
            try:
                outcome = await self.runner.run(req, listener=_on_event)
                status = str(outcome.get("status") or "")
                dur_ms = int(outcome.get("durationMs") or int((time.monotonic() - ch.started_mono) * 1000))
                if status in ("SUCCESS", "PARTIAL"):
                    found_cnt = int(outcome.get("foundCount") or 0)
                    total_cnt = int(outcome.get("totalCount") or 0)
                    ch.mapper.append_custom(
                        "done",
                        f"报告生成完成（找到 {found_cnt}/{total_cnt} 个字段）",
                        ok=True,
                        at_ms=dur_ms,
                    )
                else:
                    error = str(outcome.get("error") or "运行失败")
                    error_code = "RUN_FAILED"
                    if not ch.saw_run_failed:
                        ch.mapper.append_custom(
                            "error",
                            f"运行失败：{_sanitize_error(error)}",
                            ok=False,
                            at_ms=dur_ms,
                        )
            except asyncio.CancelledError:
                cancelled = True
                error = "运行已手动停止"
                error_code = "CANCELLED"
                elapsed = int((time.monotonic() - ch.started_mono) * 1000)
                ch.mapper.append_custom("warn", "运行已手动停止", ok=False, at_ms=elapsed)
            except InputValidationError as exc:
                error = str(exc) or "入参校验不通过"
                error_code = "INPUT_INVALID"
                elapsed = int((time.monotonic() - ch.started_mono) * 1000)
                if not ch.saw_run_failed:
                    ch.mapper.append_custom("error", f"运行失败：{_sanitize_error(exc)}", ok=False, at_ms=elapsed)
            except TemplateUnavailable as exc:
                error = str(exc) or "模板不可用"
                error_code = "TEMPLATE_UNAVAILABLE"
                elapsed = int((time.monotonic() - ch.started_mono) * 1000)
                if not ch.saw_run_failed:
                    ch.mapper.append_custom("error", f"运行失败：{_sanitize_error(exc)}", ok=False, at_ms=elapsed)
            except Exception as exc:  # noqa: BLE001 - 兜底捕获保证会话状态回写与订阅流正常闭合
                log.exception("聊天窗口后台运行未捕获异常 runId=%s", ch.run_id)
                error = str(exc) or type(exc).__name__
                error_code = "RUN_ERROR"
                elapsed = int((time.monotonic() - ch.started_mono) * 1000)
                if not ch.saw_run_failed:
                    ch.mapper.append_custom("error", f"运行失败：{_sanitize_error(exc)}", ok=False, at_ms=elapsed)

            if outcome is not None:
                duration_ms = int(outcome.get("durationMs") or int((time.monotonic() - ch.started_mono) * 1000))
            else:
                duration_ms = int((time.monotonic() - ch.started_mono) * 1000)

            completion = RunCompletion(
                run_id=ch.run_id,
                session_id=ch.session_id,
                outcome=outcome,
                error=error,
                error_code=error_code,
                cancelled=cancelled,
                steps=[dict(s) for s in ch.mapper.steps],
                duration_ms=max(0, duration_ms),
            )

            cb_fut = asyncio.ensure_future(on_complete(completion))
            final_msg: dict[str, Any] | None = None
            try:
                final_msg = await asyncio.shield(cb_fut)
            except asyncio.CancelledError:
                # 收尾阶段若再次收到取消信号，仍等待回调落盘完成以保持会话状态一致
                try:
                    final_msg = await cb_fut
                except Exception:  # noqa: BLE001
                    log.exception("聊天运行完成回调执行失败 runId=%s", ch.run_id)
            except Exception:  # noqa: BLE001
                log.exception("聊天运行完成回调执行失败 runId=%s", ch.run_id)

            ch.final_message = copy.deepcopy(final_msg) if isinstance(final_msg, dict) else None
        finally:
            ch.done = True
            ch.finished_mono = time.monotonic()
            if self._active_by_session.get(ch.session_id) == ch.run_id:
                self._active_by_session.pop(ch.session_id, None)
            self._evict_expired()
            try:
                async with ch.cond:
                    ch.cond.notify_all()
            except asyncio.CancelledError:
                # 兜底用独立脉冲唤醒仍在等待的订阅协程
                async def _final_wake() -> None:
                    async with ch.cond:
                        ch.cond.notify_all()

                t = ch.loop.create_task(_final_wake())
                ch.notify_tasks.add(t)
                t.add_done_callback(ch.notify_tasks.discard)

    def cancel(self, run_id: str) -> bool:
        """若该 run_id 正在运行，取消其后台任务并返回 True；否则返回 False。"""
        ch = self._channels.get(run_id)
        if ch is None or ch.done or ch.task is None or ch.task.done():
            return False
        return ch.task.cancel()

    def subscribe(
        self,
        run_id: str,
        after: int = 0,
        *,
        include_raw: bool = False,
        raw_after: int = 0,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """订阅运行步骤（可选附带原始过程事件）与终态消息；run_id 不在内存通道中时立即抛出 KeyError(run_id)。"""
        self._evict_expired()
        ch = self._channels.get(run_id)
        if ch is None:
            raise KeyError(run_id)
        cursor_init = max(0, int(after))
        raw_cursor_init = max(0, int(raw_after))

        async def _stream() -> AsyncIterator[tuple[str, dict[str, Any]]]:
            cursor = cursor_init
            scan_idx = 0
            raw_cursor = raw_cursor_init
            raw_scan_idx = 0
            while True:
                async with ch.cond:
                    while True:
                        new_steps = [s for s in ch.mapper.steps[scan_idx:] if s["seq"] > cursor]
                        scan_idx = len(ch.mapper.steps)
                        if include_raw:
                            new_raws = [
                                ev for ev in ch.raw_events[raw_scan_idx:]
                                if int(ev.get("seq", 0)) > raw_cursor
                            ]
                            raw_scan_idx = len(ch.raw_events)
                        else:
                            new_raws = []
                        if new_steps or new_raws or ch.done:
                            break
                        await ch.cond.wait()
                    is_done = ch.done
                    final_msg = ch.final_message

                for raw_ev in new_raws:
                    raw_cursor = int(raw_ev.get("seq", raw_cursor))
                    yield ("raw", copy.deepcopy(raw_ev))

                for step in new_steps:
                    cursor = step["seq"]
                    yield ("step", dict(step))

                if is_done:
                    if final_msg is not None:
                        yield ("final", copy.deepcopy(final_msg))
                    return

        return _stream()

    async def aclose(self) -> None:
        """关闭管理器：取消所有在途任务并等待收尾落盘结束。"""
        tasks = [
            ch.task
            for ch in list(self._channels.values())
            if ch.task is not None and not ch.task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        notify_pending = [
            t
            for ch in list(self._channels.values())
            for t in list(ch.notify_tasks)
            if not t.done()
        ]
        if notify_pending:
            await asyncio.gather(*notify_pending, return_exceptions=True)
