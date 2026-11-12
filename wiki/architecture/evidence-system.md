---
title: 强证据核验机制
type: concept
tags: [architecture, evidence, anti-hallucination, validation, list-fields]
sources:
  - src/report_agent/runtime/evidence.py
  - src/report_agent/runtime/output_model.py
  - src/report_agent/runtime/runner.py
  - src/report_agent/domain/template.py
updated: 2026-11-12
---

# 强证据核验机制

<!-- #Created By AiCoding(codex) -->

`EvidenceChecker`（`src/report_agent/runtime/evidence.py#EvidenceChecker.check`）是平台实现“零业务硬编码防幻觉”的核心防线。模型提交的每一个字段结论都必须附带结构化证据引用，由平台对照 `Workspace` 中真实发生过的接口响应、工具输出、工单入参和单据原文做确定性核对。

## 1. 五种基础证据引用类型

在 `output_model.py` 中，单条证据按 `type` 判别器分为五种来源（ Schema 自动按字段 `evidence` 等级收窄可选证据类型）：

| `type` | 结构字段 | 存在性与合法性校验规则 |
|--------|----------|------------------------|
| `api` | `resultId`, `row`, `column` | `resultId` 必须存在于 `workspace.results` 且 `ok == True`；非空记录核对时 `row`（从 `0` 开始，即 `query_result` 返回的 `row`，严格拒绝布尔值）与 `column` 必须命中真实记录单元格 |
| `document` | `quote` | `quote` 非空，且由 `locate_quote_in_document` 在单据原文中定位匹配（优先逐字匹配，其次空白折叠归一化匹配） |
| `input` | `key` | `key` 仅限当前模板声明的入参名且已传入非空值 |
| `tool` | `callId` | `callId` 必须存在于 `workspace.tool_calls` 且 `call.ok == True` |
| `field` | `name` | `name` 必须是当前模板已定义的其他字段名（禁止自引用，且全局 `EvidenceChecker.check` 会执行有向图 DFS 拦截 `field` 循环依赖） |

## 2. 三种字段证据等级（`FieldDef.evidence`）

### 2.1 原文引用（`evidence: quote`）

适用于短信正文、原套餐名称、协议条款、单据原文日期、充值流水等**绝不允许模型编造或改写**的字段：

- **允许的证据来源**：标量字段仅允许 `api` 或 `document`；列表字段在 Schema 层额外开放 `tool`（专供 `value=[]` 空列表证明已执行查询，非空列表仍仅允许 `api` / `document`）。
- **核对规则（`_check_quote`）**：
  - **默认原文包含**：提交值必须出现在被引用的接口单元格或单据 `quote` 片段中（支持连续空白归一化 `_contains_with_ws` 与数值等价 `_values_equivalent`）；
  - **整条完全一致（`quoteWhole: true`）**：短信正文类字段（如 `订购短信`、`二次确认短信`、`验证码短信`、`提醒短信` 等）开启 `quoteWhole: true`，要求提交值归一化换行符与零宽字符后与目标列原文**整条完全相等**，一个字符也不得增删截断。

### 2.2 入参直取（`evidence: input`）

适用于直接取自上游传入参数原值的字段（如 `商品名称` 取自入参 `业务名称`）：

- 仅允许 `type="input"` 证据；
- 引用的 `inputs[key]` 必须非空，且提交值与入参原值等价（`_values_equivalent`）。

### 2.3 规则推导与 `VALUE_TOOLS` 核对（`evidence: derive`）

适用于需要经过确定性日期格式转换（如将 14 位 `smsSendTime` 转为 `yyyy-MM-dd` 的 `提醒日期`/`发送日期`、将 `业务月份` 转为 `yyyy年M月d号` 的 `受理日期`）、关键词分类或跨月聚合的字段：

- 允许引用 `api`、`document`、`input`、`tool`、`field` 五类证据，所有被引用的目标都必须真实存在且成功；
- **值转换工具强约束（`VALUE_TOOLS = {"format_date"}`）**：只要 `derive` 字段的 `evidence` 引用了 `VALUE_TOOLS` 中的工具（即 `format_date` 的 `callId`），核验器强制要求字段提交值 `value` 必须与该次工具调用输出的 `value` 等价，否则退回提示“请直接使用工具输出”，杜绝模型手写改错日期格式。

## 3. 列表字段（`type: list`）逐行核验与空列表语义

列表字段（如模板 106/107 的 `充值流水`、模板 119 的 `账期短信提醒列表`）由 `_check_list_field` 与 `_check_empty_list_evidence` 核验：

### 3.1 非空列表（`status="found"`, `len(value) >= 1`）

1. 每行必须是以列名为键的对象，无缺列、无未定义多余列、不能全列为空，枚举列取值必须在可选范围内；
2. 当列表声明 `evidence: quote`（如 `充值流水`）时，仅允许 `api` 或 `document` 证据，且每一行的**每个非空文本单元格**都必须逐字出现在被引用的接口记录单元格或单据片段中。

### 3.2 空列表 `found: []` vs 缺失 `not_found`（二期核心机制）

| 提交形态 | 业务含义 | 证据核验要求（`_check_empty_list_evidence`） | 渲染与运行状态影响 |
|----------|----------|----------------------------------------------|-------------------|
| `status="found", value=[]` | 各账期/时间窗均已正常查询完毕，确认无符合条件的记录 | 即使 `f.evidence == "quote"`，也要求至少附带一条**成功的核查证据**：`type="tool"`（`ok=True`，如 `call_api` 或 `query_result` 的 `callId`）、`type="api"`（`ok=True`，允许 `records` 为空且 `row=0, column=""` 不报越界）或 `type="document"`；无查询证据瞎报 `[]` 会被打回 | `TrackedList([], name, missing=False)`，`rendered="[]"`，前端展示为“无记录（0 行）”，运行状态为 **`SUCCESS`** |
| `status="not_found", value=None` | 缺少必要入参、前置依赖缺失或任一账期接口 `ok=False` 失败 | `value` 为 `None`，`reasoning` 说明缺参或报错原因 | `TrackedList([], name, missing=True)`：若生效分支实际执行了 `{% for %}` 且字段 `visible: true`、`whenMissing != "value"`，计入 `missingShown`，运行状态准确降为 **`PARTIAL`** |

## 4. 失败字段挽救与依赖链级联降级

1. **校验重试阶段**：在 `@agent.output_validator` 内，若 `ctx.retry < ctx.max_retries`（`AGENT_OUTPUT_RETRIES`，默认 3 次），发出 `report_rejected` 事件并通过 `ModelRetry(format_issues(issues))` 让模型修正违规字段。
2. **重试耗尽降级与异常挽救（`_salvage_partial_report` + `_cascade_degraded_fields`）**：
   - 将违规字段重置为 `status="not_found", value=None, evidence=[]`；
   - `_cascade_degraded_fields` 循环扫描其余 `status="found"` 的字段：凡在 `evidence` 中通过 `{"type": "field", "name": X}` 引用了已降级字段的下游衍生字段，全部递归同步降级为 `not_found` 直至不动点，并发出 `report_degraded` 事件。

## 相关页面

- [单智能体请求处理管道](request-pipeline.md)
- [模板模型与渲染机制](template-and-rendering.md)
- [确定性平台工具设计](deterministic-tools.md)
- [ADR-001：采用单智能体自主规划 + 强证据校验替代 Java 三 Agent 编排](../decisions/adr-001-single-agent-and-evidence.md)
- [ADR-004：采用 Jinja2 沙箱对齐 Pebble 渲染语义，并以 TrackedValue / TrackedList 精确判定报告完整度](../decisions/adr-004-jinja2-pebble-and-tracked-list.md)
