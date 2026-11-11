"""智能体运行依赖（Pydantic AI 的 deps）。

#Created By AiCoding(codex)
请求开始时捕获一次资源快照，整个运行期间只读这一份，保证所有轮次看到的模板、Skill、接口一致。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..domain.resources import ResourceSet
from ..domain.template import Template
from ..gateway.base import GatewayClient
from .workspace import EventSink, Workspace


@dataclass
class RunDeps:
    run_id: str
    rev: str
    resources: ResourceSet
    template: Template
    inputs: dict[str, str]
    document: str
    allowed_skills: list[str]
    allowed_apis: list[str]
    workspace: Workspace
    events: EventSink
    gateway: GatewayClient
    settings: Settings
