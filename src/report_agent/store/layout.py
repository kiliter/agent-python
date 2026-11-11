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

from ..domain.resources import SYSTEM_PROMPT_FILE, ResourceKind

META_FILE = ".meta.json"
KINDS: tuple[ResourceKind, ...] = ("template", "skill", "api", "system-prompt")
KIND_LABEL = {"template": "模板", "skill": "Skill", "api": "接口", "system-prompt": "系统提示词"}
SYSTEM_PROMPT_KEY = "system-prompt"

TEMPLATE_KEY_RE = re.compile(r"^[1-9]\d{0,9}$")
SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")
API_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]{0,63}$")
REV_RE = re.compile(r"^r[1-9]\d{0,9}$")
CASE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class InvalidResource(ValueError):
    """草稿内容或资源标识不合法。"""


def ensure_within(base: Path, target: Path) -> Path:
    """确保目标路径位于 base 目录内部，防止路径穿越。"""
    if "\x00" in str(target):
        raise InvalidResource("资源路径包含非法字符")
    base_norm = Path(os.path.normpath(os.path.abspath(base)))
    target_norm = Path(os.path.normpath(os.path.abspath(target)))
    if base_norm not in target_norm.parents:
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
        return SYSTEM_PROMPT_FILE

    def is_dir(self) -> bool:
        return self.kind in ("template", "skill")

    def label(self) -> str:
        return f"{KIND_LABEL[self.kind]} {self.key}" if self.kind != "system-prompt" else "系统提示词"


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
        self.cases = self.root / "cases"
        self.mock_gateway = self.root / "mock-gateway"
        self.config = self.root / "config"
        self.audit = self.root / "audit.jsonl"

    def ensure(self) -> None:
        """创建基础目录。"""
        for p in (self.drafts, self.releases, self.runs, self.cases, self.mock_gateway, self.config):
            p.mkdir(parents=True, exist_ok=True)

    def release_dir(self, rev: str) -> Path:
        if not isinstance(rev, str) or not REV_RE.match(rev):
            raise InvalidResource(f"版本号「{rev}」格式不合法")
        return ensure_within(self.releases, self.releases / rev)

    def draft_dir(self, ref: ResourceRef) -> Path:
        return ensure_within(self.drafts, self.drafts / ref.kind / ref.key)


def copy_resource(src_root: Path, dst_root: Path, ref: ResourceRef) -> None:
    """把一个资源从 src 树复制到 dst 树（先删除 dst 中的旧内容）。"""
    remove_resource(dst_root, ref)
    src = src_root / ref.tree_path()
    dst = dst_root / ref.tree_path()
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(META_FILE))
    else:
        shutil.copy2(src, dst)


def remove_resource(root: Path, ref: ResourceRef) -> None:
    """从树中删除一个资源。"""
    target = root / ref.tree_path()
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
