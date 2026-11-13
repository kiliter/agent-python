"""嵌入式聊天窗口核心编排服务：会话生命周期、聊天动作分发、后台运行联动与报告确认审计。

#Created By AiCoding(codex)
严格实现 docs/chat-embed-api.md §3 与 §4 契约语义。
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
import copy
from dataclasses import dataclass, field
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Any, Literal

from ..domain.jinja_env import render_body
from ..domain.resources import ResourceSet
from ..domain.template import Template
from ..runtime.runner import AgentRunner, RunRequest
from ..runtime.text_tools import safe_regex_fullmatch
from ..store.fsutil import now_iso
from ..store.publisher import Publisher
from ..store.releases import ReleaseNotFound, ReleaseStore
from ..store.runs import RunStore, new_run_id
from ..store.service import ResourceService
from .agent import (
    COMPACT_KEEP_RECENT,
    COMPACT_TRIGGER_MESSAGES,
    MANUAL_COMPACT_KEEP_RECENT,
    MANUAL_COMPACT_MIN_SLICE,
    ChatAgent,
    ChatDeps,
    cfg_int,
    strip_java_rule_note,
)
from .manager import ChatRunManager, RunCompletion
from .steps import sanitize_error_text
from .store import SESSION_ID_RE, ChatStore, inputs_fingerprint, session_id_for

log = logging.getLogger(__name__)

_LEVEL_RANK = {"高": 0, "中": 1, "低": 2}
_MAX_SESSION_KEY_LEN = 128
_MAX_RUN_INDEX = 4096


class ChatError(Exception):
    """聊天接口领域异常，携带 HTTP 状态码、统一错误码与附加详情字段。"""

    def __init__(self, status: int, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class ChatCaller:
    """聊天接口调用方身份：user 为管理端已登录用户，key 为外部嵌入页 API Key 调用。"""

    kind: Literal["user", "key"]
    name: str
    extra: dict[str, Any] = field(default_factory=dict)


def _check_params(tpl: Template, inputs: dict[str, str]) -> tuple[bool, list[dict[str, Any]]]:
    """对照模板入参声明生成完整 ParamSpec 列表，返回 (是否全部通过, specs)。"""
    safe_inputs = inputs or {}
    specs: list[dict[str, Any]] = []
    ok = True
    for inp in tpl.definition.inputs:
        raw = safe_inputs.get(inp.key)
        val = ("" if raw is None else str(raw)).strip()
        err: str | None = None
        if not val:
            if inp.required:
                err = f"缺少必填入参「{inp.key}」"
        elif inp.pattern:
            try:
                matched = safe_regex_fullmatch(inp.pattern, val)
            except ValueError as exc:
                err = f"入参「{inp.key}」校验正则不合法：{exc}"
            else:
                if not matched:
                    err = f"格式不正确，应符合 {inp.pattern}"
        if err is not None:
            ok = False
        specs.append({
            "key": inp.key,
            "required": inp.required,
            "description": inp.description,
            "sample": inp.sample,
            "pattern": inp.pattern,
            "value": val,
            "error": err,
        })
    return ok, specs


def _missing_required_keys(tpl: Template, inputs: dict[str, str]) -> list[str]:
    """返回模板中尚未填妥（未填或格式不匹配）的必填入参键名列表。"""
    _, specs = _check_params(tpl, inputs)
    return [s["key"] for s in specs if s["required"] and s["error"] is not None]


def _merge_steps(saved_steps: list[dict[str, Any]], live_steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """合并已持久化步骤与内存中实时步骤（按 seq 去重升序）。"""
    if not live_steps:
        return [dict(s) for s in (saved_steps or []) if isinstance(s, dict)]
    by_seq: dict[int, dict[str, Any]] = {}
    for s in saved_steps or []:
        if isinstance(s, dict) and isinstance(s.get("seq"), int):
            by_seq[s["seq"]] = dict(s)
    for s in live_steps:
        if isinstance(s, dict) and isinstance(s.get("seq"), int):
            by_seq[s["seq"]] = dict(s)
    return [by_seq[k] for k in sorted(by_seq)]


_REWRITE_HINT_WORDS = ("改写", "润色", "精简", "重写", "措辞", "口径", "未经", "证据校验")


def _parse_iso_ts(raw: Any) -> float | None:
    """将 ISO 时间字符串解析为秒级时间戳，解析失败时返回 None。"""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.strip()).timestamp()
    except ValueError:
        return None


def _has_rewrite_hint(*texts: str) -> bool:
    """判断消息或紧邻用户提问是否包含改写/润色相关提示词（仅用于同秒并列候选消歧）。"""
    combined = "\n".join(t for t in texts if t)
    return any(w in combined for w in _REWRITE_HINT_WORDS)


def _backfill_legacy_rewrite_links(out_messages: list[dict[str, Any]]) -> None:
    """为历史存量会话中未携带 rewriteRunId 的改写回复消息按一对一规则补全关联元数据。"""
    bound_versions: set[tuple[str, int]] = set()
    bound_msg_indices: set[int] = set()

    for idx, msg in enumerate(out_messages):
        if msg.get("role") != "assistant" or msg.get("kind") != "text":
            continue
        existing_rid = str(msg.get("rewriteRunId") or "").strip()
        if existing_rid:
            bound_msg_indices.add(idx)
            ver_no = msg.get("rewriteVersionNo")
            if isinstance(ver_no, int) and not isinstance(ver_no, bool) and ver_no >= 2:
                bound_versions.add((existing_rid, ver_no))

    unbound_versions: list[tuple[int, str, int, float | None]] = []
    for idx, msg in enumerate(out_messages):
        if msg.get("kind") != "run":
            continue
        run_id = str(msg.get("runId") or "").strip()
        if not run_id:
            continue
        for ver in msg.get("versions") or []:
            if not isinstance(ver, dict) or ver.get("kind") != "rewrite":
                continue
            raw_no = ver.get("no")
            ver_no = int(raw_no) if isinstance(raw_no, (int, float)) and not isinstance(raw_no, bool) else 0
            if ver_no < 2 or (run_id, ver_no) in bound_versions:
                continue
            unbound_versions.append((idx, run_id, ver_no, _parse_iso_ts(ver.get("createdAt"))))

    if not unbound_versions:
        return

    candidate_msgs: list[tuple[int, float | None, str, str]] = []
    for idx, msg in enumerate(out_messages):
        if idx in bound_msg_indices:
            continue
        if msg.get("role") == "assistant" and msg.get("kind") == "text":
            prev_user_text = ""
            if idx > 0 and out_messages[idx - 1].get("role") == "user" and out_messages[idx - 1].get("kind") == "text":
                prev_user_text = str(out_messages[idx - 1].get("text") or "")
            candidate_msgs.append((
                idx,
                _parse_iso_ts(msg.get("createdAt")),
                str(msg.get("text") or ""),
                prev_user_text,
            ))

    if not candidate_msgs:
        return

    # 1) 优先按 createdAt 相差 5 秒以内做最优一对一匹配（时间差最小优先，同秒内改写语义优先）
    ts_pairs: list[tuple[float, int, int, int, int, int, str]] = []
    for run_idx, run_id, ver_no, ver_ts in unbound_versions:
        if ver_ts is None:
            continue
        for msg_idx, msg_ts, msg_text, prev_user_text in candidate_msgs:
            if msg_idx <= run_idx or msg_ts is None:
                continue
            diff = msg_ts - ver_ts
            abs_diff = abs(diff)
            if abs_diff <= 5.0:
                before_penalty = 0 if diff >= 0.0 else 1
                run_id_penalty = 0 if run_id in msg_text else 1
                hint_penalty = 0 if _has_rewrite_hint(msg_text, prev_user_text) else 1
                ts_pairs.append((abs_diff, before_penalty, run_id_penalty, hint_penalty, ver_no, msg_idx, run_id))

    ts_pairs.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4], item[5]))
    for _, _, _, _, ver_no, msg_idx, run_id in ts_pairs:
        if (run_id, ver_no) in bound_versions or msg_idx in bound_msg_indices:
            continue
        out_messages[msg_idx]["rewriteRunId"] = run_id
        out_messages[msg_idx]["rewriteVersionNo"] = ver_no
        bound_versions.add((run_id, ver_no))
        bound_msg_indices.add(msg_idx)

    # 2) 对仍未绑定的 rewrite 版本，回退匹配该运行卡片之后正文显式包含 runId 的无绑定助手消息
    for run_idx, run_id, ver_no, ver_ts in unbound_versions:
        if (run_id, ver_no) in bound_versions:
            continue
        text_matches: list[tuple[int, int]] = []
        for msg_idx, msg_ts, msg_text, prev_user_text in candidate_msgs:
            if msg_idx <= run_idx or msg_idx in bound_msg_indices:
                continue
            if run_id not in msg_text:
                continue
            if ver_ts is not None and msg_ts is not None and msg_ts < ver_ts - 5.0:
                continue
            hint_penalty = 0 if _has_rewrite_hint(msg_text, prev_user_text) else 1
            text_matches.append((hint_penalty, msg_idx))
        if text_matches:
            text_matches.sort()
            chosen_idx = text_matches[0][1]
            out_messages[chosen_idx]["rewriteRunId"] = run_id
            out_messages[chosen_idx]["rewriteVersionNo"] = ver_no
            bound_versions.add((run_id, ver_no))
            bound_msg_indices.add(chosen_idx)


class ChatService:
    """聊天选模板窗口业务编排服务。"""

    def __init__(
        self,
        store: ChatStore,
        manager: ChatRunManager,
        runner: AgentRunner,
        releases: ReleaseStore,
        service: ResourceService,
        runs: RunStore,
        publisher: Publisher,
    ) -> None:
        self.store = store
        self.manager = manager
        self.runner = runner
        self.releases = releases
        self.service = service
        self.runs = runs
        self.publisher = publisher
        self.chat_agent = ChatAgent(runner)
        self._run_to_session: OrderedDict[str, str] = OrderedDict()

    async def aclose(self) -> None:
        """应用退出时关闭后台运行管理器。"""
        await self.manager.aclose()

    # ------------------------------------------------------------------ 内部工具
    def _runtime_settings(self) -> Any:
        return getattr(self.runner, "settings", None)

    def _remember_run(self, run_id: str, session_id: str) -> None:
        if not run_id or not session_id:
            return
        self._run_to_session[run_id] = session_id
        self._run_to_session.move_to_end(run_id)
        while len(self._run_to_session) > _MAX_RUN_INDEX:
            self._run_to_session.popitem(last=False)

    @staticmethod
    def _next_msg_id(session: dict[str, Any], prefix: str = "m") -> str:
        seq = int(session.get("seq", 0)) + 1
        session["seq"] = seq
        return f"{prefix}_{seq}"

    @staticmethod
    def _check_sid_format(sid: str) -> str:
        clean = (sid or "").strip()
        if not SESSION_ID_RE.match(clean):
            raise ChatError(404, "SESSION_NOT_FOUND", f"会话 {sid} 不存在")
        return clean

    @staticmethod
    def _ensure_caller_allowed(target: str, caller: ChatCaller | None) -> None:
        if target == "draft" and (caller is None or caller.kind != "user"):
            raise ChatError(403, "DRAFT_FORBIDDEN", "仅管理端登录用户可使用草稿模式（target='draft'）")

    @staticmethod
    def _effective_memory_state(session: dict[str, Any], total_msgs: int) -> tuple[str, int]:
        """读取并清洗会话滚动记忆摘要与归档水位线，损坏或不一致状态自动自愈为 ('', 0)。"""
        raw_summary = session.get("memorySummary")
        summary = raw_summary.strip() if isinstance(raw_summary, str) else ""
        raw_up_to = session.get("summarizedUpTo")
        if (
            not summary
            or not isinstance(raw_up_to, int)
            or isinstance(raw_up_to, bool)
            or raw_up_to <= 0
        ):
            return "", 0
        safe_total = max(0, total_msgs) if isinstance(total_msgs, int) and not isinstance(total_msgs, bool) else 0
        clamped = min(raw_up_to, safe_total)
        if clamped <= 0:
            return "", 0
        return summary, clamped

    async def _capture_snapshot(self, target: str, *, allow_empty: bool = False) -> tuple[str, ResourceSet]:
        """按会话目标捕获当前资源快照。"""
        if target == "draft":
            live = self.releases.live_rev() or "-"
            rs = await asyncio.to_thread(self.service.overlay)
            return f"{live}+草稿", rs
        snap = self.releases.try_live_snapshot()
        if snap is not None:
            return snap
        try:
            return await asyncio.to_thread(self.releases.live_snapshot)
        except ReleaseNotFound as exc:
            if allow_empty:
                return "-", ResourceSet()
            raise ChatError(404, "TEMPLATE_UNAVAILABLE", "当前尚无已发布的线上资源版本") from exc

    def _heal_interrupted_in_place(self, session: dict[str, Any]) -> bool:
        """检查会话中遗留的 RUNNING 卡片，不在 manager 运行中的一律恢复为 INTERRUPTED。"""
        changed = False
        for msg in session.get("messages") or []:
            if not isinstance(msg, dict) or msg.get("kind") != "run":
                continue
            rid = str(msg.get("runId") or "")
            if rid:
                self._remember_run(rid, str(session.get("sessionId") or ""))
            if msg.get("status") == "RUNNING" and (not rid or not self.manager.is_running(rid)):
                msg["status"] = "INTERRUPTED"
                msg["error"] = "服务重启导致运行中断，请重新运行"
                changed = True
        return changed

    def _format_message_view(
        self,
        msg: dict[str, Any],
        rs: ResourceSet,
        session_inputs: dict[str, str],
    ) -> dict[str, Any]:
        """动态补算单条消息中的模板在线状态、缺参提示与在途实时步骤（按消息类型定向浅拷贝避免全量深拷贝大正文）。"""
        out = dict(msg)
        kind = out.get("kind")
        if kind == "recommend":
            items_out: list[dict[str, Any]] = []
            for item in out.get("items") or []:
                if not isinstance(item, dict):
                    continue
                tid = int(item.get("templateId", 0))
                tpl = rs.templates.get(tid)
                offline = tpl is None or tpl.offline
                it_copy = dict(item)
                it_copy["offline"] = offline
                if tpl is not None and not offline:
                    it_copy["templateName"] = tpl.name
                    it_copy["missingRequired"] = _missing_required_keys(tpl, session_inputs)
                elif isinstance(it_copy.get("missingRequired"), list):
                    it_copy["missingRequired"] = list(it_copy["missingRequired"])
                items_out.append(it_copy)
            out["items"] = items_out
        elif kind == "ask_params":
            if isinstance(out.get("params"), list):
                out["params"] = [dict(p) for p in out["params"] if isinstance(p, dict)]
        elif kind == "run":
            tid = int(out.get("templateId", 0))
            tpl = rs.templates.get(tid)
            out["templateOffline"] = tpl is None or tpl.offline
            rid = str(out.get("runId") or "")
            live_steps = self.manager.get_steps(rid) if rid else None
            out["steps"] = _merge_steps(out.get("steps") or [], live_steps)
            out["missingShown"] = list(out.get("missingShown") or [])
            out["versions"] = [dict(v) for v in (out.get("versions") or []) if isinstance(v, dict)]
        return out

    def _build_view(
        self,
        session: dict[str, Any],
        rs: ResourceSet,
        *,
        created: bool | None = None,
        inputs_changed: bool | None = None,
    ) -> dict[str, Any]:
        """构造严格符合契约 §3 ChatSession 的对外视图，剔除内部存储字段。"""
        sid = str(session["sessionId"])
        cur_inputs = dict(session.get("inputs") or {})
        raw_sources = session.get("inputSources") or {}
        cur_sources: dict[str, str] = {
            k: ("用户补充" if raw_sources.get(k) == "用户补充" else "上层")
            for k in cur_inputs
        }
        out_messages = [
            self._format_message_view(m, rs, cur_inputs)
            for m in (session.get("messages") or [])
            if isinstance(m, dict)
        ]
        _backfill_legacy_rewrite_links(out_messages)
        eff_summary, eff_up_to = self._effective_memory_state(session, len(out_messages))
        active_run_id = self.manager.has_active_run(sid)
        raw_confirmed = session.get("confirmed")
        rt_settings = self._runtime_settings()
        keep_manual = cfg_int(rt_settings, "chat_manual_compact_keep_recent", MANUAL_COMPACT_KEEP_RECENT)
        min_slice = cfg_int(rt_settings, "chat_manual_compact_min_slice", MANUAL_COMPACT_MIN_SLICE)
        view: dict[str, Any] = {
            "sessionId": sid,
            "userId": str(session["userId"]),
            "orderId": str(session["orderId"]),
            "target": "draft" if session.get("target") == "draft" else "online",
            "createdAt": str(session["createdAt"]),
            "updatedAt": str(session["updatedAt"]),
            "inputs": cur_inputs,
            "inputSources": cur_sources,
            "inputsVersion": int(session.get("inputsVersion", 1)),
            "documentChars": len(session.get("document") or ""),
            "activeRunId": active_run_id,
            "confirmed": dict(raw_confirmed) if isinstance(raw_confirmed, dict) else None,
            "memorySummary": eff_summary,
            "summarizedUpTo": eff_up_to,
            "manualCompactKeepRecent": keep_manual,
            "manualCompactMinMessages": keep_manual + min_slice,
            "messages": out_messages,
        }
        if created is not None:
            view["created"] = created
        if inputs_changed is not None:
            view["inputsChanged"] = inputs_changed
        return view

    # ------------------------------------------------------------------ 会话生命周期
    async def open_session(
        self,
        user_id: str,
        order_id: str,
        inputs: dict[str, Any] | None = None,
        document: str | None = "",
        target: str = "online",
        *,
        caller: ChatCaller,
    ) -> dict[str, Any]:
        """创建或按 (userId, orderId) 恢复会话，比对入参指纹处理更新与重启中断恢复。"""
        uid = (user_id or "").strip()
        oid = (order_id or "").strip()
        if (
            not uid
            or not oid
            or len(uid) > _MAX_SESSION_KEY_LEN
            or len(oid) > _MAX_SESSION_KEY_LEN
            or "\x00" in uid
            or "\x00" in oid
        ):
            raise ChatError(
                400,
                "INVALID_SESSION_KEY",
                f"userId 和 orderId 必填且长度不能超过 {_MAX_SESSION_KEY_LEN} 个字符",
            )

        tgt = (target or "online").strip() or "online"
        if tgt not in ("online", "draft"):
            raise ChatError(400, "INVALID_TARGET", "target 参数只能为 online 或 draft")
        self._ensure_caller_allowed(tgt, caller)

        clean_inputs = {
            str(k).strip(): ("" if v is None else str(v)).strip()
            for k, v in (inputs or {}).items()
            if str(k).strip()
        }
        clean_doc = "" if document is None else str(document)
        fp = inputs_fingerprint(clean_inputs, clean_doc)
        sid = session_id_for(uid, oid)
        _, rs = await self._capture_snapshot(tgt, allow_empty=True)

        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                now = now_iso()
                init_inputs = {k: v for k, v in clean_inputs.items() if v}
                init_sources = {k: "上层" for k in init_inputs}
                session = {
                    "sessionId": sid,
                    "userId": uid,
                    "orderId": oid,
                    "target": tgt,
                    "createdAt": now,
                    "updatedAt": now,
                    "inputs": init_inputs,
                    "inputSources": init_sources,
                    "inputsVersion": 1,
                    "document": clean_doc,
                    "fingerprint": fp,
                    "seq": 0,
                    "recommended": {},
                    "confirmed": None,
                    "confirmRecords": [],
                    "memorySummary": "",
                    "summarizedUpTo": 0,
                    "messages": [],
                }
                saved = await self.store.asave(session)
                return self._build_view(saved, rs, created=True, inputs_changed=False)

            # 严禁仅持 API Key 的调用方通过传入 target="online" 篡改或读取已有草稿态会话
            self._ensure_caller_allowed(str(session.get("target") or "online"), caller)

            created = False
            inputs_changed = False
            dirty = False

            if session.get("target") != tgt:
                session["target"] = tgt
                dirty = True

            if session.get("fingerprint") != fp:
                session["inputsVersion"] = int(session.get("inputsVersion", 1)) + 1
                inputs_changed = True
                dirty = True

                old_inputs: dict[str, str] = session.get("inputs") or {}
                old_sources: dict[str, str] = session.get("inputSources") or {}
                merged_inputs: dict[str, str] = {}
                merged_sources: dict[str, str] = {}

                # 1. 先保留所有「用户补充」来源的非空键值；旧「上层」来源键不预留（本次置空或移除即同步移除）
                for k, v in old_inputs.items():
                    val = str(v).strip()
                    if old_sources.get(k) == "用户补充" and val:
                        merged_inputs[k] = val
                        merged_sources[k] = "用户补充"

                # 2. 上层本次非空键值覆盖同名键（含覆盖旧「用户补充」），标记来源为「上层」
                for k, v in clean_inputs.items():
                    if v:
                        merged_inputs[k] = v
                        merged_sources[k] = "上层"

                session["inputs"] = merged_inputs
                session["inputSources"] = merged_sources
                session["document"] = clean_doc
                session["fingerprint"] = fp

                for msg in session.get("messages") or []:
                    if isinstance(msg, dict) and msg.get("kind") == "run":
                        msg["stale"] = True

                session.setdefault("messages", []).append({
                    "id": self._next_msg_id(session, "m_div"),
                    "role": "system",
                    "kind": "divider",
                    "createdAt": now_iso(),
                    "text": "上层入参或单据已更新，历史生成结果已标记为旧入参",
                })

            if self._heal_interrupted_in_place(session):
                dirty = True

            saved = await self.store.asave(session) if dirty else session
            return self._build_view(saved, rs, created=created, inputs_changed=inputs_changed)

    async def get_session_view(self, sid: str, *, caller: ChatCaller | None = None) -> dict[str, Any]:
        """读取会话对外视图，自动修复遗留 RUNNING 状态并计算模板在线状态。"""
        sid = self._check_sid_format(sid)
        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                raise ChatError(404, "SESSION_NOT_FOUND", f"会话 {sid} 不存在")
            self._ensure_caller_allowed(str(session.get("target") or "online"), caller)
            if self._heal_interrupted_in_place(session):
                session = await self.store.asave(session)
        _, rs = await self._capture_snapshot(str(session.get("target") or "online"), allow_empty=True)
        return self._build_view(session, rs)

    async def list_templates(self, sid: str, q: str = "", *, caller: ChatCaller | None = None) -> list[dict[str, Any]]:
        """返回换模板弹窗的模板列表：推荐过的模板排前面（高>中>低），附带最近一次运行状态。"""
        sid = self._check_sid_format(sid)
        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                raise ChatError(404, "SESSION_NOT_FOUND", f"会话 {sid} 不存在")
            self._ensure_caller_allowed(str(session.get("target") or "online"), caller)
            if self._heal_interrupted_in_place(session):
                session = await self.store.asave(session)

        _, rs = await self._capture_snapshot(str(session.get("target") or "online"), allow_empty=True)

        rec_map: dict[int, str] = {}
        for k, lvl in (session.get("recommended") or {}).items():
            if str(k).isdigit() and lvl in _LEVEL_RANK:
                rec_map[int(k)] = str(lvl)
        # 兜底：若 recommended 字典未覆盖，从历史 recommend 消息补齐
        for m in session.get("messages") or []:
            if isinstance(m, dict) and m.get("kind") == "recommend":
                for it in m.get("items") or []:
                    if isinstance(it, dict) and isinstance(it.get("templateId"), int) and it.get("level") in _LEVEL_RANK:
                        rec_map.setdefault(it["templateId"], str(it["level"]))

        last_status: dict[int, str] = {}
        known_names: dict[int, str] = {}
        for m in session.get("messages") or []:
            if isinstance(m, dict) and m.get("kind") == "run" and m.get("templateId") is not None:
                tid = int(m["templateId"])
                last_status[tid] = str(m.get("status") or "FAILED")
                if m.get("templateName"):
                    known_names[tid] = str(m["templateName"])

        candidate_ids = {tid for tid, t in rs.templates.items() if not t.offline}
        candidate_ids |= set(rec_map.keys()) | set(last_status.keys())

        kw = (q or "").strip().lower()
        items: list[dict[str, Any]] = []
        for tid in candidate_ids:
            tpl = rs.templates.get(tid)
            name = tpl.name if tpl is not None else known_names.get(tid, f"模板{tid}")
            desc = tpl.definition.description if tpl is not None else ""
            offline = tpl is None or tpl.offline
            if kw and kw not in str(tid).lower() and kw not in name.lower() and kw not in desc.lower():
                continue
            items.append({
                "templateId": tid,
                "templateName": name,
                "description": desc,
                "offline": offline,
                "recommendLevel": rec_map.get(tid),
                "lastStatus": last_status.get(tid),
            })

        items.sort(
            key=lambda it: (
                0 if it["recommendLevel"] in _LEVEL_RANK else 1,
                _LEVEL_RANK.get(it["recommendLevel"], 99),
                it["templateId"],
            )
        )
        return items

    async def get_template_preview(
        self,
        sid: str,
        template_id: int,
        *,
        caller: ChatCaller | None = None,
    ) -> dict[str, Any]:
        """返回指定模板的结构详情、入参当前值、可见字段说明与预填充样例正文（已下线模板亦允许预览）。#Created By AiCoding(codex)"""
        sid = self._check_sid_format(sid)
        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                raise ChatError(404, "SESSION_NOT_FOUND", f"会话 {sid} 不存在")
            target = str(session.get("target") or "online")
            self._ensure_caller_allowed(target, caller)
            if self._heal_interrupted_in_place(session):
                session = await self.store.asave(session)
            session_inputs = dict(session.get("inputs") or {})

        rev, rs = await self._capture_snapshot(target, allow_empty=True)
        tpl = rs.templates.get(template_id) if template_id > 0 else None
        if tpl is None:
            raise ChatError(404, "TEMPLATE_UNAVAILABLE", f"模板 {template_id} 不存在")

        sample_ctx: dict[str, Any] = {}
        for f in tpl.definition.fields:
            if f.is_list:
                sample_ctx[f.name] = [
                    {
                        col.name: (
                            col.values[0]
                            if col.type == "enum" and col.values
                            else f"【{col.name}】"
                        )
                        for col in f.columns
                    }
                ]
            elif f.type == "enum" and f.values:
                sample_ctx[f.name] = f.values[0]
            else:
                sample_ctx[f.name] = f.defaultValue if f.defaultValue else f"【{f.name}】"

        try:
            sample_md, _ = render_body(tpl.body, sample_ctx)
        except Exception:  # noqa: BLE001 - 草稿语法异常时回退展示原稿
            sample_md = tpl.body

        return {
            "templateId": tpl.id,
            "templateName": tpl.name,
            "description": tpl.definition.description or "",
            "offline": bool(tpl.offline),
            "rev": rev,
            "bodyText": tpl.body,
            "sampleMarkdown": sample_md,
            "inputs": [
                {
                    "key": inp.key,
                    "required": inp.required,
                    "description": inp.description or "",
                    "sample": inp.sample or "",
                    "pattern": inp.pattern,
                    "currentValue": str(session_inputs.get(inp.key, "")),
                }
                for inp in tpl.definition.inputs
            ],
            "fields": [
                {
                    "name": f.name,
                    "type": f.type,
                    "values": list(f.values),
                    "columns": [
                        {"name": c.name, "type": c.type, "values": list(c.values)}
                        for c in f.columns
                    ],
                    "description": strip_java_rule_note(f.description),
                }
                for f in tpl.definition.fields
                if f.visible
            ],
        }

    @staticmethod
    def _apply_extracted_inputs(cur: dict[str, Any], extracted: dict[str, str]) -> bool:
        """将聊天智能体从本轮自然语言中提取的非空入参合并入当前会话，减少重复落盘次数。"""
        if not extracted:
            return False
        cur_inp = cur.setdefault("inputs", {})
        cur_src = cur.setdefault("inputSources", {})
        for k, v in extracted.items():
            cur_inp[k] = v
            cur_src[k] = "用户补充"
        return True

    # ------------------------------------------------------------------ 模板运行与事件流
    async def start_run(
        self,
        sid: str,
        template_id: int,
        extra_inputs: dict[str, Any] | None = None,
        *,
        caller: ChatCaller,
        prompt_text: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """校验并发互斥、模板在线与入参完整性；缺参返回 ask_params，齐全则启动后台填报并返回 RUNNING 卡片。"""
        sid = self._check_sid_format(sid)
        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                raise ChatError(404, "SESSION_NOT_FOUND", f"会话 {sid} 不存在")
            target = str(session.get("target") or "online")
            self._ensure_caller_allowed(target, caller)
            if self._heal_interrupted_in_place(session):
                session = await self.store.asave(session)

            if self.manager.has_active_run(sid) is not None:
                raise ChatError(409, "RUN_IN_PROGRESS", "当前会话已有正在运行的任务，请等待完成或先停止")

            rev, rs = await self._capture_snapshot(target, allow_empty=False)
            tpl = rs.templates.get(template_id) if template_id > 0 else None
            if tpl is None or tpl.offline:
                raise ChatError(404, "TEMPLATE_UNAVAILABLE", f"模板 {template_id} 不存在或已下线")

            if extra_inputs:
                cur_inputs = session.setdefault("inputs", {})
                cur_sources = session.setdefault("inputSources", {})
                for k, v in extra_inputs.items():
                    key = str(k).strip()
                    if not key:
                        continue
                    val = ("" if v is None else str(v)).strip()
                    if val:
                        cur_inputs[key] = val
                        cur_sources[key] = "用户补充"
                    elif cur_sources.get(key) == "用户补充":
                        # 允许用户在补参卡片中清空此前误填的可选补充入参，同时不影响上层传入字段
                        cur_inputs.pop(key, None)
                        cur_sources.pop(key, None)

            ok, specs = _check_params(tpl, session.get("inputs") or {})
            if not ok:
                ask_msg: dict[str, Any] = {
                    "id": self._next_msg_id(session, "m_ask"),
                    "role": "assistant",
                    "kind": "ask_params",
                    "createdAt": now_iso(),
                    "text": (prompt_text or "").strip() or f"运行模板「{tpl.name}」前请补充或修正以下参数：",
                    "templateId": tpl.id,
                    "templateName": tpl.name,
                    "params": specs,
                }
                session.setdefault("messages", []).append(ask_msg)
                saved = await self.store.asave(session)
                return copy.deepcopy(ask_msg), self._build_view(saved, rs)

            run_id = new_run_id()
            run_msg: dict[str, Any] = {
                "id": f"m_run_{run_id}",
                "role": "assistant",
                "kind": "run",
                "createdAt": now_iso(),
                "runId": run_id,
                "templateId": tpl.id,
                "templateName": tpl.name,
                "status": "RUNNING",
                "rev": rev,
                "inputsVersion": int(session.get("inputsVersion", 1)),
                "stale": False,
                "templateOffline": False,
                "steps": [],
                "durationMs": 0,
                "error": None,
                "missingShown": [],
                "foundCount": 0,
                "totalCount": len(tpl.definition.fields),
                "versions": [],
                "confirmed": False,
            }
            session.setdefault("messages", []).append(run_msg)
            self._remember_run(run_id, sid)
            saved = await self.store.asave(session)

            req = RunRequest(
                template_id=tpl.id,
                inputs=dict(saved.get("inputs") or {}),
                document=str(saved.get("document") or ""),
                entry="聊天窗口",
                target="draft" if target == "draft" else "online",
                operator=f"chat:{saved['userId']}",
                extra={
                    "sessionId": sid,
                    "userId": saved["userId"],
                    "orderId": saved["orderId"],
                },
                run_id=run_id,
            )
            try:
                self.manager.start(sid, req, resources=rs, on_complete=self._on_run_complete)
            except BaseException:
                # 防御性回滚：若启动同步抛异常则移除刚追加的卡片
                saved["messages"] = [m for m in saved.get("messages", []) if m.get("id") != run_msg["id"]]
                await self.store.asave(saved)
                raise

            return copy.deepcopy(run_msg), self._build_view(saved, rs)

    async def _on_run_complete(self, comp: RunCompletion) -> dict[str, Any]:
        """后台填报任务结束时的持久化回调，更新 run 卡片并返回最新 ChatMessage 供推送 final。"""
        sid = comp.session_id
        self._remember_run(comp.run_id, sid)
        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                return {
                    "id": f"m_run_{comp.run_id}",
                    "role": "assistant",
                    "kind": "run",
                    "createdAt": now_iso(),
                    "runId": comp.run_id,
                    "templateId": 0,
                    "templateName": "",
                    "status": "CANCELLED" if comp.cancelled else "FAILED",
                    "rev": "-",
                    "inputsVersion": 1,
                    "stale": False,
                    "templateOffline": False,
                    "steps": list(comp.steps or []),
                    "durationMs": int(comp.duration_ms or 0),
                    "error": (
                        "运行已手动停止"
                        if comp.cancelled
                        else (sanitize_error_text(comp.error, fallback="会话不存在") if comp.error else "会话不存在")
                    ),
                    "missingShown": [],
                    "foundCount": 0,
                    "totalCount": 0,
                    "versions": [],
                    "confirmed": False,
                }

            target = str(session.get("target") or "online")
            card = next(
                (
                    m for m in (session.get("messages") or [])
                    if isinstance(m, dict) and m.get("kind") == "run" and m.get("runId") == comp.run_id
                ),
                None,
            )
            if card is None:
                card = {
                    "id": f"m_run_{comp.run_id}",
                    "role": "assistant",
                    "kind": "run",
                    "createdAt": now_iso(),
                    "runId": comp.run_id,
                    "templateId": int((comp.outcome or {}).get("templateId") or 0),
                    "templateName": str((comp.outcome or {}).get("templateName") or ""),
                    "status": "FAILED",
                    "rev": "-",
                    "inputsVersion": int(session.get("inputsVersion", 1)),
                    "stale": False,
                    "templateOffline": False,
                    "steps": [],
                    "durationMs": 0,
                    "error": None,
                    "missingShown": [],
                    "foundCount": 0,
                    "totalCount": 0,
                    "versions": [],
                    "confirmed": False,
                }
                session.setdefault("messages", []).append(card)

            if comp.cancelled:
                card["status"] = "CANCELLED"
                card["error"] = "运行已手动停止"
            elif comp.outcome is not None:
                outcome = comp.outcome
                st = str(outcome.get("status") or "FAILED")
                card["status"] = st
                card["rev"] = str(outcome.get("rev") or card.get("rev") or "-")
                raw_err = outcome.get("error")
                card["error"] = sanitize_error_text(raw_err, fallback="运行失败") if raw_err else None
                card["missingShown"] = list(outcome.get("missingShown") or [])
                card["foundCount"] = int(outcome.get("foundCount") or 0)
                card["totalCount"] = int(outcome.get("totalCount") or 0)
                if st in ("SUCCESS", "PARTIAL") and outcome.get("report") is not None:
                    card["versions"] = [{
                        "no": 1,
                        "kind": "original",
                        "markdown": str(outcome["report"]),
                        "createdAt": now_iso(),
                        "note": "智能体基于证据核验生成",
                    }]
            else:
                card["status"] = "FAILED"
                card["error"] = sanitize_error_text(comp.error, fallback="运行失败") if comp.error else "运行失败"

            card["steps"] = list(comp.steps or [])
            card["durationMs"] = int(comp.duration_ms or 0)
            saved = await self.store.asave(session)
            cur_inputs = dict(saved.get("inputs") or {})

        _, rs = await self._capture_snapshot(target, allow_empty=True)
        return self._format_message_view(card, rs, cur_inputs)

    # ------------------------------------------------------------------ 聊天对话流与上下文压缩
    async def _persist_compaction_if_monotonic(
        self,
        sid: str,
        *,
        cutoff: int,
        anchor_msg_id: str,
        new_summary: str,
    ) -> dict[str, Any] | None:
        """在会话锁内按单调水位线与边界消息 ID 锚点原子落盘压缩摘要，防止并发乱序回退。"""
        clean_summary = (new_summary or "").strip()
        if not clean_summary or cutoff <= 0:
            return None
        async with self.store.lock_for(sid):
            cur = await self.store.aget(sid)
            if cur is None:
                return None
            cur_msgs = [m for m in (cur.get("messages") or []) if isinstance(m, dict)]
            _, cur_up_to = self._effective_memory_state(cur, len(cur_msgs))
            if (
                cutoff > cur_up_to
                and len(cur_msgs) >= cutoff
                and str(cur_msgs[cutoff - 1].get("id") or "") == anchor_msg_id
            ):
                cur["memorySummary"] = clean_summary
                cur["summarizedUpTo"] = cutoff
                return await self.store.asave(cur)
            return cur

    async def compact_session(self, sid: str, *, caller: ChatCaller) -> dict[str, Any]:
        """手动触发会话早期对话滚动压缩，归档前序消息至记忆摘要并保留最近原文消息。"""
        sid = self._check_sid_format(sid)
        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                raise ChatError(404, "SESSION_NOT_FOUND", f"会话 {sid} 不存在")
            target = str(session.get("target") or "online")
            self._ensure_caller_allowed(target, caller)
            if self._heal_interrupted_in_place(session):
                session = await self.store.asave(session)
            _, rs = await self._capture_snapshot(target, allow_empty=True)
            history = [m for m in (session.get("messages") or []) if isinstance(m, dict)]
            memory_summary, prev_up_to = self._effective_memory_state(session, len(history))

        rt_settings = self._runtime_settings()
        keep_manual = cfg_int(rt_settings, "chat_manual_compact_keep_recent", MANUAL_COMPACT_KEEP_RECENT)
        min_slice = cfg_int(rt_settings, "chat_manual_compact_min_slice", MANUAL_COMPACT_MIN_SLICE)
        cutoff = len(history) - keep_manual
        if cutoff - prev_up_to < min_slice:
            return {
                "compacted": False,
                "summarizedCount": 0,
                "summarizedUpTo": prev_up_to,
                "memorySummary": memory_summary,
                "session": self._build_view(session, rs),
            }

        slice_to_compact = history[prev_up_to:cutoff]
        anchor_msg_id = str(history[cutoff - 1].get("id") or "")
        try:
            new_summary = await self.chat_agent.summarize_history(memory_summary, slice_to_compact)
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            log.warning("手动压缩聊天上下文超时 sid=%s", sid)
            raise ChatError(504, "CHAT_COMPACT_TIMEOUT", "压缩对话上下文超时，请稍后重试") from exc
        except Exception as exc:  # noqa: BLE001
            safe_reason = sanitize_error_text(exc, fallback=type(exc).__name__)
            log.warning("手动压缩聊天上下文失败 sid=%s：%s", sid, safe_reason)
            raise ChatError(502, "CHAT_COMPACT_ERROR", f"压缩对话上下文失败：{safe_reason}") from exc

        saved_session = await self._persist_compaction_if_monotonic(
            sid,
            cutoff=cutoff,
            anchor_msg_id=anchor_msg_id,
            new_summary=new_summary,
        )
        if saved_session is None:
            raise ChatError(404, "SESSION_NOT_FOUND", f"会话 {sid} 不存在")
        saved_msgs = [m for m in (saved_session.get("messages") or []) if isinstance(m, dict)]
        eff_summary, eff_up_to = self._effective_memory_state(saved_session, len(saved_msgs))
        actual_count = max(0, eff_up_to - prev_up_to)
        return {
            "compacted": actual_count > 0,
            "summarizedCount": actual_count,
            "summarizedUpTo": eff_up_to,
            "memorySummary": eff_summary,
            "session": self._build_view(saved_session, rs),
        }

    async def precheck_message(
        self,
        sid: str,
        text: str,
        auto: bool = False,
        *,
        caller: ChatCaller,
    ) -> str:
        """在建立 SSE 流之前校验会话存在性、权限与非空消息，使非法请求直接返回 HTTP 4xx。"""
        sid = self._check_sid_format(sid)
        if not auto and not (text or "").strip():
            raise ChatError(400, "EMPTY_MESSAGE", "发送的消息内容不能为空")
        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                raise ChatError(404, "SESSION_NOT_FOUND", f"会话 {sid} 不存在")
            self._ensure_caller_allowed(str(session.get("target") or "online"), caller)
        return sid

    async def send_message(
        self,
        sid: str,
        text: str,
        auto: bool = False,
        *,
        caller: ChatCaller,
    ) -> AsyncIterator[tuple[str, Any]]:
        """处理用户发送消息或打开时自动推荐，按顺序流式产出 status / message / error / done。"""
        sid = await self.precheck_message(sid, text, auto=auto, caller=caller)
        clean_text = (text or "").strip()

        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                raise ChatError(404, "SESSION_NOT_FOUND", f"会话 {sid} 不存在")
            dirty = self._heal_interrupted_in_place(session)
            # aget/asave 已保证返回独立会话深拷贝，此处只需截取追加前的消息切片，免去二次全量深拷贝
            history_before = [m for m in (session.get("messages") or []) if isinstance(m, dict)]
            user_msg: dict[str, Any] | None = None
            if not auto:
                user_msg = {
                    "id": self._next_msg_id(session, "m"),
                    "role": "user",
                    "kind": "text",
                    "createdAt": now_iso(),
                    "text": clean_text,
                }
                session.setdefault("messages", []).append(user_msg)
                dirty = True
            if dirty:
                session = await self.store.asave(session)
            target = str(session.get("target") or "online")
            session_snapshot = session

        if user_msg is not None:
            yield ("message", dict(user_msg))

        memory_summary, summarized_up_to = self._effective_memory_state(
            session_snapshot,
            len(history_before),
        )
        rt_settings = self._runtime_settings()
        trigger_msgs = cfg_int(rt_settings, "chat_compact_trigger_messages", COMPACT_TRIGGER_MESSAGES, min_val=2)
        keep_recent = cfg_int(rt_settings, "chat_compact_keep_recent", COMPACT_KEEP_RECENT)
        if keep_recent >= trigger_msgs:
            keep_recent = max(1, trigger_msgs - 1)
        if not auto and (len(history_before) - summarized_up_to) >= trigger_msgs:
            cutoff = len(history_before) - keep_recent
            if cutoff > summarized_up_to:
                yield ("status", {"text": "正在压缩早期对话上下文…"})
                slice_to_compact = history_before[summarized_up_to:cutoff]
                anchor_msg_id = str(history_before[cutoff - 1].get("id") or "")
                try:
                    new_summary = await self.chat_agent.summarize_history(
                        memory_summary,
                        slice_to_compact,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - 自动压缩异常时无感回退滑窗，绝不中断对话
                    safe_reason = sanitize_error_text(exc, fallback=type(exc).__name__)
                    log.warning("聊天上下文自动压缩失败，回退滑动窗口继续推理 sid=%s：%s", sid, safe_reason)
                else:
                    persisted = await self._persist_compaction_if_monotonic(
                        sid,
                        cutoff=cutoff,
                        anchor_msg_id=anchor_msg_id,
                        new_summary=new_summary,
                    )
                    if persisted is not None:
                        session_snapshot = persisted
                        memory_summary, summarized_up_to = self._effective_memory_state(
                            session_snapshot,
                            len(history_before),
                        )

        yield ("status", {"text": "正在分析单据并匹配模板…" if auto else "正在思考…"})

        recent_history = history_before[summarized_up_to:] if memory_summary else history_before
        rev, rs = await self._capture_snapshot(target, allow_empty=True)
        deps = ChatDeps(
            rev=rev,
            resources=rs,
            session=session_snapshot,
            get_run_detail=self.runs.get,
        )

        try:
            action = await self.chat_agent.run(
                deps,
                recent_history,
                clean_text,
                auto=auto,
                memory_summary=memory_summary,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            log.warning("聊天路由智能体调用超时 sid=%s", sid)
            yield ("error", {"code": "CHAT_AGENT_ERROR", "message": "聊天助手响应超时，请稍后重试"})
            view = await self.get_session_view(sid, caller=caller)
            yield ("done", {"session": view})
            return
        except Exception as exc:  # noqa: BLE001
            safe_reason = sanitize_error_text(exc, fallback=type(exc).__name__)
            log.warning("聊天路由智能体调用失败 sid=%s：%s", sid, safe_reason)
            yield ("error", {"code": "CHAT_AGENT_ERROR", "message": f"聊天助手响应失败：{safe_reason}"})
            view = await self.get_session_view(sid, caller=caller)
            yield ("done", {"session": view})
            return

        extracted_inputs = {
            str(k).strip(): str(v).strip()
            for k, v in (action.inputs or {}).items()
            if str(k).strip() and v is not None and str(v).strip()
        }

        # 按动作分发（在同一会话锁临界区内合并本轮提取的补充入参与助手消息，避免双次 fsync）
        if action.action == "reply":
            async with self.store.lock_for(sid):
                cur = await self.store.aget(sid)
                if cur is not None:
                    self._apply_extracted_inputs(cur, extracted_inputs)
                    reply_msg = {
                        "id": self._next_msg_id(cur, "m"),
                        "role": "assistant",
                        "kind": "text",
                        "createdAt": now_iso(),
                        "text": action.text.strip() or "已收到。",
                    }
                    cur.setdefault("messages", []).append(reply_msg)
                    await self.store.asave(cur)
                    yield ("message", reply_msg)

        elif action.action == "recommend":
            async with self.store.lock_for(sid):
                cur = await self.store.aget(sid)
                if cur is not None:
                    self._apply_extracted_inputs(cur, extracted_inputs)
                    cur_inputs = cur.get("inputs") or {}
                    rec_store = cur.setdefault("recommended", {})
                    items: list[dict[str, Any]] = []
                    for pick in action.recommendations:
                        tpl = rs.templates.get(pick.templateId)
                        if tpl is None or tpl.offline:
                            continue
                        items.append({
                            "templateId": tpl.id,
                            "templateName": tpl.name,
                            "reason": pick.reason.strip() or f"匹配模板「{tpl.name}」",
                            "level": pick.level,
                            "missingRequired": _missing_required_keys(tpl, cur_inputs),
                            "offline": False,
                        })
                        rec_store[str(tpl.id)] = pick.level

                    if items:
                        out_msg: dict[str, Any] = {
                            "id": self._next_msg_id(cur, "m_rec"),
                            "role": "assistant",
                            "kind": "recommend",
                            "createdAt": now_iso(),
                            "text": action.text.strip() or "根据当前入参和单据为您推荐以下模板：",
                            "items": items,
                        }
                    else:
                        out_msg = {
                            "id": self._next_msg_id(cur, "m"),
                            "role": "assistant",
                            "kind": "text",
                            "createdAt": now_iso(),
                            "text": action.text.strip() or "当前未找到匹配的在线模板，您可以点击右上角「选模板」浏览全部模板。",
                        }
                    cur.setdefault("messages", []).append(out_msg)
                    await self.store.asave(cur)
                    yield ("message", out_msg)

        elif action.action == "ask_params":
            async with self.store.lock_for(sid):
                cur = await self.store.aget(sid)
                if cur is not None:
                    self._apply_extracted_inputs(cur, extracted_inputs)
                    tpl = rs.templates.get(action.templateId or 0)
                    if tpl is not None and not tpl.offline and tpl.definition.inputs:
                        _, specs = _check_params(tpl, cur.get("inputs") or {})
                        out_msg = {
                            "id": self._next_msg_id(cur, "m_ask"),
                            "role": "assistant",
                            "kind": "ask_params",
                            "createdAt": now_iso(),
                            "text": action.text.strip() or f"运行模板「{tpl.name}」前请补充或修正以下参数：",
                            "templateId": tpl.id,
                            "templateName": tpl.name,
                            "params": specs,
                        }
                    else:
                        out_msg = {
                            "id": self._next_msg_id(cur, "m"),
                            "role": "assistant",
                            "kind": "text",
                            "createdAt": now_iso(),
                            "text": action.text.strip() or "请告知需要补充的参数内容。",
                        }
                    cur.setdefault("messages", []).append(out_msg)
                    await self.store.asave(cur)
                    yield ("message", out_msg)

        elif action.action == "start_run":
            if self.manager.has_active_run(sid) is not None:
                async with self.store.lock_for(sid):
                    cur = await self.store.aget(sid)
                    if cur is not None:
                        self._apply_extracted_inputs(cur, extracted_inputs)
                        busy_msg = {
                            "id": self._next_msg_id(cur, "m"),
                            "role": "assistant",
                            "kind": "text",
                            "createdAt": now_iso(),
                            "text": "当前已有正在运行的任务，请等待其完成或先点击「停止」后再启动新模板。",
                        }
                        cur.setdefault("messages", []).append(busy_msg)
                        await self.store.asave(cur)
                        yield ("message", busy_msg)
            else:
                try:
                    msg, _ = await self.start_run(
                        sid,
                        int(action.templateId or 0),
                        extracted_inputs or None,
                        caller=caller,
                        prompt_text=action.text.strip() or None,
                    )
                    if msg.get("kind") == "run" and action.text.strip():
                        # 既有自然语言说明又成功启动了运行：在运行卡片前附带简短助手回复（按顺序追加不破坏卡片 ID）
                        async with self.store.lock_for(sid):
                            cur = await self.store.aget(sid)
                            if cur is not None:
                                note_msg = {
                                    "id": self._next_msg_id(cur, "m"),
                                    "role": "assistant",
                                    "kind": "text",
                                    "createdAt": now_iso(),
                                    "text": action.text.strip(),
                                }
                                msgs = cur.setdefault("messages", [])
                                run_idx = next(
                                    (i for i, m in enumerate(msgs) if m.get("id") == msg.get("id")),
                                    len(msgs),
                                )
                                msgs.insert(run_idx, note_msg)
                                await self.store.asave(cur)
                                yield ("message", note_msg)
                    yield ("message", msg)
                except ChatError as exc:
                    async with self.store.lock_for(sid):
                        cur = await self.store.aget(sid)
                        if cur is not None:
                            self._apply_extracted_inputs(cur, extracted_inputs)
                            err_msg = {
                                "id": self._next_msg_id(cur, "m"),
                                "role": "assistant",
                                "kind": "text",
                                "createdAt": now_iso(),
                                "text": f"暂时无法启动该模板：{exc.message}",
                            }
                            cur.setdefault("messages", []).append(err_msg)
                            await self.store.asave(cur)
                            yield ("message", err_msg)

        elif action.action == "rewrite":
            updated_card_view: dict[str, Any] | None = None
            reply_msg_out: dict[str, Any] | None = None
            async with self.store.lock_for(sid):
                cur = await self.store.aget(sid)
                if cur is not None:
                    self._apply_extracted_inputs(cur, extracted_inputs)
                    card = next(
                        (
                            m for m in (cur.get("messages") or [])
                            if isinstance(m, dict)
                            and m.get("kind") == "run"
                            and m.get("runId") == action.runId
                        ),
                        None,
                    )
                    if card is None or card.get("status") not in ("SUCCESS", "PARTIAL"):
                        reply_msg_out = {
                            "id": self._next_msg_id(cur, "m"),
                            "role": "assistant",
                            "kind": "text",
                            "createdAt": now_iso(),
                            "text": "目标运行记录当前状态不可改写，请先完成一次模板运行。",
                        }
                        cur.setdefault("messages", []).append(reply_msg_out)
                        await self.store.asave(cur)
                    else:
                        versions = [dict(v) for v in (card.get("versions") or []) if isinstance(v, dict)]
                        new_ver_no = len(versions) + 1
                        ver_created_at = now_iso()
                        versions.append({
                            "no": new_ver_no,
                            "kind": "rewrite",
                            "markdown": str(action.markdown or ""),
                            "createdAt": ver_created_at,
                            "note": "AI 按对话要求改写（未经证据校验）",
                        })
                        card["versions"] = versions
                        card["confirmed"] = False
                        reply_msg_out = {
                            "id": self._next_msg_id(cur, "m"),
                            "role": "assistant",
                            "kind": "text",
                            "createdAt": ver_created_at,
                            "text": (
                                action.text.strip()
                                or "已为您生成改写版本，该版本未经平台证据校验，请预览核对后确认。"
                            ),
                            "rewriteRunId": str(card.get("runId") or ""),
                            "rewriteVersionNo": new_ver_no,
                        }
                        cur.setdefault("messages", []).append(reply_msg_out)
                        saved_cur = await self.store.asave(cur)
                        updated_card_view = self._format_message_view(
                            card,
                            rs,
                            dict(saved_cur.get("inputs") or {}),
                        )
            if updated_card_view is not None:
                yield ("message", updated_card_view)
            if reply_msg_out is not None:
                yield ("message", dict(reply_msg_out))

        final_view = await self.get_session_view(sid, caller=caller)
        yield ("done", {"session": final_view})

    # ------------------------------------------------------------------ 按 runId 反查、事件订阅、取消与确认
    def _scan_sessions_for_run(self, run_id: str) -> str | None:
        """兜底遍历 chats 分片目录查找包含指定 runId 的会话编号（只读快速预筛，不污染 LRU 缓存）。"""
        root: Path = self.store.root
        if not root.is_dir():
            return None
        try:
            with os.scandir(root) as shard_it:
                shards = [e.path for e in shard_it if not e.name.startswith(".") and e.is_dir()]
        except OSError:
            return None
        for shard_path in shards:
            try:
                with os.scandir(shard_path) as file_it:
                    sids = [
                        e.name[:-5]
                        for e in file_it
                        if not e.name.startswith(".") and e.name.endswith(".json") and e.is_file()
                    ]
            except OSError:
                continue
            for sid in sids:
                if SESSION_ID_RE.match(sid) and self.store.has_run_id(sid, run_id):
                    return sid
        return None

    async def resolve_session_for_run(
        self,
        run_id: str,
        *,
        caller: ChatCaller | None = None,
        expected_sid: str | None = None,
    ) -> str:
        """根据 runId 定位所属会话编号（支持可选 expected_sid 强绑定防跨会话越权）。#Created By AiCoding(codex)"""
        rid = (run_id or "").strip()
        if not rid or "\x00" in rid or len(rid) > 80:
            raise ChatError(404, "RUN_NOT_FOUND", f"运行记录 {run_id} 不存在")

        clean_expected = (expected_sid or "").strip()
        if clean_expected and not SESSION_ID_RE.match(clean_expected):
            raise ChatError(404, "RUN_NOT_FOUND", f"运行记录 {rid} 不存在")

        sid = self._run_to_session.get(rid) or self.manager.session_for_run(rid)
        if not sid:
            detail = await asyncio.to_thread(self.runs.get, rid)
            if isinstance(detail, dict):
                extra = detail.get("extra")
                if isinstance(extra, dict) and isinstance(extra.get("sessionId"), str):
                    cand = extra["sessionId"].strip()
                    if SESSION_ID_RE.match(cand):
                        sid = cand
        if not sid:
            sid = await asyncio.to_thread(self._scan_sessions_for_run, rid)
        if not sid or (clean_expected and sid != clean_expected):
            raise ChatError(404, "RUN_NOT_FOUND", f"运行记录 {rid} 不存在")

        sess = await self.store.aget(sid)
        if sess is None:
            raise ChatError(404, "RUN_NOT_FOUND", f"运行记录 {rid} 所属会话不存在")
        self._ensure_caller_allowed(str(sess.get("target") or "online"), caller)
        has_card = any(
            isinstance(m, dict) and m.get("kind") == "run" and m.get("runId") == rid
            for m in (sess.get("messages") or [])
        )
        if not has_card:
            raise ChatError(404, "RUN_NOT_FOUND", f"运行记录 {rid} 在会话中不存在")
        self._remember_run(rid, sid)
        return sid

    async def get_run_raw_events(
        self,
        run_id: str,
        *,
        caller: ChatCaller | None = None,
        expected_sid: str | None = None,
    ) -> dict[str, Any]:
        """读取指定运行的原始过程事件（优先内存通道，淘汰后回退读取 RunStore）。#Created By AiCoding(codex)"""
        sid = await self.resolve_session_for_run(run_id, caller=caller, expected_sid=expected_sid)
        rid = run_id.strip()

        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                raise ChatError(404, "RUN_NOT_FOUND", f"运行记录 {rid} 所属会话不存在")
            if self._heal_interrupted_in_place(session):
                session = await self.store.asave(session)
            card = next(
                (
                    m for m in (session.get("messages") or [])
                    if isinstance(m, dict) and m.get("kind") == "run" and m.get("runId") == rid
                ),
                None,
            )
            if card is None:
                raise ChatError(404, "RUN_NOT_FOUND", f"运行记录 {rid} 不存在")
            card_status = str(card.get("status") or "FAILED")

        events = self.manager.get_raw_events(rid)
        if events is None:
            detail = await asyncio.to_thread(self.runs.get, rid)
            raw_list = detail.get("events") if isinstance(detail, dict) else None
            events = [dict(e) for e in raw_list if isinstance(e, dict)] if isinstance(raw_list, list) else []

        return {
            "runId": rid,
            "status": card_status,
            "events": events,
        }

    async def stream_events(
        self,
        run_id: str,
        after: int = 0,
        *,
        include_raw: bool = False,
        raw_after: int = 0,
        caller: ChatCaller | None = None,
        expected_sid: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """订阅运行步骤（可选含原始过程事件）流；内存通道已淘汰或服务重启后自动从持久化记录重放并推送 final。"""
        sid = await self.resolve_session_for_run(run_id, caller=caller, expected_sid=expected_sid)
        rid = run_id.strip()
        safe_after = max(0, int(after))
        safe_raw_after = max(0, int(raw_after))

        try:
            sub = self.manager.subscribe(
                rid,
                safe_after,
                include_raw=include_raw,
                raw_after=safe_raw_after,
            )
            async for kind, payload in sub:
                yield (kind, payload)
            return
        except KeyError:
            pass

        # 不在 manager 内存通道中：从会话卡片恢复（若遗留 RUNNING 则转为 INTERRUPTED）并重放 raw/steps 与 final
        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                raise ChatError(404, "RUN_NOT_FOUND", f"运行记录 {rid} 所属会话不存在")
            if self._heal_interrupted_in_place(session):
                session = await self.store.asave(session)
            card = next(
                (
                    m for m in (session.get("messages") or [])
                    if isinstance(m, dict) and m.get("kind") == "run" and m.get("runId") == rid
                ),
                None,
            )
            if card is None:
                raise ChatError(404, "RUN_NOT_FOUND", f"运行记录 {rid} 不存在")
            target = str(session.get("target") or "online")
            cur_inputs = dict(session.get("inputs") or {})
            card_copy = dict(card)

        if include_raw:
            detail = await asyncio.to_thread(self.runs.get, rid)
            raw_list = detail.get("events") if isinstance(detail, dict) else None
            if isinstance(raw_list, list):
                for ev in raw_list:
                    if isinstance(ev, dict) and int(ev.get("seq", 0)) > safe_raw_after:
                        yield ("raw", ev)

        _, rs = await self._capture_snapshot(target, allow_empty=True)
        card_view = self._format_message_view(card_copy, rs, cur_inputs)
        for step in card_view.get("steps") or []:
            if isinstance(step, dict) and int(step.get("seq", 0)) > safe_after:
                yield ("step", step)
        yield ("final", card_view)

    async def cancel_run(
        self,
        run_id: str,
        *,
        caller: ChatCaller | None = None,
        expected_sid: str | None = None,
    ) -> dict[str, Any]:
        """手动请求停止指定运行。"""
        await self.resolve_session_for_run(run_id, caller=caller, expected_sid=expected_sid)
        self.manager.cancel(run_id.strip())
        return {"ok": True}

    async def confirm_run(
        self,
        run_id: str,
        markdown: str,
        acknowledge_partial: bool = False,
        *,
        caller: ChatCaller,
        expected_sid: str | None = None,
    ) -> dict[str, Any]:
        """确认采用某次运行的报告（支持 PARTIAL 二次确认拦截、重复确认幂等与 chat-confirm 审计落盘）。"""
        sid = await self.resolve_session_for_run(run_id, caller=caller, expected_sid=expected_sid)
        rid = run_id.strip()
        md_text = "" if markdown is None else str(markdown)

        async with self.store.lock_for(sid):
            session = await self.store.aget(sid)
            if session is None:
                raise ChatError(404, "SESSION_NOT_FOUND", f"会话 {sid} 不存在")
            target = str(session.get("target") or "online")
            self._ensure_caller_allowed(target, caller)
            dirty = self._heal_interrupted_in_place(session)

            card = next(
                (
                    m for m in (session.get("messages") or [])
                    if isinstance(m, dict) and m.get("kind") == "run" and m.get("runId") == rid
                ),
                None,
            )
            if card is None:
                raise ChatError(404, "RUN_NOT_FOUND", f"运行记录 {rid} 不存在")

            status = str(card.get("status") or "")
            if status not in ("SUCCESS", "PARTIAL"):
                raise ChatError(
                    400,
                    "NOT_CONFIRMABLE",
                    f"当前运行状态为 {status}，只有 SUCCESS 或 PARTIAL 状态允许确认",
                )

            if status == "PARTIAL" and not acknowledge_partial:
                raise ChatError(
                    409,
                    "PARTIAL_NEEDS_ACK",
                    "报告存在未查到的展示字段，请确认知悉后再提交",
                    missingShown=list(card.get("missingShown") or []),
                )

            versions = [v for v in (card.get("versions") or []) if isinstance(v, dict)]
            if versions:
                latest = versions[-1]
                latest_md = str(latest.get("markdown") or "")
                rewritten = latest.get("kind") == "rewrite"
            else:
                latest_md = ""
                rewritten = False

            edited = md_text != latest_md
            payload: dict[str, Any] = {
                "type": "report-confirmed",
                "userId": str(session["userId"]),
                "orderId": str(session["orderId"]),
                "templateId": int(card["templateId"]),
                "templateName": str(card["templateName"]),
                "runId": rid,
                "status": status,
                "markdown": md_text,
                "edited": edited,
                "rewritten": rewritten,
            }

            records: list[dict[str, Any]] = session.setdefault("confirmRecords", [])
            last_rec = records[-1] if records else None
            cur_confirmed = session.get("confirmed")
            # 只有当前卡片本身已处于 confirmed（即未被后续 AI 改写复位）且 edited/rewritten/markdown 完全一致时才视为幂等重放
            same_as_last = bool(
                card.get("confirmed")
                and isinstance(last_rec, dict)
                and isinstance(cur_confirmed, dict)
                and cur_confirmed.get("runId") == rid
                and cur_confirmed.get("edited") == edited
                and cur_confirmed.get("rewritten") == rewritten
                and last_rec.get("runId") == rid
                and last_rec.get("markdown") == md_text
                and last_rec.get("edited") == edited
                and last_rec.get("rewritten") == rewritten
            )

            for m in session.get("messages") or []:
                if isinstance(m, dict) and m.get("kind") == "run":
                    want = m.get("runId") == rid
                    if m.get("confirmed") is not want:
                        m["confirmed"] = want
                        dirty = True

            if not same_as_last:
                dirty = True
                confirmed_at = now_iso()
                session["confirmed"] = {
                    "runId": rid,
                    "templateId": int(card["templateId"]),
                    "templateName": str(card["templateName"]),
                    "confirmedAt": confirmed_at,
                    "edited": edited,
                    "rewritten": rewritten,
                }
                tags: list[str] = []
                if rewritten:
                    tags.append("AI 改写")
                if edited:
                    tags.append("已编辑")
                tag_suffix = f"（{'、'.join(tags)}）" if tags else ""
                session.setdefault("messages", []).append({
                    "id": self._next_msg_id(session, "m_conf"),
                    "role": "system",
                    "kind": "confirmed",
                    "createdAt": confirmed_at,
                    "text": f"已确认采用模板「{card['templateName']}」的报告{tag_suffix}",
                    "runId": rid,
                })
                records.append({
                    "runId": rid,
                    "templateId": int(card["templateId"]),
                    "templateName": str(card["templateName"]),
                    "status": status,
                    "confirmedAt": confirmed_at,
                    "operator": caller.name,
                    "edited": edited,
                    "rewritten": rewritten,
                    "originalMarkdown": str(versions[0].get("markdown") or "") if versions else "",
                    "latestVersionMarkdown": latest_md,
                    "markdown": md_text,
                })
                audit_payload = {
                    "sessionId": sid,
                    "userId": str(session["userId"]),
                    "orderId": str(session["orderId"]),
                    "runId": rid,
                    "templateId": int(card["templateId"]),
                    "templateName": str(card["templateName"]),
                    "status": status,
                    "edited": edited,
                    "rewritten": rewritten,
                }
                await asyncio.to_thread(self.publisher.audit, "chat-confirm", caller.name, audit_payload)

            saved = await self.store.asave(session) if dirty else session

        _, rs = await self._capture_snapshot(target, allow_empty=True)
        return {
            "payload": payload,
            "session": self._build_view(saved, rs),
        }
