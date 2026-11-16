---
description: "基于需求设计的 Spec Kit 实现任务清单（RA-008 Java 全量业务资产自动化迁移、四层黄金对拍与容器化一体交付）"
---

# 任务说明（Implementation Tasks）：Java 全量业务资产自动化迁移、四层黄金对拍与容器化一体交付

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：本文件承接 `spec.md` 与 `plan.md`（`<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->` 内联四章），将设计切片转化为顺序清晰、带文件路径、可独立验证的 12 项任务清单（共 `19.0` 人天）。第 3 章权威清单已对照真实测试、结构对拍与构建验证证据全部勾选 `[X]` 归档。

---

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-008` |
| 需求名称 | Java 全量业务资产自动化迁移、四层黄金对拍与容器化一体交付 |
| 对应需求文档 | `./spec.md` |
| 对应设计文档 | `./plan.md` |
| tasks 版本 | 2.0 |
| 核算工作量 | 19.0 人天 |
| 状态 | 已完成（归档验收） |
| 负责人 | AiCoding (codex) |

---

## 0. 使用方式（给 AI 的执行指令） 【核心】

1. 按第 3 章权威任务清单顺序推进；标记 `[P]` 的任务可与同组无冲突任务并行，但不得越过前置阻塞依赖。
2. 权威复选框仅存在于第 3 章，格式为 `- [X] T001 [P?] [USx?] 描述（含精确文件路径与工时）`；其他章节仅引用 `T*` 编号，不重复建复选框。
3. 每完成一项任务，在第 3.5 节同步更新实际变更文件与真实执行的验证命令及通过输出；无实测或构建证据不得勾选完成 `[X]`。
4. 若遇需求歧义或现状冲突，停止扩大实现并登记于第 9 节 `BQ-*`，回链 `spec.md` `Q-*`。

---

## 1. 需求到任务映射（Traceability） 【核心】

| 需求/标准 ID | 摘要 | 对应设计（Plan.md） | 映射任务 ID | 测试/验证映射 | 状态 |
| --- | --- | --- | --- | --- | --- |
| US1 / SC-001, SC-002 | 33 模板、11 Skill 与 3 XML 契约迁修与缺陷治理 | 第 1.3、3、4、6 章 | `T001`、`T002`、`T003`、`T005`、`T006`、`T007` | `TT-01`、`TT-02` | 已验证 |
| US2 / SC-003 | 四层黄金对拍（S1～S9/Pebble/XML/Groovy）与回归测试 | 第 3、5、6、10 章 | `T004`、`T008`、`T009` | `TT-01`、`TT-03`、`TT-04` | 已验证 |
| US3 / SC-004, SC-005 | 非 root 一体化容器、反代子路径适配与 46 篇 Wiki 体系 | 第 3、8、9、12 章 | `T010`、`T011`、`T012` | `TT-05`、`TT-06`、`TT-07` | 已验证 |
| FR-001 | `generate.py` 幂等生成与 `pebble_to_jinja` / `115` 守卫 | 第 3、6 章 | `T001`、`T002`、`T003` | `TT-01` | 已验证 |
| FR-002 | 生产 `seed/` 齐备、`validate_all()` 0 警告与无 `客户号码` 冲突 | 第 4、10 章 | `T005`、`T007` | `TT-01`、`TT-02` | 已验证 |
| FR-003 | 11 个确定性工具 Skill 与 R2/R4/R5/R8/R17 缺陷修复 | 第 1.3、6、10 章 | `T005`、`T006`、`T007` | `TT-02`、`TT-03` | 已验证 |
| FR-004 | `verify_structure.py` S1～S9 结构与 S8/S9 AST 门禁 | 第 3、6.2、10 章 | `T008` | `TT-01` | 已验证 |
| FR-005 | 三大 Java Harness 对拍（渲染/XML/Groovy）与 `smoke_run.py` | 第 5、10 章 | `T004`、`T008`、`T009`、`T012` | `TT-03`、`TT-04` | 已验证（含条件注明） |
| FR-006 | `tests/test_migrated_seed.py` 自适应跳过外部依赖回归套件 | 第 10 章 | `T009`、`T012` | `TT-02`、`TT-03` | 已验证 |
| FR-007 | 三阶段 `Dockerfile`、`USER 2000`、`workers=1`、子路径中间件与 CI | 第 7、8、9、12 章 | `T010` | `TT-05`、`TT-07` | 已验证 |
| FR-008 | 46 篇遵循 `wiki/SCHEMA.md` 规范的 LLM Wiki 知识体系 | 第 3、4、13 章 | `T011`、`T012` | `TT-06` | 已验证 |
| NFR-001 ~ NFR-005 | 零硬编码、AST 防线、非 root 单进程、零凭据与隔离可复现 | 第 7、11 章 | `T003`–`T012` | `TT-01`–`TT-07` | 已验证 |
| EX-001 ~ EX-005 | 缺 JDK 跳过、模板 `116` 白名单、动态时间戳、空格对齐与反代前缀 | 第 6.2 节、第 10 章 | `T008`、`T009`、`T010` | `TT-01`、`TT-03`、`TT-05` | 已验证 |
| Q-001, Q-002 | 模板 `116` 历史渠道字面量及孤立规则/单位/重试挂账 | 第 15 章 | `T008`、`T011`、`T012` | `TT-01`、`TT-06` | 挂账追踪（非阻塞） |

### 1.1 三类独立交付物维护台账

| 独立交付物 | 涉及情况与依据 | 关联任务 | 维护状态 | 验证结果 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 不生成（契约存于 `seed/apis/*.yaml` 与 `wiki/reference/apis-catalog.md`） | 不生成 | 已由 `T007`、`T012` 与 `test_migrated_seed.py` 校验 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 不生成（清单存于 `tools/java_migration/{TEMPLATES.md,MAPPING.md}`） | 不生成 | 已由 `T005`、`T008` 与 `verify_structure.py` 校验 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs/Dockerfile 中） | 不生成（配置存于 `.env.example`、`Dockerfile` 与 `wiki/guides/dev-test-and-deploy.md`） | 不生成 | 已由 `T010` 静态审查与 `pytest`/`build` 验证 |

---

## 2. 里程碑与切分策略（Milestones） 【补充】

| 阶段 / Milestone | 目标 | 任务范围 | 阶段工时（人天） | 验收定义 |
| --- | --- | --- | --- | --- |
| Phase 1: 准备（Setup） | Java 原模板与规则盘点分析工具、锁定 ID 映射与描述字典 | `T001`–`T002` | 2.5 | 原模板变量/规则清点与映射表锁定完成 |
| Phase 2: 基础前置（Foundational） | 配置驱动生成器引擎与三大 Java 黄金标准 Harness 开发 | `T003`–`T004` | 3.5 | 自动化生成通道与 Java 标准答案程序就绪 |
| Phase 3: 用户故事 1（P1 🎯 MVP） | 全量 33 模板、11 填报 Skill 与 3 XML 契约迁修及缺陷修复 | `T005`–`T007` | 5.5 | `validate_all()` `0 errors, 0 warnings` |
| Phase 4: 用户故事 2（P1 🎯 MVP） | 四层黄金对拍脚本与自适应跨越 Java 依赖的回归测试套件 | `T008`–`T009` | 3.5 | `verify_structure.py` S1~S9 与 `test_migrated_seed.py` 通过 |
| Phase 5: 用户故事 3（P2） | 三阶段一体化非 root 容器、子路径反代适配与 46 篇 Wiki | `T010`–`T011` | 2.5 | 容器/反代配置与 46 篇 Wiki 规范闭环 |
| Phase 6: 收尾与门禁（Polish） | 对拍回归验收、迁移账本与 Wiki 一致性及构建静态门禁收敛 | `T012` | 1.5 | 全套命令验证与台账实测记录齐全 |
| **合计** | **全周期工作量汇总** | **`T001`–`T012`（12 项）** | **19.0** | **全部交付物完成归档验收** |

### 2.1 依赖与交付顺序

- **阶段依赖**：Phase 1（分析与字典建库） → Phase 2（生成器与 Java Harness 底座，阻塞迁移与对拍） → Phase 3（US1 全量生产资源生成与修复） → Phase 4（US2 四层对拍与回归固化），Phase 5（US3 容器化与 Wiki 体系）在核心资源接口稳定后同步收敛 → Phase 6（Polish 全量收口验收）。
- **并行机会**：`T002` 与 `T001`、`T004` 与 `T003`、`T007` 与 `T005`/`T006`、`T009` 与 `T008`、`T011` 与 `T010` 相互独立，已标注 `[P]`。

---

## 3. 任务清单（按执行顺序） 【核心】

> 格式约束：`Setup`、`Foundational`、`Polish` 阶段严禁使用 `[USx]` 标签；`User Story` 阶段必须带 `[USx]` 标签；`[P]` 位于 `Txxx` 之后、`[USx]` 之前；每行明确文件路径与工时。

### 3.1 Phase 1: Setup (Shared Infrastructure)

- [X] T001 实现前代 Java Pebble 模板、`.rule` 规则及 `field-mappings.yml` 静态分析辅助工具，并编写迁移手册与差异映射文档，文件：`tools/java_migration/analyze_java.py`、`tools/java_migration/README.md`、`tools/java_migration/MAPPING.md`（1.5 人天）
- [X] T002 [P] 固化 Java 资源库 100～132 生产模板编码与 ID 一对一锁定映射及逐模板业务适用场景说明字典，文件：`tools/java_migration/template_ids.yaml`、`tools/java_migration/template_descriptions.yaml`（1.0 人天）

### 3.2 Phase 2: Foundational (Blocking Prerequisites)

- [X] T003 编制全库字段语义字典并实现幂等模板自动化生成脚本（含 `pebble_to_jinja` 转换、模板 `115` 占位符守卫、隐式依赖与 `visible` 自动推导及 `TEMPLATES.md` 同步输出），文件：`tools/java_migration/field_catalog.yaml`、`tools/java_migration/generate.py`（2.0 人天）
- [X] T004 [P] 开发对接前代 Java 编译产物与 Maven 依赖的三大黄金基准程序（Pebble 渲染引擎、Jackson 3 XML 序列化器及 Groovy 脚本执行引擎），文件：`tools/java_migration/harness/PebbleRenderHarness.java`、`tools/java_migration/harness/JavaXmlRequestHarness.java`、`tools/java_migration/harness/JavaSkillGoldenHarness.java`（1.5 人天）

### 3.3 Phase 3–5: User Stories (P1 → P2)

#### Phase 3: User Story 1 - 全量业务资产自动化迁移与历史缺陷主动修复 (Priority: P1) 🎯 MVP

**目标**：全量生成 33 套生产模板、11 个确定性工具填报 Skill 与 3 套 XML 契约，并主动消除发布告警及 R2/R4/R5/R7/R8/R17 缺陷。

**独立测试**：运行 `tests/test_migrated_seed.py` 校验 `seed` 加载 0 error / 0 warning、无同名「客户号码」告警及所有历史缺陷修复分支工作正常。

- [X] T005 [US1] 重建生成 33 套生产报告模板（`100..132`），完成 `105`/`108`/`112`/`120`/`129` 补齐可选 `deadlineDate`、消除 4 处同名「客户号码」发布警告、`121`/`标准资费` 改设 `derive` 及模板 `120`/`111`/`114`/`115` 占位符恒真死分支修复，文件：`src/report_agent/seed/templates/`、`tools/java_migration/TEMPLATES.md`（2.0 人天）
- [X] T006 [US1] 将 11 个前代 Groovy 脚本升级为基于平台 12 个确定性原语的纯文本 `SKILL.md` 并主动修复 R2（编号误识日期及无到期日跳过）、R5（`msisdn` 过滤/空 `grade` 判非靓号/多档顿号拼接）与 R8（纯年月整月展开）缺陷，文件：`src/report_agent/seed/skills/`（2.0 人天）
- [X] T007 [P] [US1] 迁移修正 3 个统一网关 XML 接口契约（注入 `${$now}`、补充真实返回列、`retry.maxAttempts=1` 与 `cc_pretty_num_info_query` 设置 `missingAs: failure`）及 6 份正例与无数据/失败 Mock 样例，文件：`src/report_agent/seed/apis/`、`src/report_agent/seed/mock-gateway/`（1.5 人天）

#### Phase 4: User Story 2 - 四层黄金标准自动化对拍与回归验证 (Priority: P1) 🎯 MVP

**目标**：交付 S1～S9 结构 AST 门禁、Pebble 逐字对拍、XML/Groovy 对拍及沙箱端到端冒烟工具链，并固化为跨环境自适应回归套件。

**独立测试**：运行 `verify_structure.py` 与 `uv run pytest tests/test_migrated_seed.py` 验证内置校验、AST 门禁与自适应外部 Java 跳过机制。

- [X] T008 [US2] 实现结构规则及 `S8`/`S9` AST 静态门禁校验脚本 `verify_structure.py`（含模板 `116` 已知上游枚举白名单）与真实 Java Pebble 多场景逐字渲染对拍脚本 `verify_render.py`，文件：`tools/java_migration/verify_structure.py`、`tools/java_migration/verify_render.py`（2.0 人天）
- [X] T009 [P] [US2] 实现报文与 Groovy 黄金对拍脚本 `check_skills.py`（含 7 项二期修复与空列表防线断言）、沙箱真模型冒烟工具 `smoke_run.py` 及跨环境自适应回归测试套件，文件：`tools/java_migration/check_skills.py`、`tools/java_migration/smoke_run.py`、`tests/test_migrated_seed.py`（1.5 人天）

#### Phase 5: User Story 3 - 前后端一体化容器交付与 Karpathy LLM Wiki 知识库沉淀 (Priority: P2)

**目标**：落地三阶段非 root 单进程一体容器构建、子路径反代中间件与 GHCR 发布工作流，并构建 46 篇遵循元规范的知识库。

**独立测试**：核查多阶段 `Dockerfile`/`.dockerignore`/`docker-entrypoint.sh`、`create_app()` 子路径剥离重定向，以及 `wiki/` 全库 frontmatter 与双向链接完整性。

- [X] T010 [US3] 实现前后端三阶段一体化容器定义、非 root `paasopt` 运行入口、环境模板、`workers=1` 单进程守护、`_SubpathPrefixMiddleware` 子路径剥离重定向与 GitHub Actions GHCR 发布流水线，文件：`Dockerfile`、`docker-entrypoint.sh`、`.dockerignore`、`.env.example`、`.github/workflows/docker-image.yml`、`src/report_agent/main.py`、`src/report_agent/config.py`、`src/report_agent/cli.py`（1.5 人天）
- [X] T011 [P] [US3] 制定 `wiki/SCHEMA.md` 元规范并构建涵盖总览、5 篇架构、6 篇组件、13 篇 Skill 卡片、5 篇 ADR 决策、5 篇实操指南、4 篇速查手册与 3 篇质量差异台账共 46 篇文档的知识体系，文件：`wiki/SCHEMA.md`、`wiki/index.md`、`wiki/log.md`、`wiki/overview.md`、`wiki/timeline.md`（1.0 人天）

### 3.4 Phase 6: Polish & Cross-Cutting Concerns

- [X] T012 执行迁移静态与全量回归门禁验证，核对 `MAPPING.md`/`README.md`/`TEMPLATES.md` 与 `wiki/` 全库一致性及实测交付证据，文件：`tools/java_migration/MAPPING.md`、`tools/java_migration/TEMPLATES.md`、`tests/test_migrated_seed.py`、`wiki/index.md`、`wiki/log.md`（1.5 人天）

### 3.5 任务详情与完成记录

#### 任务组：`T001`–`T007`（原资产分析、配置生成器、Harness 与 33/11/3 资产迁修）

- **关联需求**：`FR-001`～`FR-003`、`FR-005`、`US1`
- **关键变更点**：落地 `analyze_java.py`、`template_ids.yaml`（严格锁定 `100`～`132`）、`template_descriptions.yaml`、`field_catalog.yaml` 与 `generate.py`；开发三大 Java Harness；重建 33 套生产模板与 `TEMPLATES.md`，升级 11 个纯文本确定性工具 Skill、3 个 XML 契约与 6 份 `mock-gateway` 样例，集中完成 R2/R4/R5/R7/R8/R17 缺陷治理并清除说明中的冗余 Java 对照尾注。
- **验证方式与实测证据**：本轮实测 `uv run pytest -q`（`196 passed in 51.41s`）包含 `tests/test_migrated_seed.py` 全部生产回归用例（`test_prod_seed_loads_and_validates_zero_warnings`、`test_no_customer_phone_input_collision`、`test_template_120_deposit_else_branch_fix`、`test_pretty_number_fields_config`、`test_batch2_seed_consistency_fixes`、`test_prod_seed_template_ids_match_java_resource_db`）全部通过，`validate_all()` 保持 `0 errors, 0 warnings`。
- **状态与阻塞**：已完成；无工程阻塞。

#### 任务组：`T008`–`T009`（四层黄金对拍工具链与跨环境自适应回归测试）

- **关联需求**：`FR-004`～`FR-006`、`US2`、`EX-001`～`EX-004`
- **关键变更点**：落地 `verify_structure.py`（S1～S9 + S8/S9 AST 静态门禁与模板 `116` 白名单）、`verify_render.py`、`check_skills.py`（含 `verify_phase2_bug_fixes` 7 项专项断言）、`smoke_run.py` 与 `tests/test_migrated_seed.py`。
- **验证方式与实测证据**：
  1. 本轮实测 `uv run python tools/java_migration/verify_structure.py`：检查模板 33 个、Skill 12 个、接口 3 个，发布校验 `0 errors, 0 warnings`，S8/S9 AST 门禁全部通过（含模板 `116` 已知上游白名单提示）。
  2. 本轮实测 `uv run pytest -q`：`196 passed in 51.41s`，其中 `tests/test_migrated_seed.py` 已在 196 条全量回归中执行通过（自动覆盖无 Java 环境内置断言、外部条件用例与 `check_skills.py`）；注：`verify_render.py` / `check_skills.py` 单独外跑及 `smoke_run.py`（需真实 LLM API Key）未在本轮 SDD 归档阶段独立拉起外部进程重跑。
- **状态与阻塞**：已完成；`Q-001`（模板 `116` 渠道字面量业务收敛）按设计挂账不阻塞工程交付。

#### 任务组：`T010`–`T012`（一体容器、反代子路径、46 篇 Wiki 与全栈验收收口）

- **关联需求**：`FR-007`、`FR-008`、`US3`、`EX-005`、`NFR-001`～`NFR-005`
- **关键变更点**：落地三阶段 `Dockerfile`、`USER 2000`、`docker-entrypoint.sh`、`workers=1`、`_SubpathPrefixMiddleware` 与 GHCR 工作流；建成遵循 `wiki/SCHEMA.md` 的 46 篇 Wiki 知识库并核对 `MAPPING.md`/`TEMPLATES.md` 台账。
- **验证方式与实测证据**：
  1. `uv run pytest -q`：全量 `196 passed in 51.41s`（含 `tests/test_migrated_seed.py`）。
  2. `uvx ruff@0.11.0 check src tests`：`All checks passed!`。
  3. `cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json && npm run build`：`vue-tsc` 0 错误、`3415 modules transformed`、`built in 5.80s`、`dist/embed.html` 洁净无重型 chunk（确认 `VITE_BASE_PATH=./` 相对资源输出与容器阶段 1 一致）。
  4. `uv run python tools/java_migration/verify_structure.py`：模板 33 个、Skill 12 个、接口 3 个，`0 errors, 0 warnings`，S8/S9 AST 门禁通过。
- **状态与阻塞**：已完成；无工程阻塞。

---

## 4. 子任务拆解（可选） 【补充】

本需求 `T001`–`T012` 已涵盖所有脚本、生产资产、测试套件、容器配置与知识库落点，粒度适中，无需额外子任务拆解。

---

## 5. 代码实现约束（仅本需求新增） 【补充】

- **并发与一致性**：`cli.py` 与 `docker-entrypoint.sh` 固定 `workers=1` 确保单进程文件读写与内存状态一致；`generate.py` 严格保持幂等覆写且由 `template_ids.yaml` 锁定 `100`～`132` 编号。
- **安全与隐私边界**：容器运行必须切换非 root `USER 2000`（`paasopt`）；`.dockerignore` 禁止打包 `.env`、`data`、`tests`、`tools` 与 `wiki`；`.env.example` 与 `wiki/` 严禁出现任何真实凭证或生产客户信息。
- **错误与降级语义**：`cc_pretty_num_info_query` 通过 `missingAs: failure` 拦截顶层网关故障不误判为非靓号；`tests/test_migrated_seed.py` 缺失 JDK 时优雅跳过外部 Java Harness 并强制执行内置全量校验。

---

## 6. 测试任务矩阵（Test Tasks） 【核心】

| 测试编号 | 类型 | 测试场景与关注点 | 关联任务 | 测试路径 | 验证命令与结果 |
| --- | --- | --- | --- | --- | --- |
| TT-01 | 静态结构与 AST 门禁 | S1～S9（模板集合/正文一致/字段可见/非空说明/Skill与API/循环列/`validate_all` 零警告/S8占位符守卫/S9枚举字面量） | `T003`、`T005`、`T008` | `tools/java_migration/verify_structure.py` | `uv run python tools/java_migration/verify_structure.py`（检查模板 33 个、Skill 12 个、接口 3 个，`0 errors, 0 warnings`，S8/S9 通过） |
| TT-02 | 生产 `seed` 回归测试 | `validate_all` 零警告、`template-router` 33 模板覆盖、无 `客户号码` 冲突、`120`/`121`/`标准资费`/`111`/`114`/`115`/`deadlineDate` 修复与 ID 匹配 | `T005`、`T006`、`T007`、`T009` | `tests/test_migrated_seed.py` | `uv run pytest -q`（全量 `196 passed in 51.41s`，已覆盖通过） |
| TT-03 | 协议/Groovy/7 项修复对拍 | 3 XML 报文与 `xml-nytool` 逐字一致、Mock 样例校验、11 Skill 模拟对拍与 `verify_phase2_bug_fixes` 7 项断言 | `T004`、`T006`、`T007`、`T009` | `tools/java_migration/check_skills.py`、`tests/test_migrated_seed.py` | 已由 `test_migrated_seed.py#test_skills_and_phase2_bug_fixes` 在 `uv run pytest -q`（`196 passed in 51.41s`）中执行通过（注：单独外部 CLI 在本轮未另行重跑） |
| TT-04 | Pebble 渲染与端到端冒烟 | Java `PebbleRenderHarness` 千级组合场景逐字渲染比对及临时沙箱真模型试跑 | `T004`、`T008`、`T009`、`T012` | `tools/java_migration/verify_render.py`、`tools/java_migration/smoke_run.py` | `verify_render.py` 已接入 `test_migrated_seed.py`（具备 JDK 时自动跑）；`smoke_run.py` 依赖真实 LLM 密钥故未在本轮无密钥归档环节重跑 |
| TT-05 | 前端与反代多入口构建 | `VITE_BASE_PATH=./` 相对基址编译 `index.html` 与 `embed.html` 适配容器阶段 1 与子路径反代 | `T010`、`T012` | `frontend/`、`Dockerfile` | `cd frontend && npx vue-tsc --noEmit -p tsconfig.app.json && npm run build`（`vue-tsc` 0 错误、`3415 modules transformed`、`built in 5.80s`、`dist/embed.html` 洁净无重型 chunk） |
| TT-06 | Wiki 知识库规模与格式核查 | 46 篇文档结构、frontmatter、相对链接、零行号与 `log.md` 只追加审计 | `T011`、`T012` | `wiki/` | 已核对 `find wiki -name '*.md'` 共 46 篇，`SCHEMA.md`、`index.md`、`log.md` 完备一致 |
| TT-07 | Python 静态代码检查 | 后端与迁移回归相关代码风格与类型检查 | `T010`、`T012` | `src/`、`tests/` | `uvx ruff@0.11.0 check src tests`（`All checks passed!`） |

---

## 7. 发布任务清单（Release Tasks） 【核心】

| 发布编号 | 动作内容 | 前置依赖 | 验证与完成标准 | 回滚动作 | 关联任务 |
| --- | --- | --- | --- | --- | --- |
| RT-01 | 静态门禁与全量回归收敛 | `T001`–`T009` | `verify_structure.py` `0 errors, 0 warnings`、`pytest` 196 passed、`ruff` 0 告警 | 回退变更提交 | `T012` |
| RT-02 | 构建多阶段一体 Docker 镜像（`VITE_BASE_PATH=./`、`USER 2000`） | `RT-01` | 前端 build 0 错误、`.dockerignore` 剔除冗余目录、`ghcr.io` 推送或本地加载成功 | 切换上一稳定镜像 Tag | `T010` |
| RT-03 | 挂载 PVC `/data`、按需设 `APP_ROOT_PATH` 启动单进程服务并检查 `/healthz` | `RT-02` | `report-agent serve` 以 `workers=1` 启动，`/healthz` 返回 `UP` 与 `liveRev=r1+` | 置空 `APP_ROOT_PATH` 或回滚镜像与 `releases/current` | `T010`、`T012` |

---

## 8. 可观测性与验收（Observability & Acceptance） 【补充】

### 8.1 关键过程事件、日志与审计点位

| 场景 | 载体（过程事件 / 日志 / 审计） | 关键上下文字段 | 隐私脱敏约束 |
| --- | --- | --- | --- |
| 迁移结构与 AST 校验 | CLI 标准输出 | 校验模板/Skill/接口数量、`error`/`warning` 计数与 `S9` 白名单提示 | 只输出静态字段名与枚举字面量，不涉及客户生产数据 |
| 容器冷启动引导 | `docker-entrypoint.sh` 标准输出 | `HOST:PORT`、`DATA_DIR`、`FRONTEND_DIST`、`APP_ROOT_PATH`、`GATEWAY_MODE`、`LLM_MODEL` | 仅打印配置摘要与空/默认 `LLM_API_KEY` 警告，严禁回显任何密钥值 |
| Wiki 知识演进追踪 | `wiki/log.md` | 日期、操作类型（`ingest`/`lint`/`query`）、变更文件与结论摘要 | 按 `wiki/SCHEMA.md` 严禁记录凭据与易变源码行号 |

### 8.2 验收清单

- 全部 12 项权威任务（`19.0` 人天）已核对源码、脚本、容器文件与 46 篇 `wiki/` 文档完成验收。
- `verify_structure.py`（S1～S9）、`uv run pytest -q`（196 passed）、`ruff check` 与前端构建均取得实测通过证据，且条件未跑项（独立外部 JDK `verify_render` / 真实 LLM `smoke_run`）已如实标明边界。
- 历史挂账事项 `Q-001`、`Q-002` 已与 `wiki/lint/open-questions.md` 双向打通，不阻塞工程交付。

---

## 9. 阻塞与待确认（Blockers & Open Questions） 【核心】

当前无工程实现阻塞问题（以下两项业务口径挂账事项已按兼容等价与白名单机制安全隔离，待业务侧后续拍板调整）。

| 编号 | 问题描述 | 关联 Spec Q-* | 影响任务 | 责任方 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| BQ-1 | 模板 `116`（第 38 行）源自上游 Java 的 5 个历史渠道字面量收敛方式 | `Q-001` | `T008`、`T011`、`T012` | 业务产品负责人 | 待业务确认（非工程阻塞） | 已在 `verify_structure.py` `KNOWN_UPSTREAM_ENUM_MISMATCHES` 白名单隔离并追踪于 `wiki/lint/open-questions.md` |
| BQ-2 | 孤立 `.rule` 字段处置、`BOSS_QryBalanceFlowLog` 充值金额单位展示及契约重试次数（1 vs 2） | `Q-002` | `T007`、`T011`、`T012` | 业务运营与网关对接方 | 待业务确认（非工程阻塞） | 按等价策略运行，待灰度真实报文验证后通过模板/契约草稿发布调整 |

---

## 10. 变更记录（Changelog） 【补充】

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding (codex) | 完成 008 子规格 12 项任务拆解与 19.0 人天验收归档 |
| 2.0 | 2026-11-16 | AiCoding (codex) | 按改造后中文 Spec-Kit 任务模板重整为第 0～10 章规范结构，严格统一第 3 章任务清单格式与工时配比，补充 `verify_structure.py` 及 196 条全量实测证据与外部条件项如实说明 |

---

## 附录 A：任务依赖简图

```text
Phase 1 Setup (T001, T002)
  └──> Phase 2 Foundational (T003, T004)
         └──> Phase 3 US1 (T005, T006, T007)
                └──> Phase 4 US2 (T008, T009)
                       ├──> Phase 5 US3 (T010, T011)
                       └──────────────┴──> Phase 6 Polish (T012)
```

## 附录 B：AI 执行提示

1. 修改 `src/report_agent/seed/` 或 `tools/java_migration/field_catalog.yaml` 前，先阅读 `spec.md` 第 9 节边界与 `plan.md` 第 1.4 节禁止修改范围（禁止改动 `100`～`132` ID 或取消 `workers=1`）。
2. 所有已勾选 `[X]` 任务均已对照实测输出核验；若修改迁移规则，须重跑 `generate.py`、`verify_structure.py` 与 `pytest tests/test_migrated_seed.py` 后更新实测记录。

---

## 增量更新说明

> 本文档依据改造后中文 Spec-Kit 模板与 `/sdd-documentation` 标准维护；后续若确认关闭 `Q-001`/`Q-002`、增补模板或调整镜像策略，须同步刷新第 1 节映射表、第 3.5 节实测记录与第 10 节变更记录。
