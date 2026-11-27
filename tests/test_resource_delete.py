"""模板 / 技能 / API 删除规则与引用保护专项测试。

#Created By AiCoding(codex)
覆盖 5 条核心删除规则：
1. 模板可以直接删除（不被 template-router 残留标题阻塞，纯草稿直删，已发布生成新版本，默认清理回归用例）；
2. 技能删除要求无任何模板关联（线上 + 草稿并集）；
3. API 删除要求无任何技能关联（线上 + 草稿并集，含 template / global / chat 全部作用域）；
4. 仅允许删除绑定模板的技能（scope == "template"），global 与 chat 技能禁止删除（且防止改草稿绕过）；
5. 挂在 global 技能下的基础 API（如单据查询接口）因此天然被锁住不可误删。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from report_agent.config import Settings
from report_agent.container import build_container
from report_agent.main import create_app


@pytest.fixture
def del_client(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        report_api_keys="upstream-key",
        admin_bootstrap_password="admin-password-123",
    )
    c = build_container(settings, model=object())
    app = create_app(settings, c)
    with TestClient(app) as tc:
        r = tc.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-password-123"})
        assert r.status_code == 200, r.text
        headers = {"Authorization": f"Bearer {r.json()['token']}"}
        yield tc, c, headers


def _create_template_router(client: TestClient, headers: dict[str, str], template_ids: list[int]) -> None:
    """在测试仓库中创建并发布包含指定模板标题的 template-router 技能。"""
    r = client.post(
        "/api/v1/skills",
        headers=headers,
        json={
            "id": "template-router",
            "name": "模板路由",
            "description": "路由知识库",
            "scope": "chat",
            "apis": [],
        },
    )
    assert r.status_code == 200, r.text
    sections = "\n\n".join(f"### {tid} 模板{tid}\n适用场景说明。" for tid in template_ids)
    md = (
        "---\n"
        "name: template-router\n"
        "title: 模板路由\n"
        "description: 路由知识库\n"
        "scope: chat\n"
        "apis: []\n"
        "---\n\n"
        "# 模板路由\n\n"
        f"{sections}\n"
    )
    r = client.put("/api/v1/skills/template-router/draft", headers=headers, json={"markdown": md})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/skills/template-router/publish", headers=headers, json={"note": "发布路由"})
    assert r.status_code == 200, r.text


def test_delete_template_directly_including_draft_online_and_router_warning(del_client):
    """规则 1：模板可以直接删除（纯草稿直删、已发布生成新版本、不被 template-router 阻断、同步清理用例）。"""
    client, c, h = del_client

    # 1) 纯草稿模板直接删除（不发新版本），且关联用例一并清理
    r = client.post("/api/v1/templates", headers=h, json={"id": 2001, "name": "草稿模板"})
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/templates/2001/cases", headers=h, json={"name": "草稿用例"})
    assert r.status_code == 200, r.text
    assert c.cases.count(2001) == 1

    r = client.delete("/api/v1/templates/2001", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["deleted"] is True and data["rev"] is None and data["deletedCases"] == 1
    assert c.cases.count(2001) == 0
    assert client.get("/api/v1/templates/2001", headers=h).status_code == 404

    # 2) 已发布模板即使在 template-router 中存在 ### 1001 也能直接删除（仅返回 warning，不阻塞）
    _create_template_router(client, h, [1001])
    assert c.cases.count(1001) >= 1

    # 同时验证：直接编辑发布 template-router 引用不存在模板 999 仍会被 error 严格拦截
    bad_router_md = (
        "---\nname: template-router\ntitle: 模板路由\ndescription: 路由\nscope: chat\napis: []\n---\n\n"
        "### 1001 模板1001\n说明\n\n### 999 不存在模板\n说明\n"
    )
    assert client.put("/api/v1/skills/template-router/draft", headers=h, json={"markdown": bad_router_md}).status_code == 200
    bad_pub = client.post("/api/v1/skills/template-router/publish", headers=h, json={"note": "bad"})
    assert bad_pub.status_code == 422
    assert any(i["code"] == "ROUTER_TEMPLATE_NOT_FOUND" for i in bad_pub.json()["issues"])
    assert client.post("/api/v1/skills/template-router/discard-draft", headers=h).status_code == 200

    # 给 1001 留一份草稿，验证删除已发布模板时会连草稿与用例一并清理
    assert client.put("/api/v1/templates/1001/draft", headers=h, json={"description": "临删前改动"}).status_code == 200
    del_res = client.delete("/api/v1/templates/1001", headers=h)
    assert del_res.status_code == 200, del_res.text
    payload = del_res.json()
    assert payload["deleted"] is True and payload["rev"] is not None
    assert payload["deletedCases"] >= 1
    assert any(w["code"] == "ROUTER_TEMPLATE_NOT_FOUND" for w in payload["warnings"])
    assert client.get("/api/v1/templates/1001", headers=h).status_code == 404
    assert c.cases.count(1001) == 0


def test_delete_skill_requires_template_scope_and_no_template_refs(del_client):
    """规则 2 & 4：仅允许删除 scope=template 且无模板关联的技能；global/chat 禁止删除且防草稿绕过。"""
    client, _, h = del_client

    # 1) 已被线上模板 1001 关联的 template 技能禁止删除 -> 409 RESOURCE_IN_USE
    blocked = client.delete("/api/v1/skills/business-sms-check", headers=h)
    assert blocked.status_code == 409, blocked.text
    b_body = blocked.json()
    assert b_body["code"] == "RESOURCE_IN_USE"
    assert any(ref["kind"] == "template" and ref["id"] == 1001 for ref in b_body["references"])

    # 2) 新建纯草稿 template 技能，若被草稿模板引用同样返回 409；删掉草稿模板后可直接删除
    r = client.post(
        "/api/v1/skills",
        headers=h,
        json={"id": "temp-skill", "name": "临时模板技能", "description": "desc", "scope": "template", "apis": []},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/api/v1/templates",
        headers=h,
        json={"id": 2002, "name": "引用草稿技能的模板", "skills": ["temp-skill"]},
    )
    assert r.status_code == 200, r.text

    ref_blocked = client.delete("/api/v1/skills/temp-skill", headers=h)
    assert ref_blocked.status_code == 409
    assert ref_blocked.json()["references"][0]["scope"] == "draft"

    # 直接删除草稿模板 2002 -> 解除关联 -> 成功删除草稿技能 temp-skill
    assert client.delete("/api/v1/templates/2002", headers=h).status_code == 200
    ok_draft_del = client.delete("/api/v1/skills/temp-skill", headers=h)
    assert ok_draft_del.status_code == 200
    assert ok_draft_del.json() == {"id": "temp-skill", "deleted": True, "rev": None}
    assert client.get("/api/v1/skills/temp-skill", headers=h).status_code == 404

    # 3) 删除模板 1001 解除关联后，可删除已发布的 template 技能 business-sms-check
    assert client.delete("/api/v1/templates/1001", headers=h).status_code == 200
    ok_pub_del = client.delete("/api/v1/skills/business-sms-check", headers=h)
    assert ok_pub_del.status_code == 200, ok_pub_del.text
    assert ok_pub_del.json()["deleted"] is True and ok_pub_del.json()["rev"] is not None
    assert client.get("/api/v1/skills/business-sms-check", headers=h).status_code == 404

    # 4) scope=global 与 scope=chat 技能一律禁止删除（含未发布草稿与已发布版本）
    for sid, scope in (("global-doc-query", "global"), ("chat-helper", "chat")):
        cr = client.post(
            "/api/v1/skills",
            headers=h,
            json={"id": sid, "name": f"技能-{scope}", "description": "受保护", "scope": scope, "apis": []},
        )
        assert cr.status_code == 200, cr.text
        # 未发布草稿也不允许 DELETE
        d_draft = client.delete(f"/api/v1/skills/{sid}", headers=h)
        assert d_draft.status_code == 400 and d_draft.json()["code"] == "SKILL_DELETE_FORBIDDEN"
        # 发布后依然不允许 DELETE
        assert client.post(f"/api/v1/skills/{sid}/publish", headers=h, json={"note": "pub"}).status_code == 200
        d_pub = client.delete(f"/api/v1/skills/{sid}", headers=h)
        assert d_pub.status_code == 400 and d_pub.json()["code"] == "SKILL_DELETE_FORBIDDEN"

    # 5) 防止通过草稿把已发布的 global 技能改成 scope: template 绕过删除保护
    bypass_md = (
        "---\nname: global-doc-query\ntitle: 技能-global\ndescription: 试图绕过\nscope: template\napis: []\n---\n\n正文\n"
    )
    assert client.put("/api/v1/skills/global-doc-query/draft", headers=h, json={"markdown": bypass_md}).status_code == 200
    bypass_del = client.delete("/api/v1/skills/global-doc-query", headers=h)
    assert bypass_del.status_code == 400 and bypass_del.json()["code"] == "SKILL_DELETE_FORBIDDEN"


def test_delete_api_requires_no_skill_refs_and_global_skill_locks_base_api(del_client):
    """规则 3 & 5：API 删除需无技能关联；挂在 global 技能下的基础 API（如单据查询）会被自然锁死。"""
    client, _, h = del_client

    # 1) 已被 business-sms-check 引用的 querySMSSendInfo 禁止删除 -> 409
    r = client.delete("/api/v1/apis/querySMSSendInfo", headers=h)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "RESOURCE_IN_USE"
    assert any(ref["id"] == "business-sms-check" for ref in r.json()["references"])

    # 2) 创建基础单据查询 API 并挂到 scope=global 全局技能 -> 全局技能不可删，该基础 API 被锁住
    r = client.post(
        "/api/v1/apis",
        headers=h,
        json={"name": "queryOrderDoc", "title": "单据查询接口", "description": "全局基础单据查询"},
    )
    assert r.status_code == 200, r.text
    assert client.post("/api/v1/apis/queryOrderDoc/publish", headers=h, json={"note": "pub api"}).status_code == 200

    r = client.post(
        "/api/v1/skills",
        headers=h,
        json={
            "id": "order-doc-global",
            "name": "全局单据查询技能",
            "description": "所有模板默认可用",
            "scope": "global",
            "apis": ["queryOrderDoc"],
        },
    )
    assert r.status_code == 200, r.text
    assert client.post("/api/v1/skills/order-doc-global/publish", headers=h, json={"note": "pub global"}).status_code == 200

    # 全局技能删不掉
    del_global = client.delete("/api/v1/skills/order-doc-global", headers=h)
    assert del_global.status_code == 400 and del_global.json()["code"] == "SKILL_DELETE_FORBIDDEN"

    # 依赖它的单据查询 API 同样被锁住删不掉
    del_locked_api = client.delete("/api/v1/apis/queryOrderDoc", headers=h)
    assert del_locked_api.status_code == 409, del_locked_api.text
    body = del_locked_api.json()
    assert body["code"] == "RESOURCE_IN_USE"
    assert any(ref["id"] == "order-doc-global" and ref["skillScope"] == "global" for ref in body["references"])

    # 3) 解除模板 1001 + 删除 template 技能 business-sms-check 后，querySMSSendInfo 可成功删除
    assert client.delete("/api/v1/templates/1001", headers=h).status_code == 200
    assert client.delete("/api/v1/skills/business-sms-check", headers=h).status_code == 200
    del_api = client.delete("/api/v1/apis/querySMSSendInfo", headers=h)
    assert del_api.status_code == 200, del_api.text
    assert del_api.json()["deleted"] is True and del_api.json()["rev"] is not None
    assert client.get("/api/v1/apis/querySMSSendInfo", headers=h).status_code == 404

    # 4) 纯草稿无引用 API 可直接删除（rev=None）
    r = client.post(
        "/api/v1/apis",
        headers=h,
        json={"name": "draftOnlyApi", "title": "纯草稿接口", "description": "test"},
    )
    assert r.status_code == 200
    del_draft_api = client.delete("/api/v1/apis/draftOnlyApi", headers=h)
    assert del_draft_api.status_code == 200
    assert del_draft_api.json() == {"name": "draftOnlyApi", "deleted": True, "rev": None}


def test_delete_not_found_and_invalid_ids(del_client):
    """边界校验：不存在的资源返回 404，非法标识返回 400。"""
    client, _, h = del_client
    assert client.delete("/api/v1/templates/9999", headers=h).status_code == 404
    assert client.delete("/api/v1/templates/0", headers=h).status_code == 400
    assert client.delete("/api/v1/skills/no-such-skill", headers=h).status_code == 404
    assert client.delete("/api/v1/skills/Bad_Upper", headers=h).status_code == 400
    assert client.delete("/api/v1/apis/noSuchApi", headers=h).status_code == 404
    assert client.delete("/api/v1/apis/123bad", headers=h).status_code == 400
