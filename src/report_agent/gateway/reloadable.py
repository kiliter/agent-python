"""支持运行期热切换底层实例的网关客户端代理。

#Created By AiCoding(codex)
通过引用计数排空机制保证：
  - 新请求立即路由至最新网关实例；
  - 切换瞬间仍在途的异步请求继续使用原实例完成，待最后一个在途请求返回后自动安全关闭旧连接池。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any

from ..domain.api_contract import ApiContract
from .base import ApiCallResult, GatewayClient

log = logging.getLogger(__name__)


@dataclass
class _ClientSlot:
    client: GatewayClient
    in_flight: int = 0
    retired: bool = False
    closed: bool = False


async def _safe_aclose(client: GatewayClient) -> None:
    try:
        await client.aclose()
    except Exception:  # noqa: BLE001
        log.debug("关闭退役网关客户端时忽略异常", exc_info=True)


class ReloadableGatewayClient:
    """实现 GatewayClient 协议的热重载代理客户端。"""

    def __init__(self, initial: GatewayClient) -> None:
        self._lock = threading.Lock()
        self._slot = _ClientSlot(initial)
        self._retired_inflight: list[_ClientSlot] = []
        self._pending_close: list[GatewayClient] = []
        self._closing_tasks: set[asyncio.Task[None]] = set()

    @property
    def current(self) -> GatewayClient:
        """当前生效的底层网关客户端。"""
        with self._lock:
            return self._slot.client

    async def invoke(self, contract: ApiContract, args: dict[str, Any]) -> ApiCallResult:
        with self._lock:
            slot = self._slot
            slot.in_flight += 1
        try:
            return await slot.client.invoke(contract, args)
        finally:
            close_now = False
            with self._lock:
                slot.in_flight -= 1
                if slot.retired and slot.in_flight <= 0 and not slot.closed:
                    slot.closed = True
                    close_now = True
                    if slot in self._retired_inflight:
                        self._retired_inflight.remove(slot)
            if close_now:
                await _safe_aclose(slot.client)

    def swap(self, new_client: GatewayClient) -> GatewayClient | None:
        """原子替换为新的底层网关客户端，并安全退役旧客户端。"""
        immediate_close: GatewayClient | None = None
        with self._lock:
            if new_client is self._slot.client:
                return None
            old_slot = self._slot
            old_slot.retired = True
            self._slot = _ClientSlot(new_client)
            if old_slot.in_flight <= 0 and not old_slot.closed:
                old_slot.closed = True
                immediate_close = old_slot.client
                self._pending_close.append(immediate_close)
            elif not old_slot.closed:
                self._retired_inflight.append(old_slot)

        if immediate_close is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None and not loop.is_closed():
                task = loop.create_task(self.aclose_retired())
                with self._lock:
                    self._closing_tasks.add(task)
                task.add_done_callback(self._discard_task)
        return old_slot.client

    def _discard_task(self, task: asyncio.Task[None]) -> None:
        with self._lock:
            self._closing_tasks.discard(task)

    async def aclose_retired(self) -> None:
        """异步排空并关闭全部已空闲的退役网关客户端。"""
        with self._lock:
            to_close = list(self._pending_close)
            self._pending_close.clear()
        for client in to_close:
            await _safe_aclose(client)

    async def aclose(self) -> None:
        """应用退出时关闭当前客户端与全部退役客户端。"""
        await self.aclose_retired()
        with self._lock:
            tasks = list(self._closing_tasks)
            active_slot = self._slot
            retired_slots = list(self._retired_inflight)
            self._retired_inflight.clear()
            clients_to_close: list[GatewayClient] = []
            if not active_slot.closed:
                active_slot.closed = True
                clients_to_close.append(active_slot.client)
            for s in retired_slots:
                if not s.closed:
                    s.closed = True
                    clients_to_close.append(s.client)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for client in clients_to_close:
            await _safe_aclose(client)
