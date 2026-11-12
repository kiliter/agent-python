"""测试专用资源路径。

#Created By AiCoding(codex)
测试不再读取生产内置资源 src/report_agent/seed（迁移后会被替换），
统一使用 tests/fixtures/seed 下的 PoC 资源（模板 1001、两个 Skill、短信接口、示例用例与 mock 响应）。
"""

from __future__ import annotations

from pathlib import Path

# 测试夹具资源根目录（结构与生产 seed 目录一致）
SEED_DIR = Path(__file__).parent / "fixtures" / "seed"
