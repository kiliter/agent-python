"""API 路由、双轨鉴权与嵌入式聊天后端审查修复回归测试。

#Created By AiCoding(codex)
覆盖：
1. UserStore 统计缓存与外部修改自动失效、超长口令/用户名边界防护、TokenService 非法载荷拦截、LoginGuard 键长收敛与跨事件循环登录信号量；
2. 模板/Skill/API/系统提示词草稿乐观锁负值与布尔值校验、API 草稿数值字段布尔值防护、历史损坏运行记录视图容错；
3. 聊天草稿会话防 API Key 降级劫持、补参清空用户补充可选参数、AI 改写后重选旧版本再确认的审计与状态更新；
4. ChatStore 异步读写、冷文件扫描不污染缓存、过期清理与会话锁并发互斥、SSE 事件流异常帧兜底、ChatAgent 实例缓存与双引号错误脱敏。
"""

from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import time
from typing import Any

import httpx
import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from report_agent.api.auth import (
    MAX_PASSWORD_LEN,
    MAX_USERNAME_LEN,
    LoginGuard,
    TokenService,
    User,
    UserStore,
    hash_password,
    verify_password,
)
from report_agent.api.run_views import detail_view, report_view
from report_agent.chat.service import ChatError
from report_agent.chat.steps import StepMapper, sanitize_error_text
from report_agent.chat.store import ChatStore, inputs_fingerprint, session_id_for
from report_agent.main import create_app
from report_agent.runtime.workspace import ProcessEvent
from report_agent.store.fsutil import read_jsonl
from scripted_model import scripted


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    """解析 SSE 响应帧，忽略注释心跳行。"""
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
        if data_lines:
            events.append({
                "id": evt_id,
                "event": evt_name,
                "data": json.loads("\n".join(data_lines)),
            })
    return events


def _dual_model(chat_fn: Any = None, report_fn: Any = scripted) -> FunctionModel:
    """构造同时服务 ChatAgent 与 AgentRunner 的桩模型。"""

    def _dispatch(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        is_chat = any(t.name == "submit_chat_action" for t in info.output_tools)
        target = chat_fn if (is_chat and chat_fn is not None) else report_fn
        return target(messages, info)

    return FunctionModel(_dispatch, model_name="review-dual-model")


@pytest.fixture
async def async_client(container):
    """提供带完整 lifespan 的异步测试客户端，并预置管理端账号。"""
    UserStore(container.layout.config / "users.yaml").upsert(
        "reviewer", "pass-review-123", "审查员", "平台管理"
    )
    app = create_app(container=container)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as cl:
            yield cl


async def _admin_headers(cl: httpx.AsyncClient) -> dict[str, str]:
    r = await cl.post("/api/v1/auth/login", json={"username": "reviewer", "password": "pass-review-123"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    cl.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def test_auth_user_store_mtime_cache_and_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """验证 UserStore stat 缓存隔离与外部写文件失效、口令长度上限、Token 非法载荷拦截及 LoginGuard 键长收敛。"""
    users_path = tmp_path / "users.yaml"
    store = UserStore(users_path)
    store.upsert("alice", "correct-pass", "Alice", "业务维护")

    # 首次读取加载进缓存；修改返回字典不得污染内部缓存
    u1 = store.get("alice")
    assert u1 is not None and u1["displayName"] == "Alice"
    u1["displayName"] = "Tampered"
    assert store.get("alice")["displayName"] == "Alice"
    all_users = store._load()
    all_users.clear()
    assert store.count() == 1

    # 模拟外部直接改写 users.yaml（改变文件大小以确保同纳秒内也能被 (mtime_ns, size) 识别）
    raw_yaml = users_path.read_text(encoding="utf-8") + "\n# external-comment-padding\n"
    users_path.write_text(raw_yaml.replace("Alice", "AliceUpdated"), encoding="utf-8")
    u2 = store.get("alice")
    assert u2 is not None and u2["displayName"] == "AliceUpdated"

    # 超长口令：hash_password 抛异常，verify_password 直接短路返回 False（不触发 PBKDF2）
    with pytest.raises(ValueError, match="密码长度"):
        hash_password("x" * (MAX_PASSWORD_LEN + 1))

    import hashlib
    called_pbkdf2 = False
    orig_pbkdf2 = hashlib.pbkdf2_hmac

    def _spy_pbkdf2(*args: Any, **kwargs: Any) -> bytes:
        nonlocal called_pbkdf2
        called_pbkdf2 = True
        return orig_pbkdf2(*args, **kwargs)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", _spy_pbkdf2)
    assert verify_password("x" * (MAX_PASSWORD_LEN + 1), u2["passwordHash"]) is False
    assert called_pbkdf2 is False

    # TokenService：拦截超长 token、空 nonce 与非有限/过期 exp
    tokens = TokenService(b"test-token-secret-bytes", ttl_s=3600)
    valid_tok = tokens.issue(User("alice", "Alice", "业务维护"))
    verified = tokens.verify(valid_tok)
    assert verified is not None and verified[0].username == "alice"
    assert tokens.verify("a" * 5000) is None

    import base64
    import hmac as hmac_mod

    def _forge(payload_obj: dict[str, Any]) -> str:
        body = base64.urlsafe_b64encode(json.dumps(payload_obj).encode()).rstrip(b"=").decode()
        sig = hmac_mod.new(tokens.secret, body.encode(), hashlib.sha256).digest()
        sig_s = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        return f"{body}.{sig_s}"

    assert tokens.verify(_forge({"u": "alice", "exp": time.time() + 60, "n": ""})) is None
    assert tokens.verify(_forge({"u": "alice", "exp": math.nan, "n": "nonce123"})) is None
    tokens.revoke(verified[1])
    assert tokens.verify(valid_tok) is None

    # LoginGuard：超长用户名与 IP 会被定长摘要收敛，不会向内存表塞入超长原串
    guard = LoginGuard(max_failures=3, lock_s=60)
    huge_user = "u" * 4096
    huge_ip = "9" * 4096
    guard.fail(huge_user, known_user=False, client_ip=huge_ip)
    assert all(len(k) < 200 for k in guard._ip_fails)
    assert all(len(k) < 200 for k in guard._fails)


def test_login_cross_event_loop_semaphore_and_input_bounds(container):
    """验证登录接口在多个独立 asyncio 事件循环间正常复用限流信号量，并拦截超长账号口令。"""
    UserStore(container.layout.config / "users.yaml").upsert(
        "loop_admin", "loop-pass-123", "循环测试员", "平台管理"
    )
    app = create_app(container=container)

    async def _exercise_in_fresh_loop() -> None:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as cl:
                r_ok = await cl.post(
                    "/api/v1/auth/login",
                    json={"username": "loop_admin", "password": "loop-pass-123"},
                )
                assert r_ok.status_code == 200
                r_long_u = await cl.post(
                    "/api/v1/auth/login",
                    json={"username": "u" * (MAX_USERNAME_LEN + 5), "password": "x"},
                )
                assert r_long_u.status_code == 400 and r_long_u.json()["code"] == "INVALID_USERNAME"
                r_long_p = await cl.post(
                    "/api/v1/auth/login",
                    json={"username": "loop_admin", "password": "p" * (MAX_PASSWORD_LEN + 5)},
                )
                assert r_long_p.status_code == 401 and r_long_p.json()["code"] == "INVALID_CREDENTIALS"

    # 连续在两个不同事件循环中执行登录，不得触发绑定旧事件循环的 RuntimeError
    asyncio.run(_exercise_in_fresh_loop())
    asyncio.run(_exercise_in_fresh_loop())


async def test_draft_revision_validation_and_api_bool_guard(async_client: httpx.AsyncClient):
    """验证各资源草稿接口统一拒绝负数/布尔 revision，且接口草稿 timeoutMs/retry 忽略布尔值。"""
    headers = await _admin_headers(async_client)

    for method, url, payload in [
        ("PUT", "/api/v1/templates/1001/draft", {"name": "x", "revision": -1}),
        ("PUT", "/api/v1/templates/1001/draft", {"name": "x", "revision": True}),
        ("PUT", "/api/v1/skills/order-sms-verify/draft", {"markdown": "---\nname: order-sms-verify\n---\n", "revision": -2}),
        ("PUT", "/api/v1/skills/order-sms-verify/draft", {"markdown": "---\nname: order-sms-verify\n---\n", "revision": False}),
        ("PUT", "/api/v1/apis/querySMSSendInfo/draft", {"api": {"title": "x"}, "revision": -1}),
        ("PUT", "/api/v1/apis/querySMSSendInfo/draft", {"api": {"title": "x"}, "revision": True}),
        ("PUT", "/api/v1/settings/system-prompt/draft", {"sysPromptText": "prompt", "revision": -1}),
        ("PUT", "/api/v1/settings/system-prompt/draft", {"sysPromptText": "prompt", "revision": True}),
    ]:
        resp = await async_client.request(method, url, json=payload, headers=headers)
        assert resp.status_code == 400, f"{url} -> {resp.status_code}: {resp.text}"
        assert resp.json()["code"] == "INVALID_REVISION"

    # 先保存系统提示词草稿，再验证发布时负数/布尔 revision 同样返回 INVALID_REVISION
    r_sp = await async_client.put(
        "/api/v1/settings/system-prompt/draft",
        json={"sysPromptText": "新系统提示词内容"},
        headers=headers,
    )
    assert r_sp.status_code == 200
    r_pub_bad = await async_client.post(
        "/api/v1/settings/system-prompt/publish",
        json={"note": "bad rev", "revision": -1},
        headers=headers,
    )
    assert r_pub_bad.status_code == 400 and r_pub_bad.json()["code"] == "INVALID_REVISION"

    # API 草稿传入布尔值 timeoutMs/retry 时必须按非法数值返回 400，不得静默强转为整数 1
    r_bad_timeout = await async_client.put(
        "/api/v1/apis/querySMSSendInfo/draft",
        json={"api": {"title": "短信查询接口草稿", "timeoutMs": True}},
        headers=headers,
    )
    assert r_bad_timeout.status_code == 400
    r_bad_retry = await async_client.put(
        "/api/v1/apis/querySMSSendInfo/draft",
        json={"api": {"title": "短信查询接口草稿", "retry": True}},
        headers=headers,
    )
    assert r_bad_retry.status_code == 400


def test_run_views_resilient_to_malformed_legacy_detail():
    """验证 detail_view 与 report_view 面对历史脏数据（损坏的 columns、布尔/字符串耗时与计数）时不抛 500。"""
    malformed = {
        "runId": "run-20261112-000001-abcd",
        "status": "PARTIAL",
        "templateId": 1001,
        "templateName": "样例模板",
        "rev": "r1",
        "entry": "上游调用",
        "startTime": "2026-11-12T10:00:00+08:00",
        "durationMs": "not-a-number",
        "rounds": True,
        "foundCount": None,
        "totalCount": "bad",
        "inputs": {"手机号码": "13900001234"},
        "document": "测试单据原文",
        "fields": [
            {
                "name": "异常列表字段",
                "type": "list",
                "columns": [{"invalid_col": 123}],
                "status": "not_found",
                "value": None,
                "evidence": [],
                "reasoning": "无数据",
                "shown": True,
            }
        ],
        "apiResults": [{"id": "r1", "name": "querySMSSendInfo", "ok": True, "ms": "oops", "records": []}],
        "events": [],
        "validationRounds": [],
    }
    view = detail_view(malformed)
    assert view["durationSec"] == 0.0
    assert view["rounds"] == 0
    assert view["foundCount"] == 0
    assert view["totalCount"] == 1
    assert len(view["fields"]) == 1
    assert view["fields"][0]["name"] == "异常列表字段"
    rep_view = report_view(malformed)
    assert rep_view["durationMs"] == 0


async def test_chat_open_session_blocks_api_key_hijacking_draft_session(async_client: httpx.AsyncClient):
    """验证管理端创建的 draft 会话不能被仅持 X-API-Key 的外部调用方通过 target='online' 覆盖或读取。"""
    admin_headers = await _admin_headers(async_client)
    key_headers = {"X-API-Key": "upstream-key"}

    r_draft = await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_sec",
            "orderId": "ORD_SEC_DRAFT",
            "inputs": {"手机号码": "13900001234"},
            "document": "内部草稿测试单据",
            "target": "draft",
        },
        headers=admin_headers,
    )
    assert r_draft.status_code == 200
    sid = r_draft.json()["sessionId"]
    assert r_draft.json()["target"] == "draft"

    # 外部 API Key 试图以 target="online" 打开同一 (userId, orderId) 必须被 403 拦截
    r_hijack = await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_sec",
            "orderId": "ORD_SEC_DRAFT",
            "inputs": {"手机号码": "13900001234"},
            "document": "内部草稿测试单据",
            "target": "online",
        },
        headers=key_headers,
    )
    assert r_hijack.status_code == 403 and r_hijack.json()["code"] == "DRAFT_FORBIDDEN"

    # 确认原会话仍保持 draft，外部 Key 仍无法读取，而管理端用户可正常读取并切换模式
    r_get_key = await async_client.get(f"/api/v1/chat/sessions/{sid}", headers=key_headers)
    assert r_get_key.status_code == 403
    r_admin_switch = await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_sec",
            "orderId": "ORD_SEC_DRAFT",
            "inputs": {"手机号码": "13900001234"},
            "document": "内部草稿测试单据",
            "target": "online",
        },
        headers=admin_headers,
    )
    assert r_admin_switch.status_code == 200 and r_admin_switch.json()["target"] == "online"


async def test_chat_store_async_io_cleanup_race_and_cold_scan(tmp_path: Path):
    """验证 ChatStore 异步读写、空值指纹归一、has_run_id 不污染 LRU 缓存，以及持有会话锁时防过期误删。"""
    assert inputs_fingerprint({"a": "1", "empty": "   "}, "doc") == inputs_fingerprint({"a": "1"}, "doc")

    store = ChatStore(tmp_path / "chats", max_cache=2)
    sid_hot = session_id_for("u1", "ord1")
    sid_cold = session_id_for("u2", "ord2")

    await store.asave({
        "sessionId": sid_cold,
        "userId": "u2",
        "orderId": "ord2",
        "messages": [{"kind": "run", "runId": "run-cold-001"}],
    })
    # 清空内存缓存模拟进程重启后冷盘扫描
    store._cache.clear()
    await store.asave({"sessionId": sid_hot, "userId": "u1", "orderId": "ord1", "messages": []})
    assert list(store._cache.keys()) == [sid_hot]

    assert store.has_run_id(sid_cold, "run-cold-001") is True
    assert store.has_run_id(sid_cold, "run-missing") is False
    # 冷扫描不应把 sid_cold 挤入 _cache
    assert list(store._cache.keys()) == [sid_hot]

    loaded = await store.aget(sid_cold)
    assert loaded is not None and loaded["orderId"] == "ord2"

    # 将 sid_hot 的磁盘文件时间戳设为 10 天前，但在持有 lock_for(sid_hot) 期间执行 cleanup 不得删除该活跃会话
    hot_file = tmp_path / "chats" / sid_hot[:2] / f"{sid_hot}.json"
    old_ts = time.time() - 10 * 86400
    os.utime(hot_file, (old_ts, old_ts))
    async with store.lock_for(sid_hot):
        removed_while_locked = await asyncio.to_thread(store.cleanup, 7)
        assert removed_while_locked == 0
        assert hot_file.is_file()

    # 释放会话锁后再次执行 cleanup，超期文件正常清理
    removed_after_unlock = await asyncio.to_thread(store.cleanup, 7)
    assert removed_after_unlock == 1
    assert not hot_file.exists()


async def test_chat_confirm_after_ai_rewrite_reconfirms_v1_and_audits(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """验证确认 v1 -> 幂等重放 -> AI 改写生成 v2 -> 重新切回 v1 确认时，准确更新 edited/rewritten 并追加审计。"""
    rewritten_md = "# 改写版报告\n\n尊敬的客户，经核查已完成处理。"

    def _chat_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name="submit_chat_action",
                args={
                    "action": "rewrite",
                    "text": "已按要求精简口径。",
                    "markdown": rewritten_md,
                },
            )
        ])

    container.runner.model = _dual_model(chat_fn=_chat_fn, report_fn=scripted)
    key_headers = {"X-API-Key": "upstream-key"}

    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_conf",
            "orderId": "ORD_CONF_REWRITE",
            "inputs": case_c01["inputs"],
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid = sess["sessionId"]

    r_start = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )
    assert r_start.status_code == 200
    run_id = r_start.json()["message"]["runId"]

    r_ev = await async_client.get(f"/api/v1/chat/runs/{run_id}/events", headers=key_headers)
    ev_frames = _parse_sse(r_ev.text)
    final_card = next(e["data"] for e in ev_frames if e["event"] == "final")
    assert final_card["status"] == "SUCCESS"
    v1_md = final_card["versions"][0]["markdown"]

    # 1) 首次确认 v1 原稿
    c1 = (await async_client.post(
        f"/api/v1/chat/runs/{run_id}/confirm",
        json={"markdown": v1_md},
        headers=key_headers,
    )).json()
    assert c1["payload"]["edited"] is False and c1["payload"]["rewritten"] is False
    assert c1["session"]["confirmed"]["edited"] is False
    assert c1["session"]["confirmed"]["rewritten"] is False

    # 2) 原样重复点击确认：严格幂等，不重复追加 confirmed 系统消息与审计日志
    c1_dup = (await async_client.post(
        f"/api/v1/chat/runs/{run_id}/confirm",
        json={"markdown": v1_md},
        headers=key_headers,
    )).json()
    conf_msgs_before = [m for m in c1_dup["session"]["messages"] if m["kind"] == "confirmed"]
    audits_before = [a for a in read_jsonl(container.layout.audit) if a.get("action") == "chat-confirm"]
    assert len(conf_msgs_before) == 1
    assert len(audits_before) == 1

    # 3) 触发 AI 改写生成 v2（此时卡片 confirmed 复位为 False，最新版本变为 rewrite）
    r_msg = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        json={"text": "请精简一下这份报告"},
        headers=key_headers,
    )
    assert r_msg.status_code == 200
    msg_frames = _parse_sse(r_msg.text)
    done_sess = next(e["data"]["session"] for e in msg_frames if e["event"] == "done")
    run_card_after_rw = next(m for m in done_sess["messages"] if m["kind"] == "run" and m["runId"] == run_id)
    assert run_card_after_rw["confirmed"] is False
    assert len(run_card_after_rw["versions"]) == 2

    # 4) 用户在预览窗切回 v1 正文再次确认：相对最新 v2 属于 edited=True 且 rewritten=True，不得误判为幂等跳过
    c2 = (await async_client.post(
        f"/api/v1/chat/runs/{run_id}/confirm",
        json={"markdown": v1_md},
        headers=key_headers,
    )).json()
    assert c2["payload"]["edited"] is True
    assert c2["payload"]["rewritten"] is True
    assert c2["session"]["confirmed"]["edited"] is True
    assert c2["session"]["confirmed"]["rewritten"] is True
    run_card_reconfirmed = next(m for m in c2["session"]["messages"] if m["kind"] == "run" and m["runId"] == run_id)
    assert run_card_reconfirmed["confirmed"] is True

    conf_msgs_after = [m for m in c2["session"]["messages"] if m["kind"] == "confirmed"]
    audits_after = [a for a in read_jsonl(container.layout.audit) if a.get("action") == "chat-confirm"]
    assert len(conf_msgs_after) == 2
    assert len(audits_after) == 2
    assert audits_after[-1]["edited"] is True and audits_after[-1]["rewritten"] is True


async def test_chat_clear_supplemented_optional_input_and_agent_cache(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """验证补参表单可将此前误填的「用户补充」可选参数置空清除（保留「上层」参数），并验证 ChatAgent 实例缓存与失效。"""
    assert container.chat is not None
    chat_agent = container.chat.chat_agent
    ag1, _ = chat_agent._get_or_build_agent()
    ag2, _ = chat_agent._get_or_build_agent()
    assert ag1 is ag2

    # 切换 runner.model 后，ChatAgent 缓存必须立即失效重建
    container.runner.model = _dual_model()
    ag3, _ = chat_agent._get_or_build_agent()
    assert ag3 is not ag1

    key_headers = {"X-API-Key": "upstream-key"}
    upstream_only = {
        "手机号码": case_c01["inputs"]["手机号码"],
        "业务名称": case_c01["inputs"]["业务名称"],
        "创建时间": case_c01["inputs"]["创建时间"],
    }
    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_opt",
            "orderId": "ORD_OPT_CLEAR",
            "inputs": upstream_only,
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid = sess["sessionId"]

    # 1) 用户在补参时误填了格式错误的非必填参数「业务月份」-> 返回 ask_params
    r_bad = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001, "inputs": {"业务月份": "invalid-month"}},
        headers=key_headers,
    )
    assert r_bad.status_code == 200
    assert r_bad.json()["message"]["kind"] == "ask_params"
    assert r_bad.json()["session"]["inputs"]["业务月份"] == "invalid-month"

    # 2) 用户将「业务月份」清空为 ""，同时即使传入空串「手机号码」也不得冲掉上层入参 -> 校验通过并启动 RUNNING
    r_clear = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001, "inputs": {"业务月份": "", "手机号码": ""}},
        headers=key_headers,
    )
    assert r_clear.status_code == 200
    body = r_clear.json()
    assert body["message"]["kind"] == "run"
    assert "业务月份" not in body["session"]["inputs"]
    assert body["session"]["inputs"]["手机号码"] == upstream_only["手机号码"]

    # 等待该后台运行结束，避免退出 lifespan 时产生中断残留
    run_id = body["message"]["runId"]
    await async_client.get(f"/api/v1/chat/runs/{run_id}/events", headers=key_headers)


async def test_chat_events_sse_error_frame_and_double_quote_masking(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    """验证运行事件流在中途抛出异常时输出标准 event: error 帧，且 StepMapper 同时掩码单双引号敏感字面量。"""
    mapper = StepMapper()
    step = mapper.feed(ProcessEvent(
        1,
        "tool",
        25,
        1,
        {
            "tool": "call_api",
            "ok": False,
            "args": {"name": "querySMSSendInfo"},
            "result": {"error": '上游错误 "secret_double_quote" 与 \'secret_single_quote\' 号码 13912345678'},
        },
    ))
    assert step is not None and step["ok"] is False
    assert "secret_double_quote" not in step["text"]
    assert "secret_single_quote" not in step["text"]
    assert "13912345678" not in step["text"]

    key_headers = {"X-API-Key": "upstream-key"}
    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_sse",
            "orderId": "ORD_SSE_ERR",
            "inputs": case_c01["inputs"],
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid = sess["sessionId"]

    r_start = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )
    run_id = r_start.json()["message"]["runId"]
    # 先正常拉完确保运行完成
    await async_client.get(f"/api/v1/chat/runs/{run_id}/events", headers=key_headers)

    async def _broken_stream(*args: Any, **kwargs: Any):
        yield ("step", {"seq": 1, "atMs": 10, "icon": "start", "text": "开始", "ok": True})
        raise ChatError(500, "STREAM_BROKEN", "模拟事件重放中途失败")

    monkeypatch.setattr(container.chat, "stream_events", _broken_stream)
    r_err = await async_client.get(f"/api/v1/chat/runs/{run_id}/events", headers=key_headers)
    assert r_err.status_code == 200
    frames = _parse_sse(r_err.text)
    assert [f["event"] for f in frames] == ["step", "error"]
    assert frames[0]["id"] == "1"
    assert frames[1]["data"]["code"] == "STREAM_BROKEN"


async def test_template_subresource_revision_strict_validation(async_client: httpx.AsyncClient):
    """验证字段删除（Body 与 Query）、批量改证据类型、字段排序、Skill 绑定均严格拦截布尔/非法 revision。"""
    headers = await _admin_headers(async_client)

    for method, url, payload in [
        ("DELETE", "/api/v1/templates/1001/fields/手机号码", {"revision": True}),
        ("DELETE", "/api/v1/templates/1001/fields/手机号码", {"revision": False}),
        ("DELETE", "/api/v1/templates/1001/fields/手机号码", {"revision": -1}),
        ("DELETE", "/api/v1/templates/1001/fields/手机号码", {"revision": "abc"}),
        ("POST", "/api/v1/templates/1001/fields/batch-evidence", {"fieldNames": [], "evidenceType": "quote", "revision": True}),
        ("POST", "/api/v1/templates/1001/fields/batch-evidence", {"fieldNames": [], "evidenceType": "quote", "revision": False}),
        ("POST", "/api/v1/templates/1001/fields/batch-evidence", {"fieldNames": [], "evidenceType": "quote", "revision": -1}),
        ("PUT", "/api/v1/templates/1001/fields-order", {"names": [], "revision": True}),
        ("PUT", "/api/v1/templates/1001/fields-order", {"names": [], "revision": False}),
        ("PUT", "/api/v1/templates/1001/fields-order", {"names": [], "revision": -1}),
        ("PUT", "/api/v1/templates/1001/skills", {"skills": ["order-sms-verify"], "revision": True}),
        ("PUT", "/api/v1/templates/1001/skills", {"skills": ["order-sms-verify"], "revision": False}),
        ("PUT", "/api/v1/templates/1001/skills", {"skills": ["order-sms-verify"], "revision": -1}),
    ]:
        resp = await async_client.request(method, url, json=payload, headers=headers)
        assert resp.status_code == 400, f"{method} {url} {payload} -> {resp.status_code}: {resp.text}"
        assert resp.json()["code"] == "INVALID_REVISION"

    # delete_field 的查询参数 revision 对布尔串、非数字串、负数统一返回 400 INVALID_REVISION
    for bad_q in ("true", "false", "abc", "-1", "1.5"):
        resp = await async_client.delete(
            f"/api/v1/templates/1001/fields/手机号码?revision={bad_q}",
            headers=headers,
        )
        assert resp.status_code == 400, f"query revision={bad_q} -> {resp.status_code}: {resp.text}"
        assert resp.json()["code"] == "INVALID_REVISION"

    # 新增一个未被引用的临时字段，验证合法数字查询串走乐观锁比对（错号 409、对号 200）
    r_add = await async_client.put(
        "/api/v1/templates/1001/fields/临时待删字段",
        json={"name": "临时待删字段", "type": "string", "evidence": "quote"},
        headers=headers,
    )
    assert r_add.status_code == 200
    cur_rev = r_add.json()["revision"]

    r_conflict = await async_client.delete(
        f"/api/v1/templates/1001/fields/临时待删字段?revision={cur_rev + 10}",
        headers=headers,
    )
    assert r_conflict.status_code == 409 and r_conflict.json()["code"] == "DRAFT_CONFLICT"

    r_del_ok = await async_client.delete(
        f"/api/v1/templates/1001/fields/临时待删字段?revision={cur_rev}",
        headers=headers,
    )
    assert r_del_ok.status_code == 200 and r_del_ok.json()["deletedName"] == "临时待删字段"


async def test_chat_timeout_and_internal_error_sanitization(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
):
    """验证 TimeoutError 友好超时提示、SDK/内部异常敏感路径与密钥脱敏，以及 SSE INTERNAL_ERROR 不泄露内部异常文本。"""
    cleaned = sanitize_error_text(
        "读取失败：/Users/admin/.secret/key.pem C:\\Users\\admin\\cfg.yaml "
        "Authorization: Bearer tok_secret987654 api_key=my_raw_secret sk-proj1234567890 "
        "号码 13900009999 证件 32010219900101123X HTTP/1.1 502"
    )
    for leaked in (
        "/Users/admin",
        "key.pem",
        "C:\\Users",
        "tok_secret987654",
        "my_raw_secret",
        "sk-proj1234567890",
        "13900009999",
        "32010219900101123X",
    ):
        assert leaked not in cleaned
    assert "HTTP/1.1 502" in cleaned
    assert sanitize_error_text("", fallback="ValueError") == "ValueError"

    assert container.chat is not None
    key_headers = {"X-API-Key": "upstream-key"}
    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_err_san",
            "orderId": "ORD_ERR_SAN",
            "inputs": case_c01["inputs"],
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid = sess["sessionId"]

    # 1) ChatAgent 超时抛出空消息 TimeoutError()：返回明确超时提示而非尾随空冒号
    async def _raise_timeout(*args: Any, **kwargs: Any):
        raise TimeoutError()

    monkeypatch.setattr(container.chat.chat_agent, "run", _raise_timeout)
    r_timeout = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        json={"text": "帮我推荐模板"},
        headers=key_headers,
    )
    assert r_timeout.status_code == 200
    timeout_frames = _parse_sse(r_timeout.text)
    err_frame = next(f["data"] for f in timeout_frames if f["event"] == "error")
    assert err_frame["code"] == "CHAT_AGENT_ERROR"
    assert err_frame["message"] == "聊天助手响应超时，请稍后重试"
    assert any(f["event"] == "done" for f in timeout_frames)

    # 2) ChatAgent 抛出携带本地路径、密钥、号码的异常：经脱敏后返回，且空异常回退类名
    async def _raise_sensitive(*args: Any, **kwargs: Any):
        raise RuntimeError(
            "加载 /Users/secret/data/current.json 失败 Bearer secret_jwt_token_123 号码 13900008888 'raw_body'"
        )

    monkeypatch.setattr(container.chat.chat_agent, "run", _raise_sensitive)
    r_sens = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        json={"text": "再试一次"},
        headers=key_headers,
    )
    sens_frames = _parse_sse(r_sens.text)
    sens_err = next(f["data"] for f in sens_frames if f["event"] == "error")
    assert sens_err["code"] == "CHAT_AGENT_ERROR"
    assert sens_err["message"].startswith("聊天助手响应失败：")
    for secret_piece in ("/Users/secret", "current.json", "secret_jwt_token_123", "13900008888", "raw_body"):
        assert secret_piece not in sens_err["message"]

    async def _raise_empty_exc(*args: Any, **kwargs: Any):
        raise ValueError("")

    monkeypatch.setattr(container.chat.chat_agent, "run", _raise_empty_exc)
    r_empty_exc = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        json={"text": "空异常测试"},
        headers=key_headers,
    )
    empty_err = next(f["data"] for f in _parse_sse(r_empty_exc.text) if f["event"] == "error")
    assert empty_err["message"] == "聊天助手响应失败：ValueError"

    # 3) SSE 流内部未知异常（非 ChatError）：返回统一友好文案，不向外部透传原始异常栈/路径
    async def _unexpected_crash(*args: Any, **kwargs: Any):
        if False:
            yield ("status", {})
        raise RuntimeError("数据库文件损坏 /var/data/chats/secret.json api_key=leak123456")

    monkeypatch.setattr(container.chat, "send_message", _unexpected_crash)
    r_internal = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        json={"text": "触发未知异常"},
        headers=key_headers,
    )
    internal_frames = _parse_sse(r_internal.text)
    internal_err = next(f["data"] for f in internal_frames if f["event"] == "error")
    assert internal_err == {"code": "INTERNAL_ERROR", "message": "服务内部错误，请稍后重试"}


async def test_chat_store_cold_read_serialized_with_cleanup_and_save(tmp_path: Path):
    """验证 ChatStore 冷读盘（get/aget/has_run_id）持有分片文件锁，与 cleanup/asave 并发时绝不复活已删会话。"""
    import threading

    store = ChatStore(tmp_path / "chats", max_cache=8)
    sid = session_id_for("u_race", "ord_race")
    await store.asave({
        "sessionId": sid,
        "userId": "u_race",
        "orderId": "ord_race",
        "messages": [{"kind": "run", "runId": "run-race-001"}],
    })
    session_file = tmp_path / "chats" / sid[:2] / f"{sid}.json"
    old_ts = time.time() - 10 * 86400
    os.utime(session_file, (old_ts, old_ts))
    store._cache.clear()

    # 场景 1：模拟线程已持有分片锁（等同 cleanup 正在删除该分片文件），并发发起冷 aget 与 has_run_id：
    # 它们在未命中 _cache 后必须在 _stripe_lock 外等待；待文件删除并释放分片锁后，必须返回 None / False 且不回填缓存
    stripe_lock = store._stripe_lock(sid)
    entered_lock = threading.Event()
    release_lock = threading.Event()

    def _simulate_cleanup_under_stripe_lock() -> None:
        with stripe_lock:
            entered_lock.set()
            release_lock.wait(timeout=5.0)
            session_file.unlink(missing_ok=True)
            with store._cache_guard:
                store._cache.pop(sid, None)

    bg_cleanup = asyncio.create_task(asyncio.to_thread(_simulate_cleanup_under_stripe_lock))
    await asyncio.to_thread(entered_lock.wait, 5.0)

    aget_task = asyncio.create_task(store.aget(sid))
    has_run_task = asyncio.create_task(asyncio.to_thread(store.has_run_id, sid, "run-race-001"))
    # 给冷读任务一点时间走到 _stripe_lock 等待处
    await asyncio.sleep(0.03)
    assert not aget_task.done()
    assert not has_run_task.done()

    release_lock.set()
    await bg_cleanup
    assert await aget_task is None
    assert await has_run_task is False
    assert sid not in store._cache
    assert store.get(sid) is None

    # 场景 2：冷读在等待分片锁期间若并发 save 写入了新快照，锁内二次检查缓存直接返回最新快照
    sid2 = session_id_for("u_race2", "ord_race2")
    await store.asave({"sessionId": sid2, "userId": "u_race2", "orderId": "ord_race2", "v": 1, "messages": []})
    store._cache.clear()

    stripe_lock2 = store._stripe_lock(sid2)
    entered2 = threading.Event()
    release2 = threading.Event()

    def _concurrent_writer() -> None:
        with stripe_lock2:
            entered2.set()
            release2.wait(timeout=5.0)
            with store._cache_guard:
                store._put_cache_locked(
                    sid2,
                    {"sessionId": sid2, "userId": "u_race2", "orderId": "ord_race2", "v": 2, "messages": []},
                )

    bg_writer = asyncio.create_task(asyncio.to_thread(_concurrent_writer))
    await asyncio.to_thread(entered2.wait, 5.0)
    cold_get_task = asyncio.create_task(store.aget(sid2))
    await asyncio.sleep(0.03)
    release2.set()
    await bg_writer
    loaded2 = await cold_get_task
    assert loaded2 is not None and loaded2["v"] == 2
