"""无状态自动模板路由器：在调用方未传 templateId 时，按 template-router Skill 匹配最高置信度在线模板。

#Created By AiCoding(codex)
路由器只使用只读工具查看路由规则与可用模板，绝不调用外部业务网关；
与嵌入式聊天窗口 ChatAgent 共享同一套只读工具纯函数，并按最高置信度直接放行运行（不因低置信度阻塞）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import re
import time
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import (
    Agent,
    ModelRetry,
    RunContext,
    Tool,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
    UsageLimits,
)
from pydantic_ai.exceptions import AgentRunError, ModelAPIError

from ..domain.resources import ResourceSet
from ..domain.sanitize import sanitize_sensitive_text
from ..domain.skill import SkillParseError, normalize_skill_doc_path
from ..domain.template import Template
from .model_factory import build_output_spec
from .tools import collect_doc_requests, render_skill_doc_block, render_skill_docs_index
from .workspace import EventSink

if TYPE_CHECKING:
    from .runner import AgentRunner

ROUTER_SKILL_NAME = "template-router"
ROUTE_MAX_DOC_CHARS = 12_000
ROUTE_REQUEST_LIMIT = 8
ROUTE_TOOL_CALLS_LIMIT = 16
ROUTE_TIMEOUT_S = 120.0

_CONFIDENCE_RANK: dict[str, int] = {"高": 0, "中": 1, "低": 2}
_JAVA_RULE_NOTE_RE = re.compile(r"\n*原规则（Java）：")

ROUTER_SYSTEM_PROMPT = """你是「智能申告报告填写平台」的无状态自动模板路由器。

## 职责与流程（严格遵守）
1. 根据调用方传入的工单入参（`inputs`）与单据原文（`document`），从当前可用模板中识别最匹配的申告报告模板。
2. **优先按需读取路由规则**：
   - 若当前环境中配置了 `template-router`，请优先调用 `load_skill("template-router")` 读取路由总则与业务族索引；
   - 锁定 1～2 个相关业务族后，再按需调用 `load_skill(name="template-router", docs=["references/xxx.md"])` 读取细分模板判定细则，切勿一次性全量加载全部子文档；
   - 若环境中未配置 `template-router`，请调用 `list_templates` 查看可用模板列表，必要时调用 `get_template` 核对模板入参与字段说明。
3. **输出与选型规则**：
   - 最多输出 3 个候选模板（`candidates`），按匹配置信度从高到低排列，每个候选写明结合当前单据/入参的具体依据；
   - 只能选择当前在线可用的模板编号，严禁编造或选择已下线模板；
   - 将置信度最高的模板作为最终 `templateId` 与 `confidence`；即使信息有限、最高置信度仅为「低」，只要存在最接近的可用模板也应给出该候选并设置 `matched=true`；
   - 仅当完全无法匹配任何可用模板时，才设置 `matched=false`、`templateId=null` 且 `candidates=[]` 并说明原因。
4. **严禁编造事实**：绝不凭空臆造入参或单据中不存在的客户信息或业务结论。"""


# ============================================================================ 安全配置与共享只读纯函数
def cfg_int(settings: Any, attr: str, default: int, *, min_val: int = 1) -> int:
    """从运行配置安全读取整数参数，缺失、空值或越界时回退默认值。#Created By AiCoding(codex)"""
    if settings is None:
        return default
    raw = getattr(settings, attr, None)
    if raw is None or isinstance(raw, bool):
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return default
    return val if val >= min_val else default


def cfg_float(settings: Any, attr: str, default: float, *, gt_zero: bool = True) -> float:
    """从运行配置安全读取浮点参数，缺失、空值、NaN/Inf 或非法时回退默认值。#Created By AiCoding(codex)"""
    if settings is None:
        return default
    raw = getattr(settings, attr, None)
    if raw is None or isinstance(raw, bool):
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    if math.isnan(val) or math.isinf(val):
        return default
    if gt_zero and val <= 0:
        return default
    return val


def strip_java_rule_note(desc: str | None, *, max_chars: int | None = None) -> str:
    """剥离字段说明中的 Java 历史对照注释，按需截断超长说明文本。#Created By AiCoding(codex)"""
    cleaned = _JAVA_RULE_NOTE_RE.split(desc or "", maxsplit=1)[0].strip()
    if max_chars is not None and len(cleaned) > max_chars:
        return cleaned[:max_chars] + "…"
    return cleaned


def _resolve_chat_skill(
    rs: ResourceSet,
    *,
    name: str = ROUTER_SKILL_NAME,
    doc: str = "",
    docs: list[str] | None = None,
) -> tuple[str, bool, dict[str, Any]]:
    """解析并渲染聊天/路由专用 Skill（scope: chat）主说明或按需子文档，返回 (正文, 是否成功, 元信息)。#Created By AiCoding(codex)"""
    chat_ids = rs.chat_skills()
    req_name = (name or ROUTER_SKILL_NAME).strip() or ROUTER_SKILL_NAME
    if req_name not in chat_ids:
        if req_name == ROUTER_SKILL_NAME:
            msg = "当前未配置 template-router，请使用 list_templates 查看在线模板"
        else:
            allowed_desc = "、".join(chat_ids) if chat_ids else ROUTER_SKILL_NAME
            msg = (
                f"错误：聊天助手仅允许加载聊天专用 Skill（{allowed_desc}），不可加载「{req_name}」。"
                "如需查看在线模板，请调用 list_templates 或 get_template。"
            )
        return msg, False, {"skill": req_name, "error": msg}

    skill = rs.skills.get(req_name)
    if skill is None:
        msg = f"当前未配置 {req_name}，请使用 list_templates 查看在线模板"
        return msg, False, {"skill": req_name, "error": msg}

    raw_docs = collect_doc_requests(doc, docs)
    if raw_docs:
        available = sorted(skill.docs)
        if not available:
            msg = f"错误：Skill「{req_name}」没有可按需加载的子文档"
            return msg, False, {"skill": req_name, "title": skill.title, "error": msg}
        norm_docs: list[str] = []
        for raw_d in raw_docs:
            try:
                norm_d = normalize_skill_doc_path(raw_d)
            except SkillParseError as exc:
                msg = f"错误：子文档路径「{raw_d}」不合法（{exc}），可用子文档：{available}"
                return msg, False, {"skill": req_name, "title": skill.title, "error": msg}
            if norm_d not in norm_docs:
                norm_docs.append(norm_d)
        missing = [d for d in norm_docs if d not in skill.docs]
        if missing:
            msg = f"错误：Skill「{req_name}」中不存在子文档 {missing}，可用子文档：{available}"
            return msg, False, {"skill": req_name, "title": skill.title, "error": msg}
        text = "\n---\n\n".join(render_skill_doc_block(skill, d) for d in norm_docs)
        return text, True, {"skill": req_name, "title": skill.title, "docs": norm_docs}

    docs_index = render_skill_docs_index(skill)
    if docs_index:
        text = f"# Skill：{skill.title}（{skill.id}）\n\n{skill.body}\n\n{docs_index.rstrip()}"
    else:
        text = f"# Skill：{skill.title}（{skill.id}）\n\n{skill.body}"
    return text, True, {"skill": req_name, "title": skill.title, "docs": []}


def load_chat_skill(
    rs: ResourceSet,
    name: str = ROUTER_SKILL_NAME,
    doc: str = "",
    docs: list[str] | None = None,
) -> str:
    """共享只读纯函数：加载 scope=chat 的 Skill 主说明或按需加载子文档。#Created By AiCoding(codex)"""
    text, _, _ = _resolve_chat_skill(rs, name=name, doc=doc, docs=docs)
    return text


def list_online_templates(
    rs: ResourceSet,
    keyword: str = "",
    *,
    allow_offline: bool = False,
) -> list[dict[str, Any]]:
    """共享只读纯函数：列出当前在线（或草稿态全部）可用模板摘要，支持按关键词过滤。#Created By AiCoding(codex)"""
    kw = (keyword or "").strip().lower()
    items: list[dict[str, Any]] = []
    for tid in sorted(rs.templates):
        tpl = rs.templates[tid]
        if tpl.offline and not allow_offline:
            continue
        desc = tpl.definition.description or ""
        if kw and kw not in str(tpl.id).lower() and kw not in tpl.name.lower() and kw not in desc.lower():
            continue
        items.append({
            "id": tpl.id,
            "name": tpl.name,
            "description": desc,
            "requiredInputs": [i.key for i in tpl.definition.inputs if i.required],
            "optionalInputs": [i.key for i in tpl.definition.inputs if not i.required],
        })
    return items


def get_online_template(
    rs: ResourceSet,
    template_id: int,
    *,
    allow_offline: bool = False,
) -> dict[str, Any]:
    """共享只读纯函数：查看指定在线（或草稿态）模板的入参要求与可见报告字段说明。#Created By AiCoding(codex)"""
    tpl = rs.templates.get(template_id)
    if tpl is None or (tpl.offline and not allow_offline):
        return {"ok": False, "error": f"模板 {template_id} 不存在或已下线"}
    defn = tpl.definition
    return {
        "ok": True,
        "id": tpl.id,
        "name": tpl.name,
        "description": defn.description,
        "inputs": [
            {
                "key": inp.key,
                "required": inp.required,
                "pattern": inp.pattern,
                "description": inp.description,
                "sample": inp.sample,
            }
            for inp in defn.inputs
        ],
        "fields": [
            {
                "name": f.name,
                "type": f.type,
                "values": list(f.values) if f.type == "enum" else [],
                "description": strip_java_rule_note(f.description, max_chars=240),
            }
            for f in defn.fields
            if f.visible
        ],
    }


def _available_templates(rs: ResourceSet, *, allow_offline: bool = False) -> dict[int, Template]:
    """返回本次路由允许选中的模板集合（线上仅限非下线模板，草稿态可含未上线草稿）。"""
    return {tid: tpl for tid, tpl in rs.templates.items() if allow_offline or not tpl.offline}


def extract_usage_dict(source: Any) -> dict[str, int]:
    """安全提取 Pydantic AI 运行结果的用量字典（优先按属性读取 RunUsage，避免触发废弃调用警告）。#Created By AiCoding(codex)"""
    if source is None:
        return {}
    raw_attr = getattr(source, "usage", None)
    if raw_attr is None:
        return {}
    try:
        u = raw_attr if hasattr(raw_attr, "requests") else (raw_attr() if callable(raw_attr) else raw_attr)
        return {
            "requests": int(getattr(u, "requests", 0) or 0),
            "toolCalls": int(getattr(u, "tool_calls", 0) or 0),
            "inputTokens": int(getattr(u, "input_tokens", 0) or 0),
            "outputTokens": int(getattr(u, "output_tokens", 0) or 0),
        }
    except Exception:  # noqa: BLE001
        return {}


# ============================================================================ 路由模型、结果与异常
class TemplateRouteCandidate(BaseModel):
    """路由阶段识别出的候选模板项。"""

    model_config = ConfigDict(extra="forbid")

    templateId: int = Field(description="在线模板编号")
    reason: str = Field(description="结合当前单据关键词与入参给出的匹配理由")
    level: Literal["高", "中", "低"] = Field(description="匹配置信度：高 / 中 / 低")


class TemplateRouteDecision(BaseModel):
    """无状态模板路由智能体的结构化决策输出。"""

    model_config = ConfigDict(extra="forbid")

    matched: bool = Field(description="是否匹配到可用模板")
    templateId: int | None = Field(default=None, description="最终选中的最匹配模板编号；无匹配时为 null")
    confidence: Literal["高", "中", "低"] = Field(default="低", description="最终选中模板的匹配置信度：高 / 中 / 低")
    reason: str = Field(default="", description="选中该模板或无法匹配的依据说明")
    candidates: list[TemplateRouteCandidate] = Field(
        default_factory=list,
        description="候选模板列表（最多 3 个，按置信度从高到低排列）",
    )


class TemplateRouteError(LookupError):
    """自动模板路由未能匹配到可用模板，携带原因、候选与置信度信息。"""

    def __init__(
        self,
        message: str,
        *,
        reason: str = "",
        candidates: list[dict[str, Any]] | None = None,
        confidence: str = "低",
    ) -> None:
        super().__init__(message)
        self.reason = reason or message
        self.candidates: list[dict[str, Any]] = list(candidates or [])
        self.confidence = confidence


@dataclass
class RouteResult:
    """自动模板路由成功后的结果摘要与用量统计。"""

    template_id: int
    template_name: str
    confidence: Literal["高", "中", "低"]
    reason: str
    candidates: list[dict[str, Any]]
    skills_loaded: list[str]
    duration_ms: int
    usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto": True,
            "templateId": self.template_id,
            "templateName": self.template_name,
            "confidence": self.confidence,
            "reason": self.reason,
            "candidates": [dict(c) for c in self.candidates],
            "skillsLoaded": list(self.skills_loaded),
            "durationMs": self.duration_ms,
        }


@dataclass
class RouteDeps:
    """无状态模板路由单次推理上下文。"""

    rev: str
    resources: ResourceSet
    inputs: dict[str, str]
    document: str
    run_id: str
    events: EventSink
    allow_offline: bool = False
    skills_loaded: list[str] = field(default_factory=list)
    _call_seq: int = 0

    def next_call_id(self) -> str:
        self._call_seq += 1
        return f"rt{self._call_seq}"


# ============================================================================ 路由只读工具（发射过程事件）
async def _route_load_skill(
    ctx: RunContext[RouteDeps],
    name: str = ROUTER_SKILL_NAME,
    doc: str = "",
    docs: list[str] | None = None,
) -> str:
    """加载路由专用 Skill（scope: chat，如 template-router）主说明或按需加载其子目录参考文档。

    Args:
        name: Skill 名称，默认 "template-router"，仅允许加载作用域为 chat 的技能。
        doc: 可选，按需加载的单个子文档相对路径（如 references/broadband.md）。
        docs: 可选，按需批量加载的子文档相对路径列表。
    """
    deps = ctx.deps
    req_name = (name or ROUTER_SKILL_NAME).strip() or ROUTER_SKILL_NAME
    raw_docs = collect_doc_requests(doc, docs)

    if raw_docs:
        rec_args: dict[str, Any] = (
            {"name": req_name, "doc": raw_docs[0]}
            if (docs is None and len(raw_docs) == 1)
            else {"name": req_name, "docs": raw_docs}
        )
    else:
        rec_args = {"name": req_name}

    text, ok, meta = _resolve_chat_skill(deps.resources, name=req_name, doc=doc, docs=docs)
    if ok:
        sid = str(meta["skill"])
        if sid not in deps.skills_loaded:
            deps.skills_loaded.append(sid)
        loaded_docs = list(meta.get("docs") or [])
        summary: dict[str, Any] = {"title": meta["title"]}
        if loaded_docs:
            summary["docs"] = loaded_docs
    else:
        summary = {"error": text}
    deps.events.emit(
        "tool",
        tool="load_skill",
        callId=deps.next_call_id(),
        args=rec_args,
        ok=ok,
        result=summary,
    )
    return text


async def _route_list_templates(ctx: RunContext[RouteDeps], keyword: str = "") -> list[dict[str, Any]]:
    """列出当前可用报告模板摘要（支持按关键词过滤）。

    Args:
        keyword: 可选过滤关键词（匹配模板编号、名称或描述），留空返回全部可用模板。
    """
    deps = ctx.deps
    items = list_online_templates(deps.resources, keyword=keyword, allow_offline=deps.allow_offline)
    deps.events.emit(
        "tool",
        tool="list_templates",
        callId=deps.next_call_id(),
        args={"keyword": keyword},
        ok=True,
        result={"count": len(items)},
    )
    return items


async def _route_get_template(ctx: RunContext[RouteDeps], templateId: int) -> dict[str, Any]:
    """查看指定可用模板的入参要求与可见报告字段说明。

    Args:
        templateId: 模板编号。
    """
    deps = ctx.deps
    res = get_online_template(deps.resources, templateId, allow_offline=deps.allow_offline)
    ok = bool(res.get("ok"))
    summary = {"id": res.get("id"), "name": res.get("name")} if ok else {"error": res.get("error")}
    deps.events.emit(
        "tool",
        tool="get_template",
        callId=deps.next_call_id(),
        args={"templateId": templateId},
        ok=ok,
        result=summary,
    )
    return res


def _build_route_tools(tool_retries: int) -> list[Tool[RouteDeps]]:
    return [
        Tool(_route_load_skill, name="load_skill", max_retries=tool_retries),
        Tool(_route_list_templates, name="list_templates", max_retries=tool_retries),
        Tool(_route_get_template, name="get_template", max_retries=tool_retries),
    ]


def _build_route_context_instructions(deps: RouteDeps, output_mode: str, settings: Any = None) -> str:
    """组装无状态路由器的动态上下文指令（仅包含入参与单据正文）。"""
    rs = deps.resources
    max_doc_chars = cfg_int(settings, "chat_max_doc_chars", ROUTE_MAX_DOC_CHARS)
    avail_count = len(_available_templates(rs, allow_offline=deps.allow_offline))
    chat_ids = rs.chat_skills()
    has_router = ROUTER_SKILL_NAME in chat_ids
    router_hint = (
        f'已配置 `{ROUTER_SKILL_NAME}`（请优先调用 `load_skill("{ROUTER_SKILL_NAME}")` 阅读路由总则，再按需加载命中的子文档）'
        if has_router
        else f"当前未配置 `{ROUTER_SKILL_NAME}`（请调用 `list_templates` 查看可用模板，必要时调用 `get_template` 核对详情）"
    )

    if deps.inputs:
        input_lines = "\n".join(f"- {k}：{v}" for k, v in deps.inputs.items() if str(k).strip())
    else:
        input_lines = "（当前无入参）"

    doc = deps.document or ""
    doc_total = len(doc)
    if not doc.strip():
        doc_header = "单据正文（0 字）："
        doc_body = "（调用方未提供单据正文）"
    elif doc_total > max_doc_chars:
        doc_header = f"单据正文（总长 {doc_total} 字，以下截取前 {max_doc_chars} 字）："
        doc_body = doc[:max_doc_chars] + "\n…（单据过长已截断）"
    else:
        doc_header = f"单据正文（共 {doc_total} 字）："
        doc_body = doc

    submit_hint = (
        "完成分析后，请调用 `submit_route_decision` 提交路由决策结果。"
        if output_mode == "tool"
        else "完成分析后，请直接输出符合 TemplateRouteDecision JSON Schema 的 JSON 对象（不要用 Markdown 代码块包裹）。"
    )

    return f"""## 当前路由环境（资源快照 {deps.rev}，可用模板共 {avail_count} 个）
- 路由规则：{router_hint}
- 本次传入入参：
{input_lines}

## {doc_header}
<document>
{doc_body}
</document>

## 提交方式
{submit_hint}"""


# ============================================================================ 无状态模板路由器
class TemplateRouter:
    """无状态模板路由器：复用 AgentRunner 的运行期模型快照并按 seq 缓存 Pydantic AI Agent。#Created By AiCoding(codex)"""

    def __init__(self, runner: AgentRunner) -> None:
        self.runner = runner
        self._cached_agent: tuple[tuple[Any, ...], Any, Any, Agent[RouteDeps, TemplateRouteDecision], float] | None = None

    def _snapshot_runtime(self) -> tuple[Any, Any, Any, Any]:
        bundle = getattr(self.runner, "_bundle", None)
        if bundle is not None:
            return bundle.seq, bundle.settings, bundle.model, bundle.model_settings
        return None, self.runner.settings, self.runner.model, self.runner.model_settings

    def _build_pydantic_agent(
        self,
        rt_settings: Any,
        rt_model: Any,
        rt_model_settings: Any,
    ) -> tuple[Agent[RouteDeps, TemplateRouteDecision], float]:
        mode = rt_settings.agent_output_mode
        output = build_output_spec(
            TemplateRouteDecision,
            name="submit_route_decision",
            description="提交自动路由匹配结果（matched、templateId、confidence、reason 与最多 3 个候选模板）。",
            settings=rt_settings,
        )

        agent: Agent[RouteDeps, TemplateRouteDecision] = Agent(
            rt_model,
            deps_type=RouteDeps,
            output_type=output,
            instructions=[
                ROUTER_SYSTEM_PROMPT,
                lambda ctx: _build_route_context_instructions(ctx.deps, mode, rt_settings),
            ],
            tools=_build_route_tools(rt_settings.agent_tool_retries),
            retries={
                "tools": rt_settings.agent_tool_retries,
                "output": rt_settings.agent_output_retries,
            },
            model_settings=rt_model_settings,
        )

        @agent.output_validator
        async def _validate_decision(
            ctx: RunContext[RouteDeps],
            out: TemplateRouteDecision,
        ) -> TemplateRouteDecision:
            avail = _available_templates(ctx.deps.resources, allow_offline=ctx.deps.allow_offline)
            avail_ids = sorted(avail)

            # 1) 拦截候选列表中不存在或已下线的模板 ID
            bad_cands = [c.templateId for c in out.candidates if c.templateId not in avail]
            if bad_cands:
                raise ModelRetry(
                    f"候选模板编号 {bad_cands} 不存在或已下线；"
                    f"只能选择可用模板，当前可用模板编号：{avail_ids}"
                )

            # 2) 拦截主选 templateId 不存在或已下线的情况
            if out.templateId is not None and out.templateId not in avail:
                raise ModelRetry(
                    f"选中的模板编号 {out.templateId} 不存在或已下线；"
                    f"只能选择可用模板，当前可用模板编号：{avail_ids}"
                )

            # 3) matched=True 但既未提供主选 templateId 也没有任何有效候选
            if out.matched and out.templateId is None and not out.candidates:
                raise ModelRetry(
                    "matched=True 时必须指定有效的 templateId 或至少提供 1 个有效候选模板；"
                    f"若确实无法匹配，请返回 matched=False 且 candidates=[]。当前可用模板编号：{avail_ids}"
                )

            # 4) 仅当 matched=False 且 candidates 为空且 templateId 为空时允许无匹配交卷（调用方转为 TemplateRouteError）
            if not out.matched and not out.candidates and out.templateId is None:
                reason = out.reason.strip() or "未能根据当前单据与入参匹配到合适的在线模板"
                return out.model_copy(
                    update={"matched": False, "templateId": None, "reason": reason, "candidates": []}
                )

            # 5) 汇总主选与全部有效候选（去重），按置信度 高 > 中 > 低 稳定排序，最高置信度直接放行不阻塞
            merged_order: list[int] = []
            by_tid: dict[int, TemplateRouteCandidate] = {}

            def _merge(tid: int, level: Literal["高", "中", "低"], reason: str) -> None:
                clean_reason = (reason or "").strip()
                if tid not in by_tid:
                    merged_order.append(tid)
                    by_tid[tid] = TemplateRouteCandidate(templateId=tid, level=level, reason=clean_reason)
                    return
                existing = by_tid[tid]
                best_level = level if _CONFIDENCE_RANK[level] < _CONFIDENCE_RANK[existing.level] else existing.level
                best_reason = existing.reason or clean_reason
                by_tid[tid] = TemplateRouteCandidate(templateId=tid, level=best_level, reason=best_reason)

            if out.templateId is not None:
                _merge(out.templateId, out.confidence, out.reason)
            for cand in out.candidates:
                _merge(cand.templateId, cand.level, cand.reason)

            ranked = sorted(
                (by_tid[tid] for tid in merged_order),
                key=lambda c: _CONFIDENCE_RANK.get(c.level, 99),
            )[:3]
            best = ranked[0]
            final_reason = best.reason or out.reason.strip() or f"自动匹配最高置信度模板 #{best.templateId}"
            return out.model_copy(
                update={
                    "matched": True,
                    "templateId": best.templateId,
                    "confidence": best.level,
                    "reason": final_reason,
                    "candidates": ranked,
                }
            )

        timeout_s = cfg_float(rt_settings, "chat_timeout_s", ROUTE_TIMEOUT_S)
        return agent, timeout_s

    def _get_or_build_agent(self) -> tuple[Agent[RouteDeps, TemplateRouteDecision], float]:
        """按运行期配置快照 seq 缓存路由 Agent，支持热重载立即失效重建。"""
        seq, rt_settings, rt_model, rt_model_settings = self._snapshot_runtime()
        cache_key = (
            seq,
            rt_settings.agent_output_mode,
            rt_settings.agent_native_strict,
            rt_settings.agent_tool_retries,
            rt_settings.agent_output_retries,
            cfg_float(rt_settings, "chat_timeout_s", ROUTE_TIMEOUT_S),
            cfg_int(rt_settings, "chat_max_doc_chars", ROUTE_MAX_DOC_CHARS),
        )
        cached = self._cached_agent
        if (
            cached is not None
            and cached[0] == cache_key
            and cached[1] is rt_model
            and cached[2] == rt_model_settings
        ):
            return cached[3], cached[4]
        agent, timeout_s = self._build_pydantic_agent(rt_settings, rt_model, rt_model_settings)
        self._cached_agent = (cache_key, rt_model, rt_model_settings, agent, timeout_s)
        return agent, timeout_s

    async def route(
        self,
        rev: str,
        rs: ResourceSet,
        *,
        inputs: dict[str, str],
        document: str,
        run_id: str,
        events: EventSink,
        allow_offline: bool = False,
    ) -> RouteResult:
        """执行无状态自动模板路由，返回最高置信度匹配结果；无可用模板或无法匹配时抛出 TemplateRouteError。"""
        t0 = time.monotonic()
        has_router = ROUTER_SKILL_NAME in rs.chat_skills()
        events.emit(
            "route_started",
            runId=run_id,
            rev=rev,
            routerSkill=ROUTER_SKILL_NAME if has_router else None,
        )

        avail = _available_templates(rs, allow_offline=allow_offline)
        if not avail:
            err_msg = "当前没有可用的在线模板"
            events.emit("route_failed", runId=run_id, error=err_msg, reason=err_msg, candidates=[])
            raise TemplateRouteError(err_msg, reason=err_msg, candidates=[])

        _, rt_settings, _, _ = self._snapshot_runtime()
        req_limit = cfg_int(rt_settings, "chat_request_limit", ROUTE_REQUEST_LIMIT)
        tool_limit = cfg_int(rt_settings, "chat_tool_calls_limit", ROUTE_TOOL_CALLS_LIMIT)
        agent, timeout_s = self._get_or_build_agent()

        deps = RouteDeps(
            rev=rev,
            resources=rs,
            inputs=inputs,
            document=document,
            run_id=run_id,
            events=events,
            allow_offline=allow_offline,
        )
        user_prompt = "请根据当前工单入参与单据正文，检索并选出最匹配的申告报告模板（按最高置信度返回）。"

        try:
            async with asyncio.timeout(timeout_s):
                result = await agent.run(
                    user_prompt,
                    deps=deps,
                    usage_limits=UsageLimits(request_limit=req_limit, tool_calls_limit=tool_limit),
                )
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            err_msg = f"自动模板路由超时（超过 {timeout_s:.0f} 秒）"
            events.emit("route_failed", runId=run_id, error=err_msg, reason=err_msg, candidates=[])
            raise TemplateRouteError(err_msg, reason=err_msg, candidates=[]) from exc
        except (UsageLimitExceeded, UnexpectedModelBehavior, ModelAPIError, AgentRunError) as exc:
            err_msg = sanitize_sensitive_text(f"自动模板路由失败：{exc}")
            events.emit("route_failed", runId=run_id, error=err_msg, reason=err_msg, candidates=[])
            raise TemplateRouteError(err_msg, reason=err_msg, candidates=[]) from exc
        except Exception as exc:  # noqa: BLE001 - 兜底未知异常并确保发射 route_failed 事件与脱敏错误
            err_msg = sanitize_sensitive_text(f"自动模板路由失败：{type(exc).__name__} {exc}".strip())
            events.emit("route_failed", runId=run_id, error=err_msg, reason=err_msg, candidates=[])
            raise TemplateRouteError(err_msg, reason=err_msg, candidates=[]) from exc

        decision = result.output
        duration_ms = int((time.monotonic() - t0) * 1000)
        usage = extract_usage_dict(result)

        if not decision.matched or decision.templateId is None or decision.templateId not in avail:
            reason = decision.reason.strip() or "未能根据当前单据与入参匹配到合适的在线模板"
            events.emit("route_failed", runId=run_id, error=reason, reason=reason, candidates=[])
            raise TemplateRouteError(reason, reason=reason, candidates=[], confidence=decision.confidence)

        tpl = avail[decision.templateId]
        cand_dicts = [
            {
                "templateId": c.templateId,
                "templateName": rs.templates[c.templateId].name if c.templateId in rs.templates else f"模板 {c.templateId}",
                "level": c.level,
                "reason": c.reason,
            }
            for c in decision.candidates
        ]
        events.emit(
            "route_completed",
            runId=run_id,
            templateId=tpl.id,
            templateName=tpl.name,
            confidence=decision.confidence,
            reason=decision.reason,
            candidates=cand_dicts,
            durationMs=duration_ms,
        )
        return RouteResult(
            template_id=tpl.id,
            template_name=tpl.name,
            confidence=decision.confidence,
            reason=decision.reason,
            candidates=cand_dicts,
            skills_loaded=list(deps.skills_loaded),
            duration_ms=duration_ms,
            usage=usage,
        )
