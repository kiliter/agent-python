"""Skill：纯文本的业务方法说明（SKILL.md）。

#Created By AiCoding(codex)
Skill 不包含任何代码，只告诉模型“遇到这类字段该查什么、怎么判断”。
文件格式：skills/<id>/SKILL.md，YAML frontmatter + Markdown 正文。
"""

from __future__ import annotations

import re

import yaml
from pydantic import BaseModel, ConfigDict, Field

SKILL_FILE = "SKILL.md"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


class SkillMeta(BaseModel):
    """SKILL.md 的 frontmatter。"""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Skill 标识，必须与目录名一致")
    title: str = Field(default="", description="中文名称，管理端展示用")
    description: str = ""
    apis: list[str] = Field(default_factory=list, description="本 Skill 需要调用的接口")


class Skill(BaseModel):
    """完整 Skill：元数据 + 正文 + 原始全文。"""

    meta: SkillMeta
    body: str
    markdown: str

    @property
    def id(self) -> str:
        return self.meta.name

    @property
    def title(self) -> str:
        return self.meta.title or self.meta.name


class SkillParseError(ValueError):
    """SKILL.md 格式不正确。"""


def parse_skill_markdown(markdown: str) -> Skill:
    """解析 SKILL.md 全文。"""
    normalized = (markdown or "").lstrip("\ufeff").replace("\r\n", "\n")
    m = _FRONTMATTER_RE.match(normalized)
    if not m:
        raise SkillParseError("SKILL.md 必须以 --- 包裹的 YAML frontmatter 开头")
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"frontmatter 不是合法的 YAML：{exc}") from exc
    if not isinstance(data, dict) or not str(data.get("name") or "").strip():
        raise SkillParseError("frontmatter 缺少 name")
    apis = data.get("apis") or []
    if isinstance(apis, str):
        apis = [a.strip() for a in apis.split(",") if a.strip()]
    elif isinstance(apis, list):
        apis = [str(a).strip() for a in apis if a is not None and str(a).strip()]
    else:
        raise SkillParseError("frontmatter 中 apis 必须是列表或逗号分隔字符串")
    data["apis"] = apis
    meta = SkillMeta.model_validate(data)
    return Skill(meta=meta, body=normalized[m.end():].strip(), markdown=markdown)


def build_skill_markdown(skill_id: str, title: str, description: str, apis: list[str]) -> str:
    """新建 Skill 时生成的初始 SKILL.md。"""
    front = yaml.safe_dump(
        {"name": skill_id, "title": title, "description": description, "apis": apis},
        allow_unicode=True, sort_keys=False, width=1000,
    ).strip()
    return (
        f"---\n{front}\n---\n\n# {title}\n\n## 适用场景\n\n（说明哪些字段需要用到本 Skill）\n\n"
        "## 需要的入参\n\n## 查询方法\n\n## 识别规则\n\n## 提交要求\n"
    )
