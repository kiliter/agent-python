"""模板定义：入参、字段、正文。

#Created By AiCoding(codex)
模板是整个系统的主体：字段的取值要求、证据类型、找不到时的处理都定义在模板里。
文件格式：templates/<id>/template.yaml（定义） + templates/<id>/body.md.j2（Jinja2 正文）。
"""

from __future__ import annotations

import re
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

FieldType = Literal["string", "enum", "date", "list"]
ColumnType = Literal["string", "enum"]
EvidenceType = Literal["quote", "input", "derive"]
WhenMissing = Literal["placeholder", "empty", "value"]


class _Base(BaseModel):
    """YAML 中使用 camelCase 键名，未知键直接报错，避免拼写错误被静默忽略。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class InputDef(_Base):
    """模板入参：上游调用时传入的参数。"""

    key: str
    required: bool = False
    pattern: str | None = None
    description: str = ""
    sample: str = ""


class ColumnDef(_Base):
    """列表字段（type=list）的一列。#Created By AiCoding(codex)

    每行是一个对象，键为列名；列只支持文本（string）与枚举（enum）两种类型。
    """

    name: str
    type: ColumnType = "string"
    values: list[str] = Field(default_factory=list, description="枚举列的可选值")
    description: str = ""


class FieldDef(_Base):
    """模板字段：报告中要填的值，或只参与判断的中间字段。"""

    name: str
    visible: bool = True
    type: FieldType = "string"
    values: list[str] = Field(default_factory=list, description="枚举可选值")
    # #Created By AiCoding(codex) 列表字段的列定义；仅 type=list 时允许填写
    columns: list[ColumnDef] = Field(default_factory=list, description="列表字段（type=list）的列定义")
    format: str | None = Field(default=None, description="日期字段的展示格式，如 yyyy年M月d号")
    evidence: EvidenceType = "quote"
    quoteWhole: bool = Field(default=False, description="quote 字段的值必须与引用的整列/整段原文完全一致")
    whenMissing: WhenMissing = "placeholder"
    defaultValue: str = ""
    description: str = ""

    @property
    def is_list(self) -> bool:
        """是否为列表字段。#Created By AiCoding(codex)"""
        return self.type == "list"

    def column_names(self) -> list[str]:
        """列表字段的列名（保持声明顺序）。#Created By AiCoding(codex)"""
        return [c.name for c in self.columns]


class TemplateDef(_Base):
    """template.yaml 的内容。"""

    id: int
    name: str
    description: str = ""
    skills: list[str] = Field(default_factory=list, description="本模板允许加载的 Skill（硬限制）")
    inputs: list[InputDef] = Field(default_factory=list)
    fields: list[FieldDef] = Field(default_factory=list)

    def field(self, name: str) -> FieldDef | None:
        """按名称查找字段。"""
        return next((f for f in self.fields if f.name == name), None)

    def input(self, key: str) -> InputDef | None:
        """按名称查找入参。"""
        return next((i for i in self.inputs if i.key == key), None)


class Template(BaseModel):
    """完整模板：定义 + 正文，以及是否已下线。"""

    definition: TemplateDef
    body: str = ""
    offline: bool = False

    @property
    def id(self) -> int:
        return self.definition.id

    @property
    def name(self) -> str:
        return self.definition.name


TEMPLATE_FILE = "template.yaml"
BODY_FILE = "body.md.j2"
OFFLINE_FILE = ".offline"


def dump_template_yaml(defn: TemplateDef) -> str:
    """把模板定义序列化为 YAML（保留字段顺序、中文不转义，省略默认值减少噪音）。"""
    data = defn.model_dump(exclude_defaults=True)
    data = {"id": defn.id, "name": defn.name, **{k: v for k, v in data.items() if k not in ("id", "name")}}
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)


def parse_template_yaml(text: str) -> TemplateDef:
    """解析 template.yaml。"""
    data = yaml.safe_load(text)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("template.yaml 顶层必须是键值映射对象")
    return TemplateDef.model_validate(data)


_VAR_RE = re.compile(r"\{\{-?\s*([^{}\s|\-]+?)\s*(?:\|[^{}]*)?-?\}\}")


def body_variable_lines(body: str) -> dict[str, list[int]]:
    """统计正文中 {{变量}} 出现的行号，用于校验提示定位。"""
    result: dict[str, list[int]] = {}
    for lineno, line in enumerate(body.splitlines(), start=1):
        for m in _VAR_RE.finditer(line):
            result.setdefault(m.group(1), []).append(lineno)
    return result
