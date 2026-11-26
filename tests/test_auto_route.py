"""未传 templateId 时自动模板路由（template-router Skill）全链路自动化测试。

#Created By AiCoding(codex)
覆盖全部 12 项核心验收场景（全部使用 FunctionModel 桩模型与 mock-gateway，绝不请求外网模型）：
1. 显式传 templateId：不触发路由、无 routing 字段、既有行为 100% 兼容。
2. 显式传非法 templateId（0 / -1）：返回 400 INVALID_TEMPLATE_ID。
3. 未传 templateId（省略字段或传 null）走 POST /api/v1/reports：验证 L1+L2 子文档懒加载、命中填报与强证据核验。
4. 最高置信度优先 & 低置信度不阻塞（高/中排序择优 + 仅低置信度直接放行运行）。
5. 未传 templateId 走 POST /api/v1/reports/stream（SSE）：完整路由→填报→final 事件流顺序校验。
6. 路由无法匹配（模型无匹配 / 无可用在线模板）：同步 422 TEMPLATE_ROUTE_FAILED、SSE error、不写 RunStore。
7. 自动路由命中后缺少必填入参：400 INVALID_INPUT 附带 templateId/templateName/routing、不写 RunStore。
8. 最小测试资源集未配置 template-router Skill：自动回退 list_templates / get_template 完成匹配。
9. 路由模型误选已下线或不存在模板 ID：触发 output_validator ModelRetry 拦截并重试自愈。
10. 复合工单 POST /api/v1/reports/composite：混合/全量省略 templateId 并发路由、单子项失败隔离与汇总拼装。
11. RunStore 持久化与 GET /api/v1/runs/{runId}：routing 与 route_started/route_completed 事件完整落盘回查。
12. StepMapper 对 route_started / route_completed / route_failed 与路由工具的脱敏步骤映射测试。
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
from typing import Any

import httpx
import pytest
import yaml
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from report_agent.api.auth import UserStore
from report_agent.chat.steps import StepMapper, events_to_steps
from report_agent.container import Container, build_container
from report_agent.domain.template import Template, parse_template_yaml
from report_agent.main import create_app
from report_agent.runtime.workspace import ProcessEvent
from report_agent.store.service import skill_ref, tpl_ref
from scripted_model import scripted

API_KEY_HEADERS = {"X-API-Key": "upstream-key"}


# ============================================================================ 公共测试辅助
def _is_router_agent(info: AgentInfo) -> bool:
    """判断当前模型调用是否来自无状态模板路由器（output_tool 为 submit_route_decision）。"""
    return any(t.name == "submit_route_decision" for t in info.output_tools)


def _route_and_report_model(route_fn: Any, report_fn: Any = scripted) -> FunctionModel:
    """构造路由 + 填报双分派桩模型：路由阶段走 route_fn，填报阶段走 report_fn。"""

    async def _dispatch(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        target = route_fn if _is_router_agent(info) else report_fn
        res = target(messages, info)
        if inspect.isawaitable(res):
            return await res
        return res

    return FunctionModel(_dispatch, model_name="scripted-auto-route")


def _swap_model(container: Container, model: FunctionModel) -> None:
    """热替换测试容器内 AgentRunner 的桩模型并清空缓存（含路由器缓存）。"""
    container.runner._bundle = dataclasses.replace(container.runner._bundle, model=model)
    container.runner._agent_cache.clear()
    container.runner._router._cached_agent = None


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    """解析标准 SSE 响应帧，忽略注释心跳行。"""
    events: list[dict[str, Any]] = []
    for block in raw.split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln.strip() and not ln.startswith(":")]
        if not lines:
            continue
        evt_name = "message"
        data_lines: list[str] = []
        for ln in lines:
            if ln.startswith("event:"):
                evt_name = ln[6:].strip()
            elif ln.startswith("data:"):
                data_lines.append(ln[5:].lstrip())
        if data_lines:
            events.append({"event": evt_name, "data": json.loads("\n".join(data_lines))})
    return events


def _responses_count(messages: list[ModelMessage]) -> int:
    return sum(1 for m in messages if isinstance(m, ModelResponse))


def _tool_returns(messages: list[ModelMessage], tool_name: str) -> list[Any]:
    out: list[Any] = []
    for msg in messages:
        for part in getattr(msg, "parts", ()):
            if isinstance(part, ToolReturnPart) and part.tool_name == tool_name:
                out.append(part.content)
    return out


def _retry_prompts(messages: list[ModelMessage]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        for part in getattr(msg, "parts", ()):
            if isinstance(part, RetryPromptPart):
                out.append(part.model_response())
            elif isinstance(part, ToolReturnPart) and part.tool_name == "submit_route_decision":
                out.append(str(part.content))
    return out


def _make_simple_template(tid: int, name: str, desc: str) -> Template:
    """构造最小可发布测试模板（依赖内置 document-match Skill，仅需手机号码）。"""
    defn = parse_template_yaml(
        yaml.safe_dump(
            {
                "id": tid,
                "name": name,
                "description": desc,
                "skills": ["document-match"],
                "inputs": [
                    {"key": "手机号码", "required": True, "description": "客户手机号"},
                ],
                "fields": [
                    {
                        "name": "核查结论",
                        "visible": True,
                        "type": "string",
                        "evidence": "input",
                        "whenMissing": "placeholder",
                        "description": "核查号码说明",
                    },
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        )
    )
    return Template(definition=defn, body="核查号码：{{ 核查结论 }}")


def _publish_template_router_skill(container: Container, *, extra_ids: tuple[int, ...] = (1002,)) -> None:
    """向测试容器发布带 L1 总则与 L2 references/*.md 子文档的 template-router Skill。"""
    md = (
        "---\n"
        "name: template-router\n"
        "title: 模板路由\n"
        "description: 根据单据与入参分层检索匹配最优申告报告模板。\n"
        "scope: chat\n"
        "apis: []\n"
        "---\n\n"
        "# 模板路由总则\n\n"
        "请先锁定业务族，再按需加载子文档：\n"
        "- [业务办理争议族](references/order.md)（1001）\n"
        "- [宽带资费专项族](references/broadband.md)（"
        + "、".join(str(i) for i in extra_ids)
        + "）\n"
    )
    docs = {
        "references/order.md": (
            "# 业务办理争议族细则\n\n"
            "### 1001 业务办理争议类\n"
            "路由秘钥：ROUTER-ORDER-L2-TOKEN\n"
            "适用套餐办理、订购短信、二次确认短信与受理单争议。\n"
        ),
        "references/broadband.md": (
            "# 宽带资费专项族细则\n\n"
            "### 1002 宽带资费争议类\n"
            "路由秘钥：ROUTER-BROADBAND-L2-TOKEN\n"
            "适用家庭宽带资费、光猫押金与安装地址争议。\n"
        ),
    }
    container.service.save_skill("template-router", md, "tester", action="create", docs=docs)
    container.service.publish_draft(skill_ref("template-router"), "tester", "发布 template-router 分层技能")


def _publish_extra_templates(container: Container, *, with_offline: bool = False) -> None:
    """发布在线模板 1002，以及可选的已下线模板 1003。"""
    t1002 = _make_simple_template(1002, "宽带资费争议类", "用于家庭宽带费用与押金核查")
    container.service.save_template(t1002, "tester", action="create")
    container.service.publish_draft(tpl_ref(1002), "tester", "发布模板 1002")

    if with_offline:
        t1003 = _make_simple_template(1003, "历史停用模板", "已停用的历史模板")
        container.service.save_template(t1003, "tester", action="create")
        container.service.publish_draft(tpl_ref(1003), "tester", "发布模板 1003")
        container.service.offline_template(1003, "tester", "测试下线隔离")


async def _flush_runs(container: Container) -> None:
    """等待 RunStore 后台写协程将队列中全部记录刷入磁盘。"""
    for _ in range(100):
        if not container.runs._pending:
            break
        await asyncio.sleep(0.01)


async def _admin_headers(cl: httpx.AsyncClient) -> dict[str, str]:
    r = await cl.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "pass-1234"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    cl.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def auto_client(container):
    """默认异步客户端（带完整 lifespan，基于独立 tmp_path container）。"""
    UserStore(container.layout.config / "users.yaml").upsert(
        "chenxiaoyun", "pass-1234", "陈晓芸", "业务维护"
    )
    app = create_app(container=container)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as cl:
            yield cl


# ============================================================================ 场景 1 & 2：显式 templateId 兼容与非法 ID 拦截
async def test_1_explicit_template_id_skips_routing_and_keeps_compat(auto_client, container, case_c01):
    """场景 1：显式传 templateId 不触发路由、响应无 routing 字段、既有行为 100% 兼容。"""
    router_calls = 0

    def _never_called_router(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal router_calls
        router_calls += 1
        raise AssertionError("显式传入 templateId 时绝不应调用模板路由器")

    _swap_model(container, _route_and_report_model(_never_called_router, scripted))

    body = {"templateId": 1001, "params": case_c01["inputs"], "document": case_c01["documentText"]}
    resp = await auto_client.post("/api/v1/reports", json=body, headers=API_KEY_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert router_calls == 0
    assert data["status"] == "SUCCESS"
    assert data["templateId"] == 1001
    assert data["templateName"] == "业务办理争议类"
    assert "routing" not in data
    assert "办理成功告知短信" in data["report"]


@pytest.mark.parametrize("bad_tid", [0, -1, -99])
async def test_2_invalid_explicit_template_id_returns_400(auto_client, case_c01, bad_tid: int):
    """场景 2：显式传非法 templateId（0 / 负数）返回 400 INVALID_TEMPLATE_ID（含同步/SSE/复合接口）。"""
    base_body = {"templateId": bad_tid, "params": case_c01["inputs"], "document": case_c01["documentText"]}

    r_sync = await auto_client.post("/api/v1/reports", json=base_body, headers=API_KEY_HEADERS)
    assert r_sync.status_code == 400 and r_sync.json()["code"] == "INVALID_TEMPLATE_ID"

    r_stream = await auto_client.post("/api/v1/reports/stream", json=base_body, headers=API_KEY_HEADERS)
    assert r_stream.status_code == 400 and r_stream.json()["code"] == "INVALID_TEMPLATE_ID"

    r_comp = await auto_client.post(
        "/api/v1/reports/composite",
        json={
            "order": case_c01["inputs"],
            "document": case_c01["documentText"],
            "items": [{"templateId": bad_tid, "label": "非法模板项"}],
        },
        headers=API_KEY_HEADERS,
    )
    assert r_comp.status_code == 400 and r_comp.json()["code"] == "INVALID_TEMPLATE_ID"


# ============================================================================ 场景 3：自动加载 template-router (L1 + L2) 并执行填报
@pytest.mark.parametrize("omit_field", [True, False])
async def test_3_auto_route_with_template_router_l1_l2_lazy_load(
    auto_client,
    container,
    case_c01,
    omit_field: bool,
):
    """场景 3：未传 templateId（省略字段或传 null）自动加载 template-router L1+L2 子文档 → 命中填报与强证据核验。"""
    _publish_extra_templates(container)
    _publish_template_router_skill(container, extra_ids=(1002,))

    captured_returns: list[str] = []

    def _router_flow(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        for ret in _tool_returns(messages, "load_skill"):
            text = str(ret)
            if text not in captured_returns:
                captured_returns.append(text)
        step = _responses_count(messages)
        if step == 0:
            # L1：先加载 template-router 主说明
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "template-router"})])
        if step == 1:
            # L2：仅按需加载命中的业务族子文档 references/order.md
            return ModelResponse(
                parts=[ToolCallPart("load_skill", {"name": "template-router", "docs": ["references/order.md"]})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": 1001,
                        "confidence": "高",
                        "reason": "单据为 5G 智享套餐受理单且涉及业务办理短信核查，精准命中模板 1001",
                        "candidates": [
                            {"templateId": 1001, "level": "高", "reason": "命中业务办理争议族核心场景"},
                            {"templateId": 1002, "level": "低", "reason": "不含宽带安装特征"},
                        ],
                    },
                )
            ]
        )

    _swap_model(container, _route_and_report_model(_router_flow, scripted))

    body: dict[str, Any] = {"params": case_c01["inputs"], "document": case_c01["documentText"]}
    if not omit_field:
        body["templateId"] = None

    resp = await auto_client.post("/api/v1/reports", json=body, headers=API_KEY_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # 校验 L1 + L2 懒加载隔离：L1 仅含索引不含子文档秘钥，L2 仅含 order.md 不泄露 broadband.md
    assert len(captured_returns) == 2
    l1_text, l2_text = captured_returns[0], captured_returns[1]
    assert "可按需加载的参考文档" in l1_text and "references/order.md" in l1_text
    assert "ROUTER-ORDER-L2-TOKEN" not in l1_text and "ROUTER-BROADBAND-L2-TOKEN" not in l1_text
    assert "ROUTER-ORDER-L2-TOKEN" in l2_text
    assert "ROUTER-BROADBAND-L2-TOKEN" not in l2_text

    # 校验响应字段、routing 元数据与强证据填报结果
    assert data["status"] == "SUCCESS"
    assert data["templateId"] == 1001
    assert data["templateName"] == "业务办理争议类"
    assert "办理成功告知短信" in data["report"]

    routing = data["routing"]
    assert routing["auto"] is True
    assert routing["templateId"] == 1001
    assert routing["templateName"] == "业务办理争议类"
    assert routing["confidence"] == "高"
    assert "1001" in routing["reason"]
    assert routing["skillsLoaded"] == ["template-router"]
    assert isinstance(routing["durationMs"], int) and routing["durationMs"] >= 0
    assert [c["templateId"] for c in routing["candidates"]] == [1001, 1002]
    assert routing["candidates"][0]["templateName"] == "业务办理争议类"
    assert routing["candidates"][1]["templateName"] == "宽带资费争议类"


# ============================================================================ 场景 4：最高置信度优先 & 低置信度不阻塞
async def test_4a_highest_confidence_candidate_wins_over_lower_primary(auto_client, container, case_c01):
    """场景 4A：候选包含「中」与「高」置信度时，output_validator 自动按最高置信度重排并运行置信度最高的模板。"""
    _publish_extra_templates(container)
    _publish_template_router_skill(container, extra_ids=(1002,))

    def _router_mixed_confidence(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        # 故意把中置信度的 1002 放主选，把高置信度的 1001 放在候选第二位
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": 1002,
                        "confidence": "中",
                        "reason": "宽带疑似相关",
                        "candidates": [
                            {"templateId": 1002, "level": "中", "reason": "宽带字段弱匹配"},
                            {"templateId": 1001, "level": "高", "reason": "单据与办理短信精准吻合"},
                        ],
                    },
                )
            ]
        )

    _swap_model(container, _route_and_report_model(_router_mixed_confidence, scripted))

    resp = await auto_client.post(
        "/api/v1/reports",
        json={"params": case_c01["inputs"], "document": case_c01["documentText"]},
        headers=API_KEY_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "SUCCESS"
    # 最终必须以高置信度的 1001 执行，而非中置信度的 1002
    assert data["templateId"] == 1001
    assert data["templateName"] == "业务办理争议类"
    assert data["routing"]["templateId"] == 1001
    assert data["routing"]["confidence"] == "高"
    assert [c["templateId"] for c in data["routing"]["candidates"]] == [1001, 1002]
    assert [c["level"] for c in data["routing"]["candidates"]] == ["高", "中"]


@pytest.mark.parametrize("matched_flag", [True, False])
async def test_4b_low_confidence_does_not_block_and_runs_best_candidate(
    auto_client,
    container,
    case_c01,
    matched_flag: bool,
):
    """场景 4B：即便最高置信度仅为「低」（含 matched=False 但给出低置信度候选），仍不阻塞并直接执行填报。"""
    _publish_extra_templates(container)

    def _router_low_conf(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        payload: dict[str, Any] = {
            "matched": matched_flag,
            "templateId": 1001 if matched_flag else None,
            "confidence": "低",
            "reason": "单据信息偏少，按最接近的业务办理争议模板兜底执行",
            "candidates": [
                {"templateId": 1001, "level": "低", "reason": "最接近的通用业务办理模板"},
                {"templateId": 1002, "level": "低", "reason": "备选宽带模板"},
            ],
        }
        return ModelResponse(parts=[ToolCallPart("submit_route_decision", payload)])

    _swap_model(container, _route_and_report_model(_router_low_conf, scripted))

    resp = await auto_client.post(
        "/api/v1/reports",
        json={"params": case_c01["inputs"], "document": case_c01["documentText"]},
        headers=API_KEY_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["templateId"] == 1001
    assert data["routing"]["auto"] is True
    assert data["routing"]["confidence"] == "低"
    assert data["routing"]["templateId"] == 1001


# ============================================================================ 场景 5：SSE 流式接口事件流顺序
async def test_5_stream_sse_emits_route_events_before_run_and_final(auto_client, container, case_c01):
    """场景 5：POST /api/v1/reports/stream 依次推送 route_started → 路由工具调用 → route_completed → run_started → 填报事件 → final。"""
    _publish_extra_templates(container)
    _publish_template_router_skill(container, extra_ids=(1002,))

    def _router_flow(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        step = _responses_count(messages)
        if step == 0:
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "template-router"})])
        if step == 1:
            return ModelResponse(
                parts=[ToolCallPart("load_skill", {"name": "template-router", "docs": ["references/order.md"]})]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": 1001,
                        "confidence": "高",
                        "reason": "命中业务办理争议模板",
                        "candidates": [{"templateId": 1001, "level": "高", "reason": "精准匹配"}],
                    },
                )
            ]
        )

    _swap_model(container, _route_and_report_model(_router_flow, scripted))

    resp = await auto_client.post(
        "/api/v1/reports/stream",
        json={"params": case_c01["inputs"], "document": case_c01["documentText"]},
        headers=API_KEY_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    frames = _parse_sse(resp.text)
    assert frames and frames[-1]["event"] == "final"

    proc_events = [f["data"] for f in frames if f["event"] == "event"]
    types = [e["type"] for e in proc_events]

    # 校验关键事件全部存在且严格有序：route_started < 路由 tool < route_completed < run_started < 填报事件
    idx_rs = types.index("route_started")
    idx_rc = types.index("route_completed")
    idx_run = types.index("run_started")
    assert idx_rs == 0
    assert idx_rs < idx_rc < idx_run

    # 校验 route_started 与路由阶段工具事件位于 round=0
    assert proc_events[idx_rs]["round"] == 0
    assert proc_events[idx_rs]["routerSkill"] == "template-router"

    route_tools = [e for e in proc_events[idx_rs + 1 : idx_rc] if e["type"] == "tool"]
    assert len(route_tools) == 2
    assert all(e["tool"] == "load_skill" and str(e["callId"]).startswith("rt") for e in route_tools)
    assert route_tools[1]["result"]["docs"] == ["references/order.md"]

    # 校验 route_completed 负载
    rc = proc_events[idx_rc]
    assert rc["templateId"] == 1001
    assert rc["templateName"] == "业务办理争议类"
    assert rc["confidence"] == "高"
    assert isinstance(rc["durationMs"], int) and rc["durationMs"] >= 0

    # 校验 run_started 之后有填报事件（model_request / tool / report_accepted）
    post_run_types = set(types[idx_run + 1 :])
    assert {"model_request", "tool", "report_accepted"} <= post_run_types

    # 校验 final 帧包含 routing
    final_data = frames[-1]["data"]
    assert final_data["status"] == "SUCCESS"
    assert final_data["templateId"] == 1001
    assert final_data["routing"]["auto"] is True
    assert final_data["routing"]["confidence"] == "高"
    assert final_data["routing"]["skillsLoaded"] == ["template-router"]


# ============================================================================ 场景 6：路由无法匹配（同步 422 / SSE error / 无在线模板 / 不写 RunStore）
async def test_6a_route_failed_no_match_returns_422_and_sse_error_without_run_store(
    auto_client,
    container,
    case_c01,
):
    """场景 6A：模型返回 matched=False 且 candidates=[] → 同步 422 TEMPLATE_ROUTE_FAILED、SSE error，均不写入 RunStore。"""

    def _no_match_router(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": False,
                        "templateId": None,
                        "confidence": "低",
                        "reason": "单据属于国际漫游专项，当前无匹配在线模板",
                        "candidates": [],
                    },
                )
            ]
        )

    _swap_model(container, _route_and_report_model(_no_match_router, scripted))
    before_runs = len(container.runs.list(limit=100))

    # 1) 同步接口返回 422 TEMPLATE_ROUTE_FAILED
    r_sync = await auto_client.post(
        "/api/v1/reports",
        json={"params": case_c01["inputs"], "document": "完全无关的投诉单据"},
        headers=API_KEY_HEADERS,
    )
    assert r_sync.status_code == 422, r_sync.text
    err_body = r_sync.json()
    assert err_body["code"] == "TEMPLATE_ROUTE_FAILED"
    assert "国际漫游专项" in err_body["reason"]
    assert err_body["candidates"] == []

    # 2) SSE 接口推送 route_started -> route_failed -> error(code=TEMPLATE_ROUTE_FAILED)
    r_stream = await auto_client.post(
        "/api/v1/reports/stream",
        json={"params": case_c01["inputs"], "document": "完全无关的投诉单据"},
        headers=API_KEY_HEADERS,
    )
    assert r_stream.status_code == 200, r_stream.text
    frames = _parse_sse(r_stream.text)
    proc_types = [f["data"]["type"] for f in frames if f["event"] == "event"]
    assert "route_started" in proc_types and "route_failed" in proc_types
    assert "run_started" not in proc_types
    assert frames[-1]["event"] == "error"
    assert frames[-1]["data"]["code"] == "TEMPLATE_ROUTE_FAILED"
    assert "国际漫游专项" in frames[-1]["data"]["reason"]
    assert frames[-1]["data"]["candidates"] == []

    # 3) 均不写入 RunStore
    await _flush_runs(container)
    assert len(container.runs.list(limit=100)) == before_runs


async def test_6b_route_failed_when_no_online_templates_available(auto_client, container, case_c01):
    """场景 6B：当前快照没有任何在线模板时，不调用模型，直接 422 TEMPLATE_ROUTE_FAILED 且不写 RunStore。"""
    container.service.offline_template(1001, "tester", "全部模板下线测试")
    model_called = False

    def _should_not_call(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        nonlocal model_called
        model_called = True
        raise AssertionError("无在线模板时不应请求大模型")

    _swap_model(container, _route_and_report_model(_should_not_call, _should_not_call))
    before_runs = len(container.runs.list(limit=100))

    resp = await auto_client.post(
        "/api/v1/reports",
        json={"params": case_c01["inputs"], "document": case_c01["documentText"]},
        headers=API_KEY_HEADERS,
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "TEMPLATE_ROUTE_FAILED"
    assert "没有可用的在线模板" in body["reason"]
    assert body["candidates"] == []
    assert model_called is False

    await _flush_runs(container)
    assert len(container.runs.list(limit=100)) == before_runs


# ============================================================================ 场景 7：自动路由命中后缺少必填入参
async def test_7_auto_route_missing_required_inputs_returns_400_with_routing(auto_client, container, case_c01):
    """场景 7：路由命中 1001 但缺少必填入参 → 400 INVALID_INPUT（含 templateId/templateName/routing/errors），不写 RunStore。"""
    _publish_extra_templates(container)
    _publish_template_router_skill(container, extra_ids=(1002,))

    def _router_hit_1001(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if _responses_count(messages) == 0:
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "template-router"})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": 1001,
                        "confidence": "高",
                        "reason": "单据符合 1001 业务办理争议场景",
                        "candidates": [{"templateId": 1001, "level": "高", "reason": "单据吻合"}],
                    },
                )
            ]
        )

    _swap_model(container, _route_and_report_model(_router_hit_1001, scripted))
    before_runs = len(container.runs.list(limit=100))

    # 故意传空 params（缺少 手机号码、业务名称、创建时间 等必填项）
    r_sync = await auto_client.post(
        "/api/v1/reports",
        json={"params": {}, "document": case_c01["documentText"]},
        headers=API_KEY_HEADERS,
    )
    assert r_sync.status_code == 400, r_sync.text
    err = r_sync.json()
    assert err["code"] == "INVALID_INPUT"
    assert err["templateId"] == 1001
    assert err["templateName"] == "业务办理争议类"
    assert err["routing"]["auto"] is True
    assert err["routing"]["templateId"] == 1001
    assert err["routing"]["confidence"] == "高"
    assert err["errors"] and any("手机号码" in e for e in err["errors"])

    # SSE 接口在缺参时同样先推 route_completed 再推带路由上下文的 error(INVALID_INPUT)
    r_stream = await auto_client.post(
        "/api/v1/reports/stream",
        json={"params": {}, "document": case_c01["documentText"]},
        headers=API_KEY_HEADERS,
    )
    assert r_stream.status_code == 200, r_stream.text
    frames = _parse_sse(r_stream.text)
    proc_types = [f["data"]["type"] for f in frames if f["event"] == "event"]
    assert "route_started" in proc_types and "route_completed" in proc_types
    assert "run_started" not in proc_types
    assert frames[-1]["event"] == "error"
    err_sse = frames[-1]["data"]
    assert err_sse["code"] == "INVALID_INPUT"
    assert err_sse["templateId"] == 1001
    assert err_sse["templateName"] == "业务办理争议类"
    assert err_sse["routing"]["auto"] is True
    assert err_sse["errors"]

    await _flush_runs(container)
    assert len(container.runs.list(limit=100)) == before_runs


# ============================================================================ 场景 8：无 template-router Skill 时回退 list_templates / get_template
async def test_8_fallback_to_list_and_get_template_without_router_skill(auto_client, container, case_c01):
    """场景 8：最小测试资源集未配置 template-router 时，自动回退调用 list_templates / get_template 完成匹配。"""
    # 确认默认 fixture 中未配置 template-router
    _, live_rs = container.service.live()
    assert "template-router" not in live_rs.skills

    tool_trace: list[tuple[str, Any]] = []

    def _fallback_router(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        for tname in ("list_templates", "get_template"):
            for ret in _tool_returns(messages, tname):
                entry = (tname, ret)
                if entry not in tool_trace:
                    tool_trace.append(entry)
        step = _responses_count(messages)
        if step == 0:
            return ModelResponse(parts=[ToolCallPart("list_templates", {"keyword": ""})])
        if step == 1:
            return ModelResponse(parts=[ToolCallPart("get_template", {"templateId": 1001})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": 1001,
                        "confidence": "高",
                        "reason": "通过 list_templates 与 get_template 核对入参后确认命中模板 1001",
                        "candidates": [{"templateId": 1001, "level": "高", "reason": "字段与入参完全匹配"}],
                    },
                )
            ]
        )

    _swap_model(container, _route_and_report_model(_fallback_router, scripted))

    # 走 SSE 顺便验证 route_started.routerSkill is None 及工具调用事件
    resp = await auto_client.post(
        "/api/v1/reports/stream",
        json={"params": case_c01["inputs"], "document": case_c01["documentText"]},
        headers=API_KEY_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    frames = _parse_sse(resp.text)
    proc_events = [f["data"] for f in frames if f["event"] == "event"]
    rs_ev = next(e for e in proc_events if e["type"] == "route_started")
    assert rs_ev["routerSkill"] is None

    # 验证模型实际收到 list_templates 和 get_template 的有效结果
    list_rets = [ret for name, ret in tool_trace if name == "list_templates"]
    get_rets = [ret for name, ret in tool_trace if name == "get_template"]
    assert list_rets and any(item["id"] == 1001 for item in list_rets[0])
    assert get_rets and get_rets[0]["ok"] is True and get_rets[0]["id"] == 1001

    final_data = frames[-1]["data"]
    assert frames[-1]["event"] == "final"
    assert final_data["status"] == "SUCCESS"
    assert final_data["templateId"] == 1001
    assert final_data["routing"]["skillsLoaded"] == []


# ============================================================================ 场景 9：误选不存在或已下线模板触发 ModelRetry 自愈
async def test_9_router_validator_retries_nonexistent_and_offline_template_ids(auto_client, container, case_c01):
    """场景 9：路由模型先后误选不存在模板 9999、已下线模板 1003 → 触发两次 ModelRetry 拦截 → 重试选中在线 1001。"""
    _publish_extra_templates(container, with_offline=True)
    seen_retries: list[str] = []

    def _buggy_then_fixed_router(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        for rp in _retry_prompts(messages):
            if rp not in seen_retries:
                seen_retries.append(rp)
        step = _responses_count(messages)
        if step == 0:
            # 第 1 次：误选不存在的模板 9999
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "submit_route_decision",
                        {
                            "matched": True,
                            "templateId": 9999,
                            "confidence": "高",
                            "reason": "误编造的模板号",
                            "candidates": [{"templateId": 9999, "level": "高", "reason": "不存在"}],
                        },
                    )
                ]
            )
        if step == 1:
            # 第 2 次：主选 1001，但候选列表中夹带已下线模板 1003
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "submit_route_decision",
                        {
                            "matched": True,
                            "templateId": 1001,
                            "confidence": "高",
                            "reason": "主选在线模板但候选带入已下线模板",
                            "candidates": [
                                {"templateId": 1001, "level": "高", "reason": "在线模板"},
                                {"templateId": 1003, "level": "中", "reason": "已下线模板"},
                            ],
                        },
                    )
                ]
            )
        # 第 3 次：修正为合法在线模板 1001
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": 1001,
                        "confidence": "高",
                        "reason": "经校验修正为在线模板 1001",
                        "candidates": [{"templateId": 1001, "level": "高", "reason": "在线可用"}],
                    },
                )
            ]
        )

    _swap_model(container, _route_and_report_model(_buggy_then_fixed_router, scripted))

    resp = await auto_client.post(
        "/api/v1/reports",
        json={"params": case_c01["inputs"], "document": case_c01["documentText"]},
        headers=API_KEY_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "SUCCESS"
    assert data["templateId"] == 1001
    assert data["routing"]["templateId"] == 1001
    # 确认 output_validator 确实先后拦截了 9999 和 1003 并触发 ModelRetry
    assert len(seen_retries) == 2
    assert "9999" in seen_retries[0] and "不存在或已下线" in seen_retries[0]
    assert "1003" in seen_retries[1] and "不存在或已下线" in seen_retries[1]


# ============================================================================ 场景 10：复合工单并发自动路由与单子项失败隔离
async def test_10_composite_auto_route_mixed_and_partial_failure_isolation(auto_client, container, case_c01):
    """场景 10：POST /api/v1/reports/composite 混合/全量省略 templateId 并发路由、单子项失败隔离与汇总拼装。"""
    _publish_extra_templates(container)
    _publish_template_router_skill(container, extra_ids=(1002,))

    def _composite_router(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        # 根据动态指令（包含该子项的 document / inputs）区分不同子项的路由决策
        instr = str(getattr(_info, "instructions", "") or "")
        all_text = instr + "\n".join(str(p) for m in messages for p in getattr(m, "parts", ()))
        if "无法匹配专项" in all_text:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "submit_route_decision",
                        {
                            "matched": False,
                            "templateId": None,
                            "confidence": "低",
                            "reason": "该子项无对应在线模板",
                            "candidates": [],
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": 1001,
                        "confidence": "高",
                        "reason": "复合子项自动命中 1001",
                        "candidates": [{"templateId": 1001, "level": "高", "reason": "套餐办理核查"}],
                    },
                )
            ]
        )

    _swap_model(container, _route_and_report_model(_composite_router, scripted))

    # 1) 混合模式：子项 1 显式传 templateId=1001，子项 2 省略 templateId 成功自动路由，子项 3 自动路由失败隔离
    r_mixed = await auto_client.post(
        "/api/v1/reports/composite",
        headers=API_KEY_HEADERS,
        json={
            "order": case_c01["inputs"],
            "document": case_c01["documentText"],
            "items": [
                {"templateId": 1001, "label": "显式项-5G套餐"},
                {"label": "自动路由项-5G套餐"},
                {"templateId": None, "label": "无匹配项", "document": "这是无法匹配专项的未知投诉"},
            ],
        },
    )
    assert r_mixed.status_code == 200, r_mixed.text
    mixed = r_mixed.json()
    assert mixed["status"] == "PARTIAL"
    assert len(mixed["items"]) == 3

    it1, it2, it3 = mixed["items"]
    assert it1["status"] == "SUCCESS" and it1["templateId"] == 1001 and "routing" not in it1
    assert it2["status"] == "SUCCESS" and it2["templateId"] == 1001 and it2["templateName"] == "业务办理争议类"
    assert it2["routing"]["auto"] is True and it2["routing"]["confidence"] == "高"
    assert it3["status"] == "FAILED" and it3["templateId"] is None
    assert "无对应在线模板" in (it3["error"] or "")
    assert "显式项-5G套餐" in mixed["assembledMarkdown"]
    assert "自动路由项-5G套餐" in mixed["assembledMarkdown"]
    assert "无匹配项" in mixed["assembledMarkdown"]

    # 2) 全量省略 templateId：两项并发自动路由均成功，且共享幂等网关命中缓存
    r_all_auto = await auto_client.post(
        "/api/v1/reports/composite",
        headers=API_KEY_HEADERS,
        json={
            "order": case_c01["inputs"],
            "document": case_c01["documentText"],
            "items": [
                {"label": "自动子项A"},
                {"label": "自动子项B"},
            ],
        },
    )
    assert r_all_auto.status_code == 200, r_all_auto.text
    all_auto = r_all_auto.json()
    assert all_auto["status"] == "SUCCESS"
    assert all(it["status"] == "SUCCESS" and it["templateId"] == 1001 and it["routing"]["auto"] for it in all_auto["items"])
    assert all_auto["sharedGatewayHits"] >= 1


# ============================================================================ 场景 11：RunStore 持久化与运行详情接口回查
async def test_11_run_store_persists_routing_and_events_in_detail_api(auto_client, container, case_c01):
    """场景 11：RunStore 持久落盘 routing 与 route_started/route_completed 事件，并可通过 GET /api/v1/runs/{runId} 回查。"""
    _publish_extra_templates(container)
    _publish_template_router_skill(container, extra_ids=(1002,))

    def _router_flow(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        if _responses_count(messages) == 0:
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "template-router"})])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": 1001,
                        "confidence": "高",
                        "reason": "持久化测试命中 1001",
                        "candidates": [{"templateId": 1001, "level": "高", "reason": "精准命中"}],
                    },
                )
            ]
        )

    _swap_model(container, _route_and_report_model(_router_flow, scripted))

    # 1) 自动路由运行
    r_auto = await auto_client.post(
        "/api/v1/reports",
        json={"params": case_c01["inputs"], "document": case_c01["documentText"]},
        headers=API_KEY_HEADERS,
    )
    assert r_auto.status_code == 200, r_auto.text
    auto_run_id = r_auto.json()["runId"]

    # 2) 显式 templateId 运行作对照
    r_explicit = await auto_client.post(
        "/api/v1/reports",
        json={"templateId": 1001, "params": case_c01["inputs"], "document": case_c01["documentText"]},
        headers=API_KEY_HEADERS,
    )
    assert r_explicit.status_code == 200, r_explicit.text
    explicit_run_id = r_explicit.json()["runId"]

    await _flush_runs(container)

    # 确认磁盘详情文件已实际落盘（不是仅读内存 _pending）
    disk_auto = container.runs.get(auto_run_id)
    assert disk_auto is not None and disk_auto.get("routing", {}).get("auto") is True

    # 通过管理端 GET /api/v1/runs/{runId} 回查
    admin_hdrs = await _admin_headers(auto_client)
    d_auto = (await auto_client.get(f"/api/v1/runs/{auto_run_id}", headers=admin_hdrs)).json()
    assert d_auto["routing"]["auto"] is True
    assert d_auto["routing"]["templateId"] == 1001
    assert d_auto["routing"]["templateName"] == "业务办理争议类"
    assert d_auto["routing"]["confidence"] == "高"
    assert d_auto["routing"]["skillsLoaded"] == ["template-router"]

    ev_types = [e["type"] for e in d_auto["events"]]
    assert "route_started" in ev_types
    assert "route_completed" in ev_types
    assert ev_types.index("route_started") < ev_types.index("route_completed") < ev_types.index("run_started")
    assert any(e["type"] == "tool" and e.get("callId") == "rt1" for e in d_auto["events"])

    # 对照：显式运行详情无 routing 字段且无路由事件
    d_exp = (await auto_client.get(f"/api/v1/runs/{explicit_run_id}", headers=admin_hdrs)).json()
    assert "routing" not in d_exp
    assert all(e["type"] not in ("route_started", "route_completed", "route_failed") for e in d_exp["events"])


# ============================================================================ 场景 12：StepMapper 路由事件脱敏步骤映射
def test_12_step_mapper_maps_and_sanitizes_route_events():
    """场景 12：StepMapper 正确映射 route_started / route_completed / route_failed 及路由工具，且严格脱敏。"""
    mapper = StepMapper()

    # 1) route_started（带 routerSkill 与无 routerSkill 两种分支）
    s1 = mapper.feed(ProcessEvent(1, "route_started", 10, 0, {"rev": "r3", "routerSkill": "template-router"}))
    assert s1 is not None and s1["seq"] == 1 and s1["icon"] == "start" and s1["ok"] is True
    assert "template-router" in s1["text"] and "r3" in s1["text"]

    s2 = mapper.feed(ProcessEvent(2, "route_started", 20, 0, {"rev": "r3", "routerSkill": None}))
    assert s2 is not None and s2["seq"] == 2 and s2["icon"] == "start" and s2["ok"] is True
    assert "检索在线模板" in s2["text"]

    # 2) 路由工具 list_templates / get_template / load_skill
    s3 = mapper.feed(
        ProcessEvent(3, "tool", 30, 0, {"tool": "list_templates", "ok": True, "args": {}, "result": {"count": 5}})
    )
    assert s3 is not None and s3["icon"] == "tool" and s3["ok"] is True and "检索在线模板" in s3["text"]

    s4 = mapper.feed(
        ProcessEvent(4, "tool", 40, 0, {"tool": "get_template", "ok": True, "args": {"templateId": 1001}, "result": {"id": 1001}})
    )
    assert s4 is not None and s4["icon"] == "tool" and s4["ok"] is True and "查看模板详情" in s4["text"]

    # 3) route_completed
    s5 = mapper.feed(
        ProcessEvent(
            5,
            "route_completed",
            55,
            0,
            {"templateId": 1001, "templateName": "业务办理争议类", "confidence": "低", "durationMs": 45},
        )
    )
    assert s5 is not None and s5["seq"] == 5 and s5["icon"] == "check" and s5["ok"] is True
    assert "#1001" in s5["text"] and "业务办理争议类" in s5["text"] and "置信度：低" in s5["text"]

    # 4) route_failed：注入手机号、本地路径、Bearer 凭证、sk- 密钥与引号字面量，验证全部脱敏
    s6 = mapper.feed(
        ProcessEvent(
            6,
            "route_failed",
            80,
            0,
            {
                "error": (
                    "手机号 13900001234 在 /Users/alice/secret.txt 触发异常 "
                    "Bearer tok_secret999 sk-abcdef123456 '客户隐私原文'"
                ),
            },
        )
    )
    assert s6 is not None and s6["seq"] == 6 and s6["icon"] == "error" and s6["ok"] is False
    assert s6["text"].startswith("自动匹配模板失败：")
    assert "13900001234" not in s6["text"]
    assert "/Users/alice/secret.txt" not in s6["text"]
    assert "tok_secret999" not in s6["text"]
    assert "sk-abcdef123456" not in s6["text"]
    assert "客户隐私原文" not in s6["text"]

    # 5) events_to_steps 批量兼容序列化字典格式（与 RunStore 落盘一致）
    batch = events_to_steps([
        {"seq": 1, "type": "route_started", "atMs": 5, "round": 0, "rev": "r1", "routerSkill": "template-router"},
        {"seq": 2, "type": "route_completed", "atMs": 35, "round": 0, "templateId": 1001, "templateName": "业务办理争议类", "confidence": "高"},
        {"seq": 3, "type": "run_started", "atMs": 40, "round": 0, "templateId": 1001, "templateName": "业务办理争议类", "rev": "r1"},
    ])
    assert [s["icon"] for s in batch] == ["start", "check", "start"]
    assert [s["seq"] for s in batch] == [1, 2, 3]


# ============================================================================ 额外边界：build_container 独立隔离回归
async def test_router_agent_cache_invalidates_on_reload_model(settings, case_c01):
    """验证 TemplateRouter 随 AgentRunner._bundle 热替换立即失效重建，不沿用旧模型。"""
    calls: list[str] = []

    def _router_v1(_m: list[ModelMessage], _i: AgentInfo) -> ModelResponse:
        calls.append("v1")
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": 1001,
                        "confidence": "高",
                        "reason": "v1 命中",
                        "candidates": [{"templateId": 1001, "level": "高", "reason": "v1"}],
                    },
                )
            ]
        )

    def _router_v2(_m: list[ModelMessage], _i: AgentInfo) -> ModelResponse:
        calls.append("v2")
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": 1001,
                        "confidence": "中",
                        "reason": "v2 命中",
                        "candidates": [{"templateId": 1001, "level": "中", "reason": "v2"}],
                    },
                )
            ]
        )

    c = build_container(settings, model=_route_and_report_model(_router_v1, scripted))
    UserStore(c.layout.config / "users.yaml").upsert("chenxiaoyun", "pass-1234", "陈晓芸", "业务维护")
    app = create_app(container=c)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as cl:
            r1 = await cl.post(
                "/api/v1/reports",
                json={"params": case_c01["inputs"], "document": case_c01["documentText"]},
                headers=API_KEY_HEADERS,
            )
            assert r1.status_code == 200 and r1.json()["routing"]["confidence"] == "高"

            # 模拟热更新切换 _bundle（seq 递增，不手动清空 _router._cached_agent）
            c.runner._bundle = dataclasses.replace(
                c.runner._bundle,
                model=_route_and_report_model(_router_v2, scripted),
                seq=c.runner._bundle.seq + 1,
            )
            r2 = await cl.post(
                "/api/v1/reports",
                json={"params": case_c01["inputs"], "document": case_c01["documentText"]},
                headers=API_KEY_HEADERS,
            )
            assert r2.status_code == 200 and r2.json()["routing"]["confidence"] == "中"
    assert calls == ["v1", "v2"]
