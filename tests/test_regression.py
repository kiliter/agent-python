"""全平台回归测试工作台（固定模板 + 未绑定模板自动路由 + 单版/双版 SSE 回归 + 基线采纳）自动化测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
from typing import Any

import httpx
import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from report_agent.api.auth import UserStore
from report_agent.container import Container
from report_agent.main import create_app
from report_agent.store.cases import AUTO_CASE_SCOPE, CaseDef, CaseStore, parse_case_scope, scope_key
from report_agent.store.layout import InvalidResource
from scripted_model import scripted


# ============================================================================ 公共测试辅助
def _is_router_agent(info: AgentInfo) -> bool:
    """判断当前模型调用是否属于无状态 TemplateRouter。"""
    return any(t.name == "submit_route_decision" for t in info.output_tools)


def _route_and_report_model(route_fn: Any, report_fn: Any = scripted) -> FunctionModel:
    """按 Agent 类型把路由调用与填报调用分派给不同确定性桩函数。"""

    async def _dispatch(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        target = route_fn if _is_router_agent(info) else report_fn
        res = target(messages, info)
        if inspect.isawaitable(res):
            return await res
        return res

    return FunctionModel(_dispatch, model_name="scripted-regression")


def _swap_model(container: Container, model: FunctionModel) -> None:
    """热替换测试容器内 AgentRunner 与 TemplateRouter 的桩模型并清空缓存。"""
    container.runner._bundle = dataclasses.replace(container.runner._bundle, model=model)
    container.runner._agent_cache.clear()
    container.runner._router._cached_agent = None


def _fixed_route_to(tid: int, reason: str = "命中测试模板") -> Any:
    """构造直接返回指定模板 ID 的路由桩函数。"""

    def _router(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "submit_route_decision",
                    {
                        "matched": True,
                        "templateId": tid,
                        "confidence": "高",
                        "reason": reason,
                        "candidates": [{"templateId": tid, "level": "高", "reason": reason}],
                    },
                )
            ]
        )

    return _router


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    """解析标准 SSE 帧序列。"""
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


async def _flush_runs(container: Container) -> None:
    """等待 RunStore 后台写协程刷盘。"""
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
async def reg_client(container: Container):
    """带完整 lifespan 的异步测试客户端。"""
    UserStore(container.layout.config / "users.yaml").upsert("chenxiaoyun", "pass-1234", "陈晓芸", "业务维护")
    app = create_app(container=container)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as cl:
            yield cl


# ============================================================================ 1. CaseStore 自动路由与迁移
def test_case_store_auto_scope_and_move(container: Container):
    """验证未绑定模板自动路由作用域（cases/auto/）、申诉内容映射、全局列出与跨作用域迁移。"""
    assert parse_case_scope(None) is None
    assert parse_case_scope("") is None
    assert parse_case_scope("auto") is None
    with pytest.raises(InvalidResource):
        parse_case_scope(0)
    with pytest.raises(InvalidResource):
        parse_case_scope(-1)
    assert parse_case_scope("1001") == 1001
    assert scope_key(None) == AUTO_CASE_SCOPE
    assert scope_key(1001) == "1001"

    auto_id = container.cases.next_id(None)
    assert auto_id == "A-01"
    c = CaseStore.from_payload({
        "id": auto_id,
        "name": "未绑定自动路由样例",
        "mobile": "13911112222",
        "busiName": "5G智享套餐",
        "appealContent": "客户否认订购该套餐，要求核实办理途径",
        "expectedTemplateId": 1001,
        "documentText": "单据正文样例",
    })
    assert c.inputs["申诉内容"] == "客户否认订购该套餐，要求核实办理途径"
    assert c.expectedTemplateId == 1001
    container.cases.save(None, c)

    # list_all 自动路由置顶，固定模板在后
    all_items = container.cases.list_all()
    assert all_items[0][0] is None and all_items[0][1].id == "A-01"
    assert any(tid == 1001 for tid, _ in all_items)

    # 迁移到固定模板 1001，再迁回 auto
    moved = container.cases.move(None, "A-01", 1001)
    assert moved.id == "A-01"
    assert container.cases.get(None, "A-01") is None
    assert container.cases.get(1001, "A-01") is not None

    moved_back = container.cases.move(1001, "A-01", None, updated=CaseDef(**moved.model_dump()))
    assert moved_back.id == "A-01"
    assert container.cases.get(1001, "A-01") is None
    assert container.cases.get(None, "A-01") is not None


# ============================================================================ 2. 全平台用例 CRUD 与迁移 API
async def test_regression_cases_crud_and_scope_migration(reg_client: httpx.AsyncClient):
    """验证 /api/v1/regression/cases 列表、创建、搜索、跨作用域迁移与删除。"""
    headers = await _admin_headers(reg_client)

    # 创建自动路由用例
    r = await reg_client.post(
        "/api/v1/regression/cases",
        headers=headers,
        json={
            "templateId": None,
            "id": "REG-AUTO-01",
            "name": "自动路由测试单",
            "mobile": "13800001111",
            "busiName": "5G畅享套餐",
            "appealContent": "用户称未收到二次确认短信",
            "expectedTemplateId": 1001,
            "documentText": "测试单据正文",
        },
    )
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["scope"] == "auto" and created["isAuto"] is True
    assert created["expectedTemplateId"] == 1001
    assert created["appealContent"] == "用户称未收到二次确认短信"

    # 按作用域和关键词筛选
    only_auto = (await reg_client.get("/api/v1/regression/cases?scope=auto", headers=headers)).json()
    assert [x["id"] for x in only_auto] == ["REG-AUTO-01"]
    searched = (await reg_client.get("/api/v1/regression/cases?q=未收到二次确认", headers=headers)).json()
    assert len(searched) == 1 and searched[0]["id"] == "REG-AUTO-01"

    # 更新并迁移为固定模板 1001，同时清空 expectedTemplateId
    r_upd = await reg_client.put(
        "/api/v1/regression/cases/auto/REG-AUTO-01",
        headers=headers,
        json={
            "changeScope": True,
            "targetTemplateId": 1001,
            "name": "已绑定模板1001",
            "clearExpectedTemplate": True,
        },
    )
    assert r_upd.status_code == 200, r_upd.text
    upd = r_upd.json()
    assert upd["scope"] == "1001" and upd["isAuto"] is False
    assert upd["expectedTemplateId"] is None and upd["name"] == "已绑定模板1001"

    # 删除
    r_del = await reg_client.delete("/api/v1/regression/cases/1001/REG-AUTO-01", headers=headers)
    assert r_del.status_code == 200 and r_del.json()["deletedId"] == "REG-AUTO-01"


# ============================================================================ 3. SSE 单版回归（固定模板 + 自动路由）与批次持久化
async def test_regression_single_run_fixed_and_auto_route_sse(
    reg_client: httpx.AsyncClient,
    container: Container,
    case_c01: dict[str, Any],
):
    """验证单版 SSE 批量回归同时执行固定模板与自动路由用例，回写用例状态并落盘批次历史。"""
    headers = await _admin_headers(reg_client)
    _swap_model(container, _route_and_report_model(_fixed_route_to(1001), scripted))

    # 新建一条未绑定模板的自动路由用例（复用 fixture case_c01 的脱敏入参与单据）
    r_create = await reg_client.post(
        "/api/v1/regression/cases",
        headers=headers,
        json={
            "templateId": None,
            "id": "AUTO-C01",
            "name": "自动路由-业务办理争议",
            "inputs": case_c01["inputs"],
            "documentText": case_c01["documentText"],
            "expectedTemplateId": 1001,
        },
    )
    assert r_create.status_code == 200, r_create.text

    # 发起 SSE 批量回归（1 条自动路由 + 1 条固定模板 1001/C01）
    resp = await reg_client.post(
        "/api/v1/regression/run/stream",
        headers=headers,
        json={
            "mode": "single",
            "targetA": "online",
            "cases": [
                {"scope": "auto", "caseId": "AUTO-C01"},
                {"scope": "1001", "caseId": "C-01"},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    events = _parse_sse(resp.text)
    ev_names = [e["event"] for e in events]
    assert ev_names[0] == "batch_start"
    assert ev_names.count("case_done") == 2
    assert ev_names[-1] == "batch_done"

    batch = events[-1]["data"]
    assert batch["totalCases"] == 2
    assert batch["executedCases"] == 2
    assert batch["passedCases"] == 2
    assert batch["failedCases"] == 0
    assert batch["routeMismatchCases"] == 0
    assert batch["passRate"] == 100.0

    auto_res = next(r for r in batch["results"] if r["caseId"] == "AUTO-C01")
    assert auto_res["isAuto"] is True
    assert auto_res["templateIdA"] == 1001
    assert auto_res["verdict"] == "通过"
    assert auto_res["runIdA"]

    await _flush_runs(container)

    # 验证用例 YAML 已被持久化回写最新结果与命中模板
    listed = (await reg_client.get("/api/v1/regression/cases?scope=auto", headers=headers)).json()
    assert listed[0]["lastResult"] == "通过"
    assert listed[0]["lastMatchedTemplateId"] == 1001
    assert listed[0]["lastRunId"] == auto_res["runIdA"]

    # 验证历史批次列表与详情可回查
    batches = (await reg_client.get("/api/v1/regression/batches", headers=headers)).json()
    assert batches and batches[0]["batchId"] == batch["batchId"]
    detail = (await reg_client.get(f"/api/v1/regression/batches/{batch['batchId']}", headers=headers)).json()
    assert len(detail["results"]) == 2


# ============================================================================ 4. 路由偏差与字段期望偏差检测
async def test_regression_route_mismatch_and_expected_field_diff(
    reg_client: httpx.AsyncClient,
    container: Container,
    case_c01: dict[str, Any],
):
    """验证自动路由命中与 expectedTemplateId 不符判定为「路由偏差」，字段偏离期望基线判定为「偏离期望」。"""
    headers = await _admin_headers(reg_client)
    _swap_model(container, _route_and_report_model(_fixed_route_to(1001), scripted))

    # 用例 1：期望模板 999，但自动路由实际命中 1001 → 路由偏差
    await reg_client.post(
        "/api/v1/regression/cases",
        headers=headers,
        json={
            "templateId": None,
            "id": "AUTO-WRONG-ROUTE",
            "name": "路由偏差用例",
            "inputs": case_c01["inputs"],
            "documentText": case_c01["documentText"],
            "expectedTemplateId": 999,
        },
    )
    # 用例 2：路由正确但受理渠道期望值故意写成错误值 → 偏离期望
    await reg_client.post(
        "/api/v1/regression/cases",
        headers=headers,
        json={
            "templateId": None,
            "id": "AUTO-WRONG-FIELD",
            "name": "字段偏离用例",
            "inputs": case_c01["inputs"],
            "documentText": case_c01["documentText"],
            "expectedTemplateId": 1001,
            "expectedValues": {"受理渠道": "线下营业厅"},
        },
    )

    resp = await reg_client.post(
        "/api/v1/regression/run/stream",
        headers=headers,
        json={
            "mode": "single",
            "targetA": "online",
            "cases": [
                {"scope": "auto", "caseId": "AUTO-WRONG-ROUTE"},
                {"scope": "auto", "caseId": "AUTO-WRONG-FIELD"},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    batch = _parse_sse(resp.text)[-1]["data"]
    assert batch["routeMismatchCases"] == 1
    assert batch["diffCases"] == 2
    assert batch["passedCases"] == 0

    res_route = next(r for r in batch["results"] if r["caseId"] == "AUTO-WRONG-ROUTE")
    assert res_route["verdict"] == "路由偏差"
    assert res_route["routeMismatch"] is True
    assert any(d["caseId"] == "AUTO-WRONG-ROUTE" and d["kind"] == "route_mismatch" for d in batch["diffs"])

    res_field = next(r for r in batch["results"] if r["caseId"] == "AUTO-WRONG-FIELD")
    assert res_field["verdict"] == "偏离期望"
    assert any(
        d["caseId"] == "AUTO-WRONG-FIELD" and d["field"] == "受理渠道" and d["kind"] == "expected_mismatch"
        for d in batch["diffs"]
    )


# ============================================================================ 5. 一键采纳基线（局部单字段 + 全量锁定模板）
async def test_regression_adopt_baseline_full_and_single_field(
    reg_client: httpx.AsyncClient,
    container: Container,
    case_c01: dict[str, Any],
):
    """验证从单次运行局部采纳单字段基线与全量采纳（含自动路由模板锁定）。"""
    headers = await _admin_headers(reg_client)
    _swap_model(container, _route_and_report_model(_fixed_route_to(1001), scripted))

    await reg_client.post(
        "/api/v1/regression/cases",
        headers=headers,
        json={
            "templateId": None,
            "id": "AUTO-ADOPT",
            "name": "待采纳基线用例",
            "inputs": case_c01["inputs"],
            "documentText": case_c01["documentText"],
            "expectedValues": {"受理渠道": "旧错误渠道"},
        },
    )
    resp = await reg_client.post(
        "/api/v1/regression/run/stream",
        headers=headers,
        json={
            "mode": "single",
            "targetA": "online",
            "cases": [{"scope": "auto", "caseId": "AUTO-ADOPT"}],
        },
    )
    batch = _parse_sse(resp.text)[-1]["data"]
    assert batch["results"][0]["verdict"] == "偏离期望"
    run_id = batch["results"][0]["runIdA"]
    await _flush_runs(container)

    # 先局部采纳单字段「受理渠道」，不锁模板
    r_part = await reg_client.post(
        "/api/v1/regression/cases/auto/AUTO-ADOPT/adopt-baseline",
        headers=headers,
        json={"runId": run_id, "adoptFields": True, "adoptTemplate": False, "onlyField": "受理渠道"},
    )
    assert r_part.status_code == 200, r_part.text
    part = r_part.json()
    assert part["expectedValues"]["受理渠道"] != "旧错误渠道"
    assert len(part["expectedValues"]) == 1
    assert part["expectedTemplateId"] is None

    # 再全量采纳字段并锁定自动路由模板 1001
    r_full = await reg_client.post(
        "/api/v1/regression/cases/auto/AUTO-ADOPT/adopt-baseline",
        headers=headers,
        json={"runId": run_id, "adoptFields": True, "adoptTemplate": True},
    )
    assert r_full.status_code == 200, r_full.text
    full = r_full.json()
    assert full["expectedTemplateId"] == 1001
    assert len(full["expectedValues"]) >= 3

    # 用采纳后的基线重新回归，必须 100% 通过
    resp2 = await reg_client.post(
        "/api/v1/regression/run/stream",
        headers=headers,
        json={
            "mode": "single",
            "targetA": "online",
            "cases": [{"scope": "auto", "caseId": "AUTO-ADOPT"}],
        },
    )
    batch2 = _parse_sse(resp2.text)[-1]["data"]
    assert batch2["passedCases"] == 1 and batch2["diffCases"] == 0
    assert batch2["results"][0]["verdict"] == "通过"


# ============================================================================ 6. 双版对比回归（Draft vs Online 字段差异）
async def test_regression_compare_draft_vs_online_diff(
    reg_client: httpx.AsyncClient,
    container: Container,
):
    """验证 mode=compare 双版对比能同时执行草稿与线上快照，并精确捕获逐字段差异与双边 runId。"""
    headers = await _admin_headers(reg_client)

    # 修改模板 1001 草稿：将「受理渠道」默认/说明微调，并通过受控桩在草稿版与线上版输出不同证据值
    detail = (await reg_client.get("/api/v1/templates/1001", headers=headers)).json()
    fields = list(detail["fields"])
    for f in fields:
        if f["name"] == "受理渠道":
            f["description"] = "DRAFT_MARKER_CHANNEL"
    r_draft = await reg_client.put(
        "/api/v1/templates/1001/draft",
        headers=headers,
        json={
            "bodyText": detail["bodyText"],
            "fields": fields,
            "inputs": detail["inputs"],
            "skills": detail["skills"],
        },
    )
    assert r_draft.status_code == 200, r_draft.text

    def _branch_report(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        # 复用 scripted，但在草稿版本（instructions 或 output_tools 含 DRAFT_MARKER_CHANNEL）中修改「受理渠道」
        res = scripted(messages, info)
        schema_blob = json.dumps(
            [getattr(t, "parameters_json_schema", {}) for t in (info.output_tools or [])],
            ensure_ascii=False,
        )
        prompt_blob = (info.instructions or "") + " " + schema_blob + " " + " ".join(
            str(getattr(p, "content", ""))
            for m in messages
            for p in getattr(m, "parts", ())
        )
        if "DRAFT_MARKER_CHANNEL" in prompt_blob:
            for part in res.parts:
                if isinstance(part, ToolCallPart) and part.tool_name == "submit_report":
                    args = json.loads(part.args) if isinstance(part.args, str) else dict(part.args)
                    # 把「受理渠道」改成未找到（草稿与线上产生真实可核验差异）
                    if "受理渠道" in args:
                        args["受理渠道"] = {
                            "status": "not_found",
                            "value": None,
                            "evidence": [],
                            "reasoning": "草稿规则收紧后未匹配到受理渠道",
                        }
                    return ModelResponse(parts=[ToolCallPart("submit_report", args)])
        return res

    _swap_model(container, _route_and_report_model(_fixed_route_to(1001), _branch_report))

    resp = await reg_client.post(
        "/api/v1/regression/run/stream",
        headers=headers,
        json={
            "mode": "compare",
            "targetA": "draft",
            "targetB": "online",
            "cases": [{"scope": "1001", "caseId": "C-01"}],
        },
    )
    assert resp.status_code == 200, resp.text
    batch = _parse_sse(resp.text)[-1]["data"]
    assert batch["mode"] == "compare"
    assert batch["diffCases"] == 1
    row = batch["results"][0]
    assert row["runIdA"] and row["runIdB"] and row["runIdA"] != row["runIdB"]
    assert row["verdict"] in ("有差异", "偏离期望")
    ch_diff = next(d for d in batch["diffs"] if d["field"] == "受理渠道")
    assert ch_diff["kind"] == "field_diff"
    assert ch_diff["valA"] != ch_diff["valB"]
    assert ch_diff["runIdA"] == row["runIdA"] and ch_diff["runIdB"] == row["runIdB"]
