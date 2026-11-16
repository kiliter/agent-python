# 需求文档（Spec）：单智能体执行管道、动态交卷模型与强证据核验防幻觉引擎

<!-- #Created By AiCoding(codex) -->

> **Spec Kit 使用约定**：产物文件名固定为 `spec.md`、`plan.md`、`tasks.md`；三类外部独立交付物按需确认，仅涉及项单独生成并建立链接，不涉及项只记录依据。生成时已将全部模板占位提示替换为核实后的实际内容；不适用章节保留标题并说明 `本需求不涉及` 及依据。
> **项目依据**：项目宪章 `.specify/memory/constitution.md`、`AGENTS.md` 及 `wiki/index.md`。遵循先取证后写作原则，优先核对代码、测试与运行证据，不把推测写成事实。

---

**功能分支**：`003-agent-runner-evidence`

**创建日期**：2026-11-16

**状态**：已交付归档

**输入**：用户描述："智能申告报告填写与资源治理平台（`report-agent`）全栈研发工作拆分 —— 负责单智能体统一规划管道、基于模板动态构造严格交卷 Schema（支持 4 种输出模式与模型缓存）、`quote`/`input`/`derive` 强证据校验、列表空结果与依赖环检测、`ModelRetry` 打回重填与级联降级挽救、并发限流与过程轨迹事件流。"

## 基本信息 【核心】

| 字段 | 内容 |
| --- | --- |
| 需求编号 | `RA-003` |
| 需求名称 | 单智能体执行管道、动态交卷模型与强证据核验防幻觉引擎 |
| 核算工作量 | 33.0 人天（全栈研发工作拆分 250.0 人天之子规格 `003/008`） |
| 资料与证据来源 | 1. **核心源码（高可信）**：`src/report_agent/runtime/{__init__.py,deps.py,workspace.py,output_model.py,evidence.py,prompt.py,model_factory.py,runner.py}`、`src/report_agent/seed/system-prompt.md`、`src/report_agent/config.py`<br>2. **自动化测试（高可信）**：`tests/{scripted_model.py,test_agent_runtime.py,test_native_output.py,test_review_runtime.py,test_review_fixes_runtime.py,test_runtime_config_hot_reload.py}`<br>3. **实测运行证据（最高可信）**：本轮全量测试 `uv run pytest -q`（`196 passed in 51.41s`）与静态检查 `uvx ruff@0.11.0 check src tests`（`All checks passed!`）<br>4. **架构与规范依据（参考级）**：`.specify/memory/constitution.md`、`AGENTS.md`、`wiki/architecture/{request-pipeline.md,evidence-system.md}`、`wiki/components/agent-runner.md`、`wiki/decisions/adr-001-single-agent-and-evidence.md` |
| 文档版本 | 2.0 |
| 文档状态 | 已交付归档 |

---

## 1. 业务背景与目标 【核心】

### 1.1 业务背景

在智能申告报告填写平台建设前，前代 Java 架构（`pdf-agent-parse`）依赖多个智能体串行编排并结合大量 Groovy 脚本执行规则判断与报告组装，存在跨智能体上下文丢失、业务逻辑硬编码散落、日期/文本依赖模型隐式推理且缺乏最终结论出处防线等系统性风险。当大模型在未核验原文的情况下截断订购短信、误把提示词当证据、遗漏必填字段或在交叉引用中产生自相矛盾的结论时，未经校验的错误报告会直接流出至客户告知与工单稽核环节。

为彻底消除业务硬编码与模型幻觉风险，需要在 `report-agent` 平台构建单一 `AgentRunner` 核心运行时子系统：每次申告填写请求由单个大模型智能体在统一共享的 `Workspace` 中自主规划工具调用，通过基于模板元数据动态编译的严格交卷 Schema（`Report{id}`）收窄结构化输入空间，再由确定性 `EvidenceChecker` 在交卷出口实施强证据逐条闭环校验与级联降级挽救，同时满足多推理服务适配（`tool`/`native`/`json_object`/`prompted`）、在线配置热更新零撕裂、进程内并发控流及全链路过程事件溯源。

### 1.2 业务目标

- **GOAL-1**：以单智能体自主规划架构替代多智能体串行与 Groovy 脚本引擎，通过白名单任务提示词（`build_task_instructions`）与动态生成且禁额外键的 `Report{id}` 交卷模型实现 100% 平台零业务硬编码。
- **GOAL-2**：通过 `EvidenceChecker` 建立覆盖 `quote`、`input`、`derive`、`VALUE_TOOLS`、列表逐行与空列表 0 行查询证明及可达依赖环检测的强证据门禁，杜绝任何无真实依据的 `status="found"` 结论进入最终报告。
- **GOAL-3**：在面对局部格式漂移或重试耗尽时，通过 `ModelRetry` 精准打回重填、`_salvage_partial_report` 字段挽救与 `_cascade_degraded_fields` 不动点级联降级实现“零幻觉前提下的最大化可用字段保留”。
- **GOAL-4**：依托 `_RuntimeBundle`、跨线程安全 `_DynamicLimiter`、`EventSink` 过程轨迹流与 `DocumentIndex` 精确行列偏移定位，保障单进程部署下高可用在线热切、完整可观测性与前端/嵌入式窗口溯源能力。

---

## 2. 需求概述 【核心】

本需求交付 `report-agent` 智能体执行主干（`src/report_agent/runtime/` 中除工具实体外的 8 个核心模块及全局系统提示词 `src/report_agent/seed/system-prompt.md`）。上游 HTTP API（`routes_templates` / `routes_resources`）、工作台在线试运行、回归测试及嵌入式聊天窗口等调用方均通过提交 `RunRequest` 驱动 `AgentRunner.run`：运行时首先按 `target` 捕获不可变资源快照并完成入参裁剪与防 ReDoS 正则检验，随后装载对应模板白名单内的 Skill/API 列表，并在单次会话中通过四种可配置的结构化输出模式引导模型交卷。

交卷出口由 `@agent.output_validator` 强制守卫：所有声明 `status="found"` 的字段须经 `EvidenceChecker.check()` 校验出处真实性；列表字段通过按 `(resultId, row)` 去重展平实现毫秒级逐行检验，并强制空列表 `value=[]` 附带 0 行查询证据。若未达 `agent_output_retries` 上限则触发 `ModelRetry` 提示修正；若达到上限或出现部分缺失则启动部分挽救与沿 `{"type": "field", "name": ...}` 依赖图的级联降级，最终联合 `render.field_render` 与 `domain.jinja_env.render_body` 输出带有 `SUCCESS`/`PARTIAL`/`FAILED` 状态、精确单据行号偏移 `evidenceTarget` 与全量审计轨迹的运行成果并异步写入 `RunStore`。

### 2.1 用户场景与测试

#### 用户故事 1（US1）— 单智能体统一编排、动态交卷 Schema 与线上模型缓存（优先级：P1）

- **用户旅程**：作为上游工单系统、工作台配置人员或嵌入式聊天后台，我向 `AgentRunner.run` 提交 `RunRequest`（含 `template_id`、`inputs`、`document` 与 `target`），期望系统能在锁定同一不可变资源快照并快速拦截非法入参后，仅暴露该模板授权的白名单 Skill/API，动态生成严格交卷结构并适配不同推理服务（`tool` / `native` / `json_object` / `prompted`）完成填写与交卷复用。
- **优先级理由**：单智能体规划管道与动态强类型交卷契约是支撑所有 33+ 套申告模板运转的骨架，是核心 MVP 底座。
- **独立测试**：注入离线脚本化模型 `ScriptedModel` 或 `httpx.MockTransport` 模拟 OpenAI 兼容端点，分别在 `tool`、`native`、`json_object` 和 `prompted` 四种模式下执行端到端试跑，验证入参校验拦截、`Report{id}` Schema 约束、白名单暴露隔离以及 `(rev, tpl.id, bundle.seq)` 模型缓存命中与淘汰。
- **关联需求**：`FR-001`、`FR-002`、`FR-003`、`FR-004`
- **验收场景**：
  1. **前提** 模板已发布至线上快照且配置任一合法 `agent_output_mode`（`tool`/`native`/`json_object`/`prompted`），**当** 上游携带含首尾空格的合法入参与单据调用 `AgentRunner.run`，**则** 入参自动 `.strip()` 并通过 `validate_inputs` 校验，提示词仅包含白名单 Skill/API 且剥离 `\n+原规则（Java）：` 对照注释，相同 `(rev, tpl.id, bundle.seq)` 连续执行时直接命中上限 128 的 LRU `_agent_cache` 并成功交卷。
  2. **前提** 调用方传入缺失必填项、不符合正则或引用已下线/不存在模板的 `RunRequest`，**当** 进入 `AgentRunner.run` 前置检查，**则** 系统在零大模型 Token 消耗前提下立即抛出 `InputValidationError` 或 `TemplateUnavailable`。
  3. **前提** 运行模式设为 `native`、`json_object` 或 `prompted`，**当** `build_model` 与 `_build_agent` 构造请求发往推理服务，**则** `native` 模式发送 `NativeOutput(..., strict=settings.agent_native_strict)` 且工具清单不含 `submit_report`；`json_object` 模式覆写模型能力仅发送 `response_format={"type": "json_object"}` 并把 Schema 注入消息；`prompted` 模式完全省略 `response_format` 并能解析带 Markdown 代码块包裹的 JSON 交卷。

#### 用户故事 2（US2）— `quote`/`input`/`derive` 强证据核验与列表零记录防线（优先级：P1）

- **用户旅程**：作为申告报告质检规则与平台安全防线守护者，我希望智能体提交的任何 `status="found"` 字段结论都经过 `EvidenceChecker.check()` 的确定性校验，确保 `quote` 原文真实可查、`quoteWhole` 整段一字不差、`input` 与非空入参一致、`derive` 遵循 `VALUE_TOOLS` 与真实依赖源，并严格区分“已查询确无记录（`value=[]`）”与“未查询或失败缺失（`not_found`）”。
- **优先级理由**：强证据门禁直接决定平台是否能够达到“零幻觉”工程红线，避免未核验内容误导用户或进入稽核台账。
- **独立测试**：构造含 `ApiResult`、`ToolCall` 与跨行多空白单据文本的 `Workspace`，直接调用 `EvidenceChecker.check()` 对篡改值、截断 `quoteWhole` 短信、伪造单据片段、引用失败接口/失败工具、引用 `load_skill`、悬空依赖 `not_found`、真假空列表提交及 50 行列表性能基准进行独立断言。
- **关联需求**：`FR-005`、`FR-006`
- **验收场景**：
  1. **前提** 模板包含 `quoteWhole=true` 的短信字段、跨行折行单据引用字段、入参字段与调用 `format_date(values=[...])` 的推导字段，**当** 提交短信完整一致、单据引用匹配 `DocumentIndex` 空白归一化原文、推导值命中批量输出任一元素时，**则** `EvidenceChecker.check()` 返回空错误列表并发射 `report_accepted` 事件。
  2. **前提** 模型对 `quoteWhole` 截去末尾字符、在标量字段填入 `list`/`dict`、将 `load_skill` 或 `ok=false` 接口/工具列为依据、或让 `derive` 字段在无其他真实支撑源下引用状态为 `not_found` 的前置字段，**当** 执行 `EvidenceChecker.check()`，**则** 校验器精确返回对应字段 `FieldIssue` 错因并阻断直接通过。
  3. **前提** 列表字段提交 `status="found"` 且 `value=[]`，**当** 证据中附带 `call_api(count=0)`、`query_result(total=0)`、`len(records)==0` 的成功 `api` 证据（`row` 省略或为 `0`）或存在性单据片段时，**则** 判定为合法空列表；反之若附带记录数大于 0 的接口、`load_skill`、非查询工具或负数 `row`，则拒绝并提示核查或提交 `not_found`。

#### 用户故事 3（US3）— `ModelRetry` 打回重填、超限挽救与依赖图级联降级（优先级：P2）

- **用户旅程**：作为报告运行器运维与稳定性负责人，我希望模型偶发局部校验错误时能先通过精准的字段级 `ModelRetry` 引导模型自纠重填；当超出 `agent_output_retries` 重试上限或漏填部分字段导致异常时，能对已合规字段做最大化保留挽救，并沿字段间依赖图把所有受影响或陷入环路的衍生字段彻底收敛降级。
- **优先级理由**：在复杂模板上偶发单字段失误不应拖垮整份报告，局部打回与确定性级联降级兼顾高可用与零幻觉边界。
- **独立测试**：构造首轮故意截断短信触发退回重填、持续违例触发重试耗尽、遗漏字段或存在 `C -> A <-> B` 环路与多级衍生链的脚本化模型，独立验证 `report_rejected`、`report_degraded` 与最终各字段状态收敛。
- **关联需求**：`FR-006`、`FR-007`
- **验收场景**：
  1. **前提** 模型首次交卷在单个 `quoteWhole` 字段截断内容，第二次交卷修正为完整原文，**当** `AgentRunner.run` 执行校验与重试，**则** 首轮记录 `validationRounds` 并发射 `report_rejected`，二轮校验通过发射 `report_accepted`，仅该字段 `retried=True` 且运行最终返回 `SUCCESS`。
  2. **前提** 模型在 `agent_output_retries` 耗尽后仍不合规，或 `prompted` 模式下漏填部分字段触发 `UnexpectedModelBehavior`，**当** 提取最后候选交卷并调用 `_salvage_partial_report`，**则** 合规字段保持 `status="found"`，缺失与违例字段降级为 `status="not_found"`、`value=None`、`validationFailed=True` 并发射 `report_degraded`。
  3. **前提** 存在 `C -> A <-> B` 环路、纯自引用 `甲 -> 甲` 或仅依赖已降级/自报 `not_found` 前置字段 `X` 的多级衍生链 `Y -> Z`，**当** 执行 `EvidenceChecker.check()` 或 `_cascade_degraded_fields`，**则** 环及环外指向节点全部被检出，`Y`、`Z` 沿依赖链不动点收敛降级为 `not_found`，而同时具备备用实源的回退字段保持 `found`。

#### 用户故事 4（US4）— 零撕裂在线热切、动态并发限流、轨迹事件流与证据溯源（优先级：P2）

- **用户旅程**：作为平台管理员与前端调试/展示端用户，我希望在线修改大模型地址、输出模式或并发限额时在途报告零中断、新请求即刻生效；并在执行过程中实时接收脱敏且有序的过程事件，最终在报告详情页点击任意证据标签定位到对应接口结果行或单据原文精确行号与字符偏移。
- **优先级理由**：支撑免重启热运维以及调试工作台/嵌入式聊天窗口的实时可观测与点击溯源闭环。
- **独立测试**：构造占满配额的并发协程在跨线程下调用 `reload_config` 与 `set_limit` 验证 `_DynamicLimiter` 门控与唤醒；构造跨行折行及多次匹配的原文验证 `DocumentIndex` 与 `_evidence_label`；验证 `asyncio.CancelledError` 先写入 `RunStore` 再原样透传。
- **关联需求**：`FR-008`、`FR-009`、`FR-010`
- **验收场景**：
  1. **前提** `_DynamicLimiter` 限额为 3 且已有 3 个协程在途运行，**当** 调用 `reload_config` 原子切换 `_RuntimeBundle` 并执行 `set_limit(1)`，**则** 在途 3 个协程完整沿用原有 `_RuntimeBundle` 顺利结束，第 4 个协程排队等待直至在途数降至 0 后方获准进入；跨线程上调上限时立即唤醒队列。
  2. **前提** 运行通过 `queue_listener` 订阅过程事件，**当** 智能体发出模型请求、`TextPart` 思考文本、工具调用、交卷核验或遭遇 `asyncio.CancelledError` 取消时，**则** `EventSink` 按单调 `seq`（且保护 `seq`/`type`/`atMs`/`round` 不被业务键覆写）推送对应事件，取消时先完整异步落盘运行详情（`error="运行已取消"`）再原样重抛。
  3. **前提** 交卷通过后进入 `_finish` 与 `render_body` 渲染阶段，**当** 整理字段输出状态与溯源目标时，**则** 仅实际在正文输出或迭代且为 `not_found`（非 `whenMissing="value"`）的可见字段及未定义变量计入 `missingShown` 触发 `PARTIAL`；所有 `not_found` 字段清空残留 `evidence`；`document` 证据经 `DocumentIndex` 产出 `line`/`endLine`/`offset`/`endOffset` 与多匹配 `matches`，`field` 证据递归解析指向底层实源的 `evidenceTarget`。

### 2.2 成功标准

- **SC-001**：强证据零幻觉放行率 100% —— 所有进入 `SUCCESS` 或 `PARTIAL` 终稿且处于 `status="found"` 的标量与列表行 100% 通过 `EvidenceChecker` 确定性核验；截断 `quoteWhole`、引用 `load_skill`、标量传容器、自引用/环路及无实源衍生字段在耗尽重试后均强制降级为 `not_found`。
- **SC-002**：列表高频核验性能达标 —— 针对 50 行 × 4 列含 150 条重复 `api` 证据引用的典型列表字段（`tests/test_review_fixes_runtime.py::test_list_field_quote_evidence_dedup_and_perf`），经过 `(resultId, row)` 去重与预构建索引后的 `EvidenceChecker.check()` 5 次中位核验耗时稳定低于 5.0 ms。
- **SC-003**：四种结构化输出模式全通过 —— `tool`、`native`（`strict=True` 且自动规避 `oneOf`）、`json_object` 与 `prompted`（含 Markdown 代码块包裹与缺字段部分挽救）在模拟端到端试跑测试中 100% 通过。
- **SC-004**：在线热重载与动态并发安全 —— 跨线程调用 `reload_config` 切换 `_RuntimeBundle` 与动态调整 `agent_max_concurrent_runs` 时，在途请求隔离不撕裂、下调不超发、上调即唤醒；`online` 运行 `(rev, tpl.id, bundle.seq)` LRU 模型缓存（上限 128 槽）在同版本同配置连续请求下命中率 100%。
- **SC-005**：轨迹可观测与溯源完整性 —— 运行过程完整留存带顺序保护的 `events`、`validationRounds`、`usage`、`messages` 与三级状态判定，多匹配与跨行折行单据 100% 由 `DocumentIndex` 精确还原行列偏移定位，全部专项及全量后端套件（`uv run pytest -q` `196 passed in 51.41s`）与静态检查（`uvx ruff@0.11.0 check src tests`）零失败零告警。

### 2.3 假设

- **上下游职责边界**：领域模型解析、Jinja2 沙箱渲染器（`TrackedValue`/`TrackedList`）及基础规则校验由 `RA-001`（`domain`）提供；只读快照 `ReleaseStore`、草稿叠加视图 `ResourceService` 与异步落盘 `RunStore` 由 `RA-002`（`store`）提供；12 个确定性平台工具实体与外部网关连接器由 `RA-004`（`tools`/`gateway`）提供；HTTP REST/SSE 路由、鉴权与嵌入式聊天上层调度由 `RA-005` / `RA-007` 承担。
- **单进程并发假定**：`_DynamicLimiter` 等待队列、`_agent_cache`、`_RuntimeBundle` 与 `Workspace` 内存态均依托单进程 `asyncio` 事件循环协作，生产 Uvicorn 必须严格以 `workers=1` 运行。
- **推理服务协议假定**：大模型推理服务提供 OpenAI 兼容 Chat Completions 接口，可根据厂商特性通过 `Settings` 调整 `agent_output_mode`、`llm_strict_tools`、`llm_tool_choice_required` 等能力覆写项。
- **工时核算口径**：本子规格 `33.0 人天` 涵盖 `runtime/` 8 个核心代码文件（共 2,260 行源码）、`system-prompt.md`（23 行）、5 份专项测试与脚本化模型桩文件（2,254 行）的架构设计、实现交付、防幻觉审校加固及回归验收全周期投入。

---

## 3. 术语与概念定义 【核心，如有新术语】

> 通用平台术语参见 `wiki/reference/glossary.md`；本表仅收录本子规格核心运行与核验专有术语。

| 术语 | 英文/标识 | 定义 | 备注 |
| --- | --- | --- | --- |
| 动态交卷模型 | `Report{id}` / `build_report_model` | 运行时依据 `template.yaml` 字段与入参动态创建的 `extra="forbid"` Pydantic 模型树，将枚举、列表列结构与允许证据源类型下沉为 JSON Schema | 按 `(rev, tpl.id, bundle.seq)` 在 `online` 模式下 LRU 缓存 |
| 证据校验器 | `EvidenceChecker` | 运行于 `@agent.output_validator` 的确定性核验组件，逐条检查 `found` 字段及列表行的出处真实性、空白折叠等价、空列表 0 行证明与图循环依赖 | 核心防幻觉门禁 |
| 单据定位索引 | `DocumentIndex` | 绑定单据原文的惰性字符索引，缓存行首偏移 `line_starts`、折叠映射 `_norm_doc`/`_doc_map` 及最多 512 条 `locate()` 结果 | 通过 `Workspace._doc_index` 在单次运行复用 |
| 不动点级联降级 | `_cascade_degraded_fields` / `_compute_supported_found_fields` | 沿 `{"type": "field", "name": ...}` 依赖图迭代收敛的计算过程，自动剔除自引用、循环依赖及无备用实源而悬空依赖 `not_found` 字段的衍生结论 | 共享 `has_supporting_real_source` 判定 |
| 运行配置快照 | `_RuntimeBundle` | 不可变（`frozen=True`）封装 `settings`、`model`、`model_settings`、`tools` 与全局自增 `seq` 的容器，使运行期热更新零撕裂 | 供 `AgentRunner.reload_config` 原子替换 |
| 动态并发限流器 | `_DynamicLimiter` | 取代标准 `asyncio.Semaphore` 的进程内并发控制门禁，支持跨线程调用 `set_limit` 上调唤醒、下调不超发并清理失效事件循环 `Future` | 保障 `agent_max_concurrent_runs` 约束 |

---

## 4. 用户角色 【核心】

| 角色 | 类型 | 本需求中可执行的操作与数据范围 | 权限/安全约束 |
| --- | --- | --- | --- |
| 上游工单系统 / 工作台 / 聊天窗口 | 内部/上游调用方 | 构造 `RunRequest` 发起报告生成或试运行，订阅 `EventSink`（`queue_listener`）过程事件流 | 本模块不直接暴露 HTTP 鉴权；由 `api/` 路由鉴权并剥离伪造操作人后传入经清洗的 `RunRequest` |
| 单智能体（大模型） | AI 运行参与者 | 在 `RunDeps` 约束下阅读提示词与白名单资源、调用 12 个平台工具并在最后按指定模式提交 `Report{id}` | 工具与 Skill 严格受 `allowed_skills`/`allowed_apis` 约束；交卷数据必须经 `EvidenceChecker` 强制校验 |
| 平台管理员（热重载触发者） | 人工运维角色（间接） | 通过运行期热配置服务触发 `AgentRunner.reload_config` 切换模型、重试次数与并发配额 | `llm_api_key` 以 `SecretStr` 承载，禁止出现在事件、日志与运行摘要中 |

---

## 5. 功能需求 【核心】

### 5.1 快照锁定、入参校验与动态交卷模型构造

#### FR-001 快照锁定、模板可用性核验与入参防 ReDoS 快速失败

- **来源**：`src/report_agent/runtime/runner.py`、`src/report_agent/runtime/deps.py`
- **描述**：在启动智能体前一次性锁定不可变资源快照并完成模板状态与入参格式校验，前置阻断无效请求。
- **关联用户故事/成功标准**：`US1` / `SC-004`
- **业务规则**：
  1. 当 `req.target == "online"` 时，优先调用 `releases.try_live_snapshot()`，缺失时通过 `await asyncio.to_thread(self._capture, req.target)` 在线程池读取；当 `req.target == "draft"` 时获取 `live_rev() + "+草稿"` 与 `service.overlay()`。
  2. 模板不存在或 `target == "online"` 且 `tpl.offline` 为真时，立即抛出 `TemplateUnavailable`。
  3. 对 `req.inputs` 所有键值执行字符串化及 `.strip()` 去首尾空白；随后 `validate_inputs` 逐项校验必填入参（非空）及 `inp.pattern`（经 `safe_regex_fullmatch` 执行防 ReDoS 全串匹配）；任一错误立即抛出 `InputValidationError` 而不触发大模型请求。
  4. 构造不可变运行期间依赖上下文 `RunDeps`，固化 `run_id`、`rev`、`resources`、`template`、`inputs`、`document`、`allowed_skills`、`allowed_apis`、`Workspace`、`EventSink`、`GatewayClient` 与 `Settings` 快照。
- **输入/触发**：调用 `AgentRunner.run(req, listener)`。
- **输出/结果**：合法请求生成固定 `RunDeps`；不合法请求抛出 `TemplateUnavailable` 或 `InputValidationError`。
- **验收标准**：
  - AC-1：传入缺失必填项、正则不匹配或引用已下线模板的请求时，在零次模型请求前抛出 `InputValidationError` 或 `TemplateUnavailable`。
  - AC-2：传入含首尾空格的合法入参时，自动去除两端空白后通过校验并在 `RunDeps.inputs` 中持久化规范化后的值。

#### FR-002 动态构造严格交卷模型 `Report{id}`

- **来源**：`src/report_agent/runtime/output_model.py`
- **描述**：基于 `Template` 的入参与字段定义，运行时动态拼装 Pydantic v2 交卷模型 `Report{suffix}`（`extra="forbid"`）。
- **关联用户故事/成功标准**：`US1` / `SC-001`, `SC-003`
- **业务规则**：
  1. 对 `d.inputs` 与 `d.fields` 去重保序构造专属的 `InputEvidence{suffix}` 与 `FieldEvidence{suffix}`（均继承启用 `extra="forbid"` 的 `_Strict`）；`ApiEvidence.row` 通过 `@field_validator("row", mode="before")` 显式拒绝布尔值 `bool`。
  2. 根据 `FieldDef.evidence` 收窄允许的证据联合体（`discriminator="type"`）：标量 `quote` 仅限 `[ApiEvidence, DocumentEvidence]`；列表 `quote` 额外放行 `ToolEvidence` 用于 0 条结果查询证明；`input` 仅限 `InputEvidence`（无入参定义时回退 `[DocumentEvidence]`）；`derive` 开放 `[ApiEvidence, DocumentEvidence, InputEvidence?, ToolEvidence, FieldEvidence?]`。
  3. 对 `type="list"` 字段调用 `_build_row_model` 生成 `Row{suffix}_{idx}`，以 `c0`, `c1`... 作为内部属性名配合 `alias=col.name` 规避中文列名与 `BaseModel` 保留属性冲突，枚举列限定 `Literal` 可选值且所有列均为必填；`status="found"` 时 `value` 接受 `list[Row]`（含合法空数组 `[]`）。
  4. 标量枚举字段限定 `Literal[values]`，所有字段模型 `FieldAnswer{suffix}_{n}` 描述写入 `$defs` 模型 docstring 避免 `OpenAI` strict 转换器产生冗余 `anyOf`。
  5. 对无字段（`fields: []`）或重复字段的草稿模板安全兜底构建合法模型，不抛构建异常；提供 `report_to_dict(report)` 以 `by_alias=True, mode="json"` 导出标准字典。
- **输入/触发**：调用 `build_report_model(template)`。
- **输出/结果**：模板专属且可序列化为严格 JSON Schema 的 Pydantic `BaseModel` 类。
- **验收标准**：
  - AC-1：生成模型拒绝未声明字段、列表行缺列/多余列、越界枚举值与布尔型 `ApiEvidence.row`。
  - AC-2：零字段模板或存在重复 `inputs.key` 时 `build_report_model` 正常返回空/去重字段的合法 `Report{suffix}`。

#### FR-003 四种结构化输出模式与 128 槽 LRU 模型缓存

- **来源**：`src/report_agent/runtime/model_factory.py`、`src/report_agent/runtime/runner.py`
- **描述**：构建 OpenAI 兼容模型客户端并依据配置适配四类结构化交卷模式，同时在 `online` 运行中缓存编译完成的 `(report_model, agent)`。
- **关联用户故事/成功标准**：`US1` / `SC-003`, `SC-004`
- **业务规则**：
  1. `build_model(settings)` 使用 `SecretStr` 读取 `llm_api_key`（为空时使用 `"EMPTY"` 占位），配置 `llm_base_url`、`llm_timeout_s` 与 `llm_http_retries`；按 `agent_output_mode` 覆写模型 `profile`：`json_object` 置 `supports_json_object_output=True, supports_json_schema_output=False`；`prompted` 置双 `False`；并按需覆写 `llm_strict_tools` 与 `llm_tool_choice_required`。
  2. `_build_agent` 根据 `agent_output_mode` 选择输出通道：`tool` 使用 `ToolOutput`；`native` 使用 `NativeOutput(..., strict=settings.agent_native_strict)`；`json_object` 与 `prompted` 使用 `PromptedOutput`。
  3. 当 `req.target == "online"` 时，使用 `(rev, tpl.id, bundle.seq)` 作为 LRU 缓存键在 `self._agent_cache`（上限 `_MAX_AGENT_CACHE = 128`）中复用 `(report_model, agent)` 并执行 `move_to_end`；当 `target == "draft"` 时每次现建，不污染线上缓存。
- **输入/触发**：`build_model`、`build_model_settings` 与 `AgentRunner.run`。
- **输出/结果**：配置正确的 `OpenAIChatModel` / `Agent` 实例与热更新隔离的缓存复用。
- **验收标准**：
  - AC-1：`native` 模式请求体包含 `response_format.type == "json_schema"` 且 `strict=True`、不含 `oneOf` 且工具不含 `submit_report`；`json_object` 发送 `{"type": "json_object"}`；`prompted` 不含 `response_format`。
  - AC-2：同版本同配置的连续 `online` 运行命中 `_agent_cache`；当版本发布切换 `rev` 或热重载递增 `bundle.seq` 时立即自动隔离重编。

#### FR-004 白名单任务提示词组装与历史 Java 对照注释剥离

- **来源**：`src/report_agent/runtime/prompt.py`、`src/report_agent/seed/system-prompt.md`
- **描述**：将全局通用填报纪律与按单次请求白名单过滤的动态任务说明注入智能体 `instructions`。
- **关联用户故事/成功标准**：`US1` / `SC-001`
- **业务规则**：
  1. 全局系统提示词 `system-prompt.md` 规定单智能体工作流程、单据归属判定、空列表 `found: []` vs `not_found` 规则与“不把 `load_skill` / `not_found` 前置字段 / 空入参作为依据”等平台铁律。
  2. `build_task_instructions(deps)` 仅列出 `deps.allowed_skills` 中存在且合法的 Skill 摘要和 `deps.allowed_apis` 中允许调用的接口名称及标题。
  3. 声明式入参展示中，全空白描述自动跳过空括号；未在 `tpl.inputs` 中声明但非空的附加传入参数一并注入参考列表供模型阅读。
  4. 字段说明通过 `_JAVA_RULE_NOTE_RE = re.compile(r"\n+原规则（Java）：")` 剥离历史对照备注，避免无关历史 Groovy 描述干扰推理。
- **输入/触发**：`Agent` 每次模型轮次动态调用 `instructions`。
- **输出/结果**：隔离越权资源、去除噪音的任务提示词文本。
- **验收标准**：
  - AC-1：模板未授权的 Skill 与接口绝不出现在提示词文本中。
  - AC-2：模板字段含 `原规则（Java）：...` 或全空白 `description` 时，生成提示词已剔除对照段落且无冗余 `（）`。

### 5.2 强证据核验与图依赖防幻觉引擎

#### FR-005 确定性 `EvidenceChecker` 与高速列表核验

- **来源**：`src/report_agent/runtime/evidence.py`
- **描述**：在交卷放行前对全部 `status="found"` 字段实施基于原始数据、单据文本与工作区工具账本的确定性来源校验。
- **关联用户故事/成功标准**：`US2` / `SC-001`, `SC-002`
- **业务规则**：
  1. **基础容器与状态防御**：标量字段禁止填入 `list`/`dict` 或全空白值；枚举字段/列严格校验取值范围；严禁引用 `ok=False` 的接口/工具、严禁引用 `load_skill` 调用、严禁引用未传入或空白的 `input`。
  2. **标量等价与 `quoteWhole` 约束**：`_values_equivalent` 支持非前导零 `Decimal` 数值等价（如 `129` 与 `"129.0"`，但严格区分 `"0000"` 与 `"0"`）、布尔值大小写兼容且严格隔离 `False`/`0` 与 `True`/`1`、零宽字符剔除与空白折叠；`quoteWhole=true` 要求 `_normalize_line_endings` 后整条/整段一字不差。
  3. **单据原文定位索引 `DocumentIndex`**：绑定至 `Workspace._doc_index` 惰性初始化并缓存 `lines`、`line_starts`、空白折叠映射 `_norm_doc`/`_doc_map` 及最多 512 项 `locate()` 偏移结果，兼容跨行折行、全角空格与 NBSP 片段检索。
  4. **工具值核对**：`VALUE_TOOLS = {"format_date"}`，若 `derive` 字段引用了成功的 `format_date` 调用，则其值必须等价命中单值 `output["value"]` 或批量列表 `output["values"]` 中的至少一项。
  5. **列表结构、高速核验与空列表防线**：非空列表逐行校验必填列与非全空；对 `evidence="quote"` 的非空列表按 `(resultId, row)` 去重展开，并在循环外一次性构建原文全等集合、`"\x00"` 拼接检索串、折叠集合及懒初始化 `Decimal` 集合，覆盖每格非空非枚举文本值；空列表 `value=[]` 由 `_check_empty_list_evidence` 核验至少存在一条 0 行查询证明（`call_api(count=0)` / `query_result(total=0)` / `len(res.records)==0` 且 `row` 为 `None` 或 `0` / 存在性 `document` 片段）。
- **输入/触发**：`EvidenceChecker(template, inputs, document, workspace).check(report)`。
- **输出/结果**：返回有序 `list[FieldIssue]`；空列表代表核验通过。
- **验收标准**：
  - AC-1：任意截断 `quoteWhole`、容器塞入标量、引用 `load_skill`/失败工具/空入参、伪造单据文本或非法空列表均产出明确指向问题字段的 `FieldIssue`。
  - AC-2：50 行 × 4 列含 150 条重复 `api` 证据的列表核验在 `test_list_field_quote_evidence_dedup_and_perf` 中 5 次中位耗时 `< 5.0 ms`。

#### FR-006 可达依赖环检测与共享实源不动点计算

- **来源**：`src/report_agent/runtime/evidence.py`、`src/report_agent/runtime/runner.py`
- **描述**：拦截所有自引用、字段间循环依赖以及无真实支撑源而悬空依赖 `not_found` 前置字段的衍生结论。
- **关联用户故事/成功标准**：`US2`, `US3` / `SC-001`
- **业务规则**：
  1. `has_supporting_real_source` 作为公共判定原语同时服务 `EvidenceChecker` 与 `_cascade_degraded_fields`，判断证据列表是否存在除自身（`ref_name != self_field`）外至少一条真实有效 `api`/`document`/非空 `input`/合法 `tool`（空列表场景）/有效 `found` 前置 `field`。
  2. `_compute_supported_found_fields` 通过不动点迭代不断剔除存在自引用或仅引用 `not_found`/已被剔除前置字段的 `found` 节点；若某字段同时具备有效备用实源（如 `[field(X:not_found), api(r1)]`）则予以保留。
  3. `_find_reachable_cycle` 从所有带 `field` 引用的节点出发探测可达环路，精准检出直接环、自环及环外指向环的节点（如 `C -> A <-> B`）；跨起点复用无环剪枝缓存 `safe_nodes`，且绝不将含自环节点（`first == start`）误加入 `safe_nodes`。
- **输入/触发**：`EvidenceChecker.check` 与 `_cascade_degraded_fields`。
- **输出/结果**：输出循环依赖 `FieldIssue` 路径字符串及稳定的有效支撑字段集合 `supported_fields`。
- **验收标准**：
  - AC-1：`C -> A <-> B` 或 `甲 -> 甲` 在前、`乙 -> 甲` 在后的场景均被检出循环依赖且不允许 `safe_nodes` 错放。
  - AC-2：无备用实源的衍生链 `X(not_found) -> Y -> Z` 自动收敛降级，有有效备用实源的回退字段保持 `found`。

### 5.3 打回自纠、部分挽救与级联降级

#### FR-007 `ModelRetry` 打回重填、候选挽救与级联降级

- **来源**：`src/report_agent/runtime/runner.py`
- **描述**：当交卷校验不通过时先引导模型仅重填问题字段，重试耗尽或输出结构异常时最大化挽救有效字段并同步清理受影响下游链。
- **关联用户故事/成功标准**：`US3` / `SC-001`, `SC-003`
- **业务规则**：
  1. 在 `@agent.output_validator` 内，若存在 `issues` 且 `ctx.retry < ctx.max_retries`，将本轮 `issue_dicts` 追加至 `workspace.validation_rounds`，发射 `report_rejected` 事件并抛出 `ModelRetry(format_issues(issues))`。
  2. 若校验在最后一次重试（`ctx.retry >= ctx.max_retries`）仍未通过，调用 `_degrade_failed_fields` 将违例字段重置为 `{"status": "not_found", "value": None, "evidence": [], "reasoning": ...}`，随后运行 `_cascade_degraded_fields` 沿引用链不动点级联降级，记录 `validation_rounds` 并发射 `report_degraded` 后通过 `type(out).model_validate(report)` 放行部分结果。
  3. 当模型运行抛出 `UnexpectedModelBehavior`（如结构化校验/缺字段重试耗尽）时，调用 `_extract_candidate_report` 从最近 `ModelResponse` 的 `ToolCallPart(submit_report)` 或 `TextPart`（支持 `_extract_json_dict` 提取带 markdown 代码块或前后文夹带的 JSON 对象）捞取候选字典；若命中则交 `_salvage_partial_report` 逐字段按模型反序列化（仅非列表字段将基础数值/布尔标量安全转文本，数组/对象交校验器拒收），再依次执行 `EvidenceChecker.check` 与 `_cascade_degraded_fields`。
- **输入/触发**：`@agent.output_validator` 校验失败或 `AgentRunner.run` 捕获 `UnexpectedModelBehavior`。
- **输出/结果**：返回合规字段保留、不合格与受级联影响字段降级为 `not_found` 的完整交卷字典及事件记录。
- **验收标准**：
  - AC-1：首轮截断短信触发 `report_rejected` 后二轮重填成功，`retried=True` 且运行状态为 `SUCCESS`。
  - AC-2：`prompted` 模式遗漏字段或持续校验失败触发挽救后，合规字段保留 `found`，缺失及级联字段标为 `not_found` 且 `validationFailed=True`。

### 5.4 热更新并发控制、过程轨迹流与渲染溯源

#### FR-008 零撕裂 `_RuntimeBundle` 热重载与跨线程 `_DynamicLimiter`

- **来源**：`src/report_agent/runtime/runner.py`
- **描述**：允许运行期无停机热更新配置并安全调节全局并发限额。
- **关联用户故事/成功标准**：`US4` / `SC-004`
- **业务规则**：
  1. `AgentRunner` 将 `settings`、`model`、`model_settings` 与 `tools` 封装为冻结数据类 `_RuntimeBundle`（绑定全局唯一递增 `seq`）；单次 `run` 在进入执行前捕获局部 `bundle` 引用，确保正在执行中的运行期完全不受后续变更撕裂。
  2. `reload_config(settings, rebuild_model=True)` 原子构建新的 `_RuntimeBundle`（刷新 `model_settings`、`tools` 与可选 `model`）并调用 `self._sem.set_limit(settings.agent_max_concurrent_runs)`。
  3. `_DynamicLimiter` 维护 `_inflight`、`_limit` 与等待队列 `_waiters`：下调限额时允许已入场协程自然退出而绝不放行超出新限额的新协程；上调限额时支持跨线程通过 `loop.call_soon_threadsafe(self._wake_waiters)` 安全唤醒等待协程，并在 `_prune_waiters` 中清理已完成或已关闭事件循环的失效 `Future`；排队中途遭遇取消时正确移除队列占位或归还名额并顺延唤醒。
- **输入/触发**：调用 `AgentRunner.reload_config(...)` 或并发执行 `AgentRunner.run`。
- **输出/结果**：热更新后新请求即刻切入新配置与缓存槽，并发峰值始终受控。
- **验收标准**：
  - AC-1：占满限额 3 时下调至 1，在途 3 协程正常收尾且新请求阻塞至在途归零；跨线程升额时阻塞协程立即唤醒。
  - AC-2：队列等待协程在已关闭循环场景或中途取消下不会导致名额永久泄漏或抛出循环已关闭未捕获异常。

#### FR-009 全链路过程轨迹事件与异常取消安全落盘

- **来源**：`src/report_agent/runtime/workspace.py`、`src/report_agent/runtime/runner.py`
- **描述**：提供抗覆盖、跨线程安全的过程事件投递管线，确保超时、超限、模型故障与手动取消均可追溯落盘。
- **关联用户故事/成功标准**：`US4` / `SC-005`
- **业务规则**：
  1. `EventSink` 记录单调递增 `seq`、单调毫秒耗时 `atMs` 与当前推理轮次 `round`；`ProcessEvent.to_dict()` 按 `{**self.data, "seq": self.seq, "type": self.type, "atMs": self.at_ms, "round": self.round}` 组装，防止业务载荷篡改结构元字段；监听回调抛出异常时静默保护不阻断主运行。
  2. `queue_listener(queue)` 在创建时捕获当前运行循环 `loop`：同循环直投 `put_nowait`，跨线程调用且循环活跃时走 `loop.call_soon_threadsafe`，循环已关闭或无运行循环时兜底 `put_nowait` 不报错。
  3. `AgentRunner.run` 在 `async with rt_sem:` 与 `asyncio.timeout(agent_run_timeout_s)` 下执行 `agent.iter(...)`（绑定 `UsageLimits(request_limit, tool_calls_limit)`），按节点发射 `run_started`、`model_request`、`model_text`（最多前 2000 字）以及失败时的 `run_failed`。
  4. 外层精确捕获 `TimeoutError`、`UsageLimitExceeded`、`UnexpectedModelBehavior`、`ModelAPIError`、`AgentRunError`、`asyncio.CancelledError`（记 `error="运行已取消"`）及兜底异常，先提取 `usage` 与 `messages` 经 `_finish` 和 `runs.submit` 异步写盘后，若为 `cancelled_exc` 再原样 `raise cancelled_exc` 保留原始取消信息。
- **输入/触发**：`AgentRunner.run` 执行全过程与任意异常/取消信号。
- **输出/结果**：有序 SSE 过程事件与持久化于 `RunStore` 的完整运行摘要与详单。
- **验收标准**：
  - AC-1：`ProcessEvent` 载荷即使包含 `"seq": 999` 或 `"type": "hack"` 也不会覆盖真实事件序号与类型。
  - AC-2：外部取消运行任务时，`RunStore` 正常收到 `status="FAILED"`、`error="运行已取消"` 与已消耗 `usage` 记录，同时原 `CancelledError` 实例及说明消息完整向上抛出。

#### FR-010 统一正文字段渲染、三级状态判定与精确证据溯源

- **来源**：`src/report_agent/runtime/runner.py`、`src/report_agent/runtime/evidence.py`
- **描述**：整合 `field_render` 与 Jinja2 沙箱计算报告正文、可见缺失状态以及面向前端点击高亮的溯源定位指针。
- **关联用户故事/成功标准**：`US4` / `SC-005`
- **业务规则**：
  1. `_finish` 对模板所有字段依次调用 `render.field_render(f, ans)` 构建上下文（含 `TrackedValue`/`TrackedList`）；对任意 `not_found` 字段（含降级或自报缺失）强制清空其 `evidence` 为 `[]`，防止伪造或残留证据外流。
  2. 调用 `domain.jinja_env.render_body(tpl.body, context)` 输出正文与实际展示字段集合 `used`；若正文渲染异常记入 `render_error`。
  3. 计算 `missingShown`：包含所有处于 `used` 中且 `visible=True`、`status=="not_found"`、`whenMissing != "value"` 的字段，以及 `used` 中未定义于模板的变量名；判定规则为：`error or render_error` → `FAILED`，`missingShown` 非空 → `PARTIAL`，其余 → `SUCCESS`。
  4. `_evidence_label` 为前端生成可读 `evidenceLabel` 与结构化 `evidenceTarget`：`api` 指向 `{tab:"api", resultId, row, column}`；`document` 通过 `locate_quote_in_document` 返回精确 `line`/`endLine`/`offset`/`endOffset` 及多匹配时的 `matchCount`/`matches`（并利用 `_value_hint` 消歧）；`input`/`tool` 指向 `input` 页签；`field` 带环路防重递归解析指向底层真实源头。
- **输入/触发**：`AgentRunner._finish` 完成阶段。
- **输出/结果**：标准化运行输出字典（`status`、`report`、`fields`、`missingShown`、`apiResults`、`toolCalls`、`validationRounds`、`events`、`usage`）。
- **验收标准**：
  - AC-1：仅在未命中的 `{% if %}` 分支缺失的可见字段不计入 `missingShown`，整次运行维持 `SUCCESS`；列表字段 `status="found", value=[]` 时即使被 `{% for %}` 迭代仍判定 `SUCCESS`。
  - AC-2：`not_found` 字段即使原始模型响应附带了 `evidence` 也会被强制归空 `[]`；重复出现于单据多处的引用片段输出全部 `matches` 偏移列表。

---

## 6. 非功能需求 【补充】

| 类型 | 编号 | 说明 | 验收方式 |
| --- | --- | --- | --- |
| 防幻觉与零业务硬编码 | `NFR-001`（宪章原则 I, II） | `src/report_agent/runtime/` 禁止硬编码任何特定模板 ID、短信文本规则或接口契约细节；交卷模型全部设 `extra="forbid"`，禁止将大模型未核验推断输出为 `found` | 源码审阅与跨模板隔离回归测试 `tests/test_agent_runtime.py` |
| 单进程并发与原子热切 | `NFR-002`（宪章原则 III） | `_DynamicLimiter`、`_agent_cache`（128 槽 LRU）、`_RuntimeBundle` 与 `Workspace` 按单进程 `workers=1` 内存模型设计；`reload_config` 必须保证在途请求隔离且并发度不越界 | `tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py` 与 `tests/test_runtime_config_hot_reload.py` |
| 高效核验与资源界限 | `NFR-003`（宪章原则 V） | 50 行 × 4 列含 150 条 `api` 证据的列表核验中位耗时 `< 5.0 ms`；`DocumentIndex` 单次惰性扫描配合最多 512 项定位缓存；`model_text` 单事件截断至 2000 字防内存膨胀 | `tests/test_review_fixes_runtime.py::test_list_field_quote_evidence_dedup_and_perf` |
| 安全与零凭据硬编码 | `NFR-004`（宪章原则 VI） | `llm_api_key` 经 `SecretStr` 读取，禁止在日志、过程事件、`RunDeps` 摘要或测试中出现真实生产密钥；入参正则检验统一走 `safe_regex_fullmatch` 防 ReDoS | 代码静态审计、`ruff` 与离线桩测试 |
| 过程事件与异常可观测性 | `NFR-005`（宪章原则 VII） | 全过程按单调序号记录 `run_started`/`model_request`/`model_text`/`tool`/`report_rejected`/`report_accepted`/`report_degraded`/`run_failed`，任何取消或异常必先落盘 `RunStore` | `tests/test_review_runtime.py` 与 `tests/test_agent_runtime.py` |
| 前端与分包隔离边界 | `NFR-006`（宪章原则 VIII） | 本需求不涉及前端代码与 `embed.html` 分包改造，仅向下游接口与前端溯源面板输出稳定标准字段格式（`evidenceLabel`/`evidenceTarget`） | 核对改动目录范围及 `git status` |

---

## 7. 数据与存储需求 【补充】

> 本子规格运行期核心中间态全在内存管理，不直接向磁盘同步写文件，运行结束统一异步提交 `RunStore`（属于 `RA-002`）归档。

| 数据对象/存储位置 | 变更类型 | 关键字段与口径 | 一致性/留存策略 | 关联需求 |
| --- | --- | --- | --- | --- |
| `Workspace`（进程单次运行内存） | 新增/使用 | `results`（`r1..`）、`tool_calls`（`t1..`）、`loaded_skills`、`validation_rounds`、`_doc_index`、`_idempotent_cache`/`_idempotent_inflight` | 绑定单次 `AgentRunner.run` 生命周期，随运行结束释放 | `FR-005`, `FR-009` |
| `AgentRunner._agent_cache`（进程内存） | 新增/使用 | `OrderedDict[(rev, tpl.id, bundle.seq) -> (report_model, agent)]` | 仅限 `target="online"`；最大容量 128 槽 LRU 淘汰 | `FR-003`, `FR-008` |
| `RunStore` 落盘记录（`DATA_DIR/runs/YYYY/MM/DD/`） | 只写调用 | `RunSummary`（`index.jsonl`）+ 详单 `<runId>.json`（含 `messages`、`events`、`fields`、`validationRounds`、`usage`） | 通过 `self.runs.submit(summary, detail)` 异步排队写入，保留策略受 `RUNS_KEEP_DAYS` 控制 | `FR-009`, `FR-010` |
| `ReleaseStore` / `ResourceService`（只读快照） | 只读 | `rev`、`ResourceSet`（含 `system_prompt`、`templates`、`skills`、`apis`） | 请求入口捕获一次并在整次运行只读锁定 | `FR-001` |

---

## 8. 外部接口与集成 【补充】

| 接口/系统 | 方向 | 交互内容 | 是否新增 | 关联需求 | 备注 |
| --- | --- | --- | --- | --- | --- |
| OpenAI 兼容推理服务（`AsyncOpenAI`） | 出站 | 发送 `instructions`、工具列表、`response_format` 与 `messages`，接收工具调用与结构化交卷 | 是（本需求内建客户端适配） | `FR-003`, `FR-007` | 由 `model_factory.py` 构建，单测用 `FunctionModel` / `MockTransport` |
| 平台内部调用方（`api/`、`chat/`、工作台） | 入站（Python API） | 调用 `AgentRunner.run(RunRequest, listener)` 与 `AgentRunner.reload_config(settings)` | 否（复用既有系统内部接口） | `FR-001`, `FR-008`, `FR-009` | HTTP 外部契约归属 `RA-005` / `RA-007` |
| 12 项平台工具与外部网关（`RA-004`） | 内部协同 | `AgentRunner` 通过 `build_tools` 与 `RunDeps.gateway` 协同工具调用并共享 `Workspace` | 否（工具定义在 `RA-004`） | `FR-005`, `FR-009` | 工具记录统一写入 `Workspace.tool_calls` 与 `results` |

### 8.1 出站网关与模型接口契约摘要（涉及时填写）

| 接口/工具 | 调用方向 | 协议与端点 | 路由/识别字段 | 成功判定 | 关键失败与降级策略 |
| --- | --- | --- | --- | --- | --- |
| OpenAI 兼容大模型 API | 平台 `model_factory` → `{LLM_BASE_URL}` | HTTP JSON（OpenAI Chat Completions）；支持 `ToolOutput` / `NativeOutput` / `PromptedOutput` | `llm_model` + `Authorization: Bearer <llm_api_key>` | 模型按契约输出通过 `@agent.output_validator` 核验（或经重试修正） | HTTP 层 `llm_http_retries` 重试；校验未过 `ModelRetry` 打回；超时/超限/模型报错转 `FAILED` 或 `_salvage_partial_report` 部分挽救 |

### 8.2 三类独立交付物涉及情况

| 独立文档 | 涉及情况 | 判断依据与范围摘要 | 确认来源/日期及关联需求 |
| --- | --- | --- | --- |
| `接口文档.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求只实现进程内 `AgentRunner` 调度与证据核验引擎，不新增或变更对外 HTTP/SSE/`postMessage` 接口契约（对外契约存于 `docs/` 且归属 `RA-005`/`RA-007`） | 归档拆分确认 / 2026-11-16；`FR-001`~`FR-010` |
| `资源迁移与Seed清单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求仅包含 1 份平台通用 `src/report_agent/seed/system-prompt.md`，不涉及批量新增或重构 33 套业务模板、`skills/` 或 `tools/java_migration/` 规则（归属 `RA-008`） | 归档拆分确认 / 2026-11-16；`FR-004` |
| `部署与配置变更单.md` | 不涉及（本次归档拆分仅生成标准 SDD 三件套，实际资产已存于既有仓库源码/seed/docs 中） | 本需求所使用环境变量均为项目既有基线 `Settings` 配置项，不涉及改动 `Dockerfile`、`docker-entrypoint.sh` 或新增运维停机变更动作 | 归档拆分确认 / 2026-11-16；`FR-003`, `FR-008` |

---

## 9. 边界与约束 【补充】

### 9.1 范围边界

**本次需求包含（In Scope）：**

- `src/report_agent/runtime/` 中 8 个核心运行模块：`__init__.py`、`deps.py`、`workspace.py`、`output_model.py`、`evidence.py`、`prompt.py`、`model_factory.py`、`runner.py`。
- 全局平台级系统提示词 `src/report_agent/seed/system-prompt.md`。
- 运行时核心回归测试与离线脚本桩：`tests/scripted_model.py`、`tests/test_agent_runtime.py`、`tests/test_native_output.py`、`tests/test_review_runtime.py`、`tests/test_review_fixes_runtime.py`。

**本次需求不包含（Out of Scope）：**

- 模板/Skill/接口 YAML 解析、Jinja2 沙箱环境与 `TrackedValue`/`TrackedList` 核心实现（归属 `RA-001`，本需求仅通过接口调用 `render_body` 与 `field_render`）。
- 12 个确定性平台工具实现（`runtime/tools.py`、`runtime/text_tools.py`）与外部网关客户端（`gateway/`）（归属 `RA-004`）。
- 文件存储仓库、Git 发布锁、热更新配置持久化及 `RunStore` 底层实现（归属 `RA-002`）。
- FastAPI HTTP/SSE 路由鉴权（`api/`）、嵌入式聊天窗口（`chat/`）与 Vue 3 前端界面（`frontend/`）（归属 `RA-005`、`RA-006`、`RA-007`）。

### 9.2 技术与业务约束

- **零业务硬编码红线**：`runtime/` 任何逻辑不得直接判断特定模板编号、具体短信模版关键词或套餐计费规则（注：`runner._summary` 仅作日志检索索引读取常见通用入参键 `"手机号码"` 与 `"业务名称"`，不影响任何执行与判定分支）。
- **单进程内存态限制**：`_DynamicLimiter` 与 `_agent_cache` 仅在单进程内同步一致，禁止生产配置多 Worker 部署。
- **测试隔离边界**：单元测试必须基于 `FunctionModel`、`TestModel` 或 `httpx.MockTransport` 离线完成，受 `tests/conftest.py` 的 `SEED_DIR` 隔离机制保护，严禁访问外网大模型服务。

---

## 10. 异常场景与边界情况 【核心】

| 编号 | 场景描述 | 触发条件 | 预期处理方式 | 是否阻断主流程 | 优先级 | 关联需求 |
| --- | --- | --- | --- | --- | --- | --- |
| `EX-001` | 循环引用与自引用自我掩盖 | 字段 `A` 同时引用自身 `{"type": "field", "name": "A"}` 与 `not_found` 字段 `B`，或 `甲 -> 甲` 在前、`乙 -> 甲` 在后 | 剔除自引用本身，禁入 `safe_nodes` 剪枝缓存，检出全部环与可达节点并同步降级 | 否（局部降级为 `not_found`） | 高 | `FR-006`, `FR-007` |
| `EX-002` | 标量容器污染与数值前导零混同 | 模型向标量字段填入 `list`/`dict`，或提交 `"0"` 企图匹配 `"0000"` / 提交 `"1"` 匹配 `True` | `EvidenceChecker` 与 `_salvage_partial_report` 立即拒绝容器，`_values_equivalent` 严格区分前导零及布尔与数字 `0/1` | 否（打回重试或降级拒收） | 高 | `FR-005`, `FR-007` |
| `EX-003` | 外部运行取消与超时/超限中断 | 聊天窗口点击「停止」触发 `CancelledError`，或超出 `agent_run_timeout_s` / `UsageLimits` | 捕获异常记入 `error`（取消记 `"运行已取消"`）、提取已用 `usage`/`messages` 异步落盘 `RunStore`，遇取消时再原样重抛 | 是（本次运行结束为 `FAILED`） | 高 | `FR-009` |
| `EX-004` | 跨线程队列监听与已关闭循环 | `queue_listener` 在子线程调用或宿主事件循环已关闭时执行 `emit` | 检测循环状态，活跃跨线程走 `call_soon_threadsafe`，同循环或已关闭循环安全降级 `put_nowait` 并兜底保护不崩溃 | 否 | 中 | `FR-009` |
| `EX-005` | 草稿零字段、空白描述或重复入参 | 维护中草稿模板设 `fields: []`、重复 `inputs.key` 或全空白 `description` | `build_report_model` 去重构造空模型、`build_task_instructions` 自动跳过空白括注并透传未声明非空附加参数 | 否 | 中 | `FR-002`, `FR-004` |
| `EX-006` | 重试耗尽且模型漏填或格式错误 | 达到 `agent_output_retries` 触发 `UnexpectedModelBehavior`，或 `prompted` 文本包含代码块与缺失字段 | `_extract_candidate_report` 解析最近 `ToolCallPart`/`TextPart` 后调用 `_salvage_partial_report` 并行级联降级，保留合规字段输出 `PARTIAL` | 否（局部保留，产出 `PARTIAL`） | 高 | `FR-007` |

---

## 11. 待确认事项 【核心】

> 本需求为已交付归档之核心运行时子系统，所有架构决策与边界问题均已在实现与回归验证中闭环解决，当前无未关闭阻塞问题。

| 编号 | 问题描述 | 影响范围 | 责任方 | 期望确认日期 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `Q-001` | 模型输出模式选型与空列表证据口径一致性（是否需为部分内网推理网关关闭 `strict` 工具与 `json_schema` 能力，以及列表无记录是否计入 `PARTIAL`） | `FR-003`, `FR-005`, `FR-010` | 架构组 / 运行时团队 | 2026-11-16 | 已关闭 | 通过 `agent_output_mode`（4 模式）+ `llm_strict_tools`/`llm_tool_choice_required` 配置覆写兼容各类服务；列表查过确无匹配记录允许提交 `status="found", value=[]`（附 0 行证据）并判定为 `SUCCESS` |

---

## 附录：原始需求描述 【补充】

```text
智能申告报告填写与资源治理平台（report-agent）全栈研发工作拆分（子规格 003/008，需求编号 RA-003，33.0 人天）：
负责单智能体统一规划管道、基于模板动态构造严格交卷 Schema（支持 tool/native/json_object/prompted 4 种输出模式与 128 槽 LRU 模型缓存）、quote/input/derive 强证据校验、列表高速去重核验与空结果 0 行证明、依赖图可达环检测、ModelRetry 打回重填与部分挽救及不动点级联降级、_RuntimeBundle 在线热切换与 _DynamicLimiter 跨线程并发限流、EventSink 过程轨迹事件流、DocumentIndex 精确行列偏移定位及三态结果渲染判定。
```

---

## 变更记录（Changelog）

| 版本 | 日期 | 变更人 | 变更内容 |
| --- | --- | --- | --- |
| 1.0 | 2026-11-16 | AiCoding(codex) | 依据 `report-agent` 运行时源码与测试基线完成初始规格拆分归档 |
| 2.0 | 2026-11-16 | AiCoding(codex) | 按改造后中文 Spec-Kit 模板与 `/sdd-documentation` 取证标准重构升级为全章节闭环 SDD 规格文档 |

---

## 增量更新说明

> 本文档按 `report-agent` 中文 Spec-Kit 模板与 SDD 取证规范生成；后续如有范围或契约变更，同步更新对应章节与 `变更记录` 并联动刷新 `plan.md` 与 `tasks.md`。
