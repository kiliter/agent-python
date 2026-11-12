"""聊天窗口会话存储：DATA_DIR/chats/<sid[:2]>/<sid>.json 原子落盘、LRU 缓存与会话级协程锁。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import threading
import time
import weakref
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ..store.fsutil import now_iso, read_json, write_json
from ..store.layout import InvalidResource, ensure_within

log = logging.getLogger(__name__)

SESSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_STRIPE_COUNT = 64


class _SessionLock(asyncio.Lock):
    """支持弱引用的会话级协程互斥锁，保证在途持有或等待中的锁绝不被提前回收。"""


def session_id_for(user_id: str, order_id: str) -> str:
    """按 (userId, orderId) 计算稳定的 32 位小写十六进制会话标识。"""
    u = ("" if user_id is None else str(user_id)).strip()
    o = ("" if order_id is None else str(order_id)).strip()
    return hashlib.sha256(f"{u}\x00{o}".encode("utf-8")).hexdigest()[:32]


def inputs_fingerprint(inputs: dict[str, str], document: str) -> str:
    """对清洗后的非空 inputs（排序键值）与 document 计算稳定 SHA-256 hex。"""
    cleaned: dict[str, str] = {}
    for raw_k, raw_v in (inputs or {}).items():
        key = ("" if raw_k is None else str(raw_k)).strip()
        if not key:
            continue
        val = ("" if raw_v is None else str(raw_v)).strip()
        if val:
            cleaned[key] = val
    doc = "" if document is None else str(document)
    payload = json.dumps(
        {"inputs": cleaned, "document": doc},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ChatStore:
    """聊天会话的文件化持久化存储与内存 LRU 缓存。

    锁顺序约定：若同时需要分片文件锁与缓存锁，必须先获取 `_stripe_lock(sid)` 再获取 `_cache_guard`。
    """

    def __init__(self, root: Path, max_cache: int = 256) -> None:
        self.root = root.resolve()
        self.max_cache = max(1, int(max_cache))
        self._max_recent_locks = max(256, self.max_cache * 2)
        self._stripe_locks = tuple(threading.Lock() for _ in range(_STRIPE_COUNT))
        self._cache_guard = threading.RLock()
        self._op_seq = 0
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._locks_weak: weakref.WeakValueDictionary[str, _SessionLock] = weakref.WeakValueDictionary()
        self._locks_recent: OrderedDict[str, _SessionLock] = OrderedDict()

    def _stripe_lock(self, session_id: str) -> threading.Lock:
        return self._stripe_locks[hash(session_id) & (_STRIPE_COUNT - 1)]

    def _is_session_locked(self, session_id: str) -> bool:
        with self._cache_guard:
            lock = self._locks_weak.get(session_id)
            return bool(lock is not None and lock.locked())

    def lock_for(self, session_id: str) -> asyncio.Lock:
        """获取指定 sessionId 对应的协程互斥锁（有界保留最近常用锁，弱引用兜底防止在途锁重复创建）。"""
        key = "" if session_id is None else str(session_id)
        with self._cache_guard:
            lock = self._locks_weak.get(key)
            if lock is None:
                lock = _SessionLock()
                self._locks_weak[key] = lock
            self._locks_recent[key] = lock
            self._locks_recent.move_to_end(key)
            while len(self._locks_recent) > self._max_recent_locks:
                self._locks_recent.popitem(last=False)
            return lock

    def _resolve_path(self, session_id: str) -> Path | None:
        """校验 SESSION_ID_RE 与路径边界，返回会话 JSON 路径；非法标识返回 None。"""
        if not isinstance(session_id, str) or not SESSION_ID_RE.match(session_id):
            return None
        try:
            shard = ensure_within(self.root, self.root / session_id[:2])
            return ensure_within(shard, shard / f"{session_id}.json")
        except InvalidResource:
            return None

    def _put_cache_locked(self, session_id: str, snapshot: dict[str, Any]) -> None:
        self._cache[session_id] = snapshot
        self._cache.move_to_end(session_id)
        while len(self._cache) > self.max_cache:
            self._cache.popitem(last=False)

    def _try_get_cached(self, session_id: str) -> tuple[dict[str, Any] | None, int]:
        with self._cache_guard:
            cached = self._cache.get(session_id)
            if cached is not None:
                self._cache.move_to_end(session_id)
                return copy.deepcopy(cached), self._op_seq
            return None, self._op_seq

    def _finish_disk_load(self, session_id: str, raw: Any, seq_before: int) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        with self._cache_guard:
            # 读盘期间若并发 save 已写入更新快照，直接以最新缓存为准
            newer = self._cache.get(session_id)
            if newer is not None:
                self._cache.move_to_end(session_id)
                return copy.deepcopy(newer)
            # 仅在读盘期间未发生并发写/清理操作时回填缓存，杜绝过期脏数据复活
            if self._op_seq == seq_before:
                self._put_cache_locked(session_id, raw)
        return copy.deepcopy(raw)

    def get(self, session_id: str) -> dict[str, Any] | None:
        """按 sessionId 读取会话，返回深拷贝副本防止调用方原地污染缓存。"""
        path = self._resolve_path(session_id)
        if path is None:
            return None
        hit, seq_before = self._try_get_cached(session_id)
        if hit is not None:
            return hit
        raw = read_json(path)
        return self._finish_disk_load(session_id, raw, seq_before)

    async def aget(self, session_id: str) -> dict[str, Any] | None:
        """异步按 sessionId 读取会话：命中内存缓存时零线程切换直接返回，未命中时卸载磁盘 I/O 到工作线程。"""
        path = self._resolve_path(session_id)
        if path is None:
            return None
        hit, seq_before = self._try_get_cached(session_id)
        if hit is not None:
            return hit
        raw = await asyncio.to_thread(read_json, path)
        return self._finish_disk_load(session_id, raw, seq_before)

    def get_by_pair(self, user_id: str, order_id: str) -> dict[str, Any] | None:
        """按 (userId, orderId) 读取会话。"""
        return self.get(session_id_for(user_id, order_id))

    def has_run_id(self, session_id: str, run_id: str) -> bool:
        """只读探测会话是否包含指定 runId（冷文件扫描时先做原文子串快速过滤，不污染 LRU 缓存且免 deepcopy）。"""
        if not run_id:
            return False
        path = self._resolve_path(session_id)
        if path is None:
            return False
        with self._cache_guard:
            cached = self._cache.get(session_id)
            if cached is not None:
                return any(
                    isinstance(m, dict) and m.get("kind") == "run" and m.get("runId") == run_id
                    for m in (cached.get("messages") or [])
                )
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        if run_id not in text and json.dumps(run_id) not in text:
            return False
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return False
        if not isinstance(raw, dict):
            return False
        return any(
            isinstance(m, dict) and m.get("kind") == "run" and m.get("runId") == run_id
            for m in (raw.get("messages") or [])
        )

    def _prepare_save(self, session: dict[str, Any]) -> tuple[str, Path, dict[str, Any]]:
        if not isinstance(session, dict):
            raise InvalidResource("会话内容必须是字典对象")
        sid = session.get("sessionId")
        path = self._resolve_path(sid) if isinstance(sid, str) else None
        if path is None or not isinstance(sid, str):
            raise InvalidResource(f"会话标识「{sid}」格式不合法")
        session["updatedAt"] = now_iso()
        return sid, path, copy.deepcopy(session)

    def _write_and_cache(self, sid: str, path: Path, snapshot: dict[str, Any]) -> None:
        with self._stripe_lock(sid):
            write_json(path, snapshot)
            with self._cache_guard:
                self._op_seq += 1
                self._put_cache_locked(sid, snapshot)

    def save(self, session: dict[str, Any]) -> dict[str, Any]:
        """更新 updatedAt 后原子落盘并刷新 LRU 缓存，返回保存后的深拷贝副本。"""
        sid, path, snapshot = self._prepare_save(session)
        self._write_and_cache(sid, path, snapshot)
        return copy.deepcopy(snapshot)

    async def asave(self, session: dict[str, Any]) -> dict[str, Any]:
        """异步原子落盘会话（将 fsync + os.replace 卸载到工作线程，避免阻塞事件循环）。"""
        sid, path, snapshot = self._prepare_save(session)
        await asyncio.to_thread(self._write_and_cache, sid, path, snapshot)
        return copy.deepcopy(snapshot)

    def cleanup(self, keep_days: int) -> int:
        """清理 mtime 早于 keep_days 天的会话文件及对应缓存、空分片目录，返回删除文件数。"""
        if keep_days <= 0 or not self.root.exists():
            return 0
        cutoff = time.time() - keep_days * 86400
        removed = 0
        try:
            shards = list(self.root.iterdir())
        except OSError:
            return 0

        for shard in shards:
            if shard.is_symlink() or not shard.is_dir():
                continue
            try:
                entries = list(shard.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.is_symlink() or not entry.is_file():
                    continue
                if entry.name.startswith(".") or not entry.name.endswith(".json"):
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if mtime >= cutoff:
                    continue
                sid = entry.name[:-5]
                if self._is_session_locked(sid):
                    continue
                with self._stripe_lock(sid):
                    if self._is_session_locked(sid):
                        continue
                    try:
                        if entry.stat().st_mtime >= cutoff:
                            continue
                        entry.unlink(missing_ok=True)
                    except OSError:
                        continue
                    with self._cache_guard:
                        self._op_seq += 1
                        self._cache.pop(sid, None)
                        lock = self._locks_weak.get(sid)
                        if lock is None or not lock.locked():
                            self._locks_recent.pop(sid, None)
                    removed += 1
            try:
                if not any(shard.iterdir()):
                    shard.rmdir()
            except OSError:
                pass
        return removed
