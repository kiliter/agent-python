"""发布仓库的 Git 操作封装。

#Created By AiCoding(codex)
直接调用镜像中的 git 命令行，便于运维人员进入 PVC 用 git log / git show 排查。
提交身份通过环境变量传入，不修改任何 git config。
"""

from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from .fsutil import unlink_or_rmtree

log = logging.getLogger(__name__)

_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_GIT_BAD_IDENT_RE = re.compile(r"[\x00-\x1f\x7f<>]")


def _sanitize_git_ident(raw: str | None) -> str:
    """剥离 Git 提交人名称中的控制字符与尖括号，全空白时回退为 'system'。"""
    if not raw or not isinstance(raw, str):
        return "system"
    cleaned = _GIT_BAD_IDENT_RE.sub("", raw).strip()
    return cleaned or "system"


def _check_commit(commit: str) -> str:
    if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
        raise GitError(f"非法的 Git 提交号：{commit!r}")
    return commit


class GitError(RuntimeError):
    """git 命令执行失败。"""


@dataclass(frozen=True)
class NameStatus:
    """git diff --name-status 的一行。"""

    status: str  # A / M / D
    path: str


class GitRepo:
    """对 /data/repo 的最小 Git 封装。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _run(self, *args: str, input_bytes: bytes | None = None, env: dict[str, str] | None = None,
             check: bool = True) -> subprocess.CompletedProcess[bytes]:
        """执行 git 命令并返回结果。"""
        full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8", **(env or {})}
        try:
            proc = subprocess.run(
                ["git", "-c", "core.quotepath=false", "-c", "core.autocrlf=false", *args],
                cwd=self.path, input=input_bytes, capture_output=True, env=full_env, timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git {' '.join(args)} 执行超时") from exc
        except OSError as exc:
            raise GitError(f"git {' '.join(args)} 无法启动: {exc}") from exc
        if check and proc.returncode != 0:
            raise GitError(f"git {' '.join(args)} 失败: {proc.stderr.decode('utf-8', 'replace').strip()}")
        return proc

    def ensure_init(self) -> None:
        """仓库不存在时初始化（默认分支 main）。"""
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.path / ".git").exists():
            self._run("init", "-q", "-b", "main")

    def head(self) -> str | None:
        """当前 HEAD 提交，空仓库返回 None。"""
        proc = self._run("rev-parse", "--verify", "-q", "HEAD", check=False)
        return proc.stdout.decode().strip() or None if proc.returncode == 0 else None

    def has_changes(self) -> bool:
        """工作区是否有未提交变更（含未跟踪文件）。"""
        out = self._run("status", "--porcelain").stdout.decode()
        return bool(out.strip())

    def commit_all(self, message: str, author: str) -> str:
        """提交工作区全部变更并返回提交号。"""
        self._run("add", "-A")
        ident = _sanitize_git_ident(author)
        email = "report-agent@localhost"
        env = {
            "GIT_AUTHOR_NAME": ident,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": ident,
            "GIT_COMMITTER_EMAIL": email,
        }
        self._run("commit", "-q", "--allow-empty", "-F", "-", input_bytes=message.encode("utf-8"), env=env)
        head = self.head()
        if not head:
            raise GitError("提交后无法读取 HEAD")
        return head

    def show(self, commit: str, path: str) -> bytes | None:
        """读取某次提交中的文件内容，不存在返回 None。"""
        _check_commit(commit)
        if not path or "\x00" in path or path.startswith("/") or ".." in path.split("/"):
            return None
        proc = self._run("show", f"{commit}:{path}", check=False)
        return proc.stdout if proc.returncode == 0 else None

    def diff_name_status(self, a: str, b: str) -> list[NameStatus]:
        """两次提交之间变更的文件列表。"""
        _check_commit(a)
        _check_commit(b)
        if a == b:
            return []
        out = self._run("diff", "--name-status", "--no-renames", a, b, "--").stdout.decode("utf-8")
        result: list[NameStatus] = []
        for line in out.splitlines():
            if not line.strip():
                continue
            status, _, path = line.partition("\t")
            result.append(NameStatus(status=status[:1], path=path))
        return result

    def export(self, commit: str, dest: Path) -> None:
        """把某次提交的完整文件树导出到 dest 目录（用于重建被清理的发布快照）。"""
        _check_commit(commit)
        data = self._run("archive", "--format=tar", commit).stdout
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(dest, filter="data")

    def reset_to(self, commit: str | None) -> None:
        """发布异常回滚时将工作区与 HEAD 恢复到指定提交。"""
        if commit is not None:
            _check_commit(commit)
            self._run("reset", "--hard", commit)
            self._run("clean", "-fdx")
            return
        self._run("update-ref", "-d", "refs/heads/main", check=False)
        self._run("symbolic-ref", "HEAD", "refs/heads/main", check=False)
        self._run("rm", "-rf", "--cached", "--ignore-unmatch", ".", check=False)
        if self.path.exists():
            for child in self.path.iterdir():
                if child.name == ".git":
                    continue
                unlink_or_rmtree(child, ignore_errors=True)
