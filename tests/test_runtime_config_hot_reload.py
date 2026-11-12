"""运行配置磁盘持久化、免重启热更新、版本回退及系统提示词历史版本读取测试。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from report_agent.api.auth import UserStore
from report_agent.config import Settings
from report_agent.container import build_container
from report_agent.domain.api_contract import ApiContract
from report_agent.gateway.base import ApiCallResult
from report_agent.gateway.mock import MockGatewayClient
from report_agent.gateway.reloadable import ReloadableGatewayClient
from report_agent.gateway.unified_xml import UnifiedGatewayXmlClient
from report_agent.main import create_app
from scripted_model import scripted_model


def _make_client(c) -> TestClient:
    UserStore(c.layout.config / "users.yaml").upsert("chenxiaoyun", "pass-1234", "陈晓芸", "系统维护")
    app = create_app(container=c)
    return TestClient(app)


def _login(client: TestClient) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"username": "chenxiaoyun", "password": "pass-1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_runtime_config_bootstrap_hot_reload_persistence_rollback_and_sync_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    data_dir = tmp_path / "data"
    boot_env = Settings(
        _env_file=None,
        data_dir=data_dir,
        llm_base_url="https://llm-init.internal/v1",
        llm_api_key="sk-initial-secret-1111",
        llm_model="deepseek-v4-flash",
        llm_temperature=0.1,
        gateway_mode="mock",
        gateway_xml_style="java",
        admin_token_secret="test-secret",
    )
    # 不注入外部假模型/网关，真实测试 OpenAIChatModel 与网关实例热重建
    c = build_container(boot_env)

    runtime_dir = c.layout.config / "runtime"
    current_path = runtime_dir / "current.json"
    c1_path = runtime_dir / "revisions" / "c1.json"
    index_path = runtime_dir / "index.jsonl"
    assert current_path.is_file()
    assert c1_path.is_file()
    assert index_path.is_file()
    assert (current_path.stat().st_mode & 0o777) == 0o600
    assert (c1_path.stat().st_mode & 0o777) == 0o600
    assert (index_path.stat().st_mode & 0o777) == 0o600

    c1_doc = json.loads(c1_path.read_text(encoding="utf-8"))
    assert c1_doc["rev"] == "c1"
    assert c1_doc["operator"] == "system"
    assert c1_doc["type"] == "初始化"
    assert c1_doc["summary"] == "启动初始化（从环境变量释放）"
    assert isinstance(c.gateway, ReloadableGatewayClient)
    assert isinstance(c.gateway.current, MockGatewayClient)

    with _make_client(c) as client:
        # 未登录禁止访问全部运行配置接口
        assert client.get("/api/v1/settings/runtime").status_code == 401
        assert client.put("/api/v1/settings/runtime", json={}).status_code == 401
        assert client.get("/api/v1/settings/runtime/revisions").status_code == 401
        assert client.post("/api/v1/settings/runtime/rollback", json={"targetRev": "c1"}).status_code == 401
        assert client.post("/api/v1/settings/runtime/sync-env", json={}).status_code == 401

        h = _login(client)

        # 1. 读取初始运行配置（验证密钥脱敏与完整公开字段）
        r_get = client.get("/api/v1/settings/runtime", headers=h)
        assert r_get.status_code == 200, r_get.text
        st1 = r_get.json()
        assert st1["activeRev"] == "c1"
        assert st1["operator"] == "system"
        cfg1 = st1["config"]
        assert cfg1["llmModel"] == "deepseek-v4-flash"
        assert cfg1["llmBaseUrl"] == "https://llm-init.internal/v1"
        assert cfg1["hasLlmApiKey"] is True
        assert cfg1["llmApiKeyMasked"] == "sk-***1111"
        assert "llmApiKey" not in cfg1
        assert "gatewayAppId" not in cfg1
        assert "gatewayAccessToken" not in cfg1
        assert "sk-initial-secret-1111" not in r_get.text

        # 2. PUT 热更新模型 + 智能体参数 + 切换真实网关 live 模式（无需重启 FastAPI）
        r_put = client.put(
            "/api/v1/settings/runtime",
            headers=h,
            json={
                "llmBaseUrl": "https://llm-prod.internal/v1",
                "llmApiKey": "sk-prod-key-9999",
                "llmModel": "deepseek-r1-enterprise",
                "llmTemperature": 0.6,
                "llmMaxTokens": 4096,
                "llmTimeoutS": 90,
                "llmHttpRetries": 3,
                "llmParallelToolCalls": False,
                "llmStrictTools": False,
                "llmToolChoiceRequired": True,
                "agentOutputMode": "json_object",
                "agentNativeStrict": False,
                "agentOutputRetries": 4,
                "agentToolRetries": 3,
                "agentRequestLimit": 30,
                "agentToolCallsLimit": 60,
                "agentRunTimeoutS": 300,
                "agentMaxConcurrentRuns": 4,
                "agentPreviewRows": 20,
                "gatewayMode": "live",
                "gatewayUrl": "https://gw-prod.internal:8443",
                "gatewayAppId": "app-prod-123456",
                "gatewayAccessToken": "tok-prod-secret-abcd",
                "gatewayXmlStyle": "clean",
                "gatewayConnectTimeoutS": 8.5,
                "note": "切换生产网关与推理模型",
            },
        )
        assert r_put.status_code == 200, r_put.text
        st2 = r_put.json()
        assert st2["activeRev"] == "c2"
        assert st2["operator"] == "陈晓芸"
        assert st2["note"] == "切换生产网关与推理模型"
        assert st2["config"]["llmModel"] == "deepseek-r1-enterprise"
        assert st2["config"]["llmApiKeyMasked"] == "sk-***9999"
        assert st2["config"]["hasGatewayAppId"] is True
        assert st2["config"]["gatewayAppIdMasked"] == "app***3456"
        assert st2["config"]["hasGatewayAccessToken"] is True
        assert st2["config"]["gatewayAccessTokenMasked"] == "tok***abcd"

        # 验证内存中的 Container / AgentRunner / ReloadableGatewayClient 已立即生效
        assert c.settings.llm_model == "deepseek-r1-enterprise"
        assert c.settings.llm_api_key.get_secret_value() == "sk-prod-key-9999"
        assert c.runner.model.model_name == "deepseek-r1-enterprise"
        assert c.runner.model_settings == {"temperature": 0.6, "timeout": 90.0, "max_tokens": 4096,
                                           "parallel_tool_calls": False}
        assert c.runner._sem._value == 4
        assert c.runner._tools[0].max_retries == 3
        assert isinstance(c.gateway.current, UnifiedGatewayXmlClient)
        assert c.gateway.current.url == "https://gw-prod.internal:8443/openapi_3"
        assert c.gateway.current.app_id == "app-prod-123456"
        assert c.gateway.current.access_token == "tok-prod-secret-abcd"
        assert c.gateway.current.style == "clean"
        assert c.gateway.current.connect_timeout_s == 8.5

        # 验证兼容端点 GET /api/v1/settings/model 同步反映最新参数与新增字段
        m_info = client.get("/api/v1/settings/model", headers=h).json()
        assert m_info["model"] == "deepseek-r1-enterprise"
        assert m_info["baseUrl"] == "https://llm-prod.internal/v1"
        assert m_info["maxTokens"] == 4096
        assert m_info["gatewayMode"] == "live"
        assert m_info["gatewayUrl"] == "https://gw-prod.internal:8443"
        assert m_info["gatewayConnectTimeoutS"] == 8.5
        assert m_info["activeRev"] == "c2"

        # 3. 无实质变更的 PUT 请求应幂等返回 c2，不产生冗余版本
        r_noop = client.put(
            "/api/v1/settings/runtime",
            headers=h,
            json={**st2["config"], "llmApiKey": "", "gatewayAppId": "app***3456", "gatewayAccessToken": None},
        )
        assert r_noop.status_code == 200
        assert r_noop.json()["activeRev"] == "c2"

        # 4. 密钥留空 / 传脱敏串保持原密钥不变；显式 clearLlmApiKey / clearGatewayAppId=True 才清空（且无 OPENAI_API_KEY 环境变量时不崩溃）
        r_keep_secret = client.put(
            "/api/v1/settings/runtime",
            headers=h,
            json={
                "llmTemperature": 0.35,
                "llmApiKey": "",
                "gatewayAppId": "app***3456",
                "gatewayAccessToken": "",
                "note": "仅调低温度并保留密钥",
            },
        )
        assert r_keep_secret.status_code == 200
        assert r_keep_secret.json()["activeRev"] == "c3"
        assert c.settings.llm_api_key.get_secret_value() == "sk-prod-key-9999"
        assert c.settings.gateway_app_id.get_secret_value() == "app-prod-123456"
        assert c.settings.gateway_access_token.get_secret_value() == "tok-prod-secret-abcd"

        r_clear = client.put(
            "/api/v1/settings/runtime",
            headers=h,
            json={"clearLlmApiKey": True, "clearGatewayAppId": True, "note": "清空模型与网关密钥"},
        )
        assert r_clear.status_code == 200, r_clear.text
        assert r_clear.json()["activeRev"] == "c4"
        assert r_clear.json()["config"]["hasLlmApiKey"] is False
        assert r_clear.json()["config"]["llmApiKeyMasked"] == ""
        assert r_clear.json()["config"]["hasGatewayAppId"] is False
        assert r_clear.json()["config"]["gatewayAppIdMasked"] == ""
        assert c.settings.llm_api_key.get_secret_value() == ""
        assert c.settings.gateway_app_id.get_secret_value() == ""

        # 5. 非法参数校验（返回 400 且不破坏当前生效配置）
        bad_payloads = [
            {"gatewayMode": "live", "gatewayUrl": ""},
            {"gatewayMode": "live", "gatewayUrl": "ftp://gw.internal"},
            {"llmBaseUrl": "ftp://llm.internal/v1"},
            {"llmModel": "   "},
            {"llmTemperature": 2.5},
            {"llmMaxTokens": 0},
            {"llmTimeoutS": -1},
            {"llmHttpRetries": 99},
            {"agentOutputMode": "xml_mode"},
            {"agentMaxConcurrentRuns": 0},
            {"agentRequestLimit": 500},
            {"gatewayConnectTimeoutS": 0},
        ]
        for bad in bad_payloads:
            resp = client.put("/api/v1/settings/runtime", headers=h, json=bad)
            assert resp.status_code == 400, f"expected 400 for {bad}, got {resp.status_code}: {resp.text}"
        assert c.runtime_config.active_rev() == "c4"

        # 6. 模拟服务重启：在同一 data_dir 上用初始环境变量重新 build_container，应加载磁盘上的 c4（空 llmApiKey 亦正常启动）而非被环境变量覆盖
        restarted = build_container(boot_env)
        try:
            assert restarted.runtime_config.active_rev() == "c4"
            assert restarted.settings.llm_model == "deepseek-r1-enterprise"
            assert restarted.settings.llm_temperature == 0.35
            assert restarted.settings.llm_api_key.get_secret_value() == ""
            assert isinstance(restarted.gateway.current, UnifiedGatewayXmlClient)
            assert restarted.gateway.current.url == "https://gw-prod.internal:8443/openapi_3"
        finally:
            asyncio.run(restarted.gateway.aclose())

        # 7. 查看修订历史列表（倒序、脱敏、含 changedKeys 与 online 标记）
        revs = client.get("/api/v1/settings/runtime/revisions", headers=h).json()
        assert [x["rev"] for x in revs] == ["c4", "c3", "c2", "c1"]
        assert revs[0]["online"] is True and all(not x["online"] for x in revs[1:])
        assert revs[0]["changedKeys"] == ["llmApiKey", "gatewayAppId"]
        assert "llmModel" in revs[2]["changedKeys"] and "gatewayMode" in revs[2]["changedKeys"]
        raw_revs_text = json.dumps(revs, ensure_ascii=False)
        assert "sk-prod-key-9999" not in raw_revs_text
        assert "sk-initial-secret-1111" not in raw_revs_text
        assert "tok-prod-secret-abcd" not in raw_revs_text

        # 8. 回退至 c1：立即恢复初始模型、密钥与 Mock 网关
        assert client.post("/api/v1/settings/runtime/rollback", headers=h, json={"targetRev": "../evil"}).status_code == 400
        assert client.post("/api/v1/settings/runtime/rollback", headers=h, json={"targetRev": "c999"}).status_code == 404

        r_rb = client.post(
            "/api/v1/settings/runtime/rollback",
            headers=h,
            json={"targetRev": "c1", "reason": "生产网关演练结束切回初始快照"},
        )
        assert r_rb.status_code == 200, r_rb.text
        rb_data = r_rb.json()
        assert rb_data["activeRev"] == "c5"
        assert rb_data["targetRev"] == "c1"
        assert rb_data["config"]["llmModel"] == "deepseek-v4-flash"
        assert rb_data["config"]["gatewayMode"] == "mock"
        assert c.settings.llm_model == "deepseek-v4-flash"
        assert c.settings.llm_api_key.get_secret_value() == "sk-initial-secret-1111"
        assert c.runner.model.model_name == "deepseek-v4-flash"
        assert isinstance(c.gateway.current, MockGatewayClient)

        # 9. 修改配置后调用 sync-env 从启动环境变量重新同步
        client.put("/api/v1/settings/runtime", headers=h, json={"llmModel": "temp-override-model"})
        assert c.settings.llm_model == "temp-override-model"
        r_sync = client.post("/api/v1/settings/runtime/sync-env", headers=h, json={"note": "对齐容器环境变量"})
        assert r_sync.status_code == 200, r_sync.text
        sync_state = r_sync.json()
        assert sync_state["activeRev"] == "c7"
        assert sync_state["config"]["llmModel"] == "deepseek-v4-flash"
        assert c.settings.llm_model == "deepseek-v4-flash"

        # 再次调用 sync-env 无差异时不新增版本
        r_sync_noop = client.post("/api/v1/settings/runtime/sync-env", headers=h, json={})
        assert r_sync_noop.status_code == 200
        assert r_sync_noop.json()["activeRev"] == "c7"


def test_injected_test_doubles_preserved_and_inflight_gateway_drained(tmp_path: Path):
    """验证测试注入的 model/gateway 在非网关修改时保持不变，且网关热切换不会中断在途请求。"""

    class SlowFakeGateway:
        def __init__(self, tag: str) -> None:
            self.tag = tag
            self.closed = False
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def invoke(self, contract: ApiContract, args: dict[str, Any]) -> ApiCallResult:
            self.started.set()
            await self.release.wait()
            assert not self.closed, "在途请求完成前不应提前关闭旧网关实例"
            return ApiCallResult(ok=True, records=[{"tag": self.tag}])

        async def aclose(self) -> None:
            self.closed = True

    settings = Settings(_env_file=None, data_dir=tmp_path / "data", gateway_mode="mock", llm_api_key="test",
                        admin_token_secret="test-secret")
    fake_model = scripted_model()
    gw1 = SlowFakeGateway("gw1")
    c = build_container(settings, model=fake_model, gateway=gw1)

    # 仅更新大模型温度：注入的 fake_model 与 gw1 均保留
    c.runtime_config.update({"llmTemperature": 0.9}, "tester")
    c.apply_runtime_config()
    assert c.runner.model is fake_model
    assert c.gateway.current is gw1

    # 验证在途 invoke 期间执行 swap：旧实例待在途请求完成后才调用 aclose
    async def _exercise_drain() -> None:
        contract = next(iter(c.service.live()[1].apis.values()))
        inflight_task = asyncio.create_task(c.gateway.invoke(contract, {}))
        await gw1.started.wait()

        gw2 = SlowFakeGateway("gw2")
        gw2.release.set()
        c.gateway.swap(gw2)
        await c.gateway.aclose_retired()
        # gw1 仍有在途请求，此时绝不能被关闭
        assert gw1.closed is False

        # 新请求立即走 gw2
        res2 = await c.gateway.invoke(contract, {})
        assert res2.records == [{"tag": "gw2"}]

        # 放行 gw1 在途请求，返回后 gw1 自动安全关闭
        gw1.release.set()
        res1 = await inflight_task
        assert res1.records == [{"tag": "gw1"}]
        assert gw1.closed is True
        await c.gateway.aclose()
        assert gw2.closed is True

    asyncio.run(_exercise_drain())


def test_system_prompt_historical_versions_rollback_and_new_api_default_path(container):
    """验证系统提示词历史版本读取（?version=rN）、回退（draft_only / publish_now）与新建接口默认路径。"""
    with _make_client(container) as client:
        h = _login(client)

        # 1. 初始 r1 系统提示词
        sp_init = client.get("/api/v1/settings/system-prompt", headers=h).json()
        r1_text = sp_init["onlineText"]
        assert sp_init["onlineRev"] == "r1"
        assert sp_init["version"] == "working"
        assert sp_init["versionText"] == r1_text

        # 无草稿时访问 ?version=draft 返回 404
        assert client.get("/api/v1/settings/system-prompt?version=draft", headers=h).status_code == 404

        # 2. 发布新版本 r2，并在其上再保存未发布草稿
        r2_text = r1_text + "\n\n## 新增审核规范 v2\n- 严格核对时间窗口。"
        pub = client.post(
            "/api/v1/settings/system-prompt/publish",
            headers=h,
            json={"sysPromptText": r2_text, "note": "升级提示词 v2"},
        )
        assert pub.status_code == 200
        assert pub.json()["rev"] == "r2"
        assert pub.json()["onlineRev"] == "r2"

        draft_text = r2_text + "\n- 草稿实验规则"
        client.put("/api/v1/settings/system-prompt/draft", headers=h, json={"sysPromptText": draft_text})

        # 分别按 r1 / r2 / online / draft / working 读取
        v_r1 = client.get("/api/v1/settings/system-prompt?version=r1", headers=h)
        assert v_r1.status_code == 200
        assert v_r1.json()["version"] == "r1"
        assert v_r1.json()["versionText"] == r1_text
        assert v_r1.json()["onlineRev"] == "r2"
        assert v_r1.json()["sysPromptText"] == draft_text

        v_r2 = client.get("/api/v1/settings/system-prompt?version=r2", headers=h).json()
        assert v_r2["version"] == "r2" and v_r2["versionText"] == r2_text

        v_online = client.get("/api/v1/settings/system-prompt?version=online", headers=h).json()
        assert v_online["version"] == "online" and v_online["versionText"] == r2_text

        v_draft = client.get("/api/v1/settings/system-prompt?version=draft", headers=h).json()
        assert v_draft["version"] == "draft" and v_draft["versionText"] == draft_text

        # 非法版本号 400，不存在的版本号 404
        assert client.get("/api/v1/settings/system-prompt?version=../evil", headers=h).status_code == 400
        assert client.get("/api/v1/settings/system-prompt?version=bad_rev", headers=h).status_code == 400
        assert client.get("/api/v1/settings/system-prompt?version=r999", headers=h).status_code == 404

        # 3. 回退系统提示词：draft_only 恢复草稿；publish_now 必填原因并立即发布为 r3
        rb_draft = client.post(
            "/api/v1/settings/system-prompt/rollback",
            headers=h,
            json={"targetRev": "r1", "mode": "draft_only"},
        )
        assert rb_draft.status_code == 200
        assert rb_draft.json()["sysPromptText"] == r1_text
        assert rb_draft.json()["onlineRev"] == "r2"
        assert rb_draft.json()["sysPromptStatus"] == "PUBLISHED_DRAFT"

        assert client.post(
            "/api/v1/settings/system-prompt/rollback",
            headers=h,
            json={"targetRev": "r1", "mode": "publish_now", "reason": "   "},
        ).status_code == 400

        rb_live = client.post(
            "/api/v1/settings/system-prompt/rollback",
            headers=h,
            json={"targetRev": "r1", "mode": "publish_now", "reason": "v2 规则误伤回退"},
        )
        assert rb_live.status_code == 200, rb_live.text
        rb_json = rb_live.json()
        assert rb_json["rev"] == "r3"
        assert rb_json["onlineRev"] == "r3"
        assert rb_json["onlineText"] == r1_text
        assert rb_json["sysPromptText"] == r1_text
        assert rb_json["sysPromptStatus"] == "PUBLISHED"
        assert rb_json["draft"] is None

        # 4. 新建接口默认 records.path 应为 operation_out.content
        r_api = client.post(
            "/api/v1/apis",
            headers=h,
            json={"name": "queryUserProfile", "title": "客户画像查询", "connector": "unified-gateway-json"},
        )
        assert r_api.status_code == 200
        api_yaml = client.get("/api/v1/apis/queryUserProfile", headers=h).json()["yamlText"]
        parsed = yaml.safe_load(api_yaml)
        assert parsed["response"]["records"]["path"] == "operation_out.content"


def test_api_key_settings_hot_reload_masking_rollback_and_legacy_fallback(
    container,
    case_c01: dict[str, Any],
    tmp_path: Path,
):
    """验证 /api/v1/settings/api-key* 鉴权、重新生成/修改/清空对 reports 与 chat 免重启热生效、历史脱敏及旧配置兼容。"""
    report_body = {
        "templateId": 1001,
        "params": case_c01["inputs"],
        "document": case_c01["documentText"],
    }
    chat_body = {
        "userId": "u_hot_key",
        "orderId": "ORD_HOT_KEY_01",
        "inputs": {"手机号码": case_c01["inputs"]["手机号码"]},
        "document": "测试单据",
    }

    with _make_client(container) as client:
        # 1. 未登录访问 /api/v1/settings/api-key* 全部返回 401
        assert client.get("/api/v1/settings/api-key").status_code == 401
        assert client.put("/api/v1/settings/api-key", json={"apiKeys": "k1"}).status_code == 401
        assert client.post("/api/v1/settings/api-key/regenerate").status_code == 401

        h = _login(client)

        # 2. 初始状态读取 GET /api/v1/settings/api-key（来自 conftest 的 upstream-key）
        r_init = client.get("/api/v1/settings/api-key", headers=h)
        assert r_init.status_code == 200, r_init.text
        init_info = r_init.json()
        assert init_info == {
            "configured": True,
            "apiKeys": "upstream-key",
            "primaryKey": "upstream-key",
            "masked": "ups***-key",
            "count": 1,
            "activeRev": "c1",
        }
        assert client.post("/api/v1/reports", json=report_body, headers={"X-API-Key": "upstream-key"}).status_code == 200
        assert client.post("/api/v1/chat/sessions", json=chat_body, headers={"X-API-Key": "upstream-key"}).status_code == 200

        # 3. POST /api/v1/settings/api-key/regenerate：生成新密钥，旧 Key 立即 401，新 Key 立即 200
        r_regen = client.post("/api/v1/settings/api-key/regenerate", headers=h, json={"note": "定期轮换密钥"})
        assert r_regen.status_code == 200, r_regen.text
        regen_data = r_regen.json()
        new_key = regen_data["primaryKey"]
        assert new_key.startswith("ra_") and len(new_key) > 20
        assert regen_data["configured"] is True
        assert regen_data["apiKeys"] == new_key
        assert regen_data["count"] == 1
        assert regen_data["activeRev"] == "c2"
        assert regen_data["runtimeState"]["activeRev"] == "c2"
        assert regen_data["runtimeState"]["config"]["hasReportApiKeys"] is True
        assert regen_data["runtimeState"]["config"]["reportApiKeyCount"] == 1
        assert "reportApiKeys" not in regen_data["runtimeState"]["config"]

        # 旧 Key 立即失效（401），新 Key 立即生效（200）
        assert client.post("/api/v1/reports", json=report_body, headers={"X-API-Key": "upstream-key"}).status_code == 401
        assert client.post("/api/v1/chat/sessions", json=chat_body, headers={"X-API-Key": "upstream-key"}).status_code == 401
        assert client.post("/api/v1/reports", json=report_body, headers={"X-API-Key": new_key}).status_code == 200
        assert client.post(
            "/api/v1/chat/sessions",
            json={**chat_body, "orderId": "ORD_HOT_KEY_02"},
            headers={"X-API-Key": new_key},
        ).status_code == 200

        # 4. 非法字符（含空白或控制字符）返回 400 INVALID_RUNTIME_CONFIG 且不破坏现有密钥
        for bad_raw in ("bad key with space", "key1\nkey2", "key1\x00bad"):
            r_bad = client.put("/api/v1/settings/api-key", headers=h, json={"apiKeys": bad_raw})
            assert r_bad.status_code == 400 and r_bad.json()["code"] == "INVALID_RUNTIME_CONFIG"
        assert container.runtime_config.active_rev() == "c2"

        # 5. PUT /api/v1/settings/api-key 手动配置多把逗号分隔密钥
        r_multi = client.put(
            "/api/v1/settings/api-key",
            headers=h,
            json={"apiKeys": "  key_alpha_12345 , key_beta_67890  ", "note": "配置双密钥灰度"},
        )
        assert r_multi.status_code == 200, r_multi.text
        multi_data = r_multi.json()
        assert multi_data["configured"] is True
        assert multi_data["apiKeys"] == "key_alpha_12345,key_beta_67890"
        assert multi_data["primaryKey"] == "key_alpha_12345"
        assert multi_data["masked"] == "key***2345, key***7890"
        assert multi_data["count"] == 2
        assert multi_data["activeRev"] == "c3"

        assert client.post("/api/v1/reports", json=report_body, headers={"X-API-Key": new_key}).status_code == 401
        assert client.post("/api/v1/reports", json=report_body, headers={"X-API-Key": "key_alpha_12345"}).status_code == 200
        assert client.post(
            "/api/v1/chat/sessions",
            json={**chat_body, "orderId": "ORD_HOT_KEY_03"},
            headers={"X-API-Key": "key_beta_67890"},
        ).status_code == 200

        # 6. PUT /api/v1/settings/api-key 清空密钥 -> 立即进入免鉴权放行模式
        r_clear = client.put("/api/v1/settings/api-key", headers=h, json={"apiKeys": " ,  ", "note": "清空免鉴权"})
        assert r_clear.status_code == 200, r_clear.text
        clear_data = r_clear.json()
        assert clear_data["configured"] is False
        assert clear_data["apiKeys"] == ""
        assert clear_data["primaryKey"] == ""
        assert clear_data["masked"] == ""
        assert clear_data["count"] == 0
        assert clear_data["activeRev"] == "c4"

        assert client.post("/api/v1/reports", json=report_body).status_code == 200
        assert client.post("/api/v1/chat/sessions", json={**chat_body, "orderId": "ORD_HOT_KEY_04"}).status_code == 200

        # 7. 验证 /settings/runtime 与 /settings/runtime/revisions 绝不泄露任何明文 API Key
        rt_text = client.get("/api/v1/settings/runtime", headers=h).text
        revs = client.get("/api/v1/settings/runtime/revisions", headers=h).json()
        revs_text = json.dumps(revs, ensure_ascii=False)
        for secret_plain in ("upstream-key", new_key, "key_alpha_12345", "key_beta_67890"):
            assert secret_plain not in rt_text
            assert secret_plain not in revs_text
        c3_rev = next(x for x in revs if x["rev"] == "c3")
        assert c3_rev["changedKeys"] == ["reportApiKeys"]
        assert c3_rev["config"]["reportApiKeysMasked"] == "key***2345, key***7890"
        assert c3_rev["config"]["reportApiKeyCount"] == 2
        assert "reportApiKeys" not in c3_rev["config"]

        # 8. 回退至 c1 后，立即恢复为仅 upstream-key 有效（免鉴权立即关闭）
        r_rb = client.post(
            "/api/v1/settings/runtime/rollback",
            headers=h,
            json={"targetRev": "c1", "reason": "恢复初始调用密钥"},
        )
        assert r_rb.status_code == 200, r_rb.text
        assert client.post("/api/v1/reports", json=report_body).status_code == 401
        assert client.post("/api/v1/reports", json=report_body, headers={"X-API-Key": "upstream-key"}).status_code == 200

    # 9. 兼容旧版 current.json（缺失 reportApiKeys 键）自动回退到 fallback_settings 并归一化保存
    legacy_dir = tmp_path / "legacy_data"
    legacy_settings = Settings(
        _env_file=None,
        data_dir=legacy_dir,
        gateway_mode="mock",
        llm_api_key="test",
        admin_token_secret="test-secret",
        report_api_keys="  legacy-env-key-001 , legacy-env-key-002  ",
    )
    c_legacy = build_container(legacy_settings, model=scripted_model())
    cur_file = c_legacy.layout.config / "runtime" / "current.json"
    cur_doc = json.loads(cur_file.read_text(encoding="utf-8"))
    cur_doc["config"].pop("reportApiKeys", None)
    cur_file.write_text(json.dumps(cur_doc, ensure_ascii=False), encoding="utf-8")

    c_reloaded = build_container(legacy_settings, model=scripted_model())
    assert c_reloaded.runtime_config.active().config.reportApiKeys == "legacy-env-key-001,legacy-env-key-002"
    assert c_reloaded.settings.report_api_key_set() == {"legacy-env-key-001", "legacy-env-key-002"}
    upgraded_doc = json.loads(cur_file.read_text(encoding="utf-8"))
    assert upgraded_doc["config"]["reportApiKeys"] == "legacy-env-key-001,legacy-env-key-002"
