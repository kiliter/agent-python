"""嵌入式聊天窗口增量上下文压缩（Rolling Summary）与手动归档全链路测试。

#Created By AiCoding(codex)
覆盖短对话零压缩、达阈值自动增量压缩与改写偏好继承、二次滚动增量合并、
压缩失败优雅降级、手动压缩 /compact 边界与鉴权隔离、异常状态自愈及摘要长度护栏。
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import httpx
import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from report_agent.api.auth import COOKIE_NAME, UserStore
from report_agent.chat.agent import (
    COMPACT_KEEP_RECENT,
    COMPACT_TRIGGER_MESSAGES,
    MANUAL_COMPACT_KEEP_RECENT,
    MANUAL_COMPACT_MIN_SLICE,
    MAX_HISTORY_MESSAGES,
    MAX_MEMORY_SUMMARY_CHARS,
    build_chat_user_prompt,
    format_history_for_prompt,
)
from report_agent.chat.service import ChatService
from report_agent.main import create_app
from report_agent.store.fsutil import read_json, write_json
from scripted_model import scripted


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    """解析 SSE 响应帧，忽略注释心跳行，返回 [{id, event, data}, ...]。"""
    events: list[dict[str, Any]] = []
    for block in raw.split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln.strip() and not ln.startswith(":")]
        if not lines:
            continue
        evt_id: str | None = None
        evt_name = "message"
        data_lines: list[str] = []
        for ln in lines:
            if ln.startswith("id:"):
                evt_id = ln[3:].strip()
            elif ln.startswith("event:"):
                evt_name = ln[6:].strip()
            elif ln.startswith("data:"):
                data_lines.append(ln[5:].lstrip())
        if not data_lines:
            continue
        events.append({
            "id": evt_id,
            "event": evt_name,
            "data": json.loads("\n".join(data_lines)),
        })
    return events


def _user_prompt_text(messages: list[ModelMessage]) -> str:
    """提取模型请求中的 UserPromptPart 文本内容。"""
    chunks: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    chunks.append(part.content)
    return "\n".join(chunks)


def _instructions_text(messages: list[ModelMessage]) -> str:
    """提取模型请求中的 instructions 文本内容。"""
    chunks: list[str] = []
    for msg in messages:
        if isinstance(msg, ModelRequest):
            inst = getattr(msg, "instructions", None)
            if isinstance(inst, str) and inst:
                chunks.append(inst)
    return "\n".join(chunks)


def _tri_model(
    *,
    summary_fn: Any = None,
    chat_fn: Any = None,
    report_fn: Any = scripted,
) -> FunctionModel:
    """按 output_tools 路由到摘要压缩 Agent、ChatAgent 或填报 AgentRunner 的三路桩模型。"""

    async def _dispatch(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if any(t.name == "submit_chat_summary" for t in info.output_tools):
            if summary_fn is None:
                return ModelResponse(parts=[ToolCallPart("submit_chat_summary", {"summary": "默认测试摘要"})])
            res = summary_fn(messages, info)
            return await res if inspect.isawaitable(res) else res
        if any(t.name == "submit_chat_action" for t in info.output_tools):
            if chat_fn is None:
                return ModelResponse(parts=[ToolCallPart("submit_chat_action", {
                    "action": "reply",
                    "text": "收到。",
                })])
            res = chat_fn(messages, info)
            return await res if inspect.isawaitable(res) else res
        res = report_fn(messages, info)
        return await res if inspect.isawaitable(res) else res

    return FunctionModel(_dispatch, model_name="scripted-chat-compaction-tri")


@pytest.fixture
async def async_client(container):
    """带完整 FastAPI lifespan 的异步测试客户端。"""
    UserStore(container.layout.config / "users.yaml").upsert(
        "chenxiaoyun", "pass-1234", "陈晓芸", "业务维护"
    )
    app = create_app(container=container)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as cl:
            yield cl


async def _admin_login(cl: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    """执行管理端登录，返回 (Bearer 请求头, Cookie 令牌值)。"""
    r = await cl.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "pass-1234"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    cookie_val = r.cookies.get(COOKIE_NAME) or token
    cl.cookies.clear()
    return {"Authorization": f"Bearer {token}"}, cookie_val


async def _open_session(
    cl: httpx.AsyncClient,
    *,
    user_id: str,
    order_id: str,
    case_c01: dict[str, Any],
    headers: dict[str, str],
    target: str = "online",
) -> dict[str, Any]:
    resp = await cl.post(
        "/api/v1/chat/sessions",
        json={
            "userId": user_id,
            "orderId": order_id,
            "inputs": case_c01["inputs"],
            "document": case_c01["documentText"],
            "target": target,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _send_text_turn(
    cl: httpx.AsyncClient,
    sid: str,
    text: str,
    *,
    headers: dict[str, str],
    auto: bool = False,
) -> list[dict[str, Any]]:
    resp = await cl.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        json={"text": text, "auto": auto},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return _parse_sse(resp.text)


def _append_standard_messages(container, sid: str, count: int, *, prefix: str = "HIST") -> None:
    """通过 ChatStore 加载并追加标准聊天消息，保持磁盘与 LRU 缓存一致。"""
    sess = container.chat.store.get(sid)
    assert sess is not None
    seq = int(sess.get("seq", 0))
    msgs = sess.setdefault("messages", [])
    for idx in range(count):
        seq += 1
        role = "user" if idx % 2 == 0 else "assistant"
        msgs.append({
            "id": f"m_{seq}",
            "role": role,
            "kind": "text",
            "createdAt": "2026-11-13T10:00:00+08:00",
            "text": f"{prefix}_{idx:02d} 第{idx + 1}条测试消息",
        })
    sess["seq"] = seq
    container.chat.store.save(sess)


async def test_1_short_conversation_zero_compaction(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 1：短对话零压缩（不调用 submit_chat_summary，summarizedUpTo=0，提示词无摘要段且向后兼容）。"""
    assert COMPACT_TRIGGER_MESSAGES == 24
    assert COMPACT_KEEP_RECENT == 12
    assert MANUAL_COMPACT_KEEP_RECENT == 6
    assert MANUAL_COMPACT_MIN_SLICE == 2
    assert MAX_MEMORY_SUMMARY_CHARS == 1_200

    # 1) 验证 build_chat_user_prompt 无摘要与空白摘要逐字一致，且不含摘要段落
    sample_history = [
        {"role": "user", "kind": "text", "text": "客户咨询套餐资费"},
        {"role": "assistant", "kind": "text", "text": "您好，可以为您推荐业务办理争议类模板。"},
    ]
    expected_legacy = (
        f"## 最近对话历史\n"
        f"{format_history_for_prompt(sample_history, limit=MAX_HISTORY_MESSAGES)}\n\n"
        f"## 用户本轮消息\n请帮我解释一下"
    )
    prompt_default = build_chat_user_prompt(sample_history, "请帮我解释一下", auto=False)
    prompt_blank = build_chat_user_prompt(sample_history, "请帮我解释一下", auto=False, memory_summary="   \n\t ")
    assert prompt_default == expected_legacy
    assert prompt_blank == expected_legacy
    assert "## 早期对话记忆摘要" not in prompt_default

    prompt_auto = build_chat_user_prompt(sample_history, "", auto=True, memory_summary="")
    assert "## 早期对话记忆摘要" not in prompt_auto
    assert prompt_auto.startswith("## 最近对话历史\n")

    # 2) 多轮短对话（< 24 条消息）：不触发摘要模型，记忆状态始终为 ("", 0)
    key_headers = {"X-API-Key": "upstream-key"}
    summary_calls = 0
    chat_prompts: list[str] = []

    def summary_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal summary_calls
        summary_calls += 1
        return ModelResponse(parts=[ToolCallPart("submit_chat_summary", {"summary": "不应触发"})])

    def chat_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        chat_prompts.append(_user_prompt_text(messages))
        return ModelResponse(parts=[ToolCallPart("submit_chat_action", {
            "action": "reply",
            "text": f"短对话第 {len(chat_prompts)} 次回复。",
        })])

    container.runner.model = _tri_model(summary_fn=summary_stub, chat_fn=chat_stub)

    sess = await _open_session(
        async_client,
        user_id="u_short",
        order_id="ORD_SHORT_01",
        case_c01=case_c01,
        headers=key_headers,
    )
    assert sess["memorySummary"] == ""
    assert sess["summarizedUpTo"] == 0
    sid = sess["sessionId"]

    for idx in range(5):
        frames = await _send_text_turn(
            async_client,
            sid,
            f"短对话提问 {idx + 1}",
            headers=key_headers,
        )
        status_texts = [f["data"]["text"] for f in frames if f["event"] == "status"]
        assert "正在压缩早期对话上下文…" not in status_texts
        assert status_texts == ["正在思考…"]
        done_sess = frames[-1]["data"]["session"]
        assert done_sess["memorySummary"] == ""
        assert done_sess["summarizedUpTo"] == 0

    assert summary_calls == 0
    assert all("## 早期对话记忆摘要" not in p for p in chat_prompts)

    # 3) 即使消息数 >= 24，auto=True 自动推荐也不触发自动压缩
    _append_standard_messages(container, sid, 16, prefix="EXTRA_BEFORE_AUTO")
    auto_frames = await _send_text_turn(async_client, sid, "", headers=key_headers, auto=True)
    auto_statuses = [f["data"]["text"] for f in auto_frames if f["event"] == "status"]
    assert "正在压缩早期对话上下文…" not in auto_statuses
    assert summary_calls == 0

    persisted = (await async_client.get(f"/api/v1/chat/sessions/{sid}", headers=key_headers)).json()
    assert persisted["memorySummary"] == ""
    assert persisted["summarizedUpTo"] == 0


async def test_2_auto_compaction_threshold_rewrite_preference_and_isolation(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 2：端到端 POST /messages + POST /runs + 达阈值自动压缩 + rewrite 偏好继承与 AgentRunner 隔离。"""
    key_headers = {"X-API-Key": "upstream-key"}
    summary_prompts: list[str] = []
    chat_prompts: list[str] = []
    report_prompts: list[tuple[str, str]] = []
    target_run_id = ""
    rewritten_md = (
        "服务争议点1:业务办理争议类\n\n"
        "- 办理渠道：热线渠道。\n"
        "- 套餐资费：5G智享套餐（个人版）129元/月。\n"
        "- 确认方式：已发确认及办理成功短信。"
    )

    def summary_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        summary_prompts.append(_user_prompt_text(messages))
        return ModelResponse(parts=[ToolCallPart("submit_chat_summary", {
            "summary": "1. 用户口径偏好（口述）：后续改写报告必须使用简短分点式客服口径，每条不超过20字，禁止长段落。\n"
                       "2. 本会话已通过模板 #1001 生成过一次核查报告。",
        })])

    def chat_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt_text = _user_prompt_text(messages)
        chat_prompts.append(prompt_text)
        # 仅在进入改写轮次时触发 rewrite
        if "按我最开始要求的风格改写" in prompt_text:
            step = sum(1 for m in messages if isinstance(m, ModelResponse))
            if step == 0:
                return ModelResponse(parts=[ToolCallPart("get_run_result", {"runId": target_run_id})])
            return ModelResponse(parts=[ToolCallPart("submit_chat_action", {
                "action": "rewrite",
                "runId": target_run_id,
                "text": "已按您最初约定的简短分点式客服口径改写报告：",
                "markdown": rewritten_md,
            })])
        return ModelResponse(parts=[ToolCallPart("submit_chat_action", {
            "action": "reply",
            "text": "好的，已记录您的需求。",
        })])

    def report_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        report_prompts.append((_instructions_text(messages), _user_prompt_text(messages)))
        return scripted(messages, info)

    container.runner.model = _tri_model(
        summary_fn=summary_stub,
        chat_fn=chat_stub,
        report_fn=report_stub,
    )

    sess = await _open_session(
        async_client,
        user_id="u_auto_compact",
        order_id="ORD_AUTO_01",
        case_c01=case_c01,
        headers=key_headers,
    )
    sid = sess["sessionId"]

    # Turn 1（messages[0..1]）：用户早先提出改写偏好约束
    await _send_text_turn(
        async_client,
        sid,
        "EARLY_PREF_01：后续如果改写报告，请务必使用简短分点式客服口径，每条不超过20字，不要长段落。",
        headers=key_headers,
    )

    # 真实运行一次模板 1001（messages[2] 为 run 卡片）
    r_run = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )
    assert r_run.status_code == 200, r_run.text
    target_run_id = r_run.json()["message"]["runId"]
    ev_frames = _parse_sse(
        (await async_client.get(f"/api/v1/chat/runs/{target_run_id}/events?after=0", headers=key_headers)).text
    )
    assert ev_frames[-1]["event"] == "final" and ev_frames[-1]["data"]["status"] == "SUCCESS"

    # 继续通过真实 POST /messages 累积 11 轮对话（22 条消息，messages 总计 25 条 >= 24）
    # messages[0..12] 为待归档切片（截止到 TURN_06 助手回复），messages[13..24] 为保留的最近 12 条（TURN_07..TURN_12）
    for turn_no in range(2, 13):
        await _send_text_turn(
            async_client,
            sid,
            f"CHAT_TURN_{turn_no:02d} 普通核查沟通消息",
            headers=key_headers,
        )

    assert len(summary_prompts) == 0

    # Turn 13：触发自动阈值压缩（history_before=25, cutoff=25-12=13）并请求 AI rewrite
    rw_frames = await _send_text_turn(
        async_client,
        sid,
        "请按我最开始要求的风格改写刚刚生成的报告",
        headers=key_headers,
    )

    # 1) 验证 SSE 状态顺序：先压缩，再思考
    status_texts = [f["data"]["text"] for f in rw_frames if f["event"] == "status"]
    assert status_texts == ["正在压缩早期对话上下文…", "正在思考…"]

    # 2) 验证摘要 Agent 仅收到 [0 : len - 12] 切片（含 EARLY_PREF_01 与 TURN_06，不含 TURN_07..TURN_12）
    assert len(summary_prompts) == 1
    sum_prompt = summary_prompts[0]
    assert "EARLY_PREF_01" in sum_prompt
    assert "CHAT_TURN_06" in sum_prompt
    assert "CHAT_TURN_07" not in sum_prompt
    assert "CHAT_TURN_12" not in sum_prompt

    # 3) 验证 ChatAgent 收到记忆摘要段落，且最近对话历史仅含后 12 条（不再包含第 1 条原文）
    last_chat_prompt = chat_prompts[-1]
    assert "## 早期对话记忆摘要" in last_chat_prompt
    assert "简短分点式客服口径" in last_chat_prompt
    recent_section = last_chat_prompt.split("## 最近对话历史", 1)[1].split("## 用户本轮消息", 1)[0]
    assert "EARLY_PREF_01" not in recent_section
    assert "CHAT_TURN_06" not in recent_section
    assert "CHAT_TURN_07" in recent_section
    assert "CHAT_TURN_12" in recent_section

    # 4) 验证 rewrite 产出的新版本与绑定回复
    rw_cards = [
        f["data"] for f in rw_frames
        if f["event"] == "message" and f["data"].get("kind") == "run" and f["data"].get("runId") == target_run_id
    ]
    assert len(rw_cards) == 1
    assert len(rw_cards[0]["versions"]) == 2
    assert rw_cards[0]["versions"][1]["kind"] == "rewrite"
    assert rw_cards[0]["versions"][1]["markdown"] == rewritten_md
    rw_text_msgs = [
        f["data"] for f in rw_frames
        if f["event"] == "message" and f["data"].get("kind") == "text" and f["data"].get("role") == "assistant"
    ]
    assert len(rw_text_msgs) == 1
    assert rw_text_msgs[0]["rewriteRunId"] == target_run_id
    assert rw_text_msgs[0]["rewriteVersionNo"] == 2

    # 5) 验证 done 事件与清缓存重新 GET /sessions/{sid} 均持久保存 memorySummary 与 summarizedUpTo
    done_sess = rw_frames[-1]["data"]["session"]
    assert done_sess["summarizedUpTo"] == 13
    assert "简短分点式客服口径" in done_sess["memorySummary"]

    container.chat.store._cache.clear()
    reloaded_sess = (await async_client.get(f"/api/v1/chat/sessions/{sid}", headers=key_headers)).json()
    assert reloaded_sess["summarizedUpTo"] == 13
    assert reloaded_sess["memorySummary"] == done_sess["memorySummary"]

    # 6) 再次发起模板填报运行：验证 memorySummary / 聊天偏好绝不混入 AgentRunner 的提示词与 <document>
    report_prompts.clear()
    r_run_2 = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )
    assert r_run_2.status_code == 200, r_run_2.text
    rid_2 = r_run_2.json()["message"]["runId"]
    ev_2 = _parse_sse(
        (await async_client.get(f"/api/v1/chat/runs/{rid_2}/events?after=0", headers=key_headers)).text
    )
    assert ev_2[-1]["data"]["status"] == "SUCCESS"
    combined_report_input = "\n".join(inst + "\n" + usr for inst, usr in report_prompts)
    assert "简短分点式客服口径" not in combined_report_input
    assert "EARLY_PREF_01" not in combined_report_input
    assert "CHAT_TURN_07" not in combined_report_input


async def test_3_second_rolling_incremental_compaction(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 3：二次滚动增量合并压缩（复用上轮摘要 + 仅扫描 [old_cutoff : new_cutoff]，锚点单调递增）。"""
    key_headers = {"X-API-Key": "upstream-key"}
    summary_calls: list[str] = []
    chat_prompts: list[str] = []

    def summary_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = _user_prompt_text(messages)
        summary_calls.append(prompt)
        idx = len(summary_calls)
        if idx == 1:
            return ModelResponse(parts=[ToolCallPart("submit_chat_summary", {
                "summary": "SUMMARY_ROUND_1：客户早期说明了办理经过。",
            })])
        return ModelResponse(parts=[ToolCallPart("submit_chat_summary", {
            "summary": "SUMMARY_ROUND_2：合并早期经过与中段核查要点。",
        })])

    def chat_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        chat_prompts.append(_user_prompt_text(messages))
        return ModelResponse(parts=[ToolCallPart("submit_chat_action", {
            "action": "reply",
            "text": "收到，继续为您核查。",
        })])

    container.runner.model = _tri_model(summary_fn=summary_stub, chat_fn=chat_stub)

    sess = await _open_session(
        async_client,
        user_id="u_rolling",
        order_id="ORD_ROLL_01",
        case_c01=case_c01,
        headers=key_headers,
    )
    sid = sess["sessionId"]

    # 第 1 批写入 24 条消息：R1_00..R1_23 -> 触发第 1 次压缩切片 [0:12]
    _append_standard_messages(container, sid, 24, prefix="R1")
    f1 = await _send_text_turn(async_client, sid, "TRIGGER_ROUND_1", headers=key_headers)
    s1 = f1[-1]["data"]["session"]
    assert s1["summarizedUpTo"] == 12
    assert s1["memorySummary"] == "SUMMARY_ROUND_1：客户早期说明了办理经过。"
    assert len(summary_calls) == 1
    assert "R1_00" in summary_calls[0] and "R1_11" in summary_calls[0]
    assert "R1_12" not in summary_calls[0]

    # 当前消息总数 = 24 + 2 (user + assistant) = 26，unarchived = 26 - 12 = 14
    # 再追加 10 条消息（R2_00..R2_09），总计 36 条，unarchived = 36 - 12 = 24 >= 24
    _append_standard_messages(container, sid, 10, prefix="R2")
    f2 = await _send_text_turn(async_client, sid, "TRIGGER_ROUND_2", headers=key_headers)
    s2 = f2[-1]["data"]["session"]

    assert len(summary_calls) == 2
    second_sum_prompt = summary_calls[1]
    # 必须携带第 1 轮记忆摘要
    assert "SUMMARY_ROUND_1：客户早期说明了办理经过。" in second_sum_prompt
    # 仅包含增量切片 [12:24]（即 R1_12..R1_23），绝不重复扫描 [0:12]（R1_00..R1_11），也不包含保留的后 12 条（TRIGGER_ROUND_1 / R2_*）
    assert "R1_12" in second_sum_prompt and "R1_23" in second_sum_prompt
    assert "R1_00" not in second_sum_prompt and "R1_11" not in second_sum_prompt
    assert "TRIGGER_ROUND_1" not in second_sum_prompt and "R2_00" not in second_sum_prompt

    # summarizedUpTo 单调递增至 24
    assert s2["summarizedUpTo"] == 24
    assert s2["memorySummary"] == "SUMMARY_ROUND_2：合并早期经过与中段核查要点。"
    assert "SUMMARY_ROUND_2：合并早期经过与中段核查要点。" in chat_prompts[-1]
    recent_2 = chat_prompts[-1].split("## 最近对话历史", 1)[1].split("## 用户本轮消息", 1)[0]
    assert "R1_23" not in recent_2
    assert "TRIGGER_ROUND_1" in recent_2 and "R2_09" in recent_2


async def test_4_auto_compaction_failure_graceful_degradation(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 4：自动压缩超时或失败时无感回退滑窗，不阻断对话且不损坏既有记忆锚点。"""
    key_headers = {"X-API-Key": "upstream-key"}
    fail_mode: dict[str, str] = {"kind": "timeout"}
    chat_prompts: list[str] = []

    def failing_summary_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if fail_mode["kind"] == "timeout":
            raise TimeoutError("simulated compaction timeout")
        raise RuntimeError("simulated compaction error sk-secret12345")

    def chat_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        chat_prompts.append(_user_prompt_text(messages))
        return ModelResponse(parts=[ToolCallPart("submit_chat_action", {
            "action": "reply",
            "text": "压缩失败降级后仍正常回复。",
        })])

    container.runner.model = _tri_model(summary_fn=failing_summary_stub, chat_fn=chat_stub)

    # 4.1 首次无摘要时压缩超时 -> 回退普通滑窗，summarizedUpTo 保持 0
    sess = await _open_session(
        async_client,
        user_id="u_degrade",
        order_id="ORD_DEG_01",
        case_c01=case_c01,
        headers=key_headers,
    )
    sid = sess["sessionId"]
    _append_standard_messages(container, sid, 24, prefix="DEG1")

    frames_timeout = await _send_text_turn(async_client, sid, "超时降级测试消息", headers=key_headers)
    events_timeout = [f["event"] for f in frames_timeout]
    assert "error" not in events_timeout
    assert events_timeout[-1] == "done"
    assert [f["data"]["text"] for f in frames_timeout if f["event"] == "status"] == [
        "正在压缩早期对话上下文…",
        "正在思考…",
    ]
    msg_timeout = next(
        f["data"] for f in frames_timeout
        if f["event"] == "message" and f["data"].get("role") == "assistant"
    )
    assert msg_timeout["text"] == "压缩失败降级后仍正常回复。"
    sess_after_timeout = frames_timeout[-1]["data"]["session"]
    assert sess_after_timeout["summarizedUpTo"] == 0
    assert sess_after_timeout["memorySummary"] == ""
    assert "## 早期对话记忆摘要" not in chat_prompts[-1]

    # 4.2 已有旧摘要与锚点时二次压缩抛 RuntimeError -> 保留原摘要与原锚点不被破坏
    raw = container.chat.store.get(sid)
    assert raw is not None
    raw["memorySummary"] = "已有可靠记忆摘要"
    raw["summarizedUpTo"] = 10
    container.chat.store.save(raw)
    # 当前有 26 条消息，再补 8 条到 34 条（34 - 10 = 24 >= 24）
    _append_standard_messages(container, sid, 8, prefix="DEG2")

    fail_mode["kind"] = "runtime"
    frames_err = await _send_text_turn(async_client, sid, "异常降级测试消息", headers=key_headers)
    assert "error" not in [f["event"] for f in frames_err]
    assert frames_err[-1]["event"] == "done"
    sess_after_err = frames_err[-1]["data"]["session"]
    assert sess_after_err["summarizedUpTo"] == 10
    assert sess_after_err["memorySummary"] == "已有可靠记忆摘要"
    assert "已有可靠记忆摘要" in chat_prompts[-1]


async def test_5_manual_compact_endpoint_boundaries_and_auth(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 5：手动压缩 POST /compact（阈值不足幂等、保留最近 6 条、401/403/404/504 及脱敏 502）。"""
    bearer_headers, _ = await _admin_login(async_client)
    key_headers = {"X-API-Key": "upstream-key"}
    summary_prompts: list[str] = []
    chat_prompts: list[str] = []
    compact_mode: dict[str, str] = {"mode": "ok"}

    def summary_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if compact_mode["mode"] == "timeout":
            raise TimeoutError("manual compact timeout")
        if compact_mode["mode"] == "error":
            raise RuntimeError(
                "gateway failed sk-secret999999 path=/Users/ops/secret.yaml phone=13900001234"
            )
        summary_prompts.append(_user_prompt_text(messages))
        return ModelResponse(parts=[ToolCallPart("submit_chat_summary", {
            "summary": "手动压缩记忆：已归档前 4 条早期问答。",
        })])

    def chat_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        chat_prompts.append(_user_prompt_text(messages))
        return ModelResponse(parts=[ToolCallPart("submit_chat_action", {
            "action": "reply",
            "text": "已参考手动压缩记忆回复。",
        })])

    container.runner.model = _tri_model(summary_fn=summary_stub, chat_fn=chat_stub)

    # 5.1 鉴权与 404 校验
    r_no_auth = await async_client.post(f"/api/v1/chat/sessions/{'0' * 32}/compact")
    assert r_no_auth.status_code == 401 and r_no_auth.json()["code"] == "INVALID_API_KEY"

    r_bad_key = await async_client.post(
        f"/api/v1/chat/sessions/{'0' * 32}/compact",
        headers={"X-API-Key": "wrong-key"},
    )
    assert r_bad_key.status_code == 401 and r_bad_key.json()["code"] == "INVALID_API_KEY"

    for bad_sid in ("bad-sid-format", "0" * 32):
        r_404 = await async_client.post(
            f"/api/v1/chat/sessions/{bad_sid}/compact",
            headers=key_headers,
        )
        assert r_404.status_code == 404 and r_404.json()["code"] == "SESSION_NOT_FOUND"

    # 5.2 draft 会话隔离：纯 API Key 返回 403 DRAFT_FORBIDDEN，管理端登录允许 200
    draft_sess = await _open_session(
        async_client,
        user_id="u_man_draft",
        order_id="ORD_MAN_DRAFT",
        case_c01=case_c01,
        headers=bearer_headers,
        target="draft",
    )
    draft_sid = draft_sess["sessionId"]
    r_draft_forbidden = await async_client.post(
        f"/api/v1/chat/sessions/{draft_sid}/compact",
        headers=key_headers,
    )
    assert r_draft_forbidden.status_code == 403 and r_draft_forbidden.json()["code"] == "DRAFT_FORBIDDEN"

    r_draft_ok = await async_client.post(
        f"/api/v1/chat/sessions/{draft_sid}/compact",
        headers=bearer_headers,
    )
    assert r_draft_ok.status_code == 200 and r_draft_ok.json()["compacted"] is False

    # 5.3 未归档消息不足（7 < MANUAL_COMPACT_KEEP_RECENT + MANUAL_COMPACT_MIN_SLICE = 8）：幂等返回 compacted=False，0 次模型调用
    online_sess = await _open_session(
        async_client,
        user_id="u_man_online",
        order_id="ORD_MAN_ON",
        case_c01=case_c01,
        headers=key_headers,
    )
    sid = online_sess["sessionId"]
    _append_standard_messages(container, sid, 7, prefix="MAN")

    r_skip = await async_client.post(f"/api/v1/chat/sessions/{sid}/compact", headers=key_headers)
    assert r_skip.status_code == 200, r_skip.text
    skip_body = r_skip.json()
    assert skip_body["compacted"] is False
    assert skip_body["summarizedCount"] == 0
    assert skip_body["summarizedUpTo"] == 0
    assert skip_body["memorySummary"] == ""
    assert len(summary_prompts) == 0

    # 5.4 补至 10 条（可归档 10 - 6 = 4 条）：成功压缩 [0:4]，保留最近 6 条，二次调用幂等跳过
    _append_standard_messages(container, sid, 3, prefix="MAN_MORE")
    r_ok = await async_client.post(f"/api/v1/chat/sessions/{sid}/compact", headers=key_headers)
    assert r_ok.status_code == 200, r_ok.text
    ok_body = r_ok.json()
    assert ok_body["compacted"] is True
    assert ok_body["summarizedCount"] == 4
    assert ok_body["summarizedUpTo"] == 4
    assert ok_body["memorySummary"] == "手动压缩记忆：已归档前 4 条早期问答。"
    assert ok_body["session"]["summarizedUpTo"] == 4
    assert ok_body["session"]["memorySummary"] == ok_body["memorySummary"]
    assert len(summary_prompts) == 1
    assert "MAN_00" in summary_prompts[0] and "MAN_03" in summary_prompts[0]
    assert "MAN_04" not in summary_prompts[0] and "MAN_MORE_02" not in summary_prompts[0]

    # 紧接着再次调用 /compact（仅剩 6 条未归档）：不调模型，返回 compacted=False
    r_idemp = await async_client.post(f"/api/v1/chat/sessions/{sid}/compact", headers=key_headers)
    assert r_idemp.status_code == 200
    assert r_idemp.json()["compacted"] is False
    assert r_idemp.json()["summarizedCount"] == 0
    assert r_idemp.json()["summarizedUpTo"] == 4
    assert len(summary_prompts) == 1

    # 压缩后发消息必须携带该手动压缩记忆摘要，且最近历史不含 MAN_00..03
    await _send_text_turn(async_client, sid, "手动压缩后继续提问", headers=key_headers)
    assert "## 早期对话记忆摘要" in chat_prompts[-1]
    assert "手动压缩记忆：已归档前 4 条早期问答。" in chat_prompts[-1]
    recent_after = chat_prompts[-1].split("## 最近对话历史", 1)[1].split("## 用户本轮消息", 1)[0]
    assert "MAN_03" not in recent_after and "MAN_04" in recent_after

    # 5.5 再追加 6 条满足可归档 >= 2，测试 504 CHAT_COMPACT_TIMEOUT 与 502 CHAT_COMPACT_ERROR 脱敏
    _append_standard_messages(container, sid, 6, prefix="MAN_ERR")
    compact_mode["mode"] = "timeout"
    r_504 = await async_client.post(f"/api/v1/chat/sessions/{sid}/compact", headers=key_headers)
    assert r_504.status_code == 504 and r_504.json()["code"] == "CHAT_COMPACT_TIMEOUT"

    compact_mode["mode"] = "error"
    r_502 = await async_client.post(f"/api/v1/chat/sessions/{sid}/compact", headers=key_headers)
    assert r_502.status_code == 502
    err_502 = r_502.json()
    assert err_502["code"] == "CHAT_COMPACT_ERROR"
    assert "sk-secret999999" not in err_502["message"]
    assert "/Users/ops/secret.yaml" not in err_502["message"]
    assert "13900001234" not in err_502["message"]

    # 异常后原锚点与摘要完好无损
    view_after = (await async_client.get(f"/api/v1/chat/sessions/{sid}", headers=key_headers)).json()
    assert view_after["summarizedUpTo"] == 4
    assert view_after["memorySummary"] == "手动压缩记忆：已归档前 4 条早期问答。"


async def test_6_effective_memory_state_self_healing_and_summary_truncation(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 6：_effective_memory_state 异常状态自愈单测与 MAX_MEMORY_SUMMARY_CHARS 超长截断/空串重试护栏。"""
    # 6.1 _effective_memory_state 单元测试
    assert ChatService._effective_memory_state({"memorySummary": "有效摘要", "summarizedUpTo": True}, 20) == ("", 0)
    assert ChatService._effective_memory_state({"memorySummary": "有效摘要", "summarizedUpTo": False}, 20) == ("", 0)
    assert ChatService._effective_memory_state({"memorySummary": "有效摘要", "summarizedUpTo": -5}, 20) == ("", 0)
    assert ChatService._effective_memory_state({"memorySummary": "有效摘要", "summarizedUpTo": 0}, 20) == ("", 0)
    assert ChatService._effective_memory_state({"memorySummary": "有效摘要", "summarizedUpTo": "12"}, 20) == ("", 0)
    assert ChatService._effective_memory_state({"memorySummary": "有效摘要", "summarizedUpTo": None}, 20) == ("", 0)
    assert ChatService._effective_memory_state({"memorySummary": "  \n\t ", "summarizedUpTo": 10}, 20) == ("", 0)
    assert ChatService._effective_memory_state({"memorySummary": None, "summarizedUpTo": 10}, 20) == ("", 0)
    assert ChatService._effective_memory_state({"memorySummary": "  保留摘要  ", "summarizedUpTo": 99}, 12) == ("保留摘要", 12)
    assert ChatService._effective_memory_state({"memorySummary": "  保留摘要  ", "summarizedUpTo": 6}, 12) == ("保留摘要", 6)

    # 6.2 磁盘异常记忆字段自愈（GET /sessions/{sid} 自动归一为 ("", 0)）
    key_headers = {"X-API-Key": "upstream-key"}
    sess = await _open_session(
        async_client,
        user_id="u_heal",
        order_id="ORD_HEAL_01",
        case_c01=case_c01,
        headers=key_headers,
    )
    sid = sess["sessionId"]
    _append_standard_messages(container, sid, 10, prefix="HEAL")
    session_file = container.layout.chats / sid[:2] / f"{sid}.json"
    disk_sess = read_json(session_file)
    assert isinstance(disk_sess, dict)
    disk_sess["memorySummary"] = "脏数据摘要"
    disk_sess["summarizedUpTo"] = True
    write_json(session_file, disk_sess)
    container.chat.store._cache.clear()

    healed_view = (await async_client.get(f"/api/v1/chat/sessions/{sid}", headers=key_headers)).json()
    assert healed_view["memorySummary"] == ""
    assert healed_view["summarizedUpTo"] == 0

    # 6.3 空摘要触发 output_validator ModelRetry，超长摘要自动截断至 <= MAX_MEMORY_SUMMARY_CHARS
    retry_feedbacks: list[str] = []
    sum_attempts = 0

    def validator_summary_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal sum_attempts
        sum_attempts += 1
        for m in messages:
            if isinstance(m, ModelRequest):
                for p in m.parts:
                    if isinstance(p, RetryPromptPart):
                        retry_feedbacks.append(p.model_response())
                    elif isinstance(p, ToolReturnPart) and p.tool_name == "submit_chat_summary":
                        retry_feedbacks.append(str(p.content))
        if sum_attempts == 1:
            return ModelResponse(parts=[ToolCallPart("submit_chat_summary", {"summary": "   "})])
        return ModelResponse(parts=[ToolCallPart("submit_chat_summary", {"summary": "要" * 1500})])

    container.runner.model = _tri_model(summary_fn=validator_summary_stub)
    r_compact = await async_client.post(f"/api/v1/chat/sessions/{sid}/compact", headers=key_headers)
    assert r_compact.status_code == 200, r_compact.text
    body = r_compact.json()
    assert sum_attempts == 2
    assert any("不能为空" in fb for fb in retry_feedbacks), retry_feedbacks
    assert body["compacted"] is True
    assert len(body["memorySummary"]) <= MAX_MEMORY_SUMMARY_CHARS
    assert body["memorySummary"].endswith("…")


async def test_7_runtime_config_hot_reload_compaction_and_chat_limits(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 7：运行期热更新聊天上下文与压缩参数，无需重启立即生效并在回滚后恢复默认行为。"""
    bearer_headers, _ = await _admin_login(async_client)
    key_headers = {"X-API-Key": "upstream-key"}
    summary_prompts: list[str] = []
    chat_records: list[tuple[str, str]] = []

    def summary_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        summary_prompts.append(_user_prompt_text(messages))
        return ModelResponse(parts=[ToolCallPart("submit_chat_summary", {
            "summary": "HOT_SUMMARY：" + ("要" * 350),
        })])

    def chat_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        chat_records.append((_instructions_text(messages), _user_prompt_text(messages)))
        return ModelResponse(parts=[ToolCallPart("submit_chat_action", {
            "action": "reply",
            "text": "收到，继续为您处理。",
        })])

    container.runner.model = _tri_model(summary_fn=summary_stub, chat_fn=chat_stub)

    # 准备包含 > 600 字单据正文的会话，先核对默认压缩阈值
    long_doc_case = {**case_c01, "documentText": case_c01["documentText"] + "\n" + ("单据补充明细内容。" * 100)}
    assert len(long_doc_case["documentText"]) > 800
    s1 = await _open_session(
        async_client,
        user_id="u_hot_cmp_1",
        order_id="ORD_HOT_CMP_01",
        case_c01=long_doc_case,
        headers=key_headers,
    )
    sid1 = s1["sessionId"]
    assert s1["manualCompactKeepRecent"] == 6
    assert s1["manualCompactMinMessages"] == 8

    # 1. PUT /api/v1/settings/runtime 下调阈值与上下文窗口上限（免重启）
    r_put = await async_client.put(
        "/api/v1/settings/runtime",
        headers=bearer_headers,
        json={
            "chatCompactTriggerMessages": 6,
            "chatCompactKeepRecent": 2,
            "chatManualCompactKeepRecent": 2,
            "chatManualCompactMinSlice": 1,
            "chatMaxMemorySummaryChars": 220,
            "chatMaxHistoryMessages": 6,
            "chatMaxDocChars": 600,
            "chatMaxRunCards": 2,
            "note": "验证聊天热配置与压缩阈值联动",
        },
    )
    assert r_put.status_code == 200, r_put.text

    # 立即查询 GET /sessions/{sid} 返回更新后的手动压缩参数
    view_hot = (await async_client.get(f"/api/v1/chat/sessions/{sid1}", headers=key_headers)).json()
    assert view_hot["manualCompactKeepRecent"] == 2
    assert view_hot["manualCompactMinMessages"] == 3

    # 2. 发送 3 轮（6 条未归档消息）-> 首轮即按 600 字截断单据；第 4 轮入场时按新阈值 6 自动触发压缩且摘要按 220 字截断
    for idx in range(1, 4):
        frames = await _send_text_turn(async_client, sid1, f"HOT_TURN_{idx:02d} 核查问题", headers=key_headers)
        assert [f["data"]["text"] for f in frames if f["event"] == "status"] == ["正在思考…"]
        assert "以下截取前 600 字" in chat_records[-1][0]
    assert len(summary_prompts) == 0

    frames_trigger = await _send_text_turn(async_client, sid1, "HOT_TURN_04 触发自动压缩", headers=key_headers)
    assert [f["data"]["text"] for f in frames_trigger if f["event"] == "status"] == [
        "正在压缩早期对话上下文…",
        "正在思考…",
    ]
    assert len(summary_prompts) == 1
    assert "HOT_TURN_01" in summary_prompts[0] and "HOT_TURN_02" in summary_prompts[0]
    assert "HOT_TURN_03" not in summary_prompts[0]

    done_s1 = frames_trigger[-1]["data"]["session"]
    assert done_s1["summarizedUpTo"] == 4
    assert len(done_s1["memorySummary"]) == 220
    assert done_s1["memorySummary"].endswith("…")

    # 3. 验证 chatMaxHistoryMessages=6 与 chatMaxRunCards=2 免重启生效
    s_cards = await _open_session(
        async_client,
        user_id="u_hot_cards",
        order_id="ORD_HOT_CARDS_01",
        case_c01=long_doc_case,
        headers=key_headers,
    )
    sid_cards = s_cards["sessionId"]
    run_ids: list[str] = []
    for _ in range(3):
        rr = await async_client.post(
            f"/api/v1/chat/sessions/{sid_cards}/runs",
            json={"templateId": 1001},
            headers=key_headers,
        )
        assert rr.status_code == 200, rr.text
        rid = rr.json()["message"]["runId"]
        run_ids.append(rid)
        ev_frames = _parse_sse(
            (await async_client.get(f"/api/v1/chat/runs/{rid}/events?after=0", headers=key_headers)).text
        )
        assert ev_frames[-1]["event"] == "final"

    _append_standard_messages(container, sid_cards, 8, prefix="HIST_CAP")
    await _send_text_turn(async_client, sid_cards, "", headers=key_headers, auto=True)
    last_inst, last_prompt = chat_records[-1]
    assert run_ids[0] not in last_inst
    assert run_ids[1] in last_inst and run_ids[2] in last_inst
    recent_sec = last_prompt.split("## 最近对话历史", 1)[1].split("## 用户本轮消息", 1)[0]
    assert "HIST_CAP_00" not in recent_sec and "HIST_CAP_01" not in recent_sec
    assert "HIST_CAP_07" in recent_sec

    # 4. 未达旧阈值 8 但已达新阈值 3（4 条消息）时，调用 POST /compact 成功按 keepRecent=2 压缩
    s2 = await _open_session(
        async_client,
        user_id="u_hot_man",
        order_id="ORD_HOT_MAN_01",
        case_c01=case_c01,
        headers=key_headers,
    )
    sid2 = s2["sessionId"]
    await _send_text_turn(async_client, sid2, "MAN_HOT_01", headers=key_headers)
    await _send_text_turn(async_client, sid2, "MAN_HOT_02", headers=key_headers)

    r_man = await async_client.post(f"/api/v1/chat/sessions/{sid2}/compact", headers=key_headers)
    assert r_man.status_code == 200, r_man.text
    man_body = r_man.json()
    assert man_body["compacted"] is True
    assert man_body["summarizedCount"] == 2
    assert man_body["summarizedUpTo"] == 2
    assert len(man_body["memorySummary"]) == 220
    assert man_body["memorySummary"].endswith("…")

    # 仅剩 2 条未归档消息（== keepRecent=2），再次 /compact 幂等跳过
    r_man_again = await async_client.post(f"/api/v1/chat/sessions/{sid2}/compact", headers=key_headers)
    assert r_man_again.status_code == 200 and r_man_again.json()["compacted"] is False

    # 5. 回退配置至 c1，立即恢复默认阈值与上下文窗口大小
    r_rb = await async_client.post(
        "/api/v1/settings/runtime/rollback",
        headers=bearer_headers,
        json={"targetRev": "c1", "reason": "恢复默认聊天上下文与压缩配置"},
    )
    assert r_rb.status_code == 200, r_rb.text

    view_rb = (await async_client.get(f"/api/v1/chat/sessions/{sid2}", headers=key_headers)).json()
    assert view_rb["manualCompactKeepRecent"] == 6
    assert view_rb["manualCompactMinMessages"] == 8

    s3 = await _open_session(
        async_client,
        user_id="u_hot_rb",
        order_id="ORD_HOT_RB_01",
        case_c01=long_doc_case,
        headers=key_headers,
    )
    sid3 = s3["sessionId"]
    _append_standard_messages(container, sid3, 7, prefix="RB_DEFAULT")
    # 7 条消息：低于默认手动压缩门槛 8，也低于默认自动压缩阈值 24
    r_man_rb = await async_client.post(f"/api/v1/chat/sessions/{sid3}/compact", headers=key_headers)
    assert r_man_rb.status_code == 200 and r_man_rb.json()["compacted"] is False

    sum_count_before = len(summary_prompts)
    rb_frames = await _send_text_turn(async_client, sid3, "回退后普通提问", headers=key_headers)
    assert [f["data"]["text"] for f in rb_frames if f["event"] == "status"] == ["正在思考…"]
    assert len(summary_prompts) == sum_count_before
    assert "以下截取前 600 字" not in chat_records[-1][0]
