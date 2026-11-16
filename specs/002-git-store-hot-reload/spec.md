# 需求文档（Spec）：文件化 Git 版本存储、乐观锁草稿叠加、异步运行账本与配置热重载底座

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：产物文件名固定为 `spec.md`、`plan.md`、`tasks.md`；三类外部独立交付物按需确认，仅涉及项单独生成并建立链接，不涉及项只记录依据。本规格为已交付存量模块（子规格 002/008）按改造后中文 Spec-Kit 与 SDD 标准完成的正式归档重构，所有事实均经源码与测试证据核验。
> **项目依据**：项目宪章 `.specify/memory/constitution.md`、`AGENTS.md` 及 `wiki/index.md`。遵循先取证后写作原则，优先核对代码、测试与运行证据，不把推测写成事实。

---

**功能分支**：`[002-git-store-hot-reload]`

**创建日期**：2026-11-16

**状态**：已交付归档

**输入**：用户描述："将 Spec 002 转换为改造后中文 Spec-Kit + SDD 标准三件套（需求编号 `RA-002`，`33.0` 人天，18 项任务）" —— 负责零外部数据库的文件化存储拓扑与防路径穿越原子写入、内部 Git 版本发布与软链紧急切换、乐观锁草稿叠加缓存、单写者异步运行账本、回归用例存储及 48 项运行期配置 `0600` 热更新持久化。

## 基本信息 【核心】

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-002` |
| 需求名称 | 文件化 Git 版本存储、乐观锁草稿叠加、异步运行账本与配置热重载底座 |
| 核算工作量 | `33.0 人天`（项目总工作量 `250.0 人天`，子规格 002/008） |
| 资料与证据来源 | 1. **源码事实（可信度：高）**：`src/report_agent/store/{__init__,fsutil,layout,git_repo,drafts,releases,publisher,service,runs,cases,runtime_config}.py`（共 4,208 行）、`src/report_agent/config.py`（187 行）、`src/report_agent/cli.py`（86 行）、`src/report_agent/main.py`（异常处理映射）、`src/report_agent/container.py`（`apply_runtime_config`）<br>2. **自动化测试（可信度：高）**：`tests/test_store.py`（392 行）、`tests/test_review_storage.py`（542 行）、`tests/test_runtime_config_hot_reload.py`（1,119 行）<br>3. **架构文档与知识库（可信度：中）**：`wiki/architecture/resource-release-and-store.md`、`wiki/decisions/adr-003-file-store-and-git-release.md`、`wiki/reference/configuration.md`、`wiki/reference/glossary.md` |
| 文档版本 | `2.0` |
| 文档状态 | `已交付归档` |

---

## 1. 业务背景与目标 【核心】

### 1.1 业务背景

前代 Java 版申报系统依赖 Oracle / OceanBase 等关系型数据库存储模板、版本记录与运行日志，在容器化轻量化交付场景下带来了高昂的数据库运维、Schema 迁移与环境初始化成本；同时，当业务配置人员在工作台协同编辑模板、Skill 或接口契约时，急需草稿与线上快照严格隔离、并发修订防覆盖、发布异常自动回滚以及线上突发异常时秒级回退至任意历史快照的能力。

另一方面，平台在高并发执行智能体报告生成任务时，若多个异步请求协程并发向同一运行索引文件写入记录，极易发生行撕裂与锁等待；而面对大模型连接参数、智能体运行阈值、网关并发及聊天压缩配额等 48 项关键调优参数，传统“修改环境变量 + 重启容器”模式无法满足在线故障止血与版本可回滚需求。为此，`report-agent` 需要构建一套完全基于单 PVC 目录（`DATA_DIR`）的文件化 Git 版本存储、草稿并发治理、单写者异步运行账本与 `0600` 运行期配置热重载底座。

### 1.2 业务目标

- **GOAL-1**：以零外部数据库的 `DATA_DIR` 文件系统拓扑、内部 Git 仓库与 POSIX 原子软链接 `releases/current` 承载全量可演进资源，支持在途运行无锁锁定不可变快照与毫秒级紧急回退。
- **GOAL-2**：为工作台协同编辑提供草稿箱目录级双步原子换写、乐观锁 `revision` 冲突拦截、`baseRev` 基线漂移追踪以及按指纹缓存的 `overlay()` 叠加视图，做到多人编辑不覆盖、异常崩溃不损坏。
- **GOAL-3**：以单后台写协程异步队列彻底消除 `RunStore` 并发写入撕裂，并通过按日 LRU 缓存与启动孤儿/详情双向恢复、以及 `CaseStore` 512 字节头指纹缓存实现毫秒级检索与零丢失关停排空。
- **GOAL-4**：建立覆盖 48 项参数的 `0600` 持久化版本仓 `RuntimeConfigStore` 及单进程 `cli.py` 引导命令，支持参数跨字段校验、密钥脱敏、启动损坏自愈与审计可回滚。

---

## 2. 需求概述 【核心】

本需求交付 `report-agent` 的全套文件化存储引擎、配置模型与命令行入口（对应 `src/report_agent/store/` 11 个模块与 `config.py`、`cli.py`，共 4,481 行源码）。在物理拓扑与 IO 安全层，系统通过 `DataLayout` 划定 `repo/`、`drafts/`、`releases/`、`runs/`、`chats/`、`cases/`、`mock-gateway/`、`config/` 与 `audit.jsonl` 九大区域并锁定全部资源 ID 正则；通过 `fsutil.py` 统一提供同目录临时文件 `os.fchmod` + `fsync` + `os.replace` 原子落盘及 `ensure_within` / `ensure_entry_within` 双层路径防穿越边界。

在核心存储能力层，系统包含四大引擎：（1）`GitRepo` + `ReleaseStore` + `Publisher` 组成的事务型原子发布管道，支持以实际线上 `live_rev`（含紧急回切后）为基准增量构建、仅阻断新引入 `error` 的 `validate_all` 门禁、异常 `reset_to` 完整回滚及已淘汰快照通过 `git archive` 按需重建；（2）`DraftStore` + `ResourceService` 的乐观锁草稿与 `overlay()` 指纹缓存视图；（3）`RunStore` 单写协程异步账本与 `CaseStore` 轻量头部验证仓储；（4）`RuntimeConfigStore` 对 **48 项** 运行期配置提供 `0600` 版本化快照管理、`current.json` 损坏自愈与脱敏回滚，配合 `Settings` 空白兜底与 `cli.py`（锁定 `workers=1`）。

### 2.1 用户场景与测试

> 按用户旅程组织并标记稳定编号 `US1`、`US2` 等，使用 `P1`/`P2` 排序；每个故事均具备独立测试与自动化验收覆盖。

#### 用户故事 1（US1）— 零外部数据库的内部 Git 版本库、增量门禁发布与 releases/current 原子切换/回退（优先级：P1）

- **用户旅程**：作为平台发布管理员与线上运维人员，我希望所有已发布资源托管在单 PVC 内的内部 Git 仓库与不可变快照目录 `releases/rN/` 中，发布时仅拦截新引入阻断错误并在发生 IO 故障时自动事务级回滚，发生线上异常时可通过 `emergency_switch` 毫秒级切换 `releases/current` 至任意历史版本（包括已超过保留数被清理但存于 Git 中的版本）。
- **优先级理由**：文件化 Git 版本发布与 `releases/current` 原子软链接切换是零数据库架构的持久化核心，直接保障线上在途请求的快照隔离与故障秒级止血。
- **独立测试**：使用临时 `DATA_DIR` 目录组装 `DataLayout`、`GitRepo`、`ReleaseStore` 与 `Publisher`，验证首次建库发布、紧急回切 `r1` 后再发布新版本以 `r1` 为基准、软链写入异常回滚（含空仓库 `reset_to(None)`）及被 `prune` 清理快照通过 `git archive` 重建。
- **关联需求**：`FR-001`–`FR-004`、`SC-001`、`SC-002`、`SC-005`
- **验收场景**：
  1. **前提** 线上处于 `r2` 后被值班员通过 `emergency_switch` 原子切换回历史版本 `r1`（此时 Git `HEAD` 仍指向 `r2`），**当** 再次修改某一资源并调用 `Publisher.publish`，**则** 构建过程严格以当前 `live_rev`（`r1`）为基准生成 `r3`（`base="r1"`），既不会把被回切的 `r2` 变更误带上线，也不会因与 `r2` 内容相似而误判为 `NothingToPublish`。
  2. **前提** 一次发布在校验通过、写完 Git Commit 后于 `releases.add` 替换 `releases/current` 软链接或写入 `index.jsonl` 时发生 IO 异常，**当** 发布器捕获异常进入回滚流程，**则** 自动恢复 `index.jsonl`、清理残留构建目录与未登记版本目录、调用 `repo.reset_to(prev_head)` 将 Git 工作区与分支恢复至发布前状态（含空仓库 `reset_to(None)`），且保留用户待发布草稿不丢失。
  3. **前提** 历史版本 `r1` 的物化快照目录因超过 `releases_keep`（默认 `50`）被 `prune` 原子重命名清理，**当** 查询该版本资源或执行 `emergency_switch("r1")` 时，**则** `ReleaseStore.ensure_materialized` 自动通过 `git archive` 导出对应 Commit 并补齐 `.release.json`，重建完整目录树并原子上线；对已存在 `.release.json` 的物化快照查询缺失文件则零子进程直接返回 `None`。

#### 用户故事 2（US2）— 多维护人员并发安全的草稿箱乐观锁（revision）、基线漂移（baseRev）与 overlay 指纹缓存（优先级：P1）

- **用户旅程**：作为工作台业务维护人员，我希望编辑中的模板、Skill、接口与系统提示词隔离保存在草稿箱中而不干扰线上版本；多人同时修改或一方先行发布后提交旧版保存时，系统通过 `revision` 乐观锁拦截覆盖；在异常崩溃时自动从 `.bak` 恢复原草稿；同时 `overlay()` 与回退/下线工作流保持实时一致与零冗余磁盘解析。
- **优先级理由**：多人协同防覆盖与草稿目录多文件替换的原子完整性，直接关系配置平台日常编辑安全性与试运行准确度。
- **独立测试**：独立调用 `DraftStore` 与 `ResourceService` 测试并发修订冲突 `DraftConflict`、`os.replace` 异常时 `.bak` 回滚、跨格式等价阻断 `NothingToPublish`、`rollback("draft_only" / "publish_now")` 以及 `overlay()` 指纹命中与失效逻辑。
- **关联需求**：`FR-002`、`FR-005`、`SC-001`、`SC-005`
- **验收场景**：
  1. **前提** 维护人员 A 已将模板 `1001` 草稿保存至 `revision=2`，维护人员 B 基于旧修订 `expected_revision=0` 或在草稿已被他人发布删除后携带正数 `expected_revision=2` 提交保存，**当** 执行 `ResourceService.save_template` 或 `DraftStore.write`，**则** 立即拦截并抛出包含当前最新状态或 `NO_DRAFT` 信息的 `DraftConflict`。
  2. **前提** 调用 `DraftStore.write` 写入新草稿文件时在 `.tmp` 阶段校验到非法路径（如 `../escape.yaml` 或 `.meta.json`），或在将新目录 `os.replace` 覆盖旧草稿目录瞬间发生系统错误，**当** 异常处理分支介入，**则** 立即回切 `.bak` 备份目录恢复原草稿内容并清理临时目录，保障磁盘草稿完整性与修订号零破坏。
  3. **前提** 管理员将线上模板或系统提示词回退至某一已下线或正常的历史版本，**当** 选择 `mode="draft_only"` 或 `mode="publish_now"`，**则** `draft_only` 将历史快照内容载入草稿（剥离 `.offline` 与 `.meta.json` 并在目标为已下线版本时附带告警说明），`publish_now` 直接基于当前线上发布为新版本并清理旧草稿，同时 `_bump_draft_seq()` 立即失效 `overlay()` 缓存。

#### 用户故事 3（US3）— 高并发无损的 RunStore 单写者异步队列、按日缓存检索与回归用例库 CaseStore（优先级：P2）

- **用户旅程**：作为运行监控查询方与测试回归用户，我希望智能体高并发填报结束后的运行详情与摘要异步无锁撕裂落盘、尚未落盘记录即可实时查到、应用停机或任务取消不丢失任何记录；历史索引损坏或详情文件丢失时系统可双向自愈；同时回归用例统计与读取可在海量用例下保持毫秒级响应并过滤恶意软链与损坏 YAML。
- **优先级理由**：单写者异步写队列解决了高频追加 JSONL 的并发撕裂与阻塞瓶颈，双向降级自愈和按日/头部指纹缓存保障了运行看板与用例库的强健性与高性能。
- **独立测试**：启动 `RunStore` 验证并发 `submit`、停机 `stop()` 与 Task 取消 `_drain_queue` 排空、孤儿文件启动扫描与双向损坏降级、window 统计与过期清理，同时验证 `CaseStore.count()` 缓存命中及坏 YAML/软链过滤。
- **关联需求**：`FR-006`、`FR-007`、`SC-003`
- **验收场景**：
  1. **前提** `RunStore` 后台写协程处于运行态且队列中存在未落盘记录，**当** 同时发生高频 `submit` 投递、异步 `stop()` 关停（或后台 Task 被 `cancel()`）以及跨线程同步回退写入，**则** `_writer` 的 `finally` 与 `stop()` 通过 `_drain_queue` 同步排空全部剩余队列项并清空 `_pending`，确保运行记录零丢失。
  2. **前提** 当日目录存在未写入 `index.jsonl` 的孤儿 `<runId>.json`、索引尾部存在截断半行坏字节，或某条记录的 `<runId>.json` 磁盘损坏，**当** 启动执行 `_recover_all_orphans`、分页查询 `list()` 或查看详情 `get()`，**则** 启动扫描自动将孤儿文件摘要补写入 `index.jsonl`，损坏半行被 `read_jsonl` 自动跳过，缺失详情则自动从当日摘要通过 `_detail_from_summary` 构造降级详情（标明 `recoveredFromIndex: True`）。
  3. **前提** 某模板的 `cases/<tid>/` 目录下存放大量合法回归用例及混入的损坏 YAML 或指向外部路径的软链接文件，**当** 调用 `CaseStore.count(tid)` 与 `CaseStore.list(tid)`，**则** 软链接与不合法文件被静默过滤，且二次调用 `count()` 命中 `(mtime_ns, size)` 头部验证缓存实现零文件打开开销的高速计数。

#### 用户故事 4（US4）— 48 项运行期配置 0600 安全持久化、版本回滚与 CLI 初始化引导工具（优先级：P2）

- **用户旅程**：作为系统管理员与部署运维人员，我希望平台大模型参数、智能体阈值、网关并发、留存天数及聊天压缩配额共 **48 项** 参数支持版本化热更新持久化至 `data/config/runtime/`，所有含密钥文件在写入全程保持 `0600` 权限、对外响应严格脱敏、支持无差异幂等跳过与版本回滚、`current.json` 损坏可自动从最近快照恢复，并可通过 `report-agent` CLI 完成单进程启动、数据初始化与账号创建。
- **优先级理由**：将 48 项调控参数升级为受版本审计、强校验、可脱敏回滚的 `0600` 持久化仓库，大幅提升线上调优速度与生产配置安全性。
- **独立测试**：通过 `RuntimeConfigStore`、`/api/v1/settings/runtime*` 热更新测试及 `cli.main` 验证首次释放 `c1`、局部更新、脱敏串留空保护与 `clear_*` 清空、`0600` 权限验证、跨字段校验、`current.json` 自愈、版本回滚、`sync_from_env` 及 `cli init` 无循环阻塞清理。
- **关联需求**：`FR-008`–`FR-010`、`SC-004`
- **验收场景**：
  1. **前提** `data/config/runtime/` 尚无配置或历史 `current.json` 缺少新增字段甚至部分非可空字段为 `null`/空串，**当** 进程启动执行 `bootstrap_or_load(settings)`，**则** 无配置时从 `Settings` 释放生成 `c1`，存在旧配置时通过 `RuntimeConfig.from_storage_dict` 自动填充缺失项并归一化回写且全程保持 `0600` 权限。
  2. **前提** 管理员通过热更新提交部分字段修改或保留脱敏串（如 `sk-***9999`、`***`）提交，**当** 执行 `RuntimeConfigStore.update`，**则** 仅未传入 `clear_*` 标志的留空或脱敏密钥自动沿用原明文密钥，若经 `diff_keys` 比对无实质变更则幂等返回原修订版本，否则写入新版本号 `c{N+1}` 并记入 `audit.jsonl`；任何超界或跨字段违规（如 `agentQueryDefaultLimit > agentQueryMaxLimit` 或 `chatCompactTriggerMessages <= chatCompactKeepRecent`）均抛出 `RuntimeConfigValidationError` 不污染当前配置。
  3. **前提** `current.json` 被意外删除或写坏违反校验规则，**当** 下次启动执行 `bootstrap_or_load`，**则** 自动倒序扫描 `index.jsonl` 与 `revisions/c*.json` 找到最近合法快照恢复生效并重建 `current.json`，保证服务不带病启动也不回退覆盖至过时环境变量。

### 2.2 成功标准

- **SC-001**：存储层、配置层与 CLI 回归测试集（`tests/test_store.py`、`tests/test_review_storage.py`、`tests/test_runtime_config_hot_reload.py`）100% 通过，模拟任意中途写入崩溃或软链切换失败场景下，线上版本号、`repo/` HEAD 指针与未发布草稿保持 100% 事务一致性。
- **SC-002**：线上热路径 `ReleaseStore.try_live_snapshot()` 在命中进程内 LRU 缓存（上限 `8`）时仅执行单次 `os.readlink` 系统调用，无目录遍历或 Git 子进程开销；已物化快照（含 `.release.json`）查询不存在资源文件实现 0 次 `git show` 子进程调用。
- **SC-003**：`RunStore` 在高并发投递及强制 `stop()` / 任务 `cancel()` 场景下保持 0 条记录丢失；按日分区检索命中 `_day_cache`（400 天 LRU）时免除全量 `index.jsonl` 反序列化，`CaseStore.count()` 命中 `_valid_cache`（上限 8192）后实现 0 次文件 `open()` 计数。
- **SC-004**：`RuntimeConfigStore` 托管的全部 48 项配置持久化文件（`current.json`、`index.jsonl`、`revisions/cN.json`）在创建、更新、自愈及回滚全周期中保持 `0600` 文件权限（目录 `0700`），且公开接口与修订历史输出中明文密钥泄露量为 0。
- **SC-005**：`ensure_within` 与 `ensure_entry_within` 拦截 100% 的目录穿越（`..`）、NUL 字节及外部软链逃逸测试样本，同时在清理或替换外部软链条目时对宿主机外部目标目录文件损坏数为 0。

### 2.3 假设

- **单进程内存并发模型假设**：草稿锁、发布锁（`threading.RLock`）、`RunStore` 单后台写协程与内存缓存均运行在单个 Python 进程内，生产部署 `uvicorn` 必须强制使用 `workers=1`（已在 `cli.py` 与 `.specify/memory/constitution.md` 中固化）；多进程或多实例共享同一 PVC 不在本规格支持范围内。
- **文件系统与系统命令依赖假设**：底层挂载卷支持 POSIX `os.symlink` 与 `os.replace` 原子重命名语义，容器环境中预装标准 `git` 命令行工具（支持 `git init -b main` 与 `git archive`）；当运行于受限非 POSIX 文件系统时，`_chmod_safe` 捕获 `OSError` 保证不崩溃。
- **相邻子规格协作边界假设**：本规格不实现 HTTP REST 路由响应映射与身份鉴权（由 `005-api-auth-governance` 消费 `DraftConflict`/`PublishError`/`ResourceService`，并由 `main.py` 全局处理器映射为 400/404/409/422），也不直接重建大模型 `Agent` 或 `ReloadableGatewayClient`（由 `Container.apply_runtime_config` 协同 `003`/`004` 完成）；核定 `33.0 人天` 涵盖全部 `store/`、`config.py`、`cli.py` 及对应单测验收。

---

## 3. 术语与概念定义 【核心，如有新术语】

> 通用平台术语（如 `线上版本号`、`基线漂移`）见 `wiki/reference/glossary.md`；以下列出本存储与配置底座特有的工程术语。

| 术语 | 英文/标识 | 定义 | 备注 |
| --- | --- | --- | --- |
| PVC 布局与资源寻址凭证 | `DataLayout` / `ResourceRef` | `DataLayout` 管理 `DATA_DIR` 下九大功能子目录；`ResourceRef` 绑定资源类型（`template`/`skill`/`api`/`system-prompt`）与经白名单正则校验的唯一标识 | 统一映射发布树路径与草稿目录 |
| 末端软链安全守卫 | `ensure_within` / `ensure_entry_within` | `ensure_within` 校验 `resolve()` 真实目标位于沙箱内（防逃逸读写）；`ensure_entry_within` 仅校验父目录真实路径位于沙箱内（用于安全 `unlink` 恶意软链而不伤外部目标） | 两套逻辑互补缺一不可 |
| 发布血缘链 | `ReleaseStore.lineage` | 从指定版本或线上指针 `live_rev` 沿 `base` 字段逆向追溯得到的有效发布历史链（跳过因紧急切换被废弃的分支版本） | 用于确定线上资源 `online_change` 真实来历 |
| 双向自愈运行账本 | `RunStore` | 采用 `asyncio.Queue` + 单 `_writer` + `_pending` 内存视图的运行仓储，同时支持启动扫描孤儿 `.json` 补索引和详情丢失时从摘要构造 `recoveredFromIndex: True` 降级视图 | 兼顾零撕裂写入与容错查询 |
| 48 项运行期配置仓库 | `RuntimeConfig` / `RuntimeConfigStore` | 托管 `llm*`、`agent*`、`gateway*`、`releasesKeep`、`runsKeepDays`、`reportApiKeys`、`chat*` 等 48 个运行参数的版本化 `0600` 持久化仓库 | 支持无差异跳过、脱敏展示与修订回退 |

---

## 4. 用户角色 【核心】

| 角色 | 类型 | 本需求中可执行的操作与数据范围 | 权限/安全约束 |
| --- | --- | --- | --- |
| 业务配置维护人员 | 人工角色 | 通过工作台接口间接触发 `ResourceService` 保存草稿、对比基线漂移、放弃草稿、查看工作副本与创建回归用例 | 全部写操作携带服务端认证身份 `operator` 写入草稿 `.meta.json` 与 `audit.jsonl`，受 `expected_revision` 乐观锁保护 |
| 平台发布管理员 / 值班运维 | 人工角色 | 触发单资源/批量发布、下线/恢复模板、执行版本 `rollback`、线上紧急切换 `emergency_switch`、热更新或回退 48 项运行期配置及使用 `report-agent` CLI 初始化与加用户 | 写操作记入 `audit.jsonl`；敏感配置目录 `0700`、文件 `0600`；公开视图永不返还明文密钥 |
| 智能体运行时与异步请求协程 | 内部系统角色 | 调用 `ReleaseStore.try_live_snapshot` / `live_snapshot` 锁定不可变快照，调用 `RunStore.submit` 异步投递运行结果 | 运行期仅只读消费已发布快照，零写锁争用，异步写盘由后台单协程串行执行 |

---

## 5. 功能需求 【核心】

### 5.1 文件拓扑、原子 IO 底座与安全 Git 封装

#### FR-001 零外部数据库 PVC 存储布局管理器与标识正则约束

- **来源**：`src/report_agent/store/layout.py`（`DataLayout`、`ResourceRef`、`InvalidResource`、`ref_from_tree_path`、`copy_resource`、`remove_resource`）
- **描述**：系统必须建立统一的 PVC 本地文件系统目录拓扑与资源寻址契约，对所有外部输入的资源类型、标识、版本号与用例 ID 实施白名单正则校验。
- **关联用户故事/成功标准**：`US1` / `SC-005`
- **业务规则**：
  1. `DataLayout` 在 `root.resolve()` 下规范管理 `repo/`、`drafts/`、`releases/`（含 `current` 软链与 `index.jsonl`）、`runs/`、`chats/`、`cases/`、`mock-gateway/`、`config/` 与 `audit.jsonl`；`ensure()` 自动创建基础目录。
  2. 强制白名单正则约束：`template`（`^[1-9]\d{0,9}$`）、`skill`（`^[a-z0-9][a-z0-9\-]{0,63}$`）、`api`（`^[A-Za-z][A-Za-z0-9_\-]{0,63}$`）、`system-prompt`（固定 `"system-prompt"`）、版本号 `REV_RE`（`^r[1-9]\d{0,9}$`）与用例 ID `CASE_ID_RE`（`^[A-Za-z0-9_\-]{1,40}$`），违者抛出 `InvalidResource`。
  3. `ResourceRef.tree_path()` 统一映射资源至发布树相对路径；`ref_from_tree_path` 反向解析 diff 路径为 `ResourceRef`。
- **输入/触发**：`DATA_DIR` 根路径及各类资源标识参数。
- **输出/结果**：标准路径布局与强校验 `ResourceRef` 凭证；非法标识抛出 `InvalidResource`。
- **验收标准**：
  - AC-1：调用 `DataLayout(root).ensure()` 创建标准九区中全部基础目录；非法模板 ID（如 `"0"`、`"-1"`、`"../x"`）或超长 API 名称被 `ResourceRef` 拒绝。
  - AC-2：`ref_from_tree_path` 能将 `templates/101/body.md.j2`、`skills/abc/SKILL.md`、`apis/foo.yaml`、`system-prompt.md` 准确还原为对应 `ResourceRef`。

#### FR-002 双层路径防逃逸守卫与防权限裸露窗口的原子持久化原语

- **来源**：`src/report_agent/store/fsutil.py` 与 `src/report_agent/store/layout.py`
- **描述**：系统必须提供全链路防路径穿越/软链逃逸守卫，以及先设权、`fsync` 后原子替换的磁盘写盘工具集。
- **关联用户故事/成功标准**：`US1`、`US2` / `SC-004`、`SC-005`
- **业务规则**：
  1. `ensure_within(base, target)` 拒绝 NUL 字节与基目录自身/父级逃逸，且解析 `resolve()` 确保真实目标严格落在 `base.resolve()` 内；`ensure_entry_within(base, target)` 仅验证规范化目标严格位于 `base` 且父目录真实路径位于 `base` 内，使清理过程可安全 `unlink` 指向外部的恶意或悬空末端软链接而不破坏外部文件。
  2. `atomic_write_bytes` 在 `tempfile.mkstemp` 获取描述符后、写入任何字节前即调用 `_chmod_safe(fd, mode)` 收紧权限（消除 umask 裸露窗口），`flush` + `os.fsync` 后经 `os.replace` 原子覆盖并调用 `_fsync_dir(path.parent)`；`append_line` 在指定 `mode` 时以受限模式 `os.open` 创建追加；`_chmod_safe` 兼容捕获非 POSIX `OSError`。
  3. `read_json` 与 `read_jsonl` 自动跳过文件不存在、JSON 解码失败或崩溃残留的截断半行与非字典行；`atomic_symlink` 先建临时软链再用 `os.replace` 原子覆盖目标软链；`trees_equal` 与 `replace_dir_contents` 支撑快照内容精确比对与同步。
- **输入/触发**：目标路径、字节/文本/JSON 载荷、权限 `mode` 或软链目标名。
- **输出/结果**：原子持久化落盘文件、统一格式审计行（`append_audit`）或经宽容过滤后的列表结果。
- **验收标准**：
  - AC-1：`ensure_within` 拦截包含 `..`、`\x00` 或指向临时目录外部的软链接；调用 `remove_resource` 清理指向外部目录的软链接时，仅摘除软链自身且外部文件毫发无损。
  - AC-2：调用 `atomic_write_bytes(..., mode=0o600)` 或 `append_jsonl(..., mode=0o600)` 创建的文件权限严格为 `0o600`；`read_jsonl` 在尾行截断或掺杂非法 JSON 时正常返回其余完整记录。

#### FR-003 防命令注入与支持空仓库回滚的内部 Git 封装（GitRepo）

- **来源**：`src/report_agent/store/git_repo.py`（`GitRepo`、`GitError`、`NameStatus`）
- **描述**：系统必须封装受控内部 Git 仓库操作类 `GitRepo`，支持免改全局 Git Config 提交、安全读档/差异比对、`git archive` 快照重建与全场景回滚。
- **关联用户故事/成功标准**：`US1` / `SC-001`
- **业务规则**：
  1. `ensure_init` 初始化 `repo/`（默认分支 `main`）；所有 Git 命令禁用终端交互提示并强制 `LC_ALL=C.UTF-8`、关闭路径转义（`core.quotepath=false`）与自动换行（`core.autocrlf=false`），超时设为 60 秒。
  2. 提交身份通过 `GIT_AUTHOR_*` / `GIT_COMMITTER_*` 环境变量传入；所有接收提交号的方法（`show`、`diff_name_status`、`export`、`reset_to`）强制通过 `_COMMIT_RE`（`^[0-9a-fA-F]{7,64}$`）校验，拦截 `--help`、`-n` 等参数注入；`show` 拦截绝对路径、`..` 与 NUL 字节。
  3. `export(commit, dest)` 调用 `git archive --format=tar` 配合 `tarfile.extractall(..., filter="data")` 安全解压重建快照目录；`reset_to(commit)` 在 `commit` 非空时执行 `reset --hard` + `clean -fd`，在 `commit is None`（首次提交即失败）时删除 `refs/heads/main`、重建未诞生符号引用并清空索引与工作区。
- **输入/触发**：提交说明（含结构化 Trailer）、操作人、Commit SHA 及导出目标路径。
- **输出/结果**：提交 SHA、文件字节内容、`NameStatus` 变更列表或恢复后的工作区。
- **验收标准**：
  - AC-1：向 `show`、`export` 或 `reset_to` 传入非 hex 字符串或 `-exec` 等恶意参数立即抛出 `GitError`；向 `show` 传入 `../etc/passwd` 返回 `None`。
  - AC-2：在初始首次提交后执行 `reset_to(None)`，仓库工作区清空且 `head()` 正确回归 `None`。

### 5.2 不可变快照发布、草稿乐观锁与叠加视图

#### FR-004 锁内事务型发布器 Publisher 与不可变快照仓 ReleaseStore

- **来源**：`src/report_agent/store/releases.py` & `src/report_agent/store/publisher.py`
- **描述**：系统必须实现进程内 `RLock` 保护的不可变版本发布仓 `ReleaseStore` 与事务型发布器 `Publisher`，保障增量门禁校验、无差异拦截、原子上线、紧急切换与异常全量回滚。
- **关联用户故事/成功标准**：`US1` / `SC-001`、`SC-002`
- **业务规则**：
  1. `ReleaseStore` 按 `(mtime_ns, size)` 缓存 `releases/index.jsonl` 与 `_by_rev` 映射，维护最多 `8` 个不可变快照的 LRU 缓存 `_snapshots`；提供零子进程快路径 `try_live_snapshot()`（单次 `os.readlink` + 缓存查表）；`read_file_at` 在目录已含 `.release.json` 且目标文件不存在时直接返回 `None`，避免无效 `git show`；`prune()` 先将超限旧快照原子重命名为 `.prune-*` 再删除（始终保留 `live_rev` 与最近 `keep` 个），`ensure_materialized` 在需要时经 `git archive` 从 Git 重建已淘汰快照。
  2. `Publisher.publish` 在 `self.lock`（`threading.RLock`）内严格以当前实际线上版本 `live_rev()`（而非 Git `HEAD`）为基准克隆构建 `.build-rN` 并应用变更。
  3. 调用 `validate_all` 对比 `base_rs` 与 `new_rs` 的 `_issue_key` 差集：仅拦截本次变更新引入的 `error`（抛 `PublishError`），返回本次受影响资源的 `warning`；经 `trees_equal` 检查若内容无变化则抛出 `NothingToPublish`。
  4. 同步工作区并生成带 `Release`/`Base`/`Operator`/`Note` Trailer 的 Git 提交后，调用 `releases.add` 原子换入 `releases/rN`、写入 `index.jsonl` 并 `atomic_symlink` 切换 `releases/current`；如其中任意步失败，立即恢复 `index.jsonl`、清理未登记目录并调用 `repo.reset_to(prev_head)` 完整回滚，保留未发布草稿。
  5. 发布成功后删除已消费草稿、写入 `audit.jsonl` 并触发 `prune()`；`emergency_switch` 原子切换软链并记审计；`recover()` 启动清理残留 `.build-*`/`.restore-*`/`.prune-*`/草稿临时目录。
- **输入/触发**：变更列表 `list[Change]`、操作人、发布类型/摘要/备注或紧急回切版本号。
- **输出/结果**：`PublishResult(entry, warnings)` 或结构化异常 `PublishError`/`NothingToPublish`/`ReleaseNotFound`。
- **验收标准**：
  - AC-1：紧急切回 `r1` 后基于草稿发布 `r3` 时，`r3` 的 `base` 为 `"r1"` 且内容基于 `r1` 而非 `r2`；`releases.add` 软链失败时 `index.jsonl`、目录树与 `repo.head()` 均无损回到发布前状态。
  - AC-2：超过 `keep` 被 `prune` 清理的历史版本，在调用 `emergency_switch` 或 `snapshot` 时可经 `git archive` 无损重建并返回完整 `ResourceSet`。

#### FR-005 多人协同乐观锁草稿存储 DraftStore 与资源叠加服务 ResourceService

- **来源**：`src/report_agent/store/drafts.py` & `src/report_agent/store/service.py`
- **描述**：系统必须实现多文件原子替换与乐观锁保护的草稿存储 `DraftStore` 以及聚合线上+草稿四态视图、版本回退与指纹缓存的资源协调服务 `ResourceService`。
- **关联用户故事/成功标准**：`US2` / `SC-001`、`SC-005`
- **业务规则**：
  1. `DraftStore.write` 在 `self.lock` 内核对 `expected_revision` 与当前 `.meta.json` 的 `revision`（不一致抛 `DraftConflict`）；在同级父目录创建 `.tmp` 目录写入（禁止空文件名、`/`、`\` 与 `.meta.json`），将旧草稿目录原子替换为 `.bak` 后将 `.tmp` 替换为目标目录；若替换异常自动回切 `.bak` 恢复原草稿。
  2. `ResourceService._check_missing_draft_conflict` 当客户端携带 `expected_revision > 0` 但草稿已被他人发布/删除时，立即抛出含 `status="NO_DRAFT"` 的 `DraftConflict`（映射 HTTP 409）。
  3. `ResourceService.state` 精确计算四态：`DRAFT`、`PUBLISHED`、`PUBLISHED_DRAFT`、`OFFLINE`，维护 `online_rev` 与 `base_rev`；`publish_draft` 调用 `_same_as_online` 执行解析后语义级比对（忽略 YAML 注释和格式空白差异），一致则抛 `NothingToPublish`。
  4. `ResourceService.rollback` 支持 `draft_only`（载入历史内容剥离 `.offline`/`.meta.json`，若目标版本为下线状态则附带 `targetOffline: True` 与告警）和 `publish_now`（生成新版本并清理旧草稿）；支持 `offline_template`（写 `.offline` 标记）与 `restore_template`。
  5. `ResourceService.overlay()` 结合自增序号 `_draft_mutation_seq` 与 `os.scandir`（`follow_symlinks=False`）扫描的草稿指纹 `_drafts_fingerprint()` 构建缓存键 `(live_rev, seq, fp)`（锁外计算、写入缓存锁内双重核对 `seq` 与 `live_rev`，返回浅拷贝 `_clone_resource_set` 防止外部篡改），损坏草稿记入 `DRAFT_INVALID` 不阻断其他资源读取。
- **输入/触发**：资源保存载荷、`expected_revision`、发布/回退/下线/放弃请求或工作副本校验/试运行读取。
- **输出/结果**：更新后的 `.meta.json`、四态 `ResourceState`、浅拷贝叠加态 `ResourceSet` 或 `DraftConflict`/`NothingToPublish`/`ResourceNotFound`。
- **验收标准**：
  - AC-1：并发保存携带过期 `expected_revision` 或正数修订号对应缺失草稿时抛出 `DraftConflict`；模拟 `os.replace` 抛 `OSError` 时原草稿目录和修订号完整保留。
  - AC-2：二次调用 `overlay()` 在无草稿和线上版本变动时直接命中缓存返回浅拷贝副本；任意草稿修改、放弃、发布或磁盘文件变化立即使缓存失效。

### 5.3 单写者异步运行账本与回归用例库

#### FR-006 单协程异步运行账本 RunStore、双向损坏自愈与窗口统计聚合

- **来源**：`src/report_agent/store/runs.py`（`RunStore`、`new_run_id`、`_normalize_summary`、`_summary_from_detail`、`_normalize_detail`、`_detail_from_summary`）
- **描述**：系统必须实现单后台协程顺序写入的按日分区运行记录存储 `RunStore`，兼顾高频投递实时可见性、停机无损排空、孤儿/损毁双向恢复、按日缓存检索与定时清理。
- **关联用户故事/成功标准**：`US3` / `SC-003`
- **业务规则**：
  1. `new_run_id` 生成格式 `yyyyMMddHHmmssSSS + 7 位随机小写字母数字`（前 8 位即按日分区 `runs/YYYY/MM/DD/`）；`submit` 在写协程未启动或已停止时自动退回锁内同步写入 `_write`，在运行态先写入内存有序映射 `_pending` 再投递 `asyncio.Queue` 实现写后立即可查。
  2. `_writer` 后台协程通过 `asyncio.to_thread(self._write, *item)` 落盘并在写完（或失败）后从 `_pending` 移除；`_writer` 的 `finally` 与 `stop()` 均调用 `_drain_queue` 同步排空未处理队列，确保停机或任务被 `cancel()` 时零丢失。
  3. 启动 `start()` 时调用 `_recover_all_orphans` 一次性扫描历史目录中尚未写入 `index.jsonl` 的孤儿 `<runId>.json` 补写索引并预热 `_day_cache`（LRU 上限 `_MAX_DAY_CACHE = 400` 天）；`get(run_id)` 优先读 `_pending`，其次读 `<runId>.json`，若详情缺失或损坏则从当日摘要经 `_detail_from_summary` 构造降级详情（标明 `recoveredFromIndex: True`）。
  4. `list()` 按日期倒序分页合并内存 `_pending` 与磁盘 `_read_day_summaries`（命中 `(ddir_mtime, idx_mtime_ns, idx_size)` 指纹免全量解析）；`stats_7d()` 缓存 60 秒聚合各模板运行数/成功率/P95 耗时/Skill/API 调用与按日趋势；`cleanup(keep_days)` 删除超期日目录并级联清理空月/年父目录。
- **输入/触发**：运行摘要 `summary` 与详情 `detail` 字典、查询过滤条件、`window_stats` 天数或 `cleanup(keep_days)`。
- **输出/结果**：持久化的 `<runId>.json` 与 `index.jsonl`、规范化详情/摘要列表、聚合统计字典或清理目录数。
- **验收标准**：
  - AC-1：高频异步投递后调用 `stop()` 或取消 `_writer` Task，`index.jsonl` 与 `<runId>.json` 条数 100% 落盘且 `_pending` 清空。
  - AC-2：注入未记入索引的孤儿 JSON、尾部半行截断或损毁的 `<runId>.json` 时，启动自愈补全索引、`list()` 正常翻页、`get()` 降级返回 `recoveredFromIndex: True`。

#### FR-007 回归用例文件库 CaseStore 与高速头部指纹计数缓存

- **来源**：`src/report_agent/store/cases.py`（`CaseDef`、`CaseStore`）
- **描述**：系统必须实现独立于发布版本演进的回归测试用例存储 `CaseStore`，使用轻量头部检查缓存加速列表计数并隔离恶意软链接与损坏文件。
- **关联用户故事/成功标准**：`US3` / `SC-003`
- **业务规则**：
  1. 用例独立持久化于 `cases/<templateId>/<caseId>.yaml`，不随 `releases/current` 切换而回退；严格校验正整数 `tid` 与 `CASE_ID_RE`，所有路径经 `ensure_within` 守卫。
  2. `count(tid)` 使用 `os.scandir`（`follow_symlinks=False`）扫描目录项并读取最多 `512` 字节头判定是否合法映射 YAML（支持 UTF-8 BOM、注释、文档起始符及流式 JSON 回退校验），将 `(mtime_ns, size, valid)` 缓存在 `_valid_cache`（容量上限 `_MAX_VALID_CACHE = 8192`），命中指纹后实现 0 文件打开计数。
  3. `list(tid)` 使用 `CSafeLoader`（回退 `SafeLoader`）跳过软链接与无效 YAML；`save`/`delete` 在 `self.lock` 内原子写入并同步刷新 `_valid_cache`；`copy_all` 支撑模板复制迁移；`from_payload` 兼容前端 `mobile`/`busiName`/`createTime`/`busiMonth` 到中文 `inputs` 键的映射。
- **输入/触发**：模板 ID、用例 ID、`CaseDef` / 前端载荷或复制源目标模板 ID。
- **输出/结果**：`CaseDef` 列表、精确计数或生成的自增用例 ID（`C-01`, `C-02`...）。
- **验收标准**：
  - AC-1：向 `cases/<tid>/` 放入指向外部的软链接、空文件或列表型坏 YAML 时，`count()` 与 `list()` 静默跳过不抛异常；再次调用 `count()` 命中指纹缓存无需打开文件。
  - AC-2：`from_payload` 能准确将 `mobile` 等英文别名映射到中文 `inputs` 字典。

### 5.4 48 项运行期配置 0600 持久化、环境变量兜底与 CLI 引导

#### FR-008 48 项运行期参数模型 RuntimeConfig、边界校验与密钥脱敏保护

- **来源**：`src/report_agent/store/runtime_config.py`（`RuntimeConfig`、`RuntimeSnapshot`、`RuntimeConfigValidationError`、`mask_secret`、`split_api_keys`、`mask_api_keys`）
- **描述**：系统必须定义覆盖 48 项运行参数的不可变配置模型 `RuntimeConfig`，提供强类型规整、区间/跨字段约束校验、局部补丁应用及面向管理端的安全脱敏输出。
- **关联用户故事/成功标准**：`US4` / `SC-004`
- **业务规则**：
  1. `_ORDERED_FIELDS` 完整涵盖 **48 项** 参数：大模型连接与工具调用参数（10 项，`llm*`）、智能体执行与工具限流参数（9 项，`agentOutputMode`..`agentPreviewRows`）、网关协议参数（6 项，`gatewayMode`..`gatewayConnectTimeoutS`）、上游凭证（1 项，`reportApiKeys`）、网关并发与留存（3 项，`gatewayMaxConcurrency`/`releasesKeep`/`runsKeepDays`）、平台工具配额（3 项，`agentQueryDefaultLimit`/`agentQueryMaxLimit`/`agentMaxPeriodMonths`）与嵌入式聊天压缩配额（16 项，`chat*`）；其中 4 项为 `_NULLABLE_FIELDS`。
  2. `apply_patch` 支持局部补丁更新与类型规整（兼容字符串布尔、数字与 `"null"`/`"auto"`）；对敏感字段 `llmApiKey`、`gatewayAppId`、`gatewayAccessToken` 与 `reportApiKeys`，未传清空标志 `clear_*` 时提交空串、`"***"` 或与当前脱敏串一致的值时自动保留原明文密钥。
  3. `validate()` 对全部 48 项执行范围、URL 合法性、控制字符拦截与跨字段约束检查（含 `gatewayMode == "live"` 必填 `gatewayUrl`、`agentQueryDefaultLimit <= agentQueryMaxLimit`、`chatCompactTriggerMessages > chatCompactKeepRecent`），异常收集并抛出 `RuntimeConfigValidationError`。
  4. `to_public_dict()` 强制屏蔽所有明文密钥，替换为 `has*` 布尔标志、`*Masked` 脱敏值及 `reportApiKeyCount`；`to_effective_settings` 生成叠加后的 `Settings` 副本。
- **输入/触发**：`Settings` 启动配置、磁盘历史字典或管理员补丁载荷 `patch`。
- **输出/结果**：校验通过的 `RuntimeConfig` 实例、公开脱敏字典或 `RuntimeConfigValidationError` 列表。
- **验收标准**：
  - AC-1：传入 `agentQueryDefaultLimit > agentQueryMaxLimit` 或 `chatCompactTriggerMessages <= chatCompactKeepRecent` 或非法 URL 时，抛出含精确中文原因的 `RuntimeConfigValidationError`。
  - AC-2：提交 `llmApiKey: "sk-***abcd"` 或留空时不覆盖原密钥，传入 `clear_llm_api_key=True` 时精确清空；`to_public_dict()` 在任何条件下不含明文密钥。

#### FR-009 0600 权限版本化配置仓库 RuntimeConfigStore（自愈、幂等更新与回滚）

- **来源**：`src/report_agent/store/runtime_config.py`（`RuntimeConfigStore`）
- **描述**：系统必须在 `data/config/runtime/` 下维护严格限权（目录 `0700`、文件 `0600`）的运行配置版本仓库，保障首次初始化释放、启动缺失/损坏自愈、幂等变更、审计追踪与版本回退。
- **关联用户故事/成功标准**：`US4` / `SC-004`
- **业务规则**：
  1. 目录布局包含 `current.json`（生效快照）、`index.jsonl`（修订摘要，不含密钥）与 `revisions/cN.json`（不可变完整快照，含密钥以便精确回滚）；每次落盘前确保目录 `0700`，并在 `write_json(..., mode=0o600)` 与 `append_jsonl(..., mode=0o600)` 临时句柄阶段预先设定 `0600` 权限。
  2. `bootstrap_or_load(settings)` 执行三步决策：首先清理残留 `.*.tmp`；若 `current.json` 合法存在，通过 `from_storage_dict` 自动补全新增字段并归一化回写（同时补齐丢失的 `revisions/cN.json` 或索引行）；若 `current.json` 缺失或损坏，倒序扫描 `index.jsonl` 与 `revisions/c*.json` 找到最近有效快照恢复重建 `current.json`；若为全新目录则从 `Settings` 释放 `c1`。
  3. `update()` 经 `diff_keys` 检查无实际键值变化时幂等返回 `(current, False)` 避免生成冗余版本号；有变更时写入 `c{N+1}` 并写入 `audit.jsonl`（动作 `runtime-config-update`）。
  4. `rollback(target_rev, reason, operator)` 读取历史快照校验通过后生成新递增版本 `c{N+1}` 切换生效并记入审计（`runtime-config-rollback`）；`sync_from_env` 支持重新对齐环境变量差异（`runtime-config-sync-env`）；`revisions()` 利用 `_public_cfg_cache` 避免历史页重复读取脱敏。
- **输入/触发**：启动 `Settings`、局部热更新补丁、目标回滚版本 `cN` 或环境变量重同步指令。
- **输出/结果**：当前生效 `RuntimeSnapshot`、脱敏历史列表与 `audit.jsonl` 审计条目。
- **验收标准**：
  - AC-1：生成或更新后的 `current.json`、`index.jsonl` 与 `revisions/cN.json` 文件权限位严格为 `0o600`（`runtime/` 与 `revisions/` 为 `0o700`）。
  - AC-2：人为删除或写坏 `current.json` 后重执行 `bootstrap_or_load`，自动恢复至最新合法 `cN` 而不是重置回环境变量。

#### FR-010 Settings 空白环境变量兜底与标准 CLI 命令行引导（cli.py）

- **来源**：`src/report_agent/config.py`（`Settings`、`get_settings`）& `src/report_agent/cli.py`（`main`）
- **描述**：系统必须提供对空环境变量具备容错兜底的 `Settings` 配置模型，并提供锁定单进程运行的 `report-agent` CLI 工具（`serve`、`init`、`user add`）。
- **关联用户故事/成功标准**：`US4` / `SC-001`
- **业务规则**：
  1. `Settings._fallback_blank_non_nullable_scalars`（`mode="before"`）针对 `_NON_NULLABLE_SCALAR_FIELDS`（40 项标量字段），当环境变量注入 `None` 或纯空白字符串时自动剔除该键交由 `Field` 默认值兜底，同时保留 `llm_max_tokens`、`llm_parallel_tool_calls` 等 4 项可空字段为 `None`；提供 `normalized_root_path()` 与 `report_api_key_set()` 辅助方法。
  2. `cli.main` 提供三个子命令：`serve` 强制以 `workers=1`、`proxy_headers=True` 启动 `uvicorn.run("report_agent.main:create_app", factory=True, ...)`；`init` 通过 `build_container(settings, model=object())` 初始化目录及种子版本后，检测当前是否已有运行中事件循环以安全调用 `c.gateway.aclose()`（持强引用 `_BG_TASKS`）；`user add` 校验密码不少于 8 位后更新 `config/users.yaml`（口令走 PBKDF2 哈希，不存明文）。
- **输入/触发**：`.env` / 系统环境变量、命令行参数（`serve` / `init` / `user add`）。
- **输出/结果**：经过兜底规整的 `Settings` 单例、单进程 ASGI 服务、已初始化的 `DATA_DIR` 或用户账号落盘确认。
- **验收标准**：
  - AC-1：设置 `RELEASES_KEEP=""`、`LLM_TEMPERATURE="  "` 时 `Settings()` 正常启动并采用默认值 `50` 和 `0.0`，不报 Pydantic 解析异常。
  - AC-2：无论在无事件循环的同步进程还是运行中 `asyncio` 循环内调用 `cli.main(["init"])`，均正常初始化并关闭网关连接而不抛 `RuntimeError`。

---

## 6. 非功能需求 【补充】

| 类型 | 编号 | 说明 | 验收方式 |
| --- | --- | --- | --- |
| 零业务硬编码 | `NFR-001`（关联宪章原则 I） | `src/report_agent/store/`、`config.py` 与 `cli.py` 仅按 `ResourceRef` 与目录树拓扑处理资源，零特定模板 ID 或业务规则硬编码 | 代码静态核查 + `tests/test_store.py` |
| 发布前置门禁协同 | `NFR-002`（关联宪章原则 II） | `Publisher.publish` 在落盘和提交前强制执行 `domain.resources.validate_all` 增量差集检验；`RunStore` 完整持久留痕 `validationRounds`/`skillsLoaded`/`apiResults`/`events` | `tests/test_store.py` |
| 单进程并发与原子性 | `NFR-003`（关联宪章原则 III） | `cli.py` 强制 `workers=1`；草稿、发布、配置库共用进程内 `threading.RLock`；`RunStore` 采用单后台协程 + `_write_lock` 写盘；所有写盘与软链走同目录临时文件 `fsync` + `os.replace` | `tests/test_store.py`、`tests/test_review_storage.py` |
| 安全编码与零明文泄露 | `NFR-004`（关联宪章原则 VI） | `ensure_within` / `ensure_entry_within` 防穿越与末端软链逃逸；`GitRepo._check_commit` 防命令注入；`RuntimeConfigStore` `0700`/`0600` 预先 `os.fchmod` 赋权；公开视图 0 明文密钥 | `tests/test_review_storage.py`、`tests/test_runtime_config_hot_reload.py` |
| 关键操作审计留痕 | `NFR-005`（关联宪章原则 VII） | 发布（`publish`）、紧急回切（`emergency-switch`）、运行配置更新（`runtime-config-update`）、配置回退（`runtime-config-rollback`）与环境变量同步（`runtime-config-sync-env`）均由服务端不可伪造身份写入 `audit.jsonl` | `tests/test_store.py`、`tests/test_runtime_config_hot_reload.py` |
| 可复现测试与性能/前端边界 | `NFR-006`（关联宪章原则 V、VIII、X） | 单元测试使用临时目录与故障注入，不访问真实外网与外部 DB；`try_live_snapshot`、`RunStore._day_cache`（400 天）与 `CaseStore._valid_cache`（8192 项）消除热点磁盘遍历开销；本需求不涉及前端页面改造 | `uv run pytest -q` + `uvx ruff@0.11.0 check src tests` |

---

## 7. 数据与存储需求 【补充】

| 数据对象/存储位置 | 变更类型 | 关键字段与口径 | 一致性/留存策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `DATA_DIR/repo/` | 持久化（Git 仓库） | 已发布态完整文件树（默认分支 `main`），Commit 消息附 `Release`/`Base`/`Operator`/`Note` Trailer | 与发布操作在 `RLock` 内同步更新，失败通过 `reset_to` 回滚 | `FR-003`、`FR-004` |
| `DATA_DIR/releases/` | 持久化（不可变快照） | `index.jsonl`（发布元数据）、`r1..rN/`（完整快照 + `.release.json`）、`current -> rN` 相对软链接 | `atomic_symlink` 原子切换；默认保留最近 `50` 个（另永久保留 `live_rev`），超限原子重命名删除并可由 Git 重建 | `FR-004` |
| `DATA_DIR/drafts/<kind>/<key>/` | 持久化（工作草稿） | 资源正文文件 + `.meta.json`（`kind`, `key`, `baseRev`, `revision`, `createdAt/By`, `updatedAt/By`, `action`） | `.tmp`/`.bak` 双步原子换写，异常回切 `.bak`；乐观锁校验 `expected_revision` | `FR-005` |
| `DATA_DIR/runs/YYYY/MM/DD/` | 持久化（按日运行账本） | `index.jsonl`（摘要）+ `<runId>.json`（完整运行详单） | 单协程队列顺序写 + `_pending` 内存视图 + `_day_cache`（400 天）；按 `runs_keep_days`（默认 90 天）清理空父目录 | `FR-006` |
| `DATA_DIR/cases/<templateId>/` | 持久化（回归用例） | `<caseId>.yaml`（`id`, `name`, `source`, `inputs`, `documentText`, `expectedValues`, `lastResult`, `lastRunId`, `updatedAt`） | 不受 `releases/current` 回退影响；`_valid_cache`（8192 项）加速计数 | `FR-007` |
| `DATA_DIR/config/runtime/` | 持久化（热更新配置） | `current.json`（`activeRev` + 48 项配置）、`index.jsonl`（无密钥索引）、`revisions/cN.json`（完整版本快照） | 目录 `0700`、文件 `0600`（`os.fchmod` 预赋权）；启动损坏从最近快照自愈 | `FR-008`、`FR-009` |
| `DATA_DIR/audit.jsonl` | 只追加审计日志 | `time`、`action`、`operator` 及关联变更 `rev`/`base`/`changedKeys`/`reason` 等 | 通过 `fsutil.append_audit` 追加 `fsync` 落盘，半行损毁容错读取 | `FR-002`、`FR-004`、`FR-009` |

---

## 8. 外部接口与集成 【补充】

> 本需求不直接对外暴露 HTTP 路由（路由与异常状态码映射由 `005-api-auth-governance` 在 `api/` 与 `main.py` 挂载），也不直接发起大模型或统一网关网络请求；以下列出本层向上下层提供的边界协作契约：

| 接口/系统 | 方向 | 交互内容 | 是否新增 | 关联需求 | 备注 |
| --- | --- | --- | --- | --- | --- |
| `domain/` 资源模型与静态门禁（`001`） | 出站内部调用 | `Publisher.publish` 与 `ResourceService` 调用 `load_resource_dir`、`validate_all` 与解析器 | 否（既有内部契约） | `FR-004`、`FR-005` | `Publisher` 仅阻断新引入的 `error` |
| `api/` 路由与 `main.py` 异常处理（`005`） | 入站内部调用 | 消费 `ResourceService`、`Publisher`、`RunStore`、`CaseStore`、`RuntimeConfigStore` 并映射异常至 HTTP 400/404/409/422 | 否（既有内部契约） | `FR-004`–`FR-009` | 禁止在 `store/` 耦合 FastAPI 响应对象 |
| `Container.apply_runtime_config`（`003`/`004`） | 联动热生效回调 | 消费 `RuntimeConfigStore.to_effective_settings` 生成生效配置并触发网关、模型与运行器重建 | 否（既有内部契约） | `FR-008`、`FR-009` | 仅网关签名变更时触发 `ReloadableGatewayClient.swap` |

### 8.1 出站网关与模型接口契约摘要（涉及时填写）

> 本需求不涉及新增/变更出站外部接口，沿用既有网关或模型客户端；运行期参数修改通过 `RuntimeConfigStore` 持久化后交由 `Container.apply_runtime_config` 刷新下游运行时与连接池。

### 8.2 三类独立交付物涉及情况

| 独立文档 | 涉及情况 | 判断依据与范围摘要 | 确认来源/日期及关联需求 |
| --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求仅提供内部文件化存储、Git 封装、配置仓与 CLI，不新增对外 HTTP/SSE/postMessage 集成接口 | 归档重构指令确认（2026-11-16）；`FR-001`–`FR-010` |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求仅在 `cli init` 触发通用初始化流程，生产 33 套模板迁移资产清单归属 `008-java-migration-delivery` 与 `src/report_agent/seed/` | 归档重构指令确认（2026-11-16）；`FR-010` |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 运行期 48 项配置与环境变量模型已稳定随应用代码交付且支持免重启热更新，本次归档不涉及容器镜像或新增环境变量变更 | 归档重构指令确认（2026-11-16）；`FR-008`–`FR-010` |

---

## 9. 边界与约束 【补充】

### 9.1 范围边界

**本次需求包含（In Scope）：**

- `src/report_agent/store/` 全量 11 个模块：`__init__.py`、`fsutil.py`、`layout.py`、`git_repo.py`、`drafts.py`、`releases.py`、`publisher.py`、`service.py`、`runs.py`、`cases.py`、`runtime_config.py`。
- `src/report_agent/config.py`（`Settings` 与 40 项非可空空白兜底）与 `src/report_agent/cli.py`（`serve`/`init`/`user add`）。
- 对应存储、并发、权限与热更新测试套件：`tests/test_store.py`、`tests/test_review_storage.py`、`tests/test_runtime_config_hot_reload.py`。

**本次需求不包含（Out of Scope）：**

- 外部关系型数据库、Redis 分布式锁或多副本横向扩缩容共享锁机制。
- FastAPI REST 路由、Cookie/HMAC 会话鉴权、登录防爆破与 `main.py` 异常处理绑定（归属 `005-api-auth-governance`）。
- 嵌入式聊天窗口分片会话持久化 `ChatStore`（归属 `007-embed-chat-router`，仅共享 `DataLayout.chats` 目录定位与留存清理联动）。
- `Container` 运行器与 `ReloadableGatewayClient` 具体重建实现（分别归属 `003` 与 `004`）。

### 9.2 技术与业务约束

- **单进程硬约束（`workers=1`）**：进程内 `RLock`、单后台写协程及所有内存 LRU/指纹缓存均要求单进程部署，`cli.py` 严禁修改 `workers=1`。
- **零凭据硬编码约束**：任何代码、测试样例与文档不得包含真实 `LLM_API_KEY`、工作台口令或正式 `ra_` 密钥；测试使用临时目录与模拟脱敏占位值。
- **POSIX 与非 POSIX 兼容约束**：依赖同文件系统原子 `os.replace` 与 `os.symlink`；权限加固函数 `_chmod_safe` 须容错处理不支持权限位的挂载卷。

---

## 10. 异常场景与边界情况 【核心】

| 编号 | 场景描述 | 触发条件 | 预期处理方式 | 是否阻断主流程 | 优先级 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- |
| EX-001 | 路径穿越与末端外部软链接清理 | 入参含 `..`、`\x00` 或资源树中存在指向根目录外的软链接 | `ensure_within` 抛 `InvalidResource`；删除/覆盖资源树时 `ensure_entry_within` 仅 `unlink` 软链接自身而不追踪删除外部目标目录 | 否（外部目标零损坏，非法请求被拒绝） | 高 | `FR-002`、`FR-005` |
| EX-002 | Git 命令注入与首次提交失败回滚 | 提交号含 `--help` 等非 hex 字符，或空仓库首次发布失败执行 `reset_to(None)` | `_check_commit` 拦截非 `7~64` 位 hex 串抛 `GitError`；`reset_to(None)` 删除 `refs/heads/main`、重建未诞生符号引用并清空工作区使 `head()` 归 `None` | 是（终止异常发布，保留草稿） | 高 | `FR-003`、`FR-004` |
| EX-003 | 容器注入空字符串环境变量 | 容器编排注入 `RELEASES_KEEP=""`、`LLM_TEMPERATURE="  "` 等空白非可空字段 | `Settings._fallback_blank_non_nullable_scalars` 剔除 `_NON_NULLABLE_SCALAR_FIELDS`（40 项）中的空白项，交由 `Field` 默认值兜底，同时保留 4 项可空字段为 `None` | 否 | 中 | `FR-010` |
| EX-004 | POSIX 敏感文件写入权限裸露与非 POSIX 卷兼容 | 并发进程读取刚创建的敏感配置文件，或底层挂载卷不支持 `chmod` | `atomic_write_bytes` 在 `mkstemp` 后先 `os.fchmod(fd, 0o600)` 再写入；`_chmod_safe` 捕获 `OSError` 防止非 POSIX 卷启动崩溃 | 否 | 高 | `FR-002`、`FR-009` |
| EX-005 | `cli init` 遇外部运行中事件循环 | 异步测试框架或外层已运行 `asyncio` 循环时执行 `cli.main(["init"])` | 检测 `asyncio.get_running_loop()`：无循环走 `asyncio.run`，有循环则挂接 `create_task` 并记入 `_BG_TASKS` 强引用避免 `RuntimeError` | 否 | 中 | `FR-010` |
| EX-006 | 运行账本索引损毁或详情文件丢失 | `runs/YYYY/MM/DD/index.jsonl` 尾部半行截断、存在孤儿 `.json` 或 `<runId>.json` 损坏 | `read_jsonl` 自动跳过坏行；启动 `_recover_all_orphans` 补齐孤儿索引；详情缺失时 `_detail_from_summary` 自动降级构造详单并标记 `recoveredFromIndex: True` | 否 | 高 | `FR-006` |

---

## 11. 待确认事项 【核心】

> 本规格已于 2026-11-16 完成代码实装与全量测试归档验收，历史上设计边界均已拍板落地，当前无未关闭阻塞项。

| 编号 | 问题描述 | 影响范围 | 责任方 | 期望确认日期 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| Q-001 | 紧急切回历史版本 `r1` 后再发起新发布时，应以 Git `HEAD` 还是当前线上指针 `live_rev` 为基准树 | `FR-004`、`Publisher.publish` | 架构与发布治理负责人 | 2026-11-11 | 已关闭 | 必须以当前 `releases.live_rev()` 为基准树构建新版本，彻底杜绝已紧急下线的错误内容随后续发布重新带上线 |
| Q-002 | 启动阶段 `current.json` 丢失或写坏时，应自动恢复历史 `revisions/cN.json` 还是退回环境变量 | `FR-009`、`RuntimeConfigStore` | 运维与后端核心研发 | 2026-11-13 | 已关闭 | 倒序扫描 `index.jsonl` 与 `revisions/c*.json` 从最近合法不可变快照自动恢复，避免线上热调优参数丢失 |

---

## 附录：原始需求描述 【补充】

```text
子规格编号：002-git-store-hot-reload（RA-002，33.0 人天，18 项任务）
需求定位：智能申告报告填写与资源治理平台（report-agent）全栈研发工作拆分 —— 负责零外部数据库的文件化存储拓扑与防路径穿越原子写入、内部 Git 版本发布与软链紧急切换、乐观锁草稿叠加缓存、单写者异步运行账本、回归用例存储及 48 项运行期配置 0600 热更新持久化。
归档转换指令：严格按改造后中文 Spec-Kit 模板与 SDD 标准重构为 spec.md / plan.md / tasks.md 三件套，保留真实源码与测试路径、4 个 User Story、FR-001~FR-010 与 33.0 人天（18 项任务）配比，并核验章节完备性与零占位符红线。
```

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 完成 `002-git-store-hot-reload` 存量模块需求、设计与任务初版归档拆分 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 依据改造后中文 `.specify/templates/spec-template.md` 与 `/sdd-documentation` 标准重构全章节、补充取证分级、AC 列表、NFR/EX/Q 追踪及三类独立交付物台账 |

---

## 增量更新说明

> 本文档按 `report-agent` 中文 Spec-Kit 模板与 SDD 取证规范生成；后续如有范围或契约变更，同步更新对应章节与 `变更记录` 并联动刷新 `plan.md` 与 `tasks.md`。
