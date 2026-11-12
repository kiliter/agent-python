---
title: 单智能体请求处理管道
type: concept
tags: [architecture, pipeline, runner, status, partial-salvage]
sources:
  - src/report_agent/domain/template.py
  - src/report_agent/runtime/runner.py
  - src/report_agent/runtime/output_model.py
  - src/report_agent/runtime/render.py
  - src/report_agent/runtime/workspace.py
  - src/report_agent/api/common.py
  - src/report_agent/api/routes_system.py
updated: 2026-11-13
---

# 单智能体请求处理管道

<!-- #Created By AiCoding(codex) -->

本页说明一次申告报告生成请求从 HTTP/SSE 入口进入 `AgentRunner.run` 到最终落盘返回的全链路执行机制，重点解析资源快照隔离、动态交卷 Schema、重试挽救与三级状态（`SUCCESS` / `PARTIAL` / `FAILED`）判定。

## 1. 入口与运行模式

平台提供两类运行入口，底层均统一委托给 `src/report_agent/runtime/runner.py#AgentRunner.run`：

| 入口场景 | HTTP 路由 | 鉴权方式 | 默认目标版本（`target`） | 事件推送方式 |
|----------|-----------|----------|-------------------------|--------------|
| **上游业务调用** | `POST /api/v1/reports`、`/reports/stream` | 请求头 `X-API-Key` | 固定 `"online"`（线上快照） | 同步 JSON 或 SSE `text/event-stream` |
| **工作台试运行** | `POST /api/v1/templates/{id}/dryrun`、`/dryrun/stream` | 会话 Cookie / Bearer Token | `"draft"`（草稿叠加视图）或 `"online"` | 同步 JSON 或 SSE `text/event-stream` |

在流式接口中，路由层通过 `asyncio.Queue` 注入 `on_event` 回调，每产生一条 `ProcessEvent` 即推送 `event: event`，每 15 秒发送 `: keep-alive` 注释保活，结束后推送 `event: final`。客户端中途断开连接不会取消后台正在执行的 `AgentRunner` 任务，确保运行记录完整落盘。

## 2. 七步执行主流程

```mermaid
sequenceDiagram
    participant Caller as 调用方 (上游 / 工作台)
    participant Runner as AgentRunner.run
    participant Store as ResourceService
    participant Agent as Pydantic AI Agent
    participant Checker as EvidenceChecker
    participant Jinja as Jinja2 沙箱渲染

    Caller->>Runner: RunRequest(templateId, inputs, documentText, target)
    Runner->>Store: snapshot(target) 锁定不可变快照
    Runner->>Runner: validate_inputs() & 初始化 Workspace + EventSink
    Runner->>Runner: build_report_model() 动态生成 submit_report Schema
    loop ReAct 工具循环 (上限 request_limit / tool_calls_limit)
        Agent->>Agent: 按需调用 load_skill / call_api / 确定性计算工具
    end
    Agent->>Checker: 调用 submit_report 提交全部字段结论与证据
    alt 证据核验不通过且重试未耗尽
        Checker-->>Agent: 抛出 ModelRetry(退回具体违规字段重填)
    else 重试耗尽仍存在违规字段
        Runner->>Runner: _salvage_partial_report() + _cascade_degraded_fields()
    end
    Runner->>Jinja: build_render_context() + render_body()
    Jinja-->>Runner: 渲染文本 + 实际展示字段集合 used_fields
    Runner->>Caller: 判定 SUCCESS / PARTIAL + 异步写入 RunStore
```

### 第 1 步：捕获不可变资源快照

`AgentRunner._capture` 按 `req.target` 在运行开始瞬间锁定本次请求使用的模板、Skill 字典、接口契约字典、系统提示词与版本号（如 `r3` 或 `r3+草稿`）：
- 上游 `"online"` 模式优先调用 `ReleaseStore.try_live_snapshot()` 同步快路径（轻量 `os.readlink` 核对 `current` 软链并在进程内 `_snapshots` 命中时微秒级直返，未命中再回退 `asyncio.to_thread`）；工作台 `"draft"` 模式复用 `ResourceService.overlay()` 的 `(live_rev, _draft_mutation_seq, _drafts_fingerprint)` 内存缓存。
- 即使运行途中其他人在工作台发布了新版本，正在执行的请求也不会发生上下文撕裂。
- 若模板不存在或已被标记为下线（`tpl.offline == True` 且 `target != "draft"`），直接抛出 `TemplateUnavailableError`（HTTP 404）。

### 第 2 步：入参清洗校验与工作区创建

- 先对传入的 `req.inputs` 统一执行 `.strip()` 去除首尾空白（防止尾随空格透传给网关报错），再由 `validate_inputs(tpl, inputs)` 按 `template.yaml` 中 `inputs` 定义的 `required` 与 `pattern`（调用 `domain/template.py#safe_regex_fullmatch` 执行带防 ReDoS 语法树检查的整串匹配）做快速校验，不合法时立即抛出 `InputValidationError`（HTTP 400 `INVALID_INPUT`），不消耗任何模型 Token。
- 创建请求级隔离的 `Workspace` 与 `EventSink`（`src/report_agent/runtime/workspace.py`），负责将单据按行编号（`L001`、`L002`…）、惰性缓存 `DocumentIndex` 定位索引、记录网关调用的完整报文与幂等去重缓存（`r1`、`r2`…）、记录每次工具调用的输入输出（`t1`、`t2`…），并按序号发出过程事件（同事件循环内 `queue_listener` 直接入队，免除跨线程唤醒开销）。

### 第 3 步：动态构建与缓存交卷模型（`submit_report`）

`src/report_agent/runtime/output_model.py#build_report_model` 根据当前模板的 `fields` 动态生成 Pydantic 模型（草稿存在重复字段名时自动保序容错去重），配置 `extra="forbid"`（对应 OpenAI Structured Outputs `additionalProperties: false`，并将字段描述内聚于 `$defs` 类文档以避免 `$ref` 外层产生冗余 `anyOf` 包裹）：

- **标量字段**（`string` / `enum` / `date`）：`value` 类型为 `str | None`（枚举字段生成 `Literal[...]` 约束可选值）；
- **列表字段**（`list`）：先根据 `columns` 动态生成行模型 `{字段名}Row`（每列 `str` 或枚举 `Literal[...]`），再将字段 `value` 声明为 `list[RowModel] | None`；
- 每个字段均固定包含四个属性：`status`（`"found"` | `"not_found"`）、`value`、`evidence`（`list[Evidence]`）与 `reasoning`（`str`）；
- **线上模型与 Agent 版本缓存**：当 `target == "online"` 且使用默认模型/工具时，`AgentRunner` 按 `(rev, tpl.id, bundle.seq)` 有界缓存编译好的 `(report_model, agent)`，消除每请求重复构建动态 Pydantic Schema 的 CPU 开销。

关于交卷输出通道（`AGENT_OUTPUT_MODE`，见 `runner.py#AgentRunner._build_agent`）：
- 默认 `tool`：通过 `ToolOutput(report_model, name="submit_report")` 注册交卷工具，兼容 DeepSeek、通义千问、vLLM 等各类 OpenAI 兼容服务端；
- 可选 `native` / `json_object` / `prompted`：分别对应 `NativeOutput(report_model, strict=settings.agent_native_strict)` 与 `PromptedOutput(report_model, name="submit_report")`。

### 第 4 步：提示词注入与渐进式 Skill 披露

- **静态系统提示词 + 动态任务说明**（`prompt.py#build_task_instructions`）：加载 `system-prompt.md`，并在动态 `instructions` 中仅把当前模板 `skills` 白名单内的 Skill **标识 + 中文标题 + 一句话描述**与白名单接口渲染进目录，不一次性塞入全部 11 个 `SKILL.md` 正文。模型只在需要时调用 `load_skill`（支持 `names=[...]` 一次批量加载多个 Skill）。
- **用户提示词精简与附加参数透传**（`prompt.py#USER_PROMPT`）：注入模板全部待填字段的规则与证据要求（运行时自动剥离 `template.yaml` 中仅供人工对照的 `原规则（Java）：` 尾注以节省约 30% 字段说明 Token），同时将 `tpl.inputs` 声明入参及 `deps.inputs` 中其它非空附加参数（如 `deadlineDate`、附加渠道信息）与带行号的单据文本一并呈现给模型。

### 第 5 步：ReAct 工具循环与并发限额保护

- 平台级动态并发限流器 `_DynamicLimiter(settings.agent_max_concurrent_runs)` 限制全局并发运行数（默认 `8`，自动清理已取消或已关闭事件循环的失效等待协程），配合不可变 `_RuntimeBundle` 实现运行期配置原子热重载而不会因重建信号量突破在途并发上限。
- Pydantic AI `UsageLimits` 强制约束单次运行的 `agent_request_limit`（默认 25 轮模型请求）与 `agent_tool_calls_limit`（默认 120 次工具调用，默认开启 `llm_parallel_tool_calls=True`），外层包裹 `asyncio.timeout(settings.agent_run_timeout_s)`（默认 600s）超时保护。

### 第 6 步：证据核验、精确重填与级联部分挽救

模型每次交卷都会进入 `@agent.output_validator`：

1. `EvidenceChecker.check(report)` 逐字段核验状态、类型、格式与证据链（详见 [强证据核验机制](evidence-system.md)）。
2. 若存在违规项且未超过 `AGENT_OUTPUT_RETRIES`（默认 3 次），发出 `report_rejected` 事件，并抛出 `ModelRetry`——仅把违规字段名称及具体原因拼成反馈消息发回给模型，模型无需重跑已成功的网关查询，只需修正交卷参数。
3. 若达重试上限或外层捕获到 `UnexpectedModelBehavior`：
   - 验证器内达到重试上限（`ctx.retry >= ctx.max_retries`）时直接调用 `_degrade_failed_fields()` 原位降级违规字段；外层异常时由 `_salvage_partial_report()` 从消息历史最后一次 `submit_report` 调用或文本载荷（`_extract_json_dict` 支持跳过前置文字定位代码块 JSON）中挽救合法草稿（标量字段严格拒收 `list`/`dict` 容器值）；
   - 将所有未通过 `EvidenceChecker` 的字段强制改写为 `status="not_found", value=None, evidence=[]`（收尾阶段同步清空所有 `not_found` 字段上的未核验残留 `evidence`），标记 `degraded_fields`；
   - `_cascade_degraded_fields()` 扫描其余 `status="found"` 的字段：只要某字段的 `evidence` 含自引用、引用了已被平台降级的前置字段，或引用了模型自报 `not_found` 的前置字段且自身缺乏其它真实有效支撑源（`has_supporting_real_source`），则将该下游字段一并递归降级为 `not_found`，并发出 `report_degraded` 事件。

### 第 7 步：Jinja2 渲染与三级运行状态判定

`build_render_context()` 与 `render_body()` 渲染出最终报告，并收集模板实际展示过的字段集合 `used_fields`（详见 [模板模型与渲染机制](template-and-rendering.md)）。平台据此精确划分三级状态：

| 状态 | 判定条件 | 典型场景 |
|------|----------|----------|
| `SUCCESS` | 运行未抛异常，且正文中**所有实际展示**的无固定默认值可见字段（`visible and whenMissing != "value" and name in used_fields`）均为 `status == "found"`（包括列表字段合法查得 0 行 `status="found", value=[]`） | 正常全部填出；或未找到的字段恰好落在未命中的 `{% if %}` 分支内未展示；或列表查询确认无记录 |
| `PARTIAL` | 运行完成了渲染（含触发部分挽救），但存在至少一个**实际展示在报告中**且 `whenMissing != "value"` 的可见字段或列表字段为 `status == "not_found"`（记录在 `missingShown` 列表中） | 网关某账期报错导致 `充值流水` 为 `not_found` 且进入了展示分支；单据缺失某必填项留了占位符或空白 |
| `FAILED` | 模型连接超时、超过最大轮数/工具调用上限、无法从异常交卷中挽救任何合法结构，或模板渲染本身报错 | 大模型 502/超时、死循环触发 `UsageLimitExceeded` |

## 相关页面

- [强证据核验机制](evidence-system.md)
- [模板模型与渲染机制](template-and-rendering.md)
- [确定性平台工具设计](deterministic-tools.md)
- [AgentRunner 运行时组件剖析](../components/agent-runner.md)
- [ADR-001：采用单智能体自主规划 + 强证据校验替代 Java 三 Agent 编排](../decisions/adr-001-single-agent-and-evidence.md)
