"""全库深度审计修复回归测试（覆盖 #16 中全部 7 类历史缺陷）。

#Created By AiCoding(codex)
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import gc
import json
import logging
import logging.handlers
from pathlib import Path
import threading
from typing import Any
import warnings

from fastapi.testclient import TestClient
from pydantic import SecretStr
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
import pytest

from report_agent.api import common as api_common
from report_agent.api import routes_system
from report_agent.api.auth import DUMMY_PASSWORD_HASH, LoginGuard, UserStore
from report_agent.api.dto import body_usage
from report_agent.config import Settings
from report_agent.container import build_container
from report_agent.domain.jinja_env import TrackedValue, render_body
from report_agent.domain.template import FieldDef, InputDef, Template, TemplateDef
from report_agent.main import create_app, setup_logging
from report_agent.runtime.model_factory import build_model
from report_agent.runtime.runner import RunRequest
from report_agent.store.fsutil import read_jsonl
from report_agent.store.runs import new_run_id
from report_agent.store.service import api_ref, tpl_ref
from scripted_model import ORDER_SMS, build_report, scripted_model


def _make_authed_client(c) -> tuple[TestClient, dict[str, str]]:
    UserStore(c.layout.config / "users.yaml").upsert("auditor", "pass-1234", "审计员", "系统维护")
    app = create_app(container=c)
    client = TestClient(app)
    return client, {}


def _auth_headers(client: TestClient) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"username": "auditor", "password": "pass-1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_1_non_mapping_yaml_draft_resilience(container, case_c01):
    """审计项 1：顶层非映射 YAML 草稿不得导致 overlay() / 列表 / 概览 / 试运行 500 崩溃，且不影响其它合法草稿。"""
    # 先写入一份合法 Skill 草稿，再人为制造非映射列表/标量损坏草稿
    valid_md = container.service.skill_markdown("document-match", "online")
    assert valid_md is not None
    updated_md = valid_md + "\n<!-- valid draft marker -->\n"
    container.service.save_skill("document-match", updated_md, "tester")

    container.drafts.write(
        tpl_ref(1001),
        {"template.yaml": "[1, 2, 3]", "body.md.j2": "服务争议点1"},
        "corruptor",
        base_rev="r1",
    )
    container.drafts.write(
        tpl_ref(9999),
        {"template.yaml": "just-a-scalar", "body.md.j2": "空"},
        "corruptor",
        base_rev=None,
    )
    container.drafts.write(
        api_ref("querySMSSendInfo"),
        {"querySMSSendInfo.yaml": "[1, 2]"},
        "corruptor",
        base_rev="r1",
    )

    # overlay() 不抛异常，记录 DRAFT_INVALID，保留其它合法草稿并回退线上可用资源
    rs = container.service.overlay()
    assert 1001 in rs.templates
    assert "querySMSSendInfo" in rs.apis
    assert "<!-- valid draft marker -->" in rs.skills["document-match"].markdown
    invalid_keys = {(i.kind, i.key, i.code) for i in rs.load_issues}
    assert ("template", "1001", "DRAFT_INVALID") in invalid_keys
    assert ("template", "9999", "DRAFT_INVALID") in invalid_keys
    assert ("api", "querySMSSendInfo", "DRAFT_INVALID") in invalid_keys

    client, _ = _make_authed_client(container)
    with client:
        h = _auth_headers(client)
        assert client.get("/api/v1/templates", headers=h).status_code == 200
        assert client.get("/api/v1/templates/cross-fields", headers=h).status_code == 200
        assert client.get("/api/v1/system/overview", headers=h).status_code == 200
        assert client.get("/api/v1/skills", headers=h).status_code == 200
        assert client.get("/api/v1/apis", headers=h).status_code == 200

        # 线上版本仍可正常读取，纯草稿损坏模板读取返回 400 INVALID_RESOURCE 而非 500
        r_online = client.get("/api/v1/templates/1001?version=online", headers=h)
        assert r_online.status_code == 200
        r_bad_tpl = client.get("/api/v1/templates/9999", headers=h)
        assert r_bad_tpl.status_code == 400 and r_bad_tpl.json()["code"] == "INVALID_RESOURCE"

        # 试运行纯损坏草稿模板返回 404 TEMPLATE_UNAVAILABLE；有线上回退的 1001 试运行正常返回 200
        r_dry_9999 = client.post("/api/v1/templates/9999/dryrun", headers=h, json={"targetVersion": "draft"})
        assert r_dry_9999.status_code == 404 and r_dry_9999.json()["code"] == "TEMPLATE_UNAVAILABLE"

        r_dry_1001 = client.post(
            "/api/v1/templates/1001/dryrun",
            headers=h,
            json={"targetVersion": "draft", "inputs": case_c01["inputs"], "documentText": case_c01["documentText"]},
        )
        assert r_dry_1001.status_code == 200, r_dry_1001.text

        # 管理端可通过 PUT /templates/1001/draft 直接覆盖修复损坏草稿
        r_repair = client.put(
            "/api/v1/templates/1001/draft",
            headers=h,
            json={"name": "业务办理争议类（修复）"},
        )
        assert r_repair.status_code == 200, r_repair.text


def test_2_release_store_thread_safety_and_read_file_toctou(container, monkeypatch: pytest.MonkeyPatch):
    """审计项 2：ReleaseStore.entries() 返回防御性副本且并发读写不丢版本；read_file_at 遇到并发清理回退 Git。"""
    entries_copy = container.releases.entries()
    entries_copy.clear()
    assert len(container.releases.entries()) == 1

    stop_flag = threading.Event()
    errors: list[Exception] = []

    def reader() -> None:
        while not stop_flag.is_set():
            try:
                snap = container.releases.entries()
                nums = [e["n"] for e in snap]
                assert nums == sorted(set(nums))
                _ = container.releases.next_number()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
                break

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        base_sp = container.service.system_prompt("online")
        for idx in range(2, 7):
            container.service.save_system_prompt(f"{base_sp}\n<!-- rev {idx} -->\n", "publisher")
            res = container.service.publish_draft(routes_system.SP_REF, "publisher", f"发布 {idx}")
            assert res.entry["rev"] == f"r{idx}"
    finally:
        stop_flag.set()
        for t in threads:
            t.join(timeout=5)

    assert not errors
    assert [e["rev"] for e in container.releases.entries()] == ["r1", "r2", "r3", "r4", "r5", "r6"]

    # 模拟 read_file_at 在 is_file() 之后、read_text() 时刻被并发 prune() 删除目录触发 FileNotFoundError
    r1_sp_path = container.layout.release_dir("r1") / "system-prompt.md"
    assert r1_sp_path.is_file()
    expected_r1 = r1_sp_path.read_text(encoding="utf-8")
    orig_read_text = Path.read_text

    def flaky_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == r1_sp_path:
            raise FileNotFoundError("simulated concurrent prune rmtree")
        return orig_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    recovered = container.releases.read_file_at("r1", "system-prompt.md")
    assert recovered == expected_r1


async def test_3_run_store_stop_late_submit_and_sse_strong_ref(container, case_c01):
    """审计项 3：RunStore.stop() 后迟到投递仍同步落盘不丢失；sse_run 后台任务持有强引用防 GC。"""
    await container.runs.start()
    rid_queued = new_run_id()
    container.runs.submit(
        {"runId": rid_queued, "startTime": "2026-11-12T01:00:00+08:00", "templateId": 1001, "status": "SUCCESS"},
        {"runId": rid_queued, "status": "SUCCESS", "report": "queued-ok"},
    )
    await container.runs.stop()
    assert container.runs._queue is None and container.runs._task is None

    rid_late = new_run_id()
    container.runs.submit(
        {"runId": rid_late, "startTime": "2026-11-12T01:00:01+08:00", "templateId": 1001, "status": "SUCCESS"},
        {"runId": rid_late, "status": "SUCCESS", "report": "late-ok"},
    )
    assert container.runs.get(rid_queued)["report"] == "queued-ok"
    assert container.runs.get(rid_late)["report"] == "late-ok"

    # sse_run：即便客户端未消费 StreamingResponse 生成器并触发 GC，后台任务仍被 _BG_TASKS 强引用直至完成并自动清理
    import asyncio

    entered = asyncio.Event()
    release = asyncio.Event()

    class FakeRunner:
        async def run(self, req, listener=None):
            entered.set()
            await release.wait()
            return {"runId": "done-1", "status": "SUCCESS"}

    resp = api_common.sse_run(FakeRunner(), RunRequest(1001, {}), lambda d: d)  # type: ignore[arg-type]
    del resp
    gc.collect()
    await asyncio.wait_for(entered.wait(), timeout=2.0)
    assert len(api_common._BG_TASKS) >= 1
    release.set()
    await asyncio.sleep(0.05)
    assert len(api_common._BG_TASKS) == 0


def test_4_publisher_audit_concurrency_and_test_call_audit(container):
    """审计项 4：Publisher.audit 加锁防并发交错，test-call 异步落审计日志。"""
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(container.publisher.audit, "concurrent-op", f"user-{i}", {"seq": i}) for i in range(40)]
        for f in futs:
            f.result()

    rows = read_jsonl(container.layout.audit)
    seqs = sorted(r["seq"] for r in rows if r.get("action") == "concurrent-op")
    assert seqs == list(range(40))

    client, _ = _make_authed_client(container)
    with client:
        h = _auth_headers(client)
        r = client.post(
            "/api/v1/apis/querySMSSendInfo/test-call",
            headers=h,
            json={"params": {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}},
        )
        assert r.status_code == 200
        rows_after = read_jsonl(container.layout.audit)
        assert any(x.get("action") == "api-test-call" and x.get("api") == "querySMSSendInfo" for x in rows_after)


async def test_5_field_validation_rename_body_usage_and_tracked_concat(container):
    """审计项 5：save_field 拦截下划线前缀与保留字、重命名覆盖 {{- -}} 与 {% if %}、body_usage 计数及 TrackedValue 拼接追踪。"""
    # 1. body_usage 正确识别 {{- 字段 -}} 与 {%- if 字段 -%}，忽略字面量与注释
    sample_body = (
        "标题：受理渠道\n"
        "渠道值：{{- 受理渠道 | trim -}}\n"
        "{% if 受理渠道 == \"受理渠道\" %}A{%- elif 受理渠道 == '热线' -%}B{% endif %}{# 受理渠道 #}\n"
    )
    assert body_usage(sample_body) == {"受理渠道": 3}

    # 2. TrackedValue 在 ~ 与 + 拼接后仍追踪字段名与缺失状态
    ctx = {
        "缺失字段A": TrackedValue("{{缺失字段A}}", "缺失字段A", missing=True),
        "缺失字段B": TrackedValue("{{缺失字段B}}", "缺失字段B", missing=True),
        "正常字段": TrackedValue("已核实", "正常字段", missing=False),
    }
    rendered, used = render_body("{{ 缺失字段A ~ '（待补）' }} | {{ '前缀-' + 缺失字段B }} | {{ 正常字段 ~ '!' }}", ctx)
    assert "{{缺失字段A}}（待补）" in rendered
    assert "前缀-{{缺失字段B}}" in rendered
    assert used == {"缺失字段A", "缺失字段B", "正常字段"}

    # 3. HTTP save_field 校验、重命名与 delete_field 引用保护
    client, _ = _make_authed_client(container)
    with client:
        h = _auth_headers(client)
        for bad_name in ("_hidden", "true", "if", "for", "None"):
            r_bad = client.put(
                f"/api/v1/templates/1001/fields/{bad_name}",
                headers=h,
                json={"name": bad_name, "type": "文本", "evidenceType": "quote", "description": "非法字段名"},
            )
            assert r_bad.status_code == 400 and r_bad.json()["code"] == "INVALID_FIELD_NAME", bad_name

        # 将正文改为使用 {{- 新测试字段 -}} + {% if 新测试字段 == "新测试字段" %}
        detail = client.get("/api/v1/templates/1001", headers=h).json()
        new_fields = [
            *detail["fields"],
            {
                "name": "新测试字段",
                "visible": True,
                "type": "文本",
                "evidenceType": "quote",
                "whenMissing": "保留占位",
                "description": "测试字段",
            },
        ]
        custom_body = (
            detail["bodyText"]
            + '\n附加说明：{{- 新测试字段 ~ "（核验）" -}}\n'
            + '{%- if 新测试字段 == "新测试字段" %}命中{% endif %}{# 新测试字段 #}\n'
        )
        assert client.put(
            "/api/v1/templates/1001/draft",
            headers=h,
            json={"bodyText": custom_body, "fields": new_fields},
        ).status_code == 200

        # 未传 force=True 时，{{- 新测试字段 -}} 计入引用次数（2 次），禁止误删
        r_del = client.delete("/api/v1/templates/1001/fields/新测试字段", headers=h)
        assert r_del.status_code == 400 and r_del.json()["code"] == "FIELD_IN_USE"
        assert r_del.json()["usage"] == 2

        # 重命名 新测试字段 -> 改名后字段：{{- ... -}} 与 {%- if ... %} 同步更新，字符串字面量与注释保持不变
        r_ren = client.put(
            "/api/v1/templates/1001/fields/新测试字段",
            headers=h,
            json={
                "originalName": "新测试字段",
                "name": "改名后字段",
                "visible": True,
                "type": "文本",
                "evidenceType": "quote",
                "whenMissing": "保留占位",
                "description": "测试字段",
            },
        )
        assert r_ren.status_code == 200, r_ren.text
        assert r_ren.json()["bodyUsageCount"] == 2
        updated_detail = client.get("/api/v1/templates/1001", headers=h).json()
        assert '{{- 改名后字段 ~ "（核验）" -}}' in updated_detail["bodyText"]
        assert '{%- if 改名后字段 == "新测试字段" %}' in updated_detail["bodyText"]
        assert "{# 新测试字段 #}" in updated_detail["bodyText"]
        val_res = client.post("/api/v1/templates/1001/validate", headers=h).json()
        assert val_res["errors"] == []

    # 4. 智能体运行中若可见字段未找到且通过 ~ 拼接展示，状态必须判定为 PARTIAL 而非假阳性 SUCCESS
    concat_tpl = Template(
        definition=TemplateDef(
            id=8801,
            name="拼接追踪模板",
            inputs=[InputDef(key="手机号码", required=True)],
            fields=[
                FieldDef(name="核查结论", visible=True, type="string", evidence="quote", whenMissing="placeholder",
                         description="核查结论"),
            ],
        ),
        body="结果：{{ 核查结论 ~ '（完）' }}",
    )
    container.service.save_template(concat_tpl, "auditor", action="create")

    def not_found_model(messages, info):
        return ModelResponse(parts=[ToolCallPart("submit_report", {
            "核查结论": {"status": "not_found", "value": None, "evidence": [], "reasoning": "未查到"},
        })])

    orig_model = container.runner.model
    container.runner.model = FunctionModel(not_found_model)
    try:
        out = await container.runner.run(RunRequest(8801, {"手机号码": "13900001234"}, "空单据", target="draft"))
    finally:
        container.runner.model = orig_model
    assert out["status"] == "PARTIAL"
    assert out["missingShown"] == ["核查结论"]


async def test_6_evidence_degradation_cascades_to_dependent_fields(container, case_c01):
    """审计项 6：前置字段证据校验失败或残缺降级时，引用它的下游 type=field 衍生字段（含多跳链）同步级联降级。"""
    tpl_1001 = container.service.template_online(1001)
    assert tpl_1001 is not None
    chained_defn = tpl_1001.definition.model_copy(
        update={
            "id": 8802,
            "name": "多跳级联降级测试模板",
            "fields": [
                *tpl_1001.definition.fields,
                FieldDef(
                    name="渠道二级衍生",
                    visible=True,
                    type="string",
                    evidence="derive",
                    whenMissing="placeholder",
                    description="基于受理方式二次推导",
                ),
            ],
        }
    )
    container.service.save_template(
        Template(definition=chained_defn, body=tpl_1001.body + "\n二级衍生：{{渠道二级衍生}}"),
        "auditor",
        action="create",
    )

    # 场景 A：output_validator 重试耗尽路径（受理渠道证据非法 -> 受理方式、是否录音 -> 渠道二级衍生 两跳级联降级）
    def bad_upstream_field_model(messages, info):
        n = sum(1 for m in messages if isinstance(m, ModelResponse))
        if n == 0:
            return ModelResponse(parts=[ToolCallPart("call_api", {"name": "querySMSSendInfo", "args": {
                "手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}})])
        if n == 1:
            return ModelResponse(parts=[ToolCallPart("format_date", {"value": "20261105", "fromPattern": "yyyyMMdd",
                                                                     "toPattern": "yyyy年M月d号"})])
        rep = build_report(ORDER_SMS, "t2")
        # 故意篡改“受理渠道”引用的行号（不存在的第 99 行），而下游“受理方式”“是否录音”引用“受理渠道”，“渠道二级衍生”引用“受理方式”
        rep["受理渠道"] = {
            "status": "found",
            "value": "热线",
            "evidence": [{"type": "api", "resultId": "r1", "row": 99, "column": "smsContent"}],
            "reasoning": "伪造行号",
        }
        rep["渠道二级衍生"] = {
            "status": "found",
            "value": "电话录音核查通道",
            "evidence": [{"type": "field", "name": "受理方式"}],
            "reasoning": "由受理方式进一步推导",
        }
        return ModelResponse(parts=[ToolCallPart("submit_report", rep)])

    orig_model = container.runner.model
    container.runner.model = FunctionModel(bad_upstream_field_model)
    try:
        out_val = await container.runner.run(
            RunRequest(8802, case_c01["inputs"], case_c01["documentText"], target="draft")
        )
    finally:
        container.runner.model = orig_model

    by_name = {f["name"]: f for f in out_val["fields"]}
    for cascaded in ("受理渠道", "受理方式", "是否录音", "渠道二级衍生"):
        assert by_name[cascaded]["status"] == "not_found", cascaded
        assert by_name[cascaded]["validationFailed"] is True, cascaded
        assert by_name[cascaded]["value"] is None, cascaded
    # 无关合法字段保持 found
    assert by_name["鉴权方式"]["status"] == "found" and by_name["鉴权方式"]["value"] == "服务密码"

    # 场景 B：_salvage_partial_report 缺字段残缺交卷路径同样触发多跳级联降级
    def salvage_cascade_model(messages, info):
        n = sum(1 for m in messages if isinstance(m, ModelResponse))
        if n == 0:
            return ModelResponse(parts=[ToolCallPart("call_api", {"name": "querySMSSendInfo", "args": {
                "手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}})])
        if n == 1:
            return ModelResponse(parts=[ToolCallPart("format_date", {"value": "20261105", "fromPattern": "yyyyMMdd",
                                                                     "toPattern": "yyyy年M月d号"})])
        rep = build_report(ORDER_SMS, "t2")
        rep.pop("受理渠道")  # 缺少前置字段
        rep["渠道二级衍生"] = {
            "status": "found",
            "value": "电话录音核查通道",
            "evidence": [{"type": "field", "name": "受理方式"}],
        }
        return ModelResponse(parts=[TextPart(json.dumps(rep, ensure_ascii=False)), ToolCallPart("submit_report", rep)])

    container.runner.model = FunctionModel(salvage_cascade_model)
    try:
        out_salvage = await container.runner.run(
            RunRequest(8802, case_c01["inputs"], case_c01["documentText"], target="draft")
        )
    finally:
        container.runner.model = orig_model

    by_name_s = {f["name"]: f for f in out_salvage["fields"]}
    for cascaded in ("受理渠道", "受理方式", "是否录音", "渠道二级衍生"):
        assert by_name_s[cascaded]["status"] == "not_found", cascaded
        assert by_name_s[cascaded]["validationFailed"] is True, cascaded


def test_7_logging_spa_testcall_name_auth_hardening_and_zero_deprecation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """审计项 7：日志句柄防泄漏、无 assets 前端目录与 /api 404、test-call 名称一致性、LoginGuard 防喷洒与防时序侧信道、零弃用警告。"""
    # 1) setup_logging 重复调用不泄漏重复文件句柄，且已有 FileHandler 不会屏蔽控制台 StreamHandler
    root = logging.getLogger()
    orig_handlers = list(root.handlers)
    ext_log = tmp_path / "external.log"
    ext_fh = logging.FileHandler(ext_log, encoding="utf-8")
    try:
        root.handlers = [ext_fh]
        log_dir_1 = tmp_path / "logs1"
        s1 = Settings(_env_file=None, data_dir=tmp_path / "d1", log_dir=log_dir_1, llm_api_key="k",
                      admin_token_secret="sec")
        setup_logging(s1)
        setup_logging(s1)
        setup_logging(s1)
        has_console = any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers
        )
        managed_1 = [h for h in root.handlers if getattr(h, "_report_agent_managed", False)]
        assert has_console is True
        assert len(managed_1) == 1

        # 切换 log_dir 时自动关闭并替换旧的托管文件句柄
        log_dir_2 = tmp_path / "logs2"
        s2 = s1.model_copy(update={"log_dir": log_dir_2})
        setup_logging(s2)
        managed_2 = [h for h in root.handlers if getattr(h, "_report_agent_managed", False)]
        assert len(managed_2) == 1
        assert Path(managed_2[0].baseFilename).resolve() == (log_dir_2 / "report-agent.log").resolve()

        # 关闭 log_dir 时清理托管文件句柄
        setup_logging(s1.model_copy(update={"log_dir": None}))
        assert [h for h in root.handlers if getattr(h, "_report_agent_managed", False)] == []
    finally:
        for h in list(root.handlers):
            if h not in orig_handlers:
                root.removeHandler(h)
                h.close()
        root.handlers = orig_handlers
        ext_fh.close()

    # 2) frontend_dist 无 assets 子目录时不崩溃，且 /api 与 /api/xxx 均返回 JSON 404
    dist_dir = tmp_path / "dist_no_assets"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>SPA OK</body></html>", encoding="utf-8")
    s_spa = Settings(_env_file=None, data_dir=tmp_path / "d_spa", frontend_dist=dist_dir, gateway_mode="mock",
                     llm_api_key="k", admin_token_secret="sec-spa")
    c_spa = build_container(s_spa, model=scripted_model())
    UserStore(c_spa.layout.config / "users.yaml").upsert("auditor", "pass-1234", "审计员", "系统维护")
    app_spa = create_app(settings=s_spa, container=c_spa)
    with TestClient(app_spa) as cl:
        r_idx = cl.get("/workbench")
        assert r_idx.status_code == 200 and "SPA OK" in r_idx.text
        r_api_exact = cl.get("/api")
        assert r_api_exact.status_code == 404 and r_api_exact.json()["code"] == "NOT_FOUND"
        r_api_sub = cl.get("/api/unknown")
        assert r_api_sub.status_code == 404 and r_api_sub.json()["code"] == "NOT_FOUND"

        # 3) test-call 自定义 yamlText 中 name 与路径编码不一致时返回 400 API_NAME_MISMATCH
        h = _auth_headers(cl)
        sms_yaml = cl.get("/api/v1/apis/querySMSSendInfo", headers=h).json()["yamlText"]
        wrong_name_yaml = sms_yaml.replace("name: querySMSSendInfo", "name: mismatchedApiName", 1)
        r_mismatch = cl.post(
            "/api/v1/apis/querySMSSendInfo/test-call",
            headers=h,
            json={"params": {"手机号码": "13900001234"}, "yamlText": wrong_name_yaml},
        )
        assert r_mismatch.status_code == 400 and r_mismatch.json()["code"] == "API_NAME_MISMATCH"

        # 4) 登录接口对不存在用户仍执行 PBKDF2 校验（防用户名枚举时序侧信道）
        seen_hashes: list[str] = []
        orig_verify = routes_system.verify_password

        def spy_verify(pw: str, encoded: str) -> bool:
            seen_hashes.append(encoded)
            return orig_verify(pw, encoded)

        monkeypatch.setattr(routes_system, "verify_password", spy_verify)
        r_no_user = cl.post("/api/v1/auth/login", json={"username": "ghost_user_not_exist", "password": "wrong"})
        assert r_no_user.status_code == 401
        assert seen_hashes == [DUMMY_PASSWORD_HASH]

    # 5) LoginGuard 在 5 分钟内高频随机用户名喷洒下容量受控，且已锁定账号不被冲刷解锁
    guard = LoginGuard(max_failures=5, lock_s=300, max_entries=32)
    for _ in range(5):
        guard.fail("admin")
    with pytest.raises( Exception ):
        guard.check("admin")
    for idx in range(200):
        guard.fail(f"spray-user-{idx}")
    assert len(guard._fails) <= 32
    with pytest.raises(Exception) as locked_exc:
        guard.check("admin")
    assert getattr(locked_exc.value, "status_code", None) == 429

    # 6) build_model(llm_tool_choice_required=True) 零弃用警告
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        m = build_model(
            Settings(
                _env_file=None,
                llm_api_key=SecretStr("sk-test"),
                llm_tool_choice_required=True,
                llm_strict_tools=False,
                agent_output_mode="json_object",
            )
        )
    dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert dep_warnings == [], [str(w.message) for w in dep_warnings]
    assert m.profile["supports_forced_tool_choice"] is True
