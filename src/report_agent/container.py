"""组装全部组件（进程内单例），并负责启动初始化与崩溃恢复。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from pydantic import SecretStr

from .config import Settings
from .domain.resources import load_resource_dir
from .gateway.base import GatewayClient
from .gateway.mock import MockGatewayClient
from .gateway.reloadable import ReloadableGatewayClient
from .gateway.unified_xml import UnifiedGatewayXmlClient
from .runtime.model_factory import build_model, build_model_settings
from .runtime.runner import AgentRunner
from .store.cases import CaseStore
from .store.drafts import DraftStore
from .store.git_repo import GitRepo
from .store.layout import DataLayout, ResourceRef, SYSTEM_PROMPT_KEY
from .store.publisher import Change, Publisher
from .store.releases import ReleaseStore
from .store.runs import RunStore
from .store.runtime_config import RuntimeConfig, RuntimeConfigStore
from .store.service import ResourceService

log = logging.getLogger(__name__)

SEED_DIR = Path(__file__).parent / "seed"


def _gateway_signature(s: Settings) -> tuple:
    return (
        s.gateway_mode,
        s.gateway_url,
        s.gateway_app_id.get_secret_value(),
        s.gateway_access_token.get_secret_value(),
        s.gateway_xml_style,
        s.gateway_connect_timeout_s,
    )


@dataclass
class Container:
    settings: Settings
    layout: DataLayout
    lock: threading.RLock
    repo: GitRepo
    releases: ReleaseStore
    drafts: DraftStore
    publisher: Publisher
    service: ResourceService
    cases: CaseStore
    runs: RunStore
    gateway: GatewayClient
    runner: AgentRunner
    runtime_config: RuntimeConfigStore | None = None
    env_settings: Settings | None = None
    external_model: bool = False
    external_gateway: bool = False

    def apply_runtime_config(self) -> Settings:
        """将 runtime_config 当前生效快照热更新至内存中的网关、模型与运行器，无需重启进程。"""
        with self.lock:
            if self.runtime_config is None:
                return self.settings
            base = self.env_settings or self.settings
            prev_settings = self.settings
            effective = self.runtime_config.to_effective_settings(base)
            gw_changed = _gateway_signature(effective) != _gateway_signature(prev_settings)
            if not self.external_gateway or gw_changed:
                new_gw = build_gateway(effective, self.layout)
                self.external_gateway = False
                if isinstance(self.gateway, ReloadableGatewayClient):
                    self.gateway.swap(new_gw)
                else:
                    self.gateway = ReloadableGatewayClient(new_gw)
                    self.runner.gateway = self.gateway
            self.settings = effective
            self.runner.reload_config(effective, rebuild_model=not self.external_model)
            return effective


def build_gateway(settings: Settings, layout: DataLayout) -> GatewayClient:
    """按配置创建网关客户端。"""
    if settings.gateway_mode == "live":
        return UnifiedGatewayXmlClient(
            settings.gateway_url, settings.gateway_app_id.get_secret_value(),
            settings.gateway_access_token.get_secret_value(), settings.gateway_xml_style,
            settings.gateway_connect_timeout_s,
        )
    return MockGatewayClient(layout.mock_gateway, settings.gateway_xml_style)


def build_container(settings: Settings, model=None, gateway: GatewayClient | None = None) -> Container:
    """创建组件并完成数据目录初始化。model / gateway 可注入（测试用）。"""
    env_settings = settings
    layout = DataLayout(settings.data_dir)
    layout.ensure()
    lock = threading.RLock()
    repo = GitRepo(layout.repo)
    repo.ensure_init()
    releases = ReleaseStore(layout, repo, lock, keep=settings.releases_keep)
    drafts = DraftStore(layout, lock)
    publisher = Publisher(layout, repo, releases, drafts, lock)
    service = ResourceService(layout, releases, drafts, publisher, lock)
    cases = CaseStore(layout, lock)
    runs = RunStore(layout)
    releases.recover()
    if not releases.entries() and settings.seed_on_empty:
        seed(layout, publisher, cases)

    runtime_config = RuntimeConfigStore(layout, lock)
    had_persisted = runtime_config.exists()
    if had_persisted:
        runtime_config.bootstrap_or_load(env_settings)
        effective_settings = runtime_config.to_effective_settings(env_settings)
    else:
        effective_settings = RuntimeConfig.from_settings(env_settings).to_effective_settings(env_settings)

    external_gateway = gateway is not None
    external_model = model is not None
    raw_gw = gateway if external_gateway else build_gateway(effective_settings, layout)
    reloadable_gw = raw_gw if isinstance(raw_gw, ReloadableGatewayClient) else ReloadableGatewayClient(raw_gw)
    model_input = (
        effective_settings
        if effective_settings.llm_api_key.get_secret_value()
        else effective_settings.model_copy(update={"llm_api_key": SecretStr("EMPTY")})
    )
    actual_model = model if external_model else build_model(model_input)

    if not had_persisted:
        runtime_config.bootstrap_or_load(env_settings)
        effective_settings = runtime_config.to_effective_settings(env_settings)

    runner = AgentRunner(effective_settings, actual_model, build_model_settings(effective_settings), reloadable_gw,
                         service, releases, runs)
    return Container(
        effective_settings,
        layout,
        lock,
        repo,
        releases,
        drafts,
        publisher,
        service,
        cases,
        runs,
        reloadable_gw,
        runner,
        runtime_config=runtime_config,
        env_settings=env_settings,
        external_model=external_model,
        external_gateway=external_gateway,
    )


def seed(layout: DataLayout, publisher: Publisher, cases: CaseStore, seed_dir: Path | None = None) -> None:
    """数据目录为空时，用内置示例资源生成第一个版本，并放入示例用例和 mock 网关响应。

    seed_dir 为空时在调用时刻读取模块级 SEED_DIR（而不是定义时绑定），便于测试替换为测试夹具目录。
    #Created By AiCoding(codex)
    """
    seed_dir = seed_dir or SEED_DIR
    rs = load_resource_dir(seed_dir)
    changes: list[Change] = [Change(ResourceRef("system-prompt", SYSTEM_PROMPT_KEY), "publish", "系统提示词",
                                    source="tree", source_dir=seed_dir)]
    changes += [Change(ResourceRef("api", a.name), "publish", a.title, source="tree", source_dir=seed_dir)
                for a in rs.apis.values()]
    changes += [Change(ResourceRef("skill", s.id), "publish", s.title, source="tree", source_dir=seed_dir)
                for s in rs.skills.values()]
    changes += [Change(ResourceRef("template", str(t.id)), "publish", t.name, source="tree", source_dir=seed_dir)
                for t in rs.templates.values()]
    publisher.publish(changes, "system", "初始化", "初始化内置示例资源")
    mock_src = seed_dir / "mock-gateway"
    if mock_src.exists() and not any(layout.mock_gateway.iterdir()):
        for f in mock_src.iterdir():
            shutil.copy2(f, layout.mock_gateway / f.name)
    cases_src = seed_dir / "cases"
    if cases_src.exists() and not any(layout.cases.iterdir()):
        shutil.copytree(cases_src, layout.cases, dirs_exist_ok=True)
    log.info("已用内置示例资源初始化数据目录 %s", layout.root)
