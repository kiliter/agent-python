"""多业务复合工单编排全链路测试（汇总大模板治理、SharedGatewayClient 缓存去重、并发拼装、AI 二次润色、上游与聊天接口）。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from report_agent.api.auth import UserStore
from report_agent.container import build_container
from report_agent.domain.api_contract import ApiContract
from report_agent.domain.composite import (
    DEFAULT_COMPOSITE_TEMPLATE,
    build_composite_summary,
    render_composite_report,
    sample_composite_context,
    validate_composite_template,
)
from report_agent.gateway.base import ApiCallResult, GatewayClient
from report_agent.main import create_app
from report_agent.runtime.composite import (
    CompositeItemRequest,
    CompositeRunRequest,
    CompositeRunner,
    SharedGatewayClient,
)
from scripted_model import scripted

API_KEY_HEADERS = {"X-API-Key": "upstream-key"}


def _is_polish_agent(info: AgentInfo) -> bool:
    """识别 CompositeRunner 二次润色调用（output_tool 名称为 submit_polished_report）。"""
    return any(t.name == "submit_polished_report" for t in info.output_tools)


def _composite_model(
    polished_text: str = "# 二次润色后的汇总报告\n\n经综合核查，三项业务均已核实。",
) -> FunctionModel:
    """组合桩模型：填报子项走 scripted，二次润色走固定结构化输出。"""

    def _dispatch(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if _is_polish_agent(info):
            return ModelResponse(
                parts=[ToolCallPart("submit_polished_report", {"markdown": polished_text}, tool_call_id="p-1")]
            )
        if not info.output_tools and any("润色" in str(p) for m in messages for p in m.parts):
            return ModelResponse(parts=[TextPart(polished_text)])
        return scripted(messages, info)

    return FunctionModel(_dispatch, model_name="scripted-composite-dual")


def _parse_sse(raw: str) -> list[dict[str, Any]]:
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


@pytest.fixture
def comp_container(settings):
    """带组合桩模型（填报 + 二次润色）的独立测试容器。"""
    return build_container(settings, model=_composite_model())


@pytest.fixture
async def comp_client(comp_container):
    UserStore(comp_container.layout.config / "users.yaml").upsert(
        "chenxiaoyun", "pass-1234", "陈晓芸", "业务维护"
    )
    app = create_app(container=comp_container)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as cl:
            yield cl


async def _admin_headers(cl: httpx.AsyncClient) -> dict[str, str]:
    r = await cl.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "pass-1234"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    cl.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def test_composite_template_validation_and_render():
    """汇总大模板语法校验、样例渲染与非法语法拦截。"""
    assert validate_composite_template(DEFAULT_COMPOSITE_TEMPLATE) == []
    errs = validate_composite_template("{% for x in items %}{{ x.label }")
    assert errs and "语法错误" in errs[0]

    ctx = sample_composite_context()
    rendered = render_composite_report(
        DEFAULT_COMPOSITE_TEMPLATE,
        order=ctx["order"],
        items=ctx["items"],
    )
    assert "核查情况汇总如下" in rendered
    assert "3 项" in rendered
    assert "套餐接续直降80元加享翻倍流量" in rendered

    summary = build_composite_summary(ctx["items"])
    assert summary["totalItems"] == 3
    assert summary["successCount"] == 2
    assert summary["partialCount"] == 1
    assert summary["failedCount"] == 0


@pytest.mark.asyncio
async def test_shared_gateway_client_deduplicates_concurrent_idempotent_calls():
    """同次复合运行下，3 个并发子项调用相同幂等接口仅实际请求底层网关 1 次。"""

    class _SlowCountingGateway(GatewayClient):
        def __init__(self) -> None:
            self.calls = 0

        async def invoke(self, contract: ApiContract, args: dict[str, Any]) -> ApiCallResult:
            self.calls += 1
            await asyncio.sleep(0.02)
            return ApiCallResult(ok=True, records=[{"sms": "ok", "args": dict(args)}], cost_ms=20)

    inner = _SlowCountingGateway()
    shared = SharedGatewayClient(inner)
    contract = ApiContract(
        name="qry_sms",
        title="查短信",
        description="查询短信",
        idempotent=True,
    )
    args = {"mobileNo": "13800138000", "beginTime": "20251012000000"}

    r1, r2, r3 = await asyncio.gather(
        shared.invoke(contract, args),
        shared.invoke(contract, args),
        shared.invoke(contract, args),
    )
    assert inner.calls == 1
    assert shared.cache_hits == 2
    assert r1.ok and r2.ok and r3.ok
    # 返回副本彼此隔离，修改一个不污染缓存
    r1.records[0]["sms"] = "mutated"
    r4 = await shared.invoke(contract, args)
    assert r4.records[0]["sms"] == "ok"
    assert inner.calls == 1
    assert shared.cache_hits == 3


@pytest.mark.asyncio
async def test_composite_template_settings_lifecycle(comp_client):
    """汇总大模板管理接口：读取、保存草稿、发布、改回线上自动清理、样例预览与版本回退。"""
    headers = await _admin_headers(comp_client)

    r0 = await comp_client.get("/api/v1/settings/composite-template", headers=headers)
    assert r0.status_code == 200, r0.text
    d0 = r0.json()
    assert d0["templateText"]
    assert d0["draft"] is None

    # 1. 非法语法草稿被拦截
    r_bad = await comp_client.put(
        "/api/v1/settings/composite-template/draft",
        headers=headers,
        json={"templateText": "{% if items %}未闭合"},
    )
    assert r_bad.status_code == 400

    # 2. 保存合法草稿 -> 发布 -> 再改并改回与线上一致，确认草稿自动清空且状态回落 PUBLISHED
    custom_tpl = "# 定制汇总\n号码：{{ order.mobileNo }}\n{% for it in items %}- {{ it.label }}\n{% endfor %}"
    r_save = await comp_client.put(
        "/api/v1/settings/composite-template/draft",
        headers=headers,
        json={"templateText": custom_tpl},
    )
    assert r_save.status_code == 200, r_save.text
    assert r_save.json()["draft"] is not None
    assert r_save.json()["status"] in ("DRAFT", "PUBLISHED_DRAFT")

    r_pub = await comp_client.post(
        "/api/v1/settings/composite-template/publish",
        headers=headers,
        json={"note": "定制汇总排版"},
    )
    assert r_pub.status_code == 200, r_pub.text
    rev_custom = r_pub.json()["rev"]

    r_mod = await comp_client.put(
        "/api/v1/settings/composite-template/draft",
        headers=headers,
        json={"templateText": custom_tpl + "\n尾注"},
    )
    assert r_mod.status_code == 200
    assert r_mod.json()["draft"] is not None
    assert r_mod.json()["status"] == "PUBLISHED_DRAFT"

    r_revert = await comp_client.put(
        "/api/v1/settings/composite-template/draft",
        headers=headers,
        json={"templateText": custom_tpl},
    )
    assert r_revert.status_code == 200
    assert r_revert.json()["cleared"] is True
    assert r_revert.json()["draft"] is None
    assert r_revert.json()["status"] == "PUBLISHED"

    # 3. 实时预览接口
    r_prev = await comp_client.post(
        "/api/v1/settings/composite-template/preview",
        headers=headers,
        json={"templateText": custom_tpl},
    )
    assert r_prev.status_code == 200
    assert r_prev.json()["ok"] is True
    assert "定制汇总" in r_prev.json()["rendered"]

    # 4. 历史版本列表与回退
    r_revs = await comp_client.get("/api/v1/settings/composite-template/revisions", headers=headers)
    assert r_revs.status_code == 200
    revs = r_revs.json()
    assert any(rv["rev"] == rev_custom for rv in revs)


@pytest.mark.asyncio
async def test_composite_runner_and_upstream_api(comp_container, comp_client, case_c01):
    """复合工单并发核查、部分失败隔离、二次润色以及上游 /reports/composite & /polish 契约。"""
    base_inputs = dict(case_c01["inputs"])
    doc_text = case_c01["documentText"]

    # 1. 直接验证 CompositeRunner（2 项有效 + 1 项缺失模板隔离 + 共享文档/独立文档覆盖）
    comp = CompositeRunner(comp_container.runner)
    res = await comp.run(
        CompositeRunRequest(
            order=base_inputs,
            document=doc_text,
            items=[
                CompositeItemRequest(
                    template_id=1001,
                    label="产品A-套餐直降",
                    params={"busiName": base_inputs.get("busiName", "宽带提速包")},
                ),
                CompositeItemRequest(
                    template_id=1001,
                    label="产品B-会员包",
                    params={"busiName": base_inputs.get("busiName", "宽带提速包")},
                    document=doc_text,
                ),
                CompositeItemRequest(
                    template_id=99999,
                    label="产品C-不存在模板",
                    params={"busiName": "未知业务"},
                ),
            ],
            polish=True,
            polish_instruction="请精炼汇总",
            entry="上游调用",
        )
    )
    assert res["status"] == "PARTIAL"
    assert len(res["items"]) == 3
    assert res["items"][0]["status"] == "SUCCESS"
    assert res["items"][1]["status"] == "SUCCESS"
    assert res["items"][2]["status"] == "FAILED"
    assert "产品A-套餐直降" in res["assembledMarkdown"]
    assert "产品B-会员包" in res["assembledMarkdown"]
    assert "产品C-不存在模板" in res["assembledMarkdown"]
    assert res["polishedMarkdown"] is not None
    assert "二次润色后的汇总报告" in res["polishedMarkdown"]
    assert res["markdown"] == res["polishedMarkdown"]
    # 相同号码与同日网关短信查询在两项有效子模板间复用缓存
    assert res["sharedGatewayHits"] >= 1

    # 2. 上游接口 POST /api/v1/reports/composite + POST /api/v1/reports/composite/polish
    r_up = await comp_client.post(
        "/api/v1/reports/composite",
        headers=API_KEY_HEADERS,
        json={
            "order": base_inputs,
            "document": doc_text,
            "items": [
                {"templateId": 1001, "label": "业务一", "params": {"busiName": base_inputs.get("busiName", "")}},
                {"templateId": 1001, "label": "业务二", "params": {"busiName": base_inputs.get("busiName", "")}},
            ],
            "polish": False,
        },
    )
    assert r_up.status_code == 200, r_up.text
    body = r_up.json()
    assert body["status"] == "SUCCESS"
    assert body["polished"] is False
    assert body["assembledMarkdown"] == body["markdown"]
    assert body["sharedGatewayHits"] >= 1
    assert len(body["items"]) == 2

    r_pol = await comp_client.post(
        "/api/v1/reports/composite/polish",
        headers=API_KEY_HEADERS,
        json={"markdown": body["assembledMarkdown"], "instruction": "合并重复表述"},
    )
    assert r_pol.status_code == 200, r_pol.text
    assert "二次润色后的汇总报告" in r_pol.json()["markdown"]
    assert r_pol.json()["verified"] is False


@pytest.mark.asyncio
async def test_chat_composite_run_sse_polish_and_confirm(comp_client, case_c01):
    """嵌入式聊天窗口多商品会话创建、并发复合运行 SSE、事后二次润色与确认回传。"""
    base_inputs = dict(case_c01["inputs"])
    doc_text = case_c01["documentText"]

    # 1. 创建含多商品 items[] 的会话
    r_sess = await comp_client.post(
        "/api/v1/chat/sessions",
        headers=API_KEY_HEADERS,
        json={
            "userId": "seat-multi",
            "orderId": "ORD-MULTI-01",
            "inputs": base_inputs,
            "document": doc_text,
            "items": [
                {"label": "业务一", "params": {"busiName": base_inputs.get("busiName", "")}, "templateId": 1001},
                {"label": "业务二", "params": {"busiName": base_inputs.get("busiName", "")}, "templateId": 1001},
            ],
        },
    )
    assert r_sess.status_code == 200, r_sess.text
    sess = r_sess.json()
    sid = sess["sessionId"]
    assert len(sess["items"]) == 2

    chat_headers = {**API_KEY_HEADERS, "X-Chat-Session-Id": sid}

    # 2. 发起复合运行（开启同步润色）
    r_run = await comp_client.post(
        f"/api/v1/chat/sessions/{sid}/composite-runs",
        headers=chat_headers,
        json={
            "items": [
                {"templateId": 1001, "label": "业务一", "params": {"busiName": base_inputs.get("busiName", "")}},
                {"templateId": 1001, "label": "业务二", "params": {"busiName": base_inputs.get("busiName", "")}},
            ],
            "polish": True,
            "polishInstruction": "合并重复落款",
        },
    )
    assert r_run.status_code == 200, r_run.text
    run_msg = r_run.json()["message"]
    run_id = run_msg["runId"]
    assert run_msg["isComposite"] is True

    # 3. 订阅运行事件流直至 final
    r_sse = await comp_client.get(
        f"/api/v1/chat/runs/{run_id}/events",
        headers=chat_headers,
    )
    assert r_sse.status_code == 200, r_sse.text
    events = _parse_sse(r_sse.text)
    finals = [e["data"] for e in events if e["event"] == "final"]
    assert len(finals) == 1
    final_card = finals[0]
    assert final_card["status"] == "SUCCESS"
    assert final_card["isComposite"] is True
    assert len(final_card["compositeItems"]) == 2
    assert final_card["sharedGatewayHits"] >= 1
    # v1 确定性拼装原版 + v2 大模型二次润色版
    assert len(final_card["versions"]) == 2
    assert final_card["versions"][0]["kind"] == "original"
    assert final_card["versions"][1]["kind"] == "rewrite"
    assert "二次润色后的汇总报告" in final_card["versions"][1]["markdown"]

    # 4. 事后一键再次润色（追加 v3）
    r_p2 = await comp_client.post(
        f"/api/v1/chat/runs/{run_id}/polish",
        headers=chat_headers,
        json={"instruction": "语气更正式"},
    )
    assert r_p2.status_code == 200, r_p2.text
    assert r_p2.json()["versionNo"] == 3
    assert len(r_p2.json()["message"]["versions"]) == 3

    # 5. 确认回传复合汇总报告
    r_confirm = await comp_client.post(
        f"/api/v1/chat/runs/{run_id}/confirm",
        headers=chat_headers,
        json={"markdown": final_card["versions"][0]["markdown"]},
    )
    assert r_confirm.status_code == 200, r_confirm.text
    payload = r_confirm.json()["payload"]
    assert payload["runId"] == run_id
    assert payload["status"] == "SUCCESS"
