---
description: "REST/SSE 服务网关、三轨安全鉴权体系与全生命周期治理接口 Spec Kit 任务清单（RA-005）"
---

# 任务说明（Implementation Tasks）：REST/SSE 服务网关、三轨安全鉴权体系与全生命周期治理接口

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：本文件承接 `./spec.md` 与 `./plan.md`（`<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->` 内联四章），将 7 个研发切片转化为顺序清晰、带真实文件路径与工时的 18 项任务清单。本需求已全部实现并通过自动化测试与静态检查门禁，第 3 章权威清单任务统一标注 `[X]` 并在 `3.5` 节与第 6 章附上本轮实测证据。

---

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-005` |
| 需求名称 | REST/SSE 服务网关、三轨安全鉴权体系与全生命周期治理接口 |
| 对应需求文档 | `./spec.md` |
| 对应设计文档 | `./plan.md` |
| tasks 版本 | `2.0` |
| 核算工作量 | `33.0 人天`（18 项任务合计严格等于 `33.0 人天`） |
| 状态 | 已完成（归档验收） |
| 负责人 | AiCoding / 后端网关工程团队 |

---

## 0. 使用方式（给 AI 的执行指令） 【核心】

1. 按第 3 章权威任务清单顺序推进；标记 `[P]` 的任务可与同阶段无文件冲突任务并行，但不得越过前置阶段阻塞依赖。
2. 全文**仅第 3 章权威清单**使用复选框，每条严格遵循 `- [X] Txxx [P?] [USx?] 描述（X.X 人天）`；其他章节仅引用 `T*` 编号，不重复设置复选框。
3. 第 `3.5` 节记录各任务组对应的实际变更文件、核心符号及真实命令验证结果；无真实通过证据不得勾选 `[X]`。
4. 遇到需求歧义或现状冲突时，停止扩大改动并登记至第 9 节 `BQ-*`，回链 `spec.md` `Q-*`。

---

## 1. 需求到任务映射（Traceability） 【核心】

| 需求/标准 ID | 摘要 | 对应设计（Plan.md） | 映射任务 ID | 测试/验证映射 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `US1` / `SC-001`、`SC-003` | 防爆破工作台登录会话、三轨鉴权、子路径反代与可轮换 `X-API-Key` 上游 SSE 报告服务 | 第 `1.3`、`3`、`5`、`6`、`7` 章 | `T003`、`T004`、`T006`–`T008`、`T017` | `TT-01`、`TT-02`、`TT-04` | 已验证 |
| `US2` / `SC-002`、`SC-005` | 细粒度 `expected_revision` 模板编辑、变量联动重命名、内存预览、`cases` 与 `dryrun/stream` | 第 `3`、`5`、`6` 章 | `T004`、`T005`、`T009`–`T011` | `TT-02`、`TT-03` | 已验证 |
| `US3` / `SC-002`、`SC-005` | Skill `_safe_overlay`、双协议接口补丁与未落盘 `test-call`、提示词四视角与密钥重生成 | 第 `3`、`5`、`6`、`9` 章 | `T012`–`T014` | `TT-03` | 已验证 |
| `US4` / `SC-004`、`SC-005` | 跨版本 Diff、`emergency-switch`、`detail_view` 容错、`overview` 与 48 项热更新 | 第 `3`、`4`、`5`、`9` 章 | `T002`、`T005`、`T015`–`T016` | `TT-04`、`TT-05` | 已验证 |
| `FR-001` | 应用工厂 `create_app`、`Container`、`setup_logging`、`install_error_handlers`、`_SubpathPrefixMiddleware` 与 SPA 托管 | 第 `1.4`、`5`、`6`、`7` 章 | `T001`、`T003`、`T017` | `TT-04` | 已验证 |
| `FR-002` | PBKDF2 600k、`DUMMY_PASSWORD_HASH`、`_LOGIN_MAX_CONCURRENCY=4`、`LoginGuard`、`TokenService` | 第 `3`、`5`、`6`、`7` 章 | `T006`、`T007`、`T008` | `TT-01`、`TT-02` | 已验证 |
| `FR-003` | `require_report_key` 动态比对与 `/api/v1/reports*` 强制线上态 + SSE `_BG_TASKS` 保活 | 第 `5`、`6`、`7` 章 | `T004`、`T006`、`T007`、`T008` | `TT-01` | 已验证 |
| `FR-004` | 模板 CRUD 与单字段/排序/技能细粒度乐观锁、`_rename_body_variable`、`list+input` 与 `FIELD_IN_USE` | 第 `3`、`5`、`6` 章 | `T004`、`T009`、`T011` | `TT-02` | 已验证 |
| `FR-005` | 内存 `render-preview`、`validate` 漂移检测、`diff`、`cases` 提取与 `dryrun/stream` | 第 `5`、`6` 章 | `T005`、`T010`、`T011` | `TT-01`、`TT-02` | 已验证 |
| `FR-006` | 纯文本 Skill 治理与 `_safe_overlay` 损坏草稿回退 | 第 `5`、`6.2` 章 | `T012`、`T014` | `TT-03` | 已验证 |
| `FR-007` | XML/JSON 接口补丁、`requestPreview` 与未落盘 `test-call` 拨测审计 | 第 `5`、`6` 章 | `T013`、`T014` | `TT-03`、`TT-04` | 已验证 |
| `FR-008` | 系统提示词四视角治理与 `X-API-Key` 读取/清空/重生成 | 第 `5`、`9` 章 | `T012`、`T013`、`T014` | `TT-01`、`TT-03` | 已验证 |
| `FR-009` | `releases/diff`、`emergency-switch`、多维 `/runs`、`detail_view` 容错与 `/system/overview` | 第 `3`、`5`、`6.2` 章 | `T005`、`T015`、`T017` | `TT-01`、`TT-04` | 已验证 |
| `FR-010` | `48` 项 `_ORDERED_FIELDS` 查询/更新/回滚/环境回同步与 `aclose_retired` | 第 `3`、`4`、`5`、`9` 章 | `T002`、`T003`、`T016` | `TT-05` | 已验证 |
| `NFR-001`~`NFR-005` | 零硬编码、单智能体隔离、单进程并发与防穿越、防爆破脱敏、审计与 `ruff` 检查 | 第 `1.5`、`7`、`11` 章 | `T001`–`T018` | `TT-01`~`TT-06` | 已验证 |
| `EX-001`~`EX-006` | 反代 307 与 `/api/*` 404、防驱逐撞库、乐观锁冲突、破损草稿降级、拨测名称防越权、历史记录兜底 | 第 `6.2`、`7`、`10` 章 | `T003`、`T006`、`T009`、`T012`–`T015`、`T017` | `TT-02`、`TT-03`、`TT-04` | 已验证 |

### 1.1 三类独立交付物维护台账

| 独立交付物 | 涉及情况与依据 | 关联任务 | 维护状态 | 验证结果 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；外部/前端契约存于 `docs/frontend-api-handoff.md`） | 不生成（契约对齐见 `T018`） | 不生成 | `docs/frontend-api-handoff.md` 已与路由对齐 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 不生成 | 不生成 | 本需求不改写 `seed/` 生产模板 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 不生成 | 不生成 | `48` 项热配置已全量纳入既有环境变量体系 |

---

## 2. 里程碑与切分策略（Milestones） 【补充】

| 阶段 / Milestone | 目标 | 任务范围 | 阶段工时（人天） | 验收定义 |
| --- | --- | --- | --- | --- |
| Phase 1: Setup（基础配置与 48 项热配置模型） | 对齐 `Settings` 与 `RuntimeConfigStore`（`48` 项） | `T001`–`T002` | `3.0` | 配置模型与 `0600` 快照仓库单测就绪 |
| Phase 2: Foundational（容器装配、中间件与双态视图） | 完成 `create_app`、`Container`、`common`、`dto`、`run_views` | `T003`–`T005` | `6.0` | 应用装配、SSE 护航、乐观锁解析与容错视图就绪 |
| Phase 3: US1（三轨鉴权与上游 SSE 报表，MVP） | 交付 `auth.py`、`LoginGuard`、`/auth/*` 与 `/reports*` | `T006`–`T008` | `6.5` | `429 LOGIN_LOCKED`、撤销失效与 `X-API-Key` 报表测试通过 |
| Phase 4: US2（细粒度乐观锁模板编排与试运行） | 交付 `routes_templates.py` 全量接口与对应单测 | `T009`–`T011` | `6.0` | `409 DRAFT_CONFLICT`、变量重命名、预览与 `cases` 通过 |
| Phase 5: US3（Skill/双协议接口拨测与提示词轮换） | 交付 `routes_resources.py` 治理与拨测路由及测试 | `T012`–`T014` | `5.5` | `_safe_overlay`、未落盘 `test-call` 与密钥重生成通过 |
| Phase 6: US4（版本发布、台账容错与热配置接口） | 交付 `diff`/`emergency-switch`/`overview` 与热配置 API | `T015`–`T016` | `3.5` | 软链接切换、破损运行兜底与 `48` 项热更新生效 |
| Phase 7: Polish（深度审计回归与契约归档） | 收口 `test_deep_audit_fixes.py`、文档对齐与全量门禁 | `T017`–`T018` | `2.5` | `pytest` 196 通过、`ruff` 0 告警、前后端契约一致 |

### 2.1 依赖与交付顺序

- **阶段依赖**：Phase 1（配置基座 `T001`–`T002`） → Phase 2（容器、公共辅助与 DTO/视图底座 `T003`–`T005`） → Phase 3–6（按 P1 `US1`/`US2` 至 P2 `US3`/`US4` 递进交付） → Phase 7（深度审计回归与文档收口 `T017`–`T018`）。
- **并行机会**：Phase 1 中 `T002` 与 `T001` 并行；Phase 2 中 `T004`、`T005` 与 `T003` 并行；Phase 3–6 内各独立测试验证（`T008`、`T011`、`T014`）及 `T016` 在前置接口就绪后并行完成；Phase 7 中 `T017` 与 `T018` 并行收尾。

---

## 3. 任务清单（按执行顺序） 【核心】

### 3.1 Phase 1: Setup (Shared Infrastructure)

- [X] T001 对齐运行配置模型 `Settings`（`report_api_key_set()` 与 `normalized_root_path()`）并初始化 API 路由包入口，文件：`src/report_agent/config.py` `src/report_agent/api/__init__.py`（1.5 人天）
- [X] T002 [P] 实现 `48` 项 `_ORDERED_FIELDS` 运行期配置模型 `RuntimeConfig`、`RuntimeSnapshot` 与 `0600` 权限版本化存储 `RuntimeConfigStore`，文件：`src/report_agent/store/runtime_config.py`（1.5 人天）

### 3.2 Phase 2: Foundational (Blocking Prerequisites)

- [X] T003 实现 `create_app` 应用工厂、`Container` 热更新装配（`apply_runtime_config()` 与 `_gateway_signature`）、`_SubpathPrefixMiddleware`、统一错误处理及 SPA 静态托管，文件：`src/report_agent/main.py` `src/report_agent/container.py`（2.0 人天）
- [X] T004 [P] 实现公共依赖上下文、严格版本解析 `parse_expected_revision`、不可伪造 `operator()` 提取及 SSE 保活与 `_BG_TASKS` 护航器，文件：`src/report_agent/api/common.py`（2.0 人天）
- [X] T005 [P] 实现全资源 DTO 双向映射、正文引用扫描 `body_usage` 及具备历史破损字段兜底能力的 `detail_view` / `report_view`，文件：`src/report_agent/api/dto.py` `src/report_agent/api/run_views.py`（2.0 人天）

### 3.3 Phase 3–6: User Stories (Priority: P1–P2)

#### Phase 3: User Story 1 - 防爆破工作台会话鉴权与可轮换上游报告服务接口 (Priority: P1) 🎯 MVP

**目标**：构建具备抗算力放大、防计时侧信道与分离保护桶的登录鉴权体系，以及支持可热轮换 `X-API-Key` 的同步/流式上游报表服务接口。

**独立测试**：向 FastAPI `TestClient` 依次发起错误口令登录、未知用户喷洒、并发登录、登出吊销及轮换前后 `X-API-Key` 调用 `/api/v1/reports` 与 `/reports/stream` 完成独立验证。

- [X] T006 [US1] 实现 600k PBKDF2-HMAC-SHA256、`DUMMY_PASSWORD_HASH`、`TokenService`（`max_revoked=8192`）、分离 `_known_users` 保护桶 `LoginGuard` 与 `require_user`/`require_report_key`，文件：`src/report_agent/api/auth.py`（2.5 人天）
- [X] T007 [US1] 实现 `/api/v1/auth/login`（`_LOGIN_MAX_CONCURRENCY=4` 与直连 `_client_ip`）、`/logout`、`/me` 及锁定 `target="online"` 的 `/api/v1/reports` 与 `/reports/stream` 接口，文件：`src/report_agent/api/routes_system.py`（2.5 人天）
- [X] T008 [P] [US1] 编写并执行账号/IP 双轨锁定、未知用户防驱逐、Token 撤销容量淘汰与热轮换 `X-API-Key` 上游流式报表测试，文件：`tests/test_api_and_store_fixes.py` `tests/test_api.py`（1.5 人天）

#### Phase 4: User Story 2 - 细粒度乐观锁模板编排、沙箱实时预览与在线试运行接口 (Priority: P1)

**目标**：交付模板 CRUD、全粒度 `expected_revision` 增量编辑与正文变量联动、内存态无副作用沙箱预览、回归用例抽取及 SSE 在线试运行接口。

**独立测试**：并发提交一致与过期 `revision` 校验 `409 DRAFT_CONFLICT`，执行重命名检查正文替换安全边界，调用 `render-preview` 验证零写盘，并验证 `dryrun/stream` 与 `cases` 提取链路。

- [X] T009 [US2] 实现模板 CRUD、上下线恢复复制、跨模板字段汇总及全粒度乐观锁编辑接口（含 `_rename_body_variable`、保留名拦截、`INVALID_FIELD_EVIDENCE` 与 `FIELD_IN_USE`），文件：`src/report_agent/api/routes_templates.py`（2.5 人天）
- [X] T010 [US2] 实现内存态 `PreviewBody.fields` 驱动的 `render-preview`、`validate` 漂移检测、`diff` 差异对比、`fromRunId` 自动提取 `cases` 与 `dryrun`/`dryrun/stream` 路由，文件：`src/report_agent/api/routes_templates.py`（2.0 人天）
- [X] T011 [P] [US2] 编写并执行细粒度乐观锁冲突、变量重命名安全边界、`list+input` 拦截、内存预览及历史提取回归用例测试，文件：`tests/test_api_and_store_fixes.py` `tests/test_api.py`（1.5 人天）

#### Phase 5: User Story 3 - 技能、双协议网关契约在线拨测与提示词治理接口 (Priority: P2)

**目标**：交付纯文本 Skill 容错覆盖治理、双协议 XML/JSON 网关契约局部补丁与未落盘在线拨测（`test-call`）、系统提示词四视角治理及 API Key 在线重生成。

**独立测试**：构造损坏草稿验证 `_safe_overlay` 回退，向 `PUT /apis/{name}/draft` 提交局部 `api` 补丁，传未保存 `yamlText` 发起 `test-call` 并核对审计与 `ra_` 密钥即时生效。

- [X] T012 [US3] 实现纯文本 Skill 全生命周期治理（含损坏草稿安全回退 `_safe_overlay`）及系统提示词 `working`/`online`/`draft`/`rN` 四视角读写与发布回滚路由，文件：`src/report_agent/api/routes_resources.py`（2.0 人天）
- [X] T013 [US3] 实现双协议网关接口局部 `ApiDraftBody.api` 补丁、`validate` 脱敏 `requestPreview`、未落盘沙箱拨测 `test-call`（`_prepare_test_call_api`）及 `/settings/api-key*` 密钥轮换路由，文件：`src/report_agent/api/routes_resources.py`（2.0 人天）
- [X] T014 [P] [US3] 编写并执行双协议 XML/JSON DTO、未落盘 `test-call` 接口名一致与 Schema 校验、非 Mapping 草稿降级及 API Key 轮换集成测试，文件：`tests/test_api_routes_json.py` `tests/test_api.py`（1.5 人天）

#### Phase 6: User Story 4 - 跨版本 Diff、紧急切换、运行台账容错与 48 项配置热更新 API (Priority: P2)

**目标**：交付全局跨版本 Diff、毫秒级无冗余版本号紧急回退切换、破损运行数据容错查询大盘，以及全量 `48` 项运行期配置查询/更新/回滚/环境回同步免重启接口。

**独立测试**：对比 `GET /releases/diff`、执行带理由 `emergency-switch` 核对版本数不变、读取缺失 `templateDef` 历史运行记录并执行 `PUT /settings/runtime` 与 `rollback` 验证连接池回收。

- [X] T015 [US4] 实现发布流水列表、跨版本 `/releases/diff`、带必填原因校验的 `/releases/emergency-switch`、多维 `/runs` 检索与 `/system/overview` 大盘统计，文件：`src/report_agent/api/routes_system.py`（2.0 人天）
- [X] T016 [P] [US4] 实现 `/settings/model` 与 `48` 项 `/settings/runtime` 查询/更新/历史 `revisions`/回滚/`sync-env` 接口（联动 `apply_runtime_config` 与 `aclose_retired` 连接池回收），文件：`src/report_agent/api/routes_resources.py`（1.5 人天）

### 3.4 Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 [P] 完善并执行深度审计安全回归与运行配置热重载全量测试（涵盖反代 307/404、操作人防伪造、破损数据兜底与连接池回收），文件：`tests/test_deep_audit_fixes.py` `tests/test_runtime_config_hot_reload.py`（1.5 人天）
- [X] T018 对齐前后端全量 REST/SSE 接口路径、错误码枚举与鉴权契约，运行全量后端测试与 `ruff` 静态门禁收敛归档，文件：`docs/frontend-api-handoff.md`（1.0 人天）

### 3.5 任务详情与完成记录

#### 任务组：`T001–T002`（Phase 1：配置与热更新基座，3.0 人天）

- **关联需求**：`FR-001`、`FR-010`、`NFR-003`、`NFR-004`
- **关键变更点**：`src/report_agent/config.py`（`Settings`、`report_api_key_set()`、`normalized_root_path()`）、`src/report_agent/api/__init__.py`、`src/report_agent/store/runtime_config.py`（`_ORDERED_FIELDS` 48 项、`RuntimeConfig`、`RuntimeSnapshot`、`RuntimeConfigStore`、`0600` 原子读写与跨字段校验）。
- **验证方式与实测证据**：本轮复测全量后端测试 `uv run pytest -q` 通过（本轮基线报告 `196 passed in 51.41s`，本轮复核实测 `196 passed in 50.72s`）；静态检查 `uvx ruff@0.11.0 check src tests` 输出 `All checks passed!`。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T003–T005`（Phase 2：应用装配、公共原语与双态运行视图，6.0 人天）

- **关联需求**：`FR-001`、`FR-003`、`FR-004`、`FR-005`、`FR-009`、`FR-010`、`EX-001`、`EX-006`
- **关键变更点**：`src/report_agent/main.py`（`create_app`、`setup_logging`、`install_error_handlers`、`_SubpathPrefixMiddleware`、`_cleanup_loop`、`spa()`）、`src/report_agent/container.py`（`Container`、`apply_runtime_config`、`_gateway_signature`、`build_container`）、`src/report_agent/api/common.py`（`SSE_HEADERS`、`_BG_TASKS`、`parse_expected_revision`、`operator`、`validation_result_with_drift`、`sse_run`）、`src/report_agent/api/dto.py`、`src/report_agent/api/run_views.py`（`_fallback_field_def`、`detail_view`、`report_view`）。
- **验证方式与实测证据**：全量 `uv run pytest -q`（`196 passed in 51.41s` / 复核 `196 passed in 50.72s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全绿通过。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T006–T008`（Phase 3 / US1：三轨安全鉴权与上游 SSE 报表，6.5 人天）

- **关联需求**：`US1`、`SC-001`、`SC-003`、`FR-002`、`FR-003`、`EX-002`、`NFR-004`
- **关键变更点**：`src/report_agent/api/auth.py`（PBKDF2 600k、`DUMMY_PASSWORD_HASH`、`UserStore`、`TokenService` `max_revoked=8192`、`LoginGuard` 双轨防爆破与 `_known_users` 保护、`require_user`、`require_report_key`）、`src/report_agent/api/routes_system.py`（`_LOGIN_MAX_CONCURRENCY=4`、`_login_semaphore`、`_client_ip`、`/auth/*`、`/reports*`）、`tests/test_api_and_store_fixes.py`、`tests/test_api.py`。
- **验证方式与实测证据**：`uv run pytest -q`（`196 passed in 51.41s` / 复核 `196 passed in 50.72s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）覆盖认证限流、Token 撤销上限淘汰与动态 `X-API-Key` 报表全通过。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T009–T011`（Phase 4 / US2：模板细粒度乐观锁与试运行，6.0 人天）

- **关联需求**：`US2`、`SC-002`、`SC-005`、`FR-004`、`FR-005`、`EX-003`
- **关键变更点**：`src/report_agent/api/routes_templates.py`（全粒度乐观锁编辑、`_rename_body_variable`、`_resolve_delete_field_revision`、`INVALID_FIELD_EVIDENCE`、`FIELD_IN_USE`、`render-preview`、`/validate`、`/diff`、`/cases` `fromRunId` 自动抽取、`dryrun`/`dryrun/stream`）、`tests/test_api_and_store_fixes.py`、`tests/test_api.py`。
- **验证方式与实测证据**：`uv run pytest -q`（`196 passed in 51.41s` / 复核 `196 passed in 50.72s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全通过。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T012–T014`（Phase 5 / US3：Skill 治理、双协议拨测与提示词/密钥轮换，5.5 人天）

- **关联需求**：`US3`、`SC-002`、`SC-005`、`FR-006`、`FR-007`、`FR-008`、`EX-004`、`EX-005`
- **关键变更点**：`src/report_agent/api/routes_resources.py`（`_safe_overlay`、Skill 全周期治理、`ApiDraftBody.api` 局部补丁、`validate` 脱敏 `requestPreview`、`_prepare_test_call_api`、`test-call` 审计、系统提示词四视角治理与 `/settings/api-key*` `ra_` 重生成）、`tests/test_api_routes_json.py`、`tests/test_api.py`。
- **验证方式与实测证据**：`uv run pytest -q`（`196 passed in 51.41s` / 复核 `196 passed in 50.72s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全通过。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T015–T016`（Phase 6 / US4：版本发布、台账容错与 48 项热配置 API，3.5 人天）

- **关联需求**：`US4`、`SC-004`、`SC-005`、`FR-009`、`FR-010`、`EX-006`
- **关键变更点**：`src/report_agent/api/routes_system.py`（`/releases/diff`、`/releases/emergency-switch`、`/runs` 多维分页、`/system/overview`）、`src/report_agent/api/routes_resources.py`（`/settings/model`、48 项 `/settings/runtime`、`/revisions`、`/rollback`、`/sync-env`、`_apply_runtime_mutation` 与 `aclose_retired()`）。
- **验证方式与实测证据**：`uv run pytest -q`（`196 passed in 51.41s` / 复核 `196 passed in 50.72s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）全通过。
- **状态与阻塞**：已完成；无阻塞项。

#### 任务组：`T017–T018`（Phase 7：深度审计回归与契约归档收口，2.5 人天）

- **关联需求**：`SC-001`~`SC-005`、`FR-001`~`FR-010`、`NFR-001`~`NFR-005`、`EX-001`~`EX-006`
- **关键变更点**：`tests/test_deep_audit_fixes.py`、`tests/test_runtime_config_hot_reload.py`、`docs/frontend-api-handoff.md`。
- **验证方式与实测证据**：`uv run pytest -q`（全量 `196 passed in 51.41s`，本轮复核 `196 passed in 50.72s`）、`uvx ruff@0.11.0 check src tests`（`All checks passed!`）。
- **状态与阻塞**：已完成；无阻塞项。

---

## 4. 子任务拆解（可选） 【补充】

> 本需求 `T001`–`T018` 共 18 项任务粒度已清晰对应单一文件组与单次验收闭环，无需额外拆解子任务。

---

## 5. 代码实现约束（仅本需求新增） 【补充】

- **并发与一致性**：严格维持 `uvicorn --workers 1`；所有写草稿与版本接口使用 `expected_revision` + `DraftStore`/`Publisher` 文件锁；`RuntimeConfigStore` 在 `Container.lock` 下执行 `0600` 原子写并在锁外异步回收 `aclose_retired()`；`sse_run` 后台协程统一挂入 `_BG_TASKS`。
- **安全与隐私边界**：口令校验统一走 `600k` PBKDF2 + `_login_semaphore(4)` + `DUMMY_PASSWORD_HASH`；`LoginGuard` 分离 `_known_users` 保护真账号；直连 IP 不盲信代理头；`/settings/runtime`、`/apis/*/validate` 预览及 `GitError` 统一脱敏；`operator(request)` 禁止信任客户端输入。
- **错误与降级语义**：统一错误结构体 `{code, message, ...}`；破损草稿 YAML 由 `_safe_overlay` 回退 `live`；破损历史运行 JSON 由 `_fallback_field_def` 与 `safe_int` 降级呈现且保留 `"0"`/`"False"`。

---

## 6. 测试任务矩阵（Test Tasks） 【核心】

| 测试编号 | 类型 | 测试场景与关注点 | 关联任务 | 测试路径 | 验证命令与结果 |
| --- | --- | --- | --- | --- | --- |
| `TT-01` | 集成测试 | 登录/登出/健康检查、模板工作台流、内存预览、`dryrun`、`reports` 与流式输出、运行大盘与破损详情 | `T001`、`T005`–`T011`、`T014`–`T015` | `tests/test_api.py` | `uv run pytest -q`（含在全量 `196 passed in 51.41s` / 复核 `50.72s`） |
| `TT-02` | 安全与修复单测 | `LoginGuard` 防驱逐与 IP 桶、`TokenService` 8192 上限淘汰、细粒度乐观锁 `409`/`INVALID_REVISION`、`list+input` 拒收、`render-preview` 内存字段 | `T004`、`T006`–`T011` | `tests/test_api_and_store_fixes.py` | `uv run pytest -q`（含在全量 `196 passed in 51.41s` / 复核 `50.72s`） |
| `TT-03` | 双协议与拨测测试 | XML/JSON API DTO、`/validate` 脱敏预览、未落盘 `test-call` 抽取与失败分支、非 Mapping YAML 草稿保护 | `T012`–`T014` | `tests/test_api_routes_json.py` | `uv run pytest -q`（含在全量 `196 passed in 51.41s` / 复核 `50.72s`） |
| `TT-04` | 深度审计安全测试 | 反代 `_SubpathPrefixMiddleware`（307 与 `/api/*` 404）、SPA 托管边界、`api-test-call` 与操作人防伪造、并发安全 | `T003`、`T007`、`T013`、`T015`、`T017` | `tests/test_deep_audit_fixes.py` | `uv run pytest -q`（含在全量 `196 passed in 51.41s` / 复核 `50.72s`） |
| `TT-05` | 热更新与连接池测试 | `48` 项 `_ORDERED_FIELDS` 跨字段校验、`0600` 持久化、回滚 `cN`、环境变量同步、`aclose_retired` 回收 | `T002`、`T003`、`T016`、`T017` | `tests/test_runtime_config_hot_reload.py` | `uv run pytest -q`（含在全量 `196 passed in 51.41s` / 复核 `50.72s`） |
| `TT-06` | 静态代码门禁 | 全量后端源码与测试集 Ruff 规则合规 | `T001`–`T018` | `src/`、`tests/` | `uvx ruff@0.11.0 check src tests`（`All checks passed!`） |

---

## 7. 发布任务清单（Release Tasks） 【核心】

| 发布编号 | 动作内容 | 前置依赖 | 验证与完成标准 | 回滚动作 | 关联任务 |
| --- | --- | --- | --- | --- | --- |
| `RT-01` | 后端全量单元测试与 Ruff 静态检查收口 | `T001`–`T018` | `uv run pytest -q`（`196 passed`）且 `uvx ruff@0.11.0 check src tests`（`All checks passed!`） | 回退后端代码提交并重建镜像 | `T017`、`T018` |
| `RT-02` | 以 `uvicorn report_agent.main:app --workers 1` 启动并校验 `/healthz`、`APP_ROOT_PATH` 与 `REPORT_API_KEYS` | `RT-01` | `/healthz` 返回 `UP`、管理端登录与上游 `X-API-Key` 拨测正常 | `emergency-switch` 切回旧资源版本或 `/settings/runtime/rollback` 回退 `cN` | `T003`、`T007`、`T015`、`T016` |

---

## 8. 可观测性与验收（Observability & Acceptance） 【补充】

### 8.1 关键过程事件、日志与审计点位

| 场景 | 载体（过程事件 / 日志 / 审计） | 关键上下文字段 | 隐私脱敏约束 |
| --- | --- | --- | --- |
| 管理端资源写操作 / 紧急切换 / API 拨测 / 热配置变更 | `DATA_DIR/audit.jsonl` | `time`、`action`（如 `api-test-call` / `emergency-switch`）、`operator`（服务端会话注入）、`detail` | 严禁写入明文 `X-API-Key`、`llmApiKey`、`gatewayAccessToken` 或用户口令 |
| 应用启动、按天滚动日志与 Git 异常拦截 | `logging` / `TimedRotatingFileHandler(backupCount=30)` | 启动 `liveRev`、`llm_model`、`gateway_mode`、`cleanup` 清理天数与内部错误摘要 | 对外 `GitError` 返回脱敏消息，不透出本地路径或凭证 |
| 上游与调试 SSE 流式运行 | `Workspace` 事件队列 / `sse_run` / `RunStore` | `runId`、`templateId`、`entry`（`"上游调用"`/`"试运行"`）、`operator`、`status`、`events` | 客户端断连后由 `_BG_TASKS` 保持写入完整，不丢运行状态 |

### 8.2 验收清单

- 全量 18 项任务均按实测 `uv run pytest -q`（`196 passed in 51.41s` / 复核 `196 passed in 50.72s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）通过验证并完成归档。
- `spec.md`、`plan.md`、`tasks.md` 三件套编号追踪完整覆盖 `US1`–`US4`、`FR-001`–`FR-010`、`SC-001`–`SC-005`、`NFR-001`–`NFR-005` 与 `EX-001`–`EX-006`，工时之和精确等于 `33.0 人天`。
- 三类独立交付物台账清晰登记“不涉及”及依据，未创建冗余空文件或修改仓库外无关文件。

---

## 9. 阻塞与待确认（Blockers & Open Questions） 【核心】

> 当前无阻塞问题（历史 `Q-001`、`Q-002` 已在设计与审计加固阶段全部闭环关闭）。

| 编号 | 问题描述 | 关联 Spec Q-* | 影响任务 | 责任方 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `BQ-1` | 无未关闭阻塞项（`REPORT_API_KEYS` 空值回退与直连 IP 提取策略均已闭环） | `Q-001`、`Q-002` | 无 | 平台与安全团队 | 已关闭 | 维持受控开发回退加启动日志告警，防爆破仅认 `request.client.host` |

---

## 10. 变更记录（Changelog） 【补充】

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | Codex | 完成 `005-api-auth-governance` 初版 WBS 任务清单（18 项任务 / 33.0 人天） |
| 2.0 | 2026-11-16 | AiCoding | 按改造后中文 Spec-Kit 任务模板全面重构，补齐第 `0`–`10` 章、正则合规工时清单、三类交付物台账及本轮实测通过证据 |

---

## 附录 A：任务依赖简图

```text
Phase 1 (T001–T002, 3.0d)
  → Phase 2 (T003–T005, 6.0d)
      ├→ Phase 3 / US1 (T006–T008, 6.5d) 🎯 MVP
      ├→ Phase 4 / US2 (T009–T011, 6.0d)
      ├→ Phase 5 / US3 (T012–T014, 5.5d)
      └→ Phase 6 / US4 (T015–T016, 3.5d)
          → Phase 7 (T017–T018, 2.5d)
```

## 附录 B：AI 执行提示

1. 编码前先核对 `spec.md` 第 9 节 Out of Scope 与 `plan.md` 第 1.4 节禁止修改范围。
2. 所有已勾选 `[X]` 任务均已附带真实测试与静态检查输出；后续若调整任何接口或配置字段，须同步刷新 `tests/test_api*.py`、`docs/frontend-api-handoff.md` 与 `tasks.md` 实测证据。

---

## 增量更新说明

> 本文档依据改造后中文 Spec-Kit 模板与 `/sdd-documentation` 标准维护；后续新增或重拆任务需同步刷新第 1 节映射表、第 3 章任务工时及第 10 节变更记录。
