"""异步幂等单飞器（SingleFlight）：合并同键在途并发请求、按成功条件持久化缓存并支持取消平滑接手。

#Created By AiCoding(codex)
供单次填报工作区（tools.call_api）与复合工单共享网关（composite.SharedGatewayClient）统一复用：
1. 同一批并发等待同一个 inflight Future 的协程直接共享当次返回结果（无论成功与否），消除网关报错时的串行重试风暴；
2. 仅当 is_success(result) 为真时才写入持久化缓存 cache，确保后续新轮次仍可正常重试失败接口；
3. 当持有 inflight 的首个协程被单独 cancel 时，未取消的并发等待协程自动平滑接手重调，不误杀同批存活调用。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class IdempotentSingleFlight(Generic[K, V]):
    """异步幂等请求合并与成功结果缓存器。#Created By AiCoding(codex)"""

    def __init__(
        self,
        *,
        is_success: Callable[[V], bool],
        to_cached: Callable[[V], V] | None = None,
    ) -> None:
        self._is_success = is_success
        self._to_cached = to_cached
        self.cache: dict[K, V] = {}
        self.inflight: dict[K, asyncio.Future[V]] = {}

    async def do(self, key: K, loader: Callable[[], Awaitable[V]]) -> tuple[V, bool]:
        """执行或复用 key 对应的异步调用，返回 (结果, 是否来自缓存或并发在途复用)。#Created By AiCoding(codex)"""
        while True:
            if key in self.cache:
                return self.cache[key], True
            inflight = self.inflight.get(key)
            if inflight is None:
                fut: asyncio.Future[V] = asyncio.get_running_loop().create_future()
                self.inflight[key] = fut
                break
            try:
                shared = await asyncio.shield(inflight)
            except asyncio.CancelledError:
                # 若当前任务自身已被取消则向上抛出；若是前序 leader 单独被取消，则由存活协程接手重试
                cur_task = asyncio.current_task()
                if cur_task is None or cur_task.cancelling() > 0:
                    raise
                continue
            return shared, True

        try:
            res = await loader()
            if self._is_success(res):
                self.cache[key] = self._to_cached(res) if self._to_cached is not None else res
            if not fut.done():
                fut.set_result(res)
            return res, False
        except asyncio.CancelledError:
            if not fut.done():
                fut.cancel()
            raise
        except Exception as exc:
            if not fut.done():
                fut.set_exception(exc)
                # 预取一次异常标记，避免无并发 follower 等待时触发 Future exception was never retrieved 告警
                fut.exception()
            raise
        except BaseException:
            if not fut.done():
                fut.cancel()
            raise
        finally:
            if self.inflight.get(key) is fut:
                self.inflight.pop(key, None)
