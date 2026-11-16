# 设计文档（Feature Design Spec）：声明式领域模型、全量交叉校验与 Pebble 兼容 Jinja2 沙箱渲染引擎

<!-- #Created By AiCoding(codex) -->
<!-- SPECKIT_PLAN_LAYOUT: inline-v1 -->

> **Spec Kit 使用约定**：本模板采用**单文件内联布局（inline-v1）**，研究决策、领域与存储模型、内部接口契约及验证指南全部内联维护在本文件四个锚点章节中，不另建 `research.md`、`data-model.md`、`contracts/` 或 `quickstart.md`。本需求对应三类外部独立交付物均在 `spec.md` 第 8.2 节确认为不涉及。

---

**分支**：`[001-domain-jinja-sandbox]` | **日期**：2026-11-16 | **规格**：`./spec.md`

**输入**：`/specs/001-domain-jinja-sandbox/spec.md`

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-001` |
| 需求名称 | 声明式领域模型、全量交叉校验与 Pebble 兼容 Jinja2 沙箱渲染引擎 |
| 对应需求文档 | `./spec.md` |
| 对应任务清单 | `./tasks.md` |
| 设计文档版本 | `2.0` |
| 设计人 | AiCoding(codex) |
| 核算工作量 | `33.0 人天`（与 `spec.md` / `tasks.md` 一致） |
| 状态 | 已交付归档 |

---

## 1. 设计目标与范围 【核心】

### 1.1 设计目标（What / Why）

- **PLAN-GOAL-1（零硬编码声明式四类资源建模）**：构建 `TemplateDef`/`Template`、`SkillMeta`/`Skill`、`ApiContract` 与 `ResourceSet`/`Issue` 领域体系，将全部业务字段规则、方法论文档和统一网关协议从平台源码彻底剥离。
- **PLAN-GOAL-2（Pebble 3.2.2 逐字等价与沙箱渲染追踪）**：构建 `_TrackedSandboxEnvironment`、词法单换行扩展 `_PebbleNewlineTrimExtension`、`TrackedValue`/`TrackedList` 及唯一上下文装配入口 `runtime/render.py`，保证迁移渲染零偏差且多协程 `used` 追踪零串扰。
- **PLAN-GOAL-3（线性防 ReDoS 与全量静态交叉门禁）**：以显式栈语法树遍历 `safe_regex_compile` 拦截高危嵌套量词正则，结合 `load_resource_dir` 软链逃逸隔离与 `validate_all`（40 项诊断码）守卫发布准入门槛。

### 1.2 设计范围（Scope）

**包含：**

- `src/report_agent/domain/` 下 6 个模块（`__init__.py`、`template.py`、`jinja_env.py`、`skill.py`、`api_contract.py`、`resources.py`），共 1,788 行代码。
- `src/report_agent/runtime/render.py`（85 行）及 `src/report_agent/runtime/runner.py#validate_inputs`（入参正则快速校验入口）。
- 覆盖上述模块的单元测试与迁移校验集成测试（`tests/test_list_fields.py`、`tests/test_api_builtin_placeholders.py`、`tests/test_api_response_modes.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_deep_audit_fixes.py`、`tests/test_text_and_gateway.py`、`tests/test_migrated_seed.py`）。

**不包含：**

- 智能体推理主循环、动态交卷 Schema 与证据核验（`003-agent-runner-evidence`）。
- 12 个平台确定性工具、HTTP 网关收发与 XML/JSON 报文解析实现 `gateway/base.py`（`004-deterministic-tools-gateway`）。
- 文件存储布局、内部 Git 发布、草稿锁、运行账本与热更新配置（`002-git-store-hot-reload`）。
- FastAPI 路由、鉴权、Vue 前端与嵌入式聊天系统（`005`～`007`）。

<a id="plan-research"></a>

### 1.3 研究与关键决策（Decision Log）

| ID | 决策点 | 备选方案 | 最终选择 | 依据与取舍理由 | 影响范围 |
| --- | --- | --- | --- | --- | --- |
| D1 | 模板与契约 YAML 反序列化策略 | 默认忽略未知键 / Pydantic `extra="forbid"` | 统一基类 `_Base` 启用 `extra="forbid"` + `populate_by_name=True` | 阻止维护人员拼写错误键被静默忽略，代价比运行期参数失效小得多 | `domain/template.py`、`domain/api_contract.py` |
| D2 | ReDoS 正则语法检测方案 | 引入第三方 `google-re2` / 递归遍历 `re._parser` / 显式栈迭代遍历 `re._parser` | 显式迭代栈遍历 `re._parser.parse` + `MAX_REGEX_LENGTH=2000` + `@lru_cache(512)` | 零 C++ 扩展依赖且与 CPython 正则编译完全同源；显式栈加 `memo` 杜绝千层括号 `RecursionError` | `domain/template.py`、`domain/api_contract.py`、`runner.py` |
| D3 | Jinja2 对齐 Pebble 3.2.2 换行语义 | 在模板改写为 `{{- -}}` / 开启 `lstrip_blocks` / 自定义词法流扩展 | `trim_blocks=True` + `_PebbleNewlineTrimExtension` 剥离 `TOKEN_VARIABLE_END` 后单个 `\n` | `{{- -}}` 会破坏缩进与多空白；词法过滤器精准只去 `}}` 后单换行，不误伤正文普通 `}}` | `domain/jinja_env.py`、`tools/java_migration/verify_render.py` |
| D4 | 字段展示与缺失追踪机制 | 静态 AST 扫描正文变量 / `TrackedValue(str)` + `TrackedList(list)` + `_TrackedCodeGenerator` | 动态追踪 `TrackedValue`/`TrackedList` + `ContextVar` `_ACTIVE_USED` + `@lru_cache(256)` | 静态 AST 无法判断条件分支实际命中情况；重写 `visit_Concat`/`visit_Add` 与包装过滤器防止 `str_join` 剥离字段来源；`TrackedList` 在 `__iter__` 而非 `__len__` 记数区分布尔判断与循环 | `domain/jinja_env.py`、`runtime/render.py` |
| D5 | 模板字段与形参冲突及协程嵌套隔离 | `template.render(**context)` / 位置单字典传参 + `_ACTIVE_USED` 复用 | `template.render(context or {})` + `_TrackedTemplate` 复用外层 `_ACTIVE_USED` | 避免字段名为 `self` 时与 `Template.render(self, ...)` 形参冲突，支持嵌套模板独立收集 `used` | `domain/jinja_env.py` |
| D6 | 静态门禁错误/警告分级与渲染模块落点 | 所有隐患均阻断发布 / `error` 阻断 + 历史可兼容模式发 `warning`；`render.py` 归属 `runtime/` | `validate_all` 分级（`error` 阻断、`warning` 提示），离线模板跳过；`render.py` 单向依赖 `domain/` 与 `scalar_to_str` | 避免存量 `LIST_IN_IF_CONDITION` 卡死兼容发布；`render.py` 置入 `runtime/` 避免 `domain/` 反向导入 `runtime/` 形成循环依赖 | `domain/resources.py`、`runtime/render.py` |

---

### 1.4 技术背景与项目结构

**语言/版本**：Python `>=3.12,<3.14`（容器基于 `python:3.13-slim`）

**主要依赖**：`pydantic>=2.12,<3`、`jinja2>=3.1,<4`、`jsonschema>=4.23,<5`、`pyyaml>=6.0.2,<7`、CPython 标准库 `re._parser`

**存储**：无直接磁盘存储与外部数据库依赖；维护进程内有界缓存（`@lru_cache(maxsize=512)` 正则缓存、`@lru_cache(maxsize=256)` 预编译模板缓存、实例级 `ApiContract._validator_cache`）

**测试**：`pytest>=8.3`、`pytest-asyncio>=0.24` 与 `uvx ruff@0.11.0 check src tests`

**目标平台**：Linux 容器（单进程 Uvicorn `workers=1`）及 macOS 本地研发环境

**项目类型**：后端核心领域模型、校验门禁与沙箱渲染子系统

**约束与规模/范围**：覆盖 `src/report_agent/domain/` 6 个文件与 `src/report_agent/runtime/render.py` 共 7 个核心文件（总计 1,873 行源码，另含 `runner.py#validate_inputs` 20 行函数），支撑 33 套生产模板（`100~132`）、12 个 Skill 与双协议网关契约；工作量 `33.0 人天`（18 项任务）。

**源代码结构（真实目录落点）**：

```text
src/report_agent/
├── domain/
│   ├── __init__.py          # 领域包标识（1 行）
│   ├── template.py          # 双文件模板模型、YAML 序列化、行号统计与防 ReDoS 编译原语（263 行）
│   ├── jinja_env.py         # 不可变沙箱、Pebble 换行裁剪、hasDigit、TrackedValue/TrackedList（505 行）
│   ├── skill.py             # 纯文本 SKILL.md 解析与脚手架生成（111 行）
│   ├── api_contract.py      # ApiContract 模型、JSON Schema 缓存、${$now} 与安全请求头检查（427 行）
│   └── resources.py         # ResourceSet、Issue、防软链越界加载与 40 项 validate_all 门禁（481 行）
└── runtime/
    ├── render.py            # 唯一生产渲染上下文构建器（FieldRender / build_render_context，85 行）
    └── runner.py            # validate_inputs 入参快速失败校验（第 87–106 行）

tests/
├── test_list_fields.py                # Pebble 换行、hasDigit、列表字段与 TrackedList 测试（520 行）
├── test_api_builtin_placeholders.py   # ${$now} 内置占位符保护、组包与固定参数展示测试（83 行）
├── test_api_response_modes.py         # 5 种 records.mode、noData 优先级、flatten 与点分列名测试（588 行）
├── test_review_runtime.py             # self 键冲突、软链隔离、AST 诊断与深括号正则测试（889 行）
├── test_review_fixes_runtime.py       # 过滤器追踪保留、ReDoS 拦截与列表 if 告警测试（801 行）
├── test_deep_audit_fixes.py           # ~ / + 多字段拼接追踪与缺失传播测试（611 行）
├── test_text_and_gateway.py           # ApiContract 解析边界、沙箱与正则防护测试（311 行）
└── test_migrated_seed.py              # 生产 33 套模板与 12 个 Skill 全量 0 error/0 warning 回归（302 行）
```

**禁止修改范围**：

- 严禁在 `src/report_agent/domain/` 内反向导入 `runtime/`、`store/`、`gateway/`、`api/` 或 `chat/`。
- 严禁修改 `tests/conftest.py` 的 `SEED_DIR` 测试隔离机制，防止单元测试被生产 `seed/` 变更破坏。
- 本归档阶段不改动任何已有生产代码与前端入口 `frontend/embed.html` 分包结构。

#### 文档结构（本需求）

```text
specs/001-domain-jinja-sandbox/
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
| 原则 I：平台零业务硬编码与声明式资源隔离 | PASS | PASS | `domain/` 仅保留通用 `ROUTER_SKILL_ID = "template-router"` 常量，零特定模板 ID/短信规则硬编码 |
| 原则 II：单智能体规划、确定性原语与强证据防幻觉 | PASS | PASS | `FieldDef` 强约束 `evidence`/`whenMissing`/`quoteWhole`；`TrackedValue`/`TrackedList` 精确上报 `used` 支撑 `SUCCESS`/`PARTIAL` |
| 原则 III：文件化 Git 原子发布与单进程并发安全（`workers=1`） | PASS | PASS | `validate_all` 作为无副作用纯函数嵌入发布门禁；`_ACTIVE_USED` `ContextVar` 实现协程隔离渲染 |
| 原则 IV–V：单文件内联设计、自动化测试隔离与 Mock 契约 | PASS | PASS | 采用 `inline-v1` 单文件 Plan；全部单测受 `conftest.py` 隔离且不请求外网模型/网关 |
| 原则 VI–VII：安全脱敏、零硬编码凭证、事件与审计留痕 | PASS | PASS | `safe_regex_compile` 显式栈防 ReDoS；沙箱移除 `cycler`/`joiner`/`lipsum`/`namespace`；`_validate_headers_dict` 拦截 CRLF；`_within_root` 防软链逃逸；零明文凭据 |
| 原则 VIII–X：最小改动、代码规范、Wiki 同步及三类外部交付物确认 | PASS | PASS | `uvx ruff@0.11.0 check src tests` 与 `uv run pytest -q` 全量通过；Wiki 已同步；三类独立交付物确认为不涉及 |

### 1.6 复杂度跟踪

| 偏离或额外复杂度 | 必要性说明 | 未采用更简方案的原因 |
| --- | --- | --- |
| 无违背宪章约束；仅保留 2 项受控工程权衡：（1）使用标准库内部 `re._parser` 做显式栈 ReDoS 分析 | 保证正则语法树解析与最终 `re.compile` 100% 同源且零第三方 C++ 扩展依赖 | 简化版仅靠 `re.compile` 会允许 `(a+)+` 恶意模式，递归遍历则会被超深括号打爆栈；已通过 `>=3.12,<3.14` 版本锁与 `RecursionError` 捕获兜底 |
| （2）`runtime/render.py` 置于 `runtime/` 而非 `domain/` | `field_render` 需复用 `runtime.evidence.scalar_to_str` 对容器及数值做统一格式化 | 若放入 `domain/` 会形成 `domain` ↔ `runtime` 循环依赖；保持 `render.py` 85 行极简单向调用可彻底避免循环导入 |

### 1.7 Wiki 影响评估

- **结论**：不涉及新增或修改（对应核心知识已于前序迭代完整沉淀至 `wiki/`，本次仅为存量 Spec 001 的 SDD 标准归档重构，不改动生产代码）。
- **受影响页面（存量对应页面只读对齐参考）**：`wiki/architecture/template-and-rendering.md`、`wiki/decisions/adr-004-jinja2-pebble-and-tracked-list.md`、`wiki/components/gateway-and-api-contract.md`、`wiki/reference/glossary.md`。
- **同步项**：无需更新 `wiki/index.md` 与 `wiki/log.md`。

### 1.8 三类独立交付物设计检查

| 独立交付物 | 涉及情况与依据 | 设计与变更摘要 | 验证与回退设计 | 关联问题 |
| --- | --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 不新增对外 HTTP/SSE/postMessage 契约 | `tests/test_api_response_modes.py` 校验契约语义 | 无 |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 生产资源清单归属 `008-java-migration-delivery` 与 `src/report_agent/seed/` | `tests/test_migrated_seed.py` 回归校验 | 无 |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 不涉及环境变量、容器拓扑或运维配置变更 | `pyproject.toml` 依赖无变化 | 无 |

---

## 2. 需求映射（Traceability） 【核心】

| 规格编号 | 类型 | 需求摘要 | 设计章节映射 | 后续任务映射 |
| --- | --- | --- | --- | --- |
| `US1` / `SC-003` | 用户故事 / 成功标准 | 双文件模板建模、防 ReDoS 正则编译与入参快速校验 | 第 3.1、5.1、6.2 节 | `T001`–`T003`、`T006`–`T008` |
| `US2` / `SC-002`、`SC-004` | 用户故事 / 成功标准 | Pebble 兼容 Jinja2 不可变沙箱与 `TrackedValue`/`TrackedList` 渲染追踪 | 第 3.1、5.1、6.1 节 | `T005`、`T009`–`T011`、`T017` |
| `US3` / `SC-005` | 用户故事 / 成功标准 | 纯文本 `SKILL.md` 解析与双协议 `ApiContract`（`${$now}`、安全头、5 模式） | 第 3.1、5.1、5.2 节 | `T002`、`T012`–`T014`、`T017` |
| `US4` / `SC-001` | 用户故事 / 成功标准 | 安全目录加载 `load_resource_dir` 与 40 项 `validate_all` 静态门禁 | 第 3.2、5.1、6.1 节 | `T004`、`T015`–`T016`、`T018` |
| `FR-001`–`FR-002` | 功能需求 | `TemplateDef`/`FieldDef`、`extra="forbid"`、显式栈防 ReDoS 与 `validate_inputs` | 第 3.1、5.1 节 | `T002`、`T003`、`T006`–`T008` |
| `FR-003`–`FR-005` | 功能需求 | `_TrackedSandboxEnvironment`、`_PebbleNewlineTrimExtension`、`TrackedValue`/`TrackedList`、`build_render_context` | 第 3.1、4.1、5.1、6.1 节 | `T005`、`T009`–`T011` |
| `FR-006`–`FR-008` | 功能需求 | `parse_skill_markdown`、`ApiContract`、`schema_errors`、`_with_builtins`、双协议响应规范 | 第 3.1、5.1、5.2 节 | `T012`–`T014` |
| `FR-009`–`FR-010` | 功能需求 | `_within_root`、`load_resource_dir`、`validate_template`/`skill`/`api` 与 `validate_all` | 第 3.2、5.1、6.1 节 | `T004`、`T015`–`T016` |
| `NFR-001`–`NFR-006` | 非功能需求 | 零硬编码、防幻觉语义、并发 `ContextVar` 隔离、防注入安全、可复现测试与编码规范 | 第 7、10、11 章 | `T003`–`T005`、`T017`–`T018` |
| `EX-001`–`EX-006` | 异常边界 | 软链逃逸隔离、YAML `null` 容错、`self` 冲突规避、深括号 ReDoS、嵌套循环遮蔽、`${$now}` 保护 | 第 6.2 节 | `T003`–`T004`、`T008`、`T011`、`T014`、`T016`–`T017` |

---

<a id="plan-data-model"></a>

## 3. 核心领域模型（Domain Model） 【核心】

### 3.1 领域对象清单

| 对象 / 类 | 所在文件 | 职责与核心属性 | 关键不变量（Invariant） |
| --- | --- | --- | --- |
| `Template` / `TemplateDef` / `FieldDef` / `ColumnDef` / `InputDef` | `src/report_agent/domain/template.py` | 模板双文件建模；含 `id`、`name`、`skills`、`inputs`、`fields`（`string`/`enum`/`date`/`list`）、`columns`、`evidence`、`quoteWhole`、`whenMissing`、`defaultValue`、`offline` | 统一基类 `_Base` 开启 `extra="forbid"`；`type=list` 仅在 `validate_template` 中强约束 `columns` 非空、`whenMissing=="empty"`、`evidence in {"quote","derive"}`、禁 `quoteWhole` 与顶层 `values` |
| `TrackedValue` / `TrackedList` / `_PlaceholderUndefined` | `src/report_agent/domain/jinja_env.py` | 渲染期展示追踪包装器；`TrackedValue(str)` 维护 `field_name`、`field_names`、`missing`；`TrackedList(list)` 维护 `field_name`、`missing`、`on_iter` | `TrackedValue` 经 `strip`/`replace`/`split`/`~`/`+`/过滤器后必须保留全部来源字段；`TrackedList` 仅在 `__iter__` 或直接 `finalize` 输出时记入 `_ACTIVE_USED`，`__len__` 不触发 |
| `FieldRender` | `src/report_agent/runtime/render.py` | 封装单字段的 `found`、`value`、`rendered` 与 `context_value` | 标量 `found=False` 严格按 `whenMissing` 渲染；非列表字段收到 `list`/`dict` 时绝不输出 Python `repr` |
| `Skill` / `SkillMeta` | `src/report_agent/domain/skill.py` | 纯文本方法论元数据（`name`、`title`、`description`、`apis`）、正文 `body` 与原文 `markdown` | `name` 剥离空白后必须非空并与目录名一致；`apis` 兼容列表与逗号分隔串且保序去重 |
| `ApiContract` / `ResponseSpec` / `RecordsSpec` / `NoDataRule` / `SuccessSpec` | `src/report_agent/domain/api_contract.py` | 统一网关双协议声明契约（`connector`、`processCode`、`timeoutMs` `100~120000`、`retry.maxAttempts` `1~5`、`headers`、`input`、`request`、`response`） | `extra="forbid"`；`input` 禁声明 `$` 键；`request`/`headers` 占位符仅限 `input.properties` 或 `BUILTIN_PLACEHOLDERS`；禁用受保护头与 CRLF |
| `ResourceSet` / `Issue` | `src/report_agent/domain/resources.py` | 完整资源快照容器（`system_prompt`、`templates`、`skills`、`apis`、`load_issues`）与静态诊断记录（`level`、`code`、`message`、`kind`、`key`、`field`、`line`） | `load_issues` 隔离单条坏/越界资源不中断整体加载；`error` 阻止发布，`warning` 仅提示 |

### 3.2 静态交叉校验诊断分类与发布阻断判定

> 本需求不涉及运行期复杂持久化状态机；核心静态门禁判定规则如下：

```text
资源目录 / 叠加副本 ─(load_resource_dir)─▶ ResourceSet (含 load_issues: LOAD_FAILED)
        │
        ▼ validate_all(rs)
  ├─ 继承 rs.load_issues (error)
  ├─ 在线模板 (!tpl.offline) ──▶ validate_template (NAME_EMPTY / INPUT_* / FIELD_* / LIST_* / BODY_* / SKILL_NOT_FOUND ...)
  ├─ 全部 Skill ─────────────────▶ validate_skill (API_NOT_FOUND / ROUTER_SKILL_HAS_APIS / ROUTER_TEMPLATE_NOT_FOUND / ROUTER_TEMPLATE_UNCOVERED ...)
  ├─ 全部 ApiContract ───────────▶ validate_api (API_SCHEMA)
  └─ system_prompt 空白检查 ─────▶ SYSTEM_PROMPT_EMPTY (error)
        │
        ▼ 输出 list[Issue]
  level == "error" ──▶ 阻断发布 / 校验不通过
  level == "warning" ─▶ 仅展示整改建议，不阻断兼容发布
```

---

## 4. 数据与存储设计（本需求范围） 【核心】

> 本需求不直接操作 `DATA_DIR` 磁盘持久化（存储读写与原子发布由 `002-git-store-hot-reload` 实现）；本需求只规范四类文件在磁盘上的声明式格式与进程内无状态内存缓存：

### 4.1 存储与缓存对象概览

| 对象/路径 | 变更类型 | 数据格式与字段要点 | 并发/清理/恢复策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `_compile_safe_regex_cached` | 进程内缓存 | 键：`pattern: str`；值：校验通过并编译后的 `re.Pattern[str]` | `@lru_cache(maxsize=512)`，不可变纯函数对象并发读安全 | `FR-002` |
| `_compile_body_template` | 进程内缓存 | 键：`(body: str, strict_undefined: bool)`；值：编译后的 `_TrackedTemplate` | `@lru_cache(maxsize=256)`，依赖 `_ACTIVE_USED` 实现协程隔离 | `FR-003`、`FR-004` |
| `ApiContract._validator_cache` | 实例私有缓存 | 二元组 `(self.input, Draft202012Validator)`（通过 `PrivateAttr` 持有） | 以字典对象引用 `is self.input` 校验一致性，避免修改/重建后命中过期校验器 | `FR-007` |
| `_ACTIVE_USED` | 协程上下文变量 | `ContextVar[set[str] | None]`，默认 `None` | 每次 `render_body` / `_TrackedTemplate.render` 以 `try ... finally: reset(token)` 成对清理 | `FR-004` |
| 四类声明式资源文件规范 | 只读契约解析 | `templates/<id>/{template.yaml,body.md.j2,.offline}`、`skills/<id>/SKILL.md`、`apis/<name>.yaml`、`system-prompt.md` | 由 `load_resource_dir` 使用 `_within_root` 防软链逃逸读取 | `FR-001`、`FR-006`、`FR-007`、`FR-009` |

---

<a id="plan-contracts"></a>

## 5. 接口与契约设计（API / Tools / Events） 【核心】

> 本需求不直接新增对外 HTTP/SSE 端点或外部网关客户端，以下列出供 `store/`、`runtime/`、`gateway/` 与迁移工具链调用的内部核心 Python 接口契约：

### 5.1 接口与契约清单

| 契约编号 | 类型 | 名称 / Path | 方向 | 关键入参 / 载荷 | 关键出参 / 响应 / 事件 | 鉴权与幂等 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `API-1` | 内部领域函数 | `parse_template_yaml` / `dump_template_yaml` | 内部调用 | `text: str` / `defn: TemplateDef` | `TemplateDef` / 规范化 YAML 文本 | 纯函数幂等 | `FR-001` |
| `API-2` | 内部安全原语 | `safe_regex_compile` / `safe_regex_fullmatch` & `validate_inputs` | 内部调用 | `pattern: str`, `value: str` / `template: Template`, `inputs: dict` | `re.Pattern` / `bool` / `list[str]` 中文错误 | 纯函数，抛 `ValueError` | `FR-002` |
| `API-3` | 内部沙箱渲染 | `build_render_context` + `render_body` | 内部调用 | `template`, `report: dict \| None`, `body`, `strict_undefined` | `dict[str, Any]` 与 `(text: str, used: set[str])` | 协程安全隔离，抛 `BodySyntaxError` / `SecurityError` | `FR-003`–`FR-005` |
| `API-4` | 内部契约函数 | `parse_skill_markdown`、`parse_api_yaml`、`ApiContract.validate_args` / `build_request` / `build_headers` | 内部调用 | `markdown: str` / `text: str` / `args: dict[str, Any]` | `Skill` / `ApiContract` / 错误列表 / 组包后字典 | 屏蔽 `$` 入参覆盖；头检验抛 `ValueError` | `FR-006`–`FR-008` |
| `API-5` | 内部静态门禁 | `load_resource_dir` + `validate_all` | 内部调用 | `root: Path` / `rs: ResourceSet` | `ResourceSet`（含 `load_issues`）与 `list[Issue]` | 无副作用只读扫描，全量 40 种诊断码 | `FR-009`–`FR-010` |

### 5.2 关键契约说明与错误语义

- **YAML / Markdown 解析错误**：`parse_template_yaml`、`parse_api_yaml` 与 `parse_skill_markdown` 对顶层非映射结构、非法格式或必填缺失统一抛出 `ValueError` / `SkillParseError` / Pydantic `ValidationError`；在 `load_resource_dir` 批扫描中一律被捕获转化为 `Issue("error", "LOAD_FAILED", ...)` 写入 `rs.load_issues` 而不中断其他资源加载。
- **沙箱与正文语法错误**：Jinja2 语法错误通过 `parse_body` 与 `_compile_body_template` 统一转化为 `BodySyntaxError(message, lineno)`，在 `validate_template` 中转为 `BODY_SYNTAX`；沙箱越权访问统一由 `_TrackedSandboxEnvironment` 抛出带中文前缀的 `SecurityError`。
- **请求头与正则拦截语义**：`ApiContract.build_headers` 在替换占位符后再次运行 `_validate_headers_dict`，一旦参数值带入 `\r`/`\n`/控制字符或覆盖受保护头即抛 `ValueError`；`safe_regex_compile` 统一将 `re.error` 与 `RecursionError` 转换为可读中文 `ValueError`，确保上游 `validate_inputs` 与 `validate_args` 均不会触发未捕获 500 异常。

---

## 6. 业务流程设计（可直接编码） 【核心】

### 6.1 核心执行流程

```text
流程 A（发布前静态交叉门禁）：
1. load_resource_dir(root) 检查 root/system-prompt.md、templates/*/、skills/*/、apis/*.yaml 的 _within_root 安全性
2. 逐个解析四类资源并校验文件/目录标识一致性，单条异常隔离写入 ResourceSet.load_issues
3. validate_all(rs) 汇总 load_issues，对非离线模板调用 validate_template（YAML 语义 + 正文 AST + _list_field_issues + Skill 存在性）
4. 对所有 Skill 调用 validate_skill（API 存在性 + template-router 禁止 apis 与 ### <ID> 双向覆盖），校验 ApiContract 与 system_prompt 非空
5. 返回 list[Issue]，由调用方依据 level == "error" 决定是否阻断

流程 B（报告渲染与展示追踪）：
1. validate_inputs(template, inputs) 先 .strip() 后执行必填与 safe_regex_fullmatch 校验
2. build_render_context(template, report) 为每个字段构造 field_render（标量包装 TrackedValue，列表过滤列名后包装 TrackedList）
3. render_body(body, context) 绑定当前协程独立 used = set() 至 _ACTIVE_USED，命中 _compile_body_template 缓存编译对象
4. 执行 template.render(context or {})：经过词法 _PebbleNewlineTrimExtension 去单换行、_TrackedCodeGenerator 保留拼接来源、TrackedList.__iter__ 记入循环展示字段、finalize 记入输出字段
5. finally 块重置 _ACTIVE_USED Token，返回 (text, used) 交由 Runner 判定 SUCCESS / PARTIAL
```

### 6.2 并发控制与异常降级策略

| 异常/并发场景 | 检测时机 | 处理策略 | 是否中断主流程 | 可观测性输出 |
| --- | --- | --- | --- | --- |
| 高并发异步模板渲染 | 每次调用 `render_body` 或 `_TrackedTemplate.render` | 使用 `ContextVar` `_ACTIVE_USED` 为每个协程绑定独立 `set[str]`，外层已绑定时内层直接复用，`finally` 重置 Token | 否（并发安全隔离） | `used` 集合准确按每次运行隔离返回 |
| 超深嵌套括号正则或 ReDoS 模式 | `safe_regex_compile` 编译前 | 显式迭代栈 + `memo` 遍历 `re._parser` 语法树；捕获 `RecursionError` 转中文 `ValueError` | 是（拒绝配置或入参） | `Issue(code="INPUT_PATTERN" / "API_SCHEMA")` 或 `validate_inputs` 错误列表 |
| 单资源文件损坏或软链逃逸 | `load_resource_dir` 扫描期 | 记录 `LOAD_FAILED` 到 `rs.load_issues` 并跳过该条目，保证其余资源正常装载 | 否（局部隔离，发布门禁拦截） | `Issue(level="error", code="LOAD_FAILED")` |
| 模板未定义变量或容器误传标量 | 渲染期 `finalize` / `field_render` | 非严格模式下 `_PlaceholderUndefined` 输出 `{{变量名}}` 并记入 `used`；标量误传 `list`/`dict` 在 `field_render` 降为空串防输出对象 `repr` | 否（由 `used` 配合 `missing` 触发下游 `PARTIAL`） | `FieldRender(found=False)` 与 `used` 集合 |

---

## 7. 权限与安全控制（本需求范围） 【补充】

> 本需求不新增用户认证或 HTTP 接口权限规则（鉴权由 `005` 承载），重点落实配置解析、模板沙箱、路径逃逸与头注入四大运行时安全防线：

| 控制点 | 适用角色/调用方 | 校验机制与边界 |
| --- | --- | --- |
| 正则 ReDoS 防护（`safe_regex_compile`） | 模板配置维护方 / 上游运行入参 / 接口 Schema | 强制上限 `2000` 字符 + 显式栈语法树拦截嵌套重复量词与可空重复 + `RecursionError` 兜底 |
| Jinja2 不可变沙箱（`_TrackedSandboxEnvironment`） | 模板 `body.md.j2` 渲染执行 | 继承 `ImmutableSandboxedEnvironment` 禁止可变方法与内省属性，移除 `cycler`/`joiner`/`lipsum`/`namespace` 全局符号 |
| HTTP 安全请求头校验（`_validate_headers_dict`） | `ApiContract` 契约维护与组包替换 | 契约静态检验与 `build_headers` 渲染后双重拦截空键、`\r`/`\n`/NUL/控制字符及 `host`/`content-length`/`transfer-encoding` 覆盖 |
| 内置占位符隔离与软链边界（`_with_builtins` / `_within_root`） | 智能体调用参数 / 资源目录加载 | 剔除模型传入的所有 `$` 开头入参确保 `${$now}` 不可篡改；`_within_root` 验证 `resolve().is_relative_to(root_resolved)` 阻断软链逃逸 |

---

## 8. 前端 / 交互设计（如适用） 【补充】

> 本需求不涉及前端页面或交互变更（Vue 工作台四分区模板 IDE 与嵌入窗口分别归属 `006-vue-workbench-ide` 与 `007-embed-chat-router`）。

---

## 9. 配置与热更新开关 【补充】

> 本需求不涉及新增环境变量或运行期热更新配置项（环境变量与 48 项热更新配置存储由 `002-git-store-hot-reload` 管理）。

---

## 10. 测试设计（Test Strategy） 【核心】

### 10.1 测试范围与分层策略

| 测试类型 | 覆盖范围 | 桩/隔离策略 | 重点验证场景 |
| --- | --- | --- | --- |
| 单元测试 | `template.py`、`jinja_env.py`、`skill.py`、`api_contract.py`、`resources.py`、`render.py`、`validate_inputs` | 内存字符串、临时目录 `tmp_path`、无外网与网关依赖 | 四类字段往返、ReDoS 显式栈与超深括号、Pebble 换行裁剪、`hasDigit`、`TrackedValue`/`TrackedList`、`${$now}` 保护、安全请求头、40 项诊断码 |
| 集成/回归测试 | `ResourceSet` 整树与生产 33 套模板/12 个 Skill、`ApiContract` 双协议响应模式 | `tests/conftest.py` 自动隔离默认单元测试至 `tests/fixtures/seed/`；`test_migrated_seed.py` 专测生产 `src/report_agent/seed/` | 生产种子全量 `0 error / 0 warning`、`template-router` 双向覆盖、XML/JSON 五模式一致抽取、`self` 变量与高并发协程渲染隔离 |

### 10.2 回归范围

- 全量测试套件必须持续通过（`uv run pytest -q`），特别是跨模块消费者依赖测试：`tests/test_migrated_seed.py`、`tests/test_agent_runtime.py`、`tests/test_store.py` 与 `tests/test_text_and_gateway.py`。
- 静态代码规范检查 `uvx ruff@0.11.0 check src tests` 保持 0 报错。

<a id="plan-quickstart"></a>

### 10.5 验证指南

- **环境与前置条件**：Python `>=3.12,<3.14` 与 `uv` 环境就绪（`uv sync --extra dev`），无需外部大模型 API Key 或真实统一网关。
- **验证命令**：
  ```bash
  uv run pytest tests/test_list_fields.py tests/test_api_builtin_placeholders.py tests/test_api_response_modes.py tests/test_review_runtime.py tests/test_review_fixes_runtime.py tests/test_deep_audit_fixes.py tests/test_text_and_gateway.py tests/test_migrated_seed.py -q
  uv run pytest -q
  uvx ruff@0.11.0 check src tests
  ```
- **预期结果**：所有测试全部通过（全量 `196 passed`），`ruff` 检查输出 `All checks passed!`。

---

## 11. NFR 符合性自检 【核心】

| 自检主题 | 宪章依据 | 是否涉及 | 落实位置与验证方式 |
| --- | --- | --- | --- |
| 零业务硬编码与资源隔离 | I | 是 | `src/report_agent/domain/` 与 `runtime/render.py` 零硬编码业务规则，`test_migrated_seed.py` 与代码核验 |
| 强证据防幻觉与确定性计算 | II | 是 | `FieldDef` 证据语义与 `TrackedValue`/`TrackedList` 精准追踪展示，`test_list_fields.py`、`test_deep_audit_fixes.py` 验证 |
| 文件化存储与 `workers=1` 并发安全 | III | 是（仅协程隔离与无副作用校验） | `validate_all` 纯函数校验 + `_ACTIVE_USED` `ContextVar` 协程隔离，`test_review_runtime.py` 验证 |
| 安全编码、脱敏与零凭据硬编码 | VI | 是 | `safe_regex_compile` 防 ReDoS、沙箱去全局符号、请求头 CRLF 拦截、`_within_root` 防软链逃逸，`test_review_runtime.py` / `test_text_and_gateway.py` 验证 |
| 过程事件、阶段日志与审计留痕 | VII | 否（由 `003` 与 `005` 承接运行事件） | 本层仅通过 `Issue` 与异常向上传递结构化诊断信息 |

---

## 12. 发布与回退计划 【核心】

- **发布前置与步骤**：本需求属于平台核心 Python 源码模块，随应用镜像发布前必须通过全量 `uv run pytest -q`、`uvx ruff@0.11.0 check src tests` 与 `tools/java_migration/verify_structure.py`、`verify_render.py` 对拍；运行时任何资源变更均自动通过 `validate_all()` 门禁才可生成不可变快照 `releases/rN/`。
- **回退方案**：如发现模板静态校验规则或渲染追踪兼容异常，可通过 Git 回退应用代码并重新构建镜像；对于已发布资源快照本身问题，可依托 `002-git-store-hot-reload` 的 `releases/current` 软链切换回前一版本。

---

## 13. 实施切片与建议顺序（Implementation Slices） 【核心】

| 切片 ID | 切片名称 | 对应 Phase / 任务范围 | 目标与涉及文件 | 核算工时（人天） |
| --- | --- | --- | --- | --- |
| `S-01` | 领域骨架与基础安全原语 | Phase 1–2（`T001`–`T005`） | `domain/__init__.py`、`_Base` 基类、防 ReDoS 原语、`Issue`/`ResourceSet` 安全加载与 `_ACTIVE_USED`/`FieldRender` | `9.0` |
| `S-02` | 双文件模板建模与沙箱渲染引擎（P1） | Phase 3–4（`T006`–`T011`） | `template.py`、`runner.py#validate_inputs`、`jinja_env.py`、`render.py` 及模板/沙箱/追踪单测 | `12.5` |
| `S-03` | Skill/ApiContract 契约与全量门禁（P2） | Phase 5–6（`T012`–`T016`） | `skill.py`、`api_contract.py`、`resources.py#validate_all` 及占位符/响应模式/种子回归测试 | `9.0` |
| `S-04` | 边界加固与工程验收收口 | Phase 7（`T017`–`T018`） | `self`/展平边界复核、中文注释核验、全量 `pytest` 与 `ruff` 验收 | `2.5` |
| **合计** | **4 个实施切片** | **T001 ～ T018** | **完整交付声明式领域层与沙箱渲染引擎** | **33.0** |

---

## 14. 风险清单与缓解（Risks） 【补充】

| 风险 ID | 风险描述 | 影响 | 概率 | 缓解措施 |
| --- | --- | --- | --- | --- |
| `R-1` | CPython 小版本升级导致标准库私有接口 `re._parser` 签名变更 | 中 | 低 | `pyproject.toml` 锁定 `requires-python = ">=3.12,<3.14"`，单测直接覆盖深层括号与嵌套重复量词拦截 |
| `R-2` | 模板复杂过滤器或字符串操作链路中遗漏包装导致 `TrackedValue` 元数据丢失 | 高 | 低 | 通过 `_TrackedCodeGenerator` 接管 `~`/`+` 并包装全部内置过滤器与 `call_filter`，在 `test_deep_audit_fixes.py` 与 `test_review_fixes_runtime.py` 持续回归 |
| `R-3` | 存量模板修改引入历史未覆盖场景导致线上渲染与 Java Pebble 不一致 | 高 | 低 | 与 `tools/java_migration/verify_render.py` 共享唯一 `build_render_context` + `render_body`，支持 JDK 环境逐字等价对拍 |

---

## 15. 待确认事项（Design Open Questions） 【补充】

> 设计阶段关键技术取舍已闭环解决，无未关闭 `DQ-*`（对应 `spec.md` 第 11 节 `Q-001`、`Q-002` 均已关闭）。

| 编号 | 问题摘要 | 对应 Spec Q-* | 当前结论 | 状态 |
| --- | --- | --- | --- | --- |
| `DQ-1` | `{% if 列表 %}` 条件写法在 `validate_template` 中设为阻断 `error` 还是 `warning` | `Q-001` | 设为 `warning`（`LIST_IN_IF_CONDITION`），兼顾存量模板平稳演进与整改引导 | 已关闭 |
| `DQ-2` | ReDoS 分析采用 `re._parser` 显式栈而非第三方扩展 | `Q-002` | 采用标准库 `re._parser` + 显式迭代栈 + `RecursionError` 捕获，零额外依赖 | 已关闭 |

---

## 附录 A：核心字段与状态约定（仅本需求）

- **字段类型 `FieldType`**：`string`、`enum`、`date`、`list`；列表列类型 `ColumnType`：`string`、`enum`。
- **证据类型 `EvidenceType`**：`quote`、`input`、`derive`（列表仅限 `quote` / `derive`）。
- **缺失策略 `WhenMissing`**：`placeholder`（默认 `{{字段名}}`）、`empty`（`""`）、`value`（`defaultValue`）。
- **记录抽取模式 `RecordsMode`**：`auto`、`object`、`list`、`scalar`、`none`；**连接器 `ConnectorType`**：`unified-gateway-xml`、`unified-gateway-json`。
- **静态诊断级别 `Issue.level`**：`error`（阻断）、`warning`（提示），共覆盖 40 项 `Issue.code`。

## 附录 B：AI 编码与交付约束

1. 先阅读 `spec.md`、本 `plan.md` 与 `tasks.md`，按 `T001`–`T018` 顺序核验，不实现 Out of Scope 内容。
2. 所有已勾选完成 `[X]` 的任务必须附有真实命令验证输出，严禁“仅写完未验证即标完成”。

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 完成 `001-domain-jinja-sandbox` 初版实施设计文档 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 按改造后中文 `.specify/templates/plan-template.md`（`inline-v1` 单文件四锚点布局）重构全部 15 章并精确核对源码/测试行号与工时切片 |
