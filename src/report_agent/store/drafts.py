"""草稿存储：每个资源最多一份草稿，带乐观锁版本号。

#Created By AiCoding(codex)
drafts/<kind>/<key>/ 下存放资源文件和 .meta.json：
  template: template.yaml、body.md.j2
  skill:    SKILL.md
  api:      <name>.yaml
  system-prompt: system-prompt.md
"""

from __future__ import annotations

import os
import secrets
import shutil
import threading
from pathlib import Path
from typing import Any

from .fsutil import _fsync_dir, atomic_write_text, now_iso, read_json, read_text, write_json
from .layout import (
    META_FILE,
    DataLayout,
    InvalidResource,
    ResourceRef,
    ensure_entry_within,
    ensure_within,
    is_valid_resource_key,
)


class DraftConflict(RuntimeError):
    """保存草稿时版本号不一致（别人先保存了）。"""

    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("草稿已被其他人修改")
        self.current = current


class DraftStore:
    """草稿读写。写操作在全局写锁内进行。"""

    def __init__(self, layout: DataLayout, lock: threading.RLock) -> None:
        self.layout = layout
        self.lock = lock

    def _dir(self, ref: ResourceRef) -> Path:
        return self.layout.draft_dir(ref)

    @staticmethod
    def single_file_name(ref: ResourceRef) -> str:
        """单文件资源在草稿目录中的文件名。"""
        return Path(ref.tree_path()).name

    def exists(self, ref: ResourceRef) -> bool:
        return self.meta(ref) is not None

    def meta(self, ref: ResourceRef) -> dict[str, Any] | None:
        data = read_json(self._dir(ref) / META_FILE)
        return data if isinstance(data, dict) else None

    def list_keys(self, kind: str) -> list[str]:
        """某类资源的全部草稿标识。"""
        base = self.layout.drafts / kind
        if not base.exists():
            return []
        out: list[str] = []
        for p in base.iterdir():
            if p.name.startswith(".") or p.is_symlink() or not p.is_dir() or not is_valid_resource_key(kind, p.name):
                continue
            if isinstance(read_json(p / META_FILE), dict):
                out.append(p.name)
        return sorted(out)

    def read_file(self, ref: ResourceRef, name: str) -> str | None:
        d = self._dir(ref)
        path = ensure_within(d, d / name)
        try:
            return read_text(path)
        except (UnicodeDecodeError, OSError):
            return None

    def write(self, ref: ResourceRef, files: dict[str, str], operator: str, base_rev: str | None,
              expected_revision: int | None = None, action: str = "edit") -> dict[str, Any]:
        """原子写入草稿目录。expected_revision 不为空且与当前版本号不同时抛 DraftConflict。"""
        with self.lock:
            d = self._dir(ref)
            current = self.meta(ref)
            if expected_revision is not None and current and int(current.get("revision", 0)) != expected_revision:
                raise DraftConflict(current)
            now = now_iso()
            meta = {
                "kind": ref.kind,
                "key": ref.key,
                "baseRev": current.get("baseRev") if current else base_rev,
                "revision": int(current.get("revision", 0)) + 1 if current else 1,
                "createdAt": current.get("createdAt") if current else now,
                "createdBy": current.get("createdBy") if current else operator,
                "updatedAt": now,
                "updatedBy": operator,
                "action": current.get("action", action) if current else action,
            }
            d.parent.mkdir(parents=True, exist_ok=True)
            token = f"{os.getpid()}.{secrets.token_hex(4)}"
            tmp_dir = d.parent / f".{d.name}.{token}.tmp"
            bak_dir = d.parent / f".{d.name}.{token}.bak"
            try:
                tmp_dir.mkdir(parents=True, exist_ok=False)
                for name, text in files.items():
                    if not name or name == META_FILE or "/" in name or "\\" in name:
                        raise InvalidResource(f"草稿文件名「{name}」不合法")
                    atomic_write_text(ensure_within(tmp_dir, tmp_dir / name), text)
                write_json(tmp_dir / META_FILE, meta)
                if d.exists():
                    os.replace(d, bak_dir)
                try:
                    os.replace(tmp_dir, d)
                except BaseException:
                    if bak_dir.exists() and not d.exists():
                        os.replace(bak_dir, d)
                    raise
                _fsync_dir(d.parent)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                shutil.rmtree(bak_dir, ignore_errors=True)
            return meta

    def rebase(self, ref: ResourceRef, base_rev: str | None, action: str | None = None) -> None:
        """修改草稿的基准版本（回退恢复到草稿时使用）。"""
        with self.lock:
            meta = self.meta(ref)
            if not meta:
                return
            meta["baseRev"] = base_rev
            if action:
                meta["action"] = action
            write_json(self._dir(ref) / META_FILE, meta)

    def delete(self, ref: ResourceRef) -> bool:
        """删除草稿（兼容指向外部或悬空的末端软链接安全摘除）。"""
        with self.lock:
            d = ensure_entry_within(self.layout.drafts, self.layout.drafts / ref.kind / ref.key)
            if d.is_symlink() or d.is_file():
                d.unlink(missing_ok=True)
                return True
            if not d.exists():
                return False
            shutil.rmtree(d)
            return True

    def apply_to_tree(self, ref: ResourceRef, tree_root: Path) -> None:
        """把草稿内容写入一棵发布树（替换该资源的旧内容，先安全摘除可能存在的末端软链接）。"""
        src = self._dir(ref)
        dst = ensure_entry_within(tree_root, tree_root / ref.tree_path())
        if ref.is_dir():
            if dst.is_symlink() or dst.is_file():
                dst.unlink(missing_ok=True)
            elif dst.is_dir():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(META_FILE))
        else:
            if dst.is_symlink() or dst.is_file():
                dst.unlink(missing_ok=True)
            elif dst.is_dir():
                shutil.rmtree(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / self.single_file_name(ref), dst)
