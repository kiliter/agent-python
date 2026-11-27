"""测试公共夹具：每个测试使用独立的临时数据目录和脚本化假模型。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent))

import report_agent.container as container_module  # noqa: E402
from report_agent.config import Settings  # noqa: E402
from report_agent.container import build_container  # noqa: E402
from fixture_paths import SEED_DIR  # noqa: E402
from scripted_model import scripted_model  # noqa: E402


@pytest.fixture(autouse=True)
def _use_fixture_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有测试的空库初始化都使用 tests/fixtures/seed，不读取生产内置资源 src/report_agent/seed。

    #Created By AiCoding(codex)
    """
    monkeypatch.setattr(container_module, "SEED_DIR", SEED_DIR)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data", gateway_mode="mock", llm_api_key="test",
                    admin_token_secret="test-secret", report_api_keys="upstream-key")


@pytest.fixture
def container(settings: Settings):
    return build_container(settings, model=scripted_model())


@pytest.fixture
def case_c01() -> dict:
    return yaml.safe_load((SEED_DIR / "cases/1001/C-01.yaml").read_text(encoding="utf-8"))


def parse_sse(raw_text: str) -> list[dict[str, Any]]:
    """解析标准 SSE 响应帧序列，忽略空块与注释心跳行。#Created By AiCoding(codex)"""
    events: list[dict[str, Any]] = []
    for block in raw_text.replace("\r\n", "\n").split("\n\n"):
        lines = [ln for ln in block.splitlines() if ln.strip() and not ln.startswith(":")]
        if not lines:
            continue
        evt_name = "message"
        event_id: str | None = None
        data_lines: list[str] = []
        for ln in lines:
            if ln.startswith("event:"):
                evt_name = ln[6:].strip()
            elif ln.startswith("id:"):
                event_id = ln[3:].strip()
            elif ln.startswith("data:"):
                data_lines.append(ln[5:].lstrip())
        if data_lines:
            frame: dict[str, Any] = {"event": evt_name, "data": json.loads("\n".join(data_lines))}
            if event_id is not None:
                frame["id"] = event_id
            events.append(frame)
    return events
