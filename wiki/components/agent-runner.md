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
| `runner.py` | `AgentRunner`、`RunRequest`、`RunResult`、`_salvage_partial_report`、`_cascade_degraded_fields` | 单次报告生成的顶层编排器：快照获取、信号量并发限流、Pydantic AI `Agent` 组装、事件流收集、部分挽救降级与运行详情构造 |
| `output_model.py` | `build_report_model`、`Evidence`（5 个子类） | 按模板 `fields` 动态创建严格 Pydantic 交卷模型（含 `list` 字段嵌套 `{字段名}Row` 行模型） |
| `prompt.py` | `build_task_instructions`、`USER_PROMPT` | 组装动态任务说明（白名单 Skill 摘要目录、白名单接口、字段规则与 `L001` 行号单据） |
| `render.py` | `field_render`、`build_render_context` | 将交卷结论映射为 `TrackedValue` / `TrackedList` 渲染上下文，同时计算每个字段的展示值 |
| `model_factory.py` | `build_model`、`build_model_settings` | 根据当前生效的 `Settings`（含运行期热更新覆盖）构建 Pydantic AI `OpenAIChatModel`（定制 `OpenAIProvider` / 重试 HTTP 客户端）与 `ModelSettings` |
| `workspace.py` | `Workspace`、`ApiResult`、`ToolCall`、`EventSink` | 单次运行内存态账本：存储单据行、网关响应原文与记录行、工具调用输入输出及递增序号的过程事件 |
| `tools.py` | `RunDeps` | 通过 Pydantic AI `RunContext[RunDeps]` 向所有平台工具注入模板、资源快照、网关客户端与当前 `Workspace` |

## 2. 关键实现细节

### 2.1 `build_model` 与四种交卷输出模式适配

不同私有化部署的大模型推理框架（vLLM、SGLang、百炼、DeepSeek）对 OpenAI Structured Outputs（`response_format: json_schema`）与工具调用并存的支持度不一。`AgentRunner._build_output_type` 按 `AGENT_OUTPUT_MODE` 提供四种策略：
- **`"tool"`（默认推荐）**：返回 `ToolOutput(report_model, name="submit_report", strict=settings.llm_strict_tools)`，把最终交卷统一为标准 Function Calling，模型兼容性最好；
- **`"native"`**：返回 `NativeOutput(report_model, strict=settings.agent_native_strict)`，利用服务端受限解码直接输出严格符合 JSON Schema 的报文；
- **`"json_object"` / `"prompted"`**：适配不支持 `json_schema` 严格模式的旧版推理引擎。

每次 `AgentRunner.run` 启动时都会通过 `self.settings` 读取最新的有效 `Settings` 并实时构建模型实例，因此通过 `RuntimeConfigStore` 热更新模型名称、API Key、Base URL 或温度无需重启服务即可在下一次请求生效。

### 2.2 `Workspace` + `EventSink` 的事件流与轮次追踪

`AgentRunner._event_stream_handler` 挂载在 Pydantic AI 的 `event_stream_handler` 钩子上：
- 监听 `PartStartEvent` 中的 `TextPart` 或思考文本，实时发出 `model_text` 事件供工作台时间线展示智能体思考轨迹；
- 统计模型请求轮次 `round_no`，每次模型发起新一轮推理时发出 `model_request` 事件；
- 所有平台工具执行完毕后均通过 `workspace.log_tool(...)` 分配递增 `callId`（`t1`, `t2`...）并同步发出 `tool` 事件。

### 2.3 运行结果组装与前端溯源定位（`_locate_evidence`）

运行收尾阶段，`_build_field_results()` 为每个字段生成前端工作台可直接消费的溯源指针 `evidenceTarget`：
- 若首个核心证据为 `api`：返回 `{"tab": "api", "resultId": ..., "row": ..., "column": ...}`，前端点击字段即可自动展开对应网关调用并高亮目标行与列；
- 若为 `document`：在 `workspace.document_lines` 中检索引用片段所在行号，返回 `{"tab": "doc", "line": N}`；
- 若为 `input`：返回 `{"tab": "input", "key": ...}`。

同时，若 `with_messages=True`（或落盘完整记录），`all_messages_json()` 会保存完整 Pydantic AI 对话消息序列，供深度离线排障重放。

## 相关页面

- [单智能体请求处理管道](../architecture/request-pipeline.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [平台工具实现剖析](platform-tools.md)
- [Vue 3 资源工作台前端剖析](workbench-frontend.md)
