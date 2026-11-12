"""按模板动态生成交卷结构（submit_report 的参数 Schema）。

#Created By AiCoding(codex)
每个模板字段对应一个必填键，键名就是字段名：
  - 枚举字段的 value 限定为可选值；
  - 列表字段（type=list）的 value 为行对象数组，每列一个必填键，枚举列限定可选值；
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
    """引用接口结果中的某条记录的某一列（列表字段为空数组且接口无命中记录时，row 可填 0、column 可填空串）。"""

    type: Literal["api"]
    resultId: str = Field(description="call_api 返回的 resultId，如 r1")
    row: int = Field(default=0, description="query_result 返回的 row；列表字段 value=[] 且接口无命中记录时可填 0")
    column: str = Field(default="", description="列名，如 smsContent；列表字段 value=[] 且接口无命中记录时可填任意列名或空串")

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
    """引用平台工具的输出（如 format_date，或列表字段 value=[] 时引用 call_api / query_result 的 callId）。"""

    type: Literal["tool"]
    callId: str = Field(description="工具返回的 callId，如 t3")


def _build_row_model(f: FieldDef, model_name: str) -> type[BaseModel]:
    """生成列表字段一行的模型：每列一个必填键（别名为列名），枚举列限定可选值，禁止多余键。

    #Created By AiCoding(codex)
    Python 属性名用 c0、c1…，避免中文列名与 BaseModel 内置属性冲突；序列化、Schema 均使用列名。
    """
    cols: dict[str, Any] = {}
    for j, col in enumerate(f.columns):
        col_type: Any = Literal[tuple(col.values)] if col.type == "enum" and col.values else str  # type: ignore[valid-type]
        desc = col.description.strip() or col.name
        if col.type == "enum" and col.values:
            desc += f"；可选值：{'/'.join(col.values)}"
        cols[f"c{j}"] = (col_type, Field(alias=col.name, description=desc))
    return create_model(
        model_name, __config__=ConfigDict(extra="forbid"),
        __doc__=f"列表字段「{f.name}」的一行。", **cols,
    )


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
            # #Created By AiCoding(codex) 列表字段合法为空（value=[]）时允许引用 tool 证据证明已查询数据源；非空时由 EvidenceChecker 拦截 tool
            if f.is_list:
                return [ApiEvidence, DocumentEvidence, ToolEvidence]
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
        if f.is_list:
            # #Created By AiCoding(codex) 列表字段：支持 status=found 且 value=[] 表示已核查无记录；not_found 表示入参缺失或接口失败
            cache_key = ("list", idx)
            row_model = _build_row_model(f, f"Row{suffix}_{idx}")
            if len(kinds) == 1:
                list_item_type: Any = kinds[0]
            else:
                list_item_type = Annotated[Union[tuple(kinds)], Field(discriminator="type")]  # type: ignore[valid-type]
            cache[cache_key] = create_model(
                f"FieldAnswer{suffix}_{len(cache) + 1}", __base__=_Strict,
                status=(Literal["found", "not_found"], Field(
                    description="found=已核查数据源并得出确定列表（有记录填行数组，接口调用成功且确无匹配记录填 []）；"
                                "not_found=缺少必要入参、前置依赖缺失或接口调用失败无法获知结果")),
                value=(list[row_model] | None, Field(  # type: ignore[valid-type]
                    default=None,
                    description="行对象数组，每行包含全部列；接口调用成功且确无匹配记录时 status=found 且填 []；not_found 时为 null")),
                evidence=(list[list_item_type], Field(
                    default_factory=list,
                    description="取值依据（非空列表覆盖所有行的出处；status=found 且 value=[] 时仍须附上查询证据，如 tool/api/document）")),
                reasoning=(str, Field(default="", description="判断过程；value=[] 或 not_found 时写明核查过程与原因")),
            )
            cols_desc = "、".join(
                c.name + (f"（可选值：{'/'.join(c.values)}）" if c.type == "enum" and c.values else "") for c in f.columns
            )
            desc = (f"{EVIDENCE_LABEL[f.evidence]}；列表字段，value 为行对象数组（查过确无匹配记录时提交 status=found, value=[] 并附查询证据；"
                    f"缺少入参或接口失败时提交 status=not_found, value=null），列：{cols_desc}")
            model_fields[f"f{idx}"] = (cache[cache_key], Field(alias=f.name, description=desc))
            continue
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
