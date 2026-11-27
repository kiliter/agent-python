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
import re
import secrets
import shutil
import threading
from collections import OrderedDict, defaultdict
from contextlib import suppress
from pathlib import Path
from typing import Any

from ..domain.resources import ResourceSet, load_resource_dir
from .fsutil import (
    append_jsonl,
    atomic_symlink,
    atomic_write_bytes,
    read_json,
    read_jsonl,
    unlink_or_rmtree,
    write_json,
)
from .git_repo import GitRepo
from .layout import META_FILE, REV_RE, DataLayout, ResourceRef, ensure_within, is_valid_resource_key

log = logging.getLogger(__name__)
_DRAFT_TMP_RE = re.compile(r"^\.(?P<key>.+)\.[0-9]+\.[0-9a-fA-F]+\.(?P<ext>tmp|bak)$")


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
        self._by_rev: dict[str, dict[str, Any]] | None = None
        self._entries_sig: tuple[int, int] | None = None
        self._snapshots: OrderedDict[str, ResourceSet] = OrderedDict()
        self._loading_revs: dict[str, int] = {}
        self._snap_lock = threading.Lock()

    def _index_sig(self) -> tuple[int, int]:
        try:
            st = self.layout.release_index.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return (0, -1)

    def _invalidate_entries_cache(self) -> None:
        self._entries = None
        self._by_rev = None
        self._entries_sig = None

    def _ensure_entries_loaded(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        sig = self._index_sig()
        if self._entries is None or self._by_rev is None or self._entries_sig != sig:
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
            self._by_rev = {e["rev"]: e for e in valid}
            self._entries_sig = sig
        return self._entries, self._by_rev

    # ------------------------------------------------------------------ 索引
    def entries(self) -> list[dict[str, Any]]:
        """全部版本元数据，按版本号升序。自动跳过损坏或不完整的索引行。"""
        with self.lock:
            entries, _ = self._ensure_entries_loaded()
            return list(entries)

    def entry(self, rev: str) -> dict[str, Any]:
        if not isinstance(rev, str) or not REV_RE.match(rev):
            raise ReleaseNotFound(rev)
        with self.lock:
            _, by_rev = self._ensure_entries_loaded()
            found = by_rev.get(rev)
            if found is None:
                raise ReleaseNotFound(rev)
            return dict(found)

    def has(self, rev: str) -> bool:
        if not isinstance(rev, str) or not REV_RE.match(rev):
            return False
        with self.lock:
            _, by_rev = self._ensure_entries_loaded()
            return rev in by_rev

    def next_number(self) -> int:
        with self.lock:
            entries, _ = self._ensure_entries_loaded()
            return (int(entries[-1]["n"]) if entries else 0) + 1

    def live_rev(self) -> str | None:
        """当前线上版本号。"""
        try:
            name = Path(os.readlink(self.layout.current)).name
            return name if REV_RE.match(name) else None
        except (FileNotFoundError, OSError):
            return None

    # ------------------------------------------------------------------ 快照
    def ensure_materialized(self, rev: str) -> Path:
        """确保版本目录完整存在；已被清理或缺失 .release.json 的版本从 Git 提交重新导出（线程安全）。"""
        entry = self.entry(rev)
        path = self.layout.release_dir(rev)
        if (path / ".release.json").is_file():
            return path
        with self.lock:
            if (path / ".release.json").is_file():
                return path
            tmp = self.layout.releases / f".restore-{rev}-{os.getpid()}-{secrets.token_hex(4)}"
            try:
                self.repo.export(entry["commit"], tmp)
                write_json(tmp / ".release.json", entry)
                if os.path.lexists(path):
                    unlink_or_rmtree(path, ignore_errors=True)
                os.replace(tmp, path)
            except BaseException:
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            log.info("已从 Git 提交 %s 重建发布快照 %s", entry["commit"][:8], rev)
            return path

    def snapshot(self, rev: str) -> ResourceSet:
        """读取某个版本的资源集合（带进程内缓存；加载期间钉住版本号防 prune 并发误删，写缓存前复核完整性）。"""
        with self._snap_lock:
            if rev in self._snapshots:
                self._snapshots.move_to_end(rev)
                return self._snapshots[rev]
        with self.lock:
            path = self.ensure_materialized(rev)
            with self._snap_lock:
                if rev in self._snapshots:
                    self._snapshots.move_to_end(rev)
                    return self._snapshots[rev]
                self._loading_revs[rev] = self._loading_revs.get(rev, 0) + 1
        try:
            rs = load_resource_dir(path)
            if not (path / ".release.json").is_file():
                with self.lock:
                    path = self.ensure_materialized(rev)
                    rs = load_resource_dir(path)
            with self._snap_lock:
                if (path / ".release.json").is_file():
                    self._snapshots[rev] = rs
                    self._snapshots.move_to_end(rev)
                    while len(self._snapshots) > 8:
                        self._snapshots.popitem(last=False)
            return rs
        finally:
            with self._snap_lock:
                rem = self._loading_revs.get(rev, 1) - 1
                if rem <= 0:
                    self._loading_revs.pop(rev, None)
                else:
                    self._loading_revs[rev] = rem

    def live_snapshot(self) -> tuple[str, ResourceSet]:
        """请求开始时调用一次：返回（线上版本号，资源集合）。"""
        rev = self.live_rev()
        if not rev:
            raise ReleaseNotFound("尚无线上版本")
        return rev, self.snapshot(rev)

    def try_live_snapshot(self) -> tuple[str, ResourceSet] | None:
        """同步无重 IO 快路径：仅通过 os.readlink 读取线上软链并查进程内 _snapshots 缓存，未命中返回 None。"""
        rev = self.live_rev()
        if not rev:
            return None
        with self._snap_lock:
            rs = self._snapshots.get(rev)
            if rs is None:
                return None
            self._snapshots.move_to_end(rev)
            return rev, rs

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
        """读取某版本中的一个文件；快照已完整物化且文件不存在时直接返回 None，避免无效 git show 子进程开销。"""
        entry = self.entry(rev)
        rel_dir = self.layout.release_dir(rev)
        path = ensure_within(rel_dir, rel_dir / rel_path)
        try:
            if path.is_file():
                return path.read_text(encoding="utf-8")
            if (rel_dir / ".release.json").is_file():
                return None
        except (FileNotFoundError, OSError):
            pass
        except UnicodeDecodeError:
            return None
        data = self.repo.show(entry["commit"], rel_path)
        if data is None:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    # ------------------------------------------------------------------ 写入（调用方持有写锁）
    def add(self, entry: dict[str, Any], built_dir: Path) -> None:
        """登记新版本并切换为线上版本；切换失败时完整回滚索引与目录，保证版本与 Git 一致性。"""
        with self.lock:
            rev = entry["rev"]
            final = self.layout.release_dir(rev)
            if final.exists() and not self.has(rev):
                shutil.rmtree(final, ignore_errors=True)
            write_json(built_dir / ".release.json", entry)
            prev_index = self.layout.release_index.read_bytes() if self.layout.release_index.exists() else None
            os.replace(built_dir, final)
            try:
                append_jsonl(self.layout.release_index, entry)
                self._invalidate_entries_cache()
                atomic_symlink(rev, self.layout.current)
            except BaseException:
                self._invalidate_entries_cache()
                if prev_index is None:
                    self.layout.release_index.unlink(missing_ok=True)
                else:
                    with suppress(OSError):
                        atomic_write_bytes(self.layout.release_index, prev_index)
                if self.live_rev() != rev:
                    shutil.rmtree(final, ignore_errors=True)
                raise

    def switch(self, rev: str) -> None:
        """紧急切换线上版本。"""
        with self.lock:
            self.ensure_materialized(rev)
            atomic_symlink(rev, self.layout.current)

    def prune(self) -> None:
        """只保留最近 keep 个版本目录、线上版本及正在加载的版本（先原子重命名再删除，避免并发读半删冲突）。"""
        with self.lock:
            live = self.live_rev()
            revs = [e["rev"] for e in self.entries()]
            with self._snap_lock:
                pinned = set(self._loading_revs)
            keep_revs = (set(revs[-self.keep:]) if self.keep > 0 else set()) | ({live} if live else set()) | pinned
            for rev in revs:
                path = self.layout.release_dir(rev)
                if rev not in keep_revs and path.exists():
                    trash = self.layout.releases / f".prune-{rev}-{os.getpid()}-{secrets.token_hex(4)}"
                    try:
                        os.replace(path, trash)
                    except OSError:
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        shutil.rmtree(trash, ignore_errors=True)

    def _recover_draft_dirs(self) -> None:
        """恢复在两段式 os.replace 中间崩溃中断的完整草稿，并清理其余残留 .tmp / .bak 目录。"""
        if not self.layout.drafts.exists():
            return
        for kind_dir in self.layout.drafts.iterdir():
            if kind_dir.is_symlink() or not kind_dir.is_dir():
                continue
            kind = kind_dir.name
            candidates_by_key: dict[str, list[tuple[tuple[int, int], Path]]] = defaultdict(list)
            stale_entries: list[Path] = []
            for entry in kind_dir.iterdir():
                if not (entry.name.startswith(".") and entry.name.endswith((".tmp", ".bak"))):
                    continue
                stale_entries.append(entry)
                if entry.is_symlink() or not entry.is_dir():
                    continue
                m = _DRAFT_TMP_RE.match(entry.name)
                if not m:
                    continue
                key = m.group("key")
                ext = m.group("ext")
                if not is_valid_resource_key(kind, key):
                    continue
                meta = read_json(entry / META_FILE)
                if not isinstance(meta, dict):
                    continue
                try:
                    rev_num = int(meta.get("revision") or 0)
                except (TypeError, ValueError):
                    rev_num = 0
                priority = (rev_num, 1 if ext == "tmp" else 0)
                candidates_by_key[key].append((priority, entry))

            for key, items in candidates_by_key.items():
                target = kind_dir / key
                if os.path.lexists(target):
                    continue
                items.sort(key=lambda pair: pair[0], reverse=True)
                best_dir = items[0][1]
                try:
                    os.replace(best_dir, target)
                    log.warning("启动恢复找回中断的草稿目录 %s/%s（源自 %s）", kind, key, best_dir.name)
                except OSError:
                    log.exception("恢复中断草稿目录失败 %s -> %s", best_dir, target)

            for entry in stale_entries:
                if os.path.lexists(entry):
                    unlink_or_rmtree(entry, ignore_errors=True)

    def recover(self) -> None:
        """启动时清理残留锁与未完成构建/淘汰目录，安全恢复中断草稿，并确保线上版本目录存在。"""
        with self.lock:
            git_lock = self.repo.path / ".git" / "index.lock"
            if os.path.lexists(git_lock):
                log.warning("启动恢复发现残留 Git 锁文件 %s，已自动清理", git_lock)
                unlink_or_rmtree(git_lock, ignore_errors=True)
            for pattern in (".build-*", ".restore-*", ".prune-*"):
                for tmp in self.layout.releases.glob(pattern):
                    unlink_or_rmtree(tmp, ignore_errors=True)
            self._recover_draft_dirs()
            live = self.live_rev()
            if live and self.has(live):
                self.ensure_materialized(live)
            elif self.entries():
                last = self.entries()[-1]["rev"]
                log.warning("线上指针缺失或无效，指向最新版本 %s", last)
                self.switch(last)
