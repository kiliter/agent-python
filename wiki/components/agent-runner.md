---
title: AgentRunner 运行时组件剖析
type: component
tags: [component, runtime, runner, output-model, prompt, workspace]
sources:
  - src/report_agent/runtime/runner.py
  - src/report_agent/runtime/output_model.py
  - src/report_agent/runtime/prompt.py
  - src/report_agent/runtime/render.py
  - src/report_agent/runtime/model_factory.py
  - src/report_agent/runtime/workspace.py
updated: 2026-11-12
---

# AgentRunner 运行时组件剖析

<!-- #Created By AiCoding(codex) -->

`src/report_agent/runtime/`（除工具集与核验器外）构成了单智能体执行的调度内核，负责将静态模板定义、动态大模型客户端、请求工作区与最终结果序列化串联起来。

## 1. 模块职责分工

| 文件 | 核心类 / 函数 | 职责说明 |
|------|---------------|----------|
| `runner.py` | `AgentRunner`、`_RuntimeBundle`、`_DynamicLimiter`、`RunRequest`、`RunResult`、`_salvage_partial_report`、`_cascade_degraded_fields` | 单次报告生成的顶层编排器：快照快路径获取、动态并发限流、线上 `(report_model, agent)` 版本缓存、原子配置热重载、部分挽救与全量 `not_found` 级联降级 |
| `output_model.py` | `build_report_model`、`Evidence`（5 个子类） | 按模板 `fields` 动态创建严格 Pydantic 交卷模型（含 `list` 字段嵌套 `{字段名}Row` 行模型，字段说明收敛至 `$defs` 类文档避免 `$ref` 外层 `anyOf` 包装） |
| `prompt.py` | `build_task_instructions`、`USER_PROMPT` | 组装动态任务说明（白名单 Skill 摘要目录、剥离 `原规则（Java）：` 尾注的字段规则、展示声明与非空附加 `inputs`、`L001` 行号单据） |
| `render.py` | `field_render`、`build_render_context` | 将交卷结论映射为 `TrackedValue` / `TrackedList` 渲染上下文，同时计算每个字段的展示值 |
| `model_factory.py` | `build_model`、`build_model_settings` | 根据当前生效的 `Settings`（含运行期热更新覆盖，默认 `llm_parallel_tool_calls=True`）构建 Pydantic AI `OpenAIChatModel` 与 `ModelSettings` |
| `workspace.py` | `Workspace`、`ApiResult`、`ToolCall`、`EventSink` | 单次运行内存态账本：存储单据行与惰性 `DocumentIndex`、网关响应原文与幂等 `call_api` 去重缓存、工具调用输入输出及递增序号的过程事件 |
| `tools.py` | `RunDeps` | 通过 Pydantic AI `RunContext[RunDeps]` 向所有平台工具注入模板、资源快照、网关客户端与当前 `Workspace` |

## 2. 关键实现细节

### 2.1 四种交卷输出模式、`_RuntimeBundle` 原子热重载与模型缓存

`AgentRunner._build_output_type` 按 `AGENT_OUTPUT_MODE` 适配不同推理服务端：
- **`"tool"`（默认推荐）**：返回 `ToolOutput(report_model, name="submit_report", strict=settings.llm_strict_tools)`，把最终交卷统一为标准 Function Calling，模型兼容性最好；
- **`"native"`**：返回 `NativeOutput(report_model, strict=settings.agent_native_strict)`，利用服务端受限解码直接输出严格符合 JSON Schema 的报文；
- **`"json_object"` / `"prompted"`**：适配不支持 `json_schema` 严格模式的旧版推理引擎。

在高并发与在线热更新场景下，`AgentRunner` 做了三项关键工程加固：
1. **不可变 `_RuntimeBundle` 原子切换**：将 `(seq, settings, model, model_settings, tools)` 封装为不可变对象，`reload_config` 单引用原子替换，彻底消除跨线程分步改写属性导致的新旧配置撕裂窗口；
2. **`_DynamicLimiter` 动态并发限流**：支持在线调大或调小 `agent_max_concurrent_runs`（默认 `8`），直接计入当前已在途请求数，避免重建 `asyncio.Semaphore` 造成瞬时 `old_inflight + new_limit` 超限；
3. **线上 `(report_model, agent)` 缓存与快照快路径**：优先通过 `ReleaseStore.try_live_snapshot()` 免线程切换获取线上快照，并按 `(rev, tpl.id, bundle.seq)` 有界缓存动态构建的 `(report_model, agent)`，将每次请求的模型/Schema 组装开销从约 `9.3 ms` 降至微秒级。

### 2.2 `Workspace` + `EventSink` 的事件流与轮次追踪

`AgentRunner._event_stream_handler` 挂载在 Pydantic AI 的 `event_stream_handler` 钩子上：
- 监听 `PartStartEvent` 中的 `TextPart` 或思考文本，实时发出 `model_text` 事件供工作台时间线展示智能体思考轨迹；
- 统计模型请求轮次 `round_no`，每次模型发起新一轮推理时发出 `model_request` 事件；
- 所有平台工具执行完毕后均通过 `workspace.log_tool(...)` 分配递增 `callId`（`t1`, `t2`...）并同步发出 `tool` 事件。

### 2.3 运行结果组装与前端溯源定位（`_locate_evidence`）

运行收尾阶段，`_build_field_results()` 为每个字段生成前端工作台可直接消费的溯源指针 `evidenceTarget`：
- 若首个核心证据为 `api`：返回 `{"tab": "api", "resultId": ..., "row": ..., "column": ...}`，前端点击字段即可自动展开对应网关调用并高亮目标行与列；
- 若为 `document`：复用工作区缓存的 `DocumentIndex`（`get_document_index`）在单据中检索引用片段所在行号，返回 `{"tab": "doc", "line": N}`；
- 若为 `input`：返回 `{"tab": "input", "key": ...}`。

同时，若 `with_messages=True`（或落盘完整记录），`all_messages_json()` 会保存完整 Pydantic AI 对话消息序列，供深度离线排障重放。

## 相关页面

- [单智能体请求处理管道](../architecture/request-pipeline.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [平台工具实现剖析](platform-tools.md)
- [Vue 3 资源工作台前端剖析](workbench-frontend.md)
