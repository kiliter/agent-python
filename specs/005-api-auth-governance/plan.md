# 设计文档（Feature Design Spec）：REST/SSE 服务网关、三轨安全鉴权体系与全生命周期治理接口

<!-- #Created By AiCoding(codex) -->
<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->

> **Spec Kit 使用约定**：本文件采用**单文件内联布局（inline-v1）**，研究决策、领域与存储模型、内部接口契约及验证指南全部内联维护在本文件四个锚点章节中，不另建 `research.md`、`data-model.md`、`contracts/` 或 `quickstart.md`。本归档拆分仅生成标准 SDD 三件套，三类外部独立交付物均在 `1.8` 节记录不涉及依据；全文严格对照源码、测试与 `wiki/components/api-and-auth.md` 撰写。

---

**分支**：`[005-api-auth-governance]` | **日期**：2026-11-16 | **规格**：`./spec.md`

**输入**：`/specs/005-api-auth-governance/spec.md`

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-005` |
| 需求名称 | REST/SSE 服务网关、三轨安全鉴权体系与全生命周期治理接口 |
| 对应需求文档 | `./spec.md` |
| 对应任务清单 | `./tasks.md` |
| 设计文档版本 | `2.0` |
| 设计人 | AiCoding |
| 核算工作量 | `33.0 人天`（7 个实施切片合计 `33.0 人天`） |
| 状态 | 已交付归档 |

---

## 1. 设计目标与范围 【核心】

### 1.1 设计目标（What / Why）

- **PLAN-GOAL-1**：通过 `create_app` 与 `Container` 构建零数据库依赖、单进程可热重载的 FastAPI REST/SSE 网关，统一承载应用生命周期装配、幂等滚动日志、子路径反代前缀剥离（`_SubpathPrefixMiddleware`）与 SPA 前端构建产物安全托管（对应 `SC-005`）。
- **PLAN-GOAL-2**：建立覆盖管理端会话认证（600k PBKDF2 + 双轨防爆破 `LoginGuard` + 可吊销 `TokenService`）、上游报表调用（可即时热轮换 `X-API-Key`）与外部聊天协同边界的安全防线，实现抗算力放大、防计时侧信道与操作人不可伪造审计（对应 `SC-001`、`SC-003`）。
- **PLAN-GOAL-3**：为模板、技能、双协议网关接口与系统提示词提供全粒度 `expected_revision` 乐观锁治理、内存态沙箱预览、未落盘 `test-call` 拨测、`emergency-switch` 毫秒回退、`detail_view` 破损容错及全部 `48` 项 `_ORDERED_FIELDS` 配置免重启热更新接口（对应 `SC-002`、`SC-004`、`SC-005`）。

### 1.2 设计范围（Scope）

**包含：**

- 应用工厂与装配上下文：`src/report_agent/main.py`、`src/report_agent/container.py`、`src/report_agent/config.py`。
- 48 项热更新配置存储引擎：`src/report_agent/store/runtime_config.py`。
- FastAPI 鉴权、公共原语、DTO、双态视图与三大核心路由模块：`src/report_agent/api/{__init__,auth,common,dto,run_views,routes_templates,routes_resources,routes_system}.py`（实际文件逐一列出如下）。
- 前后端接口契约基准文档 `docs/frontend-api-handoff.md` 及四大接口与审计回归测试集。

**不包含：**

- 领域模型校验器与 Jinja2 沙箱渲染内部实现（归属 `RA-001`）、Git 底层存储与运行日志单写队列（归属 `RA-002`）、`AgentRunner` 与证据核验引擎（归属 `RA-003`）、12 平台工具与底层 XML/JSON 客户端（归属 `RA-004`）。
- Vue 3 管理端工作台界面实现（归属 `RA-006`）、嵌入式聊天子路由 `routes_chat.py` 与 `ChatService`（归属 `RA-007`）、Java 迁移工具与 Docker 构建（归属 `RA-008`）。

<a id="plan-research"></a>

### 1.3 研究与关键决策（Decision Log）

| ID | 决策点 | 备选方案 | 最终选择 | 依据与取舍理由 | 影响范围 |
| --- | --- | --- | --- | --- | --- |
| `D1` | 密码校验抗算力放大与计时侧信道防护 | 直接协程同步哈希 / 无限制线程池校验 | 600,000 次 PBKDF2-HMAC-SHA256 + `asyncio.to_thread` + 按事件循环 `WeakKeyDictionary` 隔离 `_login_semaphore()`（`4` 并发） + `DUMMY_PASSWORD_HASH` 恒定假校验 | 避免 CPU 密集哈希阻塞事件循环心跳并防止高并发登录 DoS；消除用户名是否存在计时侧信道；限制 `MAX_PASSWORD_LEN=1024` | `api/auth.py`、`api/routes_system.py` |
| `D2` | 防爆破撞库分桶与来源 IP 取值 | 单一固定容量 LRU 字典 + 采信 `X-Forwarded-For` | `LoginGuard` 分离 `_known_users` 保护桶与未知用户优先淘汰策略 + 仅取直连 `request.client.host` 计 20 次 IP 封禁 + `_bound_guard_key` SHA-256 定长摘要 | 防止随机用户名喷洒驱逐已锁定真实账号；不采信易伪造代理头；控制内存上界（4096 项） | `api/auth.py`、`api/routes_system.py` |
| `D3` | 模板并发编辑粒度与变量改名安全性 | 整包 YAML 覆盖 + 简单字符串全局替换 | 全字段/排序/技能/入参细粒度 `expected_revision` 校验 + `_rename_body_variable` 词法状态机重命名 | 最小化多人编辑冲突面；重命名仅替换 `{{ ... }}` / `{% ... %}` 合法变量引用，跳过 `{# ... #}` 注释、字符串、过滤器与 `.attr` | `api/common.py`、`api/routes_templates.py` |
| `D4` | SSE 断连任务保活与内存隔离 | 依赖客户端连接持有生成协程 | `_BG_TASKS` 强引用集合托管异步生产任务 + `15` 秒 `: keep-alive` 心跳帧 + `SSE_HEADERS` 禁缓冲 | 客户端断连或网络闪断不触发 `Task` 取消导致运行账本半残；异步队列驱动首包即时反馈 | `api/common.py`、`routes_templates.py`、`routes_system.py` |
| `D5` | 运行期 48 项配置与网关连接池免重启热生效 | 修改 `.env` 重启服务 / 每次请求重建连接 | `RuntimeConfigStore`（`0600` 版本 `cN` 快照）+ `Container.apply_runtime_config()` 比较 `_gateway_signature` + `await c.gateway.aclose_retired()` | 参数调优与 `X-API-Key` 轮换毫秒级生效，仅网关签名变化时重建 `ReloadableGatewayClient` 并优雅回收在途旧连接 | `store/runtime_config.py`、`container.py`、`routes_resources.py` |

---

### 1.4 技术背景与项目结构

**语言/版本**：Python `>=3.12,<3.14`（容器镜像基于 `python:3.13-slim` + `uv`）

**主要依赖**：FastAPI `>=0.115,<1`、Uvicorn `>=0.32,<1`、Pydantic `>=2.12,<3`、Pydantic Settings `>=2.6,<3`、PyYAML `>=6.0.2,<7`、HTTPX `>=0.28,<1`

**存储**：本地文件系统 `DATA_DIR`（`config/users.yaml`、`config/.token-secret`、`config/runtime/` 及只追加 `audit.jsonl`，通过 `Container` 协同 `repo/`、`releases/`、`drafts/`、`runs/`、`cases/`）

**测试**：`uv run pytest -q`（`TestClient` + `ScriptedModel` / `MockGatewayClient`）+ `uvx ruff@0.11.0 check src tests`

**目标平台**：Linux 容器（单进程 Uvicorn `workers=1`）及 macOS 本地开发/联调环境

**项目类型**：后端 REST/SSE 服务网关、安全鉴权中心与全生命周期资源治理 API 模块

**约束与规模/范围**：严格单进程 `workers=1`；覆盖 `48` 项 `_ORDERED_FIELDS` 运行期配置、4 个内部核心路由/鉴权/视图模块与 5 套测试套件，按 `33.0 人天` 归档核算

**源代码结构（真实目录落点）**：

```text
src/report_agent/
├── main.py                        # create_app、setup_logging、install_error_handlers、_SubpathPrefixMiddleware、_cleanup_loop、spa()
├── container.py                   # Container、_gateway_signature、build_gateway、build_container、apply_runtime_config、seed
├── config.py                      # Settings（_NON_NULLABLE_SCALAR_FIELDS、report_api_key_set、normalized_root_path）
├── store/
│   └── runtime_config.py          # _ORDERED_FIELDS（48 项）、RuntimeConfig、RuntimeSnapshot、RuntimeConfigStore（0600 与回滚）
└── api/
    ├── __init__.py                # api 子包导出边界
    ├── auth.py                    # PBKDF2 600k、DUMMY_PASSWORD_HASH、UserStore、TokenService、LoginGuard、require_user、require_report_key
    ├── common.py                  # SSE_HEADERS、_BG_TASKS、parse_expected_revision、operator、validation_result_with_drift、sse_run
    ├── dto.py                     # body_usage、ref_by_fields、field_to_dto/dto_to_field、input_to_dto、template_item/skill_item/api_item、run_record
    ├── run_views.py               # _fallback_field_def、detail_view、report_view
    ├── routes_templates.py        # 模板 CRUD、细粒度字段/排序/技能乐观锁、_rename_body_variable、render-preview、cases、dryrun/stream
    ├── routes_resources.py        # Skill 治理（_safe_overlay）、API 局部补丁与未落盘 test-call、SystemPrompt、runtime/model/api-key 热更新 API
    └── routes_system.py           # /health、/auth/*、/releases/*（diff/emergency-switch）、/runs/*、/system/overview、/reports*

docs/
└── frontend-api-handoff.md        # REST/SSE 前后端交互与错误码契约文档

tests/
├── test_api.py                    # API 全生命周期、防路径穿越、破损运行详情与系统概览集成测试
├── test_api_and_store_fixes.py    # 鉴权防爆破、信号量、Token 容量淘汰、细粒度乐观锁、list+input 拦截、render-preview 测试
├── test_api_routes_json.py        # 双协议 XML/JSON API DTO、/validate 预览、/test-call 与非 Mapping 草稿测试
├── test_deep_audit_fixes.py       # 深度审计修复、_SubpathPrefixMiddleware 反代、SPA 隔离与审计防伪造测试
└── test_runtime_config_hot_reload.py # 48 项 RuntimeConfig 校验、热生效与连接池回收测试
```

**禁止修改范围**：

- 禁止在 `src/report_agent/api/`、`main.py` 或 `container.py` 中硬编码任何模板 ID、业务字段规则或网关专用判断。
- 禁止修改 `tests/conftest.py` 对 `SEED_DIR` 的测试隔离机制，禁止在自动化单测中访问外网 LLM 或真实内网网关。
- 本需求不改动 `routes_chat.py`（归属 `RA-007`）与 `frontend/` 源码（归属 `RA-006`）。

#### 文档结构（本需求）

```text
specs/005-api-auth-governance/
├── spec.md    # specify/clarify：需求规格、范围边界与验收标准
├── plan.md    # plan：研究决策、模型、内部契约与验证指南（inline-v1）
└── tasks.md   # tasks：可执行任务清单、测试矩阵与验收证据
```

| 设计产物 | 权威位置 |
| --- | --- |
| 研究结论与技术决策 | [1.3 研究与关键决策](#plan-research) |
| 领域实体与存储设计 | [第 3–4 章](#plan-data-model) |
| 内部接口与事件契约 | [第 5 章](#plan-contracts) |
| 可执行验证指南 | [10.5 验证指南](#plan-quickstart) |

### 1.5 宪章检查

| 质量门 | 研究前 | 设计后 | 核查证据 |
| --- | --- | --- | --- |
| 原则 I：平台零业务硬编码与声明式资源隔离 | `PASS` | `PASS` | `dto.py`、`run_views.py`、`_rename_body_variable` 与各路由均仅消费泛型字段/YAML 契约，零业务编号与硬编码规则 |
| 原则 II：单智能体规划、确定性原语与强证据防幻觉 | `PASS` | `PASS` | `/reports*` 与 `/dryrun*` 统一路由至单 `AgentRunner.run`；`detail_view` / `report_view` 完整透传 `missingShown`、`retriedFields`、`validationRounds` |
| 原则 III：文件化 Git 原子发布与单进程并发安全（`workers=1`） | `PASS` | `PASS` | `expected_revision` 乐观锁、`Container.lock` 互斥、`0600` 原子写盘、`_BG_TASKS` 任务保护、`SAFE_ID_RE` 与 `is_relative_to` 防穿越校验 |
| 原则 IV–V：单文件内联设计、自动化测试隔离与 Mock 契约 | `PASS` | `PASS` | 采用 `inline-v1` 单文件布局；5 个 API/配置测试集全部基于 `TestClient` + `ScriptedModel` / `MockGatewayClient` 与测试隔离夹具 |
| 原则 VI–VII：安全脱敏、零硬编码凭证、事件与审计留痕 | `PASS` | `PASS` | 600k PBKDF2、`LoginGuard` 双轨防爆破、`hmac.compare_digest`、`requestPreview`/`runtime` 脱敏、`operator(request)` 强制写入 `audit.jsonl` |
| 原则 VIII–X：最小改动、代码规范、Wiki 同步及三类外部交付物确认 | `PASS` | `PASS` | `uvx ruff@0.11.0` 零告警；`wiki/components/api-and-auth.md` 与 `docs/frontend-api-handoff.md` 已就位；三类独立交付物明确记录不涉及 |

### 1.6 复杂度跟踪

| 偏离或额外复杂度 | 必要性说明 | 未采用更简方案的原因 |
| --- | --- | --- |
| 无（严格遵守项目宪章与既有约束） | 进程内 `_login_semaphore` + `_known_users` 分桶与 `_safe_overlay`/`_fallback_field_def` 均在宪章单进程安全与零崩溃规范框架内实现 | 无需引入 Redis 外部限流组件即可保护 600k PBKDF2 算力与历史破损运行记录兼容性 |

### 1.7 Wiki 影响评估

- **结论**：不涉及（本次归档重构仅将既有 Spec 005 三件套升级为标准中文 SDD 格式，不新增或修改代码逻辑，不新建或改动 `wiki/` 页面）。
- **受影响页面**：既有权威页面为 `wiki/components/api-and-auth.md`、`wiki/reference/configuration.md`、`wiki/architecture/resource-release-and-store.md`（均已完整沉淀运行机制；顺手核对代码发现 `TokenService` 默认 `max_revoked` 为 `8192`、`routes_templates.py` 非法列表证据返回 `INVALID_FIELD_EVIDENCE`，本文档按代码实况如实记录）。
- **同步项**：无待新增 Wiki 同步任务。

### 1.8 三类独立交付物设计检查

| 独立交付物 | 涉及情况与依据 | 设计与变更摘要 | 验证与回退设计 | 关联问题 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 对外接口契约已沉淀于 `docs/frontend-api-handoff.md` | 核对接口实现与测试集一致 | 无 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求不修改 `seed/` 生产资源或迁移规则脚本 | `tests/test_api.py` 使用测试夹具隔离 | 无 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 无新增环境变量或容器镜像变更 | `tests/test_runtime_config_hot_reload.py` | 无 |

---

## 2. 需求映射（Traceability） 【核心】

| 规格编号 | 类型 | 需求摘要 | 设计章节映射 | 后续任务映射 |
| --- | --- | --- | --- | --- |
| `US1` / `SC-001`、`SC-003` | 用户故事 / 成功标准 | 防爆破登录会话、三轨鉴权、子路径反代与可热轮换 `X-API-Key` 上游 SSE 报告服务 | 第 `1.3`、`3`、`5`、`6`、`7` 章 | `T003`、`T004`、`T006`–`T008`、`T017` |
| `US2` / `SC-002`、`SC-005` | 用户故事 / 成功标准 | 模板全粒度乐观锁、变量同步重命名、内存预览、`cases` 抽取与 `dryrun/stream` | 第 `3`、`5`、`6` 章 | `T004`、`T005`、`T009`–`T011` |
| `US3` / `SC-002`、`SC-005` | 用户故事 / 成功标准 | Skill `_safe_overlay`、双协议 API 局部补丁与未落盘 `test-call`、提示词与密钥轮换 | 第 `3`、`5`、`6`、`9` 章 | `T012`–`T014` |
| `US4` / `SC-004`、`SC-005` | 用户故事 / 成功标准 | 跨版本 Diff、毫秒级 `emergency-switch`、容错 `detail_view`、大盘统计与 48 项热更新 | 第 `3`、`4`、`5`、`9` 章 | `T002`、`T005`、`T015`–`T016` |
| `FR-001` | 功能需求 | `create_app`、`Container`、`setup_logging`、`install_error_handlers`、`_SubpathPrefixMiddleware` 与 SPA 托管 | 第 `1.4`、`5`、`6`、`7` 章 | `T001`、`T003`、`T017` |
| `FR-002` | 功能需求 | PBKDF2 600k、`DUMMY_PASSWORD_HASH`、`_LOGIN_MAX_CONCURRENCY=4`、`LoginGuard`、`TokenService` | 第 `3`、`5`、`6`、`7` 章 | `T006`、`T007`、`T008` |
| `FR-003` | 功能需求 | `require_report_key` 动态密钥校验与 `POST /api/v1/reports*` 强制线上态 + SSE 保活 | 第 `5`、`6`、`7` 章 | `T004`、`T006`、`T007`、`T008` |
| `FR-004` | 功能需求 | 模板细粒度 `expected_revision` 乐观锁、`_rename_body_variable`、`list+input` 与 `FIELD_IN_USE` 拦截 | 第 `3`、`5`、`6` 章 | `T004`、`T009`、`T011` |
| `FR-005` | 功能需求 | 内存态 `render-preview`、`validate` 漂移检测、`diff`、`cases` 提取与 `dryrun/stream` | 第 `5`、`6` 章 | `T005`、`T010`、`T011` |
| `FR-006` | 功能需求 | 纯文本 Skill 治理、`_safe_overlay` 损坏草稿回退与乐观锁修订 | 第 `5`、`6.2` 章 | `T012`、`T014` |
| `FR-007` | 功能需求 | 双协议 XML/JSON 契约、局部 `api` 补丁、`requestPreview` 与未落盘 `test-call` 审计 | 第 `5`、`6` 章 | `T013`、`T014` |
| `FR-008` | 功能需求 | 系统提示词四视角读写发布回滚与 `X-API-Key` 读取/清空/即时重生成 | 第 `5`、`9` 章 | `T012`、`T013`、`T014` |
| `FR-009` | 功能需求 | `releases/diff`、`emergency-switch`、多维 `/runs`、`detail_view` 容错与 `/system/overview` | 第 `3`、`5`、`6.2` 章 | `T005`、`T015`、`T017` |
| `FR-010` | 功能需求 | `48` 项 `_ORDERED_FIELDS` 查询/更新/回滚/环境回同步、`apply_runtime_config` 与连接池回收 | 第 `3`、`4`、`5`、`9` 章 | `T002`、`T003`、`T016` |
| `NFR-001`~`NFR-005` | 非功能需求 | 零硬编码、单智能体隔离、单进程并发与防穿越、安全防爆破脱敏、审计与 `ruff` 门禁 | 第 `1.5`、`7`、`11` 章 | `T001`–`T018` |
| `EX-001`~`EX-006` | 异常边界 | 反代重定向与 `/api/*` 404、防驱逐撞库、乐观锁/字段冲突、破损草稿降级、拨测防越权、历史运行容错 | 第 `6.2`、`7`、`10` 章 | `T003`、`T006`、`T009`、`T012`–`T015`、`T017` |

---

<a id="plan-data-model"></a>

## 3. 核心领域模型（Domain Model） 【核心】

### 3.1 领域对象清单

| 对象 / 类 | 所在文件 | 职责与核心属性 | 关键不变量（Invariant） |
| --- | --- | --- | --- |
| `Container` | `src/report_agent/container.py` | 进程内组件装配容器：持有 `settings`、`layout`、`lock`、`repo`、`releases`、`drafts`、`publisher`、`service`、`cases`、`runs`、`gateway`、`runner`、`chat`、`runtime_config` | `apply_runtime_config()` 在 `self.lock` 内比较 `_gateway_signature(effective)`，仅网关参数变化时重建并调用 `ReloadableGatewayClient.swap` |
| `User` / `UserStore` | `src/report_agent/api/auth.py` | 管理端用户模型（`username`、`displayName`、`role`）与 `users.yaml` 持久化仓库 | 口令强制 PBKDF2-HMAC-SHA256 `600,000` 次；写盘原子替换并设置 `0o600`；`MAX_USERNAME_LEN=128`、`MAX_PASSWORD_LEN=1024` |
| `TokenService` / `LoginGuard` | `src/report_agent/api/auth.py` | HMAC-SHA256 会话令牌签发/吊销与账号/IP 双轨登录防爆破守卫 | `_MAX_TOKEN_LEN=4096`；撤销表 `max_revoked=8192` 按最早到期驱逐；`_known_users` 保护真实用户不被未知用户驱逐 |
| `PublishBody` / `RollbackBody` / `DraftBody` / `ApiDraftBody` / `TestCallBody` | `src/report_agent/api/common.py`、`routes_templates.py`、`routes_resources.py` | 治理写接口标准化入参契约 | `revision` 经 `parse_expected_revision` 拒绝 `bool` 与负数；`publish_now` 强制非空 `reason`；`test-call` 校验 `api.name == name` |
| `RuntimeConfig` / `RuntimeSnapshot` | `src/report_agent/store/runtime_config.py` | 覆盖 `48` 项 `_ORDERED_FIELDS` 的运行期热更新配置与不可变版本快照（`rev`、`operator`、`source`、`time`、`note`、`changedKeys`、`config`） | 跨字段校验约束（如 `agentQueryMaxLimit >= agentQueryDefaultLimit`、`chatCompactTriggerMessages > chatCompactKeepRecent`）；落盘严格 `0o600` |
| `detail_view` / `report_view` | `src/report_agent/api/run_views.py` | 工作台完整调试审计视图与上游精简结果视图构造函数 | `detail_view` 通过 `_fallback_field_def` 与 `safe_int` 吸收缺失/破损 `templateDef` 历史数据，绝不把 `"0"`/`"False"` 当作空值 |

### 3.2 状态机（如适用）

```text
# 1. LoginGuard 账号 / IP 锁定状态机
正常态 --(fail 累计达到 max_failures=5 或 ip_max_failures=20)--> 锁定态 (HTTP 429 LOGIN_LOCKED, until = now + 300s)
锁定态 --(成功登录 success() 或 until <= now 自然过期)--> 正常态

# 2. 草稿乐观锁修订流转
草稿初始/更新态 (revision = N) --(写操作携带 expected_revision == N)--> 修订递增态 (revision = N + 1)
草稿初始/更新态 (revision = N) --(写操作携带 expected_revision != N)--> 拒绝态 (HTTP 409 DRAFT_CONFLICT 附 current)
草稿存在态 --(publish 或 discard-draft)--> 无草稿线上对齐态 (status = PUBLISHED)

# 3. RuntimeConfig 运行期配置快照演进
env_settings 基线 --(bootstrap_or_load)--> 初始版本 c1 (0o600)
当前版本 cN --(PUT /settings/runtime 或 rollback/sync-env/api-key 变更)--> 新版本 c(N+1) + Container.apply_runtime_config() + aclose_retired()
```

---

## 4. 数据与存储设计（本需求范围） 【核心】

> 核心资源 Git 存储、发布目录、`runs/` 与 `cases/` 架构设计归属 `RA-002`（`specs/002-git-store-hot-reload/plan.md`）；本节列出本需求直接维护的配置存储与内存数据结构。

### 4.1 存储与缓存对象概览

| 对象/路径 | 变更类型 | 数据格式与字段要点 | 并发/清理/恢复策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `DATA_DIR/config/users.yaml` | 读写 | YAML：`users: [{username, displayName, role, passwordHash}]` | `UserStore._lock` 互斥 + `atomic_write_text` + `0o600`；读路径按 `(st_mtime_ns, st_size)` 缓存 | `FR-002` |
| `DATA_DIR/config/.token-secret` | 首次写入后只读 | 48 字节 URL-safe 随机签名密钥文本 | 若 `ADMIN_TOKEN_SECRET` 未配置时原子创建并设为 `0o600` | `FR-002` |
| `DATA_DIR/config/runtime/{current.json,index.jsonl,revisions/cN.json}` | 读写 / 不可变快照 | `current.json` 含 `activeRev` 与全量 `config`；`index.jsonl` 为脱敏变更索引；`cN.json` 保存完整快照含密钥支持精确回滚 | `Container.lock` 互斥 + 工作线程执行 + `0o600` 权限限制；启动时异常态自愈加载 | `FR-008`、`FR-010` |
| `DATA_DIR/audit.jsonl` | 只追加 | JSONL：每行记录 `time`、`action`、`operator`、`detail` | 原子追加；写接口强制从已认证 `request.state.user.displayName` 赋值 `operator` | `FR-004`~`FR-010` |
| `LoginGuard` 内存表 (`_fails` / `_known_users` / `_ip_fails`) | 进程内内存 | 映射 `ukey -> (count, until)` 与 `ip_key -> (count, until)`，超长键做 SHA-256 摘要 | `threading.Lock` 同步；惰性清理过期条目；容量上限 `4096`，优先淘汰未知非锁定项 | `FR-002` |
| `TokenService._revoked` & `common._BG_TASKS` | 进程内内存 | 已撤销 nonce -> `exp` 字典（上限 `8192`）；活跃后台 SSE `Task` 弱耦合强引用集合 | 撤销时清理过期项并按最早过期键驱逐；SSE 任务完成回调自动 `discard` | `FR-002`、`FR-003` |

---

<a id="plan-contracts"></a>

## 5. 接口与契约设计（API / Tools / Events） 【核心】

### 5.1 接口与契约清单

| 契约编号 | 类型 | 名称 / Path | 方向 | 关键入参 / 载荷 | 关键出参 / 响应 / 事件 | 鉴权与幂等 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `API-1` | HTTP | `GET /healthz`、`GET /api/v1/health` | 外部/探活 → 网关 | 无 | `{status: "UP", liveRev, totalReleases, gatewayMode, time}` | 公开只读 / 幂等 | `FR-001` |
| `API-2` | HTTP | `POST /api/v1/auth/login`、`POST /logout`、`GET /me` | 工作台 → 网关 | `{username, password}` | `{token, username, displayName, role}` + `ra_session` Cookie / `{ok: true}` | 公开登录（`LoginGuard`+`4` 并发信号量）/ 会话鉴权 | `FR-002` |
| `API-3` | HTTP / SSE | `POST /api/v1/reports`、`POST /api/v1/reports/stream` | 上游系统 → 网关 | `ReportBody {templateId, params, document, batchNo?}` | 同步返回 `report_view`；SSE 流推送 `event`/`final`/`error` + 15s `: keep-alive` | `require_report_key`（`X-API-Key` 恒定时间比对）/ 强制 `target="online"` | `FR-003` |
| `API-4` | HTTP | `GET/POST /api/v1/templates`、`copy`、`offline`、`restore`、`cross-fields`、`GET /templates/{tid}` | 工作台 → 网关 | `CreateTemplateBody` / `CopyTemplateBody` / `ReasonBody` / `version=working\|draft\|online\|rN` | `TemplateItem` / `TemplateDetail` / 状态变更结果 | `require_user` + `SAFE_ID_RE` | `FR-004` |
| `API-5` | HTTP | `PUT /templates/{tid}/draft`、`fields/{name}`、`DELETE /fields/{name}`、`batch-evidence`、`fields-order`、`skills` | 工作台 → 网关 | 各自结构化载荷 + `revision`（乐观锁）+ 可选 `originalName` / `force` | 最新 `revision`、`draft` 元数据与更新后 DTO | `require_user` + `expected_revision`（`409`/`400`） | `FR-004` |
| `API-6` | HTTP / SSE | `POST /templates/{tid}/{validate,publish,rollback,discard-draft,render-preview}`、`GET diff/revisions`、`/cases*`、`POST /dryrun*` | 工作台 → 网关 | `PreviewBody` / `PublishBody` / `RollbackBody` / `DryRunBody`（支持 `caseId` / `fromRunId`） | `validation_result_with_drift`、`text/usedFields/undefinedFields`、Diff、用例 DTO、`detail_view` | `require_user` + `render-preview` 零写盘 | `FR-005` |
| `API-7` | HTTP | `/api/v1/skills*`（`GET/POST/PUT draft/discard-draft/validate/publish/rollback/revisions`） | 工作台 → 网关 | `CreateSkillBody`、`SkillDraftBody`（含 `revision`）、`PublishBody`、`RollbackBody` | `skill_item`（含 `refTemplates`、`loads7d`）、Markdown 与校验结果 | `require_user` + `_safe_overlay` 降级容错 | `FR-006` |
| `API-8` | HTTP | `/api/v1/apis*`（CRUD/治理/`validate`/`POST /apis/{name}/test-call`） | 工作台 → 网关 | `ApiDraftBody`（`yamlText` 或局部 `api` 补丁）、`TestCallBody {params, yamlText?}` | `api_item`、脱敏 `requestPreview`、`test-call` 返回报文/耗时/列/记录 | `require_user` + `API_NAME_MISMATCH` 防护 + 审计落盘 | `FR-007` |
| `API-9` | HTTP | `/api/v1/settings/system-prompt*`、`/api/v1/settings/api-key*`（`GET`/`PUT`/`regenerate`） | 工作台 → 网关 | `SysPromptBody`、`ApiKeyUpdateBody`、`ApiKeyRegenerateBody` | 提示词四版本状态、`_api_key_payload`（含 `ra_` 新密钥与 `runtimeState`） | `require_user` + 立即同步 `report_keys` | `FR-008` |
| `API-10` | HTTP | `/api/v1/releases*`（`diff`、`emergency-switch`）、`/runs*`、`/system/overview`、`/settings/{model,runtime*}` | 工作台 → 网关 | `SwitchBody {targetRev, reason}`、多维筛选参数、`RuntimeConfig` 48 项补丁与 `clear*` 标志 | 跨版本 Diff、`activeRev`、容错 `detail_view`、统计大盘、掩码后 `RuntimeSnapshot` | `require_user` + `0o600` + `apply_runtime_config` + `aclose_retired` | `FR-009`、`FR-010` |

### 5.2 关键契约说明与错误语义

- **统一错误载荷 `{code, message, ...}`**：所有业务、校验与认证错误均通过 `install_error_handlers` 或 `HTTPException(detail=...)` 标准化输出：
  - `400`：`BAD_REQUEST`、`INVALID_REVISION`、`INVALID_FIELD_NAME`、`INVALID_FIELD_EVIDENCE`、`FIELD_IN_USE`、`INVALID_PREVIEW_FIELD`、`INVALID_TEMPLATE_ID`、`INVALID_CASE_ID`、`INVALID_SKILL_ID`、`INVALID_API_NAME`、`API_NAME_MISMATCH`、`INVALID_API_SCHEMA`、`INVALID_PARAMS`、`INVALID_RUNTIME_CONFIG`、`NO_DRAFT`、`INVALID_VERSION`、`INVALID_LIMIT` / `INVALID_OFFSET` / `INVALID_DAYS` / `INVALID_DATE_RANGE` / `INVALID_RUN_ID`。
  - `401`：`UNAUTHORIZED`、`INVALID_CREDENTIALS`、`INVALID_API_KEY`。
  - `404`：`NOT_FOUND`、`RELEASE_NOT_FOUND`、`TEMPLATE_UNAVAILABLE`。
  - `409`：`DRAFT_CONFLICT`（附最新 `current` 草稿元数据）、`NOTHING_TO_PUBLISH`。
  - `422`：`PUBLISH_BLOCKED`（附 `issues` 明细）、`VALIDATION_ERROR`（Pydantic 入参结构校验错误）。
  - `429`：`LOGIN_LOCKED`（账号或直连 IP 触发防爆破锁定）。
  - `500`：`GIT_ERROR`（仅记录内部日志，对外隐藏堆栈与路径细节）。
- **乐观锁版本号校验边界**：`parse_expected_revision` 明确区分 `None`（跳过版本校验以兼容简单调用）与具体整数版本；若客户端误传布尔值 `true`/`false`、浮点数或负整数，立即返回 `400 INVALID_REVISION`；`DELETE /templates/{tid}/fields/{name}` 通过 `_resolve_delete_field_revision` 同时兼容查询参数 `?revision=` 与请求体 JSON `revision`。

---

## 6. 业务流程设计（可直接编码） 【核心】

### 6.1 核心执行流程

```text
# 链路 A：防爆破登录鉴权流（POST /api/v1/auth/login）
1. 提取直连 IP _client_ip(request)，校验用户名非空且 <= 128 字符、口令非空。
2. 调用 guard.check(username, client_ip=client_ip)，若账号或 IP 已锁直接返回 429 LOGIN_LOCKED。
3. 若口令 > 1024 字符，记 fail 并立即返回 401 INVALID_CREDENTIALS，阻断高迭代哈希算力放大。
4. 获取当前事件循环信号量 _login_semaphore()（上限 4 并发），在 asyncio.to_thread 中读取 UserStore 并对存在用户真实哈希或不存在用户 DUMMY_PASSWORD_HASH 执行 600k PBKDF2 校验。
5. 校验失败调用 guard.fail(..., known_user=rec is not None, client_ip=client_ip) 返回 401；成功则清空计数、签发 HMAC Token、写入 HttpOnly+SameSite=strict Cookie 并返回用户信息。

# 链路 B：48 项配置热更新 / API Key 轮换流（PUT /settings/runtime & /settings/api-key*）
1. 路由层校验布尔标识与输入结构（API Key 更新拦截控制字符，重生成构造 ra_<token_urlsafe(24)>）。
2. 进入 _apply_runtime_mutation，在工作线程获取 Container.runtime_config 并更新持久化快照（0o600 权限）。
3. 若配置确实变化，在 Container.lock 内执行 c.apply_runtime_config()：若 _gateway_signature 变更则构建新网关客户端并 swap 进 ReloadableGatewayClient；更新 settings、releases.keep 并刷新 AgentRunner 模型与参数。
4. 同步刷新 request.app.state.report_keys；回主事件循环异步执行 await c.gateway.aclose_retired() 排空关闭退役连接池后返回脱敏响应。
```

### 6.2 并发控制与异常降级策略

| 异常/并发场景 | 检测时机 | 处理策略 | 是否中断主流程 | 可观测性输出 |
| --- | --- | --- | --- | --- |
| 并发修改同一草稿资源 | 写盘前（`DraftStore` / `Service`） | 比对 `expected_revision` 与当前 `.meta.json` `revision`，失配抛出 `DraftConflict` 返 `409` 附 `current` | 是（保护先提交者数据） | 结构化 `409` JSON 响应 |
| SSE 推理流客户端中途断开 | 生成协程期间（`sse_run`） | 后台生产协程由 `_BG_TASKS` 强引用托管继续运行至终态并完整写入 `RunStore`，完成后 `done_callback` 自动移除引用 | 否（后台完整落盘） | 运行记录与日志正常落盘 |
| 资源列表含破损 YAML 草稿 | 列表聚合或校验（`routes_resources`） | `_safe_overlay` 捕获 `InvalidResource` / `ValueError`，对损坏项自动回退读取 `live` 线上版本 | 否（列表正常渲染） | 局部状态保留，不返回 500 |
| 历史运行记录 `templateDef` 缺失或数值破损 | 查看历史详情（`run_views.py`） | `detail_view` 捕获校验异常并调用 `_fallback_field_def` 重建字段定义，`safe_int` 容错计数，保留 `"0"`/`"False"` | 否（历史审计可读） | 完整返回 `detail_view` |

---

## 7. 权限与安全控制（本需求范围） 【补充】

| 控制点 | 适用角色/调用方 | 校验机制与边界 |
| --- | --- | --- |
| 管理端会话认证（`require_user`） | 管理员与配置工程师 | `Authorization: Bearer` 或 `HttpOnly` + `SameSite=strict` Cookie `ra_session`；HMAC-SHA256 签名；支持登出吊销 nonce；`LoginGuard` 5 次账号 / 20 次 IP 锁定 300 秒 |
| 上游接口密钥（`require_report_key`） | 上游业务工单系统 | 动态读取 `container.settings.report_api_key_set()`，使用 `hmac.compare_digest` 逐项常量时间比对 `X-API-Key` |
| 身份防伪造（`operator(request)`） | 所有管理端写接口与拨测接口 | 审计人与 Git 提交人一律从认证挂载的 `request.state.user.displayName` 提取，完全无视前端请求体传参 |
| 路径防穿越与标识符白名单 | 全部资源路由与静态托管 | 正则校验 `SAFE_ID_RE`、`SKILL_ID_RE`、`API_NAME_RE`、`CASE_ID_RE`、`REV_RE`、`CONFIG_REV_RE`；`spa()` 强制 `target.is_relative_to(dist_dir)` |
| 敏感数据脱敏 | `/settings/runtime*`、`/apis/{name}/validate`、`GitError` | 密钥字段经 `mask_secret`/`mask_api_keys` 掩码（`/settings/api-key` 显式授权接口除外）；`requestPreview` 脱敏凭证；`GitError` 屏蔽内部异常堆栈 |

---

## 8. 前端 / 交互设计（如适用） 【补充】

> 本需求不涉及前端页面或交互变更（浏览器管理端工作台、CodeMirror 6 IDE 与证据溯源组件归属 `RA-006` `specs/006-vue-workbench-ide/`；嵌入式聊天前端归属 `RA-007`）；本需求仅通过 `docs/frontend-api-handoff.md` 规范前后端契约并在 `main.py` 中安全托管 `FRONTEND_DIST` 静态构建目录。

---

## 9. 配置与热更新开关 【补充】

> 全部 `48` 项 `_ORDERED_FIELDS` 运行期配置项由 `RuntimeConfigStore` 托管，覆盖大模型（10 项）、智能体运行与工具限额（12 项）、嵌入式聊天与滚动上下文压缩（16 项）、统一网关与调用密钥（7 项）及快照/运行保留期（3 项）；以下仅列出本需求接口与鉴权核心相关配置及启动期环境变量边界。

| 配置项（Env / RuntimeConfig） | 类型 | 默认值 | 是否支持热更新 | 说明 |
| --- | --- | --- | --- | --- |
| `REPORT_API_KEYS` / `reportApiKeys` | `str` | `""` | 是（经 `/settings/runtime` 或 `/settings/api-key*`） | 逗号分隔上游与聊天调用密钥集，支持 `ra_` 一键重生成与安全清空 |
| `LLM_*`、`AGENT_*`、`GATEWAY_*`、`CHAT_*`、`RELEASES_KEEP`、`RUNS_KEEP_DAYS`（共 47 项） | `str`/`int`/`float`/`bool` | 见 `Settings` | 是（覆盖 `_ORDERED_FIELDS` 其余 47 项） | 通过 `PUT /api/v1/settings/runtime` 修改后立即热重载至 `Container` |
| `APP_ROOT_PATH` | `str` | `""` | 否（启动期不变量） | 反向代理子路径前缀，驱动 `_SubpathPrefixMiddleware` 与 `normalized_root_path()` |
| `FRONTEND_DIST` | `str \| None` | `None` | 否（启动期不变量） | 前端静态打包目录，存在时自动挂载 `/assets` 与隔离 SPA 兜底路由 |
| `ADMIN_TOKEN_SECRET` / `ADMIN_TOKEN_TTL_S` / `ADMIN_COOKIE_SECURE` | `SecretStr`/`int`/`bool` | 自动生成 / `43200` / `False` | 否（启动期不变量） | 会话令牌签名密钥（未设则持久化 `.token-secret` `0600`）、有效期与 HTTPS Cookie 标志 |
| `ADMIN_BOOTSTRAP_PASSWORD` / `LOG_DIR` / `LOG_LEVEL` | `SecretStr`/`str` | `None` / `None` / `INFO` | 否（启动期不变量） | 首次无用户时初始化 `admin` 口令、按天滚动文件日志目录及日志级别 |

---

## 10. 测试设计（Test Strategy） 【核心】

### 10.1 测试范围与分层策略

| 测试类型 | 覆盖范围 | 桩/隔离策略 | 重点验证场景 |
| --- | --- | --- | --- |
| 安全与鉴权单元测试 | `UserStore`、`TokenService`、`LoginGuard`、`_login_semaphore` | `tmp_path` 隔离数据目录、独立线程与内存状态 | 600k PBKDF2 校验、超长口令/Token 截断、已知用户防驱逐、IP 锁定、Token 撤销上限淘汰 |
| 接口契约与乐观锁集成测试 | `routes_templates`、`routes_resources`、`routes_system`、`dto`、`run_views` | `fastapi.testclient.TestClient` + `ScriptedModel` + `MockGatewayClient` + `conftest.py` `SEED_DIR` 隔离 | `409 DRAFT_CONFLICT`、`INVALID_REVISION`、`FIELD_IN_USE`、`INVALID_FIELD_EVIDENCE`、内存 `render-preview`、`cases` 提取 |
| 双协议拨测、热更新与反代回归测试 | XML/JSON API 接口、未落盘 `test-call`、48 项热更新、`_SubpathPrefixMiddleware`、审计与破损容错 | `monkeypatch`、模拟损坏 YAML/运行 JSON、多路径请求 | `API_NAME_MISMATCH`、脱敏 `requestPreview`、`/agent` 307 重定向、`/api/*` 404、`operator` 防伪造、`0600` 权限与连接池关闭 |

### 10.2 回归范围

- 全量测试套件 `uv run pytest -q`（当前共 196 个用例），重点覆盖 `tests/test_api.py`、`tests/test_api_and_store_fixes.py`、`tests/test_api_routes_json.py`、`tests/test_deep_audit_fixes.py` 与 `tests/test_runtime_config_hot_reload.py`。
- 静态代码风格与类型/规范检查：`uvx ruff@0.11.0 check src tests`。

<a id="plan-quickstart"></a>

### 10.5 验证指南

- **环境与前置条件**：Python `3.13` + `uv` 环境，全部自动化测试使用 `ScriptedModel` 与本地 Mock 网关，无需外网大模型或真实内网网关。
- **验证命令**：
  ```bash
  uv run pytest tests/test_api.py tests/test_api_and_store_fixes.py tests/test_api_routes_json.py tests/test_deep_audit_fixes.py tests/test_runtime_config_hot_reload.py -q
  uv run pytest -q
  uvx ruff@0.11.0 check src tests
  ```
- **预期结果**：所有测试集全量通过（无跳过或放宽断言），`ruff` 检查输出 `All checks passed!`。

---

## 11. NFR 符合性自检 【核心】

| 自检主题 | 宪章依据 | 是否涉及 | 落实位置与验证方式 |
| --- | --- | --- | --- |
| 零业务硬编码与资源隔离 | I | 是 | `src/report_agent/api/*`、`main.py`、`container.py` 仅处理声明式资源契约与 DTO 转换，经源码审阅与测试验证 |
| 强证据防幻觉与确定性计算 | II | 是 | 上游 `/reports*` 强制锁定 `target="online"`，`run_views.py` 完整保留证据状态与校验退回轮次，经 `test_api.py` 验证 |
| 文件化存储与 `workers=1` 并发安全 | III | 是 | `Container.lock`、`parse_expected_revision`、`_BG_TASKS`、`0o600` 原子写盘及标识符正则守卫，经 `test_api_and_store_fixes.py` 与 `test_deep_audit_fixes.py` 验证 |
| 安全编码、脱敏与零凭据硬编码 | VI | 是 | PBKDF2 600k、`LoginGuard`、`hmac.compare_digest`、`requestPreview` 与 `runtime` 脱敏、`GitError` 隐匿堆栈，经专项测试验证 |
| 过程事件、阶段日志与审计留痕 | VII | 是 | `operator(request)` 强制注入身份写入 `audit.jsonl`，`sse_run` 断连保活完整落盘，经 `test_deep_audit_fixes.py` 验证 |

---

## 12. 发布与回退计划 【核心】

- **发布前置与步骤**：运行 `uv run pytest -q` 与 `uvx ruff@0.11.0 check src tests` 全绿 → 校验环境变量（生产必配 `REPORT_API_KEYS`、`ADMIN_TOKEN_SECRET`、`APP_ROOT_PATH`）→ 以单进程 `uvicorn report_agent.main:app --workers 1` 启动服务并探测 `/healthz` 返回 `UP`。
- **回退方案**：
  1. 资源内容异常：通过 `POST /api/v1/releases/emergency-switch` 毫秒级原子切换 `releases/current` 至上一稳定 `rN` 版本。
  2. 运行参数/密钥异常：通过 `POST /api/v1/settings/runtime/rollback` 回退至历史 `cN` 配置快照（或调用 `sync-env` 重同步启动环境）。
  3. 网关代码异常：回退容器镜像版本并重启单进程 Uvicorn 实例。

---

## 13. 实施切片与建议顺序（Implementation Slices） 【核心】

> 与 `tasks.md` 7 个阶段及 18 项任务严格对齐，切片工时精确加总为 `33.0 人天`。

| 切片 ID | 切片名称 | 对应 Phase / 任务范围 | 目标与涉及文件 | 核算工时（如适用） |
| --- | --- | --- | --- | --- |
| `S-01` | 运行配置与 48 项热更新基座 | Phase 1（`T001`–`T002`） | `config.py`、`api/__init__.py`、`store/runtime_config.py` | `3.0 人天` |
| `S-02` | 应用工厂、公共原语与双态运行视图底座 | Phase 2（`T003`–`T005`） | `main.py`、`container.py`、`api/common.py`、`api/dto.py`、`api/run_views.py` | `6.0 人天` |
| `S-03` | 三轨安全鉴权与上游报表 REST/SSE 入口（MVP） | Phase 3 / US1（`T006`–`T008`） | `api/auth.py`、`api/routes_system.py`、`tests/test_api_and_store_fixes.py`、`tests/test_api.py` | `6.5 人天` |
| `S-04` | 细粒度乐观锁模板编排、预览、用例与试运行 | Phase 4 / US2（`T009`–`T011`） | `api/routes_templates.py`、`tests/test_api_and_store_fixes.py`、`tests/test_api.py` | `6.0 人天` |
| `S-05` | Skill 容错治理、双协议 API 拨测与提示词/密钥轮换 | Phase 5 / US3（`T012`–`T014`） | `api/routes_resources.py`、`tests/test_api_routes_json.py`、`tests/test_api.py` | `5.5 人天` |
| `S-06` | 跨版本 Diff、紧急切换、台账容错与 48 项热配置 API | Phase 6 / US4（`T015`–`T016`） | `api/routes_system.py`、`api/routes_resources.py` | `3.5 人天` |
| `S-07` | 深度审计安全回归与前后端接口契约归档收口 | Phase 7（`T017`–`T018`） | `tests/test_deep_audit_fixes.py`、`docs/frontend-api-handoff.md` | `2.5 人天` |

---

## 14. 风险清单与缓解（Risks） 【补充】

| 风险 ID | 风险描述 | 影响 | 概率 | 缓解措施 |
| --- | --- | --- | --- | --- |
| `R-1` | 运维误配置多 Worker 启动 Uvicorn 导致进程内 `LoginGuard`、撤销表与写入锁分裂 | 高 | 低 | 文档、代码注释与宪章强制规定 `workers=1`；容器启动脚本锁定单进程入口 |
| `R-2` | 高并发异常登录请求消耗线程池导致健康检查或正常用户登录超时 | 高 | 中 | 使用 `_LOGIN_MAX_CONCURRENCY = 4` 信号量限流 + `MAX_PASSWORD_LEN = 1024` 拦截 + `LoginGuard` 快速拒绝 |
| `R-3` | 历史或手工改写损坏草稿/运行记录引起治理台账或列表 500 崩溃 | 中 | 中 | `_safe_overlay` 自动回退线上快照；`detail_view` 使用 `_fallback_field_def` 与 `safe_int` 多级降级 |

---

## 15. 待确认事项（Design Open Questions） 【补充】

> 设计阶段关键技术取舍已全部闭环，无未关闭 `DQ-*`。

| 编号 | 问题摘要 | 对应 Spec Q-* | 当前结论 | 状态 |
| --- | --- | --- | --- | --- |
| `DQ-1` | `REPORT_API_KEYS` 为空时的上游报表接口鉴权策略 | `Q-001` | 允许开发环境免密回退并打印启动告警，支持通过 `/settings/api-key*` 热启用多密钥 | 已关闭 |
| `DQ-2` | 登录限流 IP 提取是否信任代理转发头 | `Q-002` | 仅取直连 `request.client.host`，避免 `X-Forwarded-For` 伪造绕过或误封禁 | 已关闭 |

---

## 附录 A：核心字段与状态约定（仅本需求）

- **Cookie 与认证头**：管理端 Cookie 名固定 `ra_session`（`HttpOnly`、`SameSite=strict`），支持 `Authorization: Bearer <token>`；上游调用头固定 `X-API-Key`；新生成系统调用密钥固定前缀 `ra_`。
- **鉴权与限流默认阈值**：`_ITERATIONS = 600_000`、`MAX_USERNAME_LEN = 128`、`MAX_PASSWORD_LEN = 1024`、`_MAX_TOKEN_LEN = 4096`、`TokenService.max_revoked = 8192`、`LoginGuard(max_failures=5, lock_s=300, max_entries=4096, ip_max_failures=20)`、`_LOGIN_MAX_CONCURRENCY = 4`。
- **SSE 帧类型**：连接初始注释 `: connected`、15 秒保活注释 `: keep-alive`、标准事件 `event: event` / `event: final` / `event: error`。

## 附录 B：AI 编码与交付约束

1. 先阅读 `spec.md`、本 `plan.md` 与 `tasks.md`，按 `T001`–`T018` 顺序实施，不实现 Out of Scope 内容。
2. 所有已勾选完成 `[X]` 的任务必须附有真实命令验证输出，严禁“仅写完未验证即标完成”。

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | Codex | 完成 `005-api-auth-governance` 初始架构设计文档（33.0 人天） |
| 2.0 | 2026-11-16 | AiCoding | 按改造后 `inline-v1` 单文件 Plan 模板重构，补充四大内联锚点、宪章门禁核查、Wiki 评估、三类独立交付物台账及精确代码符号对齐 |
