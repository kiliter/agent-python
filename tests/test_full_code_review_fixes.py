"""全仓深度代码审查修复项专项回归测试套件。

#Created By AiCoding(codex)
覆盖运行时列表挽救、日期/正则边界、Jinja2 追踪、单飞防风暴、RunStore 并发补丁、
RuntimeConfig 掩码防覆写、LoginGuard 防喷洒、失败摘要归因、聊天隔离/跨循环锁及 422 异常编码。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator
import pytest

from report_agent.api.auth import LoginGuard
from report_agent.api.missing_summary import build_missing_summary
from report_agent.chat.store import ChatStore
from report_agent.config import Settings
from report_agent.container import build_container
from report_agent.domain.jinja_env import TrackedList, TrackedValue, render_body
from report_agent.domain.sanitize import sanitize_sensitive_text
from report_agent.domain.template import Template, TemplateDef, safe_regex_compile
from report_agent.main import create_app, install_error_handlers
from report_agent.runtime.deps import RunDeps
from report_agent.runtime.output_model import build_report_model
from report_agent.runtime.runner import _salvage_partial_report
from report_agent.runtime.singleflight import IdempotentSingleFlight
from report_agent.runtime.text_tools import convert_date, extract_dates
from report_agent.runtime.workspace import ApiResult, EventSink, Workspace
from report_agent.store.layout import DataLayout
from report_agent.store.runs import RunStore
from report_agent.store.runtime_config import RuntimeConfigStore, RuntimeConfigValidationError
from scripted_model import scripted_model


def test_salvage_partial_report_preserves_list_field_aliases():
    """字段级部分挽救必须保留列表字段真实中文列别名，不得退化为 c0/c1 导致合法列表被误杀。"""
    tdef = TemplateDef.model_validate(
        {
            "id": 9001,
            "name": "列表挽救测试",
            "fields": [
                {
                    "name": "扣费明细",
                    "type": "list",
                    "evidence": "quote",
                    "columns": [
                        {"name": "月份", "type": "string"},
                        {"name": "金额", "type": "string"},
                    ],
                },
                {
                    "name": "缺失字段",
                    "type": "string",
                    "evidence": "quote",
                },
            ],
        }
    )
    tpl = Template(definition=tdef, body="{% for it in 扣费明细 %}{{it.月份}}:{{it.金额}}{% endfor %}")
    ws = Workspace()
    ws.results["r1"] = ApiResult(
        result_id="r1",
        api="mock_api",
        title="模拟接口",
        args={},
        ok=True,
        error=None,
        columns={"month": "月份", "fee": "金额"},
        records=[{"month": "202610", "fee": "39元"}],
        cost_ms=10,
    )
    deps = RunDeps(
        run_id="20261127-000000-salvage1",
        rev="r1",
        resources=None,  # type: ignore[arg-type]
        template=tpl,
        inputs={},
        document="",
        allowed_skills=[],
        allowed_apis=[],
        workspace=ws,
        events=EventSink(),
        gateway=None,  # type: ignore[arg-type]
        settings=Settings(_env_file=None),
    )
    report_model = build_report_model(tpl)
    candidate = {
        "扣费明细": {
            "status": "found",
            "value": [{"月份": "202610", "金额": "39元"}],
            "evidence": [{"type": "api", "resultId": "r1", "row": 0, "column": "month"}],
            "reasoning": "命中流水",
        },
        # 故意漏填「缺失字段」模拟触发 _salvage_partial_report
    }
    salvaged = _salvage_partial_report(candidate, report_model, deps)
    assert salvaged["扣费明细"]["status"] == "found"
    assert salvaged["扣费明细"]["value"] == [{"月份": "202610", "金额": "39元"}]
    assert salvaged["缺失字段"]["status"] == "not_found"
    assert "缺失字段" in ws.degraded_fields
    assert "扣费明细" not in ws.degraded_fields


def test_extract_dates_boundary_and_leap_day_format():
    """extract_dates 不得因前一行/前一词末尾数字或‘今年’误杀合法月日，且无年份转换支持 02月29日。"""
    doc = "联系电话：13900001234\n10月5日用户反映拨打10086 10月6日仍未解决，今年10月7日再次进线；1899年10月8日无效。"
    res = extract_dates(doc, defaultYear=2026)
    extracted = res["dates"]
    assert "20261005" in extracted
    assert "20261006" in extracted
    assert "20261007" in extracted
    assert "20261008" not in extracted

    leap_out = convert_date("02月29日", from_pattern="MM月dd日", to_pattern="MM-dd")
    assert leap_out == "02-29"


def test_safe_regex_compile_blocks_optional_and_conditional_redos():
    """safe_regex_compile 必须拦截 (a?a)+$ 与条件组 (?(1)(a+)+) 嵌套重复回溯。"""
    with pytest.raises(ValueError, match="嵌套"):
        safe_regex_compile(r"^(a?a)+$")
    with pytest.raises(ValueError, match="嵌套"):
        safe_regex_compile(r"^(a)?(?(1)(a+)+|b)$")
    rx = safe_regex_compile(r"^(?:19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")
    assert rx.fullmatch("2026-11-27") is not None


def test_jinja_tracked_context_filter_slice_and_percent_format():
    """@pass_context 过滤器不得污染 used，且列表切片与 % / .format() 必须保留字段追踪。"""
    ctx = {
        "已找到字段": TrackedValue("正常文本", "已找到字段"),
        "未引用字段": TrackedValue("{{未引用字段}}", "未引用字段"),
    }
    rendered, used = render_body("{{ ['固定项'] | random }} - {{ 已找到字段 }}", ctx)
    assert rendered == "固定项 - 正常文本"
    assert "已找到字段" in used
    assert "未引用字段" not in used

    list_ctx: dict[str, Any] = {
        "明细列表": TrackedList([], "明细列表", missing=True),
        "金额": TrackedValue("{{金额}}", "金额"),
    }
    out_text, used2 = render_body("{% for x in 明细列表[:3] %}{{x}}{% endfor %}{{ '%s元' % 金额 }}", list_ctx)
    assert "{{金额}}元" in out_text
    assert "明细列表" in used2
    assert "金额" in used2


def test_singleflight_prevents_serial_retry_storm_on_failure():
    """同批并发请求遇到 ok=False 时共享当次失败结果（仅调用底层 1 次），且后续轮次仍可重试。"""

    async def _run():
        sf: IdempotentSingleFlight[str, dict[str, Any]] = IdempotentSingleFlight(
            is_success=lambda r: bool(r.get("ok")),
            to_cached=dict,
        )
        calls = 0

        async def _unstable_call() -> dict[str, Any]:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.03)
            return {"ok": calls >= 2, "attempt": calls}

        batch1 = await asyncio.gather(*(sf.do("k1", _unstable_call) for _ in range(6)))
        assert calls == 1
        assert all(not r["ok"] and r["attempt"] == 1 for r, _ in batch1)

        # 失败结果未写入持久缓存，下一轮请求可正常重试并缓存成功结果
        res2, reused2 = await sf.do("k1", _unstable_call)
        assert calls == 2 and res2["ok"] is True and reused2 is False
        res3, reused3 = await sf.do("k1", _unstable_call)
        assert calls == 2 and res3["ok"] is True and reused3 is True

    asyncio.run(_run())


def test_run_store_pending_update_detail_not_overwritten(tmp_path: Path):
    """运行记录尚在异步队列 _pending 中时调用 update_detail，落盘后补丁不得被旧快照覆盖丢失。"""

    async def _run():
        layout = DataLayout(tmp_path)
        layout.ensure()
        store = RunStore(layout)
        await store.start()
        run_id = "20261127-010203-abcd1234"
        summary = {
            "runId": run_id,
            "startTime": "2026-11-27T01:02:03",
            "templateId": 1001,
            "templateName": "测试模板",
            "rev": "r1",
            "status": "PARTIAL",
        }
        detail = {**summary, "report": "正文"}
        store.submit(summary, detail)
        patched = store.update_detail(run_id, {"aiMissingSummary": "AI 缓存摘要"})
        assert patched is not None and patched["aiMissingSummary"] == "AI 缓存摘要"
        await store.stop()

        persisted = store.get(run_id)
        assert persisted is not None
        assert persisted.get("aiMissingSummary") == "AI 缓存摘要"

    asyncio.run(_run())


def test_runtime_config_rejects_masked_secrets_and_invalid_ports(tmp_path: Path):
    """RuntimeConfig 必须拦截字面量脱敏掩码写入及非法端口/畸形 IPv6，同时允许保留匹配的旧掩码密钥。"""
    layout = DataLayout(tmp_path)
    layout.ensure()
    base_settings = Settings(_env_file=None, data_dir=tmp_path, report_api_keys="ra_realkey1111,ra_realkey2222")
    rc_store = RuntimeConfigStore(layout, threading.RLock())
    rc_store.bootstrap_or_load(base_settings)

    with pytest.raises(RuntimeConfigValidationError):
        rc_store.update({"reportApiKeys": "ra_***9999"}, operator="admin")

    with pytest.raises(RuntimeConfigValidationError):
        rc_store.update({"llmApiKey": "sk-***fakemask"}, operator="admin")

    with pytest.raises(RuntimeConfigValidationError):
        rc_store.update({"llmBaseUrl": "http://127.0.0.1:99999/v1"}, operator="admin")

    with pytest.raises(RuntimeConfigValidationError):
        rc_store.update({"llmBaseUrl": "http://[::1/v1"}, operator="admin")


def test_login_guard_success_does_not_reset_ip_spray_bucket():
    """单个已知账号登录成功不得清空同源 IP 的喷洒失败计数。"""
    guard = LoginGuard(max_failures=5, lock_s=300)
    client_ip = "10.20.30.40"
    for i in range(19):
        guard.fail(f"victim-{i}", client_ip=client_ip)
    guard.success("known-good-user", client_ip=client_ip)
    guard.fail("victim-20", client_ip=client_ip)
    with pytest.raises(HTTPException) as exc_info:
        guard.check("victim-21", client_ip=client_ip)
    assert exc_info.value.status_code == 429


def test_missing_summary_failed_run_not_reported_as_all_found():
    """整单 FAILED 且无成稿报告时，不得将未展示可见字段归为无害条件跳过。"""
    failed_run = {
        "runId": "20261127-000000-failed01",
        "status": "FAILED",
        "error": "大模型调用失败：连接超时",
        "report": "",
        "fields": [
            {
                "name": "业务名称",
                "visible": True,
                "shown": False,
                "status": "not_found",
                "whenMissing": "placeholder",
                "reasoning": "大模型调用失败：连接超时",
            },
            {
                "name": "核查结论",
                "visible": True,
                "shown": False,
                "status": "not_found",
                "whenMissing": "placeholder",
                "reasoning": "大模型调用失败：连接超时",
            },
        ],
        "apiResults": [],
        "validationRounds": [],
    }
    res = build_missing_summary(failed_run)
    assert res["impactedCount"] == 2
    assert res["skippedCount"] == 0
    assert "均已找到" not in res["headline"]
    assert any(g["code"] == "run_failed" for g in res["groups"])


def test_chat_cross_loop_lock_and_security_invariants(tmp_path: Path):
    """验证 ChatStore 跨事件循环锁隔离、X-Chat-Session-Id 校验、上层入参保护、#0 幽灵模板过滤与审计操作人。"""
    chat_store = ChatStore(tmp_path / "chats_isolated")

    async def _touch():
        async with chat_store.lock_for("a" * 32):
            await asyncio.sleep(0)

    asyncio.run(_touch())
    asyncio.run(_touch())

    settings = Settings(_env_file=None, data_dir=tmp_path / "app_data", report_api_keys="ra_secret_key_123456")
    c = build_container(settings, model=scripted_model())
    app = create_app(settings, container=c)
    headers = {"X-API-Key": "ra_secret_key_123456"}
    with TestClient(app) as cl:
        r_open = cl.post(
            "/api/v1/chat/sessions",
            headers=headers,
            json={
                "userId": "seat_007",
                "orderId": "ORD-20261127",
                "inputs": {"手机号码": "13900001234"},
                "document": "测试单据正文",
            },
        )
        assert r_open.status_code == 200
        sid = r_open.json()["sessionId"]

        r_mismatch = cl.get(
            f"/api/v1/chat/sessions/{sid}",
            headers={**headers, "X-Chat-Session-Id": "b" * 32},
        )
        assert r_mismatch.status_code == 404

        assert c.chat is not None
        raw_sess = c.chat.store.get(sid)
        assert raw_sess is not None
        raw_sess["messages"].extend(
            [
                {
                    "id": "m_cmp_1",
                    "role": "assistant",
                    "kind": "run",
                    "createdAt": "2026-11-27T01:00:00+08:00",
                    "runId": "cmp-20261127-010000-11112222",
                    "templateId": 0,
                    "templateName": "复合工单汇总（2 项业务）",
                    "isComposite": True,
                    "status": "SUCCESS",
                    "rev": "r1",
                    "inputsVersion": 1,
                    "steps": [],
                    "durationMs": 100,
                    "error": None,
                    "missingShown": [],
                    "foundCount": 2,
                    "totalCount": 2,
                    "versions": [
                        {
                            "no": 1,
                            "kind": "original",
                            "markdown": "# 复合报告",
                            "createdAt": "2026-11-27T01:00:00+08:00",
                            "note": "",
                        }
                    ],
                    "confirmed": False,
                },
                {
                    "id": "m_run_ok",
                    "role": "assistant",
                    "kind": "run",
                    "createdAt": "2026-11-27T01:01:00+08:00",
                    "runId": "20261127-010100-33334444",
                    "templateId": 1001,
                    "templateName": "样例模板",
                    "status": "SUCCESS",
                    "rev": "r1",
                    "inputsVersion": 1,
                    "steps": [],
                    "durationMs": 80,
                    "error": None,
                    "missingShown": [],
                    "foundCount": 1,
                    "totalCount": 1,
                    "versions": [
                        {
                            "no": 1,
                            "kind": "original",
                            "markdown": "核查结果正文",
                            "createdAt": "2026-11-27T01:01:00+08:00",
                            "note": "",
                        }
                    ],
                    "confirmed": False,
                },
            ]
        )
        c.chat._apply_extracted_inputs(
            raw_sess,
            {"手机号码": "18899998888", "随意闲聊杂项键": "污染值"},
            allowed_keys=c.chat._declared_input_keys(c.releases.snapshot(c.releases.live_rev())),
        )
        assert raw_sess["inputs"]["手机号码"] == "13900001234"
        assert "随意闲聊杂项键" not in raw_sess["inputs"]
        c.chat.store.save(raw_sess)

        r_tpls = cl.get(
            f"/api/v1/chat/sessions/{sid}/templates",
            headers={**headers, "X-Chat-Session-Id": sid},
        )
        assert r_tpls.status_code == 200
        assert all(item["templateId"] > 0 for item in r_tpls.json())

        r_confirm = cl.post(
            "/api/v1/chat/runs/20261127-010100-33334444/confirm",
            headers={**headers, "X-Chat-Session-Id": sid},
            json={"markdown": "核查结果正文"},
        )
        assert r_confirm.status_code == 200
        audit_rows = [
            json.loads(line)
            for line in (settings.data_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        confirm_audits = [row for row in audit_rows if row.get("action") == "chat-confirm"]
        assert len(confirm_audits) == 1
        assert confirm_audits[0]["operator"] == "chat:seat_007"


def test_validation_error_with_value_error_returns_clean_422_and_sanitize():
    """自定义 field_validator 抛 ValueError 时全局处理器必须正常返回 422 且不回显敏感 input。"""
    mini = FastAPI()
    install_error_handlers(mini)

    class _SecretBody(BaseModel):
        secret_token: str

        @field_validator("secret_token")
        @classmethod
        def _must_start_with_prefix(cls, v: str) -> str:
            if not v.startswith("ok_"):
                raise ValueError("令牌前缀不合法")
            return v

    @mini.post("/check")
    def _endpoint(body: _SecretBody):
        return {"ok": True, "v": body.secret_token}

    with TestClient(mini) as cl:
        resp = cl.post("/check", json={"secret_token": "sk-sensitiveSecretValue12345"})
        assert resp.status_code == 422
        payload = resp.json()
        assert payload["code"] == "VALIDATION_ERROR"
        assert "sk-sensitiveSecretValue12345" not in resp.text

    cleaned = sanitize_sensitive_text(
        "失败: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 key=ra_secret12345678 /Users/admin/data/secret.json"
    )
    assert "eyJhbGci" not in cleaned
    assert "ra_secret12345678" not in cleaned
    assert "/Users/admin" not in cleaned
