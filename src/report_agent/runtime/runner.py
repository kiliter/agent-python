"""智能体运行编排：捕获资源快照 → 校验入参 → 运行 Pydantic AI 智能体 → 证据校验 → 渲染 → 记录。

#Created By AiCoding(codex)
一次请求只有一个智能体、一次运行；模型自己决定加载哪些 Skill、调用哪些接口、何时交卷。
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
import dataclasses
import itertools
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_ai import (Agent, ModelRetry, NativeOutput, PromptedOutput, RunContext, TextPart, ToolOutput,
                         UnexpectedModelBehavior, UsageLimitExceeded, UsageLimits)
from pydantic_ai.exceptions import AgentRunError, ModelAPIError
from pydantic_ai.messages import ModelResponse, ToolCallPart

from ..config import Settings
from ..domain.jinja_env import render_body
from ..domain.resources import ResourceSet
from ..domain.template import Template
from ..gateway.base import GatewayClient
from ..store.releases import ReleaseStore
from ..store.runs import RunStore, new_run_id
from ..store.service import ResourceService
from .deps import RunDeps
from .evidence import (
    EvidenceChecker,
    FieldIssue,
    format_issues,
    get_document_index,
    has_supporting_real_source,
    locate_quote_in_document,
    scalar_to_str,
)
from .model_factory import build_model, build_model_settings
from .output_model import build_report_model, report_to_dict
from .prompt import USER_PROMPT, build_task_instructions
from .render import field_render
from .text_tools import safe_regex_fullmatch
from .tools import build_tools
from .workspace import EventSink, ProcessEvent, Workspace

log = logging.getLogger(__name__)

Entry = Literal["上游调用", "试运行", "回归", "聊天窗口"]
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_JSON_FENCE_SEARCH_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_BUNDLE_SEQ = itertools.count(1)
_MAX_AGENT_CACHE = 128


class InputValidationError(ValueError):
    """入参不合法，不启动智能体。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("；".join(errors))
        self.errors = errors


class TemplateUnavailable(LookupError):
    """模板不存在或已下线。"""


@dataclass
class RunRequest:
    template_id: int
    inputs: dict[str, str]
    document: str = ""
    entry: Entry = "上游调用"
    target: Literal["online", "draft"] = "online"
    operator: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    # #Created By AiCoding(codex) 调用方可预先指定运行编号（聊天窗口需在启动前拿到 runId 以便订阅事件）
    run_id: str | None = None


def validate_inputs(template: Template, inputs: dict[str, str]) -> list[str]:
    """按模板入参定义校验必填和格式。"""
    errors = []
    safe_inputs = inputs or {}
    for inp in template.definition.inputs:
        raw = safe_inputs.get(inp.key)
        val = ("" if raw is None else str(raw)).strip()
        if not val:
            if inp.required:
                errors.append(f"缺少必填入参「{inp.key}」")
            continue
        if inp.pattern:
            try:
                matched = safe_regex_fullmatch(inp.pattern, val)
            except ValueError as exc:
                errors.append(f"入参「{inp.key}」校验正则不合法：{exc}")
                continue
            if not matched:
                errors.append(f"入参「{inp.key}」格式不正确，应符合 {inp.pattern}")
    return errors


def _extract_json_dict(text: str) -> dict[str, Any] | None:
    """从模型文本输出中提取 JSON 对象（兼容整段或夹在文字后的 ```json 代码块包裹）。"""
    raw = (text or "").strip()
    if not raw:
        return None
    m = _JSON_FENCE_RE.match(raw)
    if m:
        raw = m.group(1).strip()
    candidates = [raw]
    for fm in _JSON_FENCE_SEARCH_RE.finditer(raw):
        fenced = fm.group(1).strip()
        if fenced and fenced not in candidates:
            candidates.append(fenced)
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end and (start > 0 or end < len(raw) - 1):
        sliced = raw[start:end + 1]
        if sliced not in candidates:
            candidates.append(sliced)
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _extract_candidate_report(active_run: Any, field_names: set[str]) -> dict[str, Any] | None:
    """从失败运行的最近模型响应中提取最后一次交卷候选字典。"""
    if active_run is None:
        return None
    try:
        msgs = active_run.all_messages()
    except Exception:  # noqa: BLE001
        return None
    for msg in reversed(msgs):
        if not isinstance(msg, ModelResponse):
            continue
        for part in reversed(msg.parts):
            if isinstance(part, ToolCallPart) and part.tool_name == "submit_report":
                try:
                    d = part.args_as_dict()
                except Exception:  # noqa: BLE001
                    d = _extract_json_dict(part.args) if isinstance(part.args, str) else None
                if isinstance(d, dict):
                    return d
            elif isinstance(part, TextPart):
                d = _extract_json_dict(part.content)
                if isinstance(d, dict) and (not field_names or (set(d.keys()) & field_names)):
                    return d
    return None


def _degrade_failed_fields(report: dict[str, dict[str, Any]], ev_issues: list[FieldIssue]) -> set[str]:
    """把证据校验未通过的字段重写为 not_found，返回被降级的字段名集合。#Created By AiCoding(codex)"""
    grouped: dict[str, list[str]] = {}
    for item in ev_issues:
        grouped.setdefault(item.field, []).append(item.message)
    for name, msgs in grouped.items():
        report[name] = {
            "status": "not_found",
            "value": None,
            "evidence": [],
            "reasoning": "证据校验未通过：" + "；".join(msgs),
        }
    return set(grouped.keys())


def _cascade_degraded_fields(
    report: dict[str, dict[str, Any]],
    failed: set[str],
    issues: list[FieldIssue],
    deps: RunDeps | None = None,
) -> None:
    """将证据中引用了已降级字段或悬空依赖 not_found 前置字段的下游衍生字段递归级联降级，直到不动点。#Created By AiCoding(codex)"""
    ws = deps.workspace if deps is not None else None
    inputs = deps.inputs if deps is not None else None
    doc_idx = get_document_index(deps.workspace, deps.document) if deps is not None else None
    while True:
        valid_found = {
            k
            for k, v in report.items()
            if k not in failed and isinstance(v, dict) and v.get("status") == "found"
        }
        newly_failed: list[tuple[str, str]] = []
        for fname, ans in report.items():
            if fname not in valid_found:
                continue
            raw_ev = ans.get("evidence")
            if not isinstance(raw_ev, list):
                continue
            has_self_ref = False
            bad_failed_refs: list[str] = []
            not_found_refs: list[str] = []
            for e in raw_ev:
                if isinstance(e, dict) and e.get("type") == "field":
                    ref_name = str(e.get("name") or "")
                    if not ref_name:
                        continue
                    if ref_name == fname:
                        has_self_ref = True
                        continue
                    if ref_name in failed:
                        if ref_name not in bad_failed_refs:
                            bad_failed_refs.append(ref_name)
                    elif ref_name not in valid_found:
                        if ref_name not in not_found_refs:
                            not_found_refs.append(ref_name)
            if has_self_ref:
                msg = f"字段「{fname}」不能引用自身作为证据，衍生结论同步降级"
                newly_failed.append((fname, msg))
            elif bad_failed_refs:
                msg = f"引用的前置字段（{'、'.join(bad_failed_refs)}）校验未通过已降级，衍生结论同步降级"
                newly_failed.append((fname, msg))
            elif not_found_refs:
                val = ans.get("value")
                is_empty_list = isinstance(val, list) and len(val) == 0
                if not has_supporting_real_source(
                    raw_ev,
                    valid_found,
                    self_field=fname,
                    is_empty_list=is_empty_list,
                    ws=ws,
                    inputs=inputs,
                    doc_index=doc_idx,
                ):
                    msg = f"引用的前置字段（{'、'.join(not_found_refs)}）状态为 not_found，衍生结论同步降级"
                    newly_failed.append((fname, msg))
        if not newly_failed:
            break
        for fname, msg in newly_failed:
            issues.append(FieldIssue(fname, msg))
            failed.add(fname)
            report[fname] = {
                "status": "not_found",
                "value": None,
                "evidence": [],
                "reasoning": f"证据校验未通过：{msg}",
            }


def _salvage_partial_report(candidate: dict[str, Any], report_model: type[BaseModel],
                            deps: RunDeps) -> dict[str, dict[str, Any]]:
    """当模型交卷因缺字段或个别字段格式错误耗尽重试时，保留合法且通过证据核验的字段，其余字段安全降级。"""
    tpl = deps.template
    by_alias = {(fi.alias or key): fi for key, fi in report_model.model_fields.items()}
    salvaged: dict[str, dict[str, Any]] = {}
    issues: list[FieldIssue] = []
    failed: set[str] = set()

    for f in tpl.definition.fields:
        if f.name not in candidate or candidate[f.name] is None:
            msg = "模型输出缺少该字段结论"
            issues.append(FieldIssue(f.name, msg))
            failed.add(f.name)
            salvaged[f.name] = {"status": "not_found", "value": None, "evidence": [],
                                "reasoning": f"{msg}，已自动降级"}
            continue
        raw_ans = candidate[f.name]
        # #Created By AiCoding(codex) 仅把非列表字段的基础标量（数值/布尔）转为文本，数组/对象交由模型结构校验拒绝
        if not f.is_list and isinstance(raw_ans, dict) and isinstance(raw_ans.get("value"), (int, float, bool)):
            raw_ans = {**raw_ans, "value": scalar_to_str(raw_ans["value"])}
        fi = by_alias.get(f.name)
        try:
            if fi is None:
                raise ValueError("未知字段")
            ann = fi.annotation
            if isinstance(ann, type) and issubclass(ann, BaseModel):
                parsed: Any = ann.model_validate(raw_ans)
            else:
                parsed = TypeAdapter(ann).validate_python(raw_ans)
            salvaged[f.name] = parsed.model_dump(mode="json") if isinstance(parsed, BaseModel) else dict(parsed)
        except ValidationError as ve:
            msg = "字段结构不合法：" + "；".join(e.get("msg", "格式错误") for e in ve.errors()[:3])
            issues.append(FieldIssue(f.name, msg))
            failed.add(f.name)
            salvaged[f.name] = {"status": "not_found", "value": None, "evidence": [], "reasoning": msg}
        except Exception as exc:  # noqa: BLE001
            msg = f"字段结构不合法：{exc}"
            issues.append(FieldIssue(f.name, msg))
            failed.add(f.name)
            salvaged[f.name] = {"status": "not_found", "value": None, "evidence": [], "reasoning": msg}

    checker = EvidenceChecker(tpl, deps.inputs, deps.document, deps.workspace)
    ev_issues = checker.check(salvaged)
    if ev_issues:
        issues.extend(ev_issues)
        failed |= _degrade_failed_fields(salvaged, ev_issues)

    _cascade_degraded_fields(salvaged, failed, issues, deps=deps)

    issue_dicts = [i.to_dict() for i in issues]
    if issue_dicts:
        deps.workspace.validation_rounds.append(issue_dicts)
    if failed:
        deps.events.emit("report_degraded", attempt=max(1, len(deps.workspace.validation_rounds)),
                         issues=issue_dicts, fields=sorted(failed))
    else:
        deps.events.emit("report_accepted", attempt=max(1, len(deps.workspace.validation_rounds) + 1))
    return salvaged


@dataclass(frozen=True)
class _RuntimeBundle:
    """不可变运行期模型与工具配置快照，保证 reload_config 单引用原子切换。#Created By AiCoding(codex)"""

    settings: Settings
    model: Any
    model_settings: dict[str, Any]
    tools: list[Any]
    seq: int = field(default_factory=lambda: next(_BUNDLE_SEQ))


class _DynamicLimiter:
    """支持运行期跨线程安全动态调额的异步并发限流器，绝不因热重载突破在途并发上限。#Created By AiCoding(codex)"""

    def __init__(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._inflight = 0
        self._waiters: deque[asyncio.Future[None]] = deque()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def inflight(self) -> int:
        return self._inflight

    @property
    def _value(self) -> int:
        return max(0, self._limit - self._inflight)

    def _prune_waiters(self) -> None:
        while self._waiters and (self._waiters[0].done() or self._waiters[0].get_loop().is_closed()):
            self._waiters.popleft()

    def _wake_waiters(self) -> None:
        while self._inflight < self._limit and self._waiters:
            fut = self._waiters.popleft()
            if fut.done() or fut.get_loop().is_closed():
                continue
            self._inflight += 1
            fut.set_result(None)

    def set_limit(self, limit: int) -> None:
        self._limit = max(1, int(limit))
        self._prune_waiters()
        loop = self._waiters[0].get_loop() if self._waiters else self._loop
        if loop is not None and not loop.is_closed() and loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                self._wake_waiters()
            else:
                try:
                    loop.call_soon_threadsafe(self._wake_waiters)
                except RuntimeError:
                    self._wake_waiters()
        else:
            self._wake_waiters()

    async def __aenter__(self) -> _DynamicLimiter:
        loop = asyncio.get_running_loop()
        self._loop = loop
        self._prune_waiters()
        if self._inflight < self._limit and not self._waiters:
            self._inflight += 1
            return self
        fut: asyncio.Future[None] = loop.create_future()
        self._waiters.append(fut)
        try:
            await fut
        except BaseException:
            if not fut.done():
                fut.cancel()
                try:
                    self._waiters.remove(fut)
                except ValueError:
                    pass
            else:
                self._inflight = max(0, self._inflight - 1)
                self._wake_waiters()
            raise
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._inflight = max(0, self._inflight - 1)
        self._wake_waiters()


class AgentRunner:
    """进程内唯一的运行器。"""

    def __init__(self, settings: Settings, model: Any, model_settings: dict[str, Any], gateway: GatewayClient,
                 service: ResourceService, releases: ReleaseStore, runs: RunStore) -> None:
        self._bundle = _RuntimeBundle(
            settings=settings,
            model=model,
            model_settings=model_settings,
            tools=build_tools(settings.agent_tool_retries),
        )
        self.gateway = gateway
        self.service = service
        self.releases = releases
        self.runs = runs
        self._sem = _DynamicLimiter(settings.agent_max_concurrent_runs)
        self._agent_cache: OrderedDict[tuple[str, int, int], tuple[type[BaseModel], Agent[RunDeps, Any]]] = OrderedDict()

    @property
    def settings(self) -> Settings:
        return self._bundle.settings

    @settings.setter
    def settings(self, value: Settings) -> None:
        self._bundle = dataclasses.replace(self._bundle, settings=value, seq=next(_BUNDLE_SEQ))

    @property
    def model(self) -> Any:
        return self._bundle.model

    @model.setter
    def model(self, value: Any) -> None:
        self._bundle = dataclasses.replace(self._bundle, model=value, seq=next(_BUNDLE_SEQ))

    @property
    def model_settings(self) -> dict[str, Any]:
        return self._bundle.model_settings

    @model_settings.setter
    def model_settings(self, value: dict[str, Any]) -> None:
        self._bundle = dataclasses.replace(self._bundle, model_settings=value, seq=next(_BUNDLE_SEQ))

    @property
    def _tools(self) -> list[Any]:
        return self._bundle.tools

    @_tools.setter
    def _tools(self, value: list[Any]) -> None:
        self._bundle = dataclasses.replace(self._bundle, tools=value, seq=next(_BUNDLE_SEQ))

    def reload_config(self, settings: Settings, *, rebuild_model: bool = True) -> None:
        """运行期原子热重载模型、参数、工具重试与动态并发限流器，立即对后续运行生效。"""
        cur = self._bundle
        next_model_settings = build_model_settings(settings)
        next_model = build_model(settings) if rebuild_model else cur.model
        next_tools = build_tools(settings.agent_tool_retries)
        self._bundle = _RuntimeBundle(
            settings=settings,
            model=next_model,
            model_settings=next_model_settings,
            tools=next_tools,
        )
        self._sem.set_limit(settings.agent_max_concurrent_runs)

    # ------------------------------------------------------------------ 快照
    def _capture(self, target: str) -> tuple[str, ResourceSet]:
        if target == "draft":
            live = self.releases.live_rev() or "-"
            return f"{live}+草稿", self.service.overlay()
        return self.releases.live_snapshot()

    def _build_agent(
        self,
        report_model: type[BaseModel],
        *,
        settings: Settings | None = None,
        model: Any = None,
        model_settings: dict[str, Any] | None = None,
        tools: list[Any] | None = None,
    ) -> Agent[RunDeps, Any]:
        rt_settings = settings or self.settings
        rt_model = self.model if model is None else model
        rt_model_settings = self.model_settings if model_settings is None else model_settings
        rt_tools = self._tools if tools is None else tools
        mode = rt_settings.agent_output_mode
        if mode == "native":
            output: Any = NativeOutput(report_model, name="submit_report",
                                       strict=rt_settings.agent_native_strict)
        elif mode in ("json_object", "prompted"):
            output = PromptedOutput(report_model, name="submit_report")
        else:
            output = ToolOutput(report_model, name="submit_report",
                                description="提交全部字段的结论与证据。所有字段都有结论后调用一次。")
        agent: Agent[RunDeps, Any] = Agent(
            rt_model,
            deps_type=RunDeps,
            output_type=output,
            instructions=[lambda ctx: ctx.deps.resources.system_prompt, lambda ctx: build_task_instructions(ctx.deps)],
            tools=rt_tools,
            retries={"tools": rt_settings.agent_tool_retries, "output": rt_settings.agent_output_retries},
            model_settings=rt_model_settings,
        )

        @agent.output_validator
        async def _validate(ctx: RunContext[RunDeps], out: BaseModel) -> BaseModel:
            deps = ctx.deps
            report = report_to_dict(out)
            checker = EvidenceChecker(deps.template, deps.inputs, deps.document, deps.workspace)
            issues = checker.check(report)
            attempt = ctx.retry + 1
            if not issues:
                deps.events.emit("report_accepted", attempt=attempt)
                return out
            if ctx.retry >= ctx.max_retries:
                # 重试用完：不通过的字段及引用它们的下游衍生字段按“找不到”处理，其余字段照常使用
                failed = _degrade_failed_fields(report, issues)
                _cascade_degraded_fields(report, failed, issues, deps=deps)
                issue_dicts = [i.to_dict() for i in issues]
                deps.workspace.validation_rounds.append(issue_dicts)
                deps.events.emit("report_degraded", attempt=attempt, issues=issue_dicts, fields=sorted(failed))
                return type(out).model_validate(report)
            issue_dicts = [i.to_dict() for i in issues]
            deps.workspace.validation_rounds.append(issue_dicts)
            deps.events.emit("report_rejected", attempt=attempt, issues=issue_dicts)
            raise ModelRetry(format_issues(issues))

        return agent

    # ------------------------------------------------------------------ 运行
    async def run(self, req: RunRequest, listener: Callable[[ProcessEvent], None] | None = None) -> dict[str, Any]:
        """执行一次填写，返回完整结果（同时写入运行记录）。"""
        run_id = req.run_id or new_run_id()
        started_at = datetime.now().astimezone()
        if req.target == "online":
            try_snap = getattr(self.releases, "try_live_snapshot", None)
            snap = try_snap() if callable(try_snap) else None
            rev, rs = snap if snap is not None else await asyncio.to_thread(self._capture, req.target)
        else:
            rev, rs = await asyncio.to_thread(self._capture, req.target)
        tpl = rs.templates.get(req.template_id)
        if tpl is None:
            raise TemplateUnavailable(f"模板 {req.template_id} 不存在" + ("（草稿与线上都没有）" if req.target == "draft" else "或未发布"))
        if tpl.offline and req.target == "online":
            raise TemplateUnavailable(f"模板 {req.template_id} 已下线")
        inputs = {k: ("" if v is None else str(v)).strip() for k, v in (req.inputs or {}).items()}
        errors = validate_inputs(tpl, inputs)
        if errors:
            raise InputValidationError(errors)

        bundle = self._bundle
        rt_settings = bundle.settings
        rt_model = bundle.model
        rt_model_settings = bundle.model_settings
        rt_tools = bundle.tools
        rt_sem = self._sem
        events = EventSink(listener)
        deps = RunDeps(
            run_id=run_id, rev=rev, resources=rs, template=tpl, inputs=inputs, document=req.document or "",
            allowed_skills=[s for s in tpl.definition.skills if s in rs.skills],
            allowed_apis=rs.allowed_apis(tpl), workspace=Workspace(), events=events, gateway=self.gateway,
            settings=rt_settings,
        )
        events.emit("run_started", runId=run_id, templateId=tpl.id, templateName=tpl.name, rev=rev,
                    skills=deps.allowed_skills, apis=deps.allowed_apis)
        cache_key = (rev, tpl.id, bundle.seq) if req.target == "online" else None
        cached_pair = self._agent_cache.get(cache_key) if cache_key is not None else None
        if cached_pair is not None:
            self._agent_cache.move_to_end(cache_key)  # type: ignore[arg-type]
            report_model, agent = cached_pair
        else:
            report_model = build_report_model(tpl)
            agent = self._build_agent(
                report_model,
                settings=rt_settings,
                model=rt_model,
                model_settings=rt_model_settings,
                tools=rt_tools,
            )
            if cache_key is not None:
                self._agent_cache[cache_key] = (report_model, agent)
                while len(self._agent_cache) > _MAX_AGENT_CACHE:
                    self._agent_cache.popitem(last=False)
        report: dict[str, dict[str, Any]] | None = None
        error: str | None = None
        usage: dict[str, Any] = {}
        messages: Any = None
        result = None
        active_run = None
        cancelled_exc: asyncio.CancelledError | None = None
        t0 = time.monotonic()
        try:
            async with rt_sem:
                async with asyncio.timeout(rt_settings.agent_run_timeout_s):
                    async with agent.iter(
                        USER_PROMPT, deps=deps,
                        usage_limits=UsageLimits(request_limit=rt_settings.agent_request_limit,
                                                 tool_calls_limit=rt_settings.agent_tool_calls_limit),
                    ) as run:
                        active_run = run
                        async for node in run:
                            if Agent.is_model_request_node(node):
                                events.round += 1
                                events.emit("model_request")
                            elif Agent.is_call_tools_node(node):
                                for part in node.model_response.parts:
                                    if isinstance(part, TextPart) and part.content.strip():
                                        events.emit("model_text", text=part.content.strip()[:2000])
                        result = run.result
            if result is not None:
                report = report_to_dict(result.output)
        except TimeoutError:
            error = f"运行超时（超过 {rt_settings.agent_run_timeout_s:.0f} 秒）"
        except UsageLimitExceeded as exc:
            error = f"超过运行上限：{exc}"
        except UnexpectedModelBehavior as exc:
            candidate = _extract_candidate_report(active_run, {f.name for f in tpl.definition.fields})
            if candidate is not None:
                log.warning("模型交卷重试耗尽，触发字段级降级 runId=%s：%s", run_id, exc)
                report = _salvage_partial_report(candidate, report_model, deps)
            else:
                error = f"模型输出异常：{exc}"
        except ModelAPIError as exc:
            error = f"大模型调用失败：{exc}"
        except AgentRunError as exc:
            error = f"智能体运行失败：{exc}"
        except asyncio.CancelledError as exc:
            # #Created By AiCoding(codex) 被调用方取消（聊天窗口「停止」）：照常写入运行记录后再向上原样重抛取消异常
            cancelled_exc = exc
            error = "运行已取消"
        except Exception as exc:  # noqa: BLE001 - 兜底，保证运行记录完整
            log.exception("智能体运行异常 runId=%s", run_id)
            error = f"内部错误：{type(exc).__name__} {exc}"

        src = result if result is not None else active_run
        if src is not None:
            try:
                u = src.usage
                usage = {"requests": u.requests, "toolCalls": u.tool_calls, "inputTokens": u.input_tokens,
                         "outputTokens": u.output_tokens}
            except Exception:  # noqa: BLE001
                pass
            try:
                messages = json.loads(src.all_messages_json())
            except Exception:  # noqa: BLE001
                pass

        if error:
            events.emit("run_failed", error=error)
            log.warning("运行失败 runId=%s template=%s：%s", run_id, tpl.id, error)

        model_name = getattr(rt_model, "model_name", None) or rt_settings.llm_model
        outcome = self._finish(run_id, started_at, rev, req, deps, report, error, usage, t0, model_name=model_name)
        detail = {**outcome, "messages": messages}
        self.runs.submit(self._summary(outcome), detail)
        if cancelled_exc is not None:
            raise cancelled_exc
        return outcome

    # ------------------------------------------------------------------ 结果整理
    def _finish(self, run_id: str, started_at: datetime, rev: str, req: RunRequest, deps: RunDeps,
                report: dict[str, dict[str, Any]] | None, error: str | None, usage: dict[str, Any],
                t0: float, *, model_name: str | None = None) -> dict[str, Any]:
        tpl = deps.template
        ws = deps.workspace
        retried = {i["field"] for rnd in ws.validation_rounds for i in rnd if isinstance(i, dict) and "field" in i}
        degraded_fields = {f for e in deps.events.events if e.type == "report_degraded"
                           for f in (e.data.get("fields") or [])}
        fields_out: list[dict[str, Any]] = []
        context: dict[str, Any] = {}
        for f in tpl.definition.fields:
            missing_in_report = report is not None and f.name not in report
            raw_ans = (report or {}).get(f.name)
            ans = raw_ans if isinstance(raw_ans, dict) else {
                "status": "not_found", "value": None, "evidence": [], "reasoning": error or "没有结论",
            }
            raw_ev = ans.get("evidence")
            ev_list = [e for e in raw_ev if isinstance(e, dict)] if isinstance(raw_ev, list) else []
            # #Created By AiCoding(codex) 渲染值统一由 render.field_render 计算（与 build_render_context 同一路径）：
            # 列表字段上下文为 TrackedList，生效分支执行 {% for %} 遍历即记为已展示（found: [] 为 SUCCESS，not_found 为 PARTIAL）。
            fr = field_render(f, ans)
            if not fr.found:
                ev_list = []
            context[f.name] = fr.context_value
            label, target = _evidence_label(ev_list, ws, deps.document, value=_value_hint(fr.value), report=report)
            fo = {
                "name": f.name, "visible": f.visible, "type": f.type, "evidenceType": f.evidence,
                "whenMissing": f.whenMissing, "status": "found" if fr.found else "not_found", "value": fr.value,
                "renderedValue": fr.rendered, "evidence": ev_list,
                "reasoning": str(ans.get("reasoning") or ""), "retried": f.name in retried,
                "validationFailed": f.name in degraded_fields or missing_in_report,
                "evidenceLabel": label, "evidenceTarget": target,
            }
            if f.is_list:
                fo["columns"] = [c.model_dump() for c in f.columns]
            fields_out.append(fo)
        report_text = ""
        used: set[str] = set()
        render_error = None
        try:
            report_text, used = render_body(tpl.body, context)
        except Exception as exc:  # noqa: BLE001 - 草稿正文可能有错误
            render_error = f"正文渲染失败：{exc}"
        by_name = {f.name: f for f in tpl.definition.fields}
        missing_shown = [fo["name"] for fo in fields_out
                         if fo["name"] in used and by_name[fo["name"]].visible and fo["status"] == "not_found"
                         and by_name[fo["name"]].whenMissing != "value"]
        undefined_used = sorted(u for u in used if u not in by_name)
        for u in undefined_used:
            if u not in missing_shown:
                missing_shown.append(u)
        if error or render_error:
            status = "FAILED"
        elif missing_shown:
            status = "PARTIAL"
        else:
            status = "SUCCESS"
        for fo in fields_out:
            fo["shown"] = fo["name"] in used
        api_results = [r.to_dict(with_raw=True) for r in ws.results.values()]
        return {
            "runId": run_id, "startTime": started_at.isoformat(timespec="seconds"), "templateId": tpl.id,
            "templateName": tpl.name, "templateDef": tpl.definition.model_dump(), "rev": rev, "target": req.target,
            "entry": req.entry, "operator": req.operator,
            "status": status, "error": error or render_error, "inputs": deps.inputs, "document": deps.document,
            "report": report_text, "fields": fields_out, "missingShown": missing_shown,
            "foundCount": sum(1 for fo in fields_out if fo["status"] == "found"), "totalCount": len(fields_out),
            "durationMs": int((time.monotonic() - t0) * 1000), "rounds": deps.events.round,
            "usage": usage, "skillsLoaded": list(ws.loaded_skills), "apiResults": api_results,
            "toolCalls": [{"callId": c.call_id, "tool": c.tool, "args": c.args, "output": c.output, "atMs": c.at_ms,
                           "ok": c.ok} for c in ws.tool_calls.values()],
            "validationRounds": ws.validation_rounds,
            "events": [e.to_dict() for e in deps.events.events],
            "model": model_name or getattr(self.model, "model_name", None) or self.settings.llm_model,
            "extra": req.extra,
        }

    @staticmethod
    def _summary(o: dict[str, Any]) -> dict[str, Any]:
        """写入 index.jsonl 的摘要。"""
        return {
            "runId": o["runId"], "startTime": o["startTime"], "templateId": o["templateId"],
            "templateName": o["templateName"], "rev": o["rev"], "target": o["target"], "entry": o["entry"],
            "operator": o["operator"], "status": o["status"], "error": o["error"],
            "mobile": o["inputs"].get("手机号码", ""), "busiName": o["inputs"].get("业务名称", ""),
            "found": o["foundCount"], "total": o["totalCount"], "durationMs": o["durationMs"], "rounds": o["rounds"],
            "skills": o["skillsLoaded"],
            "apiCalls": [{"name": r["api"], "ok": r["ok"], "ms": r["costMs"]} for r in o["apiResults"]],
            "retries": len(o["validationRounds"]),
            "batchNo": (o.get("extra") or {}).get("batchNo"),
        }


def _value_hint(value: Any) -> str | None:
    """证据定位时用于缩小匹配范围的文本值；列表/对象值不参与定位。#Created By AiCoding(codex)"""
    if value is None or isinstance(value, (list, dict)):
        return None
    return scalar_to_str(value) or None


def _evidence_label(evidence: list[dict[str, Any]], ws: Workspace, document: str,
                    value: str | None = None, report: dict[str, dict[str, Any]] | None = None,
                    _seen: set[str] | None = None) -> tuple[str, dict[str, Any]]:
    """生成给人看的证据说明，以及前端定位用的 evidenceTarget。"""
    labels: list[str] = []
    target: dict[str, Any] | None = None
    doc_idx = get_document_index(ws, document)
    for e in evidence:
        if not isinstance(e, dict):
            continue
        t = e.get("type")
        if t == "api":
            res = ws.results.get(str(e.get("resultId") or ""))
            api = res.api if res else "?"
            col_name = e.get("column")
            if res is not None and len(res.records) == 0:
                labels.append(f"接口 {api} · {e.get('resultId')}（无返回记录）")
            elif col_name:
                labels.append(f"接口 {api} · {e.get('resultId')} 第 {e.get('row')} 行 · {col_name}")
            else:
                labels.append(f"接口 {api} · {e.get('resultId')} 第 {e.get('row')} 行")
            target = target or {"tab": "api", "resultId": e.get("resultId"), "row": e.get("row"),
                                "column": col_name}
        elif t == "document":
            quote = scalar_to_str(e.get("quote"))
            locs = locate_quote_in_document(document, quote, value=value, index=doc_idx)
            if locs:
                first_loc = locs[0]
                line = first_loc["line"]
                end_line = first_loc["endLine"]
                line_desc = f"第 {line} 行" if line == end_line else f"第 {line}-{end_line} 行"
                doc_target: dict[str, Any] = {
                    "tab": "doc", "line": line, "endLine": end_line,
                    "offset": first_loc["offset"], "endOffset": first_loc["endOffset"],
                }
                if len(locs) > 1:
                    doc_target["matchCount"] = len(locs)
                    doc_target["matches"] = locs
            else:
                first = quote.splitlines()[0] if quote else ""
                line = next((i + 1 for i, ln in enumerate(doc_idx.lines) if first and first in ln), None)
                line_desc = f"第 {line} 行" if line else ""
                doc_target = {"tab": "doc", **({"line": line} if line else {})}
            short = quote if len(quote) <= 30 else quote[:30] + "…"
            labels.append("单据原文" + (f" · {line_desc}" if line_desc else "") + f"“{short}”")
            target = target or doc_target
        elif t == "input":
            labels.append(f"入参 · {e.get('key')}")
            target = target or {"tab": "input", "key": e.get("key")}
        elif t == "tool":
            call = ws.tool_calls.get(str(e.get("callId") or ""))
            labels.append(f"工具 {call.tool if call else '?'}#{e.get('callId')}")
            target = target or {"tab": "input", "callId": e.get("callId")}
        elif t == "field":
            ref_name = str(e.get("name") or "")
            labels.append(f"字段[{ref_name}]")
            if target is None and report and ref_name in report:
                seen = set(_seen or set())
                if ref_name not in seen:
                    seen.add(ref_name)
                    ref_ans = report.get(ref_name)
                    if isinstance(ref_ans, dict) and isinstance(ref_ans.get("evidence"), list) and ref_ans["evidence"]:
                        _, sub_target = _evidence_label(
                            ref_ans["evidence"], ws, document,
                            value=_value_hint(ref_ans.get("value")), report=report, _seen=seen,
                        )
                        target = sub_target
    return (" + ".join(labels), target or {"tab": "doc"})
