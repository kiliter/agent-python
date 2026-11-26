"""运行记录单页离线 HTML 模拟回放导出（支持单条与多选）及 AST 字段条件跳过自动化测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from report_agent.api.auth import UserStore
from report_agent.api.run_export import render_runs_replay_html
from report_agent.domain.jinja_env import body_field_conditions
from report_agent.domain.template import FieldDef
from report_agent.main import create_app
from report_agent.runtime.prompt import _build_condition_guide, _resolve_skippable_conditions
from report_agent.runtime.runner import RunRequest


# ============================================================================ 1. Jinja2 AST 字段条件短路测试
def test_body_field_conditions_and_enum_coverage():
    """验证 AST 静态提取条件字段、枚举全覆盖过滤、自保护条件与循环局部变量边界。"""
    body = """
服务争议点：
{% if 争议类型 == "业务" %}
{{受理日期}} {{标准资费}} {{业务套餐内容}}
{% endif %}
{% if 争议类型 == "营销活动" %}
{{受理日期}} {{活动时间}} {{活动内容}}
{% endif %}
{% if 受理渠道 == "热线" %}
{{二次确认短信}}
{% elif 受理渠道 == "掌上营业厅" %}
{{验证码短信}}
{% endif %}
{% if 违约责任 is defined and 违约责任 != "" %}
违约：{{违约责任}}
{% endif %}
{% for item in 提醒列表 %}
  {% if item.类型 == "超额" %}
    {{外层提示}}
  {% endif %}
{% endfor %}
{{订购短信}}
"""
    raw = body_field_conditions(body)
    # 顶层无条件输出与自保护字段、循环局部变量保护的字段不得进入条件跳过表
    assert "订购短信" not in raw
    assert "争议类型" not in raw
    assert "受理渠道" not in raw
    assert "违约责任" not in raw
    assert "提醒列表" not in raw
    assert "外层提示" not in raw

    assert raw["二次确认短信"] == ('受理渠道 == "热线"', ("受理渠道",))
    assert raw["验证码短信"] == ('受理渠道 == "掌上营业厅"', ("受理渠道",))
    assert raw["标准资费"] == ('争议类型 == "业务"', ("争议类型",))
    assert raw["活动时间"] == ('争议类型 == "营销活动"', ("争议类型",))
    # 受理日期出现在两个分支中
    assert "争议类型" in raw["受理日期"][1]

    # 结合字段定义：争议类型枚举仅含 ["业务", "营销活动"] → 受理日期全覆盖，被自动排除出可跳过表
    fields = [
        FieldDef(name="争议类型", visible=False, type="enum", values=["业务", "营销活动"], evidence="derive"),
        FieldDef(name="受理渠道", visible=False, type="enum", values=["热线", "掌上营业厅", "其他"], evidence="derive"),
        FieldDef(name="受理日期", visible=True, type="string", evidence="derive"),
        FieldDef(name="标准资费", visible=True, type="string", evidence="derive"),
        FieldDef(name="业务套餐内容", visible=True, type="string", evidence="quote"),
        FieldDef(name="活动时间", visible=True, type="string", evidence="derive"),
        FieldDef(name="活动内容", visible=True, type="string", evidence="quote", description="从单据提取"),
        FieldDef(name="二次确认短信", visible=True, type="string", evidence="quote"),
        FieldDef(name="验证码短信", visible=True, type="string", evidence="quote"),
        # 构造依赖保护场景：无条件字段「总结」引用了「活动内容」
        FieldDef(name="总结", visible=True, type="string", evidence="derive", description="结合「活动内容」生成"),
    ]
    skippable = _resolve_skippable_conditions(body, fields)
    assert "受理日期" not in skippable  # 枚举全覆盖 → 必查
    assert "活动内容" not in skippable  # 被无条件字段「总结」说明引用 → 保守必查
    assert set(skippable.keys()) == {"标准资费", "业务套餐内容", "活动时间", "二次确认短信", "验证码短信"}

    guide = _build_condition_guide(fields, skippable)
    assert "争议类型" in guide and "受理渠道" in guide
    assert '仅当 `受理渠道 == "热线"` 时需要查询：二次确认短信' in guide
    assert '仅当 `受理渠道 == "掌上营业厅"` 时需要查询：验证码短信' in guide
    assert "无需加载其专属 Skill" in guide


# ============================================================================ 2. 单页 HTML 导出（单条/多选/零外链/XSS防护）
@pytest.fixture
def export_client(container):
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
    assert m is not None, "导出 HTML 缺少内联 agent-replay-payload JSON"
    return json.loads(m.group(1))


def test_render_html_zero_external_deps_and_xss_escape():
    """校验离线单页 HTML 严格无外部资源依赖，且对 </script> 等标签完成安全转义。"""
    fake_run = {
        "runId": "20261126220001testxss",
        "startTime": "2026-11-26T22:00:01+08:00",
        "templateId": 104,
        "templateName": "业务办理未授权争议处理类",
        "rev": "r12",
        "entry": "回归",
        "status": "SUCCESS",
        "durationMs": 5200,
        "rounds": 3,
        "foundCount": 2,
        "totalCount": 2,
        "missingShown": [],
        "inputs": {"业务名称": "5G套餐</script><img onerror=alert(1)>", "手机号码": "13900001234"},
        "document": "单据原文 </script> 结束",
        "events": [
            {"type": "run_started", "atMs": 0, "round": 0, "data": {}},
            {"type": "tool_call", "atMs": 800, "round": 1, "data": {"tool": "load_skill", "args": {"name": "business-sms"}}},
            {"type": "tool_result", "atMs": 950, "round": 1, "data": {"tool": "load_skill", "ok": True, "result": {"title": "订购短信核查"}}},
        ],
        "fields": [
            {"name": "业务名称", "visible": True, "shown": True, "status": "found", "value": "5G套餐", "evidenceLabel": "入参 · 业务名称", "reasoning": "入参取值"},
        ],
        "report": "核查报告：</script><b>测试</b>",
    }
    doc = render_runs_replay_html([fake_run])
    assert doc.startswith("<!DOCTYPE html>")
    # 严禁任何外部脚本或样式引用
    assert not re.search(r"<(?:script|link)[^>]+https?://", doc, re.IGNORECASE)
    # 确认 payload 内联区域不存在未转义的 </script>
    raw_block = doc.split('<script id="agent-replay-payload" type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "</script>" not in raw_block
    data = json.loads(raw_block)
    assert data["count"] == 1
    assert data["runs"][0]["inputs"]["业务名称"] == "5G套餐</script><img onerror=alert(1)>"
    assert len(data["runs"][0]["steps"]) >= 2


async def test_export_runs_html_single_and_multi_api(export_client: TestClient, container, case_c01):
    """验证 POST /api/v1/runs/export-html 支持单条与多选批量导出，以及边界错误校验。"""
    headers = _login_headers(export_client)

    # 先真实跑出 2 笔运行记录（使用默认 scripted 模型）
    out1 = await container.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"], entry="试运行"))
    out2 = await container.runner.run(RunRequest(1001, case_c01["inputs"], case_c01["documentText"], entry="回归"))
    rid1, rid2 = out1["runId"], out2["runId"]

    # 1. 空列表 → 400
    r_empty = export_client.post("/api/v1/runs/export-html", headers=headers, json={"runIds": []})
    assert r_empty.status_code == 400 and r_empty.json()["code"] == "EMPTY_RUN_IDS"

    # 2. 不存在的编号 → 404
    r_404 = export_client.post("/api/v1/runs/export-html", headers=headers, json={"runIds": ["20261126000000notexist"]})
    assert r_404.status_code == 404

    # 3. 单条导出
    r_one = export_client.post("/api/v1/runs/export-html", headers=headers, json={"runIds": [rid1]})
    assert r_one.status_code == 200
    assert r_one.headers["content-type"].startswith("text/html")
    assert r_one.headers["x-exported-count"] == "1"
    payload_one = _extract_payload(r_one.text)
    assert payload_one["count"] == 1
    one = payload_one["runs"][0]
    assert one["runId"] == rid1
    assert one["report"] == out1["report"]
    assert one["steps"]
    assert one["rawEvents"]
    assert one["fields"]
    # 验证 rawEvents 原样保留了平铺的 ProcessEvent 详细信息（tool/callId/args/result/skills/issues）
    tool_evs = [e for e in one["rawEvents"] if e["type"] == "tool"]
    assert tool_evs and all("tool" in e and "args" in e and "result" in e for e in tool_evs)
    start_evs = [e for e in one["rawEvents"] if e["type"] == "run_started"]
    assert start_evs and start_evs[0].get("skills") and start_evs[0].get("apis")
    rej_evs = [e for e in one["rawEvents"] if e["type"] == "report_rejected"]
    assert rej_evs and rej_evs[0].get("issues")
    # 验证运行记录 4 页签、证据溯源检查器与纯 JSON 导出所需的完整结构均已打包
    assert one["templateDef"] and one["templateDef"]["id"] == 1001 and one["templateDef"]["fields"]
    assert isinstance(one["usage"], dict) and "inputTokens" in one["usage"]
    assert one["apiResults"] and one["apiResults"][0]["records"]
    assert one["documentLines"] and one["documentLines"][0]["line"] == 1
    assert one["toolCalls"] and isinstance(one["toolCalls"][0]["args"], dict)
    assert all("evidenceTarget" in f and "evidenceType" in f for f in one["fields"])
    assert "运行记录详情" in r_one.text and "证据溯源检查器" in r_one.text
    assert "导出 JSON" in r_one.text and "导出全部 JSON" in r_one.text and "模板定义快照" in r_one.text

    # 4. 多选批量导出（含重复 ID 自动去重）
    r_multi = export_client.post("/api/v1/runs/export-html", headers=headers, json={"runIds": [rid1, rid2, rid1]})
    assert r_multi.status_code == 200
    assert r_multi.headers["x-exported-count"] == "2"
    payload_multi = _extract_payload(r_multi.text)
    assert payload_multi["count"] == 2
    assert [x["runId"] for x in payload_multi["runs"]] == [rid1, rid2]
