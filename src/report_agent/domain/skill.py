"""Skill：纯文本的业务方法说明（SKILL.md）及按需懒加载的同级/子目录参考文档。

#Created By AiCoding(codex)
Skill 不包含任何代码，只告诉模型“遇到这类字段该查什么、怎么判断”。
文件格式：
  skills/<id>/SKILL.md                 主文档（YAML frontmatter + Markdown 正文）
  skills/<id>/<subdir>/<name>.md       可选参考子文档（如 references/broadband.md），支持按需懒加载
"""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

SKILL_FILE = "SKILL.md"
ROUTER_SKILL_ID = "template-router"
SkillScope = Literal["template", "global", "chat"]
_VALID_SCOPES = frozenset({"template", "global", "chat"})
_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(?:(.*?)\n)?---[ \t]*(?:\n|$)", re.DOTALL)

# #Created By AiCoding(codex) 多文件 Skill 子文档安全边界常量
MAX_SKILL_DOCS = 50
MAX_SKILL_DOC_CHARS = 200_000
MAX_SKILL_DOC_DEPTH = 3
_DOC_SEGMENT_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff._-]{0,63}$")
_CTRL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_FENCED_CODE_RE = re.compile(r"(^|\n)([ \t]*)(`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:\n[ \t]*\3[ \t]*(?=\n|$)|$)")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_MD_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(\s*(<[^>]+>|[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_IGNORED_DIR_ENTRIES = frozenset({".meta.json", ".DS_Store"})


class SkillMeta(BaseModel):
    """SKILL.md 的 frontmatter。"""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Skill 标识，必须与目录名一致")
    title: str = Field(default="", description="中文名称，管理端展示用")
    description: str = ""
    scope: SkillScope = Field(
        default="template",
        description="作用域：template（按模板绑定）/ global（全局填报自动持有）/ chat（聊天助手专用）",
    )
    apis: list[str] = Field(default_factory=list, description="本 Skill 需要调用的接口")


class Skill(BaseModel):
    """完整 Skill：元数据 + 正文 + 原始全文 + 可选子目录参考文档。"""

    meta: SkillMeta
    body: str
    markdown: str
    docs: dict[str, str] = Field(
        default_factory=dict,
        description="同级及子目录下的参考 Markdown 文档（规范化相对 POSIX 路径 -> 原文）",
    )

    @property
    def id(self) -> str:
        return self.meta.name

    @property
    def title(self) -> str:
        return self.meta.title or self.meta.name

    @property
    def scope(self) -> SkillScope:
        """Skill 作用域（template / global / chat）。#Created By AiCoding(codex)"""
        return self.meta.scope

    @property
    def is_global(self) -> bool:
        """是否为全局填报 Skill（所有填报模板自动持有）。#Created By AiCoding(codex)"""
        return self.meta.scope == "global"

    @property
    def is_chat(self) -> bool:
        """是否为聊天助手专用 Skill。#Created By AiCoding(codex)"""
        return self.meta.scope == "chat"


class SkillParseError(ValueError):
    """SKILL.md 或子文档格式/路径不正确。"""


def normalize_skill_doc_path(raw: str) -> str:
    """校验并规范化 Skill 子文档相对路径（如 references/broadband.md）。

    #Created By AiCoding(codex)
    允许同级或最多两级子目录下的 .md 文件（深度上限 3），严禁绝对路径、反斜杠、
    父目录穿越（..）、隐藏段（如 .meta.json / .git）以及覆盖主文件 SKILL.md。
    """
    if not isinstance(raw, str):
        raise SkillParseError("子文档路径必须是字符串")
    if _CTRL_CHAR_RE.search(raw):
        raise SkillParseError(f"子文档路径「{raw!r}」包含非法控制字符")
    cleaned = raw.strip()
    if not cleaned:
        raise SkillParseError("子文档路径不能为空")
    if "\\" in cleaned:
        raise SkillParseError(f"子文档路径「{raw}」不能包含反斜杠，请使用 / 分隔")
    if cleaned.startswith("/"):
        raise SkillParseError(f"子文档路径「{raw}」不能为绝对路径")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if not cleaned:
        raise SkillParseError(f"子文档路径「{raw}」不合法")
    parts = cleaned.split("/")
    if len(parts) > MAX_SKILL_DOC_DEPTH:
        raise SkillParseError(f"子文档路径「{raw}」目录层级过深，最多允许 {MAX_SKILL_DOC_DEPTH - 1} 级子目录")
    for seg in parts:
        if not seg or seg in (".", "..") or seg.startswith("."):
            raise SkillParseError(f"子文档路径「{raw}」包含非法路径段「{seg}」")
        if not _DOC_SEGMENT_RE.match(seg):
            raise SkillParseError(
                f"子文档路径段「{seg}」不合法：仅允许中英文、数字、点、下划线和短横线，且须以中英文或数字开头"
            )
    norm = "/".join(parts)
    if norm.lower() == SKILL_FILE.lower():
        raise SkillParseError(f"子文档路径不能与主文件 {SKILL_FILE} 同名")
    if not norm.lower().endswith(".md"):
        raise SkillParseError(f"子文档「{norm}」必须是 .md 结尾的 Markdown 文件")
    return norm


def extract_doc_title(text: str, fallback: str = "") -> str:
    """提取子文档标题（首个 Markdown 标题，缺失时取首行非空文本）。#Created By AiCoding(codex)"""
    normalized = (text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    m_fm = _FRONTMATTER_RE.match(normalized)
    body = normalized[m_fm.end():] if m_fm else normalized
    m_h = _HEADING_RE.search(body)
    if m_h:
        title = m_h.group(1).strip()
        if title:
            return title[:80]
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:60] + ("…" if len(stripped) > 60 else "")
    return fallback


def resolve_skill_doc_link(target: str, current_doc: str = SKILL_FILE) -> str | None:
    """将 Markdown 中的相对 .md 链接解析为相对于 Skill 根目录的 POSIX 路径。

    #Created By AiCoding(codex)
    外链（http/https/mailto 等）、纯锚点（#xxx）及非 .md 目标返回 None。
    返回值可能为 SKILL_FILE、合法子文档路径，或越界/非法路径字符串（供校验器报错）。
    """
    raw = (target or "").strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1].strip()
    if not raw or raw.startswith("#") or _SCHEME_RE.match(raw):
        return None
    # 去除锚点与查询参数
    path_only = raw.split("#", 1)[0].split("?", 1)[0].strip()
    if not path_only or not path_only.lower().endswith(".md"):
        return None
    if "\\" in path_only or path_only.startswith("/"):
        return path_only
    base_dir = posixpath.dirname(current_doc) if current_doc != SKILL_FILE else ""
    joined = posixpath.join(base_dir, path_only) if base_dir else path_only
    resolved = posixpath.normpath(joined)
    if resolved.lower() == SKILL_FILE.lower():
        return SKILL_FILE
    return resolved


def extract_md_doc_links(markdown: str, current_doc: str = SKILL_FILE) -> list[tuple[str, str]]:
    """提取 Markdown 正文中的相对 .md 链接（忽略围栏代码块与行内代码），返回 [(原始目标, 解析后路径)]。#Created By AiCoding(codex)"""
    text = (markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    # 剥离代码块与行内代码，避免示例路径触发断链误报
    stripped = _FENCED_CODE_RE.sub(lambda m: m.group(1), text)
    stripped = _INLINE_CODE_RE.sub("", stripped)
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in _MD_LINK_RE.finditer(stripped):
        raw_target = m.group(1)
        resolved = resolve_skill_doc_link(raw_target, current_doc=current_doc)
        if resolved is None:
            continue
        pair = (raw_target, resolved)
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    return out


def validate_skill_docs_map(docs: dict[str, str] | None) -> dict[str, str]:
    """校验并规范化子文档映射表，返回按路径升序排列的新字典。#Created By AiCoding(codex)"""
    if not docs:
        return {}
    if not isinstance(docs, dict):
        raise SkillParseError("子文档集合 docs 必须是键值对对象")
    if len(docs) > MAX_SKILL_DOCS:
        raise SkillParseError(f"单个 Skill 最多支持 {MAX_SKILL_DOCS} 篇子文档（当前 {len(docs)} 篇）")
    clean: dict[str, str] = {}
    for raw_path, content in docs.items():
        norm_path = normalize_skill_doc_path(raw_path)
        if norm_path in clean:
            raise SkillParseError(f"子文档路径「{norm_path}」重复")
        if not isinstance(content, str):
            raise SkillParseError(f"子文档「{norm_path}」内容必须是文本字符串")
        if len(content) > MAX_SKILL_DOC_CHARS:
            raise SkillParseError(
                f"子文档「{norm_path}」长度 {len(content)} 字符，超过上限 {MAX_SKILL_DOC_CHARS} 字符"
            )
        clean[norm_path] = content
    return dict(sorted(clean.items()))


def parse_skill_markdown(markdown: str, docs: dict[str, str] | None = None) -> Skill:
    """解析 SKILL.md 全文及可选子文档集合。"""
    normalized = (markdown or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    m = _FRONTMATTER_RE.match(normalized)
    if not m:
        raise SkillParseError("SKILL.md 必须以 --- 包裹的 YAML frontmatter 开头")
    try:
        raw_front = m.group(1)
        data = yaml.safe_load(raw_front) if raw_front is not None else {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"frontmatter 不是合法的 YAML：{exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise SkillParseError("frontmatter 顶层必须是键值对象")
    raw_name = data.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise SkillParseError("frontmatter 缺少 name")
    clean_data: dict[str, object] = {**data, "name": raw_name.strip()}
    for text_key in ("title", "description"):
        val = clean_data.get(text_key)
        if val is None:
            clean_data[text_key] = ""
        elif isinstance(val, bool) or not isinstance(val, (str, int, float)):
            raise SkillParseError(f"frontmatter 中 {text_key} 必须是字符串")
        else:
            clean_data[text_key] = str(val)
    apis_raw = clean_data.get("apis")
    if apis_raw is None or apis_raw == "":
        apis: list[str] = []
    elif isinstance(apis_raw, str):
        apis = list(dict.fromkeys(a.strip() for a in apis_raw.split(",") if a.strip()))
    elif isinstance(apis_raw, list):
        parsed_apis: list[str] = []
        for a in apis_raw:
            if a is None:
                continue
            if not isinstance(a, str):
                raise SkillParseError("frontmatter 中 apis 列表元素必须是字符串")
            if a.strip():
                parsed_apis.append(a.strip())
        apis = list(dict.fromkeys(parsed_apis))
    else:
        raise SkillParseError("frontmatter 中 apis 必须是列表或逗号分隔字符串")
    clean_data["apis"] = apis
    raw_scope = clean_data.get("scope")
    if raw_scope is None or (isinstance(raw_scope, str) and not raw_scope.strip()):
        # #Created By AiCoding(codex) 向后兼容：未声明 scope 时，template-router 自动归为 chat，其余默认 template
        clean_data["scope"] = "chat" if clean_data["name"] == ROUTER_SKILL_ID else "template"
    elif isinstance(raw_scope, str):
        norm_scope = raw_scope.strip().lower()
        if norm_scope not in _VALID_SCOPES:
            raise SkillParseError(f"frontmatter 中 scope={raw_scope!r} 不合法，只能是 template、global 或 chat")
        clean_data["scope"] = norm_scope
    else:
        raise SkillParseError("frontmatter 中 scope 必须是字符串（template / global / chat）")
    try:
        meta = SkillMeta.model_validate(clean_data)
    except ValidationError as exc:
        raise SkillParseError(f"frontmatter 字段不合法：{exc}") from exc
    clean_docs = validate_skill_docs_map(docs)
    return Skill(meta=meta, body=normalized[m.end():].strip(), markdown=markdown, docs=clean_docs)


def load_skill_dir(path: Path, root_resolved: Path | None = None) -> Skill:
    """读取整个 Skill 目录（SKILL.md 与同级/子目录下的 .md 文档），拒绝任何软链与越界路径。#Created By AiCoding(codex)"""
    boundary = root_resolved if root_resolved is not None else path.resolve()
    skill_dir_resolved = path.resolve()
    if not skill_dir_resolved.is_relative_to(boundary):
        raise ValueError(f"Skill {path.name} 路径越界")
    skill_file = path / SKILL_FILE
    if skill_file.is_symlink() or not skill_file.resolve().is_relative_to(boundary):
        raise ValueError(f"Skill {path.name} 内部文件路径越界")
    main_md = skill_file.read_text(encoding="utf-8")

    raw_docs: dict[str, str] = {}
    stack: list[tuple[Path, str]] = [(path, "")]
    while stack:
        cur_dir, rel_prefix = stack.pop()
        with os.scandir(cur_dir) as it:
            entries = sorted(it, key=lambda e: e.name)
        for entry in entries:
            if entry.name in _IGNORED_DIR_ENTRIES:
                continue
            entry_path = Path(entry.path)
            if entry.is_symlink():
                raise ValueError(f"Skill {path.name} 内部不允许包含软链接：{entry.name}")
            if not entry_path.resolve().is_relative_to(boundary):
                raise ValueError(f"Skill {path.name} 内部文件路径越界：{entry.name}")
            rel_posix = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
            if entry.is_dir(follow_symlinks=False):
                if entry.name.startswith("."):
                    raise SkillParseError(f"子文档目录「{rel_posix}」不能以点开头")
                stack.append((entry_path, rel_posix))
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            if rel_posix == SKILL_FILE:
                continue
            norm_path = normalize_skill_doc_path(rel_posix)
            raw_docs[norm_path] = entry_path.read_text(encoding="utf-8")

    return parse_skill_markdown(main_md, docs=raw_docs)


def build_skill_markdown(
    skill_id: str,
    title: str,
    description: str,
    apis: list[str],
    scope: SkillScope = "template",
) -> str:
    """新建 Skill 时生成的初始 SKILL.md。"""
    front = yaml.safe_dump(
        {
            "name": skill_id,
            "title": title,
            "description": description,
            "scope": scope,
            "apis": [] if scope == "chat" else apis,
        },
        allow_unicode=True, sort_keys=False, width=1000,
    ).strip()
    return (
        f"---\n{front}\n---\n\n# {title}\n\n## 适用场景\n\n（说明哪些字段需要用到本 Skill）\n\n"
        "## 需要的入参\n\n## 查询方法\n\n## 识别规则\n\n## 提交要求\n"
    )
