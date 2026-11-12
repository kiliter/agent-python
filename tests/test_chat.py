"""嵌入式聊天选模板窗口全链路测试（使用 FunctionModel 桩模型，不请求真实大模型）。

#Created By AiCoding(codex)
覆盖鉴权与草稿权限边界、会话恢复与入参指纹演进、自动推荐与 output_validator 自愈、
缺参拦截与补参运行、SSE 脱敏步骤与断点续接、单会话并发互斥与手动取消、
AI 改写与确认全分支（幂等 + 审计）、模板下线兼容及进程重启 INTERRUPTED 恢复。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from report_agent.api.auth import COOKIE_NAME, UserStore
from report_agent.chat.steps import StepMapper
from report_agent.chat.store import ChatStore, inputs_fingerprint, session_id_for
from report_agent.domain.template import ColumnDef, FieldDef, InputDef, Template, TemplateDef
from report_agent.main import create_app
from report_agent.runtime.workspace import ProcessEvent
from report_agent.store.fsutil import read_json, read_jsonl, write_json
from report_agent.store.layout import InvalidResource
from scripted_model import ORDER_SMS, build_report, scripted


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
        joined = "\n".join(data_lines)
        events.append({
            "id": evt_id,
            "event": evt_name,
            "data": json.loads(joined),
        })
    return events


def _is_chat_agent(info: AgentInfo) -> bool:
    """判断当前 FunctionModel 调用是否来自聊天路由 Agent（而非填报 AgentRunner）。"""
    return any(t.name == "submit_chat_action" for t in info.output_tools)


def _dual_model(chat_fn: Any = None, report_fn: Any = scripted) -> FunctionModel:
    """构造同时服务 ChatAgent 与 AgentRunner 的组合桩模型（支持同步或异步函数）。"""

    async def _dispatch(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        target = chat_fn if (_is_chat_agent(info) and chat_fn is not None) else report_fn
        res = target(messages, info)
        if inspect.isawaitable(res):
            return await res
        return res

    return FunctionModel(_dispatch, model_name="scripted-chat-dual")


@pytest.fixture
async def async_client(container):
    """带完整 FastAPI lifespan（含 RunStore 写协程与清理钩子）的异步测试客户端。"""
    UserStore(container.layout.config / "users.yaml").upsert(
        "chenxiaoyun", "pass-1234", "陈晓芸", "业务维护"
    )
    app = create_app(container=container)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as cl:
            yield cl


async def _flush_runs(container) -> None:
    """等待 RunStore 异步写队列把内存 _pending 记录刷入磁盘。"""
    for _ in range(100):
        if not container.runs._pending:
            break
        await asyncio.sleep(0.01)


async def _admin_login(cl: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    """执行管理端登录，返回 (Bearer 请求头, Cookie 令牌值)。"""
    r = await cl.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "pass-1234"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    cookie_val = r.cookies.get(COOKIE_NAME) or token
    # 清理客户端默认保存的会话 Cookie，便于后续显式按需测试无凭证 / API Key / Bearer / Cookie
    cl.cookies.clear()
    return {"Authorization": f"Bearer {token}"}, cookie_val


def test_chat_store_and_step_mapper_unit(tmp_path: Path):
    """单元验证 ChatStore（分片原子落盘、深拷贝防污染、路径穿越防护、过期清理）与 StepMapper 隐私脱敏。"""
    sid = session_id_for(" u_01 ", " ORD-100 ")
    assert sid == session_id_for("u_01", "ORD-100") and len(sid) == 32
    assert inputs_fingerprint({"a": " 1 ", "b": "2"}, "doc") == inputs_fingerprint({"b": "2", "a": "1"}, "doc")

    store = ChatStore(tmp_path / "chats", max_cache=4)
    assert store.get("../evil") is None
    with pytest.raises(InvalidResource):
        store.save({"sessionId": "../evil"})

    saved = store.save({"sessionId": sid, "userId": "u_01", "orderId": "ORD-100", "messages": [{"kind": "text"}]})
    saved["messages"].append({"kind": "mutated"})
    reloaded = store.get_by_pair("u_01", "ORD-100")
    assert reloaded is not None and len(reloaded["messages"]) == 1

    # 验证过期清理删除超期 JSON 与空分片目录
    json_file = tmp_path / "chats" / sid[:2] / f"{sid}.json"
    assert json_file.is_file()
    old_ts = time.time() - 10 * 86400
    os.utime(json_file, (old_ts, old_ts))
    assert store.cleanup(keep_days=7) == 1
    assert store.get(sid) is None and not json_file.parent.exists()

    # 验证 StepMapper 忽略内部模型思考事件，且错误文本掩码客户手机号与引号字面量
    mapper = StepMapper()
    assert mapper.feed(ProcessEvent(1, "model_request", 10, 1, {})) is None
    assert mapper.feed(ProcessEvent(2, "model_text", 20, 1, {"text": "内部推理"})) is None
    s1 = mapper.feed(ProcessEvent(3, "run_started", 30, 1, {"templateName": "业务办理争议类", "rev": "r1"}))
    assert s1 is not None and s1["seq"] == 1 and s1["icon"] == "start"
    s2 = mapper.feed(ProcessEvent(
        4,
        "tool",
        50,
        1,
        {
            "tool": "call_api",
            "ok": False,
            "args": {"name": "querySMSSendInfo"},
            "result": {"error": "号码 13900001234 报文 '<secret_payload>' 超时"},
        },
    ))
    assert s2 is not None and s2["seq"] == 2 and s2["ok"] is False
    assert "13900001234" not in s2["text"] and "secret_payload" not in s2["text"]


async def test_1_auth_and_draft_permission_boundaries(async_client: httpx.AsyncClient):
    """场景 1：鉴权与权限边界（无凭证 401、API Key 仅限 online、管理端 Bearer/Cookie 可用 online 与 draft）。"""
    base_body = {
        "userId": "u_auth",
        "orderId": "ORD_AUTH_01",
        "inputs": {"手机号码": "13900001234"},
        "document": "测试单据",
    }

    # 无凭证与错误 API Key 一律 401
    r_no_auth = await async_client.post("/api/v1/chat/sessions", json=base_body)
    assert r_no_auth.status_code == 401 and r_no_auth.json()["code"] == "INVALID_API_KEY"
    r_bad_key = await async_client.post(
        "/api/v1/chat/sessions",
        json=base_body,
        headers={"X-API-Key": "wrong-key"},
    )
    assert r_bad_key.status_code == 401

    # 有效 X-API-Key 访问 target="online" 返回 200，访问 target="draft" 返回 403
    key_headers = {"X-API-Key": "upstream-key"}
    r_key_online = await async_client.post(
        "/api/v1/chat/sessions",
        json={**base_body, "target": "online"},
        headers=key_headers,
    )
    assert r_key_online.status_code == 200, r_key_online.text
    assert r_key_online.json()["target"] == "online" and r_key_online.json()["created"] is True

    r_key_draft = await async_client.post(
        "/api/v1/chat/sessions",
        json={**base_body, "orderId": "ORD_AUTH_02", "target": "draft"},
        headers=key_headers,
    )
    assert r_key_draft.status_code == 403 and r_key_draft.json()["code"] == "DRAFT_FORBIDDEN"

    # 管理端登录：Bearer 与 Cookie 均可访问 online 和 draft
    bearer_headers, cookie_val = await _admin_login(async_client)
    for idx, tgt in enumerate(("online", "draft"), start=1):
        r_bearer = await async_client.post(
            "/api/v1/chat/sessions",
            json={**base_body, "orderId": f"ORD_BEARER_{idx}", "target": tgt},
            headers=bearer_headers,
        )
        assert r_bearer.status_code == 200, r_bearer.text
        assert r_bearer.json()["target"] == tgt

        r_cookie = await async_client.post(
            "/api/v1/chat/sessions",
            json={**base_body, "orderId": f"ORD_COOKIE_{idx}", "target": tgt},
            headers={"Cookie": f"{COOKIE_NAME}={cookie_val}"},
        )
        assert r_cookie.status_code == 200, r_cookie.text
        assert r_cookie.json()["target"] == tgt

    # 管理端用户同时携带有效 X-API-Key + Bearer token 访问 target="draft" 返回 200（模拟页带出系统 Key 场景）
    r_combo_draft = await async_client.post(
        "/api/v1/chat/sessions",
        json={**base_body, "orderId": "ORD_COMBO_DRAFT", "target": "draft"},
        headers={**bearer_headers, "X-API-Key": "upstream-key"},
    )
    assert r_combo_draft.status_code == 200, r_combo_draft.text
    assert r_combo_draft.json()["target"] == "draft"

    # 管理端用户同时携带错误 X-API-Key + Bearer token 返回 401（模拟页测试错误 Key 拦截场景）
    r_combo_bad_key = await async_client.post(
        "/api/v1/chat/sessions",
        json={**base_body, "orderId": "ORD_COMBO_BAD", "target": "draft"},
        headers={**bearer_headers, "X-API-Key": "wrong-key"},
    )
    assert r_combo_bad_key.status_code == 401 and r_combo_bad_key.json()["code"] == "INVALID_API_KEY"


async def test_2_session_restore_inputs_update_and_stale_marking(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 2：会话创建、恢复与入参更新（inputsVersion 递增、divider 消息、旧卡片 stale、保留未冲突用户补充入参）。"""
    key_headers = {"X-API-Key": "upstream-key"}
    upstream_inputs = {
        "手机号码": case_c01["inputs"]["手机号码"],
        "业务名称": case_c01["inputs"]["业务名称"],
        "创建时间": case_c01["inputs"]["创建时间"],
    }
    doc_v1 = case_c01["documentText"]

    # 1) 首次打开会话（不传可选的「业务月份」）
    s1 = (await async_client.post(
        "/api/v1/chat/sessions",
        json={"userId": "u_restore", "orderId": "ORD_2001", "inputs": upstream_inputs, "document": doc_v1},
        headers=key_headers,
    )).json()
    sid = s1["sessionId"]
    assert s1["created"] is True and s1["inputsChanged"] is False and s1["inputsVersion"] == 1
    assert "document" not in s1 and s1["documentChars"] == len(doc_v1)
    assert s1["inputSources"] == {"手机号码": "上层", "业务名称": "上层", "创建时间": "上层"}

    # 2) 用户补充「业务月份」并执行一次运行，生成一张历史 run 卡片
    r_run = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001, "inputs": {"业务月份": "20261105"}},
        headers=key_headers,
    )
    assert r_run.status_code == 200, r_run.text
    run_id = r_run.json()["message"]["runId"]

    ev_resp = await async_client.get(f"/api/v1/chat/runs/{run_id}/events?after=0", headers=key_headers)
    ev_list = _parse_sse(ev_resp.text)
    assert ev_list[-1]["event"] == "final" and ev_list[-1]["data"]["status"] == "SUCCESS"

    # 3) 同一 (userId, orderId) 且相同入参+单据再次打开：恢复原会话，指纹未变
    s2 = (await async_client.post(
        "/api/v1/chat/sessions",
        json={"userId": "u_restore", "orderId": "ORD_2001", "inputs": upstream_inputs, "document": doc_v1},
        headers=key_headers,
    )).json()
    assert s2["sessionId"] == sid
    assert s2["created"] is False and s2["inputsChanged"] is False and s2["inputsVersion"] == 1
    old_card_before = next(m for m in s2["messages"] if m["kind"] == "run" and m["runId"] == run_id)
    assert old_card_before["stale"] is False
    assert s2["inputs"]["业务月份"] == "20261105" and s2["inputSources"]["业务月份"] == "用户补充"

    # 4) 上层修改单据正文（或入参）后再次调用 POST /sessions（仍未传「业务月份」）
    doc_v2 = doc_v1 + "\n补充备注：客户二次进线核实"
    s3 = (await async_client.post(
        "/api/v1/chat/sessions",
        json={"userId": "u_restore", "orderId": "ORD_2001", "inputs": upstream_inputs, "document": doc_v2},
        headers=key_headers,
    )).json()
    assert s3["sessionId"] == sid
    assert s3["created"] is False and s3["inputsChanged"] is True and s3["inputsVersion"] == 2
    assert any(m["kind"] == "divider" for m in s3["messages"])
    old_card_after = next(m for m in s3["messages"] if m["kind"] == "run" and m["runId"] == run_id)
    assert old_card_after["stale"] is True
    # 之前「用户补充」的未冲突入参必须保留
    assert s3["inputs"]["业务月份"] == "20261105"
    assert s3["inputSources"]["业务月份"] == "用户补充"
    assert s3["inputSources"]["手机号码"] == "上层"


async def test_3_auto_recommend_validator_self_healing_and_missing_required(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 3：自动推荐与 output_validator 自愈（首次推荐不存在的 9999 触发 ModelRetry，修正为 1001 并计算 missingRequired）。"""
    key_headers = {"X-API-Key": "upstream-key"}
    retry_feedbacks: list[str] = []
    call_steps: list[int] = []

    def chat_recommend_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step = sum(1 for m in messages if isinstance(m, ModelResponse))
        call_steps.append(step)
        for m in messages:
            if isinstance(m, ModelRequest):
                for p in m.parts:
                    if isinstance(p, RetryPromptPart):
                        retry_feedbacks.append(p.model_response())
                    elif isinstance(p, ToolReturnPart) and p.tool_name == "submit_chat_action":
                        retry_feedbacks.append(str(p.content))
        if step == 0:
            # 先调用只读工具验证路由助手工具链正常
            return ModelResponse(parts=[
                ToolCallPart("load_skill", {"name": "template-router"}),
                ToolCallPart("list_templates", {"keyword": "业务办理"}),
            ])
        if step == 1:
            # 故意返回不存在的 templateId: 9999 触发 @agent.output_validator ModelRetry
            return ModelResponse(parts=[
                ToolCallPart("submit_chat_action", {
                    "action": "recommend",
                    "text": "为您推荐匹配模板：",
                    "recommendations": [
                        {"templateId": 9999, "reason": "幻觉不存在的模板", "level": "高"},
                    ],
                })
            ])
        # 第 2 次提交合法的 templateId: 1001（附重复项验证自动去重）
        return ModelResponse(parts=[
            ToolCallPart("submit_chat_action", {
                "action": "recommend",
                "text": "根据套餐办理受理单，推荐业务办理争议类模板：",
                "recommendations": [
                    {"templateId": 1001, "reason": "单据为套餐办理受理单", "level": "高"},
                    {"templateId": 1001, "reason": "重复候选应被去重", "level": "低"},
                ],
            })
        ])

    container.runner.model = _dual_model(chat_fn=chat_recommend_stub)

    # 故意缺少必填入参「创建时间」
    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_rec",
            "orderId": "ORD_REC_01",
            "inputs": {"手机号码": "13900001234", "业务名称": "5G智享套餐（个人版）"},
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid = sess["sessionId"]

    msg_resp = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        json={"text": "", "auto": True},
        headers=key_headers,
    )
    assert msg_resp.status_code == 200, msg_resp.text
    frames = _parse_sse(msg_resp.text)

    # 验证触发过 ModelRetry 且提示了无效编号 9999 与合法在线编号 1001
    assert call_steps == [0, 1, 2]
    assert any("9999" in rp and "1001" in rp for rp in retry_feedbacks), retry_feedbacks

    # auto=True 不应产生 user 文本消息；SSE 包含 status、recommend message 与 done
    event_kinds = [f["event"] for f in frames]
    assert "status" in event_kinds and event_kinds[-1] == "done"
    msg_frames = [f["data"] for f in frames if f["event"] == "message"]
    assert all(m["role"] != "user" for m in msg_frames)
    rec_msg = next(m for m in msg_frames if m["kind"] == "recommend")
    assert len(rec_msg["items"]) == 1
    item = rec_msg["items"][0]
    assert item["templateId"] == 1001
    assert item["templateName"] == "业务办理争议类"
    assert item["level"] == "高"
    assert item["offline"] is False
    assert item["missingRequired"] == ["创建时间"]

    # 验证换模板接口将已推荐模板排前并带上 recommendLevel
    tpls = (await async_client.get(f"/api/v1/chat/sessions/{sid}/templates", headers=key_headers)).json()
    assert tpls[0]["templateId"] == 1001 and tpls[0]["recommendLevel"] == "高"


async def test_4_missing_params_intercept_run_sse_resume_and_entry(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 4：缺参/正则拦截返回 ask_params，补参启动运行、SSE 友好步骤与断点续接，RunStore 记录 entry='聊天窗口'。"""
    bearer_headers, _ = await _admin_login(async_client)
    key_headers = {"X-API-Key": "upstream-key"}

    # 给模板 1001 新增一个带正则的必填入参「工单流水号」并发布上线为 r2
    tpl_detail = (await async_client.get("/api/v1/templates/1001", headers=bearer_headers)).json()
    new_inputs = list(tpl_detail["inputs"]) + [{
        "key": "工单流水号",
        "required": True,
        "pattern": r"^WO-\d{4}$",
        "description": "工单号，格式 WO-四位数字",
        "sample": "WO-1024",
    }]
    r_draft = await async_client.put(
        "/api/v1/templates/1001/draft",
        headers=bearer_headers,
        json={"inputs": new_inputs},
    )
    assert r_draft.status_code == 200, r_draft.text
    r_pub = await async_client.post(
        "/api/v1/templates/1001/publish",
        headers=bearer_headers,
        json={"note": "新增必填正则入参工单流水号"},
    )
    assert r_pub.status_code == 200, r_pub.text

    # 创建会话：故意缺失「工单流水号」且「手机号码」格式不合法
    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_run",
            "orderId": "ORD_RUN_01",
            "inputs": {
                "手机号码": "12345",
                "业务名称": case_c01["inputs"]["业务名称"],
                "创建时间": case_c01["inputs"]["创建时间"],
            },
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid = sess["sessionId"]

    # 1) 缺参/格式错误时调用 POST /runs：返回 ask_params 卡片而不启动后台运行
    r_ask = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001, "inputs": {"工单流水号": "BAD"}},
        headers=key_headers,
    )
    assert r_ask.status_code == 200, r_ask.text
    ask_payload = r_ask.json()
    assert ask_payload["message"]["kind"] == "ask_params"
    assert ask_payload["session"]["activeRunId"] is None
    err_by_key = {p["key"]: p["error"] for p in ask_payload["message"]["params"]}
    assert err_by_key["手机号码"] is not None
    assert err_by_key["工单流水号"] is not None
    assert container.runs.list() == []

    # 2) 携带合规补充参数再次调用 POST /runs：返回 RUNNING 的 run 卡片
    r_start = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={
            "templateId": 1001,
            "inputs": {
                "手机号码": case_c01["inputs"]["手机号码"],
                "业务月份": case_c01["inputs"]["业务月份"],
                "工单流水号": "WO-2026",
            },
        },
        headers=key_headers,
    )
    assert r_start.status_code == 200, r_start.text
    run_msg = r_start.json()["message"]
    assert run_msg["kind"] == "run" and run_msg["status"] == "RUNNING"
    run_id = run_msg["runId"]

    # 3) 订阅 GET /runs/{runId}/events?after=0，校验友好脱敏 step 与 final
    ev_all_resp = await async_client.get(f"/api/v1/chat/runs/{run_id}/events?after=0", headers=key_headers)
    assert ev_all_resp.status_code == 200
    all_frames = _parse_sse(ev_all_resp.text)
    step_frames = [f for f in all_frames if f["event"] == "step"]
    final_frames = [f for f in all_frames if f["event"] == "final"]
    assert len(step_frames) >= 5 and len(final_frames) == 1

    seqs = [f["data"]["seq"] for f in step_frames]
    assert seqs == list(range(1, len(step_frames) + 1))
    assert [int(f["id"]) for f in step_frames] == seqs
    step_texts = "\n".join(f["data"]["text"] for f in step_frames)
    assert "开始填写「业务办理争议类」" in step_texts
    assert "查询「短信发送记录查询」" in step_texts
    assert "报告生成完成" in step_texts
    # 严禁在步骤文本中泄露客户手机号或原始短信正文
    assert "13900001234" not in step_texts and "JS2026110500321" not in step_texts

    final_card = final_frames[0]["data"]
    assert final_card["status"] == "SUCCESS"
    assert len(final_card["versions"]) == 1 and final_card["versions"][0]["kind"] == "original"

    # 4) 验证 ?after=2 与 Last-Event-ID 请求头断点续接
    ev_after2 = _parse_sse(
        (await async_client.get(f"/api/v1/chat/runs/{run_id}/events?after=2", headers=key_headers)).text
    )
    seqs_after2 = [f["data"]["seq"] for f in ev_after2 if f["event"] == "step"]
    assert seqs_after2 == [s for s in seqs if s > 2]
    assert ev_after2[-1]["event"] == "final"

    ev_last_id = _parse_sse((await async_client.get(
        f"/api/v1/chat/runs/{run_id}/events?after=1",
        headers={**key_headers, "Last-Event-ID": "3"},
    )).text)
    seqs_last_id = [f["data"]["seq"] for f in ev_last_id if f["event"] == "step"]
    assert seqs_last_id == [s for s in seqs if s > 3]
    assert ev_last_id[-1]["event"] == "final"

    # 5) 验证 RunStore 中落盘的运行记录 entry == "聊天窗口"
    await _flush_runs(container)
    summaries = container.runs.list()
    matched_summary = next((s for s in summaries if s["runId"] == run_id), None)
    assert matched_summary is not None and matched_summary["entry"] == "聊天窗口"
    detail = container.runs.get(run_id)
    assert detail is not None and detail["entry"] == "聊天窗口" and detail["status"] == "SUCCESS"


async def test_5_single_session_concurrency_mutex_and_manual_cancel(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 5：单会话并发互斥（409 RUN_IN_PROGRESS）与手动取消（CANCELLED + RunStore 落盘记录）。"""
    key_headers = {"X-API-Key": "upstream-key"}
    entered = asyncio.Event()
    never_finish = asyncio.Event()

    async def slow_report_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        entered.set()
        await never_finish.wait()
        return ModelResponse(parts=[])

    container.runner.model = _dual_model(report_fn=slow_report_stub)

    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_cancel",
            "orderId": "ORD_CANCEL_01",
            "inputs": case_c01["inputs"],
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid = sess["sessionId"]

    r1 = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )
    assert r1.status_code == 200, r1.text
    run_id = r1.json()["message"]["runId"]
    await asyncio.wait_for(entered.wait(), timeout=5.0)

    # 运行进行中再次发起运行 -> 409 RUN_IN_PROGRESS
    r2 = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )
    assert r2.status_code == 409 and r2.json()["code"] == "RUN_IN_PROGRESS"

    # 手动取消运行
    r_cancel = await async_client.post(f"/api/v1/chat/runs/{run_id}/cancel", headers=key_headers)
    assert r_cancel.status_code == 200 and r_cancel.json()["ok"] is True

    # 订阅事件流确认终态为 CANCELLED
    ev_frames = _parse_sse(
        (await async_client.get(f"/api/v1/chat/runs/{run_id}/events?after=0", headers=key_headers)).text
    )
    assert ev_frames[-1]["event"] == "final"
    assert ev_frames[-1]["data"]["status"] == "CANCELLED"

    sess_after = (await async_client.get(f"/api/v1/chat/sessions/{sid}", headers=key_headers)).json()
    assert sess_after["activeRunId"] is None
    card = next(m for m in sess_after["messages"] if m["kind"] == "run" and m["runId"] == run_id)
    assert card["status"] == "CANCELLED"

    # 验证 RunStore 仍然记录了该次取消运行
    await _flush_runs(container)
    cancel_detail = container.runs.get(run_id)
    assert cancel_detail is not None
    assert cancel_detail["entry"] == "聊天窗口"
    assert "取消" in (cancel_detail.get("error") or "")


async def test_6_rewrite_and_confirm_all_branches_idempotency_and_audit(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 6：AI 改写与确认全分支（FAILED/CANCELLED 400、PARTIAL 409/ack、rewrite 追加版本、人工微调幂等确认与审计）。"""
    key_headers = {"X-API-Key": "upstream-key"}

    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_confirm",
            "orderId": "ORD_CONF_01",
            "inputs": case_c01["inputs"],
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid = sess["sessionId"]

    # 6.1 CANCELLED 运行调用 confirm 返回 400 NOT_CONFIRMABLE
    entered_cancel = asyncio.Event()
    hold_cancel = asyncio.Event()

    async def hang_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        entered_cancel.set()
        await hold_cancel.wait()
        return ModelResponse(parts=[])

    container.runner.model = _dual_model(report_fn=hang_stub)
    cancelled_rid = (await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )).json()["message"]["runId"]
    await asyncio.wait_for(entered_cancel.wait(), timeout=5.0)
    await async_client.post(f"/api/v1/chat/runs/{cancelled_rid}/cancel", headers=key_headers)
    await async_client.get(f"/api/v1/chat/runs/{cancelled_rid}/events?after=0", headers=key_headers)

    r_conf_cancelled = await async_client.post(
        f"/api/v1/chat/runs/{cancelled_rid}/confirm",
        json={"markdown": "x"},
        headers=key_headers,
    )
    assert r_conf_cancelled.status_code == 400 and r_conf_cancelled.json()["code"] == "NOT_CONFIRMABLE"

    # 6.2 FAILED 运行调用 confirm 返回 400 NOT_CONFIRMABLE
    def fail_report_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise RuntimeError("模拟底层模型异常")

    container.runner.model = _dual_model(report_fn=fail_report_stub)
    failed_rid = (await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )).json()["message"]["runId"]
    failed_frames = _parse_sse(
        (await async_client.get(f"/api/v1/chat/runs/{failed_rid}/events?after=0", headers=key_headers)).text
    )
    assert failed_frames[-1]["data"]["status"] == "FAILED"

    r_conf_failed = await async_client.post(
        f"/api/v1/chat/runs/{failed_rid}/confirm",
        json={"markdown": "x"},
        headers=key_headers,
    )
    assert r_conf_failed.status_code == 400 and r_conf_failed.json()["code"] == "NOT_CONFIRMABLE"

    # 6.3 PARTIAL 运行：未传 acknowledgePartial=True 返回 409 PARTIAL_NEEDS_ACK（含 missingShown），传后确认成功
    def partial_report_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step = sum(1 for m in messages if isinstance(m, ModelResponse))
        if step == 0:
            return ModelResponse(parts=[ToolCallPart("call_api", {
                "name": "querySMSSendInfo",
                "args": {
                    "手机号码": "13900001234",
                    "开始时间": "20261105000000",
                    "结束时间": "20261105235959",
                },
            })])
        if step == 1:
            return ModelResponse(parts=[ToolCallPart("format_date", {
                "value": "20261105",
                "fromPattern": "yyyyMMdd",
                "toPattern": "yyyy年M月d号",
            })])
        date_call = next(
            p.content["callId"]
            for m in messages
            for p in getattr(m, "parts", [])
            if isinstance(p, ToolReturnPart) and p.tool_name == "format_date"
        )
        rep = build_report(ORDER_SMS, date_call)
        # 将可见字段「鉴权方式」设为 not_found，触发 PARTIAL
        rep["鉴权方式"] = {"status": "not_found", "value": None, "evidence": [], "reasoning": "单据未记录鉴权方式"}
        return ModelResponse(parts=[ToolCallPart("submit_report", rep)])

    rewritten_md = "服务争议点1:业务办理争议类\n\n经核查，客户通过热线渠道办理5G智享套餐（个人版），已下发确认与告知短信。"
    inspect_seen: dict[str, Any] = {}

    def chat_rewrite_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step = sum(1 for m in messages if isinstance(m, ModelResponse))
        if step == 0:
            return ModelResponse(parts=[ToolCallPart("get_run_result", {"runId": partial_rid})])
        for m in messages:
            for p in getattr(m, "parts", []):
                if isinstance(p, ToolReturnPart) and p.tool_name == "get_run_result":
                    inspect_seen["result"] = p.content
        return ModelResponse(parts=[ToolCallPart("submit_chat_action", {
            "action": "rewrite",
            "runId": partial_rid,
            "text": "已按要求为您精简润色报告正文（请注意改写版未经证据校验）：",
            "markdown": rewritten_md,
        })])

    container.runner.model = _dual_model(chat_fn=chat_rewrite_stub, report_fn=partial_report_stub)
    partial_rid = (await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )).json()["message"]["runId"]
    partial_frames = _parse_sse(
        (await async_client.get(f"/api/v1/chat/runs/{partial_rid}/events?after=0", headers=key_headers)).text
    )
    partial_card = partial_frames[-1]["data"]
    assert partial_card["status"] == "PARTIAL"
    assert "鉴权方式" in partial_card["missingShown"]
    await _flush_runs(container)

    # 未传 acknowledgePartial -> 409 PARTIAL_NEEDS_ACK
    r_need_ack = await async_client.post(
        f"/api/v1/chat/runs/{partial_rid}/confirm",
        json={"markdown": partial_card["versions"][0]["markdown"]},
        headers=key_headers,
    )
    assert r_need_ack.status_code == 409
    ack_err = r_need_ack.json()
    assert ack_err["code"] == "PARTIAL_NEEDS_ACK" and "鉴权方式" in ack_err["missingShown"]

    # 传 acknowledgePartial=True -> 首次确认原版成功（edited=False, rewritten=False）
    r_ack_ok = await async_client.post(
        f"/api/v1/chat/runs/{partial_rid}/confirm",
        json={"markdown": partial_card["versions"][0]["markdown"], "acknowledgePartial": True},
        headers=key_headers,
    )
    assert r_ack_ok.status_code == 200, r_ack_ok.text
    assert r_ack_ok.json()["payload"]["edited"] is False
    assert r_ack_ok.json()["payload"]["rewritten"] is False
    ack_ok_card = next(
        m for m in r_ack_ok.json()["session"]["messages"] if m["kind"] == "run" and m["runId"] == partial_rid
    )
    assert ack_ok_card["confirmed"] is True

    # 6.4 通过 messages 触发 AI rewrite，验证卡片新增 kind=="rewrite" 版本、复位 confirmed=False，且助手文本回复携带 rewriteRunId / rewriteVersionNo
    rw_resp = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        json={"text": "请把生成的报告精简一下措辞", "auto": False},
        headers=key_headers,
    )
    assert rw_resp.status_code == 200, rw_resp.text
    assert inspect_seen["result"]["ok"] is True and "鉴权方式" in inspect_seen["result"]["missingShown"]

    rw_frames = _parse_sse(rw_resp.text)
    updated_cards = [
        f["data"] for f in rw_frames
        if f["event"] == "message" and f["data"].get("kind") == "run" and f["data"].get("runId") == partial_rid
    ]
    assert len(updated_cards) == 1
    assert updated_cards[0]["confirmed"] is False
    versions = updated_cards[0]["versions"]
    assert len(versions) == 2
    assert versions[0]["kind"] == "original" and versions[1]["kind"] == "rewrite"
    assert versions[1]["markdown"] == rewritten_md

    rw_assistant_msgs = [
        f["data"] for f in rw_frames
        if f["event"] == "message" and f["data"].get("kind") == "text" and f["data"].get("role") == "assistant"
    ]
    assert len(rw_assistant_msgs) == 1
    rw_msg_id = rw_assistant_msgs[0]["id"]
    assert rw_assistant_msgs[0]["rewriteRunId"] == partial_rid
    assert rw_assistant_msgs[0]["rewriteVersionNo"] == 2

    done_session = rw_frames[-1]["data"]["session"]
    assert done_session["confirmed"]["runId"] == partial_rid
    assert done_session["confirmed"]["rewritten"] is False
    sess_after_rw = (await async_client.get(f"/api/v1/chat/sessions/{sid}", headers=key_headers)).json()
    sess_rw_msg = next(m for m in sess_after_rw["messages"] if m["id"] == rw_msg_id)
    assert sess_rw_msg["rewriteRunId"] == partial_rid
    assert sess_rw_msg["rewriteVersionNo"] == 2
    sess_rw_card = next(m for m in sess_after_rw["messages"] if m["kind"] == "run" and m["runId"] == partial_rid)
    assert sess_rw_card["confirmed"] is False

    # 6.5 在 rewrite 版本基础上人工微调 markdown 后提交确认：edited=True, rewritten=True，重复调用幂等，记入 audit.jsonl
    manually_edited_md = rewritten_md + "\n（坐席人工补充核实无误）"
    r_conf_1 = await async_client.post(
        f"/api/v1/chat/runs/{partial_rid}/confirm",
        json={"markdown": manually_edited_md, "acknowledgePartial": True},
        headers=key_headers,
    )
    assert r_conf_1.status_code == 200, r_conf_1.text
    body_1 = r_conf_1.json()
    payload_1 = body_1["payload"]
    assert payload_1 == {
        "type": "report-confirmed",
        "userId": "u_confirm",
        "orderId": "ORD_CONF_01",
        "templateId": 1001,
        "templateName": "业务办理争议类",
        "runId": partial_rid,
        "status": "PARTIAL",
        "markdown": manually_edited_md,
        "edited": True,
        "rewritten": True,
    }
    conf_1_card = next(m for m in body_1["session"]["messages"] if m["kind"] == "run" and m["runId"] == partial_rid)
    assert conf_1_card["confirmed"] is True
    confirmed_msgs_1 = [m for m in body_1["session"]["messages"] if m["kind"] == "confirmed"]
    audit_count_1 = sum(
        1 for row in read_jsonl(container.layout.audit)
        if row.get("action") == "chat-confirm" and row.get("runId") == partial_rid
    )
    assert audit_count_1 == 2  # 首次原版确认 1 条 + 改写微调确认 1 条

    # 相同 markdown 重复调用 confirm：保持幂等，不重复追加 confirmed 消息与审计记录
    r_conf_2 = await async_client.post(
        f"/api/v1/chat/runs/{partial_rid}/confirm",
        json={"markdown": manually_edited_md, "acknowledgePartial": True},
        headers=key_headers,
    )
    assert r_conf_2.status_code == 200
    body_2 = r_conf_2.json()
    assert body_2["payload"] == payload_1
    confirmed_msgs_2 = [m for m in body_2["session"]["messages"] if m["kind"] == "confirmed"]
    assert len(confirmed_msgs_2) == len(confirmed_msgs_1)
    audit_rows = [
        row for row in read_jsonl(container.layout.audit)
        if row.get("action") == "chat-confirm" and row.get("runId") == partial_rid
    ]
    assert len(audit_rows) == audit_count_1
    assert audit_rows[-1]["edited"] is True and audit_rows[-1]["rewritten"] is True

    # 6.6 历史存量会话自动兼容补全：剥离磁盘上的 rewriteRunId/rewriteVersionNo，验证 _build_view 一对一补全且不误绑普通问答消息
    session_file = container.layout.chats / sid[:2] / f"{sid}.json"
    raw_session = read_json(session_file)
    assert isinstance(raw_session, dict)
    raw_rw_msg = next(m for m in raw_session["messages"] if m.get("id") == rw_msg_id)
    raw_rw_msg.pop("rewriteRunId", None)
    raw_rw_msg.pop("rewriteVersionNo", None)
    v2_ts = raw_rw_msg["createdAt"]

    # 插入同秒普通答疑消息 + 引用 runId 的后续答疑消息，以及一条间隔超 5 秒但含 runId 的旧改写消息（对应 v3）
    raw_card = next(
        m for m in raw_session["messages"] if m.get("kind") == "run" and m.get("runId") == partial_rid
    )
    raw_card["versions"].append({
        "no": 3,
        "kind": "rewrite",
        "markdown": rewritten_md + "\n（二次温和客服口径）",
        "createdAt": "2099-01-01T10:00:00+08:00",
        "note": "AI 按对话要求改写（未经证据校验）",
    })
    raw_session["messages"].extend([
        {
            "id": "m_legacy_qa_user",
            "role": "user",
            "kind": "text",
            "createdAt": v2_ts,
            "text": "为什么鉴权方式没有查到？",
        },
        {
            "id": "m_legacy_qa_1",
            "role": "assistant",
            "kind": "text",
            "createdAt": v2_ts,
            "text": "「鉴权方式」未查到是因为当前工单单据未记录鉴权方式。",
        },
        {
            "id": "m_legacy_rw_v3",
            "role": "assistant",
            "kind": "text",
            "createdAt": "2099-01-01T10:00:30+08:00",
            "text": f"已为运行 {partial_rid} 生成二次温和客服回复版本：",
        },
        {
            "id": "m_legacy_qa_2",
            "role": "assistant",
            "kind": "text",
            "createdAt": "2099-01-01T10:01:00+08:00",
            "text": f"补充说明：{partial_rid} 的其余可见核查字段均已找到。",
        },
    ])
    write_json(session_file, raw_session)
    container.chat.store._cache.clear()

    legacy_view = (await async_client.get(f"/api/v1/chat/sessions/{sid}", headers=key_headers)).json()
    by_id = {m["id"]: m for m in legacy_view["messages"]}
    assert by_id[rw_msg_id]["rewriteRunId"] == partial_rid
    assert by_id[rw_msg_id]["rewriteVersionNo"] == 2
    assert by_id["m_legacy_rw_v3"]["rewriteRunId"] == partial_rid
    assert by_id["m_legacy_rw_v3"]["rewriteVersionNo"] == 3
    assert "rewriteRunId" not in by_id["m_legacy_qa_1"] and "rewriteVersionNo" not in by_id["m_legacy_qa_1"]
    assert "rewriteRunId" not in by_id["m_legacy_qa_2"] and "rewriteVersionNo" not in by_id["m_legacy_qa_2"]


async def test_7_template_offline_and_restart_interrupted_recovery(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 7：模板下线后历史卡片 templateOffline=True 仍可确认但禁重跑（404）；遗留 RUNNING 卡片自动恢复为 INTERRUPTED。"""
    bearer_headers, _ = await _admin_login(async_client)
    key_headers = {"X-API-Key": "upstream-key"}

    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_offline",
            "orderId": "ORD_OFF_01",
            "inputs": case_c01["inputs"],
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid = sess["sessionId"]

    # 先跑出一条模板 1001 的成功历史卡片
    run_id = (await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )).json()["message"]["runId"]
    frames = _parse_sse(
        (await async_client.get(f"/api/v1/chat/runs/{run_id}/events?after=0", headers=key_headers)).text
    )
    orig_md = frames[-1]["data"]["versions"][0]["markdown"]

    # 管理端将模板 1001 下线
    r_off = await async_client.post(
        "/api/v1/templates/1001/offline",
        headers=bearer_headers,
        json={"reason": "模板停用下线测试"},
    )
    assert r_off.status_code == 200, r_off.text

    # 1) 查看会话：历史卡片标记 templateOffline == True
    sess_view = (await async_client.get(f"/api/v1/chat/sessions/{sid}", headers=key_headers)).json()
    hist_card = next(m for m in sess_view["messages"] if m["kind"] == "run" and m["runId"] == run_id)
    assert hist_card["templateOffline"] is True

    # 2) 已下线模板的历史成功卡片仍然允许 confirm
    r_conf = await async_client.post(
        f"/api/v1/chat/runs/{run_id}/confirm",
        json={"markdown": orig_md},
        headers=key_headers,
    )
    assert r_conf.status_code == 200, r_conf.text
    assert r_conf.json()["payload"]["type"] == "report-confirmed"

    # 3) 再次尝试运行已下线模板返回 404 TEMPLATE_UNAVAILABLE
    r_rerun = await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )
    assert r_rerun.status_code == 404 and r_rerun.json()["code"] == "TEMPLATE_UNAVAILABLE"

    # 4) 模拟会话 JSON 文件中遗留一条 status == "RUNNING" 且不在 ChatRunManager 中的孤儿卡片
    session_file = container.layout.chats / sid[:2] / f"{sid}.json"
    raw_session = read_json(session_file)
    assert isinstance(raw_session, dict)
    orphan_run_id = "20261112093000000orphan1"
    raw_session["messages"].append({
        "id": f"m_run_{orphan_run_id}",
        "role": "assistant",
        "kind": "run",
        "createdAt": "2026-11-12T09:30:00+08:00",
        "runId": orphan_run_id,
        "templateId": 1001,
        "templateName": "业务办理争议类",
        "status": "RUNNING",
        "rev": "r1",
        "inputsVersion": 1,
        "stale": False,
        "templateOffline": False,
        "steps": [{"seq": 1, "atMs": 12, "icon": "start", "text": "开始填写「业务办理争议类」（版本 r1）", "ok": True}],
        "durationMs": 0,
        "error": None,
        "missingShown": [],
        "foundCount": 0,
        "totalCount": 17,
        "versions": [],
        "confirmed": False,
    })
    write_json(session_file, raw_session)
    # 清空内存缓存以真实模拟服务进程重启后首次从磁盘加载会话
    container.chat.store._cache.clear()

    recovered_view = (await async_client.get(f"/api/v1/chat/sessions/{sid}", headers=key_headers)).json()
    assert recovered_view["activeRunId"] is None
    orphan_card = next(m for m in recovered_view["messages"] if m["kind"] == "run" and m["runId"] == orphan_run_id)
    assert orphan_card["status"] == "INTERRUPTED"
    assert orphan_card["error"]

    # 验证磁盘文件也已同步持久化为 INTERRUPTED，且调用 confirm 返回 400 NOT_CONFIRMABLE
    persisted_after = read_json(session_file)
    persisted_orphan = next(
        m for m in persisted_after["messages"] if m.get("kind") == "run" and m.get("runId") == orphan_run_id
    )
    assert persisted_orphan["status"] == "INTERRUPTED"
    r_conf_interrupted = await async_client.post(
        f"/api/v1/chat/runs/{orphan_run_id}/confirm",
        json={"markdown": "x"},
        headers=key_headers,
    )
    assert r_conf_interrupted.status_code == 400 and r_conf_interrupted.json()["code"] == "NOT_CONFIRMABLE"


async def test_8_template_preview_enum_list_offline_and_404(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 8：模板结构与样例预览（枚举分支、列表行占位、Java 规则后缀剥离、已下线可预览、404 与 draft 权限）。"""
    bearer_headers, _ = await _admin_login(async_client)
    key_headers = {"X-API-Key": "upstream-key"}

    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_preview",
            "orderId": "ORD_PREV_01",
            "inputs": {"手机号码": "13900001234", "业务名称": "5G智享套餐（个人版）"},
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid = sess["sessionId"]

    # 1) 预览内置在线模板 1001：验证枚举分支渲染、currentValue 带出、仅返回 visible=True 字段
    r_prev_1001 = await async_client.get(
        f"/api/v1/chat/sessions/{sid}/templates/1001",
        headers=key_headers,
    )
    assert r_prev_1001.status_code == 200, r_prev_1001.text
    p1001 = r_prev_1001.json()
    assert p1001["templateId"] == 1001
    assert p1001["templateName"] == "业务办理争议类"
    assert p1001["offline"] is False
    assert p1001["rev"] == "r1"
    assert "{% if 争议类型 == \"业务\" %}" in p1001["bodyText"]
    # 枚举中间字段「争议类型」取首项 "业务"、「受理渠道」取首项 "热线"，两个条件段落均真实渲染而非空白
    assert "经核查，客户号码办理业务/套餐如下：" in p1001["sampleMarkdown"]
    assert "本次业务通过短信回复确认方式确认办理" in p1001["sampleMarkdown"]
    assert "【鉴权方式】" in p1001["sampleMarkdown"]
    inp_by_key = {inp["key"]: inp for inp in p1001["inputs"]}
    assert inp_by_key["手机号码"]["currentValue"] == "13900001234"
    assert inp_by_key["创建时间"]["currentValue"] == ""
    field_names = [f["name"] for f in p1001["fields"]]
    assert "鉴权方式" in field_names and "是否录音" in field_names
    assert "受理渠道" not in field_names and "争议类型" not in field_names and "受理网点" not in field_names

    # 2) 新建含 list 字段（枚举列 + 文本列）、defaultValue 与 Java 历史规则注释的模板 1002 并发布
    list_tpl = Template(
        definition=TemplateDef(
            id=1002,
            name="充值流水核查类",
            description="核查多笔充值与账单提醒记录",
            inputs=[
                InputDef(key="手机号码", required=True, pattern=r"^1\d{10}$", description="客户号码", sample="13900001234"),
            ],
            fields=[
                FieldDef(
                    name="结果判定",
                    visible=False,
                    type="enum",
                    values=["有记录", "无记录"],
                    evidence="derive",
                    whenMissing="value",
                    defaultValue="无记录",
                    description="中间枚举控制分支",
                ),
                FieldDef(
                    name="核查备注",
                    visible=True,
                    type="string",
                    evidence="derive",
                    whenMissing="value",
                    defaultValue="账务核对一致",
                    description="补充核查结论。\n\n原规则（Java）：Groovy demo script line",
                ),
                FieldDef(
                    name="充值流水",
                    visible=True,
                    type="list",
                    evidence="quote",
                    whenMissing="empty",
                    columns=[
                        ColumnDef(name="渠道类型", type="enum", values=["线上", "营业厅"]),
                        ColumnDef(name="充值金额", type="string"),
                    ],
                    description="逐笔列出充值记录\n原规则（Java）：QryBalance.groovy",
                ),
            ],
        ),
        body=(
            "服务争议点1:充值流水核查类\n"
            "{% if 结果判定 == '有记录' %}\n"
            "{% for row in 充值流水 %}\n"
            "- 渠道：{{row.渠道类型}}，金额：{{row.充值金额}}\n"
            "{% endfor %}\n"
            "{% endif %}\n"
            "结论：{{核查备注}}\n"
        ),
    )
    container.service.save_template(list_tpl, "chenxiaoyun", action="create")

    # 草稿会话（target='draft'）可预览尚未发布的 1002，且纯 X-API-Key 访问该会话模板预览返回 403
    draft_sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={"userId": "u_preview_draft", "orderId": "ORD_PREV_DRAFT", "inputs": {}, "document": "", "target": "draft"},
        headers=bearer_headers,
    )).json()
    draft_sid = draft_sess["sessionId"]
    r_forbidden = await async_client.get(
        f"/api/v1/chat/sessions/{draft_sid}/templates/1002",
        headers=key_headers,
    )
    assert r_forbidden.status_code == 403 and r_forbidden.json()["code"] == "DRAFT_FORBIDDEN"

    r_draft_prev = await async_client.get(
        f"/api/v1/chat/sessions/{draft_sid}/templates/1002",
        headers=bearer_headers,
    )
    assert r_draft_prev.status_code == 200, r_draft_prev.text
    p1002_draft = r_draft_prev.json()
    assert "+草稿" in p1002_draft["rev"]
    assert "- 渠道：线上，金额：【充值金额】" in p1002_draft["sampleMarkdown"]
    assert "结论：账务核对一致" in p1002_draft["sampleMarkdown"]
    fields_1002 = {f["name"]: f for f in p1002_draft["fields"]}
    assert "结果判定" not in fields_1002
    assert fields_1002["核查备注"]["description"] == "补充核查结论。"
    assert "原规则（Java）" not in fields_1002["充值流水"]["description"]
    assert fields_1002["充值流水"]["columns"] == [
        {"name": "渠道类型", "type": "enum", "values": ["线上", "营业厅"]},
        {"name": "充值金额", "type": "string", "values": []},
    ]

    # 发布 1002 后将其下线：验证线上会话仍允许预览已下线模板并标记 offline=True
    r_pub = await async_client.post(
        "/api/v1/templates/1002/publish",
        headers=bearer_headers,
        json={"note": "发布 1002"},
    )
    assert r_pub.status_code == 200, r_pub.text
    r_off = await async_client.post(
        "/api/v1/templates/1002/offline",
        headers=bearer_headers,
        json={"reason": "测试下线后仍可预览模板"},
    )
    assert r_off.status_code == 200, r_off.text

    r_off_prev = await async_client.get(
        f"/api/v1/chat/sessions/{sid}/templates/1002",
        headers=key_headers,
    )
    assert r_off_prev.status_code == 200, r_off_prev.text
    assert r_off_prev.json()["offline"] is True
    assert "- 渠道：线上，金额：【充值金额】" in r_off_prev.json()["sampleMarkdown"]

    # 3) 不存在的模板或会话返回 404
    r_missing_tpl = await async_client.get(
        f"/api/v1/chat/sessions/{sid}/templates/9999",
        headers=key_headers,
    )
    assert r_missing_tpl.status_code == 404 and r_missing_tpl.json()["code"] == "TEMPLATE_UNAVAILABLE"

    r_missing_sid = await async_client.get(
        f"/api/v1/chat/sessions/{'0' * 32}/templates/1001",
        headers=key_headers,
    )
    assert r_missing_sid.status_code == 404 and r_missing_sid.json()["code"] == "SESSION_NOT_FOUND"


async def test_9_raw_process_events_stream_and_persisted_fallback(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 9：原样过程事件（includeRaw SSE 实时流 + GET /runs/{runId}/raw 内存命中与 RunStore 淘汰回退 + 越权拦截）。"""
    bearer_headers, _ = await _admin_login(async_client)
    key_headers = {"X-API-Key": "upstream-key"}

    def rich_report_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step = sum(1 for m in messages if isinstance(m, ModelResponse))
        if step == 0:
            return ModelResponse(parts=[
                TextPart("先调用短信接口查询客户当日办理短信记录。"),
                ToolCallPart("call_api", {
                    "name": "querySMSSendInfo",
                    "args": {
                        "手机号码": "13900001234",
                        "开始时间": "20261105000000",
                        "结束时间": "20261105235959",
                    },
                }),
            ])
        if step == 1:
            return ModelResponse(parts=[
                ToolCallPart("format_date", {
                    "value": "20261105",
                    "fromPattern": "yyyyMMdd",
                    "toPattern": "yyyy年M月d号",
                }),
            ])
        date_call = next(
            p.content["callId"]
            for m in messages
            for p in getattr(m, "parts", [])
            if isinstance(p, ToolReturnPart) and p.tool_name == "format_date"
        )
        return ModelResponse(parts=[ToolCallPart("submit_report", build_report(ORDER_SMS, date_call))])

    container.runner.model = _dual_model(report_fn=rich_report_stub)

    sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_raw",
            "orderId": "ORD_RAW_01",
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
    assert r_start.status_code == 200, r_start.text
    run_id = r_start.json()["message"]["runId"]

    # 1) 订阅 includeRaw=1&rawAfter=0：同时收到 raw、step 与 final，且 raw 帧不带 SSE id
    ev_resp = await async_client.get(
        f"/api/v1/chat/runs/{run_id}/events?after=0&includeRaw=1&rawAfter=0",
        headers=key_headers,
    )
    assert ev_resp.status_code == 200
    frames = _parse_sse(ev_resp.text)
    raw_frames = [f for f in frames if f["event"] == "raw"]
    step_frames = [f for f in frames if f["event"] == "step"]
    final_frames = [f for f in frames if f["event"] == "final"]
    assert len(raw_frames) >= 5 and len(step_frames) >= 4 and len(final_frames) == 1
    assert all(f["id"] is None for f in raw_frames)
    assert all(f["id"] is not None for f in step_frames)

    raw_seqs = [f["data"]["seq"] for f in raw_frames]
    assert raw_seqs == list(range(1, len(raw_frames) + 1))
    raw_types = {f["data"]["type"] for f in raw_frames}
    # StepMapper 忽略的 model_request / model_text 也必须在 raw 事件流中完整送达
    assert {"run_started", "model_request", "model_text", "tool", "report_accepted"}.issubset(raw_types)
    assert frames[-1]["event"] == "final" and frames[-1]["data"]["status"] == "SUCCESS"

    # 2) 默认不传 includeRaw 时绝不下发 raw 帧
    plain_frames = _parse_sse(
        (await async_client.get(f"/api/v1/chat/runs/{run_id}/events?after=0", headers=key_headers)).text
    )
    assert all(f["event"] in ("step", "final") for f in plain_frames)

    # 3) 内存通道尚在时调用 GET /runs/{runId}/raw
    r_mem_raw = await async_client.get(f"/api/v1/chat/runs/{run_id}/raw", headers=key_headers)
    assert r_mem_raw.status_code == 200, r_mem_raw.text
    mem_payload = r_mem_raw.json()
    assert mem_payload["runId"] == run_id
    assert mem_payload["status"] == "SUCCESS"
    assert [e["seq"] for e in mem_payload["events"]] == raw_seqs

    # 4) 刷盘后清空 ChatRunManager 内存通道（模拟超过 10 分钟被淘汰或服务重启），验证 RunStore 持久化回退
    await _flush_runs(container)
    container.chat.manager._channels.clear()
    assert container.chat.manager.get_raw_events(run_id) is None

    r_disk_raw = await async_client.get(f"/api/v1/chat/runs/{run_id}/raw", headers=key_headers)
    assert r_disk_raw.status_code == 200, r_disk_raw.text
    disk_payload = r_disk_raw.json()
    assert disk_payload["runId"] == run_id
    assert disk_payload["status"] == "SUCCESS"
    assert [e["seq"] for e in disk_payload["events"]] == raw_seqs

    # 内存通道淘汰后再次订阅带 rawAfter=3 的 events 流，验证从 RunStore 重放 seq > 3 的 raw 事件
    replay_frames = _parse_sse((await async_client.get(
        f"/api/v1/chat/runs/{run_id}/events?after=2&includeRaw=1&rawAfter=3",
        headers=key_headers,
    )).text)
    replay_raw_seqs = [f["data"]["seq"] for f in replay_frames if f["event"] == "raw"]
    replay_step_seqs = [f["data"]["seq"] for f in replay_frames if f["event"] == "step"]
    assert replay_raw_seqs == [s for s in raw_seqs if s > 3]
    assert all(s > 2 for s in replay_step_seqs)
    assert replay_frames[-1]["event"] == "final"

    # 5) 越权隔离：非聊天会话的上游运行调用 /chat/runs/{id}/raw 返回 404；draft 会话运行对纯 Key 返回 403
    r_upstream = await async_client.post(
        "/api/v1/reports",
        json={
            "templateId": 1001,
            "params": case_c01["inputs"],
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )
    assert r_upstream.status_code == 200, r_upstream.text
    upstream_rid = r_upstream.json()["runId"]
    await _flush_runs(container)
    r_unauth_run = await async_client.get(f"/api/v1/chat/runs/{upstream_rid}/raw", headers=key_headers)
    assert r_unauth_run.status_code == 404 and r_unauth_run.json()["code"] == "RUN_NOT_FOUND"

    draft_sess = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_raw_draft",
            "orderId": "ORD_RAW_DRAFT",
            "inputs": case_c01["inputs"],
            "document": case_c01["documentText"],
            "target": "draft",
        },
        headers=bearer_headers,
    )).json()
    draft_run_id = (await async_client.post(
        f"/api/v1/chat/sessions/{draft_sess['sessionId']}/runs",
        json={"templateId": 1001},
        headers=bearer_headers,
    )).json()["message"]["runId"]
    await async_client.get(f"/api/v1/chat/runs/{draft_run_id}/events?after=0", headers=bearer_headers)
    r_draft_key = await async_client.get(f"/api/v1/chat/runs/{draft_run_id}/raw", headers=key_headers)
    assert r_draft_key.status_code == 403 and r_draft_key.json()["code"] == "DRAFT_FORBIDDEN"

    # 6) 验证运行尚未结束时，model_request（StepMapper 返回 None）也能实时唤醒 include_raw=True 订阅者
    model_entered = asyncio.Event()
    release_model = asyncio.Event()

    async def gated_report_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step = sum(1 for m in messages if isinstance(m, ModelResponse))
        if step == 0:
            model_entered.set()
            await release_model.wait()
        return rich_report_stub(messages, info)

    container.runner.model = _dual_model(report_fn=gated_report_stub)
    live_rid = (await async_client.post(
        f"/api/v1/chat/sessions/{sid}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )).json()["message"]["runId"]
    await asyncio.wait_for(model_entered.wait(), timeout=5.0)

    # 此时模型第 1 轮尚未返回，仅有 run_started 与 model_request；推进游标到 run_started 之后，确认 model_request 能立即产出而不阻塞
    live_it = container.chat.manager.subscribe(live_rid, after=99, include_raw=True, raw_after=1)
    first_live = await asyncio.wait_for(anext(live_it), timeout=2.0)
    assert first_live[0] == "raw" and first_live[1]["type"] == "model_request"
    release_model.set()
    remaining_kinds = [kind async for kind, _ in live_it]
    assert "final" in remaining_kinds


async def test_10_cross_session_run_isolation_via_header_and_query(
    async_client: httpx.AsyncClient,
    container,
    case_c01: dict[str, Any],
):
    """场景 10：跨会话 runId 防越权（携带 X-Chat-Session-Id 或 ?sessionId= 访问他人会话 /raw /events /cancel /confirm 统一 404）。"""
    key_headers = {"X-API-Key": "upstream-key"}
    entered = asyncio.Event()
    release = asyncio.Event()

    async def gated_stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        step = sum(1 for m in messages if isinstance(m, ModelResponse))
        if step == 0:
            entered.set()
            await release.wait()
        return scripted(messages, info)

    container.runner.model = _dual_model(report_fn=gated_stub)

    sess_a = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_iso_a",
            "orderId": "ORD_ISO_A",
            "inputs": case_c01["inputs"],
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sess_b = (await async_client.post(
        "/api/v1/chat/sessions",
        json={
            "userId": "u_iso_b",
            "orderId": "ORD_ISO_B",
            "inputs": case_c01["inputs"],
            "document": case_c01["documentText"],
        },
        headers=key_headers,
    )).json()
    sid_a = sess_a["sessionId"]
    sid_b = sess_b["sessionId"]
    assert sid_a != sid_b

    run_id = (await async_client.post(
        f"/api/v1/chat/sessions/{sid_a}/runs",
        json={"templateId": 1001},
        headers=key_headers,
    )).json()["message"]["runId"]
    await asyncio.wait_for(entered.wait(), timeout=5.0)

    headers_b = {**key_headers, "X-Chat-Session-Id": sid_b}
    headers_bad = {**key_headers, "X-Chat-Session-Id": "not-a-valid-session-id"}
    headers_a = {**key_headers, "X-Chat-Session-Id": sid_a}

    # 1) 运行进行中：会话 B（请求头或查询参数）与非法会话 ID 请求 /raw /events /cancel 均返回 404，且不会误取消会话 A 的任务
    for h in (headers_b, headers_bad):
        for method, path in (
            ("GET", f"/api/v1/chat/runs/{run_id}/raw"),
            ("GET", f"/api/v1/chat/runs/{run_id}/events?after=0"),
            ("POST", f"/api/v1/chat/runs/{run_id}/cancel"),
        ):
            r = await async_client.request(method, path, headers=h)
            assert r.status_code == 404 and r.json()["code"] == "RUN_NOT_FOUND", (method, path, r.text)

    for method, path in (
        ("GET", f"/api/v1/chat/runs/{run_id}/raw?sessionId={sid_b}"),
        ("GET", f"/api/v1/chat/runs/{run_id}/events?after=0&sessionId={sid_b}"),
        ("POST", f"/api/v1/chat/runs/{run_id}/cancel?sessionId={sid_b}"),
    ):
        r = await async_client.request(method, path, headers=key_headers)
        assert r.status_code == 404 and r.json()["code"] == "RUN_NOT_FOUND"

    # 请求头与查询参数矛盾时同样拒绝（404）
    r_conflict = await async_client.get(
        f"/api/v1/chat/runs/{run_id}/raw?sessionId={sid_b}",
        headers=headers_a,
    )
    assert r_conflict.status_code == 404 and r_conflict.json()["code"] == "RUN_NOT_FOUND"
    assert container.chat.manager.is_running(run_id) is True

    # 2) 放行会话 A 任务完成，并校验会话 A 携带自身 X-Chat-Session-Id 可正常读取 events 与 raw
    release.set()
    ev_ok = await async_client.get(f"/api/v1/chat/runs/{run_id}/events?after=0", headers=headers_a)
    assert ev_ok.status_code == 200
    frames = _parse_sse(ev_ok.text)
    assert frames[-1]["event"] == "final" and frames[-1]["data"]["status"] == "SUCCESS"
    orig_md = frames[-1]["data"]["versions"][0]["markdown"]

    raw_ok = await async_client.get(f"/api/v1/chat/runs/{run_id}/raw", headers=headers_a)
    assert raw_ok.status_code == 200 and raw_ok.json()["runId"] == run_id

    # 3) 跨会话调用 /confirm（请求头、查询参数、非法格式）一律 404；本会话携带 X-Chat-Session-Id 确认返回 200
    for h in (headers_b, headers_bad):
        r_conf_deny = await async_client.post(
            f"/api/v1/chat/runs/{run_id}/confirm",
            json={"markdown": orig_md},
            headers=h,
        )
        assert r_conf_deny.status_code == 404 and r_conf_deny.json()["code"] == "RUN_NOT_FOUND"

    r_conf_q_deny = await async_client.post(
        f"/api/v1/chat/runs/{run_id}/confirm?sessionId={sid_b}",
        json={"markdown": orig_md},
        headers=key_headers,
    )
    assert r_conf_q_deny.status_code == 404 and r_conf_q_deny.json()["code"] == "RUN_NOT_FOUND"

    r_conf_ok = await async_client.post(
        f"/api/v1/chat/runs/{run_id}/confirm",
        json={"markdown": orig_md},
        headers=headers_a,
    )
    assert r_conf_ok.status_code == 200 and r_conf_ok.json()["payload"]["runId"] == run_id



