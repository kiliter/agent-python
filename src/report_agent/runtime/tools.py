"""平台通用工具：模型只能通过这些工具与外界交互，工具本身不含任何业务规则。

#Created By AiCoding(codex)
  load_skill     读取 Skill 说明（只能读模板允许的 Skill）
  call_api       调用已声明的接口（只能调模板 Skill 声明的接口），返回摘要和 resultId
  query_result   在接口结果中按条件筛选，返回完整列值
  normalize_text 文本清洗；text_contains 包含判断；date_range 起止时间；format_date 日期格式转换
每次调用都分配 callId（t1、t2…），可作为 derive 证据引用。
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext, Tool, ToolDefinition

from ..gateway.base import ApiCallResult
from .deps import RunDeps
from .text_tools import convert_date, date_range as _date_range, normalize_text as _normalize, normalized_contains
from .workspace import ApiResult

log = logging.getLogger(__name__)


def _record(ctx: RunContext[RunDeps], tool: str, args: dict[str, Any], output: Any, ok: bool = True,
            summary: Any = None) -> str:
    """登记工具调用并推送过程事件，返回 callId。"""
    deps = ctx.deps
    call = deps.workspace.record_call(tool, args, output, deps.events.elapsed_ms(), ok)
    deps.events.emit("tool", tool=tool, callId=call.call_id, args=args, ok=ok,
                     result=summary if summary is not None else output)
    return call.call_id


def _fail_or_retry(ctx: RunContext[RunDeps], tool: str, args: dict[str, Any], message: str, fallback: Any) -> Any:
    """记录异常工具调用；未超过重试次数时让模型重试，重试耗尽后返回结构化降级结果而非中断整次运行。"""
    _record(ctx, tool, args, {"error": message}, ok=False)
    if ctx.retry < ctx.max_retries:
        raise ModelRetry(message)
    return fallback


def _cell_text(row: dict[str, Any], col: str) -> str:
    val = row.get(col)
    return "" if val is None else str(val)


# ============================================================================ load_skill
async def load_skill(ctx: RunContext[RunDeps], name: str) -> str:
    """读取一个 Skill 的完整说明。需要查询或判断某类字段前先读取对应 Skill。

    Args:
        name: Skill 标识，只能是“可用 Skill”中列出的标识。
    """
    deps = ctx.deps
    if name not in deps.allowed_skills or name not in deps.resources.skills:
        msg = f"Skill「{name}」不可用，只能加载：{deps.allowed_skills}"
        return _fail_or_retry(ctx, "load_skill", {"name": name}, msg, f"错误：{msg}")
    skill = deps.resources.skills[name]
    if name not in deps.workspace.loaded_skills:
        deps.workspace.loaded_skills.append(name)
    _record(ctx, "load_skill", {"name": name}, {"title": skill.title}, summary={"title": skill.title})
    apis = [a for a in skill.meta.apis if a in deps.resources.apis]
    api_lines = "\n".join(f"- {a}（{deps.resources.apis[a].title}）参数：{deps.resources.apis[a].param_hint()}"
                          for a in apis)
    return f"# Skill：{skill.title}（{skill.id}）\n\n{skill.body}\n\n" + (
        f"## 本 Skill 可调用的接口\n{api_lines}\n" if api_lines else "")


async def _prepare_load_skill(ctx: RunContext[RunDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    allowed = [s for s in ctx.deps.allowed_skills if s in ctx.deps.resources.skills]
    if not allowed:
        return None
    schema = json.loads(json.dumps(tool_def.parameters_json_schema))
    schema["properties"]["name"]["enum"] = allowed
    return dataclasses.replace(tool_def, parameters_json_schema=schema)


# ============================================================================ call_api
async def call_api(ctx: RunContext[RunDeps], name: str, args: dict[str, Any]) -> dict[str, Any]:
    """调用一个业务接口。完整结果保存在工作区，这里只返回条数和预览；细看请用 query_result。

    Args:
        name: 接口名，只能是允许调用的接口。
        args: 接口参数（键为参数名），必须符合该接口的参数要求。
    """
    deps = ctx.deps
    clean_args = dict(args) if isinstance(args, dict) else {}
    if name not in deps.allowed_apis or name not in deps.resources.apis:
        msg = f"接口「{name}」不可调用，只能调用：{deps.allowed_apis}"
        return _fail_or_retry(ctx, "call_api", {"name": name, "args": clean_args}, msg,
                              {"ok": False, "error": msg, "note": "接口不在允许范围内，请按找不到处理"})
    contract = deps.resources.apis[name]
    errors = contract.validate_args(clean_args)
    if errors:
        msg = f"接口 {name} 参数不合法：{'；'.join(errors)}。参数要求：{contract.param_hint()}"
        return _fail_or_retry(ctx, "call_api", {"name": name, "args": clean_args}, msg,
                              {"ok": False, "error": msg, "note": "接口参数不合法，请按找不到处理"})
    t0 = time.monotonic()
    try:
        res = await deps.gateway.invoke(contract, clean_args)
    except Exception as exc:  # noqa: BLE001 - 网关意外异常转为结构化错误记录
        log.warning("网关调用未预期异常 api=%s：%s", name, exc)
        res = ApiCallResult(ok=False, error=f"网关调用异常：{type(exc).__name__} {exc}".strip(),
                            cost_ms=int((time.monotonic() - t0) * 1000))
    result = ApiResult(
        result_id=deps.workspace.next_result_id(), api=name, title=contract.title, args=clean_args, ok=res.ok,
        error=res.error, columns=dict(contract.response.records.columns), records=res.records,
        cost_ms=res.cost_ms, raw=res.raw, request_preview=res.request_preview, no_data=res.no_data,
    )
    deps.workspace.add_result(result)
    if not res.ok:
        out = {"resultId": result.result_id, "ok": False, "error": res.error,
               "note": "接口调用失败，请如实按找不到处理并写明原因，不要猜测数据"}
        _record(ctx, "call_api", {"name": name, "args": clean_args}, out, ok=False,
                summary={**out, "costMs": res.cost_ms})
        return out
    max_chars = contract.response.summary.maxPreviewChars
    n_preview = contract.preview_rows(deps.settings.agent_preview_rows)
    preview = []
    for i, rec in enumerate(res.records[:n_preview]):
        clipped = {
            k: ("" if v is None else (str(v) if len(str(v)) <= max_chars else str(v)[:max_chars] + "…"))
            for k, v in rec.items()
        }
        preview.append({**clipped, "row": i})
    out = {
        "resultId": result.result_id, "ok": True, "count": len(res.records), "columns": result.columns,
        "preview": preview,
        "note": ("没有记录" if not res.records else
                 "预览内容已截断；判断和引用前必须用 query_result 读取完整列值"),
    }
    _record(ctx, "call_api", {"name": name, "args": clean_args},
            {"resultId": result.result_id, "count": len(res.records)},
            summary={"resultId": result.result_id, "ok": True, "count": len(res.records), "costMs": res.cost_ms})
    return out


async def _prepare_call_api(ctx: RunContext[RunDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    allowed = [a for a in ctx.deps.allowed_apis if a in ctx.deps.resources.apis]
    if not allowed:
        return None
    schema = json.loads(json.dumps(tool_def.parameters_json_schema))
    schema["properties"]["name"]["enum"] = allowed
    hints = "；".join(f"{a}（{ctx.deps.resources.apis[a].title}）：{ctx.deps.resources.apis[a].param_hint()}"
                     for a in allowed)
    return dataclasses.replace(tool_def, parameters_json_schema=schema,
                               description=f"{tool_def.description}\n可调用接口：{hints}")


# ============================================================================ query_result
class Condition(BaseModel):
    """筛选条件。"""

    column: str = Field(description="列名")
    op: Literal["equals", "contains", "notContains", "normalizedContains", "normalizedNotContains"] = Field(
        description="contains/notContains 原样比较；normalized* 先对两边做 normalize_text 再比较")
    value: str = Field(description="比较的值")
    before: str | None = Field(default=None, description="只比较该列中第一次出现这个子串之前的部分；没有该子串时比较全文")


class OrderBy(BaseModel):
    column: str
    desc: bool = True


def _match(cell: str, cond: Condition) -> bool:
    text = cell
    if cond.before and cond.before in text:
        text = text[: text.index(cond.before)]
    if cond.op == "equals":
        return text == cond.value
    if cond.op == "contains":
        return cond.value in text
    if cond.op == "notContains":
        return cond.value not in text
    if cond.op == "normalizedContains":
        return normalized_contains(text, cond.value)
    return not normalized_contains(text, cond.value)


async def query_result(ctx: RunContext[RunDeps], resultId: str, where: list[Condition] | None = None,
                       orderBy: OrderBy | None = None, limit: int = 20,
                       columns: list[str] | None = None) -> dict[str, Any]:
    """在接口结果中筛选记录，返回完整列值（引用证据时使用返回的 row）。多个条件之间是“并且”关系。

    Args:
        resultId: call_api 返回的 resultId。
        where: 筛选条件列表。
        orderBy: 排序列，默认倒序。
        limit: 最多返回多少行。
        columns: 只返回这些列；不填返回全部列。
    """
    deps = ctx.deps
    where = where or []
    limit = max(1, min(int(limit if limit is not None else 20), 100))
    args = {"resultId": resultId, "where": [c.model_dump(exclude_none=True) for c in where],
            "orderBy": orderBy.model_dump() if orderBy else None, "limit": limit}
    res = deps.workspace.results.get(resultId)
    if res is None:
        msg = f"resultId {resultId} 不存在，可用：{list(deps.workspace.results)}"
        return _fail_or_retry(ctx, "query_result", args, msg,
                              {"resultId": resultId, "ok": False, "error": msg, "total": 0, "rows": []})
    if not res.ok:
        out = {"resultId": resultId, "ok": False, "error": res.error, "total": 0, "rows": [],
               "note": "该接口调用失败，没有可筛选的记录"}
        _record(ctx, "query_result", args, {"ok": False, "error": res.error, "total": 0, "rows": []}, ok=False)
        return out
    all_cols = set().union(*(r.keys() for r in res.records)) if res.records else set(res.columns)
    for c in where:
        if res.records and c.column not in all_cols:
            msg = f"列 {c.column} 不存在，可用列：{sorted(all_cols)}"
            return _fail_or_retry(ctx, "query_result", args, msg,
                                  {"resultId": resultId, "ok": False, "error": msg, "total": 0, "rows": []})
    if orderBy and res.records and orderBy.column not in all_cols:
        msg = f"排序列 {orderBy.column} 不存在，可用列：{sorted(all_cols)}"
        return _fail_or_retry(ctx, "query_result", args, msg,
                              {"resultId": resultId, "ok": False, "error": msg, "total": 0, "rows": []})
    rows = [(i, r) for i, r in enumerate(res.records) if all(_match(_cell_text(r, c.column), c) for c in where)]
    if orderBy:
        rows.sort(key=lambda x: _cell_text(x[1], orderBy.column), reverse=orderBy.desc)
    out_rows = [{**({k: v for k, v in r.items() if k in columns} if columns else r), "row": i}
                for i, r in rows[:limit]]
    out = {"resultId": resultId, "total": len(rows), "rows": out_rows}
    _record(ctx, "query_result", args, {"total": len(rows), "rows": [r["row"] for r in out_rows]})
    return out


# ============================================================================ 文本与日期
async def normalize_text(ctx: RunContext[RunDeps], text: str, extraChars: str = "") -> dict[str, Any]:
    """文本清洗：Unicode NFKC 兼容归一化，删除固定的中英文标点，以及 extraChars 中的字符。

    Args:
        text: 待清洗文本。
        extraChars: 额外要删除的字符，例如空格和换行。
    """
    value = _normalize(text or "", extraChars or "")
    call_id = _record(ctx, "normalize_text", {"text": text, "extraChars": extraChars}, {"value": value})
    return {"callId": call_id, "value": value}


async def text_contains(ctx: RunContext[RunDeps], target: str, text: str | None = None, normalize: bool = True,
                        extraChars: str = "") -> dict[str, Any]:
    """判断文本是否包含目标串。不传 text 时在单据全文中查找。

    Args:
        target: 要查找的目标串。
        text: 被查找的文本；不传表示单据全文。
        normalize: 是否先对两边做 normalize_text 再比较。
        extraChars: normalize 时额外删除的字符。
    """
    source = ctx.deps.document if text is None else text
    target_s = target or ""
    extra_s = extraChars or ""
    if normalize:
        contains = normalized_contains(source, target_s, extra_s)
    else:
        contains = bool(target_s) and target_s in (source or "")
    out = {"contains": contains, "normalizedTarget": _normalize(target_s, extra_s) if normalize else target_s}
    call_id = _record(ctx, "text_contains", {"target": target, "text": "<单据全文>" if text is None else text,
                                             "normalize": normalize, "extraChars": extraChars}, out)
    return {"callId": call_id, **out}


async def date_range(ctx: RunContext[RunDeps], time: str, unit: Literal["day", "month"]) -> dict[str, Any]:
    """计算某个时间所在的那一天（或那个月）的开始和结束时间，格式 yyyyMMddHHmmss。

    Args:
        time: 至少包含 yyyyMMdd 的时间，如 20261105103012。
        unit: day 或 month。
    """
    try:
        start, end = _date_range(time, unit)
    except ValueError as exc:
        return _fail_or_retry(ctx, "date_range", {"time": time, "unit": unit}, str(exc),
                              {"ok": False, "error": str(exc)})
    call_id = _record(ctx, "date_range", {"time": time, "unit": unit}, {"start": start, "end": end})
    return {"callId": call_id, "start": start, "end": end}


async def format_date(ctx: RunContext[RunDeps], value: str, fromPattern: str, toPattern: str) -> dict[str, Any]:
    """日期格式转换（Java 风格格式：yyyy、MM、M、dd、d、HH、mm、ss）。结果可作为 derive 证据引用 callId。

    Args:
        value: 原日期文本，如 20261005。
        fromPattern: 原格式，如 yyyyMMdd。
        toPattern: 目标格式，如 yyyy年M月d号。
    """
    try:
        out = convert_date(value, fromPattern, toPattern)
    except ValueError as exc:
        _record(ctx, "format_date", {"value": value, "fromPattern": fromPattern, "toPattern": toPattern},
                {"error": str(exc)}, ok=False)
        return {"ok": False, "error": str(exc)}
    call_id = _record(ctx, "format_date", {"value": value, "fromPattern": fromPattern, "toPattern": toPattern},
                      {"value": out})
    return {"callId": call_id, "ok": True, "value": out}


def build_tools(tool_retries: int) -> list[Tool[RunDeps]]:
    """本平台提供给模型的全部工具。"""
    return [
        Tool(load_skill, prepare=_prepare_load_skill, max_retries=tool_retries),
        Tool(call_api, prepare=_prepare_call_api, max_retries=tool_retries),
        Tool(query_result, max_retries=tool_retries),
        Tool(normalize_text, max_retries=tool_retries),
        Tool(text_contains, max_retries=tool_retries),
        Tool(date_range, max_retries=tool_retries),
        Tool(format_date, max_retries=tool_retries),
    ]
