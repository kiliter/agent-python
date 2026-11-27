"""PVC 目录布局与资源路径映射。

#Created By AiCoding(codex)
/data
├── repo/                    Git 仓库，内容始终与最新构建的发布快照一致
├── drafts/<kind>/<key>/     草稿（与发布树结构相同）+ .meta.json
├── releases/
│   ├── index.jsonl          每个发布版本一行元数据
│   ├── r1/ r2/ ...          不可变的发布快照
│   └── current -> rN        线上版本（原子切换）
├── runs/YYYY/MM/DD/         运行记录：index.jsonl + <runId>.json
├── cases/<templateId>/      回归用例
├── mock-gateway/            mock 模式下的网关样例响应
├── config/                  用户、令牌密钥
└── audit.jsonl              发布、回退、紧急切换等操作日志
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..domain.composite import COMPOSITE_TEMPLATE_FILE, COMPOSITE_TEMPLATE_KEY
from ..domain.resources import SYSTEM_PROMPT_FILE, ResourceKind
from .fsutil import unlink_or_rmtree

META_FILE = ".meta.json"
DEFAULT_IGNORE_FILES: frozenset[str] = frozenset({META_FILE, ".DS_Store"})
KINDS: tuple[ResourceKind, ...] = ("template", "skill", "api", "system-prompt", "composite-template")
KIND_LABEL = {
    "template": "模板",
    "skill": "Skill",
    "api": "接口",
    "system-prompt": "系统提示词",
    "composite-template": "汇总大模板",
}
SYSTEM_PROMPT_KEY = "system-prompt"

TEMPLATE_KEY_RE = re.compile(r"^[1-9][0-9]{0,9}$")
SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")
API_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")
REV_RE = re.compile(r"^r[1-9][0-9]{0,9}$")
CASE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class InvalidResource(ValueError):
    """草稿内容或资源标识不合法。"""


def ensure_within(base: Path, target: Path) -> Path:
    """确保目标路径（含解析软链接后的真实路径）位于 base 目录内部，防止路径穿越与软链逃逸。"""
    if "\x00" in str(base) or "\x00" in str(target):
        raise InvalidResource("资源路径包含非法字符")
    base_norm = Path(os.path.normpath(os.path.abspath(base)))
    target_norm = Path(os.path.normpath(os.path.abspath(target)))
    if target_norm == base_norm or not target_norm.is_relative_to(base_norm):
        raise InvalidResource("非法的资源路径访问")
    try:
        base_res = base.resolve()
        target_res = target.resolve()
    except (OSError, RuntimeError) as exc:
        raise InvalidResource("非法的资源路径访问") from exc
    if target_res == base_res or not target_res.is_relative_to(base_res):
        raise InvalidResource("非法的资源路径访问")
    return target


def ensure_entry_within(base: Path, target: Path) -> Path:
    """确保条目自身（不跟随末端软链接）位于 base 目录内部，用于安全摘除或清理末端软链接/条目。"""
    if "\x00" in str(base) or "\x00" in str(target):
        raise InvalidResource("资源路径包含非法字符")
    base_norm = Path(os.path.normpath(os.path.abspath(base)))
    target_norm = Path(os.path.normpath(os.path.abspath(target)))
    if target_norm == base_norm or not target_norm.is_relative_to(base_norm):
        raise InvalidResource("非法的资源路径访问")
    try:
        base_res = base.resolve()
        parent_res = target_norm.parent.resolve()
    except (OSError, RuntimeError) as exc:
        raise InvalidResource("非法的资源路径访问") from exc
    if parent_res != base_res and not parent_res.is_relative_to(base_res):
        raise InvalidResource("非法的资源路径访问")
    return target


def is_valid_resource_key(kind: str, key: str) -> bool:
    """检查资源标识是否符合各类型的命名规范。"""
    if not isinstance(key, str) or not key or "\x00" in key:
        return False
    if kind == "template":
        return bool(TEMPLATE_KEY_RE.match(key))
    if kind == "skill":
        return bool(SKILL_ID_RE.match(key))
    if kind == "api":
        return bool(API_NAME_RE.match(key))
    if kind == "system-prompt":
        return key == SYSTEM_PROMPT_KEY
    if kind == "composite-template":
        return key == COMPOSITE_TEMPLATE_KEY
    return False


@dataclass(frozen=True)
class ResourceRef:
    """资源引用：类型 + 标识（模板为数字 id 的字符串形式）。"""

    kind: ResourceKind
    key: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise InvalidResource(f"未知的资源类型：{self.kind}")
        if not is_valid_resource_key(self.kind, self.key):
            label = KIND_LABEL.get(self.kind, self.kind)
            raise InvalidResource(f"{label}标识「{self.key}」格式不合法")

    def tree_path(self) -> str:
        """该资源在发布树中的相对路径（目录或文件）。"""
        if self.kind == "template":
            return f"templates/{self.key}"
        if self.kind == "skill":
            return f"skills/{self.key}"
        if self.kind == "api":
            return f"apis/{self.key}.yaml"
        if self.kind == "composite-template":
            return COMPOSITE_TEMPLATE_FILE
        return SYSTEM_PROMPT_FILE

    def is_dir(self) -> bool:
        return self.kind in ("template", "skill")

    def label(self) -> str:
        if self.kind == "system-prompt":
            return "系统提示词"
        if self.kind == "composite-template":
            return "汇总大模板"
        return f"{KIND_LABEL[self.kind]} {self.key}"


def ref_from_tree_path(path: str) -> ResourceRef | None:
    """根据发布树中的文件路径反查所属资源（用于版本 diff）。"""
    parts = path.split("/")
    try:
        if parts[0] == "templates" and len(parts) >= 2:
            return ResourceRef("template", parts[1])
        if parts[0] == "skills" and len(parts) >= 2:
            return ResourceRef("skill", parts[1])
        if parts[0] == "apis" and len(parts) == 2 and parts[1].endswith(".yaml"):
            return ResourceRef("api", parts[1][:-5])
        if path == SYSTEM_PROMPT_FILE:
            return ResourceRef("system-prompt", SYSTEM_PROMPT_KEY)
        if path == COMPOSITE_TEMPLATE_FILE:
            return ResourceRef("composite-template", COMPOSITE_TEMPLATE_KEY)
    except InvalidResource:
        return None
    return None


class DataLayout:
    """数据目录下各子目录的位置。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.repo = self.root / "repo"
        self.drafts = self.root / "drafts"
        self.releases = self.root / "releases"
        self.current = self.releases / "current"
        self.release_index = self.releases / "index.jsonl"
        self.runs = self.root / "runs"
        self.chats = self.root / "chats"
        self.cases = self.root / "cases"
        self.regressions = self.root / "regressions"
        self.mock_gateway = self.root / "mock-gateway"
        self.config = self.root / "config"
        self.audit = self.root / "audit.jsonl"

    def ensure(self) -> None:
        """创建基础目录。"""
        for p in (
            self.drafts, self.releases, self.runs, self.chats,
            self.cases, self.regressions, self.mock_gateway, self.config,
        ):
            p.mkdir(parents=True, exist_ok=True)

    def release_dir(self, rev: str) -> Path:
        if not isinstance(rev, str) or not REV_RE.match(rev):
            raise InvalidResource(f"版本号「{rev}」格式不合法")
        return ensure_within(self.releases, self.releases / rev)

    def draft_dir(self, ref: ResourceRef) -> Path:
        return ensure_within(self.drafts, self.drafts / ref.kind / ref.key)


def read_tree_text_files(
    root: Path,
    *,
    ignore_names: set[str] | frozenset[str] = DEFAULT_IGNORE_FILES,
) -> dict[str, str]:
    """递归读取目录下的全部 UTF-8 文本文件（拦截一切软链接并将非 UTF-8 字节转为 InvalidResource）。"""
    if root.is_symlink():
        raise InvalidResource(f"资源目录包含非法软链接「{root.name}」")
    out: dict[str, str] = {}
    stack: list[tuple[Path, str]] = [(root, "")]
    while stack:
        cur_dir, rel_prefix = stack.pop()
        try:
            with os.scandir(cur_dir) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if entry.name in ignore_names:
                continue
            if entry.is_symlink():
                raise InvalidResource(f"资源目录包含非法软链接「{entry.name}」")
            rel_posix = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
            entry_path = ensure_within(root, Path(entry.path))
            if entry.is_dir(follow_symlinks=False):
                stack.append((entry_path, rel_posix))
            elif entry.is_file(follow_symlinks=False):
                try:
                    out[rel_posix] = entry_path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    continue
                except UnicodeDecodeError as exc:
                    raise InvalidResource(f"文件「{rel_posix}」不是有效的 UTF-8 文本") from exc
    return dict(sorted(out.items()))


def copy_dir_no_symlinks(
    src: Path,
    dst: Path,
    *,
    ignore_names: set[str] | frozenset[str] = DEFAULT_IGNORE_FILES,
) -> None:
    """递归复制目录内容，严格拒绝任何软链接并过滤指定忽略文件名。"""
    if src.is_symlink():
        raise InvalidResource(f"资源目录包含非法软链接「{src.name}」")
    dst.mkdir(parents=True, exist_ok=True)
    stack: list[tuple[Path, Path]] = [(src, dst)]
    while stack:
        cur_src, cur_dst = stack.pop()
        with os.scandir(cur_src) as it:
            entries = sorted(it, key=lambda e: e.name)
        for entry in entries:
            if entry.name in ignore_names:
                continue
            if entry.is_symlink():
                raise InvalidResource(f"资源目录包含非法软链接「{entry.name}」")
            src_child = ensure_within(src, Path(entry.path))
            dst_child = ensure_entry_within(dst, cur_dst / entry.name)
            if entry.is_dir(follow_symlinks=False):
                dst_child.mkdir(parents=True, exist_ok=True)
                stack.append((src_child, dst_child))
            elif entry.is_file(follow_symlinks=False):
                shutil.copy2(src_child, dst_child)


def copy_resource(
    src_root: Path,
    dst_root: Path,
    ref: ResourceRef,
    *,
    ignore_names: set[str] | frozenset[str] | None = None,
) -> None:
    """把一个资源从 src 树复制到 dst 树（先删除 dst 中的旧内容，拦截软链接并过滤忽略文件）。"""
    remove_resource(dst_root, ref)
    src = ensure_within(src_root, src_root / ref.tree_path())
    dst = ensure_entry_within(dst_root, dst_root / ref.tree_path())
    if src.is_symlink():
        raise InvalidResource(f"资源路径「{ref.tree_path()}」包含非法软链接")
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    skip = DEFAULT_IGNORE_FILES if ignore_names is None else (DEFAULT_IGNORE_FILES | set(ignore_names))
    if src.is_dir():
        copy_dir_no_symlinks(src, dst, ignore_names=skip)
    else:
        shutil.copy2(src, dst)


def remove_resource(root: Path, ref: ResourceRef) -> None:
    """从树中删除一个资源（兼容指向外部或悬空的目录/文件软链接安全摘除）。"""
    target = ensure_entry_within(root, root / ref.tree_path())
    unlink_or_rmtree(target)
