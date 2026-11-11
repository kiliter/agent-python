"""发布版本：索引、物化快照、线上指针、版本血缘。

#Created By AiCoding(codex)
每次发布生成一个新版本 rN：
  - releases/rN/ 是完整资源树（不可变），请求开始时捕获一次，整个运行期间都用它；
  - releases/index.jsonl 记录版本元数据（基准版本、Git 提交、操作人、变更清单）；
  - releases/current 软链接指向线上版本，发布和紧急切换都是原子地改这个链接。
紧急切换到旧版本后再发布，新版本以“当前线上版本”为基准构建，所以每个版本都记录 base，
沿 base 往回走得到的链路就是线上内容的真实来历。
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ..domain.resources import ResourceSet, load_resource_dir
from .fsutil import append_line, atomic_symlink, read_jsonl, write_json
from .git_repo import GitRepo
from .layout import REV_RE, DataLayout, ResourceRef, ensure_within

log = logging.getLogger(__name__)


class ReleaseNotFound(KeyError):
    """版本不存在。"""


class ReleaseStore:
    """发布版本的读取与切换。"""

    def __init__(self, layout: DataLayout, repo: GitRepo, lock: threading.RLock, keep: int = 50) -> None:
        self.layout = layout
        self.repo = repo
        self.lock = lock
        self.keep = keep
        self._entries: list[dict[str, Any]] | None = None
        self._snapshots: OrderedDict[str, ResourceSet] = OrderedDict()
        self._snap_lock = threading.Lock()

    # ------------------------------------------------------------------ 索引
    def entries(self) -> list[dict[str, Any]]:
        """全部版本元数据，按版本号升序。自动跳过损坏或不完整的索引行。"""
        if self._entries is None:
            valid: list[dict[str, Any]] = []
            for item in read_jsonl(self.layout.release_index):
                rev = item.get("rev")
                commit = item.get("commit")
                if not isinstance(rev, str) or not REV_RE.match(rev) or not isinstance(commit, str) or not commit:
                    continue
                try:
                    n = int(item.get("n") or rev[1:])
                except (TypeError, ValueError):
                    continue
                valid.append({**item, "n": n})
            valid.sort(key=lambda e: e["n"])
            self._entries = valid
        return self._entries

    def entry(self, rev: str) -> dict[str, Any]:
        if not isinstance(rev, str) or not REV_RE.match(rev):
            raise ReleaseNotFound(rev)
        for e in self.entries():
            if e["rev"] == rev:
                return e
        raise ReleaseNotFound(rev)

    def has(self, rev: str) -> bool:
        return bool(isinstance(rev, str) and REV_RE.match(rev) and any(e["rev"] == rev for e in self.entries()))

    def next_number(self) -> int:
        return max((int(e["n"]) for e in self.entries()), default=0) + 1

    def live_rev(self) -> str | None:
        """当前线上版本号。"""
        try:
            name = Path(os.readlink(self.layout.current)).name
            return name if REV_RE.match(name) else None
        except (FileNotFoundError, OSError):
            return None

    # ------------------------------------------------------------------ 快照
    def ensure_materialized(self, rev: str) -> Path:
        """确保版本目录存在；已被清理的版本从 Git 提交重新导出（线程安全）。"""
        entry = self.entry(rev)
        path = self.layout.release_dir(rev)
        if path.exists():
            return path
        with self.lock:
            if path.exists():
                return path
            tmp = self.layout.releases / f".restore-{rev}-{os.getpid()}-{secrets.token_hex(4)}"
            try:
                self.repo.export(entry["commit"], tmp)
                write_json(tmp / ".release.json", entry)
                os.replace(tmp, path)
            except BaseException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            log.info("已从 Git 提交 %s 重建发布快照 %s", entry["commit"][:8], rev)
            return path

    def snapshot(self, rev: str) -> ResourceSet:
        """读取某个版本的资源集合（带进程内缓存，版本不可变所以缓存永不过期）。"""
        with self._snap_lock:
            if rev in self._snapshots:
                self._snapshots.move_to_end(rev)
                return self._snapshots[rev]
        rs = load_resource_dir(self.ensure_materialized(rev))
        with self._snap_lock:
            self._snapshots[rev] = rs
            while len(self._snapshots) > 8:
                self._snapshots.popitem(last=False)
        return rs

    def live_snapshot(self) -> tuple[str, ResourceSet]:
        """请求开始时调用一次：返回（线上版本号，资源集合）。"""
        rev = self.live_rev()
        if not rev:
            raise ReleaseNotFound("尚无线上版本")
        return rev, self.snapshot(rev)

    # ------------------------------------------------------------------ 血缘
    def lineage(self, rev: str | None = None) -> list[dict[str, Any]]:
        """从 rev（默认线上版本）沿 base 往回的版本链，最新在前。"""
        rev = rev or self.live_rev()
        by_rev = {e["rev"]: e for e in self.entries()}
        chain: list[dict[str, Any]] = []
        seen: set[str] = set()
        while rev and rev in by_rev and rev not in seen:
            seen.add(rev)
            e = by_rev[rev]
            chain.append(e)
            rev = e.get("base")
        return chain

    def online_change(self, ref: ResourceRef, rev: str | None = None) -> dict[str, Any] | None:
        """线上内容中，该资源最近一次被修改的版本。"""
        for e in self.lineage(rev):
            if any(c["kind"] == ref.kind and c["key"] == ref.key for c in e.get("changes", [])):
                return e
        return None

    def history(self, ref: ResourceRef) -> list[dict[str, Any]]:
        """修改过该资源的全部版本（含紧急切换后被放弃的分支），最新在前。"""
        return [e for e in reversed(self.entries())
                if any(c["kind"] == ref.kind and c["key"] == ref.key for c in e.get("changes", []))]

    def read_file_at(self, rev: str, rel_path: str) -> str | None:
        """读取某版本中的一个文件。"""
        entry = self.entry(rev)
        rel_dir = self.layout.release_dir(rev)
        path = ensure_within(rel_dir, rel_dir / rel_path)
        if path.is_file():
            return path.read_text(encoding="utf-8")
        data = self.repo.show(entry["commit"], rel_path)
        return data.decode("utf-8") if data is not None else None

    # ------------------------------------------------------------------ 写入（调用方持有写锁）
    def add(self, entry: dict[str, Any], built_dir: Path) -> None:
        """登记新版本并切换为线上版本。"""
        final = self.layout.release_dir(entry["rev"])
        write_json(built_dir / ".release.json", entry)
        os.replace(built_dir, final)
        append_line(self.layout.release_index, _dumps(entry))
        self._entries = None
        atomic_symlink(entry["rev"], self.layout.current)

    def switch(self, rev: str) -> None:
        """紧急切换线上版本。"""
        self.ensure_materialized(rev)
        atomic_symlink(rev, self.layout.current)

    def prune(self) -> None:
        """只保留最近 keep 个版本目录和线上版本目录，更早的可随时从 Git 恢复。"""
        live = self.live_rev()
        revs = [e["rev"] for e in self.entries()]
        keep = set(revs[-self.keep:]) | ({live} if live else set())
        for rev in revs:
            path = self.layout.release_dir(rev)
            if rev not in keep and path.exists():
                shutil.rmtree(path, ignore_errors=True)

    def recover(self) -> None:
        """启动时清理未完成的构建目录与临时草稿目录，并确保线上版本目录存在。"""
        for tmp in self.layout.releases.glob(".build-*"):
            shutil.rmtree(tmp, ignore_errors=True)
        for tmp in self.layout.releases.glob(".restore-*"):
            shutil.rmtree(tmp, ignore_errors=True)
        if self.layout.drafts.exists():
            for kind_dir in self.layout.drafts.iterdir():
                if not kind_dir.is_dir():
                    continue
                for tmp in kind_dir.iterdir():
                    if tmp.name.startswith(".") and (tmp.name.endswith(".tmp") or tmp.name.endswith(".bak")):
                        shutil.rmtree(tmp, ignore_errors=True)
        live = self.live_rev()
        if live and self.has(live):
            self.ensure_materialized(live)
        elif self.entries():
            last = self.entries()[-1]["rev"]
            log.warning("线上指针缺失或无效，指向最新版本 %s", last)
            self.switch(last)


def _dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
