---
title: 本地开发、测试与部署指南
type: guide
tags: [guide, dev, pytest, frontend, docker, deployment]
sources:
  - pyproject.toml
  - Dockerfile
  - .env.example
  - src/report_agent/cli.py
  - tests/conftest.py
  - docs/frontend-api-handoff.md
updated: 2026-11-12
---

# 本地开发、测试与部署指南

<!-- #Created By AiCoding(codex) -->

本页汇总 `agent-python` 的本地环境初始化、前后端分离联调、单体静态托管、`pytest` 测试隔离机制以及容器化单进程部署规范。

## 1. 本地快速启动

### 1.1 后端初始化与运行

环境要求：Python `3.12` 或 `3.13`（推荐 `3.13`）、`uv`、本地已安装 `git` 命令（资源发布仓库依赖 `git` CLI）。

```bash
# 1. 安装全部依赖（含 pytest / ruff）
uv sync --extra dev

# 2. 复制并按需编辑环境变量（切勿把真实 API Key 提交到 Git！）
cp .env.example .env

# 3. 初始化数据目录并创建管理员账号
uv run report-agent init
uv run report-agent user add --username admin --password '<YOUR_PASSWORD>' --display-name 系统管理员 --role 平台管理

# 4. 启动后端服务（默认监听 http://0.0.0.0:8000）
uv run report-agent serve
# 开发态若需源码变更自动重载，可使用单进程 factory 模式启动：
uv run uvicorn report_agent.main:create_app --factory --reload
```

> 快捷方式：也可在 `.env` 中配置 `ADMIN_BOOTSTRAP_PASSWORD`（首次启动若 `users.yaml` 不存在会自动创建 `admin` 账号）。

### 1.2 前端工作台联调与构建

环境要求：Node.js `20+`、`npm`。

```bash
cd frontend
npm ci

# 开发模式联调（Vite 将 /api 代理至 http://127.0.0.1:8000）
VITE_USE_MOCK=false npm run dev

# 类型检查与生产打包（产出至 frontend/dist）
npx vue-tsc --noEmit -p tsconfig.app.json
npm run build
```

若希望由 FastAPI 单端口同时托管前端页面与 `/api/v1` 接口，在构建完 `frontend/dist` 后设置环境变量 `FRONTEND_DIST=frontend/dist` 启动 `report-agent serve`，直接访问 `http://127.0.0.1:8000` 即可。

## 2. 自动化测试与 `SEED_DIR` 隔离机制

```bash
# 运行全部单元与集成测试
uv run pytest

# Python 代码风格与静态检查
uvx ruff@0.11.0 check src tests
```

### 重要机制：`tests/conftest.py` 的种子资源隔离

阅读或编写测试时务必理解两套种子目录的分工：
1. **默认测试夹具（`tests/fixtures/seed/`）**：`tests/conftest.py` 定义了 `autouse=True` 的 `_use_fixture_seed` fixture，自动将 `report_agent.container.SEED_DIR` 猴子补丁指向 `tests/fixtures/seed`（仅含精简测试模板 `1001`、`querySMSSendInfo` 与 `business-sms`）。这样当我们增删或调整 33 个生产模板时，平台内核的几十个存储/路由/权限单测依然极速且稳定，互不耦合。
2. **生产迁移种子回归（`tests/test_migrated_seed.py`）**：该测试文件显式读取真实的 `src/report_agent/seed/`，对全部 33 个生产模板、11 个 Skill、3 个网关契约做全量 `validate_all()` 零错误零告警断言与核心渲染回归。
3. **确定性桩模型（`tests/scripted_model.py`）**：单测中无需联网调用真实大模型，通过自定义的 `ScriptedModel` 按剧本返回预设 Tool Call 序列与 `submit_report` 输出，即可完整测试 `AgentRunner`、工具链、证据打回重试与部分挽救逻辑。

## 3. 容器化构建与生产部署规范

仓库根目录的 `Dockerfile` 采用多阶段或预构建托管方案（基于 `python:3.13-slim`，内置 `git` 与 `uv:0.7`，监听 `8000` 端口，挂载 `/data` 持久化卷）。

### 生产部署三大必守红线

1. **必须保持单进程运行（`workers=1`）**：
   - `cli.py` 中 `uvicorn.run(..., workers=1)` 为有意设计。草稿乐观锁、Git 仓库发布锁（`threading.Lock`）、`RunStore` 异步顺序写队列、`AuthService` 登录失败锁定计数与 `ReloadableGatewayClient` 热更新槽位均为进程内同步状态，严禁使用 `--workers > 1` 或 Gunicorn 多 Worker 启动同一 `DATA_DIR`。
2. **挂载持久化本地 POSIX 文件系统到 `DATA_DIR`**：
   - `DATA_DIR`（容器内默认 `/data`）必须挂载支持符号链接（Symlink）与原子 `rename`（`os.replace`）的持久化卷，否则重启会丢失已发布版本、草稿、运行审计与在线热更新配置。
3. **生产安全配置检查**：
   - 必须设置高强度 `REPORT_API_KEYS` 保护上游 `/api/v1/reports` 接口；
   - 若通过 HTTPS 反向代理对外暴露工作台，设置 `ADMIN_COOKIE_SECURE=true` 使 `ra_session` Cookie 启用 `Secure` 标志；
   - 生产环境将 `GATEWAY_MODE=live` 并配置真实网关地址与令牌，切勿保留 `GATEWAY_MODE=mock`（除非做演练压测）。

## 相关页面

- [环境变量与运行期配置参考](../reference/configuration.md)
- [文件化资源存储与 Git 原子发布机制](../architecture/resource-release-and-store.md)
- [Java 资源迁移与一致性对拍指南](java-migration-and-verification.md)
- [常见故障排查手册](troubleshooting.md)
