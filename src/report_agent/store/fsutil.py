"""文件读写工具：原子写入、JSON 读写、原子切换软链接。

#Created By AiCoding(codex)
所有对 PVC 的写入都先写同目录临时文件，fsync 后再 rename 覆盖，
保证进程崩溃或断电时不会留下写了一半的文件。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def now_iso() -> str:
    """当前时间（本地时区）ISO 字符串，精确到秒。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def fmt_time(iso: str | None, empty: str = "—") -> str:
    """把 ISO 时间格式化为前端使用的 'YYYY-MM-DD HH:mm'。"""
    if not iso:
        return empty
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def _fsync_dir(path: Path) -> None:
    """同步目录元数据，确保 rename 结果落盘（部分文件系统不支持时忽略）。"""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _chmod_safe(path_or_fd: Path | int, mode: int) -> None:
    """尽力设置文件或文件描述符权限，兼容不支持 POSIX chmod 的文件系统。"""
    try:
        if isinstance(path_or_fd, int):
            if hasattr(os, "fchmod"):
                os.fchmod(path_or_fd, mode)
        else:
            path_or_fd.chmod(mode)
    except OSError:
        pass


def atomic_write_bytes(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """原子写入二进制内容；指定 mode 时在写入前先收紧临时文件权限，杜绝权限裸露窗口。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        if mode is not None:
            _chmod_safe(fd, mode)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            _chmod_safe(Path(tmp), mode)
        os.replace(tmp, path)
        if mode is not None:
            _chmod_safe(path, mode)
        _fsync_dir(path.parent)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    """原子写入 UTF-8 文本。"""
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)


def write_json(path: Path, data: Any, *, mode: int | None = None) -> None:
    """原子写入 JSON（UTF-8，不转义中文）。"""
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", mode=mode)


def dumps_jsonl(data: Any) -> str:
    """紧凑序列化单行 JSONL 记录（不转义中文）。"""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)


def read_json(path: Path, default: Any = None) -> Any:
    """读取 JSON 文件，不存在或损坏时返回默认值。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        log.warning("JSON 文件无法解析 %s：%s", path, exc)
        return default


def read_text(path: Path) -> str | None:
    """读取文本文件，不存在时返回 None。"""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def append_line(path: Path, line: str, *, mode: int | None = None) -> None:
    """追加一行到 JSONL 文件并 fsync。调用方负责保证单写者；指定 mode 时以受限权限打开并修正文件权限。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (line.rstrip("\n") + "\n").encode("utf-8")
    if mode is None:
        with path.open("ab") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, mode)
    fd_owned = False
    try:
        _chmod_safe(fd, mode)
        fh = os.fdopen(fd, "ab")
        fd_owned = True
        with fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        if not fd_owned:
            try:
                os.close(fd)
            except OSError:
                pass
        raise
    _chmod_safe(path, mode)


def append_jsonl(path: Path, data: dict[str, Any], *, mode: int | None = None) -> None:
    """将字典序列化为单行 JSON 追加至 JSONL 文件并 fsync。"""
    append_line(path, dumps_jsonl(data), mode=mode)


def append_audit(path: Path, action: str, operator: str, detail: dict[str, Any]) -> None:
    """追加一条统一格式的审计日志记录。"""
    append_jsonl(path, {"time": now_iso(), "action": action, "operator": operator, **detail})


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL 文件；跳过崩溃时可能残留的半行、损坏字节或非对象记录。"""
    items: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    items.append(obj)
    except (FileNotFoundError, OSError):
        pass
    return items


def atomic_symlink(target: str, link: Path) -> None:
    """原子地把软链接 link 指向 target（先建临时链接再 rename 覆盖）。"""
    link.parent.mkdir(parents=True, exist_ok=True)
    tmp = link.with_name(f".{link.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp.unlink(missing_ok=True)
    try:
        os.symlink(target, tmp)
        os.replace(tmp, link)
        _fsync_dir(link.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def trees_equal(dir_a: Path | None, dir_b: Path | None, ignore: set[str] | None = None) -> bool:
    """判断两棵目录树的全部文件内容是否完全一致（忽略 ignore 中的文件名/目录名）。"""
    skip = ignore or set()

    def snapshot_files(root: Path | None) -> dict[str, Path]:
        if root is None or not root.exists():
            return {}
        out: dict[str, Path] = {}
        for cur, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in skip)
            cur_path = Path(cur)
            for fname in sorted(files):
                if fname in skip:
                    continue
                fpath = cur_path / fname
                out[fpath.relative_to(root).as_posix()] = fpath
        return out

    fa = snapshot_files(dir_a)
    fb = snapshot_files(dir_b)
    if fa.keys() != fb.keys():
        return False
    for rel, pa in fa.items():
        pb = fb[rel]
        try:
            if pa.stat().st_size != pb.stat().st_size or pa.read_bytes() != pb.read_bytes():
                return False
        except OSError:
            return False
    return True


def replace_dir_contents(dst: Path, src: Path, keep: set[str] | None = None) -> None:
    """用 src 目录的内容替换 dst 目录的内容（保留 keep 中列出的顶层条目，如 .git）。"""
    keep = keep or set()
    dst.mkdir(parents=True, exist_ok=True)
    for child in dst.iterdir():
        if child.name in keep:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in src.iterdir():
        if child.name in keep:
            continue
        target = dst / child.name
        if child.is_symlink():
            os.symlink(os.readlink(child), target)
        elif child.is_dir():
            shutil.copytree(child, target, symlinks=True)
        else:
            shutil.copy2(child, target)
