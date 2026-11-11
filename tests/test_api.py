"""HTTP 接口测试（FastAPI TestClient）。

#Created By AiCoding(codex)
"""

from __future__ import annotations

from datetime import date
import json
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from report_agent.api.auth import UserStore, verify_password
from report_agent.main import create_app


@pytest.fixture
def client(container):
    UserStore(container.layout.config / "users.yaml").upsert("chenxiaoyun", "pass-1234", "陈晓芸", "业务维护")
    app = create_app(container=container)
    with TestClient(app) as cl:
        yield cl


def _login(client) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "pass-1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_auth(client):
    assert client.get("/api/v1/templates").status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "x"}).status_code == 401
    h = _login(client)
    assert client.get("/api/v1/auth/me", headers=h).json()["displayName"] == "陈晓芸"
    # Cookie 会话也可以访问
    assert client.get("/api/v1/templates").status_code == 200
    client.post("/api/v1/auth/logout", headers=h)
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_template_workbench_flow(client):
    h = _login(client)
    items = client.get("/api/v1/templates", headers=h).json()
    assert items[0]["id"] == 1001 and items[0]["status"] == "PUBLISHED" and items[0]["onlineRev"] == "r1"
    detail = client.get("/api/v1/templates/1001", headers=h).json()
    assert detail["bodyText"].startswith("服务争议点1") and len(detail["fields"]) == 17
    field = next(f for f in detail["fields"] if f["name"] == "受理渠道")
    assert field["type"] == "枚举" and field["whenMissing"] == "默认值" and field["bodyUsageCount"] == 2

    # 保存草稿（前端整包提交），正文引用未定义字段 → 校验报错，发布被拦截
    r = client.put("/api/v1/templates/1001/draft", headers=h,
                   json={"bodyText": detail["bodyText"] + "\n客户星级：{{客户星级}}", "fields": detail["fields"],
                         "inputs": detail["inputs"], "skills": ["办理短信核查", "document-match"]})
    assert r.status_code == 200, r.text
    assert any(i["code"] == "BODY_UNDEFINED_FIELD" for i in r.json()["issues"])
    assert client.get("/api/v1/templates", headers=h).json()[0]["status"] == "PUBLISHED_DRAFT"
    r = client.post("/api/v1/templates/1001/publish", headers=h, json={"note": "x"})
    assert r.status_code == 422 and r.json()["code"] == "PUBLISH_BLOCKED"

    # 新增字段补齐定义后发布成功
    r = client.put("/api/v1/templates/1001/fields/客户星级", headers=h,
                   json={"name": "客户星级", "visible": True, "type": "文本", "evidenceType": "quote",
                         "whenMissing": "置空", "description": "单据中的客户星级"})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/templates/1001/publish", headers=h, json={"note": "新增客户星级"})
    assert r.status_code == 200, r.text
    assert r.json()["rev"] == "r2" and r.json()["summary"].startswith("发布 模板 1001（业务办理争议类）")
    revs = client.get("/api/v1/templates/1001/revisions", headers=h).json()
    assert [x["rev"] for x in revs] == ["r2", "r1"] and revs[0]["online"]
    d = client.get("/api/v1/templates/1001/diff?a=r2&b=r1", headers=h).json()
    assert d["fields"][0]["name"] == "客户星级" and d["fields"][0]["change"] == "removed"
    rel = client.get("/api/v1/releases", headers=h).json()
    assert rel[0]["rev"] == "r2" and rel[0]["isLive"]
    diff = client.get("/api/v1/releases/diff?a=r1&b=r2", headers=h).json()
    assert diff["changes"] == [{"kind": "template", "key": "1001", "label": "模板 1001", "change": "modified",
                                "files": ["templates/1001/body.md.j2", "templates/1001/template.yaml"]}]

    # 紧急切回 r1
    r = client.post("/api/v1/releases/emergency-switch", headers=h, json={"targetRev": "r1", "reason": "回滚"})
    assert r.json()["activeRev"] == "r1"


def test_render_preview(client):
    h = _login(client)
    r = client.post("/api/v1/templates/1001/render-preview", headers=h,
                    json={"values": {"争议类型": "业务", "受理渠道": "热线", "鉴权方式": "服务密码"}}).json()
    assert r["error"] is None and "经服务密码办理" in r["text"] and "{{二次确认短信}}" in r["text"]
    bad = client.post("/api/v1/templates/1001/render-preview", headers=h, json={"bodyText": "{% if %}"}).json()
    assert bad["error"]


def test_dryrun_and_runs(client, case_c01):
    h = _login(client)
    r = client.post("/api/v1/templates/1001/dryrun", headers=h,
                    json={"targetVersion": "draft", "inputs": case_c01["inputs"], "documentText": case_c01["documentText"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "SUCCESS" and out["rounds"] == 7 and out["apiCallCount"] == 1
    f = next(x for x in out["fields"] if x["name"] == "订购短信")
    assert f["runStatus"] == "found" and f["retried"] and f["evidenceTarget"]["tab"] == "api"
    assert out["smsRecords"][3]["smsContent"].startswith("【业务办理成功提醒】")
    assert out["documentLines"][2]["text"] == "办理业务：5G智享套餐(个人版)"

    runs = client.get("/api/v1/runs", headers=h).json()
    assert runs and runs[0]["runId"] == out["runId"] and runs[0]["entry"] == "试运行"
    detail = client.get(f"/api/v1/runs/{out['runId']}", headers=h).json()
    assert detail["report"] == out["report"]

    # 运行记录转为用例
    r = client.post("/api/v1/templates/1001/cases", headers=h, json={"name": "转入", "fromRunId": out["runId"]})
    assert r.status_code == 200 and r.json()["source"] == "由运行记录转入"
    assert len(client.get("/api/v1/templates/1001/cases", headers=h).json()) == 2


def test_upstream_report_and_stream(client, case_c01):
    body = {"templateId": 1001, "params": case_c01["inputs"], "document": case_c01["documentText"]}
    assert client.post("/api/v1/reports", json=body).status_code == 401
    r = client.post("/api/v1/reports", json=body, headers={"X-API-Key": "upstream-key"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "SUCCESS" and "办理成功告知短信" in r.json()["report"]
    bad = client.post("/api/v1/reports", json={**body, "params": {}}, headers={"X-API-Key": "upstream-key"})
    assert bad.status_code == 400 and bad.json()["code"] == "INVALID_INPUT"

    with client.stream("POST", "/api/v1/reports/stream", json=body, headers={"X-API-Key": "upstream-key"}) as resp:
        text = "".join(resp.iter_text())
    events = [blk for blk in text.split("\n\n") if blk.startswith("event:")]
    kinds = [blk.split("\n")[0][len("event: "):] for blk in events]
    assert kinds[-1] == "final" and kinds.count("event") > 10
    final = json.loads(events[-1].split("\n", 1)[1][len("data: "):])
    assert final["status"] == "SUCCESS"


def test_skill_and_api_management(client):
    h = _login(client)
    skills = client.get("/api/v1/skills", headers=h).json()
    sms = next(s for s in skills if s["id"] == "business-sms-check")
    assert sms["name"] == "办理短信核查" and sms["refTemplates"] == ["1001 业务办理争议类"]
    md = client.get("/api/v1/skills/business-sms-check", headers=h).json()["markdown"]
    r = client.put("/api/v1/skills/business-sms-check/draft", headers=h, json={"markdown": md.replace("name: business-sms-check", "name: other")})
    assert r.status_code == 400
    r = client.put("/api/v1/skills/business-sms-check/draft", headers=h, json={"markdown": md + "\n补充说明\n"})
    assert r.status_code == 200
    assert client.post("/api/v1/skills/business-sms-check/publish", headers=h, json={"note": "补充"}).json()["rev"] == "r2"

    r = client.post("/api/v1/skills", headers=h, json={"id": "renewal-sms", "name": "续约短信核查", "apis": ["notExist"]})
    assert r.status_code == 200 and r.json()["status"] == "DRAFT"
    r = client.post("/api/v1/skills/renewal-sms/publish", headers=h, json={})
    assert r.status_code == 422 and r.json()["issues"][0]["code"] == "API_NOT_FOUND"

    apis = client.get("/api/v1/apis", headers=h).json()
    assert apis[0]["name"] == "querySMSSendInfo" and apis[0]["params"][0]["name"] == "手机号码"
    assert {"name": "content.sendType", "value": "0"} in apis[0]["fixedParams"]
    r = client.post("/api/v1/apis/querySMSSendInfo/test-call", headers=h,
                    json={"params": {"手机号码": "13900001234", "开始时间": "20261105000000", "结束时间": "20261105235959"}})
    assert r.status_code == 200 and r.json()["ok"] and len(r.json()["records"]) == 5
    r = client.post("/api/v1/apis/querySMSSendInfo/test-call", headers=h, json={"params": {"手机号码": "1"}})
    assert r.status_code == 400 and r.json()["code"] == "INVALID_PARAMS"

    sp = client.get("/api/v1/settings/system-prompt", headers=h).json()
    assert sp["sysPromptStatus"] == "PUBLISHED"
    r = client.post("/api/v1/settings/system-prompt/publish", headers=h, json={"sysPromptText": sp["sysPromptText"] + "\n- 新规则"})
    assert r.status_code == 200 and r.json()["status"] == "PUBLISHED"


def test_health_and_auth_lockout_and_api_key_edges(client, case_c01):
    # 免鉴权健康探针
    hz = client.get("/healthz").json()
    assert hz["status"] == "UP" and hz["liveRev"] == "r1"
    api_hz = client.get("/api/v1/health").json()
    assert api_hz["status"] == "UP" and api_hz["liveRev"] == "r1" and api_hz["totalReleases"] >= 1

    # 空用户名/密码返回 400
    assert client.post("/api/v1/auth/login", json={"username": "  ", "password": "x"}).status_code == 400
    assert client.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": ""}).status_code == 400

    # 连续 5 次密码错误触发 429 锁定
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "wrong"})
        assert r.status_code == 401 and r.json()["code"] == "INVALID_CREDENTIALS"
    locked = client.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "pass-1234"})
    assert locked.status_code == 429 and locked.json()["code"] == "LOGIN_LOCKED"

    # 锁定期届满后失败计数应重置，单次输错不会再次立即锁死
    guard = client.app.state.login_guard
    guard._fails["chenxiaoyun"] = (5, time.time() - 1)
    once_wrong = client.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "wrong"})
    assert once_wrong.status_code == 401
    ok = client.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "pass-1234"})
    assert ok.status_code == 200

    # 上游接口鉴权与模板编号边界
    body = {"templateId": 1001, "params": case_c01["inputs"], "document": case_c01["documentText"]}
    no_key = client.post("/api/v1/reports", json=body)
    assert no_key.status_code == 401 and no_key.json()["code"] == "INVALID_API_KEY"
    bad_key = client.post("/api/v1/reports", json=body, headers={"X-API-Key": "wrong-key"})
    assert bad_key.status_code == 401 and bad_key.json()["code"] == "INVALID_API_KEY"
    bad_tid = client.post("/api/v1/reports", json={**body, "templateId": 0}, headers={"X-API-Key": "upstream-key"})
    assert bad_tid.status_code == 400 and bad_tid.json()["code"] == "INVALID_TEMPLATE_ID"


def test_resource_id_validation_traversal_and_not_found_contracts(client, container):
    h = _login(client)

    # 模板 ID、版本号与不存在资源边界
    assert client.get("/api/v1/templates/0", headers=h).status_code == 400
    assert client.get("/api/v1/templates/-5", headers=h).status_code == 400
    assert client.get("/api/v1/templates/9999", headers=h).status_code == 404
    assert client.get("/api/v1/templates/1001?version=../evil", headers=h).status_code == 400
    assert client.get("/api/v1/templates/1001?version=r999", headers=h).status_code == 404
    assert client.post("/api/v1/templates/9999/publish", headers=h, json={"note": ""}).status_code == 404
    assert client.post("/api/v1/templates/1001/publish", headers=h, json={"note": ""}).status_code == 400
    assert client.post("/api/v1/templates/9999/discard-draft", headers=h).status_code == 404
    assert client.post("/api/v1/templates/9999/offline", headers=h, json={"reason": "x"}).status_code == 404

    # 回归用例路径穿越与非法编号拦截
    assert client.put("/api/v1/templates/1001/cases/bad%20id!", headers=h, json={"name": "x"}).status_code == 400
    assert client.delete("/api/v1/templates/1001/cases/..%2F..%2Fconfig%2Fusers", headers=h).status_code in (400, 404)
    assert (container.layout.config / "users.yaml").exists()
    assert client.delete("/api/v1/templates/1001/cases/C-99", headers=h).status_code == 404
    assert client.post("/api/v1/templates/1001/cases", headers=h,
                       json={"name": "bad", "fromRunId": "../evil"}).status_code == 400
    assert client.post("/api/v1/templates/1001/cases", headers=h,
                       json={"name": "missing", "fromRunId": "20261111000000000abcdefg"}).status_code == 404

    # Skill 路径穿越（特别是 %2E%2E 防止误删整个 drafts 目录）与不存在资源 404
    r_dot = client.post("/api/v1/skills/%2E%2E/discard-draft", headers=h)
    assert r_dot.status_code in (400, 404)
    assert container.layout.drafts.exists()
    assert client.get("/api/v1/skills/Bad_Upper", headers=h).status_code == 400
    assert client.get("/api/v1/skills/no-such-skill", headers=h).status_code == 404
    assert client.post("/api/v1/skills/no-such-skill/publish", headers=h, json={"note": ""}).status_code == 404
    assert client.post("/api/v1/skills/no-such-skill/discard-draft", headers=h).status_code == 404
    assert client.get("/api/v1/skills/no-such-skill/revisions", headers=h).status_code == 404

    # 接口编码校验与不存在资源 404
    assert client.get("/api/v1/apis/123bad", headers=h).status_code == 400
    assert client.get("/api/v1/apis/noSuchApi", headers=h).status_code == 404
    assert client.post("/api/v1/apis/noSuchApi/publish", headers=h, json={"note": ""}).status_code == 404
    assert client.post("/api/v1/apis/noSuchApi/discard-draft", headers=h).status_code == 404
    assert client.get("/api/v1/apis/noSuchApi/revisions", headers=h).status_code == 404

    # 运行记录与发布版本边界
    assert client.get("/api/v1/runs/bad..id", headers=h).status_code == 400
    assert client.get("/api/v1/runs/20261111000000000abcdefg", headers=h).status_code == 404
    assert client.get("/api/v1/releases?limit=0", headers=h).status_code == 400
    assert client.get("/api/v1/releases/not-a-rev", headers=h).status_code == 404
    assert client.get("/api/v1/releases/diff?a=&b=r1", headers=h).status_code == 400


def test_field_editing_reorder_and_api_skill_edge_cases(client):
    h = _login(client)
    detail = client.get("/api/v1/templates/1001", headers=h).json()

    # 1) 非法字段名被拦截
    r = client.put("/api/v1/templates/1001/fields/123bad", headers=h,
                   json={"name": "123bad", "type": "文本", "evidenceType": "quote", "whenMissing": "置空"})
    assert r.status_code == 400 and r.json()["code"] == "INVALID_FIELD_NAME"

    # 2) 新增两个相似前缀字段并写入正文，测试改名只精确替换目标占位符且拒绝重名冲突
    for fname in ("核查结论", "核查结论备注"):
        res = client.put(f"/api/v1/templates/1001/fields/{fname}", headers=h,
                         json={"name": fname, "type": "文本", "evidenceType": "derive", "whenMissing": "保留占位"})
        assert res.status_code == 200
    custom_body = detail["bodyText"] + "\n结论：{{ 核查结论 }}；过滤：{{核查结论|default('无')}}；备注：{{核查结论备注}}"
    fields_now = client.get("/api/v1/templates/1001/fields", headers=h).json()
    assert client.put("/api/v1/templates/1001/draft", headers=h,
                      json={"bodyText": custom_body, "fields": fields_now}).status_code == 200

    # 重命名为已存在的字段名 -> 400 FIELD_EXISTS
    conflict = client.put("/api/v1/templates/1001/fields/核查结论备注", headers=h,
                          json={"name": "核查结论备注", "originalName": "核查结论",
                                "type": "文本", "evidenceType": "derive", "whenMissing": "保留占位"})
    assert conflict.status_code == 400 and conflict.json()["code"] == "FIELD_EXISTS"

    # 合法重命名：核查结论 -> 稽核结论，验证 {{ 核查结论 }} 与 {{核查结论|...}} 均更新，且不破坏 {{核查结论备注}}
    renamed = client.put("/api/v1/templates/1001/fields/稽核结论", headers=h,
                         json={"name": "稽核结论", "originalName": "核查结论",
                               "type": "文本", "evidenceType": "derive", "whenMissing": "保留占位"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "稽核结论"
    updated_body = client.get("/api/v1/templates/1001", headers=h).json()["bodyText"]
    assert "{{ 稽核结论 }}" in updated_body and "{{稽核结论|default('无')}}" in updated_body
    assert "{{核查结论备注}}" in updated_body

    # 3) 字段排序：重复名称即使总长度相等也必须 400 拒绝
    names = [f["name"] for f in client.get("/api/v1/templates/1001/fields", headers=h).json()]
    dup_names = [names[0]] * len(names)
    assert client.put("/api/v1/templates/1001/fields-order", headers=h, json={"names": dup_names}).status_code == 400
    rev_names = list(reversed(names))
    assert client.put("/api/v1/templates/1001/fields-order", headers=h, json={"names": rev_names}).status_code == 200

    # 4) Skill validate 接口返回 drift 字段，与前端 ValidationResult 契约一致
    v_sk = client.post("/api/v1/skills/business-sms-check/validate", headers=h)
    assert v_sk.status_code == 200 and {"errors", "warnings", "drift"} <= set(v_sk.json().keys())

    # 5) 接口局部更新参数边界与直接回退原因校验
    assert client.put("/api/v1/apis/querySMSSendInfo/draft", headers=h,
                      json={"api": {"timeoutMs": -5}}).status_code == 400
    assert client.put("/api/v1/apis/querySMSSendInfo/draft", headers=h,
                      json={"api": {"timeoutMs": "bad"}}).status_code == 400
    assert client.put("/api/v1/apis/querySMSSendInfo/draft", headers=h,
                      json={"api": {"retry": 0}}).status_code == 400
    ok_patch = client.put("/api/v1/apis/querySMSSendInfo/draft", headers=h,
                          json={"api": {"timeoutMs": 15000, "retry": 2}})
    assert ok_patch.status_code == 200
    assert client.post("/api/v1/templates/1001/rollback", headers=h,
                       json={"targetRev": "r1", "mode": "publish_now", "reason": "  "}).status_code == 400
    assert client.post("/api/v1/skills/business-sms-check/rollback", headers=h,
                       json={"targetRev": "r1", "mode": "publish_now", "reason": ""}).status_code == 400
    assert client.post("/api/v1/apis/querySMSSendInfo/rollback", headers=h,
                       json={"targetRev": "r1", "mode": "publish_now", "reason": ""}).status_code == 400


def test_runs_pagination_filtering_corrupted_detail_and_system_overview(client, container, case_c01):
    assert client.get("/api/v1/system/overview").status_code == 401
    h = _login(client)
    # 先跑一次真实试运行
    dry = client.post("/api/v1/templates/1001/dryrun", headers=h,
                      json={"targetVersion": "online", "inputs": case_c01["inputs"],
                            "documentText": case_c01["documentText"]})
    assert dry.status_code == 200
    real_run_id = dry.json()["runId"]

    # 再注入一条详情文件损坏的运行记录，验证 /runs 与 /runs/{id} 均不报错
    today = date.today()
    ds = today.strftime("%Y%m%d")
    corrupt_id = f"{ds}235959999corrupt"
    container.runs._write(
        {"runId": corrupt_id, "startTime": f"{today.isoformat()}T23:59:59+08:00", "templateId": 1001,
         "templateName": "业务办理争议类", "rev": "r1", "entry": "上游调用", "status": "FAILED",
         "mobile": "13988887777", "busiName": "国际漫游包争议ABC", "found": 0, "total": 17, "durationMs": 650,
         "rounds": 1, "skills": ["business-sms-check"], "apiCalls": [{"name": "querySMSSendInfo", "ok": False, "ms": 210}],
         "retries": 1, "error": "GATEWAY_TIMEOUT", "batchNo": "BATCH-09"},
        {"runId": corrupt_id, "status": "FAILED"},
    )
    day_dir = container.layout.runs / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    (day_dir / f"{corrupt_id}.json").write_text("{broken json!!!", encoding="utf-8")

    # 分页与过滤参数异常校验
    assert client.get("/api/v1/runs?limit=0", headers=h).status_code == 400
    assert client.get("/api/v1/runs?offset=-1", headers=h).status_code == 400
    assert client.get("/api/v1/runs?dateFrom=2026-11-10&dateTo=2026-11-01", headers=h).status_code == 400
    assert client.get("/api/v1/runs?templateId=0", headers=h).status_code == 400

    # 分页与大小写不敏感关键字查询
    p1 = client.get("/api/v1/runs?limit=1&offset=0", headers=h).json()
    p2 = client.get("/api/v1/runs?limit=1&offset=1", headers=h).json()
    assert len(p1) == 1 and len(p2) == 1 and p1[0]["runId"] == corrupt_id and p2[0]["runId"] == real_run_id
    q_hit = client.get("/api/v1/runs?q=gateway_timeout", headers=h).json()
    assert [x["runId"] for x in q_hit] == [corrupt_id]
    q_busi = client.get("/api/v1/runs?q=abc", headers=h).json()
    assert [x["runId"] for x in q_busi] == [corrupt_id]

    # 详情文件损坏时仍能正常返回 200 降级详情视图
    deg = client.get(f"/api/v1/runs/{corrupt_id}", headers=h)
    assert deg.status_code == 200
    deg_json = deg.json()
    assert deg_json["runId"] == corrupt_id and deg_json["status"] == "FAILED"
    assert deg_json["record"]["mobile"] == "13988887777" and deg_json["record"]["batchNo"] == "BATCH-09"

    # 系统可观测概览端点契约与鉴权校验
    assert client.get("/api/v1/system/overview?days=0", headers=h).status_code == 400
    assert client.get("/api/v1/system/overview?days=400", headers=h).status_code == 400
    ov = client.get("/api/v1/system/overview?days=7", headers=h)
    assert ov.status_code == 200, ov.text
    ov_data = ov.json()
    assert ov_data["status"] == "UP" and ov_data["windowDays"] == 7
    assert ov_data["release"]["liveRev"] == "r1" and ov_data["release"]["totalReleases"] >= 1
    assert ov_data["resources"]["templates"]["total"] >= 1
    assert ov_data["runs"]["total"] == 2 and ov_data["runs"]["success"] == 1 and ov_data["runs"]["failed"] == 1
    assert ov_data["runs"]["p95DurationMs"] >= ov_data["runs"]["avgDurationMs"] >= 0
    assert len(ov_data["runs"]["daily"]) == 7
    assert ov_data["templateStats"][0]["id"] == 1001 and ov_data["templateStats"][0]["runs"] == 2
    api_stat = next(a for a in ov_data["apiStats"] if a["name"] == "querySMSSendInfo")
    assert api_stat["calls"] == 2 and api_stat["failedCalls"] == 1 and api_stat["p95Ms"] >= 0


def test_review_regressions_run_view_zero_password_hash_and_test_call_schema(client, container):
    h = _login(client)

    # 1) 历史运行记录缺失/破损 templateDef 且字段值为 0 / False 时，仍返回完整 TemplateField 契约并保留 "0" / "False"
    today = date.today()
    ds = today.strftime("%Y%m%d")
    legacy_id = f"{ds}120000001legacy0"
    container.runs._write(
        {"runId": legacy_id, "startTime": f"{today.isoformat()}T12:00:00+08:00", "templateId": 1001,
         "templateName": "业务办理争议类", "rev": "r1", "entry": "上游调用", "status": "SUCCESS",
         "mobile": "13900001234", "busiName": "退费核查", "found": 2, "total": 2, "durationMs": 300, "rounds": 2},
        {"runId": legacy_id, "status": "SUCCESS", "templateId": 1001, "templateDef": {"broken": True},
         "inputs": {"手机号码": "13900001234"}, "report": "退费金额：0",
         "fields": [
             {"name": "退费金额", "visible": True, "status": "found", "value": 0, "evidenceLabel": "接口记录#0"},
             {"name": "是否越权", "visible": False, "status": "found", "value": False},
         ]},
    )
    detail = client.get(f"/api/v1/runs/{legacy_id}", headers=h)
    assert detail.status_code == 200
    f_map = {f["name"]: f for f in detail.json()["fields"]}
    assert {"runStatus", "runValue", "evidenceType", "whenMissing", "evidenceTarget", "enumValues"} <= set(
        f_map["退费金额"].keys())
    assert f_map["退费金额"]["runStatus"] == "found" and f_map["退费金额"]["runValue"] == "0"
    assert f_map["是否越权"]["runStatus"] == "found" and f_map["是否越权"]["runValue"] == "False"

    case_res = client.post("/api/v1/templates/1001/cases", headers=h,
                           json={"name": "零值转入用例", "fromRunId": legacy_id})
    assert case_res.status_code == 200
    assert case_res.json()["expectedValues"] == {"退费金额": "0", "是否越权": "False"}

    # 2) users.yaml 中 passwordHash 为 null / 非字符串 / 超界迭代次数时，登录返回 401 而非 500
    assert verify_password("pass", None) is False  # type: ignore[arg-type]
    assert verify_password("pass", 12345) is False  # type: ignore[arg-type]
    assert verify_password("pass", "pbkdf2_sha256$0$aaaa$bbbb") is False
    assert verify_password("pass", "pbkdf2_sha256$99999999$aaaa$bbbb") is False

    users_path = container.layout.config / "users.yaml"
    users_doc = yaml.safe_load(users_path.read_text(encoding="utf-8"))
    users_doc["users"].extend([
        {"username": "nullhash", "displayName": "空哈希", "role": "维护", "passwordHash": None},
        {"username": "inthash", "displayName": "数字哈希", "role": "维护", "passwordHash": 999},
    ])
    users_path.write_text(yaml.safe_dump(users_doc, allow_unicode=True), encoding="utf-8")
    for bad_user in ("nullhash", "inthash"):
        resp = client.post("/api/v1/auth/login", json={"username": bad_user, "password": "any"})
        assert resp.status_code == 401 and resp.json()["code"] == "INVALID_CREDENTIALS"

    # 3) test-call 传入自定义 yamlText 含非法正则或未知占位符时，执行契约校验并返回 400 而非 500
    valid_yaml = client.get("/api/v1/apis/querySMSSendInfo", headers=h).json()["yamlText"]
    bad_regex_yaml = valid_yaml.replace(r"^1\d{10}$", "[unclosed-regex")
    r_bad_re = client.post("/api/v1/apis/querySMSSendInfo/test-call", headers=h,
                           json={"params": {"手机号码": "13900001234"}, "yamlText": bad_regex_yaml})
    assert r_bad_re.status_code == 400 and r_bad_re.json()["code"] == "INVALID_API_SCHEMA"

    bad_ph_yaml = valid_yaml.replace("${手机号码}", "${未声明入参}")
    r_bad_ph = client.post("/api/v1/apis/querySMSSendInfo/test-call", headers=h,
                           json={"params": {"手机号码": "13900001234"}, "yamlText": bad_ph_yaml})
    assert r_bad_ph.status_code == 400 and r_bad_ph.json()["code"] == "INVALID_API_SCHEMA"
