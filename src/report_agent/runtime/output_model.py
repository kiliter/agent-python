"""按模板动态生成交卷结构（submit_report 的参数 Schema）。

#Created By AiCoding(codex)
每个模板字段对应一个必填键，键名就是字段名：
  - 枚举字段的 value 限定为可选值；
  - evidence 只允许该字段证据类型对应的来源（quote → api/document，input → input，derive → 全部）；
  - input 证据的 key、field 证据的 name 限定为本模板的入参名、字段名。
这样模型照着 Schema 填就不会漏字段、写错字段名或填出范围外的枚举值；
证据内容是否属实由 evidence.EvidenceChecker 校验。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from ..domain.template import FieldDef, Template

EVIDENCE_LABEL = {"quote": "原文引用", "input": "入参", "derive": "推导"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiEvidence(_Strict):
    """引用接口结果中的某条记录的某一列。"""

    type: Literal["api"]
    resultId: str = Field(description="call_api 返回的 resultId，如 r1")
    row: int = Field(description="query_result 返回的 row")
    column: str = Field(description="列名，如 smsContent")

    @field_validator("row", mode="before")
    @classmethod
    def _reject_bool_row(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("row 必须是整数行号，不能是布尔值")
        return v


class DocumentEvidence(_Strict):
    """引用单据原文片段。"""

    type: Literal["document"]
    quote: str = Field(description="从单据中逐字复制的原文片段")


class ToolEvidence(_Strict):
    """引用平台工具的输出（如 format_date）。"""

    type: Literal["tool"]
    callId: str = Field(description="工具返回的 callId，如 t3")


def build_report_model(template: Template) -> type[BaseModel]:
    """生成本模板的交卷模型。"""
    d = template.definition
    input_keys = [i.key for i in d.inputs]
    field_names = [f.name for f in d.fields]
    suffix = str(d.id)

    InputEvidence = None
    if input_keys:
        InputEvidence = create_model(
            f"InputEvidence{suffix}", __base__=_Strict, __doc__="引用入参的值。",
            type=(Literal["input"], ...),
            key=(Literal[tuple(input_keys)], Field(description="入参名")),  # type: ignore[valid-type]
        )
    FieldEvidence = None
    if field_names:
        FieldEvidence = create_model(
            f"FieldEvidence{suffix}", __base__=_Strict, __doc__="引用本报告中另一个字段的结论。",
            type=(Literal["field"], ...),
            name=(Literal[tuple(field_names)], Field(description="字段名")),  # type: ignore[valid-type]
        )

    def evidence_types(f: FieldDef) -> list[type[BaseModel]]:
        if f.evidence == "quote":
            return [ApiEvidence, DocumentEvidence]
        if f.evidence == "input":
            return [InputEvidence] if InputEvidence else [DocumentEvidence]
        types: list[type[BaseModel]] = [ApiEvidence, DocumentEvidence, ToolEvidence]
        if FieldEvidence:
            types.append(FieldEvidence)
        if InputEvidence:
            types.insert(2, InputEvidence)
        return types

    cache: dict[tuple, type[BaseModel]] = {}
    model_fields: dict[str, Any] = {}
    for idx, f in enumerate(d.fields):
        kinds = evidence_types(f)
        values = tuple(f.values) if f.type == "enum" and f.values else None
        sig = (tuple(k.__name__ for k in kinds), values)
        if sig not in cache:
            if len(kinds) == 1:
                item_type: Any = kinds[0]
            else:
                item_type = Annotated[Union[tuple(kinds)], Field(discriminator="type")]  # type: ignore[valid-type]
            value_type: Any = Literal[values] if values else str  # type: ignore[valid-type]
            cache[sig] = create_model(
                f"FieldAnswer{suffix}_{len(cache) + 1}", __base__=_Strict,
                status=(Literal["found", "not_found"], Field(description="found=找到并给出证据；not_found=没有依据")),
                value=(value_type | None, Field(default=None, description="字段值；not_found 时为 null")),
                evidence=(list[item_type], Field(default_factory=list, description="取值依据")),
                reasoning=(str, Field(default="", description="判断过程；not_found 时写明原因")),
            )
        desc = f"{EVIDENCE_LABEL[f.evidence]}"
        if f.type == "enum":
            desc += f"；可选值：{'/'.join(f.values)}"
        if f.evidence == "quote" and f.quoteWhole:
            desc += "；必须整条原样引用"
        model_fields[f"f{idx}"] = (cache[sig], Field(alias=f.name, description=desc))

    return create_model(
        f"Report{suffix}", __config__=ConfigDict(populate_by_name=True, extra="forbid"),
        __doc__=f"提交模板「{d.name}」全部字段的结论。每个字段都必须出现。", **model_fields,
    )


def report_to_dict(report: BaseModel) -> dict[str, dict[str, Any]]:
    """把交卷模型转为 字段名 → {status, value, evidence, reasoning}。"""
    return report.model_dump(by_alias=True, mode="json")
