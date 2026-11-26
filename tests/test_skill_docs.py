"""多文件 Skill 子目录 Markdown 懒加载全链路测试（领域校验、存储发布回退、运行时/聊天懒加载与 REST API）。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from report_agent.api.auth import UserStore
from report_agent.chat.agent import ChatDeps, load_skill as chat_load_skill
from report_agent.domain.resources import ResourceSet, load_resource_dir, validate_skill
from report_agent.domain.skill import (
    MAX_SKILL_DOCS,
    SkillParseError,
    extract_doc_title,
    extract_md_doc_links,
    normalize_skill_doc_path,
    parse_skill_markdown,
)
from report_agent.domain.template import Template, parse_template_yaml
from report_agent.main import create_app
from report_agent.runtime.runner import RunRequest
from report_agent.store.publisher import NothingToPublish
from report_agent.store.service import skill_ref


def _make_simple_template(tid: int, name: str = "测试模板") -> Template:
    defn = parse_template_yaml(yaml.safe_dump({
        "id": tid,
        "name": name,
        "skills": [],
        "inputs": [{"key": "手机号码", "required": True}],
        "fields": [{"name": "结论", "evidence": "quote", "description": "结论"}],
    }, allow_unicode=True))
    return Template(definition=defn, body="{{ 结论 }}")


def test_normalize_skill_doc_path_security_and_titles():
    # 合法路径：同级、一级子目录、两级子目录、带前导 ./、中文文件名
    assert normalize_skill_doc_path("guide.md") == "guide.md"
    assert normalize_skill_doc_path("./references/broadband.md") == "references/broadband.md"
    assert normalize_skill_doc_path("references/sms/case-1.md") == "references/sms/case-1.md"
    assert normalize_skill_doc_path("说明/宽带细则_v1.md") == "说明/宽带细则_v1.md"

    # 非法路径全部拦截
    bad_cases = [
        "",
        "   ",
        "/etc/passwd.md",
        "../secret.md",
        "references/../secret.md",
        "references\\a.md",
        ".hidden/a.md",
        "references/.secret.md",
        "SKILL.md",
        "skill.md",
        "references/guide.txt",
        "a/b/c/d.md",  # 深度超过 3（超过两级子目录）
        "references//a.md",
        "references/bad name.md",
        "references/a\nb.md",
    ]
    for bad in bad_cases:
        with pytest.raises(SkillParseError):
            normalize_skill_doc_path(bad)

    # 标题提取（跳过可选 frontmatter）
    assert extract_doc_title("# 宽带退订核查细则\n\n正文") == "宽带退订核查细则"
    assert extract_doc_title("---\ntitle: ignore\n---\n\n## 二级标题\n内容") == "二级标题"
    assert extract_doc_title("没有标题时取首行") == "没有标题时取首行"

    # 相对链接解析（忽略代码块、行内代码、外链、纯锚点、非 .md）
    md = (
        "见 [宽带细则](./references/broadband.md#sec1) 与 [外链](https://example.com/a.md)\n"
        "以及行内示例 `[假链接](references/fake.md)` 和锚点 [顶部](#top)\n"
        "```markdown\n[代码块示例](references/in-code.md)\n```\n"
        "返回 [首页](../SKILL.md) 或 [同级](./sibling.md)\n"
    )
    links_main = extract_md_doc_links(md, current_doc="SKILL.md")
    assert [resolved for _, resolved in links_main] == [
        "references/broadband.md",
        "../SKILL.md",
        "sibling.md",
    ]
    # 在 references/a.md 中引用同目录 b.md 和主文件 ../SKILL.md
    links_sub = extract_md_doc_links("见 [B](b.md) 和 [主文件](../SKILL.md)", current_doc="references/a.md")
    assert [resolved for _, resolved in links_sub] == ["references/b.md", "SKILL.md"]


def test_validate_skill_links_orphans_symlink_and_router_across_docs(tmp_path: Path):
    # 1. 断链 error + 孤儿 warning + 多跳可达正常
    sk = parse_skill_markdown(
        "---\nname: multi-doc\ntitle: 多文档技能\ndescription: 描述\napis: []\n---\n"
        "参见 [入口](references/a.md) 与 [缺失](references/missing.md)\n",
        docs={
            "references/a.md": "# 文档 A\n继续看 [文档 B](b.md) 和 [返回主文件](../SKILL.md)",
            "references/b.md": "# 文档 B\n具体规则",
            "examples/orphan.md": "# 孤儿文档\n没有被任何文件引用",
        },
    )
    rs = ResourceSet(system_prompt="sys", skills={"multi-doc": sk})
    issues = validate_skill(sk, rs)
    by_code = {i.code: i for i in issues}
    assert "SKILL_DOC_NOT_FOUND" in by_code and by_code["SKILL_DOC_NOT_FOUND"].level == "error"
    assert by_code["SKILL_DOC_NOT_FOUND"].field == "SKILL.md"
    assert "SKILL_DOC_UNREFERENCED" in by_code and by_code["SKILL_DOC_UNREFERENCED"].level == "warning"
    assert by_code["SKILL_DOC_UNREFERENCED"].field == "examples/orphan.md"
    # references/b.md 经由 a.md 多跳可达，不应误报孤儿
    assert all(not (i.code == "SKILL_DOC_UNREFERENCED" and i.field == "references/b.md") for i in issues)

    # 2. 超过 MAX_SKILL_DOCS 上限报错
    too_many = {f"references/d{i}.md": f"# 文档 {i}" for i in range(MAX_SKILL_DOCS + 1)}
    with pytest.raises(SkillParseError, match="最多支持"):
        parse_skill_markdown("---\nname: x\n---\nbody", docs=too_many)

    # 3. template-router 拆分子文档时，validate_skill 跨 SKILL.md + docs 扫描 ### <ID>
    router_sk = parse_skill_markdown(
        "---\nname: template-router\ntitle: 路由\ndescription: 路由\nscope: chat\napis: []\n---\n"
        "见 [资费类](references/fee.md)\n",
        docs={
            "references/fee.md": "# 资费类模板\n\n### 101 资费争议\n适用资费争议\n\n### 999 不存在模板\n坏模板\n",
        },
    )
    rs_router = ResourceSet(
        system_prompt="sys",
        templates={101: _make_simple_template(101, "资费争议"), 102: _make_simple_template(102, "宽带争议")},
        skills={"template-router": router_sk},
    )
    r_issues = validate_skill(router_sk, rs_router)
    r_codes = {i.code for i in r_issues}
    assert "ROUTER_TEMPLATE_NOT_FOUND" in r_codes  # 命中 999
    assert "ROUTER_TEMPLATE_UNCOVERED" in r_codes  # 提示 102 未覆盖，而 101 已被子文档覆盖
    assert all("101" not in i.message for i in r_issues if i.code == "ROUTER_TEMPLATE_UNCOVERED")

    # 4. 磁盘加载拒绝软链接逃逸
    outside = tmp_path / "secret.md"
    outside.write_text("# 外部机密", encoding="utf-8")
    res_root = tmp_path / "res"
    sdir = res_root / "skills" / "evil-skill"
    (sdir / "references").mkdir(parents=True)
    (sdir / "SKILL.md").write_text("---\nname: evil-skill\ntitle: 坏技能\ndescription: d\n---\nbody", encoding="utf-8")
    (sdir / "references" / "link.md").symlink_to(outside)
    loaded = load_resource_dir(res_root)
    assert "evil-skill" not in loaded.skills
    assert any(i.code == "LOAD_FAILED" and i.key == "evil-skill" for i in loaded.load_issues)


def test_store_multifile_skill_draft_publish_fingerprint_and_rollback(container):
    sid = "layered-guide"
    md_v1 = (
        "---\nname: layered-guide\ntitle: 分层核查指引\ndescription: 分层文档\nscope: template\napis: []\n---\n"
        "主流程见 [宽带细则](references/broadband.md) 与 [案例](examples/case-1.md)\n"
    )
    docs_v1 = {
        "references/broadband.md": "# 宽带细则\n宽带 v1 规则",
        "examples/case-1.md": "# 案例一\nv1 案例",
    }
    container.service.save_skill(sid, md_v1, "tester", action="create", docs=docs_v1)

    # 验证 overlay 缓存命中并在直接改盘嵌套子文档时通过 _drafts_fingerprint 自动失效
    rs_before = container.service.overlay()
    assert rs_before.skills[sid].docs["references/broadband.md"] == "# 宽带细则\n宽带 v1 规则"
    sub_file = container.layout.draft_dir(skill_ref(sid)) / "references" / "broadband.md"
    sub_file.write_text("# 宽带细则\n直接改盘后的内容", encoding="utf-8")
    rs_after = container.service.overlay()
    assert rs_after.skills[sid].docs["references/broadband.md"] == "# 宽带细则\n直接改盘后的内容"

    # 恢复 v1 并发布为 r_v1
    container.service.save_skill(sid, md_v1, "tester", docs=docs_v1)
    pub1 = container.service.publish_draft(skill_ref(sid), "tester", "发布 v1 多文件 Skill")
    rev1 = pub1.entry["rev"]

    # 未改内容重新保存（包含老调用方 docs=None 保留已有子文档）→ _same_as_online 拒绝重复发布
    container.service.save_skill(sid, md_v1, "tester")
    assert container.service.skill_docs(sid, "working") == docs_v1
    with pytest.raises(NothingToPublish):
        container.service.publish_draft(skill_ref(sid), "tester", "空发布")

    # 仅修改子文档（SKILL.md 一字未改）→ 可正常发布为 r_v2
    docs_v2 = {
        "references/broadband.md": "# 宽带细则\n宽带 v2 更新规则",
        "examples/case-1.md": "# 案例一\nv1 案例",
        "references/extra.md": "# 新增补充\n由 [宽带细则](broadband.md) 互链",
    }
    md_v2 = md_v1 + "以及 [新增补充](references/extra.md)\n"
    container.service.save_skill(sid, md_v2, "tester", docs=docs_v2)
    pub2 = container.service.publish_draft(skill_ref(sid), "tester", "发布 v2")
    assert pub2.entry["rev"] != rev1
    assert container.service.skill_docs(sid, "online") == docs_v2
    assert container.service.skill_docs(sid, rev1) == docs_v1

    # 回退 draft_only 至 rev1：应完整还原嵌套子文档并移除 v2 新增的 references/extra.md
    container.service.rollback(skill_ref(sid), rev1, "draft_only", "核对旧版", "tester")
    assert container.service.skill_docs(sid, "working") == docs_v1
    assert "references/extra.md" not in (container.service.skill_docs(sid, "working") or {})

    # 回退 publish_now 至 rev1：线上直接恢复 v1 子文档集合
    container.service.rollback(skill_ref(sid), rev1, "publish_now", "紧急回退", "tester")
    assert container.service.skill_docs(sid, "online") == docs_v1


async def test_runtime_and_chat_lazy_load_skill_subdocs(container):
    # 1. 创建一个带子目录文档的 global Skill（所有模板可用），供 AgentRunner 测试 L1 + L2 懒加载
    md_global = (
        "---\nname: tiered-global\ntitle: 分层全局规则\ndescription: 包含子目录参考文档\nscope: global\napis: []\n---\n"
        "主说明只放摘要，详细规则请按需加载 [宽带退订细则](references/broadband.md) 或 [漫游细则](references/roaming.md)。\n"
    )
    docs_global = {
        "references/broadband.md": "# 宽带退订核查细则\n唯一口令：BROADBAND-SECRET-OK",
        "references/roaming.md": "# 漫游资费细则\n唯一口令：ROAMING-SECRET-OK",
    }
    container.service.save_skill("tiered-global", md_global, "tester", action="create", docs=docs_global)
    container.service.publish_draft(skill_ref("tiered-global"), "tester", "发布分层全局技能")

    captured_tool_returns: list[str] = []

    def _lazy_flow(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        # 收集工具返回文本以断言 L1 不含子文档正文但含索引，L2 仅返回按需请求的子文档
        for msg in messages:
            for part in getattr(msg, "parts", ()):
                if getattr(part, "tool_name", None) == "load_skill" and hasattr(part, "content"):
                    content = str(part.content)
                    if content not in captured_tool_returns:
                        captured_tool_returns.append(content)
        step = sum(1 for m in messages if isinstance(m, ModelResponse))
        if step == 0:
            # L1：仅加载主 SKILL.md
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "tiered-global"})])
        if step == 1:
            # L2：故意请求一个不存在的子文档触发重试提示
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "tiered-global", "doc": "references/nope.md"})])
        if step == 2:
            # L2：按需加载 ./references/broadband.md（验证 ./ 自动规范化）
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "tiered-global", "doc": "./references/broadband.md"})])
        nf = {"status": "not_found", "value": None, "evidence": [], "reasoning": "未提供"}
        report = {
            "订购短信": nf,
            "二次确认短信": nf,
            "验证码短信": nf,
            "受理渠道": nf,
            "争议类型": nf,
            "受理网点": nf,
            "鉴权方式": nf,
            "标准资费": nf,
            "业务套餐内容": nf,
            "活动时间": nf,
            "活动内容": nf,
            "客户承诺": nf,
            "商品名称": {"status": "found", "value": "宽带套餐", "evidence": [{"type": "input", "key": "业务名称"}], "reasoning": "入参"},
            "受理日期": nf,
            "受理方式": nf,
            "是否录音": nf,
            "业务名称": {"status": "found", "value": "宽带套餐", "evidence": [{"type": "input", "key": "业务名称"}], "reasoning": "入参"},
        }
        return ModelResponse(parts=[ToolCallPart("submit_report", report)])

    container.runner._bundle = dataclasses.replace(container.runner._bundle, model=FunctionModel(_lazy_flow))
    container.runner._agent_cache.clear()
    detail = await container.runner.run(
        RunRequest(
            template_id=1001,
            inputs={"手机号码": "13900001234", "业务名称": "宽带套餐", "创建时间": "20261105103012"},
            document="普通单据",
        )
    )
    assert "tiered-global" in detail["skillsLoaded"]
    # L1 返回包含参考文档索引，不含子文档具体口令
    l1 = captured_tool_returns[0]
    assert "可按需加载的参考文档" in l1
    assert "references/broadband.md" in l1 and "宽带退订核查细则" in l1
    assert "BROADBAND-SECRET-OK" not in l1 and "ROAMING-SECRET-OK" not in l1
    # L2 请求缺失文档给出可用文档提示
    assert any("不存在子文档" in t and "references/broadband.md" in t for t in captured_tool_returns)
    # L2 成功懒加载 broadband.md，但不泄露未请求的 roaming.md
    l2_ok = next(t for t in captured_tool_returns if "BROADBAND-SECRET-OK" in t)
    assert "references/broadband.md" in l2_ok
    assert "ROAMING-SECRET-OK" not in l2_ok

    # 2. 验证 ChatAgent 的 load_skill 同样支持 L1 索引 + L2 子文档按需懒加载
    md_chat = (
        "---\nname: chat-faq\ntitle: 聊天问答手册\ndescription: 分层手册\nscope: chat\napis: []\n---\n"
        "按场景加载 [退订话术](references/cancel.md)\n"
    )
    docs_chat = {"references/cancel.md": "# 退订话术\nCHAT-CANCEL-RULE"}
    container.service.save_skill("chat-faq", md_chat, "tester", action="create", docs=docs_chat)
    container.service.publish_draft(skill_ref("chat-faq"), "tester", "发布分层聊天技能")
    _, live_rs = container.service.live()

    class _DummyCtx:
        def __init__(self, deps: ChatDeps) -> None:
            self.deps = deps

    ctx = _DummyCtx(ChatDeps(rev="r1", resources=live_rs, session={}, get_run_detail=lambda _rid: None))
    chat_l1 = await chat_load_skill(ctx, "chat-faq")
    assert "可按需加载的参考文档" in chat_l1 and "references/cancel.md" in chat_l1
    assert "CHAT-CANCEL-RULE" not in chat_l1

    chat_l2 = await chat_load_skill(ctx, "chat-faq", docs=["./references/cancel.md"])
    assert "CHAT-CANCEL-RULE" in chat_l2

    chat_bad = await chat_load_skill(ctx, "chat-faq", doc="../SKILL.md")
    assert "错误" in chat_bad and "references/cancel.md" in chat_bad


def test_skill_docs_rest_api_lifecycle(container):
    UserStore(container.layout.config / "users.yaml").upsert("admin", "pass-1234", "管理员", "平台管理")
    app = create_app(container=container)
    with TestClient(app) as client:
        token = client.post("/api/v1/auth/login", json={"username": "admin", "password": "pass-1234"}).json()["token"]
        h = {"Authorization": f"Bearer {token}"}

        # 1. 创建 Skill
        r_create = client.post(
            "/api/v1/skills",
            headers=h,
            json={"id": "api-multidoc", "name": "多文档接口测试", "description": "测试", "scope": "template", "apis": []},
        )
        assert r_create.status_code == 200
        assert r_create.json()["docsCount"] == 0

        # 2. 保存带子文档的草稿（故意带一条孤儿文档 + 一条有效引用）
        md_v1 = (
            "---\nname: api-multidoc\ntitle: 多文档接口测试\ndescription: 测试\nscope: template\napis: []\n---\n"
            "详见 [指南](references/guide.md)\n"
        )
        docs_v1 = {
            "references/guide.md": "# 使用指南\n正文 v1",
            "examples/unused.md": "# 孤儿样例\n未引用",
        }
        r_save = client.put(
            "/api/v1/skills/api-multidoc/draft",
            headers=h,
            json={"markdown": md_v1, "docs": docs_v1},
        )
        assert r_save.status_code == 200, r_save.text
        save_data = r_save.json()
        assert save_data["docs"] == docs_v1
        assert any(i["code"] == "SKILL_DOC_UNREFERENCED" for i in save_data["issues"])

        # 3. GET 返回 docs、docsCount 与 docPaths
        r_get = client.get("/api/v1/skills/api-multidoc", headers=h)
        assert r_get.status_code == 200
        get_data = r_get.json()
        assert get_data["docs"] == docs_v1
        assert get_data["item"]["docsCount"] == 2
        assert get_data["item"]["docPaths"] == ["examples/unused.md", "references/guide.md"]

        # 4. 非法路径被拦截（400）
        r_bad = client.put(
            "/api/v1/skills/api-multidoc/draft",
            headers=h,
            json={"markdown": md_v1, "docs": {"../escape.md": "# bad"}},
        )
        assert r_bad.status_code == 400

        # 5. 发布 v1，再改子文档为 v2，再 discard-draft 恢复 v1 的 docs
        r_pub = client.post("/api/v1/skills/api-multidoc/publish", headers=h, json={"note": "v1"})
        assert r_pub.status_code == 200
        rev1 = r_pub.json()["rev"]

        docs_v2 = {"references/guide.md": "# 使用指南\n正文 v2"}
        r_save2 = client.put(
            "/api/v1/skills/api-multidoc/draft",
            headers=h,
            json={"markdown": md_v1, "docs": docs_v2},
        )
        assert r_save2.status_code == 200

        r_discard = client.post("/api/v1/skills/api-multidoc/discard-draft", headers=h)
        assert r_discard.status_code == 200
        assert r_discard.json()["docs"] == docs_v1

        # 6. 发布 v2 后 rollback 回 rev1，响应直接带回 rev1 的 docs
        client.put("/api/v1/skills/api-multidoc/draft", headers=h, json={"markdown": md_v1, "docs": docs_v2})
        client.post("/api/v1/skills/api-multidoc/publish", headers=h, json={"note": "v2"})
        r_rb = client.post(
            "/api/v1/skills/api-multidoc/rollback",
            headers=h,
            json={"targetRev": rev1, "mode": "draft_only", "reason": "恢复 v1"},
        )
        assert r_rb.status_code == 200
        assert r_rb.json()["docs"] == docs_v1
