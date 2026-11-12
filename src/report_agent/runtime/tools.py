"""平台通用工具：模型只能通过这些工具与外界交互，工具本身不含任何业务规则。

#Created By AiCoding(codex)
  load_skill     读取 Skill 说明（只能读模板允许的 Skill）
  call_api       调用已声明的接口（只能调模板 Skill 声明的接口），返回摘要和 resultId
  query_result   在单个或多个接口结果中按条件筛选（支持 startsWith、between、prefixLen、anyOf、resultIds），返回完整列值
  normalize_text 文本清洗；text_contains 包含判断；date_range 起止时间；format_date 日期格式转换
  extract_dates  严格日历日期扫描；date_shift 日期偏移与窗口；expand_period 账期/区间展开；time_diff 秒级时间差；regex_extract 安全正则提取
每次调用都分配 callId（t1、t2…），可作为 derive 证据或空列表查询证据引用。
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext, Tool, ToolDefinition

from ..gateway.base import ApiCallResult
from .deps import RunDeps
from .text_tools import (
    convert_date,
    date_range as _date_range,
    date_shift as _date_shift,
    expand_period as _expand_period,
    extract_dates as _extract_dates,
    normalize_text as _normalize,
    regex_extract as _regex_extract,
    time_diff as _time_diff,
)
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
    call_id = _record(ctx, tool, args, {"error": message}, ok=False)
    if ctx.retry < ctx.max_retries:
        raise ModelRetry(message)
    if isinstance(fallback, dict) and "callId" not in fallback:
        return {"callId": call_id, **fallback}
    return fallback


def _cell_text(row: dict[str, Any], col: str) -> str:
    val = row.get(col)
    return "" if val is None else str(val)


def _render_skill_block(deps: RunDeps, skill_id: str) -> str:
    """组装单个 Skill 的说明文本及关联接口提示。#Created By AiCoding(codex)"""
    skill = deps.resources.skills[skill_id]
    apis = [a for a in skill.meta.apis if a in deps.resources.apis]
    api_lines = "\n".join(
        f"- {a}（{deps.resources.apis[a].title}）参数：{deps.resources.apis[a].param_hint()}"
        for a in apis
    )
    return f"# Skill：{skill.title}（{skill.id}）\n\n{skill.body}\n\n" + (
        f"## 本 Skill 可调用的接口\n{api_lines}\n" if api_lines else ""
    )


# ============================================================================ load_skill
async def load_skill(ctx: RunContext[RunDeps], name: str = "", names: list[str] | None = None) -> str:
    """读取一个或多个 Skill 的完整说明。需要查询或判断某类字段前先读取对应 Skill。#Created By AiCoding(codex)

    Args:
        name: 单个 Skill 标识，只能是“可用 Skill”中列出的标识。
        names: 可选批量加载的 Skill 标识列表，一次返回多个 Skill 的说明。
    """
    deps = ctx.deps
    raw_names: list[str] = []
    if name and str(name).strip():
        raw_names.append(str(name).strip())
    if names:
        for item in names:
            if item is not None and str(item).strip():
                raw_names.append(str(item).strip())
    req_names = list(dict.fromkeys(raw_names))

    if not req_names:
        rec_args = {"name": name} if names is None else {"name": name, "names": list(names)}
        msg = f"请指定要加载的 Skill（name 或 names），可用：{deps.allowed_skills}"
        return _fail_or_retry(ctx, "load_skill", rec_args, msg, f"错误：{msg}")

    bad = [s for s in req_names if s not in deps.allowed_skills or s not in deps.resources.skills]
    if bad:
        rec_args = {"name": name} if names is None else (
            {"name": name, "names": list(names)} if name else {"names": list(names)}
        )
        msg = (
            f"Skill「{bad[0]}」不可用，只能加载：{deps.allowed_skills}"
            if len(bad) == 1
            else f"Skill {bad} 不可用，只能加载：{deps.allowed_skills}"
        )
        return _fail_or_retry(ctx, "load_skill", rec_args, msg, f"错误：{msg}")

    for s in req_names:
        if s not in deps.workspace.loaded_skills:
            deps.workspace.loaded_skills.append(s)

    if names is None and len(req_names) == 1:
        skill = deps.resources.skills[req_names[0]]
        _record(ctx, "load_skill", {"name": req_names[0]}, {"title": skill.title}, summary={"title": skill.title})
        return _render_skill_block(deps, req_names[0])

    titles = [deps.resources.skills[s].title for s in req_names]
    rec_args = {"name": name, "names": req_names} if name else {"names": req_names}
    rec_out = {"titles": titles} if len(titles) > 1 else {"title": titles[0], "titles": titles}
    _record(ctx, "load_skill", rec_args, rec_out, summary=rec_out)
    return "\n---\n\n".join(_render_skill_block(deps, s) for s in req_names)


async def _prepare_load_skill(ctx: RunContext[RunDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    allowed = [s for s in ctx.deps.allowed_skills if s in ctx.deps.resources.skills]
    if not allowed:
        return None
    orig = tool_def.parameters_json_schema
    orig_props = orig.get("properties") or {}
    props = dict(orig_props)
    if "name" in props:
        name_prop = {k: v for k, v in props["name"].items() if k != "default"}
        name_prop["enum"] = allowed
        props["name"] = name_prop
    if "names" in props:
        names_prop = dict(props["names"])
        if "anyOf" in names_prop:
            names_prop["anyOf"] = [
                {**branch, "items": {**(branch.get("items") or {}), "enum": allowed}}
                if isinstance(branch, dict) and branch.get("type") == "array"
                else branch
                for branch in names_prop["anyOf"]
            ]
        elif "items" in names_prop and isinstance(names_prop["items"], dict):
            names_prop["items"] = {**names_prop["items"], "enum": allowed}
        props["names"] = names_prop
    schema = {**orig, "properties": props}
    return dataclasses.replace(tool_def, parameters_json_schema=schema)


def _format_api_success_payload(contract: Any, result: ApiResult, default_preview_rows: int) -> dict[str, Any]:
    """根据已缓存或新获取的成功 ApiResult 生成返回给模型的摘要字典（不含 callId）。#Created By AiCoding(codex)"""
    max_chars = contract.response.summary.maxPreviewChars
    n_preview = contract.preview_rows(default_preview_rows)
    preview = []
    for i, rec in enumerate(result.records[:n_preview]):
        clipped = {
            k: ("" if v is None else (str(v) if len(str(v)) <= max_chars else str(v)[:max_chars] + "…"))
            for k, v in rec.items()
        }
        preview.append({**clipped, "row": i})
    if contract.response.records.mode == "none" and result.ok and not result.no_data:
        note = "接口调用成功（该契约声明无业务记录体）"
    elif not result.records:
        note = "没有记录"
    else:
        note = "预览内容已截断；判断和引用前必须用 query_result 读取完整列值"
    return {
        "resultId": result.result_id,
        "ok": True,
        "count": len(result.records),
        "columns": result.columns,
        "preview": preview,
        "note": note,
    }


def _record_cached_api_hit(
    ctx: RunContext[RunDeps],
    name: str,
    clean_args: dict[str, Any],
    contract: Any,
    hit: ApiResult,
) -> dict[str, Any]:
    """记录并组装幂等缓存或在途复用命中的 call_api 返回值。#Created By AiCoding(codex)"""
    payload = _format_api_success_payload(contract, hit, ctx.deps.settings.agent_preview_rows)
    call_id = _record(
        ctx,
        "call_api",
        {"name": name, "args": clean_args},
        {"resultId": hit.result_id, "count": len(hit.records)},
        summary={"resultId": hit.result_id, "ok": True, "count": len(hit.records), "costMs": 0},
    )
    return {"callId": call_id, **payload}


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

    ws = deps.workspace
    cache_key: tuple[str, str] | None = None
    if contract.idempotent:
        cache_key = (name, json.dumps(clean_args, sort_keys=True, ensure_ascii=False, default=str))
        seen_inflight: set[int] = set()
        while True:
            cached = ws._idempotent_cache.get(cache_key)
            if cached is not None:
                return _record_cached_api_hit(ctx, name, clean_args, contract, cached)
            inflight = ws._idempotent_inflight.get(cache_key)
            if inflight is None or id(inflight) in seen_inflight:
                break
            seen_inflight.add(id(inflight))
            try:
                shared = await asyncio.shield(inflight)
            except asyncio.CancelledError:
                # 若当前任务自身已被取消则向上抛出；若是前序并发调用单独被取消，则由当前存活任务接手执行
                cur_task = asyncio.current_task()
                if cur_task is None or cur_task.cancelling() > 0:
                    raise
                continue
            if shared.ok:
                return _record_cached_api_hit(ctx, name, clean_args, contract, shared)

    fut: asyncio.Future[ApiResult] | None = None
    if cache_key is not None and cache_key not in ws._idempotent_inflight:
        fut = asyncio.get_running_loop().create_future()
        ws._idempotent_inflight[cache_key] = fut

    try:
        t0 = time.monotonic()
        try:
            res = await deps.gateway.invoke(contract, clean_args)
        except Exception as exc:  # noqa: BLE001 - 网关意外异常转为结构化错误记录
            log.warning("网关调用未预期异常 api=%s：%s", name, exc)
            res = ApiCallResult(ok=False, error=f"网关调用异常：{type(exc).__name__} {exc}".strip(),
                                cost_ms=int((time.monotonic() - t0) * 1000))
        result = ApiResult(
            result_id=ws.next_result_id(), api=name, title=contract.title, args=clean_args, ok=res.ok,
            error=res.error, columns=dict(contract.response.records.columns), records=res.records,
            cost_ms=res.cost_ms, raw=res.raw, request_preview=res.request_preview, no_data=res.no_data,
        )
        ws.add_result(result)
        if cache_key is not None and result.ok:
            ws._idempotent_cache[cache_key] = result
        if fut is not None and not fut.done():
            fut.set_result(result)
    except BaseException:
        if fut is not None and not fut.done():
            fut.cancel()
        raise
    finally:
        if fut is not None and cache_key is not None and ws._idempotent_inflight.get(cache_key) is fut:
            ws._idempotent_inflight.pop(cache_key, None)

    if not result.ok:
        base_err = {
            "resultId": result.result_id,
            "ok": False,
            "error": result.error,
            "note": "接口调用失败，请如实按找不到处理并写明原因，不要猜测数据",
        }
        call_id = _record(ctx, "call_api", {"name": name, "args": clean_args}, base_err, ok=False,
                          summary={**base_err, "costMs": result.cost_ms})
        return {"callId": call_id, **base_err}

    payload = _format_api_success_payload(contract, result, deps.settings.agent_preview_rows)
    call_id = _record(
        ctx, "call_api", {"name": name, "args": clean_args},
        {"resultId": result.result_id, "count": len(result.records)},
        summary={"resultId": result.result_id, "ok": True, "count": len(result.records), "costMs": result.cost_ms},
    )
    return {"callId": call_id, **payload}


async def _prepare_call_api(ctx: RunContext[RunDeps], tool_def: ToolDefinition) -> ToolDefinition | None:
    allowed = [a for a in ctx.deps.allowed_apis if a in ctx.deps.resources.apis]
    if not allowed:
        return None
    orig = tool_def.parameters_json_schema
    orig_props = orig.get("properties") or {}
    props = {**orig_props, "name": {**(orig_props.get("name") or {}), "enum": allowed}}
    schema = {**orig, "properties": props}
    hints = "；".join(f"{a}（{ctx.deps.resources.apis[a].title}）：{ctx.deps.resources.apis[a].param_hint()}"
                     for a in allowed)
    return dataclasses.replace(tool_def, parameters_json_schema=schema,
                               description=f"{tool_def.description}\n可调用接口：{hints}")


# ============================================================================ query_result
class Condition(BaseModel):
    """筛选条件。#Created By AiCoding(codex)"""

    column: str = Field(description="列名")
    op: Literal[
        "equals",
        "contains",
        "notContains",
        "normalizedContains",
        "normalizedNotContains",
        "startsWith",
        "between",
    ] = Field(
        description=(
            "equals/contains/notContains/startsWith/between 原样比较；"
            "normalized* 先对两边做 normalize_text 再比较；between 为闭区间 [value, endValue]"
        )
    )
    value: str = Field(description="比较的值（op=between 时为下限值，含）")
    before: str | None = Field(default=None, description="只比较该列中第一次出现这个子串之前的部分；没有该子串时比较全文")
    endValue: str | None = Field(default=None, description="op=between 时的上限值（含）")
    prefixLen: int | None = Field(default=None, description="先截取列值前 prefixLen 个字符再比较，如 payDatetime 取前 8 位日期")


class OrderBy(BaseModel):
    column: str
    desc: bool = True


def _validate_condition_params(conditions: list[Condition]) -> str | None:
    """校验筛选条件自身参数合法性，非法时返回错误描述。#Created By AiCoding(codex)"""
    for cond in conditions:
        if cond.prefixLen is not None and (isinstance(cond.prefixLen, bool) or cond.prefixLen <= 0):
            return f"列 {cond.column} 的 prefixLen 必须是正整数"
        if cond.op == "between":
            if cond.endValue is None or cond.endValue == "":
                return f"列 {cond.column} 使用 op=between 时必须提供非空 endValue"
            if cond.value > cond.endValue:
                return f"列 {cond.column} 的 between 下限 {cond.value!r} 不能大于上限 {cond.endValue!r}"
    return None


def _match(cell: str, cond: Condition, *, norm_value: str | None = None) -> bool:
    """按单个 Condition 判断单元格文本是否命中（支持预计算的归一化目标串减少重复开销）。#Created By AiCoding(codex)"""
    text = cell
    if cond.before and cond.before in text:
        text = text[: text.index(cond.before)]
    if cond.prefixLen is not None and cond.prefixLen > 0:
        if cond.op == "between" and len(text) < cond.prefixLen:
            return False
        text = text[: cond.prefixLen]
    if cond.op == "equals":
        return text == cond.value
    if cond.op == "startsWith":
        return text.startswith(cond.value)
    if cond.op == "between":
        return bool(cond.endValue) and cond.value <= text <= cond.endValue
    if cond.op == "contains":
        return cond.value in text
    if cond.op == "notContains":
        return cond.value not in text
    t_norm = _normalize(cond.value) if norm_value is None else norm_value
    hit = bool(t_norm) and t_norm in _normalize(text)
    return hit if cond.op == "normalizedContains" else not hit


def _validate_query_columns(
    results_list: list[ApiResult],
    where_list: list[Condition],
    any_list: list[Condition],
    order_by: OrderBy | None,
    columns: list[str] | None,
) -> str | None:
    """统一校验单表与多表合并模式下的筛选列、排序列与投影列是否存在。#Created By AiCoding(codex)"""
    all_cols: set[str] = set()
    for r in results_list:
        all_cols.update(r.columns.keys())
        for rec in r.records:
            all_cols.update(rec.keys())
    if not all_cols:
        return None
    sorted_cols = sorted(all_cols)
    for c in (*where_list, *any_list):
        if c.column not in all_cols:
            return f"列 {c.column} 不存在，可用列：{sorted_cols}"
    if order_by and order_by.column not in all_cols:
        return f"排序列 {order_by.column} 不存在，可用列：{sorted_cols}"
    if columns:
        bad_cols = [col for col in columns if col not in all_cols]
        if bad_cols:
            return f"投影列 {', '.join(bad_cols)} 不存在，可用列：{sorted_cols}"
    return None


def _filter_and_sort_records(
    results_list: list[ApiResult],
    where_list: list[Condition],
    any_list: list[Condition],
    order_by: OrderBy | None,
) -> list[tuple[str, int, dict[str, Any]]]:
    """对一个或多个成功接口结果执行 AND/OR 筛选与统一排序（预归一化条件常量）。#Created By AiCoding(codex)"""
    where_pairs = [(c, _normalize(c.value) if c.op.startswith("normalized") else None) for c in where_list]
    any_pairs = [(c, _normalize(c.value) if c.op.startswith("normalized") else None) for c in any_list]
    matched: list[tuple[str, int, dict[str, Any]]] = []
    for res in results_list:
        for i, rec in enumerate(res.records):
            if where_pairs and not all(_match(_cell_text(rec, c.column), c, norm_value=nv) for c, nv in where_pairs):
                continue
            if any_pairs and not any(_match(_cell_text(rec, c.column), c, norm_value=nv) for c, nv in any_pairs):
                continue
            matched.append((res.result_id, i, rec))
    if order_by:
        matched.sort(key=lambda x: _cell_text(x[2], order_by.column), reverse=order_by.desc)
    return matched


async def query_result(
    ctx: RunContext[RunDeps],
    resultId: str = "",
    where: list[Condition] | None = None,
    orderBy: OrderBy | None = None,
    limit: int = 20,
    columns: list[str] | None = None,
    *,
    anyOf: list[Condition] | None = None,
    resultIds: list[str] | None = None,
) -> dict[str, Any]:
    """在接口结果中筛选记录，返回完整列值（引用证据时使用返回的 row）。#Created By AiCoding(codex)

    where 内多个条件之间为“并且”关系；传入 anyOf 时还需满足 anyOf 中至少一个条件（“或者”关系）。
    传入非空 resultIds 时支持跨多个接口结果合并筛选与统一排序，每行额外携带来源 resultId。

    Args:
        resultId: 单个 call_api 返回的 resultId（与 resultIds 二选一）。
        where: AND 筛选条件列表。
        orderBy: 排序列，默认倒序。
        limit: 最多返回多少行（1~100）。
        columns: 只返回这些列；不填返回全部列。
        anyOf: 可选 OR 筛选条件列表，行需满足至少一项。
        resultIds: 可选多结果合并模式的 resultId 列表。
    """
    deps = ctx.deps
    where_list = where or []
    any_list = anyOf or []
    multi_mode = bool(resultIds)
    rids = list(dict.fromkeys(str(r).strip() for r in (resultIds or []))) if multi_mode else []

    if isinstance(limit, bool):
        msg = "limit 必须是正整数"
        bad_args: dict[str, Any] = {"resultIds": rids} if multi_mode else {"resultId": resultId}
        bad_args["limit"] = limit
        fallback = {**({"resultIds": rids} if multi_mode else {"resultId": resultId}), "ok": False, "error": msg, "total": 0, "rows": []}
        return _fail_or_retry(ctx, "query_result", bad_args, msg, fallback)
    limit = max(1, min(int(limit if limit is not None else 20), 100))

    args: dict[str, Any] = {
        "where": [c.model_dump(exclude_none=True) for c in where_list],
        "orderBy": orderBy.model_dump() if orderBy else None,
        "limit": limit,
    }
    if multi_mode:
        args["resultIds"] = rids
        if resultId:
            args["resultId"] = resultId
    else:
        args["resultId"] = resultId
    if any_list:
        args["anyOf"] = [c.model_dump(exclude_none=True) for c in any_list]
    if columns is not None:
        args["columns"] = list(columns)

    def _err_payload(err_msg: str) -> dict[str, Any]:
        key_part = {"resultIds": rids} if multi_mode else {"resultId": resultId}
        return {**key_part, "ok": False, "error": err_msg, "total": 0, "rows": []}

    cond_err = _validate_condition_params([*where_list, *any_list])
    if cond_err:
        return _fail_or_retry(ctx, "query_result", args, cond_err, _err_payload(cond_err))

    proj_cols = set(columns) if columns else None

    if multi_mode:
        if any(not rid for rid in rids):
            msg = "resultIds 中不能包含空字符串"
            return _fail_or_retry(ctx, "query_result", args, msg, _err_payload(msg))
        missing_rids = [rid for rid in rids if rid not in deps.workspace.results]
        if missing_rids:
            msg = f"resultId {', '.join(missing_rids)} 不存在，可用：{list(deps.workspace.results)}"
            return _fail_or_retry(ctx, "query_result", args, msg, _err_payload(msg))
        results_list = [deps.workspace.results[rid] for rid in rids]
        failed_res = [r for r in results_list if not r.ok]
        if failed_res:
            err = "；".join(f"{r.result_id} 调用失败：{r.error or '未知错误'}" for r in failed_res)
            call_id = _record(ctx, "query_result", args, {"ok": False, "error": err, "total": 0, "rows": []}, ok=False)
            return {
                "callId": call_id,
                "resultIds": rids, "ok": False, "error": err, "total": 0, "rows": [],
                "note": "存在调用失败的接口结果，没有可合并筛选的记录",
            }
        col_err = _validate_query_columns(results_list, where_list, any_list, orderBy, columns)
        if col_err:
            return _fail_or_retry(ctx, "query_result", args, col_err, _err_payload(col_err))
        merged_rows = _filter_and_sort_records(results_list, where_list, any_list, orderBy)
        out_rows = [
            {
                **({k: v for k, v in rec.items() if k in proj_cols} if proj_cols else rec),
                "resultId": rid,
                "row": i,
            }
            for rid, i, rec in merged_rows[:limit]
        ]
        call_id = _record(
            ctx, "query_result", args,
            {"total": len(merged_rows), "rows": [{"resultId": r["resultId"], "row": r["row"]} for r in out_rows]},
        )
        return {"callId": call_id, "resultIds": rids, "total": len(merged_rows), "rows": out_rows}

    if not resultId:
        msg = f"resultId 不能为空（或传入非空 resultIds），可用：{list(deps.workspace.results)}"
        return _fail_or_retry(ctx, "query_result", args, msg, _err_payload(msg))
    res = deps.workspace.results.get(resultId)
    if res is None:
        msg = f"resultId {resultId} 不存在，可用：{list(deps.workspace.results)}"
        return _fail_or_retry(ctx, "query_result", args, msg, _err_payload(msg))
    if not res.ok:
        call_id = _record(ctx, "query_result", args, {"ok": False, "error": res.error, "total": 0, "rows": []}, ok=False)
        return {"callId": call_id, "resultId": resultId, "ok": False, "error": res.error, "total": 0, "rows": [],
                "note": "该接口调用失败，没有可筛选的记录"}
    col_err = _validate_query_columns([res], where_list, any_list, orderBy, columns)
    if col_err:
        return _fail_or_retry(ctx, "query_result", args, col_err, _err_payload(col_err))
    matched_rows = _filter_and_sort_records([res], where_list, any_list, orderBy)
    out_rows = [
        {**({k: v for k, v in rec.items() if k in proj_cols} if proj_cols else rec), "row": i}
        for _, i, rec in matched_rows[:limit]
    ]
    call_id = _record(ctx, "query_result", args, {"total": len(matched_rows), "rows": [r["row"] for r in out_rows]})
    return {"callId": call_id, "resultId": resultId, "total": len(matched_rows), "rows": out_rows}


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
    """判断文本是否包含目标串。不传 text 时在单据全文中查找。#Created By AiCoding(codex)

    normalize=True 时默认一并剥离半角/全角空格、制表符与换行符，兼容跨行折行 PDF 业务名匹配。

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
        effective_extra = extra_s + " \t\r\n\u3000"
        norm_target = _normalize(target_s, effective_extra)
        contains = bool(norm_target) and norm_target in _normalize(source, effective_extra)
    else:
        contains = bool(target_s) and target_s in (source or "")
        norm_target = target_s
    out = {"contains": contains, "normalizedTarget": norm_target}
    call_id = _record(ctx, "text_contains", {"target": target, "text": "<单据全文>" if text is None else text,
                                             "normalize": normalize, "extraChars": extraChars}, out)
    return {"callId": call_id, **out}


async def date_range(ctx: RunContext[RunDeps], time: str, unit: Literal["day", "month"]) -> dict[str, Any]:
    """计算某个时间所在的那一天（或那个月）的开始和结束时间，格式 yyyyMMddHHmmss。

    Args:
        time: 包含合法日期（unit=month 时也支持 yyyyMM / yyyy-M / yyyy年M月）的时间文本。
        unit: day 或 month。
    """
    try:
        start, end = _date_range(time, unit)
    except ValueError as exc:
        return _fail_or_retry(ctx, "date_range", {"time": time, "unit": unit}, str(exc),
                              {"ok": False, "error": str(exc)})
    call_id = _record(ctx, "date_range", {"time": time, "unit": unit}, {"start": start, "end": end})
    return {"callId": call_id, "start": start, "end": end}


async def format_date(
    ctx: RunContext[RunDeps],
    value: str = "",
    fromPattern: str = "",
    toPattern: str = "",
    values: list[str] | None = None,
) -> dict[str, Any]:
    """日期格式转换（Java 风格格式：yyyy、MM、M、dd、d、HH、mm、ss）。结果可作为 derive 证据引用 callId。#Created By AiCoding(codex)

    支持单值 value 转换（返回 value）或 values 列表批量转换（返回 values）。

    Args:
        value: 原日期文本，如 20261005（与 values 二选一或同时传入）。
        fromPattern: 原格式，如 yyyyMMdd。
        toPattern: 目标格式，如 yyyy年M月d号。
        values: 可选批量转换的原日期文本列表。
    """
    rec_args: dict[str, Any] = (
        {"value": value, "fromPattern": fromPattern, "toPattern": toPattern}
        if values is None
        else {**({"value": value} if value else {}), "values": list(values),
              "fromPattern": fromPattern, "toPattern": toPattern}
    )
    try:
        if values is not None:
            if not values:
                raise ValueError("values 不能为空列表")
            converted = [convert_date(v, fromPattern, toPattern) for v in values]
            payload: dict[str, Any] = {"values": converted}
            if value:
                payload["value"] = convert_date(value, fromPattern, toPattern)
            call_id = _record(ctx, "format_date", rec_args, payload)
            return {"callId": call_id, "ok": True, **payload}
        out = convert_date(value, fromPattern, toPattern)
    except ValueError as exc:
        return _fail_or_retry(ctx, "format_date", rec_args, str(exc), {"ok": False, "error": str(exc)})
    call_id = _record(ctx, "format_date", rec_args, {"value": out})
    return {"callId": call_id, "ok": True, "value": out}


async def extract_dates(
    ctx: RunContext[RunDeps],
    text: str | None = None,
    defaultYear: str | int | None = None,
) -> dict[str, Any]:
    """从文本中按严格规则扫描并经真实日历校验提取日期（yyyyMMdd）。不传 text 时扫描单据全文。#Created By AiCoding(codex)

    绝不把字母数字混合编号（如 25JS206149）、11 位手机号或流水号子串误识别为日期；非法日历日期（如 2 月 30 日）自动剔除。

    Args:
        text: 待提取日期的文本；不传时取单据全文。
        defaultYear: 无年份前缀的“M月d日/号”使用的默认年份来源（可传 4 位年份、日期或创建时间如 20261005103000）。
    """
    source = ctx.deps.document if text is None else text
    out = _extract_dates(source, defaultYear=defaultYear)
    call_id = _record(
        ctx,
        "extract_dates",
        {"text": "<单据全文>" if text is None else text, "defaultYear": defaultYear},
        out,
    )
    return {"callId": call_id, "ok": True, **out}


async def date_shift(
    ctx: RunContext[RunDeps],
    date: str,
    days: int = 0,
    endDays: int | None = None,
) -> dict[str, Any]:
    """按基准日期与天数偏移计算目标日期及起止时间窗口（yyyyMMdd000000 ~ yyyyMMdd235959）。#Created By AiCoding(codex)

    Args:
        date: 基准日期，支持 yyyyMMdd、yyyyMMddHHmmss、yyyy-M-d、yyyy/M/d、yyyy.M.d、yyyy年M月d日/号。
        days: 起始日期相对基准日的偏移天数（负数表示往前，0 表示当天）。
        endDays: 结束日期相对基准日的偏移天数；不传时与 days 相同。
    """
    args = {"date": date, "days": days, "endDays": endDays}
    try:
        out = _date_shift(date, days=days, endDays=endDays)
    except ValueError as exc:
        return _fail_or_retry(ctx, "date_shift", args, str(exc), {"ok": False, "error": str(exc)})
    call_id = _record(ctx, "date_shift", args, out)
    return {"callId": call_id, "ok": True, **out}


async def expand_period(ctx: RunContext[RunDeps], period: str) -> dict[str, Any]:
    """解析账期、单日或日期/年月区间，展开涉及的月份列表（yyyyMM）及总体起止时间窗口。#Created By AiCoding(codex)

    支持多账期分隔（如 202610$202611、202610,202611）、区间（如 20260705-20260808、202607-202609、2026-07-05~2026-08-08）、
    纯年月（如 202607、2026-07、2026年7月）与具体日期/时间戳（如 20260705、20260705103000）。

    Args:
        period: 账期、日期或区间文本。
    """
    args = {"period": period}
    try:
        out = _expand_period(period)
    except ValueError as exc:
        return _fail_or_retry(ctx, "expand_period", args, str(exc), {"ok": False, "error": str(exc)})
    call_id = _record(ctx, "expand_period", args, out)
    return {"callId": call_id, "ok": True, **out}


async def time_diff(ctx: RunContext[RunDeps], time1: str, time2: str) -> dict[str, Any]:
    """精确计算两个时间戳的秒级差值（time1 - time2）。#Created By AiCoding(codex)

    Args:
        time1: 第一个时间戳（支持 yyyyMMddHHmmss、yyyy-M-d HH:mm:ss、yyyy/M/d HH:mm:ss）。
        time2: 第二个时间戳（支持格式同 time1）。
    """
    args = {"time1": time1, "time2": time2}
    try:
        out = _time_diff(time1, time2)
    except ValueError as exc:
        return _fail_or_retry(ctx, "time_diff", args, str(exc), {"ok": False, "error": str(exc)})
    call_id = _record(ctx, "time_diff", args, out)
    return {"callId": call_id, "ok": True, **out}


async def regex_extract(
    ctx: RunContext[RunDeps],
    pattern: str,
    text: str | None = None,
    group: int = 1,
) -> dict[str, Any]:
    """用正则表达式从文本中提取非空匹配内容。不传 text 时在单据全文中查找。#Created By AiCoding(codex)

    Args:
        pattern: 正则表达式；含括号时默认提取第 1 个捕获组，无括号且 group=1 时自动提取整段匹配。
        text: 待匹配文本；不传时取单据全文。
        group: 捕获组下标（0 表示整段匹配，默认 1）。
    """
    source = ctx.deps.document if text is None else text
    args = {"pattern": pattern, "text": "<单据全文>" if text is None else text, "group": group}
    try:
        out = _regex_extract(pattern, source, group=group)
    except ValueError as exc:
        return _fail_or_retry(ctx, "regex_extract", args, str(exc), {"ok": False, "error": str(exc)})
    call_id = _record(ctx, "regex_extract", args, out)
    return {"callId": call_id, "ok": True, **out}


def build_tools(tool_retries: int) -> list[Tool[RunDeps]]:
    """本平台提供给模型的全部工具。#Created By AiCoding(codex)"""
    return [
        Tool(load_skill, prepare=_prepare_load_skill, max_retries=tool_retries),
        Tool(call_api, prepare=_prepare_call_api, max_retries=tool_retries),
        Tool(query_result, max_retries=tool_retries),
        Tool(normalize_text, max_retries=tool_retries),
        Tool(text_contains, max_retries=tool_retries),
        Tool(date_range, max_retries=tool_retries),
        Tool(format_date, max_retries=tool_retries),
        Tool(extract_dates, max_retries=tool_retries),
        Tool(date_shift, max_retries=tool_retries),
        Tool(expand_period, max_retries=tool_retries),
        Tool(time_diff, max_retries=tool_retries),
        Tool(regex_extract, max_retries=tool_retries),
    ]
