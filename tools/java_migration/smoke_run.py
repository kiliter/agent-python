"""迁移后模板的端到端冒烟：真实大模型 + mock 网关，在临时数据目录副本上跑一次模板。

#Created By AiCoding(codex)
用法：uv run python tools/java_migration/smoke_run.py [模板ID]（默认 101，单据与入参取 tests/fixtures 的 C-01 用例）
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from report_agent.config import Settings  # noqa: E402
from report_agent.container import build_container  # noqa: E402
from report_agent.runtime.runner import RunRequest  # noqa: E402


async def main() -> None:
    tid = int(sys.argv[1]) if len(sys.argv) > 1 else 101
    case = yaml.safe_load((ROOT / "tests/fixtures/seed/cases/1001/C-01.yaml").read_text(encoding="utf-8"))
    base = Settings()
    tmp = Path(tempfile.mkdtemp(prefix="smoke_"))
    shutil.copytree(base.data_dir, tmp / "data", symlinks=True)  # 保留 releases/current 软链接
    settings = base.model_copy(update={"data_dir": tmp / "data", "gateway_mode": "mock"})
    c = build_container(settings)
    out = await c.runner.run(RunRequest(tid, case["inputs"], case["documentText"], entry="试运行"))
    print(json.dumps({k: out[k] for k in ("status", "error", "foundCount", "totalCount", "durationMs", "rounds",
                                          "skillsLoaded", "usage")}, ensure_ascii=False))
    for f in out["fields"]:
        print(f"  {'✓' if f['status'] == 'found' else '·'} {f['name']} = {str(f['renderedValue'])[:70]!r}"
              f"{'  [校验退回过]' if f['retried'] else ''}")
    print("----- 报告 -----")
    print(out["report"])
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
