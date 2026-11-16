# 需求文档（Spec）：声明式领域模型、全量交叉校验与 Pebble 兼容 Jinja2 沙箱渲染引擎

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：产物文件名固定为 `spec.md`、`plan.md`、`tasks.md`；三类外部独立交付物按需确认，仅涉及项单独生成并建立链接，不涉及项只记录依据。本规格为已交付存量模块（子规格 001/008）按改造后中文 Spec-Kit 与 SDD 标准完成的正式归档重构，所有事实均经源码与测试证据核验。
> **项目依据**：项目宪章 `.specify/memory/constitution.md`、`AGENTS.md` 及 `wiki/index.md`。遵循先取证后写作原则，优先核对代码、测试与运行证据，不把推测写成事实。

---

**功能分支**：`[001-domain-jinja-sandbox]`

**创建日期**：2026-11-16

**状态**：已交付归档

**输入**：用户描述："将 Spec 001 转换为改造后中文 Spec-Kit + SDD 标准三件套（需求编号 `RA-001`，`33.0` 人天，18 项任务）" —— 负责报告模板双文件建模、防 ReDoS 入参校验、对齐 Pebble 3.2.2 的 Jinja2 沙箱与分支展示追踪（`TrackedValue`/`TrackedList`）、纯文本 Skill 与声明式接口契约解析及整树静态发布校验。

## 基本信息 【核心】

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-001` |
| 需求名称 | 声明式领域模型、全量交叉校验与 Pebble 兼容 Jinja2 沙箱渲染引擎 |
| 核算工作量 | `33.0 人天`（项目总工作量 `250.0 人天`，子规格 001/008） |
| 资料与证据来源 | 1. **源码事实（可信度：高）**：`src/report_agent/domain/{__init__,template,jinja_env,skill,api_contract,resources}.py`（共 1,788 行）、`src/report_agent/runtime/render.py`（85 行）、`src/report_agent/runtime/runner.py#validate_inputs`、`src/report_agent/gateway/base.py#extract_records/extract_json_records`<br>2. **自动化测试（可信度：高）**：`tests/test_list_fields.py`、`tests/test_api_builtin_placeholders.py`、`tests/test_api_response_modes.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_deep_audit_fixes.py`、`tests/test_text_and_gateway.py`、`tests/test_migrated_seed.py`<br>3. **迁移对拍与知识库（可信度：中）**：`tools/java_migration/verify_render.py`、`wiki/architecture/template-and-rendering.md`、`wiki/decisions/adr-004-jinja2-pebble-and-tracked-list.md`、`wiki/reference/glossary.md` |
| 文档版本 | `2.0` |
| 文档状态 | `已交付归档` |

---

## 1. 业务背景与目标 【核心】

### 1.1 业务背景

在智能申告报告填写与资源治理平台（`report-agent`）中，业务申报规则、外部网关协议与报告格式模板高度多变（涵盖 33 套生产模板 `100~132`、12 个 Skill 与多套统一网关 XML/JSON 接口）。如果将字段约束、短信识别关键词、渠道分支逻辑或网关报文解析硬编码在 Python 平台代码中，每次业务微调都需要修改代码并重新发版部署，既违背平台“零业务硬编码”原则，也无法支撑工作台在线编辑与热发布。

同时，平台需要从前代 Java 版本（`pdf-agent-parse`，基于 Pebble 3.2.2 模板引擎）平滑迁移：一方面必须保证 Jinja2 渲染输出与 Pebble 3.2.2 在换行裁剪、空值处理和数字测试（`hasDigit`）上达到逐字等价；另一方面报告终稿还必须精确识别“模板声明了但未命中条件分支的字段”与“命中展示分支却缺失取值的字段”，从而为下游运行结果判定 `SUCCESS` 或 `PARTIAL` 提供零误差依据。此外，面向动态编辑的 YAML/Markdown 配置与不可信上游入参，必须构建防 ReDoS 正则检验、防 Jinja 沙箱越权及整树发布前静态交叉门禁，避免不合格配置流入线上。

### 1.2 业务目标

- **GOAL-1**：以纯声明式双文件模板（`template.yaml` + `body.md.j2`）、纯文本方法论（`SKILL.md`）和双协议网关契约（`apis/<name>.yaml`）完整承载全部业务规则，实现平台 `src/report_agent/` 源码零业务硬编码。
- **GOAL-2**：在 Python Jinja2 不可变沙箱下实现与 Java Pebble 3.2.2 100% 逐字等价的渲染行为，并通过 `TrackedValue`/`TrackedList` 实现多协程并发零串扰的分支展示字段追踪（`used`）。
- **GOAL-3**：通过 Pydantic `extra="forbid"` 严格模型、显式栈防 ReDoS 正则编译器（`safe_regex_compile`）与 HTTP 安全头/内置占位符保护，阻断配置拼写错误、回溯型正则攻击、沙箱内省注入与请求头 CRLF 注入。
- **GOAL-4**：建立整棵资源树静态交叉校验门禁 `validate_all`（覆盖 40 项结构化诊断码与 `template-router` 双向核验），在保存校验与版本发布前实现 `0 error / 0 warning` 合规把关。

---

## 2. 需求概述 【核心】

本需求交付 `report-agent` 的声明式领域模型、安全沙箱渲染引擎与全量静态交叉校验体系（对应 `src/report_agent/domain/` 6 个模块与 `src/report_agent/runtime/render.py`）。在资源定义层，系统对模板（含 `string`、`enum`、`date`、`list` 四类字段及 `ColumnDef`、`InputDef`、`whenMissing`、`evidence`、`quoteWhole`）、纯文本 Skill（含 frontmatter 规范化与 `apis` 去重）以及声明式接口契约 `ApiContract`（含 `Draft202012Validator` 缓存、`${$now}` 内置占位符、`noData`/`success` 规则与 5 种 `records.mode`）提供严格反序列化与格式校验。

在执行安全与渲染追踪层，系统封装了基于 `re._parser` 显式迭代栈遍历的 `safe_regex_compile` / `safe_regex_fullmatch`，消除超长或嵌套重复量词正则引起的 ReDoS 与栈溢出风险；构建基于 `ImmutableSandboxedEnvironment` 的 `_TrackedSandboxEnvironment`，联合词法单换行裁剪扩展 `_PebbleNewlineTrimExtension`、`hasDigit` 测试、`TrackedValue`、AST 代码生成器 `_TrackedCodeGenerator`、`TrackedList` 与 `ContextVar`（`_ACTIVE_USED`），并由 `runtime/render.py` 向上游运行器与 Java 迁移对拍脚本提供唯一的标准渲染上下文构造入口 `build_render_context`。最后，通过 `load_resource_dir` 软链逃逸隔离与 `validate_all` 整树交叉门禁，将语法、列定义、引用失配与路由覆盖问题阻断在发布之前。

### 2.1 用户场景与测试

> 按用户旅程组织并标记稳定编号 `US1`、`US2` 等，使用 `P1`/`P2` 排序；每个故事均已对应可独立运行的自动化验证测试。

#### 用户故事 1（US1）— 模板双文件建模与入参防 ReDoS 安全校验（优先级：P1）

- **用户旅程**：作为业务模板维护人员与上游调用接入方，我希望在 `templates/<id>/template.yaml` 与 `body.md.j2` 中完整声明模板字段（含列表与列定义）、缺失策略和入参正则约束，并在配置解析与上游请求接入前自动拒绝未知键与高危回溯正则（ReDoS），从而安全、无歧义地定义业务报告模板。
- **优先级理由**：模板双文件模型是“零业务硬编码”平台承载业务知识的基石，而正则 ReDoS 防护与入参快速失败校验直接守卫运行时与配置期边界安全，属于核心 MVP 能力。
- **独立测试**：构造仅包含 `template.yaml` 与 `body.md.j2` 的内联模板，独立运行 `parse_template_yaml`、`dump_template_yaml`、`safe_regex_compile`、`safe_regex_fullmatch` 与 `validate_inputs`，验证四类字段往返等价、严格键检查及 ReDoS 正则拦截，无需启动大模型或网关服务。
- **关联需求**：`FR-001`、`FR-002`、`SC-001`、`SC-003`
- **验收场景**：
  1. **前提** 维护人员提交包含 `string`、`enum`、`date`、`list` 四类字段、`whenMissing`（`placeholder`/`empty`/`value`）及 `visible: false` 中间字段的 `template.yaml`，**当** 系统执行 `parse_template_yaml` 与 `dump_template_yaml` 往返解析，**则** 所有字段属性与列表列定义 `columns` 保持无损等价，若 YAML 中存在未声明的拼写错误键则因 `extra="forbid"` 立即拒绝。
  2. **前提** 模板入参或接口契约 Schema 中配置了超过 `MAX_REGEX_LENGTH`（`2000` 字符）、超深括号嵌套或含嵌套重复量词（如 `(a+)+`、可空子式重复）的正则表达式，**当** 调用 `safe_regex_compile` 或发布/运行时触发校验，**则** 显式栈语法树分析器（`_subpattern_can_match_empty`、`_has_nested_repeat`）在编译前拦截并抛出中文 `ValueError`，不会发生栈溢出或回溯卡死。
  3. **前提** 上游调用携带缺失必填项或不符合 `pattern` 正则的入参字典，**当** 运行前执行 `validate_inputs`，**则** 所有入参先经 `.strip()` 去首尾空白，随后按顺序返回包含具体入参名的中文错误信息，阻断后续大模型推理流程。

#### 用户故事 2（US2）— 对齐 Java Pebble 3.2.2 的 Jinja2 不可变沙箱与 TrackedValue/TrackedList 分支展示追踪（优先级：P1）

- **用户旅程**：作为报告生成运行时与迁移对拍验证方，我希望报告正文在 Jinja2 不可变沙箱中的渲染输出与前代 Java Pebble 3.2.2 逐字一致，且仅将在实际生效输出分支中被展示或遍历迭代的字段记入 `used` 集合，从而防止模板恶意操作宿主机对象并准确判定报告状态为 `SUCCESS` 或 `PARTIAL`。
- **优先级理由**：逐字渲染等价是 33 套生产模板零回退迁移的前提，而 `used` 字段追踪的精准度直接决定运行终态判定与线上告警准确性。
- **独立测试**：构造带换行标签、过滤器、`~`/`+` 拼接、`hasDigit` 测试、`{% if %}` 与 `{% for %}` 嵌套的测试模板及模拟交卷字典，独立调用 `build_render_context` 与 `render_body`，验证输出文本逐字精确性、`used` 集合准确性以及并发/嵌套渲染隔离。
- **关联需求**：`FR-003`、`FR-004`、`FR-005`、`SC-002`、`SC-004`
- **验收场景**：
  1. **前提** 报告正文模板包含 `{{ 字段 }}\n`、`{% if %}\n`、`{# 注释 #}\n`、`\r\n` 换行及 `{{ 值 | trim ~ 后缀 }}` 或 `{% if 标准资费 is hasDigit %}`，**当** 系统通过 `render_body` 渲染，**则** `_PebbleNewlineTrimExtension` 与 `trim_blocks=True` 联合去除每个输出/控制/注释标签后紧跟的单个换行（保留纯文本字面 `}}` 与行首缩进），`hasDigit` 对缺失占位符和 `None` 返回 `False` 不抛异常，且经过滤器与拼接后的结果仍保留全部关联字段名于 `used` 集合中。
  2. **前提** 正文对 `type: list` 字段执行 `{% if 列表字段 %}...{% endif %}` 布尔判断而未进入 `{% for item in 列表字段 %}` 迭代（或 `{% for %}` 处于未命中的 `{% if %}` 分支内），**当** `TrackedList` 参与渲染，**则** 布尔判断仅触发 `__len__` 而不触发 `__iter__`，因此该列表字段不会被误记入 `_ACTIVE_USED`；仅当实际执行生效分支的 `{% for %}` 循环时才记入 `used`。
  3. **前提** 模板正文中包含尝试调用可变方法（如 `{{ 充值流水.append('x') }}`）或访问危险全局对象（如 `cycler`、`joiner`、`lipsum`、`namespace`）的表达式，**当** 在沙箱环境渲染，**则** `ImmutableSandboxedEnvironment` 立即抛出 `SecurityError`，且高并发或嵌套模板调用通过 `ContextVar`（`_ACTIVE_USED`）与 `@lru_cache(maxsize=256)` 预编译缓存保持协程隔离与低延迟。

#### 用户故事 3（US3）— 纯文本 SKILL.md 与声明式双协议接口契约 ApiContract 建模（优先级：P2）

- **用户旅程**：作为业务配置人员与平台工具调用层，我希望通过纯文本 `SKILL.md` 编排模型查数方法论，并通过声明式 `apis/<name>.yaml` 定义双协议（XML/JSON）网关参数 Schema、`${$now}` 时间戳注入、安全 HTTP 头以及 `noData`/`success`/`records.mode` 响应解包契约，从而完全剥离代码与业务接口逻辑。
- **优先级理由**：纯文本 Skill 与声明式 `ApiContract` 是平台接入新业务接口免发版、零脚本安全执行的核心抽象契约。
- **独立测试**：构造含 BOM/CRLF 的 `SKILL.md`、带 `${$now}` 与嵌套点分路径的 XML/JSON `ApiContract` YAML，独立调用 `parse_skill_markdown`、`parse_api_yaml`、`schema_errors`、`validate_args`、`build_request`、`build_headers` 及联合 `gateway/base.py` 的记录抽取验证全量解析、组包与契约语义。
- **关联需求**：`FR-006`、`FR-007`、`FR-008`、`SC-005`
- **验收场景**：
  1. **前提** 一份包含 YAML frontmatter（支持列表或逗号分隔 `apis` 字符串）与 Markdown 正文的 `SKILL.md`，**当** 调用 `parse_skill_markdown`，**则** 自动剔除 UTF-8 BOM 并归一化 `\r\n`，对 `apis` 保序去重；若缺失 `---` 包裹或 `name` 为空则抛出 `SkillParseError`。
  2. **前提** 一个使用 `${$now}` 内置占位符、声明 JSON Schema `input` 约束并配置自定义 HTTP 请求头的 `ApiContract`，**当** 执行 `schema_errors`、`validate_args`、`build_request` 与 `build_headers`，**则** 禁止在 `input` 中声明 `$` 开头参数且屏蔽调用方对 `$now` 的覆盖，拦截 CRLF/控制字符及 `host`/`content-length`/`transfer-encoding` 受保护请求头覆盖，并按单次组包时刻统一注入 `yyyyMMddHHmmss` 时间戳。
  3. **前提** 声明式 `ResponseSpec` 同时配置 `noData` 规则与 `success` 成功码，或使用五种 `records.mode`（`auto`、`object`、`list`、`scalar`、`none`）及 `flatten: true`/点分列（如 `userInfo.userName`），**当** 由 `ApiContract` 解析校验并交由下游连接器执行报文解析时，**则** 契约语义保持 XML 与 JSON 双协议一致：`noData` 优先于 `success` 判定为空结果，`auto` 自动解包标准 `content.list`，且显式点分列与 `flatten` 规范合法通过校验。

#### 用户故事 4（US4）— 整棵资源树 validate_all 静态交叉门禁（优先级：P2）

- **用户旅程**：作为平台发布审核与配置维护人员，我希望在保存工作副本或执行版本发布前，系统对 `system-prompt.md`、在线 `templates/*`、全部 `skills/*` 与 `apis/*` 组成的 `ResourceSet` 执行静态交叉门禁，精准输出阻塞错误（`error`）和指导警告（`warning`）并定位行号，避免配置失误流出线上。
- **优先级理由**：发布前静态交叉校验可提前拦截 40 类配置隐患、列表空指针风险和路由失配，是保障发布高质量零事故的关键门禁。
- **独立测试**：构造包含多类缺陷（未定义变量、列表未定义列、循环非列表、缺失 Skill/API、`template-router` 声明了 `apis` 或引用已下线模板、未覆盖在线模板等）的 `ResourceSet` 或磁盘目录，调用 `load_resource_dir` 与 `validate_all` 断言全部精确 `Issue.code`、`level` 与行号定位。
- **关联需求**：`FR-009`、`FR-010`、`SC-001`
- **验收场景**：
  1. **前提** 模板正文中引用了未定义变量、用 `{% for %}` 遍历标量字段、在循环内访问列表未声明列 `item.未知列` 或使用元组解构循环变量，**当** 执行 `validate_template`，**则** 精确产生对应行号的 `BODY_UNDEFINED_FIELD`、`FOR_NON_LIST`、`LIST_COLUMN_UNDEFINED`、`LIST_LOOP_TARGET` 阻断错误；而当内层循环重绑定同名循环变量遍历另一列表时，不会误按外层列表校验而产生误报。
  2. **前提** 模板在 `{% if 列表字段 %}` 条件中直接引用列表字段，或字段与入参同名但 `evidence != "input"`，或 `visible: true` 字段未在正文出现，**当** 执行 `validate_template`，**则** 分别发出 `LIST_IN_IF_CONDITION`、`FIELD_SAME_AS_INPUT`、`VISIBLE_NOT_IN_BODY` 的 `warning` 提示，指导维护人员修复而不粗暴阻止兼容发布。
  3. **前提** 资源集合包含聊天路由 Skill `template-router`，**当** 执行 `validate_skill` 与 `validate_all`，**则** 若 `template-router` 声明了任何业务网关 `apis` 或 `### <ID>` 引用了不存在/已下线模板则阻断（`ROUTER_SKILL_HAS_APIS` / `ROUTER_TEMPLATE_NOT_FOUND`）；若有在线模板未被 `template-router` 覆盖则发出 `ROUTER_TEMPLATE_UNCOVERED` 警告；离线模板（`.offline`）自动跳过模板级阻塞校验，系统提示词为空时触发 `SYSTEM_PROMPT_EMPTY` 错误。

### 2.2 成功标准

- **SC-001**：覆盖本规格的全部领域模型、沙箱渲染、契约解析与静态门禁测试集（`tests/test_list_fields.py`、`tests/test_api_builtin_placeholders.py`、`tests/test_api_response_modes.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`、`tests/test_deep_audit_fixes.py`、`tests/test_text_and_gateway.py`）100% 通过，`tests/test_migrated_seed.py` 验证 `validate_all` 对内置 33 套生产模板与 12 个 Skill 产出 `0 error / 0 warning`。
- **SC-002**：`render_body` 与 Java Pebble 3.2.2 引擎在标量、条件分支、循环列表、换行裁剪与 `hasDigit` 测试场景下渲染输出达到 100% 逐字一致，同时借助 `_compile_body_template`（`@lru_cache(maxsize=256)`）与 `_compile_safe_regex_cached`（`@lru_cache(maxsize=512)`）消除重复编译开销。
- **SC-003**：`safe_regex_compile` 能够以确定性显式栈遍历拒绝所有含嵌套重复量词（如 `(a+)+`）、超长（`> 2000` 字符）或超深括号嵌套的正则，在编译校验阶段零回溯超时、零 `RecursionError`。
- **SC-004**：`_TrackedSandboxEnvironment` 对沙箱越权方法调用（如 `list.append`）及未定义变量内部属性访问的拦截率达到 100%，且并发渲染协程之间通过 `_ACTIVE_USED` `ContextVar` 实现 100% 的 `used` 集合零串扰隔离。
- **SC-005**：声明式 `ApiContract` 契约与下游解析器协同支持 XML/JSON 双协议、5 种 `records.mode`（`auto`、`object`、`list`、`scalar`、`none`）、`noData` 优先判定、`flatten: true` 递归展平及显式点分列提取，双协议下产出 100% 一致的标准化记录结构。

### 2.3 假设

- **上下游子规格边界假设**：本规格聚焦静态资源建模、正则/Schema/交叉门禁校验与沙箱渲染引擎，不直接发起大模型推理、网络 HTTP 收发或 PVC 文件持久化；交卷动态 Pydantic 模型构造与证据核验归属 `003-agent-runner-evidence`，网关 HTTP 收发与 XML/JSON 报文实际解析函数（`gateway/base.py#extract_records`、`extract_json_records`）归属 `004-deterministic-tools-gateway`，文件持久化与发布锁归属 `002-git-store-hot-reload`。
- **运行环境与依赖假设**：运行环境锁定为 Python `>=3.12,<3.14`（核心依赖 `pydantic>=2.12,<3`、`jinja2>=3.1,<4`、`jsonschema>=4.23,<5`、`pyyaml>=6.0.2,<7`），正则安全分析基于 CPython 标准库 `re._parser` 语法树接口并附带 `RecursionError` 显式兜底。
- **全周期人天核算口径**：本子规格核定工作量 `33.0 人天`，覆盖架构与领域对齐（3.0 人天）、安全正则与加载诊断基座（6.0 人天）、模板建模与防 ReDoS 入参校验（6.5 人天）、Jinja2 沙箱与 `TrackedValue`/`TrackedList` 渲染追踪（6.0 人天）、Skill 与 `ApiContract` 双协议契约建设（5.5 人天）、`validate_all` 静态门禁实现（3.5 人天）及边界加固与全套测试验收（2.5 人天）。

---

## 3. 术语与概念定义 【核心，如有新术语】

> 通用平台术语（如 `单据文本`、`原文引用证据`、`整条引用`、`追踪标量/追踪列表`、`实际展示缺失字段`）见 `wiki/reference/glossary.md`；以下列出本规格领域层与沙箱引擎专属的核心概念。

| 术语 | 英文/标识 | 定义 | 备注 |
| --- | --- | --- | --- |
| 模板双文件定义 | `Template` / `TemplateDef` | 由 `templates/<id>/template.yaml`（元数据、入参、字段与 Skill 白名单）和 `body.md.j2`（Jinja2 正文）组合而成的报告模板领域聚合实体 | 可附带 `.offline` 标记文件表示已下线 |
| Pebble 词法单换行裁剪 | `_PebbleNewlineTrimExtension` | 在 Jinja2 词法流中精准剥离 `TOKEN_VARIABLE_END`（`}}`）后紧跟的单个 `\n` 换行，与 `trim_blocks=True` 协同对齐 Java Pebble 3.2.2 默认 `newLineTrimming` 语义的扩展 | 不影响纯文本字面 `}}` 与行首缩进 |
| 防 ReDoS 正则语法树预检 | `safe_regex_compile` | 基于 `re._parser.parse` 显式迭代栈遍历检测空匹配子式与嵌套重复量词（`_has_nested_repeat`），并限制最大长度 `2000` 字符的安全正则编译原语 | 用于入参正则与接口 Schema `pattern` |
| 声明式接口契约 | `ApiContract` | `apis/<name>.yaml` 定义的统一网关接口声明，包含连接器协议、`processCode`、JSON Schema `input`、请求/头模板、`noData`/`success` 与五种 `records.mode` | 仅声明结构，不携带任何可执行脚本 |
| 内置保留占位符 | `BUILTIN_PLACEHOLDERS`（`${$now}`） | 名称以 `$` 开头、由平台在单次组包时刻统一注入值的保留占位符（如 `${$now}` 生成 `yyyyMMddHHmmss`），禁止在 `input` 中声明或被模型入参覆盖 | 在 `request` 与 `headers` 替换时统一求值 |
| 资源树静态诊断项 | `ResourceSet` / `Issue` | `ResourceSet` 持有加载后的全量资源与 `load_issues`；`Issue` 为 `validate_all` 产出的分级（`error`/`warning`）问题记录，含稳定诊断码 `code`、资源定位与行号 | 支持 40 种结构化诊断码 |

---

## 4. 用户角色 【核心】

| 角色 | 类型 | 本需求中可执行的操作与数据范围 | 权限/安全约束 |
| --- | --- | --- | --- |
| 业务配置人员 / 模板维护人员 | 人工角色 | 编写与保存 `template.yaml`、`body.md.j2`、`SKILL.md`、`apis/<name>.yaml` 与 `system-prompt.md`，查看 `validate_all` 返回的 `Issue` 错误与行号定位 | 通过工作台鉴权后经 `store/` 与 `api/` 间接触发解析与校验，禁止在资源中夹带脚本或危险 Jinja 全局调用 |
| 平台发布审核员 | 人工角色 | 在发布前执行整棵资源树静态交叉门禁 `validate_all`，依据 `error` 阻断与 `warning` 提示确认发布合规性 | 所有 `error` 级诊断自动阻止新版本上线；仅允许基于合法 `ResourceSet` 发布 |
| 智能体运行时与渲染引擎 | 内部系统角色 | 消费 `Template`、`Skill`、`ApiContract`，调用 `validate_inputs` 校验入参，调用 `build_render_context` 与 `render_body` 输出正文及 `used` 字段集合 | 只读消费已锁定不可变快照中的领域对象，多协程通过 `_ACTIVE_USED` `ContextVar` 严格隔离 |
| 迁移对拍工具链 | 内部/离线验证角色 | 调用 `load_resource_dir`、`validate_all`、`build_render_context` 与 `render_body` 对 33 套生产资源进行结构校验与 Java Pebble 逐字渲染等价对拍 | 与线上共享唯一 `runtime/render.py` 渲染入口，仅限本地/CI 验证使用 |

---

## 5. 功能需求 【核心】

### 5.1 模板双文件建模与防 ReDoS 入参校验

#### FR-001 声明式双文件模板领域建模与严格 YAML 解析

- **来源**：`src/report_agent/domain/template.py`（`InputDef`、`ColumnDef`、`FieldDef`、`TemplateDef`、`Template`、`parse_template_yaml`、`dump_template_yaml`）
- **描述**：系统必须支持基于 `templates/<id>/template.yaml` 与 `templates/<id>/body.md.j2` 的声明式模板建模，完整表达入参定义、四类报告字段、列表列结构、缺失策略及可见性，并在反序列化阶段严格拒绝未知键。
- **关联用户故事/成功标准**：`US1` / `SC-001`
- **业务规则**：
  1. 领域基类 `_Base` 强制配置 `ConfigDict(extra="forbid", populate_by_name=True)`，任何未定义键或拼写错误在反序列化阶段立即抛出 `ValidationError`。
  2. 报告字段 `FieldDef` 支持四种类型：`string`、`enum`（需配置 `values`）、`date`（可选 `format`）与 `list`（需配置 `columns: list[ColumnDef]`）；列类型 `ColumnDef.type` 限定为 `string` 或 `enum`。
  3. 字段 `evidence` 限定为 `quote`、`input`、`derive`；`whenMissing` 限定为 `placeholder`（默认）、`empty`、`value`（配 `defaultValue`）；`visible` 控制是否为报告正文直接展示或循环输出的字段；`quoteWhole` 标记原文整段一致约束。
  4. `parse_template_yaml` 要求顶层必须为字典（空 YAML 视为空字典）；`dump_template_yaml` 以 `id`、`name` 在前并 `exclude_defaults=True`、`allow_unicode=True`、`sort_keys=False`、`width=1000` 序列化，确保往返无损等价。
- **输入/触发**：`template.yaml` 文本内容、`body.md.j2` 文本、`.offline` 存在标志或前端修改后的 `TemplateDef` 对象。
- **输出/结果**：合法校验后的 `TemplateDef` / `Template` 实例或格式规范的 YAML 字符串；非法输入抛出 `ValueError` 或 `ValidationError`。
- **验收标准**：
  - AC-1：包含四类字段、`ColumnDef`、`whenMissing` 三策略、`visible: false` 及 `quoteWhole` 的 `template.yaml` 经 `parse_template_yaml` 与 `dump_template_yaml` 往返解析后语义完全一致。
  - AC-2：向 `template.yaml` 传入未定义字段或非映射顶层结构（如列表或标量）时立即抛出校验错误并拒绝解析。

#### FR-002 确定性防 ReDoS 正则编译与运行时入参快速失败校验

- **来源**：`src/report_agent/domain/template.py`（`safe_regex_compile`、`safe_regex_fullmatch`）、`src/report_agent/runtime/runner.py#validate_inputs`
- **描述**：系统必须提供基于显式迭代语法树遍历的防 ReDoS 正则编译器与缓存匹配原语，统一服务于模板入参 `pattern` 校验、接口契约 JSON Schema 校验及运行时上游入参快速失败检查。
- **关联用户故事/成功标准**：`US1` / `SC-003`
- **业务规则**：
  1. `safe_regex_compile` 拒绝空串、非字符串及长度超过 `MAX_REGEX_LENGTH = 2000` 的正则，并捕获 `re.error` 与 `RecursionError` 统一抛出中文 `ValueError`。
  2. `_subpattern_can_match_empty` 与 `_has_nested_repeat` 通过显式栈迭代遍历 `re._parser.parse` 语法树（不递归调用自身），拦截重复量词内嵌套可变重复量词（如 `(a+)+`）、`hi > 1` 的可空重复体及可空分支内嵌重复模式。
  3. 合法模式经 `@lru_cache(maxsize=512)` 缓存编译后的 `re.Pattern`；`safe_regex_fullmatch` 执行整串完全匹配。
  4. 运行前 `validate_inputs(template, inputs)` 对每个入参先执行 `.strip()` 去首尾空白：必填项为空直接记录缺失错误；非空且声明了 `pattern` 时调用 `safe_regex_fullmatch`，不匹配则按序收集包含入参键名的中文错误信息。
- **输入/触发**：正则表达式字符串（入参 `pattern` 或 JSON Schema `pattern`）及运行请求传入的 `inputs: dict[str, str]`。
- **输出/结果**：缓存的编译正则 `re.Pattern`、布尔匹配结果或有序中文错误列表 `list[str]`。
- **验收标准**：
  - AC-1：输入超过 2000 字符的正则、超过 500 层嵌套括号的正则或 `(a+)+`、`([a-z]*)*` 等指数回溯正则时，`safe_regex_compile` 在毫秒级抛出中文 `ValueError` 且无 `RecursionError`。
  - AC-2：调用 `validate_inputs` 时缺失必填入参、仅空白字符串或不符合 `pattern` 的值均被精确拦截，合法入参返回空错误列表。

### 5.2 Pebble 兼容 Jinja2 沙箱与分支展示追踪渲染

#### FR-003 对齐 Java Pebble 3.2.2 的不可变 Jinja2 沙箱环境

- **来源**：`src/report_agent/domain/jinja_env.py`（`_TrackedSandboxEnvironment`、`_PebbleNewlineTrimExtension`、`_test_has_digit`、`make_environment`、`_compile_body_template`）
- **描述**：系统必须提供继承自 `ImmutableSandboxedEnvironment` 的 Jinja2 沙箱渲染环境，从词法换行裁剪、自定义测试、危险符号屏蔽与模板缓存四个维度精确对齐前代 Java Pebble 3.2.2 语义并保障沙箱安全。
- **关联用户故事/成功标准**：`US2` / `SC-002`、`SC-004`
- **业务规则**：
  1. 环境开启 `autoescape=False`、`keep_trailing_newline=True`、`trim_blocks=True`（不开启 `lstrip_blocks`，保留行首缩进），并通过词法过滤器 `_PebbleNewlineTrimExtension` 剥离紧跟 `TOKEN_VARIABLE_END`（`}}`）后的单个 `\n` 换行，但不影响正文中的字面 `}}`。
  2. 注册 `hasDigit` 自定义测试（`_test_has_digit`）：文本中含至少一个 Unicode 数字字符返回 `True`；`None`、`Undefined` 及仅含占位符文本（如 `{{标准资费}}`）返回 `False` 而不抛异常。
  3. 从 `env.globals` 移除 `cycler`、`joiner`、`lipsum`、`namespace` 四个危险或可变全局对象，依托 `ImmutableSandboxedEnvironment` 拦截所有可变容器方法（如 `list.append`）并抛出 `SecurityError`。
  4. 提供共享预编译缓存 `_compile_body_template(body, strict_undefined)`（`@lru_cache(maxsize=256)`），支持 `strict_undefined=False`（顶层缺失变量由 `_PlaceholderUndefined` 渲染为 `{{变量名}}` 占位符，对象子属性缺失仍抛错）与 `strict_undefined=True`（严格模式）双实例隔离。
- **输入/触发**：报告正文模板字符串 `body` 与编译/渲染调用请求。
- **输出/结果**：预编译的 `_TrackedTemplate` 对象或经安全拦截抛出的 `BodySyntaxError` / `SecurityError`。
- **验收标准**：
  - AC-1：包含 `{{ 字段 }}\n`、`{% if %}\n`、`{# 注释 #}\n`、字面 `}}` 及 `{% if 标准资费 is hasDigit %}` 的模板在沙箱内渲染输出与 Pebble 3.2.2 规则 100% 逐字一致。
  - AC-2：在模板中尝试调用 `{{ 列表.append('x') }}` 或使用 `cycler`/`namespace` 时抛出 `SecurityError`；访问未定义对象子属性时抛 `UndefinedError`。

#### FR-004 TrackedValue / TrackedList 与并发隔离展示字段追踪

- **来源**：`src/report_agent/domain/jinja_env.py`（`TrackedValue`、`TrackedList`、`_TrackedCodeGenerator`、`_TrackedTemplate`、`_wrap_filter_func`、`_ACTIVE_USED`、`render_body`）
- **描述**：系统必须实现精确的渲染期动态字段展示追踪机制，确保经过过滤、切片或拼接的标量字段及仅在生效分支迭代的列表字段均能准确计入 `used` 集合，并在并发与嵌套调用中保持零串扰。
- **关联用户故事/成功标准**：`US2` / `SC-002`、`SC-004`
- **业务规则**：
  1. `TrackedValue(str)` 记录来源字段名集合 `field_names` 与缺失标志 `missing`，重写 `strip`/`lstrip`/`rstrip`/`replace`/`lower`/`upper`/`title`/`removeprefix`/`removesuffix`/`split`/`rsplit`/`splitlines`/`__getitem__`/`__add__`/`__radd__`，确保转换后仍携带完整来源字段名与 `missing` 标记。
  2. `_TrackedCodeGenerator` 重写 Jinja2 `visit_Concat`（`~` 拼接）与 `visit_Add`（`+` 拼接），委托 `_tracked_concat` 与 `_tracked_add` 避免 CPython 原生字符串拼接剥离 `TrackedValue` 元数据；`_wrap_filter_func` 与 `call_filter` 收集过滤器入参（含 `list`/`tuple`/`Mapping` 容器内部）的追踪来源并包装返回字符串。
  3. `TrackedList(list)` 在 `{% if 列表 %}` 中仅触发 `__len__` 而不记入 `used`；仅在进入实际执行分支的 `{% for item in 列表 %}` 触发 `__iter__`（或直接被 `finalize` 输出）时将字段名写入当前 `ContextVar` `_ACTIVE_USED`。
  4. `render_body(body, context, *, strict_undefined=False)` 以单位置字典 `template.render(context or {})` 调用（规避字段名 `self` 冲突），并通过 `_ACTIVE_USED.set(used)` / `reset(token)` 实现异步并发协程与嵌套 `make_environment(used=...)` 渲染的完全隔离。
- **输入/触发**：正文模板 `body`、字段渲染上下文 `context` 及可选 `strict_undefined` 开关。
- **输出/结果**：二元组 `(rendered_text: str, used_fields: set[str])`。
- **验收标准**：
  - AC-1：`{{ 字段A | trim ~ 字段B }}`、`{{ [字段A] | join(",") }}` 或 `{{ 字段A + 字段B }}` 输出后，`used` 精确包含 `字段A` 与 `字段B`；未命中条件分支内的 `{{ 字段C }}` 或 `{% for x in 列表D %}` 不进入 `used`。
  - AC-2：当模板中存在名为 `self` 的字段或高并发协程同时调用 `render_body` 时，输出正确且各协程返回的 `used` 集合互不污染。

#### FR-005 唯一生产渲染上下文构建器 build_render_context 与 field_render

- **来源**：`src/report_agent/runtime/render.py`（`FieldRender`、`missing_value`、`list_rows`、`field_render`、`build_render_context`）
- **描述**：系统必须提供唯一且标准的报告渲染上下文构建模块，把智能体交卷字典转换为 `TrackedValue` 与 `TrackedList` 渲染上下文，使线上运行与迁移对拍验证共享同一语义路径。
- **关联用户故事/成功标准**：`US2` / `SC-002`
- **业务规则**：
  1. 对普通标量字段：当 `status == "found"` 且值非 `None`、非 `list`/`dict` 容器且去除空白后非空时，判定 `found=True`，以 `scalar_to_str` 转换结果构造 `TrackedValue(..., missing=False)`；否则判定 `found=False`，依据 `whenMissing`（`empty` → `""`、`value` → `defaultValue`、`placeholder` → `"{{字段名}}"`）生成渲染文本并构造 `TrackedValue(..., missing=True)`。
  2. 对列表字段（`type == "list"`）：当 `status == "found"` 且 `value` 为 `list`（含合法空列表 `[]`）时，经 `list_rows` 过滤仅保留模板声明列（丢弃非字典行），每行单元格包装为 `TrackedValue`（容器值规整为空串 `""`，不输出 Python `repr`）并组装为 `TrackedList(ctx_rows, f.name, missing=False)`；未找到时返回 `TrackedList([], f.name, missing=True)`。
  3. `build_render_context(template, report)` 遍历全部声明字段调用 `field_render`，`report` 为 `None` 时所有字段均按未找到处理。
- **输入/触发**：`Template` 领域对象与智能体提交的 `report` 字典（可为 `None`）。
- **输出/结果**：单字段 `FieldRender(found, value, rendered, context_value)` 及完整的 Jinja2 渲染上下文字典 `dict[str, Any]`。
- **验收标准**：
  - AC-1：`AgentRunner._finish` 与 `tools/java_migration/verify_render.py` 调用同一 `build_render_context` 入口，标量 `whenMissing` 三种策略与列表 `[]`/`not_found` 区分结果完全一致。
  - AC-2：向普通字段误传 `list`/`dict` 时 `field_render` 不会输出 Python 对象字符串表示（如 `['a']`），向列表字段传入多余未声明键时自动剥离。

### 5.3 纯文本 Skill 与声明式双协议接口契约建模

#### FR-006 纯文本 SKILL.md 解析规范与脚手架生成

- **来源**：`src/report_agent/domain/skill.py`（`SkillMeta`、`Skill`、`SkillParseError`、`parse_skill_markdown`、`build_skill_markdown`）
- **描述**：系统必须支持解析由 YAML frontmatter 与 Markdown 正文组成的无脚本纯文本 `SKILL.md`，为模型规划提供声明式方法论说明并严格校验元数据。
- **关联用户故事/成功标准**：`US3` / `SC-001`
- **业务规则**：
  1. `parse_skill_markdown` 先剥离 UTF-8 BOM（`\ufeff`）并将 `\r\n`/`\r` 归一化为 `\n`，要求文本必须以 `---` 包裹的合法 YAML frontmatter 开头，否则抛出 `SkillParseError`。
  2. `name` 必须为非空字符串（去除首尾空白）；`title` 与 `description` 为 `None` 时规整为空串 `""`，为数值/字符串时转字符串并拒绝布尔/容器类型；`SkillMeta` 允许 `extra="ignore"` 兼容扩展元信息。
  3. `apis` 字段同时兼容 YAML 字符串列表与逗号分隔字符串（`None` 或空串规整为 `[]`），自动去空白并保序去重；列表内非字符串非空元素抛 `SkillParseError`。
  4. `build_skill_markdown` 按固定结构生成包含frontmatter与标准五节标题（适用场景、需要的入参、查询方法、识别规则、提交要求）的初始化模板。
- **输入/触发**：`SKILL.md` 原始全文或新建 Skill 的标识、标题、描述和接口列表。
- **输出/结果**：`Skill(meta, body, markdown)` 领域对象或格式化 Markdown 文本。
- **验收标准**：
  - AC-1：含 BOM、Windows 换行及逗号分隔 `apis: "a, b, a"` 的 `SKILL.md` 经解析后 `apis == ["a", "b"]`、`body` 去除前导空白且保留原始 `markdown`。
  - AC-2：缺失 `---` 分隔符、frontmatter 顶层非字典或 `name` 为空串时抛出 `SkillParseError`。

#### FR-007 声明式 ApiContract 契约建模、`${$now}` 内置占位符与安全请求头校验

- **来源**：`src/report_agent/domain/api_contract.py`（`ApiContract`、`RetrySpec`、`BUILTIN_PLACEHOLDERS`、`builtin_values`、`parse_api_yaml`、`fixed_params`）
- **描述**：系统必须支持声明式 `apis/<name>.yaml` 接口契约建模、JSON Schema 编译缓存、内置占位符安全注入以及防 CRLF 注入的自定义 HTTP 请求头模板校验。
- **关联用户故事/成功标准**：`US3` / `SC-005`
- **业务规则**：
  1. `ApiContract` 采用 `extra="forbid"`，声明 `connector`（`unified-gateway-xml` / `unified-gateway-json`）、`processCode`、`timeoutMs`（`100~120000`）、`retry.maxAttempts`（`1~5`）、`idempotent`、`headers`、`input`（JSON Schema）、`request` 与 `response`。
  2. `schema_errors()` 检查：`processCode` 非空；`input` 为合法 `Draft202012Validator` Schema 且内部全部 `pattern` 均通过 `safe_regex_compile`；XML 连接器检查合法 XML 标签名（`_XML_TAG_RE`），JSON 连接器禁止空键名；禁止 `input.properties` 声明任何 `$` 开头保留键；`request` 和 `headers` 中所有 `${...}` 引用必须属于 `input.properties` 或 `BUILTIN_PLACEHOLDERS`（当前为 `$now`）。
  3. `build_request` 与 `build_headers` 在替换占位符前调用 `_with_builtins(args)`：过滤调用方传入的任何 `$` 开头键，按单次组包时刻统一注入 `$now`（本地时间 `yyyyMMddHHmmss`）；整段字符串恰好为 `${参数}` 时 `copy.deepcopy` 保留原始 `dict`/`list` 类型。
  4. `_validate_headers_dict` 在契约校验与 `build_headers` 运行替换后双重拦截空头名、换行符 `\r`/`\n`/NUL 与控制字符（允许值内 `\t`）、非法 RFC 字符及受保护请求头（`host`、`content-length`、`transfer-encoding`）；`fixed_params` 识别仅含内置占位符 `${$now}` 的请求项并在管理端原样展示。
- **输入/触发**：`apis/<name>.yaml` 文本与运行时调用参数字典 `args`。
- **输出/结果**：`ApiContract` 实例、`schema_errors()`/`validate_args()` 错误列表、组包后的 `request`/`headers` 字典或预览结构。
- **验收标准**：
  - AC-1：若模型入参尝试覆盖 `$now` 或契约在 `input` 中声明 `$now`，`build_request` 忽略覆盖值并以组包实时时间替代，`schema_errors` 精确报错。
  - AC-2：传入导致替换后请求头包含 `\r\n` 或尝试覆盖 `Host`/`Content-Length` 时，`schema_errors` 与 `build_headers` 均拦截拒绝。

#### FR-008 双协议响应结构契约声明（noData 优先、五种记录抽取模式与展平策略）

- **来源**：`src/report_agent/domain/api_contract.py`（`SuccessSpec`、`NoDataRule`、`RecordsSpec`、`SummarySpec`、`ResponseSpec`），协同下游 `src/report_agent/gateway/base.py`（`extract_records`、`extract_json_records`）
- **描述**：系统必须在领域契约层完整支持统一网关 XML 与 JSON 双协议的响应判定及结构化记录抽取声明，确保各种空节点、标量、单对象与嵌套报文在下游呈现完全一致的契约语义。
- **关联用户故事/成功标准**：`US3` / `SC-005`
- **业务规则**：
  1. `ResponseSpec` 包含 `success: SuccessSpec | None`（含 `path`、`equals`、`missingAs="success"|"failure"`）、`noData: list[NoDataRule]`（支持 `equals` 与 `contains`）、`records: RecordsSpec` 与 `summary: SummarySpec`（`maxPreviewChars=60`、`previewRows`）。
  2. 通过 Pydantic `mode="before"` 验证器，自动将 YAML 中显式写为 `null` 的 `headers`、`response`、`noData`、`records`、`summary`、`records.path` 与 `records.columns` 规整为空字典/空列表/空串，并将标量列说明与头值规范化为字符串。
  3. `RecordsSpec.mode` 支持五种契约模式：`auto`（默认，识别标准 `content.list` 自动解包多行）、`object`（严格单对象取首条）、`list`（强制多行列表）、`scalar`（标量包为单列记录且保留 `"0"`/`"false"`）与 `none`（仅校验 `success` 与 `noData`，不抽取表格记录）。
  4. 支持 `path: ""`（根路径直取）、`flatten: true` 嵌套展平及显式点分列路径（如 `userInfo.userName`），供下游网关解码器依据契约在 XML 与 JSON 下产出一致的记录列表。
- **输入/触发**：`apis/<name>.yaml` 中 `response` 段声明数据。
- **输出/结果**：规范化的 `ResponseSpec`、`RecordsSpec` 模型，供下游 `gateway/base.py` 与 `runtime/tools.py` 消费。
- **验收标准**：
  - AC-1：YAML 中将 `records.path: null`、`records.columns: null`、`noData: null` 或 `headers: null` 时可正常解析为 `""`/`{}`/`[]` 不抛校验异常。
  - AC-2：契约声明覆盖五种 `mode`、`noData`、`flatten` 与点分路径，与 `tests/test_api_response_modes.py` 中 XML/JSON 双协议对拍预期完全匹配。

### 5.4 资源安全加载与整树静态交叉门禁

#### FR-009 资源目录安全加载与软链逃逸损坏隔离（load_resource_dir）

- **来源**：`src/report_agent/domain/resources.py`（`ResourceSet`、`Issue`、`load_template_dir`、`_within_root`、`load_resource_dir`、`read_offline_marker`）
- **描述**：系统必须提供全目录资源安全加载器，对单个损坏文件或软链接越界行为实现精确隔离记录，防止单一故障资源阻塞其余正常资源的加载与诊断。
- **关联用户故事/成功标准**：`US4` / `SC-001`
- **业务规则**：
  1. `_within_root(path, root_resolved)` 通过 `path.resolve().is_relative_to(root_resolved)` 检查所有目录及内部文件（`system-prompt.md`、`template.yaml`、`body.md.j2`、`.offline`、`SKILL.md`、`apis/*.yaml`），任何指向资源根目录之外的软链接均被拦截，生成 `LOAD_FAILED` 错误并跳过该资源。
  2. 强校验目录/文件名标识一致：`template.yaml` 的 `id` 必须等于目录名、`SKILL.md` 的 `name` 必须等于目录名、`apis/<name>.yaml` 的 `name` 必须等于文件 stem。
  3. 单个资源存在 YAML/Markdown 语法错误、Pydantic 校验异常或 OS 读取失败时，仅向 `ResourceSet.load_issues` 追加 `LOAD_FAILED` 记录，其余合法资源继续完整装载。
  4. `ResourceSet` 提供 `skill_by_ref`（按 ID 或中文 `title` 查找）与 `allowed_apis(template)`（按 Skill 声明顺序收集去重且存在于 `rs.apis` 中的接口列表）。
- **输入/触发**：发布态目录或叠加工作副本根目录 `root: Path`。
- **输出/结果**：聚合容器 `ResourceSet`（含 `system_prompt`、`templates`、`skills`、`apis` 与 `load_issues`）。
- **验收标准**：
  - AC-1：向模板目录、Skill 目录或 `apis/` 放入指向根目录外部的软链接或语法损坏的 YAML 时，`load_issues` 记录精确 `LOAD_FAILED` 且其余合法模板/Skill/接口仍正常加载。
  - AC-2：当 `template.yaml` 中 `id` 与目录名不一致时被识别为 `LOAD_FAILED` 隔离，不误覆盖其他模板槽位。

#### FR-010 整棵资源树静态交叉校验门禁（validate_all）

- **来源**：`src/report_agent/domain/resources.py`（`validate_template`、`validate_skill`、`validate_api`、`validate_all`、`_list_field_issues`、`_loop_attr_uses`）
- **描述**：系统必须提供整棵资源树的发布前静态交叉校验门禁，全面核查语法、字段/列规范、正文 AST 变量、列表循环作用域、跨资源引用、系统提示词及 `template-router` 双向覆盖，输出稳定的分级诊断码（共 40 项）。
- **关联用户故事/成功标准**：`US4` / `SC-001`
- **业务规则**：
  1. **模板定义与字段/列规则**：检查模板名非空、入参唯一及合法安全正则；检查字段名与列名符合 `_bad_identifier`（禁下划线/数字开头、模板保留字、空白大括号，列名额外禁与 `dict` 内置属性重名如 `items`/`keys`/`values`/`get`）；检查 `enum` 可选值、`defaultValue` 合法性、`input` 证据有入参；对 `type=list` 强制要求至少一列且 `evidence in {"quote","derive"}`、`whenMissing == "empty"`、禁 `quoteWhole` 与顶层 `values`；对字段与入参同名非 `input` 发 `FIELD_SAME_AS_INPUT` 警告。
  2. **正文 AST 与列表作用域检查**：解析正文 Jinja2 AST，统计未定义引用报 `BODY_UNDEFINED_FIELD`（附行号），对 `visible=True` 但未引用发 `VISIBLE_NOT_IN_BODY` 警告；检查 `{% for x in 字段 %}` 禁止遍历非列表字段（`FOR_NON_LIST`）、禁止元组多变量解构（`LIST_LOOP_TARGET`）、检查循环体内 `x.列名` / `x["列名"]` 未声明列（`LIST_COLUMN_UNDEFINED`，遇内层同名重绑定 `for` 时仅检 `iter` 与 `else_` 避免作用域串扰误报）；对直接输出 `{{ 列表 }}` 发 `LIST_PRINTED` 警告；对 `{% if 列表 %}` 发 `LIST_IN_IF_CONDITION` 警告。
  3. **跨资源引用与 `template-router` 核验**：校验模板关联的 `skills` 与 Skill 声明的 `apis` 存在性（`SKILL_NOT_FOUND` / `API_NOT_FOUND`）；禁止填报模板引入 `template-router`（警告 `ROUTER_SKILL_IN_TEMPLATE`）；对 `template-router` 强制禁止声明 `apis`（`ROUTER_SKILL_HAS_APIS`）、检查 `### <ID>` 标题对应的模板必须存在且未下线（`ROUTER_TEMPLATE_NOT_FOUND`），对未在 `template-router` 维护说明的在线模板发 `ROUTER_TEMPLATE_UNCOVERED` 警告。
  4. **全局与离线策略**：`validate_all` 自动继承 `rs.load_issues`；已标记 `.offline` 的模板跳过 `validate_template` 检查；`system_prompt` 为空白时产生 `SYSTEM_PROMPT_EMPTY` 错误；所有接口经 `validate_api` 转为 `API_SCHEMA` 错误。
- **输入/触发**：完整 `ResourceSet` 实例。
- **输出/结果**：有序诊断项列表 `list[Issue]`（包含 `level`、`code`、`message`、`kind`、`key`、`field`、`line`）。
- **验收标准**：
  - AC-1：逐一覆盖 40 种诊断码的构造场景时，`validate_all` 返回精确匹配的 `level`、`code`、`field` 与 `line`。
  - AC-2：运行 `tests/test_migrated_seed.py` 对仓库内 33 套生产模板与 12 个 Skill 执行 `validate_all`，结果为 `0 error / 0 warning`。

---

## 6. 非功能需求 【补充】

| 类型 | 编号 | 说明 | 验收方式 |
| --- | --- | --- | --- |
| 零业务硬编码 | `NFR-001`（关联宪章原则 I） | `src/report_agent/domain/` 与 `runtime/render.py` 不包含任何具体模板 ID（`100~132`）、业务套餐或短信词硬编码，仅保留通用路由器标识常量 `ROUTER_SKILL_ID = "template-router"` | 代码静态审查 + `tests/test_migrated_seed.py` 跨种子隔离校验 |
| 防幻觉与证据语义 | `NFR-002`（关联宪章原则 II） | 模板字段强制要求声明 `evidence` 与 `whenMissing`，列表强制 `whenMissing="empty"` 与 `quote`/`derive` 限定；`TrackedValue`/`TrackedList` 通过 `ContextVar` 精确汇报实际展示与缺失字段，支撑下游 `SUCCESS`/`PARTIAL` 判定 | `tests/test_list_fields.py`、`tests/test_deep_audit_fixes.py` |
| 单进程并发隔离 | `NFR-003`（关联宪章原则 III） | `_TrackedSandboxEnvironment` 与 `@lru_cache` 编译缓存（正则 `512`、模板 `256`）在多协程并发下仅通过 `ContextVar`（`_ACTIVE_USED`）传递状态，无跨请求共享可变全局状态 | `tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py` |
| 安全与防注入 | `NFR-004`（关联宪章原则 VI） | 显式迭代栈阻断 ReDoS 与 `RecursionError`；`ImmutableSandboxedEnvironment` 移除 `cycler`/`joiner`/`lipsum`/`namespace` 阻断模板越权；`_validate_headers_dict` 阻断请求头 CRLF 与受保护头覆盖；`_within_root` 阻断软链逃逸 | `tests/test_review_runtime.py`、`tests/test_text_and_gateway.py` |
| 可复现测试与性能边界 | `NFR-005`（关联宪章原则 V） | 全部单测不访问外网大模型或真实网关，借助 `tests/conftest.py` 的 `SEED_DIR` 隔离机制避免受生产模板变更干扰；渲染与正则编译依托有界 `@lru_cache`（256/512）消除重复解析开销 | `uv run pytest -q` 全量通过 + `verify_render.py` 对拍验证 |
| 源码规范与前端边界 | `NFR-006`（关联宪章原则 VIII、X） | 遵循 Python `>=3.12,<3.14` 类型注解与 `ruff@0.11.0` 零告警规范；本需求属于纯后端领域层与运行时渲染层，不涉及前端界面与 `embed.html` 分包改造 | `uvx ruff@0.11.0 check src tests` |

---

## 7. 数据与存储需求 【补充】

> 本需求不直接修改或持久化 `DATA_DIR` 磁盘文件（由 `002-git-store-hot-reload` 负责原子写入与版本管理），仅定义四类声明式文件资源的数据结构契约与进程内无状态有界内存缓存：

| 数据对象/存储位置 | 变更类型 | 关键字段与口径 | 一致性/留存策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `templates/<id>/template.yaml` 与 `body.md.j2`（及 `.offline`） | 规范定义（只读解析） | `TemplateDef`（`id`, `name`, `skills`, `inputs`, `fields`）+ Jinja2 正文文本 | Pydantic `extra="forbid"` 严格校验，与目录名强一致 | `FR-001`、`FR-009` |
| `skills/<id>/SKILL.md` | 规范定义（只读解析） | YAML frontmatter（`name`, `title`, `description`, `apis`）+ Markdown 正文 | BOM 剥离、`\n` 归一化、`apis` 保序去重、与目录名一致 | `FR-006`、`FR-009` |
| `apis/<name>.yaml` | 规范定义（只读解析） | `ApiContract`（`connector`, `processCode`, `timeoutMs`, `retry`, `headers`, `input`, `request`, `response`） | `extra="forbid"`、实例级 `_validator_cache` 校验器复用 | `FR-007`、`FR-008` |
| `system-prompt.md` | 规范定义（只读加载） | 纯文本系统提示词模板 | 非空白门禁校验（`SYSTEM_PROMPT_EMPTY`） | `FR-009`、`FR-010` |
| 进程内有界内存缓存与协程上下文 | 新增运行期内存结构 | `_compile_safe_regex_cached`（LRU 512）、`_compile_body_template`（LRU 256）、`_ACTIVE_USED`（`ContextVar`） | 不可变对象缓存永不过期；`ContextVar` 通过 `try/finally` 自动 `reset(token)` | `FR-002`、`FR-003`、`FR-004` |

---

## 8. 外部接口与集成 【补充】

> 本需求不直接新增对外 HTTP/SSE 端点或外部网络客户端，以下列出本领域层定义的内部边界契约与面向统一网关的声明式结构摘要：

| 接口/系统 | 方向 | 交互内容 | 是否新增 | 关联需求 | 备注 |
| --- | --- | --- | --- | --- | --- |
| `store/` 资源管理与发布器（`002`） | 内部入站调用 | 调用 `load_resource_dir`、`validate_all`、`validate_template`/`validate_skill`/`validate_api` 获取 `ResourceSet` 与 `Issue` 列表 | 否（既有内部模块契约） | `FR-009`、`FR-010` | `Publisher.publish` 用其做增量错误拦截 |
| `runtime/` 智能体执行引擎（`003`） | 内部入站调用 | 调用 `validate_inputs`、`build_render_context`、`render_body` 获取入参错误、上下文与 `(text, used)` | 否（既有内部模块契约） | `FR-002`、`FR-004`、`FR-005` | 支撑 `SUCCESS`/`PARTIAL` 状态判定 |
| `gateway/` 统一网关连接器（`004`） | 内部消费 `ApiContract` | 消费 `ApiContract.validate_args`、`build_request`、`build_headers` 及 `ResponseSpec`/`RecordsSpec` | 否（既有内部模块契约） | `FR-007`、`FR-008` | 实际 HTTP 收发与报文解析由 `004` 执行 |
| `tools/java_migration/` 对拍工具链（`008`） | 离线验证调用 | 复用 `load_resource_dir`、`validate_all`、`build_render_context`、`render_body` 与 `ApiContract` | 否（既有内部工具调用） | `FR-005`、`FR-010` | 确保迁移结构与渲染 100% 一致 |

### 8.1 出站网关与模型接口契约摘要（涉及时填写）

> 本需求不直接发起出站 HTTP 请求，网络层收发实现归属 `004-deterministic-tools-gateway`；以下仅列出本需求在 `ApiContract` 中定义并校验的出站网关声明式契约字段：

| 接口/工具 | 调用方向 | 协议与端点 | 路由/识别字段 | 成功判定 | 关键失败与降级策略 |
| --- | --- | --- | --- | --- | --- |
| `apis/<name>.yaml`（`ApiContract` 契约） | 平台 → 统一网关（声明式规范） | `unified-gateway-xml` / `unified-gateway-json` | `processCode`、`headers`（禁止覆盖 `host`/`content-length`/`transfer-encoding`） | `noData` 优先判定为空（`ok=True, no_data=True`）；否则校验 `response.success`（`path` + `equals` + `missingAs`） | 参数校验错误直接返回中文列表；组包替换通过 `_with_builtins` 锁定 `${$now}` 防模型覆盖 |

### 8.2 三类独立交付物涉及情况

| 独立文档 | 涉及情况 | 判断依据与范围摘要 | 确认来源/日期及关联需求 |
| --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求仅定义内部 Python 领域模型、静态门禁与渲染契约，不新增或变更面向外部系统的 HTTP/SSE/postMessage 接口 | 归档重构指令确认（2026-11-16）；`FR-001`–`FR-010` |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 生产 33 套模板、12 个 Skill 与 3 套契约存放于 `src/report_agent/seed/`，其全量迁移工作另归属 `008-java-migration-delivery` | 归档重构指令确认（2026-11-16）；`FR-009`、`FR-010` |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求不新增环境变量、容器镜像参数或运维配置动作 | 归档重构指令确认（2026-11-16）；`NFR-006` |

---

## 9. 边界与约束 【补充】

### 9.1 范围边界

**本次需求包含（In Scope）：**

- `src/report_agent/domain/template.py`：双文件模板模型、`extra="forbid"` 严格基类、YAML 序列化/反序列化、正文行号提取与显式栈防 ReDoS 正则编译器。
- `src/report_agent/domain/jinja_env.py`：对齐 Pebble 3.2.2 的不可变沙箱环境、`_PebbleNewlineTrimExtension`、`hasDigit` 测试、`TrackedValue`/`TrackedList`/`_TrackedCodeGenerator`、`ContextVar` 追踪隔离与 LRU 模板编译缓存。
- `src/report_agent/runtime/render.py` 与 `runner.py#validate_inputs`：唯一生产渲染上下文构建器 `build_render_context`/`field_render` 及运行前入参快速失败校验。
- `src/report_agent/domain/skill.py` 与 `api_contract.py`：纯文本 `SKILL.md` 解析与生成、声明式 `ApiContract`（双协议、`Draft202012Validator` 缓存、`${$now}` 占位符、安全请求头及五种响应模式模型）。
- `src/report_agent/domain/resources.py`：软链防逃逸加载 `load_resource_dir` 与覆盖 40 项诊断码的全量交叉门禁 `validate_all`。

**本次需求不包含（Out of Scope）：**

- 智能体 ReAct 推理循环、动态交卷模型 `build_report_model` 与 `EvidenceChecker` 证据核验（归属 `003-agent-runner-evidence`）。
- 12 个确定性平台工具实现、网关实际 HTTP 请求收发及 XML/JSON 响应树展平解析（`gateway/base.py` 归属 `004-deterministic-tools-gateway`）。
- PVC 文件持久化、内部 Git 仓库提交、草稿乐观锁、`RunStore` 与热更新存储（归属 `002-git-store-hot-reload`）。
- FastAPI HTTP 路由、鉴权、Vue 工作台界面、嵌入式聊天路由与 Java 资产批量迁移脚本（分别归属 `005`～`008`）。

### 9.2 技术与业务约束

- **零业务硬编码约束**：严格遵守项目宪章原则 I，`domain/` 与 `render.py` 严禁写入特定模板编号、特定短信特征词或具体套餐业务逻辑。
- **CPython 版本窗口约束**：防 ReDoS 分析器复用标准库 `re._parser.parse`，受 `pyproject.toml` 声明的 `requires-python = ">=3.12,<3.14"` 版本约束保障，并通过迭代栈与 `RecursionError` 捕获兜底。
- **单向依赖约束**：`src/report_agent/domain/` 严禁导入 `runtime/`、`store/`、`gateway/` 或 `api/`；仅允许 `runtime/render.py` 单向复用 `domain/` 与 `runtime.evidence.scalar_to_str`。
- **列表字段硬约束**：`type: list` 字段必须配置至少 1 列 `columns`，且强制限定 `whenMissing == "empty"`、`evidence in {"quote", "derive"}`、禁止 `quoteWhole` 与顶层 `values`，确保行级渲染与 `PARTIAL` 追踪语义一致。

---

## 10. 异常场景与边界情况 【核心】

| 编号 | 场景描述 | 触发条件 | 预期处理方式 | 是否阻断主流程 | 优先级 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- |
| EX-001 | 目录内部软链接逃逸与损坏文件加载 | `load_resource_dir` 扫描到指向根目录外的软链接，或 YAML/Markdown 语法损坏 | 记入 `ResourceSet.load_issues`（`LOAD_FAILED`），跳过损坏条目确保其余合法资源正常装载 | 否（仅隔离单条目，但阻断发布门禁） | 高 | `FR-009` |
| EX-002 | YAML 配置中的 `null` 值与标量类型混用 | `ApiContract` 中 `headers`、`noData`、`records.path` 或 `records.columns` 显式写为 `null` 或数字/布尔 | Pydantic `mode="before"` 自动规整为 `{}`/`[]`/`""` 或规范字符串，避免误判合法简化配置 | 否 | 中 | `FR-008` |
| EX-003 | 模板字段名与 Python/Jinja 形参 `self` 冲突 | 模板定义名为 `self` 的字段并在正文输出或引用 | `render_body` 以位置参数 `template.render(context or {})` 传参而非 `**context` 解包，彻底规避形参覆盖报错 | 否 | 高 | `FR-004` |
| EX-004 | 超深括号嵌套或 ReDoS 恶意正则 | 入参或 Schema `pattern` 包含数千层括号或 `(a+)+` 嵌套重复量词 | `_subpattern_can_match_empty` 显式栈加 `memo` 避免栈溢出，识别高危模式或捕获 `RecursionError` 统一抛出中文 `ValueError` | 是（拒绝非法配置/请求） | 高 | `FR-002` |
| EX-005 | 内层循环重绑定同名循环变量 | 外层 `{% for item in A %}` 嵌套内层 `{% for item in B %}` 并访问 `B` 的列 | `_loop_attr_uses` 仅检查内层循环的 `iter` 与 `else_` 分支，跳过内层循环体，避免按外层列定义误报 `LIST_COLUMN_UNDEFINED` | 否 | 中 | `FR-010` |
| EX-006 | 占位符复杂类型传递与模型覆盖内置变量 | 整段字符串仅含 `${参数}` 或模型传入 `$now` 参数覆盖内置时间戳 | 整段占位符通过 `copy.deepcopy` 保留原 `dict`/`list` 类型；`_with_builtins` 剔除所有 `$` 开头入参确保 `${$now}` 不可篡改 | 否 | 高 | `FR-007` |

---

## 11. 待确认事项 【核心】

> 本规格已于 2026-11-16 完成代码实装与全量测试归档验收，历史上关键设计歧义均已闭环解决，当前无未关闭阻塞项。

| 编号 | 问题描述 | 影响范围 | 责任方 | 期望确认日期 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| Q-001 | 前代 Pebble 模板中 `{% if 列表 %}` 条件写法在缺少数据时是否直接报阻断错误还是降级警告 | `FR-010`、`validate_template` | 架构与模板治理负责人 | 2026-11-12 | 已关闭 | 定为 `warning`（`LIST_IN_IF_CONDITION`），引导改为 `{% for %}...{% else %}` 以确保 `PARTIAL` 追踪生效，同时兼容存量模板逐步整改 |
| Q-002 | 正则 ReDoS 分析器是否引入第三方 `google-re2` 扩展或基于标准库 `re._parser` 构建 | `FR-002`、`safe_regex_compile` | 平台核心研发 | 2026-11-12 | 已关闭 | 采用基于标准库 `re._parser` 的显式迭代栈分析，保持零 C++ 扩展依赖与标准正则语法 100% 同源，并限定 Python `>=3.12,<3.14` |

---

## 附录：原始需求描述 【补充】

```text
子规格编号：001-domain-jinja-sandbox（RA-001，33.0 人天，18 项任务）
需求定位：智能申告报告填写与资源治理平台（report-agent）全栈研发工作拆分 —— 负责报告模板双文件建模、防 ReDoS 入参校验、对齐 Pebble 3.2.2 的 Jinja2 沙箱与分支展示追踪（TrackedValue/TrackedList）、纯文本 Skill 与声明式接口契约解析及整树静态发布校验。
归档转换指令：严格按改造后中文 Spec-Kit 模板与 SDD 标准重构为 spec.md / plan.md / tasks.md 三件套，保留真实源码与测试路径、4 个 User Story、FR-001~FR-010 与 33.0 人天（18 项任务）配比，并核验章节完备性与零占位符红线。
```

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 完成 `001-domain-jinja-sandbox` 存量模块需求、设计与任务初版归档拆分 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 依据改造后中文 `.specify/templates/spec-template.md` 与 `/sdd-documentation` 标准重构全章节、补充取证分级、AC 列表、NFR/EX/Q 追踪及三类独立交付物台账 |

---

## 增量更新说明

> 本文档按 `report-agent` 中文 Spec-Kit 模板与 SDD 取证规范生成；后续如有范围或契约变更，同步更新对应章节与 `变更记录` 并联动刷新 `plan.md` 与 `tasks.md`。
