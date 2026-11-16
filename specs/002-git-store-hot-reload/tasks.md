---
description: "文件化 Git 版本存储、乐观锁草稿叠加、异步运行账本与配置热重载底座任务清单（RA-002）"
---

# 任务说明（Implementation Tasks）：文件化 Git 版本存储、乐观锁草稿叠加、异步运行账本与配置热重载底座

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：本文件承接 `spec.md` 与 `plan.md`（`<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->` 内联四章），将设计切片转化为顺序清晰、带文件路径、可独立验证的任务清单。不适用章节保留标题并注明 `本需求不涉及` 及依据；全量 18 项任务均已完成验证归档。

---

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-002` |
| 需求名称 | 文件化 Git 版本存储、乐观锁草稿叠加、异步运行账本与配置热重载底座 |
| 对应需求文档 | `./spec.md` |
| 对应设计文档 | `./plan.md` |
| tasks 版本 | `2.0` |
| 核算工作量 | `33.0 人天`（18 项任务，与 `spec.md` / `plan.md` 一致） |
| 状态 | 已完成（归档验收） |
| 负责人 | AiCoding(codex) |

---

## 0. 使用方式（给 AI 的执行指令） 【核心】

1. 按第 3 章权威任务清单顺序推进；标记 `[P]` 的任务可与同组无冲突任务并行，但不得越过前置阻塞依赖。
2. 权威复选框仅存在于第 3 章，格式为已完成标识配合 `T001 [P?] [USx?] 描述（X.X 人天）`；其他章节仅引用 `T*` 编号，不重复建复选框。
3. 每完成一项任务，在第 3.5 节同步记录实际变更文件与真实执行的验证命令及通过输出；无实测或构建证据不得勾选完成。
4. 若遇需求歧义或现状冲突，停止扩大实现并登记于第 9 节 `BQ-*`，回链 `spec.md` `Q-*`。

---

## 1. 需求到任务映射（Traceability） 【核心】

| 需求/标准 ID | 摘要 | 对应设计（Plan.md） | 映射任务 ID | 测试/验证映射 | 状态 |
| --- | --- | --- | --- | --- | --- |
| `US1` / `SC-001`、`SC-002` | 内部 Git 发布、增量门禁、软链原子切换/回退与淘汰快照重建 | 第 3.1、5.1、6.1 节 | `T001`、`T003`–`T008` | `TT-01`–`TT-03` | 已验证 |
| `US2` / `SC-001`、`SC-005` | 乐观锁草稿存储 `.tmp`/`.bak` 换写、四态计算与 `overlay()` 缓存 | 第 3.1、3.2、4.1 节 | `T003`–`T004`、`T009`–`T011` | `TT-04`、`TT-05` | 已验证 |
| `US3` / `SC-003` | `RunStore` 单写协程与双向自愈、`CaseStore` 512B 头指纹计数缓存 | 第 3.1、4.1、6.2 节 | `T012`–`T014` | `TT-06`、`TT-07` | 已验证 |
| `US4` / `SC-004` | 48 项运行期配置 `0600` 持久化、脱敏回滚、自愈恢复与单进程 CLI | 第 3.1、4.1、7、9 章 | `T002`、`T015`–`T016` | `TT-08`、`TT-09` | 已验证 |
| `FR-001`–`FR-003` | `DataLayout`、`ResourceRef`、`fsutil` 原子写盘、双层守卫与 `GitRepo` | 第 3.1、4.1、7 章 | `T001`、`T003`–`T005` | `TT-01`、`TT-02` | 已验证 |
| `FR-004`–`FR-005` | `ReleaseStore`、`Publisher`、`DraftStore` 与 `ResourceService` | 第 3.1、3.2、5.1 节 | `T006`–`T011` | `TT-03`–`TT-05` | 已验证 |
| `FR-006`–`FR-007` | `RunStore` 异步队列/统计/清理与 `CaseStore` 轻量扫描/兼容映射 | 第 4.1、6.2 节 | `T012`–`T014` | `TT-06`、`TT-07` | 已验证 |
| `FR-008`–`FR-010` | `RuntimeConfig`（48 项）、`RuntimeConfigStore`（`0600`）、`Settings` 与 `cli.py` | 第 4.1、7、9 章 | `T002`、`T015`–`T016` | `TT-08`、`TT-09` | 已验证 |
| `NFR-001`–`NFR-006` | 零硬编码、门禁联动、单进程并发安全、防注入脱敏、`audit.jsonl` 与性能边界 | 第 7、10、11 章 | `T003`–`T005`、`T017`–`T018` | `TT-01`、`TT-08`、`TT-10` | 已验证 |
| `EX-001`–`EX-006` | 末端软链清理、Git 空仓回滚、空环境变量兜底、`0600` 权限窗口、`cli init`、双向恢复 | 第 6.2、7、9 章 | `T002`、`T004`–`T005`、`T008`、`T011`、`T014`、`T016`–`T017` | `TT-01`、`TT-06`、`TT-08`、`TT-09` | 已验证 |

### 1.1 三类独立交付物维护台账

| 独立交付物 | 涉及情况与依据 | 关联任务 | 维护状态 | 验证结果 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；见 `spec.md` 第 8.2 节） | 不生成 | 不生成 | 与 `spec.md` 第 8.2 节及 `plan.md` 第 1.8 节一致 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；见 `spec.md` 第 8.2 节） | 不生成 | 不生成 | 生产种子归属 `008` 与 `src/report_agent/seed/` |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；见 `spec.md` 第 8.2 节） | 不生成 | 不生成 | 无新增运维变更单 |

---

## 2. 里程碑与切分策略（Milestones） 【补充】

| 阶段 / Milestone | 目标 | 任务范围 | 阶段工时（人天） | 验收定义 |
| --- | --- | --- | --- | --- |
| Phase 1: 准备 | 初始化存储包布局 `DataLayout` 与空白兜底 `Settings` 基座 | `T001`–`T002` | `3.0` | 九大子目录布局与 `Settings` 就绪 |
| Phase 2: 基础前置 | 建设原子 IO/`0600` 工具、双层路径守卫及安全 `GitRepo` 封装 | `T003`–`T005` | `6.0` | 原子写、防逃逸与空仓回滚原语就绪 |
| Phase 3: 用户故事 1（P1） | 交付不可变快照仓 `ReleaseStore` 与事务型发布器 `Publisher` | `T006`–`T008` | `6.5` | 增量发布、切回基准、回滚与重建测试通过 |
| Phase 4: 用户故事 2（P1） | 交付乐观锁草稿 `DraftStore` 与四态叠加服务 `ResourceService` | `T009`–`T011` | `6.0` | 修订冲突、`.bak` 恢复与 `overlay` 缓存通过 |
| Phase 5: 用户故事 3（P2） | 交付单写协程 `RunStore` 与高速回归用例仓储 `CaseStore` | `T012`–`T014` | `5.5` | 异步排空、双向恢复与头部计数缓存通过 |
| Phase 6: 用户故事 4（P2） | 交付 48 项配置 `0600` 仓 `RuntimeConfigStore` 与单进程 `cli.py` | `T015`–`T016` | `3.5` | 权限、脱敏、自愈回滚与 `cli init` 测试通过 |
| Phase 7: 收尾阶段 | 权限/注释标记核对、全量 `pytest` 回归与 `ruff` 静态检查 | `T017`–`T018` | `2.5` | 全量 `pytest` 与 `ruff` 零告警通过 |

### 2.1 依赖与交付顺序

- **阶段依赖**：`Phase 1`（准备）→ `Phase 2`（基础前置，阻塞所有存储组件）→ `Phase 3`（`US1` 发布主干）→ `Phase 4`（`US2` 草稿与叠加服务）与 `Phase 5`（`US3` 独立日志与用例仓储）→ `Phase 6`（`US4` 配置热更新与 CLI）→ `Phase 7`（加固与收口门禁）。
- **并行机会**：`T004`（`layout.py` 安全边界）与 `T005`（`git_repo.py` 命令封装）可与 `T003`（`fsutil.py`）并行；`US3` 的 `RunStore`（`T012`）与 `CaseStore`（`T013`）互相独立可并行开发；`T014` 与 `T016` 测试可同步并行验证。

---

## 3. 任务清单（按执行顺序） 【核心】

### 3.1 Phase 1: Setup (Shared Infrastructure)

- [X] T001 初始化存储包标识与 PVC 标准目录布局管理器 `DataLayout`（涵盖 `repo/`、`drafts/`、`releases/`、`runs/`、`chats/`、`cases/`、`mock-gateway/`、`config/` 与 `audit.jsonl`），文件：`src/report_agent/store/__init__.py`、`src/report_agent/store/layout.py`（1.5 人天）
- [X] T002 [P] 实现基于 `pydantic-settings` 的 `Settings` 模型、`_NON_NULLABLE_SCALAR_FIELDS`（40 项）空白默认兜底 `_fallback_blank_non_nullable_scalars` 及 `normalized_root_path` / `report_api_key_set`，文件：`src/report_agent/config.py`（1.5 人天）

### 3.2 Phase 2: Foundational (Blocking Prerequisites)

- [X] T003 实现临时文件 `os.fchmod` + `fsync` + `os.replace` 原子写盘（`atomic_write_bytes`、`atomic_write_text`、`write_json`）、受限权限 `append_jsonl` / `append_audit`、损坏宽容 `read_jsonl` 及原子软链替换 `atomic_symlink`，文件：`src/report_agent/store/fsutil.py`（2.0 人天）
- [X] T004 [P] 实现正则标识规范（`TEMPLATE_KEY_RE`、`SKILL_ID_RE`、`API_NAME_RE`、`REV_RE`、`CASE_ID_RE`）、`ResourceRef`、双检防软链逃逸 `ensure_within` 与安全摘除末端软链 `ensure_entry_within`，文件：`src/report_agent/store/layout.py`（2.0 人天）
- [X] T005 [P] 实现防命令注入（`_COMMIT_RE`）的受控 `GitRepo` 封装，支持环境变量身份注入、`show` 路径穿越拦截、`git archive` 提取导出（`filter="data"`）及兼容未诞生分支的回滚 `reset_to`，文件：`src/report_agent/store/git_repo.py`（2.0 人天）

### 3.3 Phase 3–6: User Stories (US1–US4)

#### Phase 3: User Story 1 - 零外部数据库的内部 Git 版本库、增量门禁发布与 releases/current 原子切换/回退 (Priority: P1)

**目标**：实现基于内部 Git 与原子软链的事务型版本发布、增量静态门禁与历史版本零停机切换/恢复。

**独立测试**：独立驱动 `ReleaseStore` 与 `Publisher` 完成版本发布、增量门禁拦截、软链切换异常回滚、紧急回切后再发布与淘汰快照 Git 重建。

- [X] T006 [US1] 实现 `ReleaseStore`，提供 `(mtime_ns, size)` 缓存索引、LRU 快照缓存（上限 8）、`try_live_snapshot` 无重 IO 快路径、`read_file_at`、基于 `git archive` 的 `ensure_materialized`、`lineage`、`prune` 与启动修复 `recover`，文件：`src/report_agent/store/releases.py`（2.5 人天）
- [X] T007 [US1] 实现 `Publisher`，在 `RLock` 内完成基于 `live_rev` 线上基准克隆、`validate_all` 增量阻断（`_issue_key`）、`trees_equal` 无变更拒绝 `NothingToPublish`、Git Trailer 提交、原子切换、异常全量回滚与 `emergency_switch`，文件：`src/report_agent/store/publisher.py`（2.5 人天）
- [X] T008 [P] [US1] 编写并执行增量门禁拦截、紧急回切后发布基线验证、软链切换异常回滚、空仓 `reset_to(None)`、`prune` 快照从 Git 重建及路径穿越测试，文件：`tests/test_store.py`、`tests/test_review_storage.py`（1.5 人天）

#### Phase 4: User Story 2 - 多维护人员并发安全的草稿箱乐观锁（revision）、基线漂移检测（baseRev）与 overlay 指纹缓存 (Priority: P1)

**目标**：实现安全的多人草稿乐观锁、基线版本追踪、`draft` 叠加缓存与版本回退/下线工作流。

**独立测试**：独立调用 `DraftStore` 与 `ResourceService` 验证乐观锁冲突 `DraftConflict`、`os.replace` 异常 `.bak` 恢复、`rollback` 与 `overlay()` 缓存行为。

- [X] T009 [US2] 实现 `DraftStore` 与 `DraftConflict`，提供 `.tmp`/`.bak` 双步原子换写与回滚、乐观锁 `expected_revision` 检查、非法文件名拦截、外部软链安全摘除 `delete` 及发布树写入 `apply_to_tree`，文件：`src/report_agent/store/drafts.py`（2.5 人天）
- [X] T010 [US2] 实现 `ResourceService`，封装四态计算 `state`、`baseRev` 维护、`_check_missing_draft_conflict` 冲突检测、`_same_as_online` 语义等价判断、`rollback`（`draft_only`/`publish_now`）、模板下线/恢复及 `(live_rev, seq, fp)` 指纹缓存 `overlay()`，文件：`src/report_agent/store/service.py`（2.0 人天）
- [X] T011 [P] [US2] 编写并执行草稿修订冲突、`os.replace` 故障 `.bak` 自动回滚、损坏 `.meta.json` 隔离、下线恢复及 `overlay()` 软链防护测试，文件：`tests/test_store.py`、`tests/test_review_storage.py`（1.5 人天）

#### Phase 5: User Story 3 - 高并发无损的 RunStore 单写者异步队列、按日缓存检索与回归用例库 CaseStore (Priority: P2)

**目标**：实现单协程异步无损运行记录写入、双向损坏自愈、按日指纹缓存检索及高速回归用例存储。

**独立测试**：启动 `RunStore` 验证异步投递、并发 `stop()`/任务取消排空、索引与详情双向恢复及 `CaseStore` 头部校验缓存。

- [X] T012 [US3] 实现 `RunStore`，涵盖 `new_run_id`、单写协程 `_writer`、`_pending` 实时合并、`_drain_queue` 取消排空、启动孤儿扫描 `_recover_all_orphans`、双向损坏恢复、`_day_cache`（400 天）、60 秒 TTL `window_stats` 与 `cleanup` 空目录清理，文件：`src/report_agent/store/runs.py`（2.0 人天）
- [X] T013 [US3] 实现 `CaseDef` 与 `CaseStore`，基于 `CSafeLoader`、`os.scandir`（`follow_symlinks=False`）与 512 字节头指纹缓存 `_valid_cache`（上限 8192）实现低开销 `count()`、`list()`、`copy_all()` 与前端兼容映射 `from_payload`，文件：`src/report_agent/store/cases.py`（2.0 人天）
- [X] T014 [P] [US3] 编写并执行并发停机排空、Task 取消无损落盘、双向索引降级、窗口聚合统计、过期清理及损坏 YAML/软链用例过滤测试，文件：`tests/test_store.py`、`tests/test_review_storage.py`（1.5 人天）

#### Phase 6: User Story 4 - 48 项运行期配置 0600 安全持久化、版本回滚与 CLI 初始化引导工具 (Priority: P2)

**目标**：实现 48 项运行期配置的版本化 `0600` 持久化、脱敏展示、自愈回退及单进程 CLI 引导命令。

**独立测试**：通过 `RuntimeConfigStore`、`/api/v1/settings/runtime*` 热更新测试及 `cli.main(["init"])` 验证权限、脱敏、自愈与回滚。

- [X] T015 [US4] 实现 48 项 `_ORDERED_FIELDS` 的 `RuntimeConfig`（`validate`、`apply_patch`、密钥脱敏）、`0600` 持久化仓 `RuntimeConfigStore`（`bootstrap_or_load` 自愈、`update`、`rollback`、`sync_from_env`）与 `cli.py`（`serve` `workers=1`、`init`、`user add`），文件：`src/report_agent/store/runtime_config.py`、`src/report_agent/cli.py`（2.0 人天）
- [X] T016 [P] [US4] 编写并执行 48 项配置热更新、`0600` 权限验证、密钥留空/清空保护、`current.json` 损坏自愈、跨字段边界验证与 `cli init` 测试，文件：`tests/test_runtime_config_hot_reload.py`、`tests/test_review_storage.py`（1.5 人天）

### 3.4 Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 [P] 完善 `store/`、`config.py` 与 `cli.py` 的中文注释、`#Created By AiCoding(codex)` 头部标记、非 POSIX 权限兜底 `_chmod_safe` 及审计日志结构化字段复核，文件：`src/report_agent/store/`、`src/report_agent/config.py`、`src/report_agent/cli.py`（1.5 人天）
- [X] T018 执行全量自动化测试与 Ruff 静态检查，并核验 `specs/002-git-store-hot-reload` 三件套追踪与 Wiki 一致性，覆盖：`tests/`、`src/report_agent/store/`、`src/report_agent/config.py`、`src/report_agent/cli.py`（1.0 人天）

### 3.5 任务详情与完成记录

#### 任务组：`T001`–`T005`（存储拓扑、配置兜底与原子/路径/Git 基础原语）

- **关联需求**：`FR-001`–`FR-003`、`FR-010`、`NFR-001`、`NFR-003`、`NFR-004`、`EX-001`–`EX-004`
- **关键变更点**：创建 `store/__init__.py`、`layout.py`（`DataLayout`、`ResourceRef`、5 类白名单正则与 `ensure_within`/`ensure_entry_within`）、`config.py`（40 项非可空空白兜底）、`fsutil.py`（`atomic_write_bytes` 先 `fchmod` 后落盘、`read_jsonl`、`atomic_symlink`、`append_audit`）与 `git_repo.py`（`_COMMIT_RE` 防注入与兼容未诞生分支的 `reset_to`）。
- **验证方式与实测证据**：本轮通过 `uv run pytest -q`（全量 `196 passed in 51.41s`，含 `tests/test_store.py`、`tests/test_review_storage.py`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）验证通过。
- **状态与阻塞**：已完成；无阻塞。

#### 任务组：`T006`–`T011`（P1 用户故事 `US1` & `US2`：Git 原子发布与草稿乐观锁）

- **关联需求**：`US1`、`US2`、`FR-004`、`FR-005`、`SC-001`、`SC-002`、`SC-005`、`EX-001`、`EX-002`
- **关键变更点**：完成 `releases.py`（`ReleaseStore`、`_snapshots` LRU 8、`try_live_snapshot`、`read_file_at` 快路径、`ensure_materialized`、`prune`、`recover`）、`publisher.py`（基于 `live_rev` 克隆、`validate_all` 差集阻断、`trees_equal` 去重、Git Trailer、异常完整回滚、`emergency_switch`）、`drafts.py`（`.tmp`/`.bak` 换写与 `DraftConflict`）及 `service.py`（四态、`rollback`、下线恢复与 `overlay` 指纹缓存）。
- **验证方式与实测证据**：本轮通过 `uv run pytest -q`（全量 `196 passed in 51.41s`，含 `tests/test_store.py`、`tests/test_review_storage.py`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）验证通过。
- **状态与阻塞**：已完成；无阻塞。

#### 任务组：`T012`–`T016`（P2 用户故事 `US3` & `US4`：异步运行账本、用例仓与 48 项配置热重载）

- **关联需求**：`US3`、`US4`、`FR-006`–`FR-010`、`SC-003`、`SC-004`、`EX-003`–`EX-006`
- **关键变更点**：完成 `runs.py`（`RunStore` 单协程 `_writer`、`_pending`、`_drain_queue`、启动孤儿扫描、双向降级、`_day_cache` 400 天、`stats_7d` 60s 缓存、`cleanup`）、`cases.py`（`CaseStore` `CSafeLoader`、512B 头验证缓存 8192 项、`from_payload`）、`runtime_config.py`（48 项 `RuntimeConfig`、`0600` 版本化 `RuntimeConfigStore`、脱敏、`bootstrap_or_load` 自愈与回滚）及 `cli.py`（`serve` `workers=1`、`init`、`user add`）。
- **验证方式与实测证据**：本轮通过 `uv run pytest -q`（全量 `196 passed in 51.41s`，含 `tests/test_store.py`、`tests/test_review_storage.py`、`tests/test_runtime_config_hot_reload.py`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）验证通过。
- **状态与阻塞**：已完成；无阻塞。

#### 任务组：`T017`–`T018`（收尾加固与全量门禁验收）

- **关联需求**：`NFR-001`–`NFR-006`、`SC-001`–`SC-005`
- **关键变更点**：复核 `_chmod_safe` 非 POSIX 挂载兼容、中文注释、`#Created By AiCoding(codex)` 头部标记、`audit.jsonl` 动作字段及 `specs/002-git-store-hot-reload/{spec,plan,tasks}.md` 规范闭环。
- **验证方式与实测证据**：本轮实测 `uv run pytest -q` 输出 `196 passed in 51.41s`，`uvx ruff@0.11.0 check src tests` 输出 `All checks passed!`。
- **状态与阻塞**：已完成；无阻塞。

---

## 4. 子任务拆解（可选） 【补充】

> 本需求各 `T001`–`T018` 粒度已适中（每项 1.0–2.5 人天），无需额外子任务拆解。

---

## 5. 代码实现约束（仅本需求新增） 【补充】

- **并发与一致性**：草稿、发布与运行配置统一共享进程级 `threading.RLock`，`cli.py` 强制传递 `workers=1`；`RunStore` 采用单一后台写入协程配合 `_write_lock` 写盘；`ResourceService.overlay()` 与 `ReleaseStore.snapshot()` 均通过锁保护与版本指纹校验确保内存视图一致。
- **安全与隐私边界**：`ensure_within`（读写校验 `resolve()`）与 `ensure_entry_within`（清理仅校验父目录不跟随末端软链）严格分离；`RuntimeConfigStore` 目录 `0700`、文件 `0600` 先赋权后写字节；`to_public_dict()`、`revisions()` 与 `index.jsonl` 禁止落盘或返还明文密钥；`GitRepo` 严格校验 `_COMMIT_RE` 与路径边界。
- **错误与降级语义**：统一抛出结构化领域异常（`InvalidResource`、`DraftConflict`、`PublishError`、`NothingToPublish`、`ReleaseNotFound`、`ResourceNotFound`、`RuntimeConfigValidationError`、`GitError`）由上层 `main.py` 映射为 HTTP 400/404/409/422/500；`RunStore` 与 `RuntimeConfigStore` 具备损坏文件隔离与历史降级自愈能力。

---

## 6. 测试任务矩阵（Test Tasks） 【核心】

| 测试编号 | 类型 | 测试场景与关注点 | 关联任务 | 测试路径 | 验证命令与结果 |
| --- | --- | --- | --- | --- | --- |
| `TT-01` | 安全/单元测试 | `atomic_write_bytes` 预先 `0600` 赋权、NUL/`..`/外部软链逃逸拦截与安全 `unlink` 末端软链 | `T001`、`T003`–`T004` | `tests/test_store.py`、`tests/test_review_storage.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-02` | 单元测试 | `GitRepo` 参数注入拦截、路径穿越拦截、空仓 `reset_to(None)` 与 `git archive` 解压 | `T005`、`T008` | `tests/test_store.py`、`tests/test_review_storage.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-03` | 集成测试 | `Publisher` 增量门禁拦截、切回 `r1` 后基于 `live_rev` 发布、软链失败回滚及 `prune` 后重建 | `T006`–`T008` | `tests/test_store.py`、`tests/test_review_storage.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-04` | 单元测试 | 草稿 `expected_revision` 与 `NO_DRAFT` 冲突、`os.replace` 异常 `.bak` 自动回切、损坏 `.meta.json` 隔离 | `T009`、`T011` | `tests/test_store.py`、`tests/test_review_storage.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-05` | 集成测试 | `ResourceService` 四态计算、`_same_as_online`、`rollback`（含 `targetOffline`）、下线恢复与 `overlay` 缓存 | `T010`、`T011` | `tests/test_store.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-06` | 并发/自愈测试 | `RunStore` 并发 `stop()`/Task 取消 `_drain_queue` 排空、启动孤儿补索引、详情降级与 `cleanup` | `T012`、`T014` | `tests/test_store.py`、`tests/test_review_storage.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-07` | 性能/安全测试 | `CaseStore` 512 字节头验证缓存、损坏 YAML/空文件/软链过滤与 `from_payload` 英文键映射 | `T013`、`T014` | `tests/test_store.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-08` | 安全/配置测试 | `RuntimeConfigStore` 48 项热更新、`0600` 权限、脱敏串留空与 `clear_*`、`current.json` 自愈与版本回滚 | `T015`–`T016` | `tests/test_runtime_config_hot_reload.py`、`tests/test_review_storage.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-09` | 边界/CLI 测试 | `Settings` 40 项空白环境变量默认值兜底与 `cli.main(["init"])` 在循环内外无阻塞清理网关 | `T002`、`T015`–`T016` | `tests/test_runtime_config_hot_reload.py`、`tests/test_review_storage.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-10` | 静态代码检查 | `src/` 与 `tests/` 全量 Ruff 代码规范、导入与异常风格检查 | `T017`–`T018` | `src/`、`tests/` | `uvx ruff@0.11.0 check src tests`（`All checks passed!`） |

---

## 7. 发布任务清单（Release Tasks） 【核心】

| 发布编号 | 动作内容 | 前置依赖 | 验证与完成标准 | 回滚动作 | 关联任务 |
| --- | --- | --- | --- | --- | --- |
| `RT-01` | 存储层全套单测、并发排空测试、配置热更新测试与 Ruff 静态检查收口 | `T001`–`T017` 全部完成 | `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`） | Git 回退对应源码提交 | `T018` |
| `RT-02` | 验证 `report-agent init` / `serve`（`workers=1`）初始化 PVC 目录、`c1` 与 `r1` 快照就绪 | `RT-01` | `GET /healthz` 正常响应，`config/runtime/` 权限 `0700`/`0600` | `Publisher.emergency_switch` 回退 `releases/current` 或 `RuntimeConfigStore.rollback` | `T018` |

---

## 8. 可观测性与验收（Observability & Acceptance） 【补充】

### 8.1 关键过程事件、日志与审计点位

| 场景 | 载体（过程事件 / 日志 / 审计） | 关键上下文字段 | 隐私脱敏约束 |
| --- | --- | --- | --- |
| 版本发布与紧急切换 | `DATA_DIR/audit.jsonl` & `store.publisher` 日志 | `time`、`action`（`publish`/`emergency-switch`）、`operator`、`rev`、`base`、`from`/`to`、`reason` | 操作人取自服务端认证身份，不记录敏感数据 |
| 运行配置热更新/回滚/同步 | `DATA_DIR/audit.jsonl` & `config/runtime/index.jsonl` | `action`（`runtime-config-update`/`rollback`/`sync-env`）、`operator`、`rev`、`base`、`changedKeys` | `index.jsonl` 与日志只存 `changedKeys` 键名，严禁打印密钥原值 |
| 存储恢复与损坏降级 | `store.runs` / `store.runtime_config` / `store.releases` 日志 | `runId`、`rev`、恢复条数或降级标记 `recoveredFromIndex: True` | 仅记录相对标识，脱敏处理 |

### 8.2 验收清单

- 第 3 章全量 18 项权威任务已按实测 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）完成核验。
- `spec.md`、`plan.md` 与 `tasks.md` 追踪矩阵覆盖全部 `US1`–`US4`、`FR-001`–`FR-010`、`SC-001`–`SC-005`、`NFR-001`–`NFR-006`、`EX-001`–`EX-006`，无宪章违例。
- 三类外部独立交付物确认为不涉及且未创建多余文件；既有 `wiki/` 存储与配置参考文档完整一致。

---

## 9. 阻塞与待确认（Blockers & Open Questions） 【核心】

> 当前无阻塞问题（历史 `Q-001`、`Q-002` 均已闭环关闭）。

| 编号 | 问题描述 | 关联 Spec Q-* | 影响任务 | 责任方 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `BQ-1` | 紧急切换至旧版本 `r1` 后再次发布的基准树来源选择 | `Q-001` | `T007`、`T008` | 架构与发布治理负责人 | 已关闭 | 以 `releases.live_rev()` 为基准而非 Git `HEAD`，已于 `publisher.py` 实装并通过单测验证 |
| `BQ-2` | 运行期配置 `current.json` 丢失或损坏时的启动恢复策略 | `Q-002` | `T015`、`T016` | 运维与后端核心研发 | 已关闭 | 倒序从 `index.jsonl` 与 `revisions/c*.json` 最近合法快照自愈重建，已通过故障恢复单测 |

---

## 10. 变更记录（Changelog） 【补充】

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 完成 `002-git-store-hot-reload` 18 项任务与 `33.0 人天` 初版拆分 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 按改造后中文 `.specify/templates/tasks-template.md` 规范升级全章节、锁定任务复选框正则与工时配比并补充实测 `196 passed in 51.41s` 与 `ruff` 验收记录 |

---

## 附录 A：任务依赖简图

```text
Phase 1 (Setup: T001–T002, 3.0d)
  └─▶ Phase 2 (Foundational: T003–T005, 6.0d)
        ├─▶ Phase 3 (US1 Git 原子发布与切换: T006–T008, 6.5d)
        │     └─▶ Phase 4 (US2 乐观锁草稿与叠加缓存: T009–T011, 6.0d)
        ├─▶ Phase 5 (US3 RunStore 异步队列与 CaseStore: T012–T014, 5.5d)
        └─▶ Phase 6 (US4 48 项 0600 热配置与 CLI: T015–T016, 3.5d)
              └─▶ Phase 7 (Polish 与全量测试/ruff 验收: T017–T018, 2.5d)
```

## 附录 B：AI 执行提示

1. 编码前先核对 `spec.md` 第 9 节 Out of Scope 与 `plan.md` 第 1.4 节禁止修改范围（严禁修改 `cli.py` `workers=1` 或引入外部数据库）。
2. 所有已勾选完成状态的任务均已附真实命令验证证据（`uv run pytest -q` 与 `uvx ruff@0.11.0 check src tests`），禁止无验证勾选完成。

---

## 增量更新说明

> 本文档依据改造后中文 Spec-Kit 模板与 `/sdd-documentation` 标准维护；后续新增或重拆任务需同步刷新第 1 节映射表与第 10 节变更记录。
