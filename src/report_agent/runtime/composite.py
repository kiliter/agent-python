"""复合工单运行时编排：单号码多商品 × 多模板并发核查、跨子项幂等网关去重、Jinja2 确定性拼装与大模型二次润色。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import copy
from dataclasses import dataclass, field
import json
import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, ModelRetry, UsageLimits

from ..domain.api_contract import ApiContract
from ..domain.composite import (
    DEFAULT_COMPOSITE_TEMPLATE,
    build_composite_summary,
    render_composite_report,
)
from ..domain.sanitize import sanitize_sensitive_text
from ..gateway.base import ApiCallResult, GatewayClient
from ..store.runs import new_run_id
from .model_factory import build_output_spec
from .router import TemplateRouteError
from .runner import AgentRunner, Entry, InputValidationError, RunRequest, TemplateUnavailable
from .singleflight import IdempotentSingleFlight
from .workspace import ProcessEvent

log = logging.getLogger(__name__)

MAX_COMPOSITE_ITEMS = 20
POLISH_TIMEOUT_S = 90.0

_STATUS_LABEL = {
    "SUCCESS": "成功",
    "PARTIAL": "部分缺失",
    "FAILED": "失败",
    "CANCELLED": "已取消",
}

POLISH_SYSTEM_PROMPT = """你是「智能申告报告填写平台」的复合工单汇总润色助手。

你会收到一份已经由多个强证据核查子模板通过 Jinja2 确定性拼装生成的复合工单报告。
你的职责是对这份汇总报告做**二次润色与衔接优化**，使其通顺、精炼、专业，可直接作为面向申诉平台的正式答复。

## 严格红线（绝对不可违反）
1. **零事实篡改、零编造**：严禁修改、删减或凭空添加任何手机号码、工单号、业务/套餐/活动名称、资费金额、办理时间、短信原文、订单流水号、违约金或查证结论。
2. **保留全部待补占位与缺失说明**：原文中若存在 `{{字段名}}` 占位符或“未查询到/核查未完成”的项，必须如实保留，绝不能自行编造填满。
3. **仅做语篇优化**：可以合并各子报告之间高度重复的开场客套或落款，提炼 1~2 句总述，优化段落编号与过渡句，确保覆盖原始报告中的每一项商品核查事实。
4. 直接输出完整的润色后 Markdown 正文，不要在正文外附加解释性前后缀。"""


class CompositePolishOutput(BaseModel):
    """复合报告二次润色结构化输出。"""

    model_config = ConfigDict(extra="forbid")

    markdown: str = Field(description="二次润色后的完整 Markdown 汇总报告正文")


class SharedGatewayClient(GatewayClient):
    """单次复合工单运行内的幂等网关缓存包装器：跨子项并发去重并统计命中次数。#Created By AiCoding(codex)"""

    def __init__(self, inner: GatewayClient) -> None:
        self._inner = inner
        self._singleflight: IdempotentSingleFlight[tuple[str, str], ApiCallResult] = IdempotentSingleFlight(
            is_success=lambda r: r.ok,
            to_cached=lambda r: self._clone_result(r, cached=False),
        )
        self._cache = self._singleflight.cache
        self._inflight = self._singleflight.inflight
        self.cache_hits = 0

    @staticmethod
    def _clone_result(res: ApiCallResult, *, cached: bool = False) -> ApiCallResult:
        return ApiCallResult(
            ok=res.ok,
            records=copy.deepcopy(res.records),
            raw=res.raw,
            error=res.error,
            cost_ms=0 if cached else res.cost_ms,
            http_status=res.http_status,
            request_preview=res.request_preview,
            no_data=res.no_data,
        )

    async def invoke(self, contract: ApiContract, args: dict[str, Any]) -> ApiCallResult:
        if not contract.idempotent:
            return await self._inner.invoke(contract, args)

        cache_key = (contract.name, json.dumps(args, sort_keys=True, ensure_ascii=False, default=str))
        res, reused = await self._singleflight.do(cache_key, lambda: self._inner.invoke(contract, args))
        if reused and res.ok:
            self.cache_hits += 1
        return self._clone_result(res, cached=reused)


@dataclass
class CompositeItemRequest:
    """复合工单中的单个业务/商品子项（template_id 为 None 时自动路由匹配）。"""

    template_id: int | None = None
    params: dict[str, str] = field(default_factory=dict)
    document: str | None = None
    label: str = ""


@dataclass
class CompositeRunRequest:
    """复合工单运行请求：公共工单信息 + 多商品子项列表。"""

    items: list[CompositeItemRequest]
    order: dict[str, str] = field(default_factory=dict)
    document: str = ""
    polish: bool = False
    polish_instruction: str = ""
    composite_template: str | None = None
    target: Literal["online", "draft"] = "online"
    entry: Entry = "上游调用"
    operator: str = ""
    batch_no: str | None = None
    composite_run_id: str | None = None


class CompositeRunner:
    """复合工单编排器：复用 AgentRunner 单模板强证据管道，统一拼装与可选二次润色。#Created By AiCoding(codex)"""

    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner
        self._cached_polish_agent: tuple[tuple[Any, ...], Any, Any, Agent[None, CompositePolishOutput]] | None = None

    def _get_or_build_polish_agent(self) -> tuple[Agent[None, CompositePolishOutput], Any]:
        """按运行期配置快照 _bundle.seq 缓存二次润色 Agent，热重载后自动重建。#Created By AiCoding(codex)"""
        bundle = self.runner._bundle
        rt_settings = bundle.settings
        rt_model = bundle.model
        rt_model_settings = bundle.model_settings
        cache_key = (
            bundle.seq,
            rt_settings.agent_output_mode,
            rt_settings.agent_native_strict,
            rt_settings.agent_output_retries,
        )
        cached = self._cached_polish_agent
        if (
            cached is not None
            and cached[0] == cache_key
            and cached[1] is rt_model
            and cached[2] == rt_model_settings
        ):
            return cached[3], rt_settings

        output_spec = build_output_spec(
            CompositePolishOutput,
            name="submit_polished_report",
            description="提交二次润色后的完整 Markdown 复合汇总报告。",
            settings=rt_settings,
        )
        agent: Agent[None, CompositePolishOutput] = Agent(
            rt_model,
            output_type=output_spec,
            instructions=POLISH_SYSTEM_PROMPT,
            retries={"output": rt_settings.agent_output_retries},
            model_settings=rt_model_settings,
        )

        @agent.output_validator
        async def _validate_polish(out: CompositePolishOutput) -> CompositePolishOutput:
            cleaned = (out.markdown or "").strip()
            if not cleaned:
                raise ModelRetry("润色后的 markdown 正文不能为空。")
            return out.model_copy(update={"markdown": cleaned})

        self._cached_polish_agent = (cache_key, rt_model, rt_model_settings, agent)
        return agent, rt_settings

    async def polish_markdown(
        self,
        assembled_markdown: str,
        *,
        order: dict[str, Any] | None = None,
        instruction: str = "",
    ) -> str:
        """对已通过 Jinja2 确定性拼装的大报告执行大模型二次润色（严禁篡改核查事实）。#Created By AiCoding(codex)"""
        base_md = (assembled_markdown or "").strip()
        if not base_md:
            raise ValueError("待润色的汇总报告正文不能为空")

        agent, rt_settings = self._get_or_build_polish_agent()

        order_lines = "\n".join(
            f"- {k}：{v}" for k, v in (order or {}).items() if str(k).strip() and str(v or "").strip()
        )
        extra_note = (instruction or "").strip()
        user_prompt = (
            (f"## 工单公共信息\n{order_lines}\n\n" if order_lines else "")
            + (f"## 润色要求\n{extra_note}\n\n" if extra_note else "")
            + f"## 待润色的确定性拼装报告（请保留全部核查事实与待补占位符）\n{base_md}"
        )

        raw_run_timeout = getattr(rt_settings, "agent_run_timeout_s", POLISH_TIMEOUT_S)
        eff_run_timeout = POLISH_TIMEOUT_S if raw_run_timeout is None else float(raw_run_timeout)
        timeout_s = min(POLISH_TIMEOUT_S, max(10.0, eff_run_timeout))
        async with asyncio.timeout(timeout_s):
            res = await agent.run(
                user_prompt,
                usage_limits=UsageLimits(request_limit=4, tool_calls_limit=4),
            )
        return res.output.markdown.strip()

    async def run(
        self,
        req: CompositeRunRequest,
        *,
        on_progress: Callable[[str, str, bool], None] | None = None,
        on_sub_event: Callable[[int, ProcessEvent], None] | None = None,
    ) -> dict[str, Any]:
        """并发执行多个业务子项、套用汇总大模板确定性拼装，并按需执行大模型二次润色。#Created By AiCoding(codex)"""
        if not req.items:
            raise InputValidationError(["复合工单至少需要包含 1 个业务子项（items 不能为空）"])
        if len(req.items) > MAX_COMPOSITE_ITEMS:
            raise InputValidationError([f"单次复合工单最多支持 {MAX_COMPOSITE_ITEMS} 个业务子项"])

        t0 = time.monotonic()
        composite_run_id = req.composite_run_id or f"cmp-{new_run_id()}"
        clean_order = {
            str(k).strip(): ("" if v is None else str(v)).strip()
            for k, v in (req.order or {}).items()
            if str(k).strip()
        }
        common_doc = req.document or ""

        # 1. 整单锁定同一份资源快照，保证所有子项与汇总大模板版本一致
        if req.target == "online":
            try_snap = getattr(self.runner.releases, "try_live_snapshot", None)
            snap = try_snap() if callable(try_snap) else None
            rev, rs = snap if snap is not None else await asyncio.to_thread(self.runner._capture, req.target)
        else:
            rev, rs = await asyncio.to_thread(self.runner._capture, req.target)

        shared_gw = SharedGatewayClient(self.runner.gateway)
        if on_progress:
            on_progress("start", f"开始并发核查 {len(req.items)} 项业务（快照 {rev}）", True)

        async def _run_one(idx: int, item: CompositeItemRequest) -> dict[str, Any]:
            clean_item_params = {
                str(k).strip(): ("" if v is None else str(v)).strip()
                for k, v in (item.params or {}).items()
                if str(k).strip()
            }
            # 公共工单参数作为基线，子项非空参数覆盖同名键
            merged_inputs = {**clean_order}
            for k, v in clean_item_params.items():
                if v:
                    merged_inputs[k] = v
                elif k not in merged_inputs:
                    merged_inputs[k] = ""

            tpl = rs.templates.get(item.template_id) if item.template_id is not None else None
            tpl_name = tpl.name if tpl else (f"模板 {item.template_id}" if item.template_id is not None else "自动路由")
            explicit_label = (item.label or "").strip() or merged_inputs.get("业务名称", "").strip()
            label = explicit_label or tpl_name
            eff_doc = item.document if (item.document is not None and item.document.strip()) else common_doc
            sub_run_id = new_run_id()

            if on_progress:
                if item.template_id is None:
                    on_progress("skill", f"[{idx}/{len(req.items)}] 启动核查「{label}」→ 自动匹配模板", True)
                else:
                    on_progress("skill", f"[{idx}/{len(req.items)}] 启动核查「{label}」→ #{item.template_id} {tpl_name}", True)

            def _sub_listener(ev: ProcessEvent) -> None:
                if on_sub_event:
                    on_sub_event(idx, ev)

            sub_req = RunRequest(
                template_id=item.template_id,
                inputs=merged_inputs,
                document=eff_doc,
                entry=req.entry,
                target=req.target,
                operator=req.operator,
                run_id=sub_run_id,
                extra={
                    "compositeRunId": composite_run_id,
                    "compositeIndex": idx,
                    "compositeLabel": label,
                    **({"batchNo": req.batch_no} if req.batch_no else {}),
                },
                gateway_override=shared_gw,
                snapshot_override=(rev, rs),
            )
            try:
                out = await self.runner.run(sub_req, listener=_sub_listener if on_sub_event else None)
            except (InputValidationError, TemplateUnavailable, TemplateRouteError) as exc:
                err_msg = sanitize_sensitive_text(exc)
                matched_tid = getattr(exc, "template_id", None) if item.template_id is None else item.template_id
                matched_tname = getattr(exc, "template_name", None) or tpl_name
                matched_routing = getattr(exc, "routing", None)
                matched_tpl = rs.templates.get(matched_tid) if matched_tid is not None else tpl
                fail_label = explicit_label or matched_tname
                if on_progress:
                    kind_desc = "模板路由失败" if isinstance(exc, TemplateRouteError) else "校验失败"
                    on_progress("error", f"[{idx}/{len(req.items)}] 「{fail_label}」{kind_desc}：{err_msg}", False)
                return {
                    "index": idx,
                    "label": fail_label,
                    "runId": sub_run_id,
                    "templateId": matched_tid,
                    "templateName": matched_tname,
                    "status": "FAILED",
                    "statusLabel": _STATUS_LABEL["FAILED"],
                    "report": "",
                    "foundCount": 0,
                    "totalCount": len(matched_tpl.definition.fields) if matched_tpl else 0,
                    "missingShown": [],
                    "error": err_msg,
                    "durationMs": 0,
                    "params": merged_inputs,
                    **({"routing": matched_routing} if matched_routing else {}),
                }
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 单子项异常不中断整单其他子项，对外消息统一脱敏
                log.exception("复合工单子项运行异常 compositeRunId=%s idx=%d", composite_run_id, idx)
                err_msg = sanitize_sensitive_text(f"子项运行异常：{type(exc).__name__} {exc}".strip())
                if on_progress:
                    on_progress("error", f"[{idx}/{len(req.items)}] 「{label}」失败：{err_msg}", False)
                return {
                    "index": idx,
                    "label": label,
                    "runId": sub_run_id,
                    "templateId": item.template_id,
                    "templateName": tpl_name,
                    "status": "FAILED",
                    "statusLabel": _STATUS_LABEL["FAILED"],
                    "report": "",
                    "foundCount": 0,
                    "totalCount": len(tpl.definition.fields) if tpl else 0,
                    "missingShown": [],
                    "error": err_msg,
                    "durationMs": 0,
                    "params": merged_inputs,
                }

            st = str(out.get("status") or "FAILED")
            found_c = int(out.get("foundCount") or 0)
            total_c = int(out.get("totalCount") or 0)
            missing_shown = list(out.get("missingShown") or [])
            resolved_tid = out.get("templateId") if out.get("templateId") is not None else item.template_id
            resolved_tname = str(out.get("templateName") or tpl_name)
            final_label = explicit_label or resolved_tname
            raw_sub_err = out.get("error")
            sub_err = sanitize_sensitive_text(raw_sub_err) if raw_sub_err else None
            if on_progress:
                icon = "check" if st == "SUCCESS" else ("warn" if st == "PARTIAL" else "error")
                on_progress(
                    icon,
                    f"[{idx}/{len(req.items)}] 「{final_label}」核查完成（{_STATUS_LABEL.get(st, st)}，{found_c}/{total_c}）",
                    st != "FAILED",
                )
            return {
                "index": idx,
                "label": final_label,
                "runId": str(out.get("runId") or sub_run_id),
                "templateId": int(resolved_tid) if resolved_tid is not None else None,
                "templateName": resolved_tname,
                "status": st,
                "statusLabel": _STATUS_LABEL.get(st, st),
                "report": str(out.get("report") or ""),
                "foundCount": found_c,
                "totalCount": total_c,
                "missingShown": missing_shown,
                "error": sub_err,
                "durationMs": int(out.get("durationMs") or 0),
                "params": merged_inputs,
                **({"routing": out["routing"]} if out.get("routing") else {}),
            }

        tasks = [asyncio.create_task(_run_one(i + 1, it)) for i, it in enumerate(req.items)]
        try:
            item_results = list(await asyncio.gather(*tasks))
        except asyncio.CancelledError:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        summary = build_composite_summary(item_results)
        if summary["successCount"] == summary["totalItems"]:
            overall_status = "SUCCESS"
        elif summary["failedCount"] == summary["totalItems"]:
            overall_status = "FAILED"
        else:
            overall_status = "PARTIAL"

        # 2. 套入汇总大模板做 Jinja2 确定性拼装
        tpl_source = (
            req.composite_template
            if (req.composite_template is not None and req.composite_template.strip())
            else (rs.composite_template or DEFAULT_COMPOSITE_TEMPLATE)
        )
        assembled_md = render_composite_report(tpl_source, order=clean_order, items=item_results)
        if on_progress:
            gw_note = f"（跨子项复用网关缓存 {shared_gw.cache_hits} 次）" if shared_gw.cache_hits > 0 else ""
            on_progress("tool", f"已完成 {len(item_results)} 项子报告的 Jinja2 确定性汇总拼装{gw_note}", True)

        # 3. 按需执行大模型二次润色（保留确定性原版，润色失败时优雅降级）
        polished_md: str | None = None
        polish_error: str | None = None
        if req.polish and overall_status != "FAILED" and assembled_md.strip():
            if on_progress:
                on_progress("skill", "正在使用大模型对汇总报告执行二次润色与衔接优化…", True)
            try:
                polished_md = await self.polish_markdown(
                    assembled_md,
                    order=clean_order,
                    instruction=req.polish_instruction,
                )
                if on_progress:
                    on_progress("check", "已完成大模型二次润色（同步保留 Jinja2 确定性核验原版）", True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 润色失败不丢失已完成的强证据拼装版
                polish_error = sanitize_sensitive_text(f"大模型二次润色失败，已回退确定性拼装版：{exc}")
                log.warning("复合工单大模型二次润色失败 compositeRunId=%s：%s", composite_run_id, polish_error)
                if on_progress:
                    on_progress("warn", polish_error, False)

        total_found = sum(int(it["foundCount"]) for it in item_results)
        total_fields = sum(int(it["totalCount"]) for it in item_results)
        all_missing: list[str] = []
        for it in item_results:
            for m in it.get("missingShown") or []:
                tag = f"{it['label']}·{m}"
                if tag not in all_missing:
                    all_missing.append(tag)

        dur_ms = int((time.monotonic() - t0) * 1000)
        final_md = polished_md if polished_md else assembled_md
        return {
            "compositeRunId": composite_run_id,
            "runId": composite_run_id,
            "status": overall_status,
            "rev": rev,
            "durationMs": dur_ms,
            "markdown": final_md,
            "assembledMarkdown": assembled_md,
            "polishedMarkdown": polished_md,
            "polished": bool(polished_md),
            "polishError": polish_error,
            "sharedGatewayHits": shared_gw.cache_hits,
            "foundCount": total_found,
            "totalCount": total_fields,
            "missingShown": all_missing,
            "summary": summary,
            "order": clean_order,
            "items": item_results,
        }
