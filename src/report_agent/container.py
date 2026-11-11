"""组装全部组件（进程内单例），并负责启动初始化与崩溃恢复。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .domain.resources import load_resource_dir
from .gateway.base import GatewayClient
from .gateway.mock import MockGatewayClient
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
from .store.service import ResourceService

log = logging.getLogger(__name__)

SEED_DIR = Path(__file__).parent / "seed"


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
    gateway = gateway or build_gateway(settings, layout)
    runner = AgentRunner(settings, model or build_model(settings), build_model_settings(settings), gateway,
                         service, releases, runs)
    return Container(settings, layout, lock, repo, releases, drafts, publisher, service, cases, runs, gateway, runner)


def seed(layout: DataLayout, publisher: Publisher, cases: CaseStore, seed_dir: Path = SEED_DIR) -> None:
    """数据目录为空时，用内置示例资源生成第一个版本，并放入示例用例和 mock 网关响应。"""
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
