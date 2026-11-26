"""运行记录「非找到字段」确定性归因摘要、按需 AI 总结缓存与离线 HTML 同步测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from report_agent.api.auth import UserStore
from report_agent.api.missing_summary import build_missing_summary
from report_agent.main import create_app


# ============================================================================ 1. 确定性归因分类单测
def test_build_missing_summary_all_found():
    """全部字段均找到时返回零缺失摘要。"""
    run = {
        "runId": "20261126230001000allok1",
        "fields": [
            {"name": "业务名称", "visible": True, "shown": True, "status": "found", "value": "5G套餐"},
            {"name": "订购短信", "visible": True, "shown": True, "status": "found", "value": "已开通"},
        ],
        "apiResults": [],
        "validationRounds": [],
    }
    res = build_missing_summary(run)
    assert res["totalFields"] == 2
    assert res["foundCount"] == 2
    assert res["nonFoundCount"] == 0
    assert res["impactedCount"] == 0
    assert res["groups"] == []
    assert "无缺失项" in res["headline"]


def test_build_missing_summary_only_condition_skipped():
    """仅存在条件分支跳过字段时，impactedCount 为 0 且摘要明确提示不影响成稿。"""
    run = {
        "runId": "20261126230002000skip01",
        "fields": [
            {"name": "业务名称", "visible": True, "shown": True, "status": "found", "value": "5G套餐"},
            {
                "name": "二次确认短信",
                "visible": True,
                "shown": False,
                "status": "not_found",
                "whenMissing": "placeholder",
                "reasoning": "展示条件不满足（受理渠道为其他，非热线），跳过。",
            },
            {
                "name": "验证码短信",
                "visible": True,
                "shown": False,
                "status": "not_found",
                "whenMissing": "placeholder",
                "reasoning": "展示条件不满足（受理渠道为其他，非掌上营业厅），跳过。",
            },
        ],
        "apiResults": [],
        "validationRounds": [],
    }
    res = build_missing_summary(run)
    assert res["nonFoundCount"] == 2
    assert res["skippedCount"] == 2
    assert res["impactedCount"] == 0
    assert res["shownMissingCount"] == 0
    assert [g["code"] for g in res["groups"]] == ["condition_skipped"]
    assert "不影响最终成稿" in res["headline"]


def test_build_missing_summary_mixed_root_causes():
    """混合场景：接口报错、接口无记录、证据校验降级、原文无记载、默认值兜底与条件跳过精确归类。"""
    run = {
        "runId": "20261126230003000mixed1",
        "status": "PARTIAL",
        "fields": [
            {"name": "业务名称", "visible": True, "shown": True, "status": "found", "value": "流量包8元"},
            {
                "name": "订购短信",
                "visible": True,
                "shown": True,
                "status": "not_found",
                "whenMissing": "placeholder",
                "reasoning": "调用 querySMSSendInfo 两次均失败（ok=false，业务返回码 17），无法获取短信记录。",
            },
            {
                "name": "鉴权方式",
                "visible": True,
                "shown": True,
                "status": "not_found",
                "whenMissing": "placeholder",
                "reasoning": "query-pdf-text 返回 count=0，未查到属于本次业务的单据。",
            },
            {
                "name": "违约时间",
                "visible": True,
                "shown": True,
                "status": "not_found",
                "whenMissing": "placeholder",
                "reasoning": "已通读单据全文，其中仅有违约规则，未记载具体违约发生时间。",
            },
            {
                "name": "原套餐名称",
                "visible": True,
                "shown": True,
                "status": "not_found",
                "whenMissing": "placeholder",
                "validationFailed": True,
                "retried": True,
                "reasoning": "原提取值未通过核验。",
            },
            {
                "name": "是否录音",
                "visible": True,
                "shown": True,
                "status": "not_found",
                "whenMissing": "value",
                "reasoning": "受理渠道未能确定，按默认值兜底输出。",
            },
            {
                "name": "受理渠道",
                "visible": False,
                "shown": False,
                "status": "not_found",
                "whenMissing": "value",
                "reasoning": "querySMSSendInfo 返回码 17，无短信可判定渠道。",
            },
            {
                "name": "二次确认短信",
                "visible": True,
                "shown": False,
                "status": "not_found",
                "whenMissing": "placeholder",
                "reasoning": "展示条件不满足，跳过。",
            },
        ],
        "apiResults": [
            {
                "resultId": "r1",
                "api": "query-pdf-text",
                "title": "查询单据正文",
                "ok": True,
                "noData": True,
                "records": [],
            },
            {
                "resultId": "r2",
                "api": "querySMSSendInfo",
                "title": "短信发送记录查询",
                "ok": False,
                "error": "业务返回码 17：能力编排执行错误",
                "records": [],
            },
        ],
        "validationRounds": [[{"field": "原套餐名称", "message": "引用片段未在目标行中找到"}]],
    }
    res = build_missing_summary(run)
    assert res["totalFields"] == 8
    assert res["foundCount"] == 1
    assert res["nonFoundCount"] == 7
    assert res["shownMissingCount"] == 4
    assert res["defaultFallbackCount"] == 2
    assert res["skippedCount"] == 1
    assert res["impactedCount"] == 6

    by_code = {g["code"]: [f["name"] for f in g["fields"]] for g in res["groups"]}
    assert set(by_code["api_error"]) == {"订购短信", "受理渠道"}
    assert by_code["validation_failed"] == ["原套餐名称"]
    assert by_code["api_no_data"] == ["鉴权方式"]
    assert by_code["not_in_source"] == ["违约时间"]
    assert by_code["dependency_missing"] == ["是否录音"]
    assert by_code["condition_skipped"] == ["二次确认短信"]

    # 校验退回具体原因附带在 briefReason 中
    val_field = next(g for g in res["groups"] if g["code"] == "validation_failed")["fields"][0]
    assert "引用片段未在目标行中找到" in val_field["briefReason"]

    # rootCauses 覆盖失败接口、空接口、校验失败与原文缺失
    rc_codes = {rc["code"] for rc in res["rootCauses"]}
    assert {"api_error", "api_no_data", "validation_failed", "not_in_source"} <= rc_codes
    assert "querySMSSendInfo" in res["headline"]
    assert "订购短信" in res["plainText"]


# ============================================================================ 2. API + 按需 AI 总结缓存 + 离线 HTML 同步
@pytest.fixture
def summary_client(container):
    UserStore(container.layout.config / "users.yaml").upsert("admin", "pass-1234", "管理员", "平台管理")
    app = create_app(container=container)
    with TestClient(app) as cl:
        yield cl


def _login_headers(cl: TestClient) -> dict[str, str]:
    r = cl.post("/api/v1/auth/login", json={"username": "admin", "password": "pass-1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _extract_payload(html_text: str) -> dict[str, Any]:
    m = re.search(
        r'<script id="agent-replay-payload" type="application/json">(.*?)</script>',
        html_text,
        re.DOTALL,
    )
    assert m is not None
    return json.loads(m.group(1))


def test_missing_summary_ai_endpoint_cache_and_export(summary_client: TestClient, container):
    """验证详情返回确定性摘要、按需 AI 总结落盘缓存与 force 刷新、以及离线 HTML 同步包含。"""
    headers = _login_headers(summary_client)

    calls = {"n": 0}

    def fake_llm(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        return ModelResponse(
            parts=[
                TextPart(
                    content=(
                        f"**核心结论**：第 {calls['n']} 次总结——因短信接口报错导致 1 项展示字段缺失。\n"
                        "- **接口报错**：`订购短信` 受 `querySMSSendInfo` 返回码 17 影响未取得记录。\n"
                        "- **建议处理**：请在接口管理中对 `querySMSSendInfo` 做拨测确认历史日期窗口。"
                    )
                )
            ]
        )

    container.runner.model = FunctionModel(fake_llm)

    run_id = "20261126231000001sumai1"
    detail_doc = {
        "runId": run_id,
        "startTime": "2026-11-26T23:10:00+08:00",
        "templateId": 1001,
        "templateName": "样例核查模板",
        "rev": "r1",
        "entry": "试运行",
        "operator": "管理员",
        "status": "PARTIAL",
        "inputs": {"手机号码": "13900001234", "业务名称": "5G畅享套餐"},
        "document": "",
        "report": "核查报告：{{订购短信}}",
        "fields": [
            {"name": "业务名称", "visible": True, "shown": True, "status": "found", "value": "5G畅享套餐"},
            {
                "name": "订购短信",
                "visible": True,
                "shown": True,
                "status": "not_found",
                "whenMissing": "placeholder",
                "reasoning": "querySMSSendInfo 返回码 17 调用失败。",
            },
        ],
        "missingShown": ["订购短信"],
        "foundCount": 1,
        "totalCount": 2,
        "durationMs": 3200,
        "rounds": 2,
        "apiResults": [
            {
                "resultId": "r1",
                "api": "querySMSSendInfo",
                "title": "短信发送记录查询",
                "ok": False,
                "error": "业务返回码 17：编排错误",
                "records": [],
            }
        ],
        "toolCalls": [],
        "validationRounds": [],
        "events": [],
    }
    summary_doc = {
        "runId": run_id,
        "startTime": detail_doc["startTime"],
        "templateId": 1001,
        "templateName": "样例核查模板",
        "rev": "r1",
        "entry": "试运行",
        "status": "PARTIAL",
        "mobile": "13900001234",
        "busiName": "5G畅享套餐",
        "found": 1,
        "total": 2,
        "durationMs": 3200,
        "rounds": 2,
    }
    container.runs.submit(summary_doc, detail_doc)

    # 1) GET 运行详情自带确定性摘要，AI 总结初始为空
    r_get = summary_client.get(f"/api/v1/runs/{run_id}", headers=headers)
    assert r_get.status_code == 200
    ms = r_get.json()["missingSummary"]
    assert ms["nonFoundCount"] == 1
    assert ms["shownMissingCount"] == 1
    assert ms["aiSummary"] is None
    assert ms["groups"][0]["code"] == "api_error"

    # 2) 首次 POST 触发 AI 总结并持久化
    r_ai1 = summary_client.post(f"/api/v1/runs/{run_id}/missing-summary/ai", json={"force": False}, headers=headers)
    assert r_ai1.status_code == 200, r_ai1.text
    b1 = r_ai1.json()
    assert b1["cached"] is False
    assert calls["n"] == 1
    assert "第 1 次总结" in b1["aiSummary"]["text"]

    # 3) 再次 POST（force=False）直接命中持久化缓存，不重复调模型
    r_ai2 = summary_client.post(f"/api/v1/runs/{run_id}/missing-summary/ai", json={"force": False}, headers=headers)
    assert r_ai2.status_code == 200
    b2 = r_ai2.json()
    assert b2["cached"] is True
    assert calls["n"] == 1
    assert "第 1 次总结" in b2["aiSummary"]["text"]

    # 4) force=True 强制重生成并覆盖缓存
    r_ai3 = summary_client.post(f"/api/v1/runs/{run_id}/missing-summary/ai", json={"force": True}, headers=headers)
    assert r_ai3.status_code == 200
    b3 = r_ai3.json()
    assert b3["cached"] is False
    assert calls["n"] == 2
    assert "第 2 次总结" in b3["aiSummary"]["text"]

    # 5) 再次 GET 详情与离线 HTML 导出均同步携带缓存后的 AI 总结与确定性摘要
    r_get2 = summary_client.get(f"/api/v1/runs/{run_id}", headers=headers)
    assert "第 2 次总结" in r_get2.json()["missingSummary"]["aiSummary"]["text"]

    r_exp = summary_client.post("/api/v1/runs/export-html", json={"runIds": [run_id]}, headers=headers)
    assert r_exp.status_code == 200
    payload = _extract_payload(r_exp.text)
    exp_ms = payload["runs"][0]["missingSummary"]
    assert exp_ms["nonFoundCount"] == 1
    assert "第 2 次总结" in exp_ms["aiSummary"]["text"]
    assert "renderMissingSummaryHtml" in r_exp.text

    # 6) 全部找到的记录调用 AI 总结返回 400 NO_MISSING_FIELDS
    ok_id = "20261126231001002allok2"
    container.runs.submit(
        {**summary_doc, "runId": ok_id, "status": "SUCCESS", "found": 1, "total": 1},
        {
            **detail_doc,
            "runId": ok_id,
            "status": "SUCCESS",
            "fields": [{"name": "业务名称", "visible": True, "shown": True, "status": "found", "value": "5G畅享套餐"}],
            "missingShown": [],
            "foundCount": 1,
            "totalCount": 1,
        },
    )
    r_none = summary_client.post(f"/api/v1/runs/{ok_id}/missing-summary/ai", headers=headers)
    assert r_none.status_code == 400
    assert r_none.json()["code"] == "NO_MISSING_FIELDS"
