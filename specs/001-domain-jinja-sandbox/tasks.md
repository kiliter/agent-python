---
description: "声明式领域模型、全量交叉校验与 Pebble 兼容 Jinja2 沙箱渲染引擎任务清单（RA-001）"
---

# 任务说明（Implementation Tasks）：声明式领域模型、全量交叉校验与 Pebble 兼容 Jinja2 沙箱渲染引擎

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：本文件承接 `spec.md` 与 `plan.md`（`<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->` 内联四章），将设计切片转化为顺序清晰、带文件路径、可独立验证的任务清单。不适用章节保留标题并注明 `本需求不涉及` 及依据；全量 18 项任务均已完成验证归档。

---

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-001` |
| 需求名称 | 声明式领域模型、全量交叉校验与 Pebble 兼容 Jinja2 沙箱渲染引擎 |
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
| `US1` / `SC-003` | 双文件模板建模、防 ReDoS 正则编译与入参快速校验 | 第 3.1、5.1、6.2 节 | `T001`–`T003`、`T006`–`T008` | `TT-01`、`TT-02` | 已验证 |
| `US2` / `SC-002`、`SC-004` | Pebble 兼容 Jinja2 沙箱与 `TrackedValue`/`TrackedList` 渲染追踪 | 第 3.1、5.1、6.1 节 | `T005`、`T009`–`T011`、`T017` | `TT-03`、`TT-04` | 已验证 |
| `US3` / `SC-005` | 纯文本 `SKILL.md` 解析与双协议 `ApiContract` 契约 | 第 3.1、5.1、5.2 节 | `T002`、`T012`–`T014`、`T017` | `TT-05`、`TT-06` | 已验证 |
| `US4` / `SC-001` | 安全目录加载 `load_resource_dir` 与 40 项 `validate_all` 门禁 | 第 3.2、5.1、6.1 节 | `T004`、`T015`–`T016`、`T018` | `TT-07`、`TT-08` | 已验证 |
| `FR-001`–`FR-002` | `TemplateDef`/`FieldDef`、`extra="forbid"`、防 ReDoS 原语与 `validate_inputs` | 第 3.1、5.1 节 | `T002`、`T003`、`T006`–`T008` | `TT-01`、`TT-02` | 已验证 |
| `FR-003`–`FR-005` | `_TrackedSandboxEnvironment`、`_PebbleNewlineTrimExtension`、`build_render_context` | 第 3.1、4.1、5.1 节 | `T005`、`T009`–`T011` | `TT-03`、`TT-04` | 已验证 |
| `FR-006`–`FR-008` | `parse_skill_markdown`、`ApiContract`、`${$now}` 保护、响应规范 | 第 3.1、5.1、5.2 节 | `T012`–`T014` | `TT-05`、`TT-06` | 已验证 |
| `FR-009`–`FR-010` | `_within_root`、`load_resource_dir` 与 `validate_all` 40 项诊断码 | 第 3.2、5.1、6.1 节 | `T004`、`T015`–`T016` | `TT-07`、`TT-08` | 已验证 |
| `NFR-001`–`NFR-006` | 零硬编码、防幻觉语义、协程隔离、防注入安全、可复现测试与编码规范 | 第 7、10、11 章 | `T003`–`T005`、`T017`–`T018` | `TT-02`、`TT-04`、`TT-08`、`TT-09` | 已验证 |
| `EX-001`–`EX-006` | 软链隔离、YAML `null`、`self` 键冲突、深括号 ReDoS、循环遮蔽、`${$now}` 保护 | 第 6.2 节 | `T003`–`T004`、`T008`、`T011`、`T014`、`T016`–`T017` | `TT-02`、`TT-04`、`TT-05`、`TT-07` | 已验证 |

### 1.1 三类独立交付物维护台账

| 独立交付物 | 涉及情况与依据 | 关联任务 | 维护状态 | 验证结果 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；见 `spec.md` 第 8.2 节） | 不生成 | 不生成 | 与 `spec.md` 第 8.2 节及 `plan.md` 第 1.8 节一致 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；见 `spec.md` 第 8.2 节） | 不生成 | 不生成 | 生产种子归 `008` 与 `src/report_agent/seed/` |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中；见 `spec.md` 第 8.2 节） | 不生成 | 不生成 | 无新增环境变量或容器变更 |

---

## 2. 里程碑与切分策略（Milestones） 【补充】

| 阶段 / Milestone | 目标 | 任务范围 | 阶段工时（人天） | 验收定义 |
| --- | --- | --- | --- | --- |
| Phase 1: 准备 | 初始化领域包标识、核心依赖与 `_Base` 严格契约基类 | `T001`–`T002` | `3.0` | `domain/` 包结构与文件名常量就绪 |
| Phase 2: 基础前置 | 建设显式栈防 ReDoS 原语、安全目录加载器与渲染追踪上下文 | `T003`–`T005` | `6.0` | ReDoS 检测、`_within_root`、`_ACTIVE_USED` 就绪 |
| Phase 3: 用户故事 1（P1） | 交付模板双文件建模、YAML 往返与运行前入参校验 | `T006`–`T008` | `6.5` | 四类字段、严格键检查与入参校验测试通过 |
| Phase 4: 用户故事 2（P1） | 交付 Pebble 兼容沙箱、`TrackedValue`/`TrackedList` 与唯一渲染上下文 | `T009`–`T011` | `6.0` | 逐字渲染等价、安全拦截与追踪测试通过 |
| Phase 5: 用户故事 3（P2） | 交付纯文本 `SKILL.md` 与双协议 `ApiContract` 契约 | `T012`–`T014` | `5.5` | Skill 解析、`${$now}` 保护与 5 模式测试通过 |
| Phase 6: 用户故事 4（P2） | 交付 `validate_all` 静态交叉门禁与生产种子零告警核验 | `T015`–`T016` | `3.5` | 40 项诊断码及 33 套生产模板 0 告警通过 |
| Phase 7: 收尾阶段 | 边界条件加固、注释标记核验、全量回归与 `ruff` 验收 | `T017`–`T018` | `2.5` | 全量 `pytest` 与 `ruff` 零告警通过 |

### 2.1 依赖与交付顺序

- **阶段依赖**：`Phase 1`（准备）→ `Phase 2`（基础前置，阻塞所有用户故事）→ `Phase 3`（`US1`，模板基础）与 `Phase 4`/`Phase 5`（`US2`/`US3`）→ `Phase 6`（`US4`，依赖 `US1`–`US3` 完整模型）→ `Phase 7`（边界加固与全量验收）。
- **并行机会**：`T004`（`resources.py`）与 `T005`（`jinja_env.py`/`render.py`）可与 `T003` 并行；`US2`（沙箱渲染）与 `US3`（Skill/ApiContract）分属独立文件模块，可并行开发；各 Story 的测试任务 `T008`、`T011`、`T014`、`T016` 可与后续阶段设计同步推进。

---

## 3. 任务清单（按执行顺序） 【核心】

### 3.1 Phase 1: Setup (Shared Infrastructure)

- [X] T001 梳理并初始化领域模型包标识及核心依赖规范，文件：`src/report_agent/domain/__init__.py`、`pyproject.toml`（1.5 人天）
- [X] T002 [P] 建立统一配置基类 `_Base`（`extra="forbid"`、`populate_by_name=True`）及模板/契约文件名常量约定，文件：`src/report_agent/domain/template.py`、`src/report_agent/domain/api_contract.py`（1.5 人天）

### 3.2 Phase 2: Foundational (Blocking Prerequisites)

- [X] T003 实现显式栈正则 AST 分析函数（`_subpattern_can_match_empty`、`_has_nested_repeat`）、`MAX_REGEX_LENGTH = 2000` 门禁及 `@lru_cache(maxsize=512)` 缓存原语 `safe_regex_compile` / `safe_regex_fullmatch`，文件：`src/report_agent/domain/template.py`（2.0 人天）
- [X] T004 [P] 实现诊断载体 `Issue`、资源容器 `ResourceSet`（含 `skill_by_ref`、`allowed_apis`）及防软链接越界加载框架 `_within_root` / `load_resource_dir`，文件：`src/report_agent/domain/resources.py`（2.0 人天）
- [X] T005 [P] 建立 `ContextVar` 追踪上下文 `_ACTIVE_USED` 及标准单字段渲染结果数据类 `FieldRender`，文件：`src/report_agent/domain/jinja_env.py`、`src/report_agent/runtime/render.py`（2.0 人天）

### 3.3 Phase 3–6: User Stories (US1–US4)

#### Phase 3: User Story 1 - 模板双文件建模与入参防 ReDoS 安全校验 (Priority: P1)

**目标**：完成 `template.yaml` 与 `body.md.j2` 双文件字段/列/入参建模及运行前防 ReDoS 入参快速失败校验。

**独立测试**：独立调用 `parse_template_yaml`、`dump_template_yaml`、`safe_regex_compile` 与 `validate_inputs` 校验四类字段、严格键检查及入参规则。

- [X] T006 [US1] 实现 `InputDef`、`ColumnDef`、`FieldDef`、`TemplateDef` 与 `Template` 模型，支持 `string`/`enum`/`date`/`list` 四类字段、`whenMissing` 三策略、`visible` 与 `quoteWhole` 约束，文件：`src/report_agent/domain/template.py`（2.5 人天）
- [X] T007 [US1] 实现 `parse_template_yaml`、`dump_template_yaml`、正文行号索引 `body_variable_lines` 及集成 `safe_regex_fullmatch` 的 `validate_inputs` 入参校验，文件：`src/report_agent/domain/template.py`、`src/report_agent/runtime/runner.py`（2.5 人天）
- [X] T008 [P] [US1] 编写并执行模板 YAML 往返解析、未知键 `extra="forbid"` 拦截及超长/超深嵌套与嵌套重复量词 ReDoS 拦截单元测试，文件：`tests/test_list_fields.py`、`tests/test_review_runtime.py`、`tests/test_text_and_gateway.py`（1.5 人天）

#### Phase 4: User Story 2 - 对齐 Java Pebble 3.2.2 的 Jinja2 不可变沙箱与 TrackedValue/TrackedList 分支展示追踪 (Priority: P1)

**目标**：实现与 Pebble 3.2.2 逐字等价的不可变 Jinja2 沙箱、过滤拼接追踪 `TrackedValue` 与仅循环记入追踪 `TrackedList`。

**独立测试**：独立调用 `build_render_context` 与 `render_body` 验证换行裁剪、沙箱安全拦截、`hasDigit` 测试及分支渲染 `used` 集合准确性。

- [X] T009 [US2] 实现 `_TrackedSandboxEnvironment`、词法单换行裁剪扩展 `_PebbleNewlineTrimExtension`、`hasDigit` 测试 `_test_has_digit`、危险全局符号移除与 `@lru_cache(maxsize=256)` 模板预编译缓存 `_compile_body_template`，文件：`src/report_agent/domain/jinja_env.py`（2.5 人天）
- [X] T010 [US2] 实现 `TrackedValue`、`_TrackedCodeGenerator`（接管 `~` 与 `+`）、过滤器包装 `_wrap_filter_func`、`TrackedList`、`_PlaceholderUndefined` 及 `field_render` / `build_render_context`，文件：`src/report_agent/domain/jinja_env.py`、`src/report_agent/runtime/render.py`（2.0 人天）
- [X] T011 [P] [US2] 编写并执行 Pebble 换行等价、沙箱拦截 `SecurityError`、`self` 键冲突规避、嵌套协程隔离及 `TrackedValue`/`TrackedList` 分支追踪测试，文件：`tests/test_list_fields.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_deep_audit_fixes.py`（1.5 人天）

#### Phase 5: User Story 3 - 纯文本 SKILL.md 与声明式双协议接口契约 ApiContract 建模 (Priority: P2)

**目标**：完成纯文本 `SKILL.md` 解析与支持 XML/JSON 双协议、`${$now}` 内置占位符、安全请求头及 5 种抽取模式的 `ApiContract` 建模。

**独立测试**：独立执行 `parse_skill_markdown`、`parse_api_yaml`、`schema_errors`、`validate_args`、`build_request`、`build_headers` 及联合响应模式解析验证契约正确性。

- [X] T012 [US3] 实现 `SkillMeta`、`Skill`、`SkillParseError`、`parse_skill_markdown`（BOM/CRLF 规范化、`apis` 保序去重）及初始脚手架函数 `build_skill_markdown`，文件：`src/report_agent/domain/skill.py`（2.0 人天）
- [X] T013 [US3] 实现 `ApiContract` 及子模型（`RetrySpec`、`SuccessSpec`、`NoDataRule`、`RecordsSpec`、`SummarySpec`、`ResponseSpec`），提供 `Draft202012Validator` 缓存、`BUILTIN_PLACEHOLDERS`（`${$now}`）、安全请求头 CRLF 检查与 `schema_errors`，文件：`src/report_agent/domain/api_contract.py`（2.0 人天）
- [X] T014 [P] [US3] 编写并执行 `${$now}` 保护校验、请求头注入拦截、`null` 归一化及 XML/JSON 契约 `noData` 优先级与五种 `records.mode` 回归测试，文件：`tests/test_api_builtin_placeholders.py`、`tests/test_api_response_modes.py`、`tests/test_review_runtime.py`（1.5 人天）

#### Phase 6: User Story 4 - 整棵资源树 validate_all 静态交叉门禁 (Priority: P2)

**目标**：完成模板、Skill、接口与系统提示词的全量静态交叉校验门禁，精准定位语法、列定义、引用与路由覆盖隐患。

**独立测试**：构造含多类配置错误与警告的 `ResourceSet`，执行 `validate_template`、`validate_skill`、`validate_api` 与 `validate_all` 验证全部 40 项诊断码。

- [X] T015 [US4] 实现 `validate_template`、`validate_skill`、`validate_api` 与 `validate_all`，完成正文 AST 变量/列表列检查、内层循环变量遮蔽、`LIST_IN_IF_CONDITION` 与 `FIELD_SAME_AS_INPUT` 预警及 `template-router` 与在线模板双向核验，文件：`src/report_agent/domain/resources.py`（2.0 人天）
- [X] T016 [P] [US4] 编写并执行发布门禁诊断码、内层循环遮蔽、同名入参预警、软链隔离及生产 33 套模板与 12 个 Skill 全量 0 error/0 warning 回归测试，文件：`tests/test_list_fields.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_migrated_seed.py`（1.5 人天）

### 3.4 Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 [P] 复核并加固 `domain/` 与 `runtime/render.py` 边界条件（`self` 变量渲染、YAML `null` 归一化、超深括号兜底）、中文注释与 `#Created By AiCoding(codex)` 头部标记，文件：`src/report_agent/domain/`、`src/report_agent/runtime/render.py`（1.5 人天）
- [X] T018 执行全量自动化测试与 Ruff 静态检查，并核验 `specs/001-domain-jinja-sandbox` 三件套追踪与 Wiki 一致性，覆盖：`tests/`、`src/report_agent/domain/`、`src/report_agent/runtime/render.py`（1.0 人天）

### 3.5 任务详情与完成记录

#### 任务组：`T001`–`T005`（准备与基础安全原语）

- **关联需求**：`FR-001`、`FR-002`、`FR-004`、`FR-005`、`FR-009`、`NFR-001`、`NFR-003`、`NFR-004`
- **关键变更点**：创建 `src/report_agent/domain/__init__.py`；在 `template.py` 与 `api_contract.py` 确立 `_Base`（`extra="forbid"`）基类与显式栈 ReDoS 检查原语（`safe_regex_compile`/`safe_regex_fullmatch`，`MAX_REGEX_LENGTH = 2000`，`@lru_cache(512)`）；在 `resources.py` 建立 `Issue`/`ResourceSet` 与 `_within_root`/`load_resource_dir`；在 `jinja_env.py` 与 `render.py` 建立 `_ACTIVE_USED` `ContextVar` 与 `FieldRender`。
- **验证方式与实测证据**：本轮通过 `uv run pytest -q`（全量 `196 passed in 51.41s`，含 `tests/test_review_runtime.py`、`tests/test_text_and_gateway.py`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）验证通过。
- **状态与阻塞**：已完成；无阻塞。

#### 任务组：`T006`–`T011`（P1 用户故事 `US1` & `US2`：模板建模与沙箱追踪）

- **关联需求**：`US1`、`US2`、`FR-001`–`FR-005`、`SC-002`–`SC-004`、`EX-003`、`EX-004`
- **关键变更点**：完成 `InputDef`、`ColumnDef`、`FieldDef`、`TemplateDef`、`Template`、`parse_template_yaml`、`dump_template_yaml`、`body_variable_lines` 与 `runner.py#validate_inputs`；完成 `_TrackedSandboxEnvironment`、`_PebbleNewlineTrimExtension`、`_test_has_digit`、`TrackedValue`、`TrackedList`、`_TrackedCodeGenerator`、`_wrap_filter_func`、`_compile_body_template`（`@lru_cache(256)`）与 `build_render_context`/`field_render`。
- **验证方式与实测证据**：本轮通过 `uv run pytest -q`（全量 `196 passed in 51.41s`，含 `tests/test_list_fields.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_deep_audit_fixes.py`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）验证通过。
- **状态与阻塞**：已完成；无阻塞。

#### 任务组：`T012`–`T016`（P2 用户故事 `US3` & `US4`：Skill/ApiContract 与交叉门禁）

- **关联需求**：`US3`、`US4`、`FR-006`–`FR-010`、`SC-001`、`SC-005`、`EX-001`、`EX-002`、`EX-005`、`EX-006`
- **关键变更点**：完成 `skill.py`（`SkillMeta`、`Skill`、`parse_skill_markdown`、`build_skill_markdown`）、`api_contract.py`（`ApiContract`、`ResponseSpec`、`RecordsSpec`、`BUILTIN_PLACEHOLDERS` `${$now}` 保护、`_validate_headers_dict`、`Draft202012Validator` 缓存）及 `resources.py`（`validate_template`、`validate_skill`、`validate_api`、`validate_all` 40 项诊断码与 `template-router` 双向覆盖）。
- **验证方式与实测证据**：本轮通过 `uv run pytest -q`（全量 `196 passed in 51.41s`，含 `tests/test_api_builtin_placeholders.py`、`tests/test_api_response_modes.py`、`tests/test_migrated_seed.py`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）验证通过。
- **状态与阻塞**：已完成；无阻塞。

#### 任务组：`T017`–`T018`（收尾加固与全量质量门禁）

- **关联需求**：`NFR-001`–`NFR-006`、`SC-001`–`SC-005`
- **关键变更点**：完成 `domain/` 与 `runtime/render.py` 边界条件复核、中文注释与 `#Created By AiCoding(codex)` 头部标记检查，以及 `specs/001-domain-jinja-sandbox/{spec,plan,tasks}.md` 规范收口。
- **验证方式与实测证据**：本轮实测 `uv run pytest -q` 输出 `196 passed in 51.41s`，`uvx ruff@0.11.0 check src tests` 输出 `All checks passed!`。
- **状态与阻塞**：已完成；无阻塞。

---

## 4. 子任务拆解（可选） 【补充】

> 本需求各 `T001`–`T018` 粒度已适中（每项 1.0–2.5 人天），无需额外子任务拆解。

---

## 5. 代码实现约束（仅本需求新增） 【补充】

- **并发与一致性**：`_compile_body_template`（256）与 `_compile_safe_regex_cached`（512）仅缓存不可变对象；多协程渲染状态仅通过 `_ACTIVE_USED` `ContextVar` 传递并经 `try/finally` 重置 Token；`ApiContract._validator_cache` 使用对象引用比对防止配置字典更新后复用旧验证器。
- **安全与隐私边界**：`safe_regex_compile` 使用显式迭代栈拦截嵌套重复量词与超深括号；`_TrackedSandboxEnvironment` 移除 `cycler`/`joiner`/`lipsum`/`namespace`；`_validate_headers_dict` 拦截控制字符、CRLF 与受保护头覆盖；`_within_root` 拦截外部软链接；`ApiContract._with_builtins` 禁止入参覆盖 `$now`。
- **错误与降级语义**：语法与解析异常统一转结构化 `BodySyntaxError`/`SkillParseError`/`ValueError` 或 `Issue(level="error", code="LOAD_FAILED")`；`field_render` 对非列表字段收到 `list`/`dict` 时规整为空串不泄漏 Python 对象 `repr`。

---

## 6. 测试任务矩阵（Test Tasks） 【核心】

| 测试编号 | 类型 | 测试场景与关注点 | 关联任务 | 测试路径 | 验证命令与结果 |
| --- | --- | --- | --- | --- | --- |
| `TT-01` | 单元测试 | 模板 YAML 四类字段往返、`extra="forbid"` 未知键与列表字段定义校验 | `T006`–`T008` | `tests/test_list_fields.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-02` | 安全/异常测试 | 显式栈 ReDoS 拦截（`(a+)+`、超长 `> 2000`、千层括号）与 `validate_inputs` 拦截 | `T003`、`T007`、`T008` | `tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_text_and_gateway.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-03` | 单元测试 | Pebble 单换行裁剪、字面 `}}` 保留、`hasDigit` 测试、`TrackedList` 仅循环记入追踪 | `T009`–`T011` | `tests/test_list_fields.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-04` | 安全/并发测试 | 沙箱 `SecurityError`、`self` 键冲突、嵌套渲染隔离、`~`/`+`/过滤器来源传播 | `T005`、`T009`–`T011` | `tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_deep_audit_fixes.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-05` | 安全/单元测试 | `${$now}` 防覆盖、请求头 CRLF/受保护头拦截、`SKILL.md` BOM/CRLF 归一化与 `apis` 去重 | `T012`–`T014` | `tests/test_api_builtin_placeholders.py`、`tests/test_review_runtime.py`、`tests/test_text_and_gateway.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-06` | 集成/契约测试 | XML/JSON 双协议下 5 种 `records.mode`、`noData` 优先判定、`flatten` 与点分列提取 | `T013`–`T014` | `tests/test_api_response_modes.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-07` | 单元测试 | 软链越界隔离 `LOAD_FAILED`、AST 行号、内层循环遮蔽、`LIST_IN_IF_CONDITION` 与 `FIELD_SAME_AS_INPUT` | `T004`、`T015`–`T016` | `tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-08` | 回归测试 | 生产 33 套模板与 12 个 Skill 全量 `validate_all` 零报错零警告、`template-router` 双向核验 | `T015`–`T016`、`T018` | `tests/test_migrated_seed.py` | 纳入本轮 `uv run pytest -q`（全量 `196 passed in 51.41s`）通过 |
| `TT-09` | 静态代码检查 | `src/` 与 `tests/` 全量 Ruff 代码风格、未使用变量与安全规则检查 | `T017`–`T018` | `src/`、`tests/` | `uvx ruff@0.11.0 check src tests`（`All checks passed!`） |

---

## 7. 发布任务清单（Release Tasks） 【核心】

| 发布编号 | 动作内容 | 前置依赖 | 验证与完成标准 | 回滚动作 | 关联任务 |
| --- | --- | --- | --- | --- | --- |
| `RT-01` | 后端领域层单元测试、生产种子门禁回归与 Ruff 静态检查收口 | `T001`–`T017` 全部完成 | `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`） | Git 回退对应源码提交 | `T018` |
| `RT-02` | 联动 `008` 迁移工具校验（Java 结构与 Pebble 渲染对拍）与发布镜像就绪 | `RT-01` | `verify_structure.py`（0 error / 0 warning）与 `verify_render.py` 逐字一致 | 切换 `releases/current` 软链或回退容器镜像版本 | `T018` |

---

## 8. 可观测性与验收（Observability & Acceptance） 【补充】

### 8.1 关键过程事件、日志与审计点位

| 场景 | 载体（过程事件 / 日志 / 审计） | 关键上下文字段 | 隐私脱敏约束 |
| --- | --- | --- | --- |
| 资源加载与静态门禁检查 | `Issue` / `ResourceSet.load_issues` / `domain.resources` `logging` | `level`、`code`、`kind`、`key`、`field`、`line` | 只记录资源路径相对名称与字段名，不记录敏感业务数据内容 |
| 沙箱越权与语法异常 | `BodySyntaxError` / `SecurityError`（供上层 `Workspace` 与 `RunStore` 捕获记录） | `lineno`、结构化中文错误摘要 | 不泄露宿主机绝对路径与内存对象地址 |

### 8.2 验收清单

- 第 3 章全量 18 项权威任务已按实测 `uv run pytest -q`（`196 passed in 51.41s`）与 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）完成核验。
- `spec.md`、`plan.md` 与 `tasks.md` 追踪矩阵覆盖全部 `US1`–`US4`、`FR-001`–`FR-010`、`SC-001`–`SC-005`、`NFR-001`–`NFR-006`、`EX-001`–`EX-006`，无遗漏且无宪章违例。
- 三类外部独立交付物已确认为不涉及且未生成多余文件；既有 `wiki/` 规范页面已完整覆盖本模块知识。

---

## 9. 阻塞与待确认（Blockers & Open Questions） 【核心】

> 当前无阻塞问题（历史 `Q-001`、`Q-002` 均已闭环关闭）。

| 编号 | 问题描述 | 关联 Spec Q-* | 影响任务 | 责任方 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `BQ-1` | `{% if 列表 %}` 条件写法在静态门禁中的处理级别 | `Q-001` | `T015`、`T016` | 架构与模板治理负责人 | 已关闭 | 定为 `warning`（`LIST_IN_IF_CONDITION`），已于 `resources.py` 实装并通过单测验证 |
| `BQ-2` | ReDoS 正则语法分析引擎选型与 CPython 版本兼容 | `Q-002` | `T003`、`T008` | 平台核心研发 | 已关闭 | 采用标准库 `re._parser` 显式迭代栈方案并限定 Python `>=3.12,<3.14`，已通过千层括号单测 |

---

## 10. 变更记录（Changelog） 【补充】

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 完成 `001-domain-jinja-sandbox` 18 项任务与 `33.0 人天` 初版拆分 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 按改造后中文 `.specify/templates/tasks-template.md` 规范升级全章节、锁定任务复选框正则与工时配比并补充实测 `196 passed in 51.41s` 与 `ruff` 验收记录 |

---

## 附录 A：任务依赖简图

```text
Phase 1 (Setup: T001–T002, 3.0d)
  └─▶ Phase 2 (Foundational: T003–T005, 6.0d)
        ├─▶ Phase 3 (US1 模板双文件与防 ReDoS: T006–T008, 6.5d)
        │     └─▶ Phase 4 (US2 Pebble 沙箱与追踪: T009–T011, 6.0d)
        ├─▶ Phase 5 (US3 Skill 与 ApiContract: T012–T014, 5.5d)
        └─▶ Phase 6 (US4 全量静态门禁 validate_all: T015–T016, 3.5d) ◀─ 汇合 US1–US3
              └─▶ Phase 7 (Polish 与全量测试/ruff 验收: T017–T018, 2.5d)
```

## 附录 B：AI 执行提示

1. 编码前先核对 `spec.md` 第 9 节 Out of Scope 与 `plan.md` 第 1.4 节禁止修改范围（尤其是 `domain/` 单向依赖与 `tests/conftest.py` 隔离边界）。
2. 所有已勾选完成状态的任务均已附真实命令验证证据（`uv run pytest -q` 与 `uvx ruff@0.11.0 check src tests`），禁止无验证勾选完成。

---

## 增量更新说明

> 本文档依据改造后中文 Spec-Kit 模板与 `/sdd-documentation` 标准维护；后续新增或重拆任务需同步刷新第 1 节映射表与第 10 节变更记录。
