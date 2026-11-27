"""Skill 作用域（scope: template / global / chat）领域校验、自动注入、聊天隔离与管理接口测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from report_agent.api.auth import UserStore
from report_agent.chat.agent import ChatDeps, load_skill as chat_load_skill
from report_agent.domain.api_contract import parse_api_yaml
from report_agent.domain.resources import ResourceSet, validate_skill, validate_template
from report_agent.domain.skill import SkillParseError, build_skill_markdown, parse_skill_markdown
from report_agent.domain.template import Template, parse_template_yaml
from report_agent.main import create_app
from report_agent.runtime.runner import RunRequest
from report_agent.store.service import api_ref, skill_ref


def _make_template(skills: list[str]) -> Template:
    defn = parse_template_yaml(yaml.safe_dump({
        "id": 9001,
        "name": "作用域测试模板",
        "skills": skills,
        "inputs": [{"key": "手机号码", "required": True}],
        "fields": [
            {"name": "单据结论", "evidence": "quote", "description": "从单据提取"},
        ],
    }, allow_unicode=True))
    return Template(definition=defn, body="结论：{{ 单据结论 }}")


def test_parse_skill_scope_defaults_compat_and_errors():
    # 1. 未写 scope 时普通技能默认 template，template-router 自动向后兼容为 chat
    normal = parse_skill_markdown("---\nname: demo-skill\ntitle: 演示\ndescription: 描述\napis: []\n---\n正文")
    assert normal.scope == "template" and not normal.is_global and not normal.is_chat

    legacy_router = parse_skill_markdown("---\nname: template-router\ntitle: 路由\ndescription: 路由\napis: []\n---\n正文")
    assert legacy_router.scope == "chat" and legacy_router.is_chat

    # 2. 显式声明 global / chat（兼容大小写）
    g = parse_skill_markdown("---\nname: query-pdf-text\ntitle: 查正文\ndescription: 全局\nscope: GLOBAL\napis: [query-pdf-text]\n---\n正文")
    assert g.scope == "global" and g.is_global

    c = parse_skill_markdown("---\nname: chat-tone-guide\ntitle: 话术规范\ndescription: 聊天\nscope: chat\napis: []\n---\n正文")
    assert c.scope == "chat" and c.is_chat

    # 3. 非法 scope 报错
    with pytest.raises(SkillParseError, match="scope"):
        parse_skill_markdown("---\nname: bad-scope\nscope: admin\n---\n正文")

    # 4. build_skill_markdown 正确写入 scope，且 chat 清空 apis
    md_global = build_skill_markdown("pdf-global", "查单据", "说明", ["apiA"], scope="global")
    parsed_g = parse_skill_markdown(md_global)
    assert parsed_g.scope == "global" and parsed_g.meta.apis == ["apiA"]

    md_chat = build_skill_markdown("chat-guide", "聊天指引", "说明", ["apiA"], scope="chat")
    parsed_c = parse_skill_markdown(md_chat)
    assert parsed_c.scope == "chat" and parsed_c.meta.apis == []


def test_resource_set_allowed_skills_apis_and_cross_validation():
    api_sms = parse_api_yaml("name: smsApi\ntitle: 短信\nprocessCode: smsApi\n")
    api_pdf = parse_api_yaml("name: pdfApi\ntitle: 单据\nconnector: http\nurl: https://pdf.example/q\n")

    sk_tpl = parse_skill_markdown("---\nname: tpl-skill\ntitle: 模板技能\ndescription: d\nscope: template\napis: [smsApi]\n---\nbody")
    sk_global = parse_skill_markdown("---\nname: global-pdf\ntitle: 全局单据\ndescription: d\nscope: global\napis: [pdfApi]\n---\nbody")
    sk_chat = parse_skill_markdown("---\nname: chat-helper\ntitle: 聊天助手\ndescription: d\nscope: chat\napis: []\n---\nbody")
    sk_chat_bad = parse_skill_markdown("---\nname: chat-bad\ntitle: 违规聊天\ndescription: d\nscope: chat\napis: [pdfApi]\n---\nbody")

    rs = ResourceSet(
        system_prompt="sys",
        apis={"smsApi": api_sms, "pdfApi": api_pdf},
        skills={
            "tpl-skill": sk_tpl,
            "global-pdf": sk_global,
            "chat-helper": sk_chat,
            "chat-bad": sk_chat_bad,
        },
    )

    # 模板未绑定 global-pdf，但 allowed_skills / allowed_apis 自动注入 global-pdf 及其 pdfApi
    tpl_clean = _make_template(["tpl-skill"])
    assert rs.allowed_skills(tpl_clean) == ["tpl-skill", "global-pdf"]
    assert rs.allowed_apis(tpl_clean) == ["smsApi", "pdfApi"]
    assert [i.code for i in validate_template(tpl_clean, rs)] == []

    # 模板未显式绑定任何技能但有全局技能时，不报 NO_SKILL
    tpl_empty = _make_template([])
    assert rs.allowed_skills(tpl_empty) == ["global-pdf"]
    assert rs.allowed_apis(tpl_empty) == ["pdfApi"]
    assert "NO_SKILL" not in [i.code for i in validate_template(tpl_empty, rs)]

    # 模板冗余绑定 global 或误绑 chat：产生告警，且运行时过滤掉 chat 技能
    tpl_warn = _make_template(["global-pdf", "chat-helper"])
    warn_codes = {i.code for i in validate_template(tpl_warn, rs)}
    assert "GLOBAL_SKILL_REDUNDANT" in warn_codes
    assert "CHAT_SKILL_IN_TEMPLATE" in warn_codes
    assert rs.allowed_skills(tpl_warn) == ["global-pdf"]

    # chat 技能声明业务接口触发 CHAT_SKILL_HAS_APIS 阻塞错误
    chat_err_codes = {i.code for i in validate_skill(sk_chat_bad, rs)}
    assert "CHAT_SKILL_HAS_APIS" in chat_err_codes


async def test_runner_auto_injects_global_skill_and_chat_loads_chat_scope(container):
    # 1. 发布一个常规 HTTP 接口 + 一个 scope: global 技能（未绑定到模板 1001）
    api_yaml = yaml.safe_dump({
        "name": "globalPdfApi",
        "title": "全局单据查询",
        "connector": "http",
        "method": "POST",
        "url": "https://pdf.internal.example/query",
        "bodyType": "json",
        "input": {
            "type": "object",
            "required": ["手机号码"],
            "properties": {"手机号码": {"type": "string"}},
        },
        "request": {"mobile": "${手机号码}"},
        "response": {
            "format": "json",
            "records": {"mode": "scalar", "path": "pdfText", "columns": {"value": "单据全文"}},
            "summary": {"maxPreviewChars": -1},
        },
    }, allow_unicode=True, sort_keys=False)
    container.service.save_api("globalPdfApi", api_yaml, "tester", action="create")
    container.service.publish_draft(api_ref("globalPdfApi"), "tester", "发布全局单据 API")

    (container.layout.mock_gateway / "globalPdfApi.json").write_text(
        json.dumps({"pdfText": "受理网点：南京鼓楼营业厅；鉴权方式：服务密码"}, ensure_ascii=False),
        encoding="utf-8",
    )

    global_skill_md = build_skill_markdown(
        "global-pdf-loader",
        "全局单据加载",
        "上游未传单据时自动加载单据正文",
        ["globalPdfApi"],
        scope="global",
    )
    container.service.save_skill("global-pdf-loader", global_skill_md, "tester", action="create")
    container.service.publish_draft(skill_ref("global-pdf-loader"), "tester", "发布全局技能")

    # 2. 模板 1001 并未绑定 global-pdf-loader，但运行时自动允许加载该技能并调用 globalPdfApi
    _, live_rs = container.service.live()
    tpl = live_rs.templates[1001]
    assert "global-pdf-loader" not in tpl.definition.skills
    assert "global-pdf-loader" in live_rs.allowed_skills(tpl)
    assert "globalPdfApi" in live_rs.allowed_apis(tpl)

    # 3. 验证 ChatAgent 的 load_skill 允许加载新增的 scope: chat 技能，并拒绝 global 技能
    chat_skill_md = build_skill_markdown(
        "chat-reply-policy",
        "聊天回复口径规范",
        "规定聊天窗口回复格式与注意事项",
        [],
        scope="chat",
    )
    container.service.save_skill("chat-reply-policy", chat_skill_md, "tester", action="create")
    container.service.publish_draft(skill_ref("chat-reply-policy"), "tester", "发布聊天专用技能")
    _, live_rs2 = container.service.live()

    class _DummyCtx:
        def __init__(self, deps: ChatDeps) -> None:
            self.deps = deps

    ctx = _DummyCtx(ChatDeps(rev="r1", resources=live_rs2, session={}, get_run_detail=lambda _rid: None))
    loaded_chat = await chat_load_skill(ctx, "chat-reply-policy")
    assert "聊天回复口径规范" in loaded_chat

    denied_global = await chat_load_skill(ctx, "global-pdf-loader")
    assert "错误" in denied_global and "global-pdf-loader" in denied_global

    # 4. 真实通过 FunctionModel 跑一次模板 1001，确认模型能直接调用未绑定的全局技能和接口
    def _global_flow(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        step = sum(1 for m in messages if isinstance(m, ModelResponse))
        if step == 0:
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "global-pdf-loader"})])
        if step == 1:
            return ModelResponse(parts=[ToolCallPart("call_api", {"name": "globalPdfApi", "args": {"手机号码": "13900001234"}})])
        nf = {"status": "not_found", "value": None, "evidence": [], "reasoning": "未提供"}
        report = {
            "订购短信": nf,
            "二次确认短信": nf,
            "验证码短信": nf,
            "受理渠道": nf,
            "争议类型": nf,
            "受理网点": {
                "status": "found",
                "value": "南京鼓楼营业厅",
                "evidence": [{"type": "api", "resultId": "r1", "row": 0, "column": "value"}],
                "reasoning": "来自全局单据接口",
            },
            "鉴权方式": {
                "status": "found",
                "value": "服务密码",
                "evidence": [{"type": "api", "resultId": "r1", "row": 0, "column": "value"}],
                "reasoning": "来自全局单据接口",
            },
            "标准资费": nf,
            "业务套餐内容": nf,
            "活动时间": nf,
            "活动内容": nf,
            "客户承诺": nf,
            "商品名称": {"status": "found", "value": "5G智享套餐", "evidence": [{"type": "input", "key": "业务名称"}], "reasoning": "入参"},
            "受理日期": nf,
            "受理方式": nf,
            "是否录音": nf,
            "业务名称": {"status": "found", "value": "5G智享套餐", "evidence": [{"type": "input", "key": "业务名称"}], "reasoning": "入参"},
        }
        return ModelResponse(parts=[ToolCallPart("submit_report", report)])

    container.runner.model = FunctionModel(_global_flow)
    run_detail = await container.runner.run(
        RunRequest(
            template_id=1001,
            inputs={"手机号码": "13900001234", "业务名称": "5G智享套餐", "创建时间": "20261105103012"},
            document="",
        )
    )
    assert "global-pdf-loader" in run_detail["skillsLoaded"]
    auth_field = next(f for f in run_detail["fields"] if f["name"] == "鉴权方式")
    assert auth_field["status"] == "found" and auth_field["value"] == "服务密码"


def test_skill_scope_rest_api_endpoints(container):
    UserStore(container.layout.config / "users.yaml").upsert("admin", "pass-1234", "管理员", "平台管理")
    app = create_app(container=container)
    with TestClient(app) as client:
        token = client.post("/api/v1/auth/login", json={"username": "admin", "password": "pass-1234"}).json()["token"]
        h = {"Authorization": f"Bearer {token}"}

        # 1. 创建 global 技能
        r_g = client.post(
            "/api/v1/skills",
            headers=h,
            json={
                "id": "global-doc-demo",
                "name": "全局单据演示",
                "description": "所有模板自动持有",
                "scope": "global",
                "apis": ["querySMSSendInfo"],
            },
        )
        assert r_g.status_code == 200, r_g.text
        assert r_g.json()["scope"] == "global"

        # 2. 创建 chat 技能并尝试绑定 API → 返回 400
        r_chat_bad = client.post(
            "/api/v1/skills",
            headers=h,
            json={
                "id": "chat-bad-demo",
                "name": "违规聊天技能",
                "scope": "chat",
                "apis": ["querySMSSendInfo"],
            },
        )
        assert r_chat_bad.status_code == 400

        # 3. 合法创建 chat 技能，列表返回准确 scope
        r_c = client.post(
            "/api/v1/skills",
            headers=h,
            json={"id": "chat-ok-demo", "name": "聊天规范演示", "description": "规范", "scope": "chat", "apis": []},
        )
        assert r_c.status_code == 200 and r_c.json()["scope"] == "chat"

        skills = client.get("/api/v1/skills", headers=h).json()
        scope_map = {s["id"]: s["scope"] for s in skills}
        assert scope_map["global-doc-demo"] == "global"
        assert scope_map["chat-ok-demo"] == "chat"
