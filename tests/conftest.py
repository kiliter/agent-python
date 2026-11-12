"""测试公共夹具：每个测试使用独立的临时数据目录和脚本化假模型。

#Created By AiCoding(codex)
"""

from __future__ import annotations

import sys
from pathlib import Path

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
