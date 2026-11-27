"""迁移后模板的端到端冒烟：真实大模型 + 本地 Mock 网关，在全新隔离的临时数据目录上试跑指定模板。

#Created By AiCoding(codex)
安全边界：
  - 绝不全量拷贝本地 DATA_DIR（避免把 config/runtime/current.json 中持久化的 live 网关配置或历史 runs/chats 带入冒烟环境）；
  - 使用全新临时目录按当前最新 SEED_DIR 自动初始化发布，并显式注入 MockGatewayClient，100% 保证冒烟只走本地 Mock 网关；
  - 若环境变量未显式提供 LLM 参数且本地运行配置存在，仅按需提取 llmApiKey / llmBaseUrl / llmModel 三项模型连接参数。
用法：uv run python tools/java_migration/smoke_run.py [模板ID]（默认 101，单据与入参取 tests/fixtures 的 C-01 用例）
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from pydantic import SecretStr
import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from report_agent.config import Settings  # noqa: E402
from report_agent.container import SEED_DIR, build_container  # noqa: E402
from report_agent.gateway.mock import MockGatewayClient  # noqa: E402
from report_agent.runtime.runner import RunRequest  # noqa: E402


def _extract_local_llm_overrides(base: Settings) -> dict[str, Any]:
    """仅按需从本地 current.json 提取未由环境变量指定的模型连接参数，绝不读取任何网关配置。"""
    rt_file = base.data_dir / "config" / "runtime" / "current.json"
    if not rt_file.is_file():
        return {}
    try:
        payload = json.loads(rt_file.read_text(encoding="utf-8"))
        cfg = payload.get("config") if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(cfg, dict):
        return {}

    updates: dict[str, Any] = {}
    if not os.environ.get("LLM_API_KEY") and not base.llm_api_key.get_secret_value() and cfg.get("llmApiKey"):
        updates["llm_api_key"] = SecretStr(str(cfg["llmApiKey"]))
    if not os.environ.get("LLM_BASE_URL") and cfg.get("llmBaseUrl"):
        updates["llm_base_url"] = str(cfg["llmBaseUrl"])
    if not os.environ.get("LLM_MODEL") and cfg.get("llmModel"):
        updates["llm_model"] = str(cfg["llmModel"])
    return updates


async def main() -> None:
    tid = int(sys.argv[1]) if len(sys.argv) > 1 else 101
    case = yaml.safe_load((ROOT / "tests/fixtures/seed/cases/1001/C-01.yaml").read_text(encoding="utf-8"))
    base = Settings()
    llm_overrides = _extract_local_llm_overrides(base)
    tmp = Path(tempfile.mkdtemp(prefix="smoke_"))
    c = None
    try:
        tmp_data = tmp / "data"
        settings = base.model_copy(
            update={
                **llm_overrides,
                "data_dir": tmp_data,
                "gateway_mode": "mock",
                "seed_on_empty": True,
            }
        )
        mock_gw = MockGatewayClient(
            tmp_data / "mock-gateway",
            settings.gateway_xml_style,
            fallback_root=SEED_DIR / "mock-gateway",
        )
        c = build_container(settings, gateway=mock_gw)
        assert c.settings.gateway_mode == "mock" and c.external_gateway is True
        out = await c.runner.run(RunRequest(tid, case["inputs"], case["documentText"], entry="试运行"))
        print(
            json.dumps(
                {
                    k: out[k]
                    for k in (
                        "status",
                        "error",
                        "foundCount",
                        "totalCount",
                        "durationMs",
                        "rounds",
                        "skillsLoaded",
                        "usage",
                    )
                },
                ensure_ascii=False,
            )
        )
        for f in out["fields"]:
            print(
                f"  {'✓' if f['status'] == 'found' else '·'} {f['name']} = {str(f['renderedValue'])[:70]!r}"
                f"{'  [校验退回过]' if f['retried'] else ''}"
            )
        print("----- 报告 -----")
        print(out["report"])
    finally:
        if c is not None:
            await c.gateway.aclose()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
