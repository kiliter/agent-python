# 设计文档（Feature Design Spec）：文件化 Git 版本存储、乐观锁草稿叠加、异步运行账本与配置热重载底座

<!-- #Created By AiCoding(codex) -->
<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->

> **Spec Kit 使用约定**：本模板采用**单文件内联布局（inline-v1）**，研究决策、领域与存储模型、内部接口契约及验证指南全部内联维护在本文件四个锚点章节中，不另建 `research.md`、`data-model.md`、`contracts/` 或 `quickstart.md`。本需求对应三类外部独立交付物均在 `spec.md` 第 8.2 节确认为不涉及。

---

**分支**：`[002-git-store-hot-reload]` | **日期**：2026-11-16 | **规格**：`./spec.md`

**输入**：`/specs/002-git-store-hot-reload/spec.md`

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-002` |
| 需求名称 | 文件化 Git 版本存储、乐观锁草稿叠加、异步运行账本与配置热重载底座 |
| 对应需求文档 | `./spec.md` |
| 对应任务清单 | `./tasks.md` |
| 设计文档版本 | `2.0` |
| 设计人 | AiCoding(codex) |
| 核算工作量 | `33.0 人天`（与 `spec.md` / `tasks.md` 一致） |
| 状态 | 已交付归档 |

---

## 1. 设计目标与范围 【核心】

### 1.1 设计目标（What / Why）

- **PLAN-GOAL-1（零外部数据库事务级版本发布底座）**：依托 `DataLayout`、`fsutil`、`GitRepo`、`ReleaseStore` 与 `Publisher` 实现单 PVC 上的不可变版本发布、增量静态门禁、原子软链上线切换与异常完整回滚。
- **PLAN-GOAL-2（并发安全草稿箱与高速叠加视图）**：通过 `DraftStore`（`.tmp`/`.bak` 换写与乐观锁）和 `ResourceService`（四态计算、`rollback`、下线恢复与指纹缓存 `overlay()`）支撑多人编辑防覆盖与草稿试运行。
- **PLAN-GOAL-3（高吞吐运行账本与轻量用例仓储）**：通过 `RunStore` 单协程异步写队列、双向损坏自愈与 400 天 LRU 缓存，以及 `CaseStore` 512 字节头验证指纹缓存，满足高并发零撕裂落盘与毫秒级检索。
- **PLAN-GOAL-4（48 项运行配置 `0600` 热重载与单进程 CLI）**：实现版本化 `RuntimeConfigStore`、脱敏历史、启动损坏自愈、`Settings` 空白兜底及锁定 `workers=1` 的 `report-agent` CLI。

### 1.2 设计范围（Scope）

**包含：**

- `src/report_agent/store/` 下 11 个模块（`__init__.py`、`fsutil.py`、`layout.py`、`git_repo.py`、`drafts.py`、`releases.py`、`publisher.py`、`service.py`、`runs.py`、`cases.py`、`runtime_config.py`，共 4,208 行）。
- `src/report_agent/config.py`（187 行）与 `src/report_agent/cli.py`（86 行）。
- 存储、权限、异步排空、软链防御与热更新测试套件：`tests/test_store.py`、`tests/test_review_storage.py`、`tests/test_runtime_config_hot_reload.py`（共 2,053 行）。

**不包含：**

- 外部关系型数据库、Redis 锁或多进程分布式协调。
- FastAPI HTTP 路由层、鉴权会话 `UserStore`/`AuthService` 与全局异常处理挂载（`005-api-auth-governance`）。
- 智能体核心执行与 `ReloadableGatewayClient` 具体重建实现（`003`、`004`），及聊天会话分片存储 `ChatStore`（`007`）。

<a id="plan-research"></a>

### 1.3 研究与关键决策（Decision Log）

| ID | 决策点 | 备选方案 | 最终选择 | 依据与取舍理由 | 影响范围 |
| --- | --- | --- | --- | --- | --- |
| D1 | 业务资源版本与快照持久化方式 | 引入 SQLite/PostgreSQL / 内部 Git CLI + 不可变物化目录 + 软链 | `GitRepo` + `releases/rN/` + `releases/current` 原子软链接 | 免除外部 DB 运维与迁移，运维可直接 `git log`/`git show` 排障，同时热路径只读本地目录与单次 `os.readlink` | `store/git_repo.py`、`releases.py`、`publisher.py` |
| D2 | 静态门禁在增量发布中的阻断口径 | `validate_all` 任一错误全量阻断 / 仅阻断本次新增引入错误 | 计算 `validate_all(new_rs)` 与 `validate_all(base_rs)` 的 `_issue_key` 差集，仅阻断新引入 `error` | 防止单个历史遗留不兼容模板卡死其余模板/Skill/API 的线上发布 | `store/publisher.py` |
| D3 | 多文件草稿写入原子性 | 逐文件直接覆写 / `.tmp` + `.bak` 双步目录替换 | 构建 `.tmp` → 原目录替为 `.bak` → `os.replace` 替换，失败自动回切 `.bak` | 保证 `template.yaml` 与 `body.md.j2` 严格原子同步更新，清理残留旧文件且崩溃零破坏 | `store/drafts.py` |
| D4 | 高并发运行记录追加策略 | 多协程文件锁直写 `index.jsonl` / `asyncio.Queue` 单后台写协程 | 单协程 `_writer` 串行消费 + `_pending` 内存视图 + `stop()`/`cancel()` 同步 `_drain_queue` | 消除并发写盘行撕裂与阻塞主事件循环；队列未启或关停后无缝退回同步锁内写盘 | `store/runs.py` |
| D5 | 路径与恶意软链安全防御拆分 | 统一 `resolve()` 检查 / 分离 `ensure_within` 与 `ensure_entry_within` | 读写走 `ensure_within`（校验目标真实路径）；删改/替换前置清理走 `ensure_entry_within`（仅校验父目录真实路径） | 若删软链也跟随 `resolve()` 会误判无法清理恶意或悬空软链，分离后可安全 `unlink` 自身而不伤外部文件 | `store/layout.py`、`drafts.py` |
| D6 | `CaseStore.count` 性能优化与运行配置持久模型 | 全量 `yaml.load` / `os.scandir` + 512 字节头检查缓存；固定配置 / `0600` 版本化 `cN` 快照 | `os.scandir(follow_symlinks=False)` + 512 字节头指纹缓存（8192 项）；`RuntimeConfigStore` 预先 `os.fchmod(fd, 0o600)` | 将列表页用例计数降为 `stat` 级开销；热配置版本化脱敏审计并消除创建瞬间的权限裸露窗口 | `store/cases.py`、`fsutil.py`、`runtime_config.py` |

---

### 1.4 技术背景与项目结构

**语言/版本**：Python `>=3.12,<3.14`（容器 `python:3.13-slim`）+ 系统 `git` CLI

**主要依赖**：`pydantic>=2.12,<3`、`pydantic-settings>=2.6,<3`、`pyyaml>=6.0.2,<7`（优先 `CSafeLoader`）、`uvicorn[standard]>=0.32`、标准库 `asyncio`/`threading`/`tarfile`/`subprocess`

**存储**：零外部数据库，纯单 PVC 本地文件存储（`repo/`、`drafts/`、`releases/`、`runs/YYYY/MM/DD/`、`chats/`、`cases/`、`mock-gateway/`、`config/runtime/` 与 `audit.jsonl`）

**测试**：`pytest>=8.3`、`pytest-asyncio>=0.24` 与 `uvx ruff@0.11.0 check src tests`

**目标平台**：支持 POSIX `os.symlink` 与 `os.replace` 原子重命名语义的 Linux 容器（单进程 Uvicorn `workers=1`）及 macOS 本地环境

**项目类型**：后端文件存储基础设施、配置中心与 CLI 引导子系统

**约束与规模/范围**：覆盖 `src/report_agent/store/` 11 个模块与 `config.py`、`cli.py` 共 13 个核心源文件（合计 4,481 行源码）及 2,053 行专项存储/热更新测试，支撑 48 项运行期参数热重载与按日百万级运行记录检索；总工作量 `33.0 人天`（18 项任务）。

**源代码结构（真实目录落点）**：

```text
src/report_agent/
├── config.py                # Settings 环境变量模型（含 40 项非可空空白兜底，187 行）
├── cli.py                   # CLI 入口（serve workers=1、init、user add，86 行）
└── store/
    ├── __init__.py          # 存储包标识（1 行）
    ├── fsutil.py            # 原子写盘（fchmod+fsync+replace）、JSONL/审计与原子软链（246 行）
    ├── layout.py            # DataLayout、ResourceRef、正则规范、ensure_within/ensure_entry_within（195 行）
    ├── git_repo.py          # Git CLI 封装（防参数注入、tarfile archive 导出、空仓 reset，146 行）
    ├── drafts.py            # 乐观锁草稿存储（.tmp/.bak 事务换写、安全摘除，167 行）
    ├── releases.py          # ReleaseStore（LRU 8、血缘、try_live_snapshot、prune、recover，287 行）
    ├── publisher.py         # Publisher（RLock 事务发布、增量门禁、Trailer 提交与回滚，189 行）
    ├── service.py           # ResourceService（四态计算、回退、下线恢复、overlay 指纹缓存，620 行）
    ├── runs.py              # RunStore（单写协程、双向自愈、_day_cache 400、60s 统计、cleanup，720 行）
    ├── cases.py             # CaseStore（CSafeLoader、512B 头验证缓存 8192、from_payload，228 行）
    └── runtime_config.py    # 48 项配置 0600 持久化、脱敏、自愈恢复与修订回滚（1,409 行）

tests/
├── test_store.py                      # 发布回滚、切回再发布、草稿换写、RunStore/CaseStore 回归（392 行）
├── test_review_storage.py             # 0600 权限、软链逃逸、并发 stop/cancel 排空、cli init（542 行）
└── test_runtime_config_hot_reload.py  # 48 项热更新、API Key 脱敏轮换、跨字段与自愈验证（1,119 行）
```

**禁止修改范围**：

- 严禁修改 `cli.py` 中 `uvicorn.run(..., workers=1)` 单进程硬约束。
- 严禁在 `store/` 模块中直接依赖 `fastapi` HTTP 响应对象（统一抛出领域异常交由 `main.py` 全局处理器映射）。
- 严禁在源码、测试或配置文件中写入真实密钥，测试仅可在临时 `tmp_path` 数据目录下创建 `0600` 模拟凭证。

#### 文档结构（本需求）

```text
specs/002-git-store-hot-reload/
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
| 原则 I：平台零业务硬编码与声明式资源隔离 | PASS | PASS | 存储层仅按 `ResourceRef` 与目录树拓扑管理，不含任何模板/短信业务硬编码 |
| 原则 II：单智能体规划、确定性原语与强证据防幻觉 | PASS | PASS | `Publisher.publish` 强制执行 `validate_all`；`RunStore` 完整留存 `validationRounds`/`apiResults`/`events` |
| 原则 III：文件化 Git 原子发布与单进程并发安全（`workers=1`） | PASS | PASS | `cli.py` 锁定 `workers=1`；全局 `RLock`、单后台写协程、`atomic_symlink` 与 `reset_to` 保障零 DB 一致性 |
| 原则 IV–V：单文件内联设计、自动化测试隔离与 Mock 契约 | PASS | PASS | 采用 `inline-v1` 单文件布局；测试全部基于临时 `DATA_DIR` 与故障注入，无外网/DB 依赖 |
| 原则 VI–VII：安全脱敏、零硬编码凭证、事件与审计留痕 | PASS | PASS | `0700`/`0600` 先赋权后写、`to_public_dict` 脱敏、`audit.jsonl` 留痕、双层路径守卫与 SHA 校验防注入 |
| 原则 VIII–X：最小改动、代码规范、Wiki 同步及三类外部交付物确认 | PASS | PASS | `uvx ruff@0.11.0 check src tests` 与 `uv run pytest -q` 全量通过；Wiki 已同步；三类外部交付物确认为不涉及 |

### 1.6 复杂度跟踪

| 偏离或额外复杂度 | 必要性说明 | 未采用更简方案的原因 |
| --- | --- | --- |
| 无违背宪章约束；保留 2 项工程权衡：（1）单进程 `RLock` + 单协程写队列替代外部 DB/Redis | 满足单副本 PVC 零数据库轻量交付目标，避免分布式锁与 DB 迁移运维负担 | 若使用多进程文件锁，Windows/NFS/容器卷兼容复杂且无法利用进程内 `_snapshots`/`_day_cache`/`_overlay_cache` 内存加速 |
| （2）同时维护 `ensure_within` 与 `ensure_entry_within` 两套路径守卫 | 日常读写必须禁止软链逃逸；删除/覆盖清理恶意末端软链时必须避免跟随目标 | 单一 `resolve()` 校验会在删除指向外部的悬空或恶意软链时拒绝清理或伤及外部文件 |

### 1.7 Wiki 影响评估

- **结论**：不涉及新增或修改（对应架构决策与配置清单已于前序迭代完整同步至 `wiki/`，本次仅做 Spec 002 标准归档重构）。
- **受影响页面（存量对应页面只读对齐参考）**：`wiki/architecture/resource-release-and-store.md`、`wiki/decisions/adr-003-file-store-and-git-release.md`、`wiki/reference/configuration.md`、`wiki/reference/glossary.md`。
- **同步项**：无需更新 `wiki/index.md` 与 `wiki/log.md`。

### 1.8 三类独立交付物设计检查

| 独立交付物 | 涉及情况与依据 | 设计与变更摘要 | 验证与回退设计 | 关联问题 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 不新增对外集成契约（HTTP 路由与错误码归 `005`） | `tests/test_store.py` 校验内部契约 | 无 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | `cli init` 触发既有种子加载，资产清单归属 `008` | `tests/test_review_storage.py#test_cli_init` 覆盖 | 无 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 48 项参数与 `Settings` 已完整交付，不新增运维变更动作 | `tests/test_runtime_config_hot_reload.py` 校验 | 无 |

---

## 2. 需求映射（Traceability） 【核心】

| 规格编号 | 类型 | 需求摘要 | 设计章节映射 | 后续任务映射 |
| --- | --- | --- | --- | --- |
| `US1` / `SC-001`、`SC-002` | 用户故事 / 成功标准 | 内部 Git 发布、增量门禁、软链原子切换/回退与淘汰快照重建 | 第 3.1、5.1、6.1、6.2 节 | `T001`、`T003`–`T008` |
| `US2` / `SC-001`、`SC-005` | 用户故事 / 成功标准 | 乐观锁草稿存储 `.tmp`/`.bak` 换写、四态计算、`rollback` 与 `overlay()` 指纹缓存 | 第 3.1、3.2、4.1、6.1 节 | `T003`–`T004`、`T009`–`T011` |
| `US3` / `SC-003` | 用户故事 / 成功标准 | `RunStore` 单写协程与双向自愈、`CaseStore` 512B 头指纹计数缓存 | 第 3.1、4.1、6.2 节 | `T012`–`T014` |
| `US4` / `SC-004` | 用户故事 / 成功标准 | 48 项运行期配置 `0600` 持久化、脱敏回滚、自愈恢复与单进程 CLI | 第 3.1、4.1、7、9 章 | `T002`、`T015`–`T016` |
| `FR-001`–`FR-003` | 功能需求 | `DataLayout`、`ResourceRef`、`fsutil` 原子写盘、双层路径守卫与 `GitRepo` | 第 3.1、4.1、7 章 | `T001`、`T003`–`T005` |
| `FR-004`–`FR-005` | 功能需求 | `ReleaseStore`、`Publisher`、`DraftStore` 与 `ResourceService` | 第 3.1、3.2、5.1、6.1 节 | `T006`–`T011` |
| `FR-006`–`FR-007` | 功能需求 | `RunStore` 异步队列/统计/清理与 `CaseStore` 轻量扫描/兼容映射 | 第 4.1、6.2 节 | `T012`–`T014` |
| `FR-008`–`FR-010` | 功能需求 | `RuntimeConfig`（48 项）、`RuntimeConfigStore`（`0600`）、`Settings` 与 `cli.py` | 第 4.1、7、9 章 | `T002`、`T015`–`T016` |
| `NFR-001`–`NFR-006` | 非功能需求 | 零硬编码、门禁联动、单进程原子并发、安全防线、`audit.jsonl` 审计与性能边界 | 第 7、10、11 章 | `T003`–`T005`、`T017`–`T018` |
| `EX-001`–`EX-006` | 异常边界 | 末端软链清理、Git 空仓回滚、空环境变量兜底、`0600` 权限窗口、`cli init` 循环、`RunStore` 双向恢复 | 第 6.2、7、9 章 | `T002`、`T004`–`T005`、`T008`、`T011`、`T014`、`T016`–`T017` |

---

<a id="plan-data-model"></a>

## 3. 核心领域模型（Domain Model） 【核心】

### 3.1 领域对象清单

| 对象 / 类 | 所在文件 | 职责与核心属性 | 关键不变量（Invariant） |
| --- | --- | --- | --- |
| `DataLayout` / `ResourceRef` | `src/report_agent/store/layout.py` | PVC 九大目录定位与资源寻址凭证（`kind`、`key`、`tree_path()`） | `key` 严格符合对应白名单正则；`release_dir`/`draft_dir` 经过 `ensure_within` 守卫 |
| `GitRepo` / `NameStatus` | `src/report_agent/store/git_repo.py` | 内部 Git CLI 封装；环境变量注入提交身份，`diff` 行模型（`status`, `path`） | 提交 SHA 必须匹配 `_COMMIT_RE`；`show` 禁绝对路径/`..`/NUL；`export` 启用 `filter="data"` |
| `ReleaseStore` | `src/report_agent/store/releases.py` | 不可变发布版本索引、LRU 快照读（8 项）、`lineage` 血缘与 `ensure_materialized` 重建 | 线上指针只通过 `atomic_symlink` 替换；`prune` 始终保留 `live_rev` 与最近 `keep` 个快照 |
| `Publisher` / `Change` / `PublishResult` | `src/report_agent/store/publisher.py` | 在 `RLock` 内完成增量构建、`validate_all` 差集拦截、`trees_equal` 去重、Git 提交与回滚 | 必须以实际 `live_rev` 为基准；任意阶段失败回滚索引/目录/`repo.reset_to` 且保留草稿 |
| `DraftStore` / `DraftConflict` | `src/report_agent/store/drafts.py` | 草稿目录原子换写、`.meta.json` 维护（`baseRev`, `revision`）与安全删除 | 校验 `expected_revision`；禁空名、`/`、`\` 与 `.meta.json`；替换失败自动回切 `.bak` |
| `ResourceService` / `ResourceState` | `src/report_agent/store/service.py` | 四态计算（`DRAFT`/`PUBLISHED`/`PUBLISHED_DRAFT`/`OFFLINE`）、`rollback`、下线/恢复与 `overlay()` | 增量校验及 `overlay()` 共享指纹缓存 `(live_rev, seq, fp)` 并返回浅拷贝 |
| `RunStore` | `src/report_agent/store/runs.py` | 异步单写队列账本、`new_run_id`、`_pending`、`_day_cache`（400 天）、`window_stats` 与 `cleanup` | `_writer` 退出或取消时同步 `_drain_queue`；详情缺失由摘要降级构造 `recoveredFromIndex: True` |
| `CaseDef` / `CaseStore` | `src/report_agent/store/cases.py` | 回归用例实体与仓储（`CSafeLoader`、512B 头验证缓存 `_valid_cache` 8192 项、`from_payload`） | 静默过滤软链接与坏 YAML；`from_payload` 自动映射英文键到中文 `inputs` |
| `RuntimeConfig` / `RuntimeSnapshot` / `RuntimeConfigStore` | `src/report_agent/store/runtime_config.py` | 48 项不可变配置、`cN` 修订快照、脱敏导出、`bootstrap_or_load` 自愈与 `update`/`rollback` | 存储目录 `0700`、文件 `0600`；未显式 `clear_*` 时保护既有密钥；跨字段约束强制阻断 |
| `Settings` | `src/report_agent/config.py` | 启动环境变量模型与空白标量默认兜底（`_NON_NULLABLE_SCALAR_FIELDS` 40 项） | 保留 4 项可空字段为 `None`；规范化 `app_root_path` 与 `report_api_keys` |

### 3.2 资源四态流转与状态机

```text
  [新建草稿] ──(save_*)──▶ DRAFT ──(publish_draft)──▶ PUBLISHED
                             ▲                           │
                             │ (offline 后 restore/编辑) │ (再次 save_*)
                             │                           ▼
                          OFFLINE ◀──(offline_template)── PUBLISHED / PUBLISHED_DRAFT
```

- **四态计算规则**（`ResourceService.state`）：线上存在且未下线时，有草稿为 `PUBLISHED_DRAFT`，无草稿为 `PUBLISHED`；线上存在且已下线时，有草稿为 `DRAFT`，无草稿为 `OFFLINE`；线上不存在且有草稿为 `DRAFT`；两者皆无（非 `system-prompt`）抛 `ResourceNotFound`。

---

## 4. 数据与存储设计（本需求范围） 【核心】

### 4.1 存储与缓存对象概览

| 对象/路径 | 变更类型 | 数据格式与字段要点 | 并发/清理/恢复策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `DATA_DIR/repo/` | 持久化仓库 | Git 工作区与提交历史（Trailer：`Release`, `Base`, `Operator`, `Note`） | `Publisher.lock`（`RLock`）串行化；异常执行 `reset_to` 回滚 | `FR-003`、`FR-004` |
| `DATA_DIR/releases/` | 持久化快照区 | `index.jsonl`、只读快照 `rN/`（含 `.release.json`）、相对软链 `current -> rN` | `_entries_sig` 指纹缓存；`_snapshots` LRU 上限 `8`；`prune` 保留最近 `keep`（默认 `50`）+ `live_rev` | `FR-004` |
| `DATA_DIR/drafts/<kind>/<key>/` | 持久化草稿 | 资源文件 + `.meta.json`（`revision`, `baseRev`, `createdAt/By`, `updatedAt/By`, `action`） | `.tmp`/`.bak` 双步替换 + 乐观锁；`ResourceService._overlay_cache` 按 `(live_rev, seq, fp)` 失效 | `FR-005` |
| `DATA_DIR/runs/YYYY/MM/DD/` | 按日运行账本 | `index.jsonl` + `<runId>.json` | `asyncio.Queue` 单写者 + `_pending` + `_day_cache`（400 天 LRU）+ `stats_7d`（60s TTL）；`cleanup` 清空父目录 | `FR-006` |
| `DATA_DIR/cases/<tid>/<cid>.yaml` | 持久化用例 | YAML 映射文件（`id`, `inputs`, `documentText`, `expectedValues`, `lastResult` 等） | `os.scandir` + `_valid_cache`（上限 8192）；不随发布回滚 | `FR-007` |
| `DATA_DIR/config/runtime/` | 受限配置仓 | `current.json`、`index.jsonl`、`revisions/cN.json`（含 48 项配置） | 目录 `0700`、文件 `0600`；`_public_cfg_cache` 脱敏缓存；损坏倒序自愈 | `FR-008`、`FR-009` |
| `DATA_DIR/audit.jsonl` | 只追加审计日志 | 单行紧凑 JSON（`time`, `action`, `operator`, 及变更明细） | `append_audit` + `fsync` 写入，读取时容错跳过坏行 | `FR-002`、`FR-004`、`FR-009` |

---

<a id="plan-contracts"></a>

## 5. 接口与契约设计（API / Tools / Events） 【核心】

> 本需求不直接定义 HTTP REST 路由（由 `005` 暴露并经 `main.py` 转换异常状态码）；以下列出供上层路由、`Container` 与 CLI 调用的核心服务与命令行契约：

### 5.1 接口与契约清单

| 契约编号 | 类型 | 名称 / Path | 方向 | 关键入参 / 载荷 | 关键出参 / 响应 / 事件 | 鉴权与幂等 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `API-1` | 内部服务 | `Publisher.publish` / `emergency_switch` | 内部调用 | `changes: list[Change]`, `operator`, `type_label`, `summary`, `note` / `rev`, `reason` | `PublishResult(entry, warnings)` / `None`（写入 `audit.jsonl`） | `RLock` 串行；同内容 `NothingToPublish` | `FR-004` |
| `API-2` | 内部服务 | `ResourceService.save_*` / `publish_draft` / `rollback` / `overlay` | 内部调用 | `expected_revision`, `operator`, `target_rev`, `mode` | `.meta.json`、`PublishResult`、浅拷贝 `ResourceSet` | 乐观锁冲突抛 `DraftConflict` | `FR-005` |
| `API-3` | 内部仓储 | `RunStore.start` / `stop` / `submit` / `get` / `list` / `stats_7d` / `cleanup` | 内部调用 | `summary`, `detail`, `run_id`, `date_from/to`, `keep_days` | 降级或规范详单、分页列表、统计聚合字典 | 单写协程顺序化；实时合并 `_pending` | `FR-006` |
| `API-4` | 内部配置仓 | `RuntimeConfigStore.bootstrap_or_load` / `update` / `rollback` / `sync_from_env` / `revisions` | 内部调用 | `Settings`、`patch`、`clear_*`、`target_rev`、`operator` | `RuntimeSnapshot`、`(snap, changed)`、脱敏历史列表 | 无键值变化幂等跳过；写 `0600` + 审计 | `FR-008`、`FR-009` |
| `API-5` | CLI 入口 | `report-agent {serve, init, user add}`（`cli.py#main`） | 命令行 | `--host`, `--port`, `--username`, `--display-name`, `--role`, `--password` | 退出码 `0`/`1`/`2` 与控制台摘要输出 | `serve` 强制 `workers=1`；口令至少 8 位 | `FR-010` |

### 5.2 关键契约说明与错误语义

- **向 `main.py` 暴露的异常映射契约**：`InvalidResource` / `RuntimeConfigValidationError` → HTTP `400 INVALID_RESOURCE`；`ResourceNotFound` / `ReleaseNotFound` → HTTP `404`；`NothingToPublish` → HTTP `409 NOTHING_TO_PUBLISH`；`DraftConflict` → HTTP `409 DRAFT_CONFLICT`（附 `current` 元信息）；`PublishError` → HTTP `422 PUBLISH_BLOCKED`（附序列化后的 `issues`）；`GitError` → HTTP `500`（后端记录详错日志）。
- **无差异与键保护幂等语义**：`Publisher.publish` 与 `ResourceService.publish_draft` 在实际内容相同（或解析等价 `_same_as_online`）时拒绝生成空版本并抛 `NothingToPublish`；`RuntimeConfigStore.update` 与 `sync_from_env` 在 `diff_keys` 为空时直接返回 `(current, False)`，不浪费修订号也不写冗余审计。

---

## 6. 业务流程设计（可直接编码） 【核心】

### 6.1 核心执行流程

```text
流程 A（事务型资源发布 Publisher.publish）：
1. 获取进程级 self.lock（RLock），读取当前线上指针 base_rev = releases.live_rev()（即使此前经过紧急回切）
2. 确保 base_rev 目录已物化（ensure_materialized），克隆基准目录树至 releases/.build-rN（忽略 .release.json）
3. 依次应用各 Change（draft 草稿、tree 回退快照、offline 标记或 delete 摘除）
4. 加载构建目录执行 validate_all(new_rs)，与 base_rs 的 _issue_key 差集对比：有新增 error 则清理 .build 并抛 PublishError
5. 调用 trees_equal 对比无实际内容变化则抛 NothingToPublish
6. 同步构建目录至 repo/ 工作区并 commit_all（写入 Release/Base/Operator/Note Trailer）
7. releases.add 写入 .release.json、os.replace 移入 releases/rN、追加 index.jsonl 并 atomic_symlink 切换 current
8. 若步骤 6–7 任一步发生异常，自动恢复 index.jsonl、清理残余目录并调用 repo.reset_to(prev_head) 回滚；保留用户草稿
9. 成功后删除已消费草稿、记入 audit.jsonl 并调用 prune() 清理超限历史物化目录

流程 B（RunStore 异步写入与启动自愈）：
1. start() 调用 _recover_all_orphans 扫描未写入 index.jsonl 的孤儿 <runId>.json 补全索引并预热 _day_cache
2. 创建 asyncio.Queue 与后台 _writer 协程；submit() 将记录放入 _pending 并入队，未启动时退回 _write 同步写入
3. _writer 通过 asyncio.to_thread(_write) 顺序写盘并在 finally 中弹出 _pending、刷新 _day_cache
4. stop() 投递 None 哨兵、等待 _writer 结束并执行 _drain_queue 确保零记录遗漏
```

### 6.2 并发控制与异常降级策略

| 异常/并发场景 | 检测时机 | 处理策略 | 是否中断主流程 | 可观测性输出 |
| --- | --- | --- | --- | --- |
| 发布过程中替换索引或软链失败 | `Publisher.publish` / `ReleaseStore.add` | 恢复 `prev_index`、清理未提交版本目录并调用 `repo.reset_to(prev_head)`（支持空仓归 `None`） | 是（抛出原异常） | `log.exception` 告警，线上版本与草稿零受损 |
| 草稿覆盖瞬间 `os.replace` 失败 | `DraftStore.write` | 自动将 `.bak` 还原回目标目录并清理 `.tmp`，保持原草稿修订号与文件完整 | 是（抛出原异常） | 保留原 `.meta.json` 状态 |
| 运行配置 `current.json` 缺失或损坏 | `RuntimeConfigStore.bootstrap_or_load` | 倒序扫描 `index.jsonl` 与 `revisions/c*.json` 找到最近合法快照恢复重建 `current.json` | 否（自动自愈生效） | `log.warning` 记录恢复版本号 `rev` |
| 运行详情 `<runId>.json` 损毁或缺失 | `RunStore.get` | 从当日 `index.jsonl` 摘要调用 `_detail_from_summary` 构造降级详单并标注 `recoveredFromIndex: True` | 否（降级可读） | `log.warning` 记录降级恢复的 `runId` |
| 草稿修改/删除/发布与 `overlay()` 并发 | `ResourceService.overlay()` | 锁外扫描指纹，写入缓存前在 `_overlay_lock` 内双重校验 `_draft_mutation_seq` 与 `live_rev` | 否 | 缓存失效或命中均返回安全浅拷贝 |

---

## 7. 权限与安全控制（本需求范围） 【补充】

| 控制点 | 适用角色/调用方 | 校验机制与边界 |
| --- | --- | --- |
| 路径穿越与软链双层边界 | 所有磁盘存储类（`layout.py` / `drafts.py` / `cases.py`） | 标识正则拦截 + `ensure_within`（验证 `resolve()` 防逃逸读写）+ `ensure_entry_within`（防删除误伤外部目标） |
| 敏感运行配置权限与脱敏 | `RuntimeConfigStore`（`runtime_config.py`） | 目录 `0700`、文件 `0600`（`mkstemp` 后先 `os.fchmod` 再写字节）；`to_public_dict` 与 `index.jsonl` 严禁存明文密钥 |
| Git 子进程防注入 | `GitRepo`（`git_repo.py`） | `_COMMIT_RE`（`7~64` 位 hex）阻断参数注入；`show` 拦截绝对路径/`..`/NUL；`tarfile` 使用 `filter="data"` 解压 |
| 操作人不可伪造审计与账号密码 | `Publisher` / `RuntimeConfigStore` / `cli user add` | 所有写入审计直接采用服务端认证 `operator`；`cli user add` 强制口令不少于 8 位并交由 `UserStore` 哈希持久化 |

---

## 8. 前端 / 交互设计（如适用） 【补充】

> 本需求不涉及前端页面或交互变更（前端资源四态图标展示、配置表单与历史版本弹窗归属 `006-vue-workbench-ide`，后端接口适配归属 `005-api-auth-governance`）。

---

## 9. 配置与热更新开关 【补充】

> 本需求核心交付即包含启动 `Settings`（`src/report_agent/config.py`）及受 `RuntimeConfigStore` 版本化持久管理的 **48 项** 热更新开关（`src/report_agent/store/runtime_config.py`）：

| 配置项（Env / RuntimeConfig） | 类型 | 默认值 | 是否支持热更新 | 说明 |
| --- | --- | --- | --- | --- |
| `llmBaseUrl` / `llmApiKey` / `llmModel` / `llmTemperature` / `llmMaxTokens` / `llmTimeoutS` / `llmHttpRetries` / `llmParallelToolCalls` / `llmStrictTools` / `llmToolChoiceRequired`（共 10 项） | `str`/`float`/`int`/`bool`/`None` | 默认模型连接与超时配置（`maxTokens` 等 3 项可空） | 是（`0600` 版本化持久化） | `llmTemperature` 限定 `0~2`、`llmHttpRetries` 限定 `0~10`；密钥支持脱敏留空保留与显式 `clear_llm_api_key` |
| `agentOutputMode` / `agentNativeStrict` / `agentOutputRetries` / `agentToolRetries` / `agentRequestLimit` / `agentToolCallsLimit` / `agentRunTimeoutS` / `agentMaxConcurrentRuns` / `agentPreviewRows` / `agentQueryDefaultLimit` / `agentQueryMaxLimit` / `agentMaxPeriodMonths`（共 12 项） | 枚举/`bool`/`int`/`float` | `tool`、`True`、`3`、`2`、`25`、`120`、`600.0`、`8`、`10`、`20`、`100`、`36` | 是（`0600` 版本化持久化） | 强制跨字段校验 `agentQueryDefaultLimit <= agentQueryMaxLimit` 及各上下界 |
| `gatewayMode` / `gatewayUrl` / `gatewayAppId` / `gatewayAccessToken` / `gatewayXmlStyle` / `gatewayConnectTimeoutS` / `gatewayMaxConcurrency`（共 7 项） | 枚举/`str`/`float`/`int` | `mock`、`""`、`java`、`5.0`、`32` | 是（`0600` 版本化持久化） | `gatewayMode == "live"` 时强校验 `gatewayUrl` 非空合法；密钥支持脱敏保护与 `clear_*` |
| `reportApiKeys`、`releasesKeep`、`runsKeepDays`（共 3 项） | `str` / `int` | `""`、`50`、`90` | 是（`0600` 版本化持久化） | `reportApiKeys` 脱敏展示且禁止含空白/控制字符；`releasesKeep` `1~500`；`runsKeepDays` `0~3650` |
| `chatMaxDocChars` / `chatMaxHistoryMessages` / `chatMaxRunCards` / `chatMaxMarkdownPreviewChars` / `chatCompactTriggerMessages` / `chatCompactKeepRecent` / `chatManualCompactKeepRecent` / `chatManualCompactMinSlice` / `chatMaxMemorySummaryChars` / `chatMaxSummaryMsgChars` / `chatRequestLimit` / `chatToolCallsLimit` / `chatTimeoutS` / `chatSummaryRequestLimit` / `chatSummaryToolCallsLimit` / `chatSummaryTimeoutS`（共 16 项） | `int` / `float` | `12000`/`20`/`8`/`1500`/`24`/`12`/`6`/`2`/`1200`/`800`/`8`/`16`/`120.0`/`3`/`4`/`60.0` | 是（`0600` 版本化持久化） | 强制跨字段校验 `chatCompactTriggerMessages > chatCompactKeepRecent` |
| `DATA_DIR`、`SEED_ON_EMPTY`、`ADMIN_TOKEN_SECRET`、`ADMIN_TOKEN_TTL_S`、`ADMIN_COOKIE_SECURE`、`ADMIN_BOOTSTRAP_PASSWORD`、`LOG_LEVEL`、`LOG_DIR`、`FRONTEND_DIST`、`APP_ROOT_PATH`、`FORWARDED_ALLOW_IPS`（启动级 `Settings`） | `Path`/`bool`/`SecretStr`/`str`/`int` | `./data`、`True`、`None`、`43200`、`False`、`None`、`INFO`、`None`、`None`、`""`、`127.0.0.1` | 否（仅启动生效） | 40 项非可空标量字段配置空白或 `None` 时自动由 `_fallback_blank_non_nullable_scalars` 回退至 `Field` 默认值 |

---

## 10. 测试设计（Test Strategy） 【核心】

### 10.1 测试范围与分层策略

| 测试类型 | 覆盖范围 | 桩/隔离策略 | 重点验证场景 |
| --- | --- | --- | --- |
| 单元测试 | `fsutil.py`、`layout.py`、`git_repo.py`、`drafts.py`、`releases.py`、`publisher.py`、`cases.py` | 独立 `tmp_path` 临时目录、`monkeypatch` 注入 IO/软链失败 | 原子写 `0600` 权限、路径与末端软链穿越、`os.replace` 回切 `.bak`、空仓 `reset_to(None)`、`prune` 后 Git 重建、`CaseStore` 坏文件隔离 |
| 并发与集成测试 | `RunStore`、`ResourceService`、`RuntimeConfigStore`、`Settings`、`cli.py` 与容器热生效联调 | 真实临时 Git 仓库 + 多协程并发模拟 + 注入故障环境变量 | `stop()`/`cancel()` 无损排空、孤儿/详情双向恢复、`overlay` 缓存失效、48 项配置跨字段校验、`current.json` 损坏自愈、脱敏轮换与 `cli init` |

### 10.2 回归范围

- 全量测试套件必须持续通过（`uv run pytest -q`），同时保证上层依赖消费者测试（`tests/test_api.py`、`tests/test_api_and_store_fixes.py`、`tests/test_deep_audit_fixes.py`、`tests/test_migrated_seed.py`）零回归。
- 静态检查 `uvx ruff@0.11.0 check src tests` 保持 0 错误。

<a id="plan-quickstart"></a>

### 10.5 验证指南

- **环境与前置条件**：Python `>=3.12,<3.14`、`uv` 环境与系统 `git` 命令行工具就绪，无需外部数据库与外网。
- **验证命令**：
  ```bash
  uv run pytest tests/test_store.py tests/test_review_storage.py tests/test_runtime_config_hot_reload.py -q
  uv run pytest -q
  uvx ruff@0.11.0 check src tests
  ```
- **预期结果**：全部测试通过（全量 `196 passed`），`ruff` 检查输出 `All checks passed!`。

---

## 11. NFR 符合性自检 【核心】

| 自检主题 | 宪章依据 | 是否涉及 | 落实位置与验证方式 |
| --- | --- | --- | --- |
| 零业务硬编码与资源隔离 | I | 是 | `store/`、`config.py`、`cli.py` 零业务硬编码，`test_store.py` 核验 |
| 强证据防幻觉与确定性计算 | II | 是（发布前置门禁联动） | `Publisher.publish` 调 `validate_all`；`RunStore` 完整留存运行证据记录 |
| 文件化存储与 `workers=1` 并发安全 | III | 是 | `cli.py` 锁定 `workers=1`；`RLock` + 单协程队列 + `atomic_symlink`，`test_review_storage.py` 验证 |
| 安全编码、脱敏与零凭据硬编码 | VI | 是 | `0700`/`0600` 写入前 `fchmod`、`to_public_dict` 脱敏、`ensure_within`/`ensure_entry_within`、`GitRepo._check_commit`，全套存储/配置测试验证 |
| 过程事件、阶段日志与审计留痕 | VII | 是 | `append_audit` 写 `audit.jsonl` 记录发布/回退/配置更新；`RunStore` 保留完整 `events` 轨迹 |

---

## 12. 发布与回退计划 【核心】

- **发布前置与步骤**：存储层随应用发布前须执行 `uv run pytest -q` 与 `uvx ruff@0.11.0 check src tests`；容器首次启动自动调用 `bootstrap_or_load` 释放 `c1` 并在 `SEED_ON_EMPTY=true` 时生成 `r1`；线上部署严格锁定单进程 `workers=1` 并挂载同一持久化 PVC 至 `DATA_DIR`。
- **回退方案**：资源发布问题可通过工作台或调用 `Publisher.emergency_switch` 瞬间将 `releases/current` 软链切回历史 `rK`（即使已淘汰亦可自动由 Git 重建）；运行期参数调优问题可通过 `RuntimeConfigStore.rollback` 一键回退至任意历史修订 `cN`。

---

## 13. 实施切片与建议顺序（Implementation Slices） 【核心】

| 切片 ID | 切片名称 | 对应 Phase / 任务范围 | 目标与涉及文件 | 核算工时（人天） |
| --- | --- | --- | --- | --- |
| `S-01` | 存储拓扑、环境变量与安全 IO/Git 底座 | Phase 1–2（`T001`–`T005`） | `store/__init__.py`、`layout.py`、`config.py`、`fsutil.py`、`git_repo.py` | `9.0` |
| `S-02` | Git 原子发布与乐观锁草稿治理（P1） | Phase 3–4（`T006`–`T011`） | `releases.py`、`publisher.py`、`drafts.py`、`service.py` 及存储回滚/冲突测试 | `12.5` |
| `S-03` | 异步运行账本、用例仓与 48 项配置热重载（P2） | Phase 5–6（`T012`–`T016`） | `runs.py`、`cases.py`、`runtime_config.py`、`cli.py` 及排空/权限/热更新测试 | `9.0` |
| `S-04` | 权限加固、标记复核与全量门禁收口 | Phase 7（`T017`–`T018`） | `_chmod_safe`/注释/`#Created By AiCoding(codex)` 复核、全量 `pytest` 与 `ruff` 验收 | `2.5` |
| **合计** | **4 个实施切片** | **T001 ～ T018** | **完整交付文件化存储、发布与配置热重载底座** | **33.0** |

---

## 14. 风险清单与缓解（Risks） 【补充】

| 风险 ID | 风险描述 | 影响 | 概率 | 缓解措施 |
| --- | --- | --- | --- | --- |
| `R-1` | 生产误配置多进程启动（`workers > 1`）导致进程内 `RLock`、缓存与单写队列失效 | 高 | 低 | 在 `cli.py` 中硬编码传递 `workers=1` 并在容器启动脚本与 `.specify/memory/constitution.md` 固化单进程部署约束 |
| `R-2` | 底层容器卷不支持 POSIX `chmod` 导致 `os.fchmod` 抛出异常阻塞启动 | 中 | 低 | `fsutil._chmod_safe` 捕获 `OSError` 平滑降级，同时在支持 POSIX 的环境中确保 `0600`/`0700` 生效 |
| `R-3` | 异常断电导致 `releases/index.jsonl`、`runs/.../index.jsonl` 或 `current.json` 损坏 | 高 | 中 | `read_jsonl` 跳过坏行；`ReleaseStore.recover` 清理残留构建目录；`RunStore` 启动扫孤儿与详情降级；`RuntimeConfigStore` 倒序从 `c*.json` 自动自愈 |

---

## 15. 待确认事项（Design Open Questions） 【补充】

> 设计阶段关键技术取舍已闭环解决，无未关闭 `DQ-*`（对应 `spec.md` 第 11 节 `Q-001`、`Q-002` 均已关闭）。

| 编号 | 问题摘要 | 对应 Spec Q-* | 当前结论 | 状态 |
| --- | --- | --- | --- | --- |
| `DQ-1` | 紧急切回历史版本后再次发布时的基准树选取依据 | `Q-001` | 以当前 `releases.live_rev()` 线上软链目标为基准树而非 Git `HEAD`，防止被下线分支变更回流 | 已关闭 |
| `DQ-2` | 运行期配置 `current.json` 受损时的重启恢复策略 | `Q-002` | 优先倒序从 `index.jsonl` 与 `revisions/c*.json` 合法快照重建 `current.json`，避免热配置回退丢失 | 已关闭 |

---

## 附录 A：核心字段与状态约定（仅本需求）

- **资源四态枚举 `Status`**：`DRAFT`、`PUBLISHED`、`PUBLISHED_DRAFT`、`OFFLINE`。
- **资源发布动作 `ChangeAction`**：`publish`、`rollback`、`offline`、`delete`。
- **关键正则规范**：`TEMPLATE_KEY_RE`（`^[1-9]\d{0,9}$`）、`SKILL_ID_RE`（`^[a-z0-9][a-z0-9\-]{0,63}$`）、`API_NAME_RE`（`^[A-Za-z][A-Za-z0-9_\-]{0,63}$`）、`REV_RE`（`^r[1-9]\d{0,9}$`）、`CASE_ID_RE`（`^[A-Za-z0-9_\-]{1,40}$`）、`CONFIG_REV_RE`（`^c[1-9]\d{0,9}$`）。
- **版本查询视图关键字**：`working`、`draft`、`online`、`rN`。

## 附录 B：AI 编码与交付约束

1. 先阅读 `spec.md`、本 `plan.md` 与 `tasks.md`，严禁修改 `cli.py` 的 `workers=1` 约束与 Out of Scope 边界。
2. 所有已勾选完成 `[X]` 的任务必须附有真实命令验证输出，严禁“仅写完未验证即标完成”。

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 完成 `002-git-store-hot-reload` 初版实施设计文档 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 按改造后中文 `.specify/templates/plan-template.md`（`inline-v1` 单文件四锚点布局）重构全部 15 章并精确核对源码/测试行号、48 项配置参数与工时切片 |
