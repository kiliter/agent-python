---
title: 强证据核验机制
type: concept
tags: [architecture, evidence, anti-hallucination, validation, list-fields]
sources:
  - src/report_agent/runtime/evidence.py
  - src/report_agent/runtime/output_model.py
  - src/report_agent/runtime/runner.py
  - src/report_agent/runtime/render.py
  - src/report_agent/domain/template.py
updated: 2026-11-13
---

# 强证据核验机制

<!-- #Created By AiCoding(codex) -->

`EvidenceChecker`（`src/report_agent/runtime/evidence.py#EvidenceChecker.check`）是平台实现“零业务硬编码防幻觉”的核心防线。模型提交的每一个字段结论都必须附带结构化证据引用，由平台对照 `Workspace` 中真实发生过的接口响应、工具输出、工单入参和单据原文做确定性核对。

## 1. 五种基础证据引用类型

在 `output_model.py` 中，单条证据按 `type` 判别器分为五种来源（ Schema 自动按字段 `evidence` 等级收窄可选证据类型）：

| `type` | 结构字段 | 存在性与合法性校验规则 |
|--------|----------|------------------------|
| `api` | `resultId`, `row`, `column` | `resultId` 必须存在于 `workspace.results` 且 `ok == True`；非空记录核对时 `row`（从 `0` 开始，即 `query_result` 返回的 `row`，严格拒绝布尔值与越界下标）与 `column` 必须命中真实记录单元格 |
| `document` | `quote` | `quote` 非空，且由绑定在工作区上的惰性索引 `DocumentIndex`（`locate_quote_in_document`）在单据原文中定位匹配（优先逐字匹配，其次空白折叠归一化匹配） |
| `input` | `key` | `key` 必须存在于当前运行入参 `inputs` 中且去空白后非空（空字符串/全空白入参不能作为 `found` 证据） |
| `tool` | `callId` | `callId` 必须存在于 `workspace.tool_calls` 且 `call.ok == True`；**严禁将 `load_skill` 作为任何字段的证据**（`load_skill` 仅用于阅读技能说明） |
| `field` | `name` | `name` 必须是当前模板已定义的其他字段名（禁止自引用；全局 `EvidenceChecker.check` 通过 `_find_reachable_cycle` 跨起点共享无环 `safe_nodes` 执行 $O(V+E)$ 有向图 DFS，且不对含自环节点标记无环，完整拦截环上节点及 `B -> A -> A` / `C -> A <-> B` 等指向环的环外节点；同时通过不动点 `_compute_supported_found_fields` 立即剔除含自引证据字段，禁止无真实有效数据源支撑地引用 `not_found` 前置字段） |

此外，标量字段与列表单元格在 `EvidenceChecker._check_field`、`_salvage_partial_report` 与 `render.py#field_render` 中统一拒收 `list` / `dict` 容器类型（`scalar_to_str` 仅转换基础数值/布尔标量），杜绝把 Python 容器 `repr` 强转混入报告正文。

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

适用于需要经过确定性日期格式转换（如将 14 位 `smsSendTime` 转为 `yyyy-MM-dd` 的 `提醒日期`/`发送日期`、将 `业务月份` 转为 `yyyy年M月d号` 的 `受理日期`）、标准化表达（如将“月费10元”标准化为“10元/月”的 `标准资费`）、多来源回退（如单据缺失时回退 `extraInfo` 的 `安装地址`）、关键词分类或跨月聚合的字段：

- 允许引用 `api`、`document`、`input`、`tool`、`field` 五类证据，所有被引用的目标都必须真实存在且成功（禁止引用 `load_skill` 或空值 `input`）；
- **前置 `not_found` 字段支撑约束**：通过 `_compute_supported_found_fields` 迭代收敛，若 `derive` 字段在 `evidence` 中引用了状态为 `not_found` 的前置 `field`，则必须同时具备至少一条真实有效支撑源（如备选回退链中另一个状态为 `found` 的前置 `field`，或合法的 `api` / `document` / 非空 `input`），单引或全引 `not_found` 前置字段提交 `found` 一律拦截报错；
- **值转换工具强约束（`VALUE_TOOLS = {"format_date"}`）**：只要 `derive` 字段的 `evidence` 引用了 `VALUE_TOOLS` 中的工具（即 `format_date` 的 `callId`），核验器强制要求字段提交值 `value` 必须与该次工具调用输出的 `value`（或批量模式输出的 `values` 列表任一元素）等价，否则退回提示“请直接使用工具输出”，杜绝模型手写改错日期格式。

## 3. 列表字段（`type: list`）逐行核验与空列表语义

列表字段（如模板 106/107 的 `充值流水`、模板 119 的 `账期短信提醒列表`）由 `_check_list_field` 与 `_check_empty_list_evidence` 核验：

### 3.1 非空列表（`status="found"`, `len(value) >= 1`）

1. 每行必须是以列名为键的对象，无缺列、无未定义多余列、不能全列为空，枚举列取值必须在可选范围内；
2. 当列表声明 `evidence: quote`（如 `充值流水`）时，仅允许 `api` 或 `document` 证据，核验器在行×列循环外预计算引用源的空白折叠串，确保每一行的**每个非空非枚举单元格**都逐字出现在被引用的接口记录单元格或单据片段中。

### 3.2 空列表 `found: []` vs 缺失 `not_found`（二期核心机制）

| 提交形态 | 业务含义 | 证据核验要求（`_check_empty_list_evidence`） | 渲染与运行状态影响 |
|----------|----------|----------------------------------------------|-------------------|
| `status="found", value=[]` | 各账期/时间窗均已正常查询完毕，确认无符合条件的记录 | 即使 `f.evidence == "quote"`，也要求至少附带一条**结果为 0 行的真实查询证明**：`type="tool"` 仅允许 `ok=True` 的 `call_api(count==0)` 或 `query_result(total==0)` 的 `callId`（严禁引用 `load_skill`、`normalize_text` 或结果大于 0 的调用）；`type="api"` 仅当 `ok=True`、`len(records) == 0` 且 `row in (None, 0)` 时有效（原表非空但筛选为空时须改引 `total==0` 的 `query_result` `callId`）；或合法的 `type="document"` | `TrackedList([], name, missing=False)`，`rendered="[]"`，前端展示为“无记录（0 行）”，运行状态为 **`SUCCESS`** |
| `status="not_found", value=None` | 缺少必要入参、前置依赖缺失或任一账期接口 `ok=False` 失败 | `value` 为 `None`，`reasoning` 说明缺参或报错原因 | `TrackedList([], name, missing=True)`：若生效分支实际执行了 `{% for %}` 且字段 `visible: true`、`whenMissing != "value"`，计入 `missingShown`，运行状态准确降为 **`PARTIAL`** |

## 4. 失败字段挽救与依赖链级联降级

1. **校验重试阶段**：在 `@agent.output_validator` 内，若 `ctx.retry < ctx.max_retries`（`AGENT_OUTPUT_RETRIES`，默认 3 次），发出 `report_rejected` 事件并通过 `ModelRetry(format_issues(issues))` 让模型修正违规字段。
2. **重试耗尽降级与异常挽救（`_degrade_failed_fields` + `_salvage_partial_report` + `_cascade_degraded_fields`）**：
   - 将违规字段重置为 `status="not_found", value=None, evidence=[]`（收尾阶段同样清空所有 `not_found` 字段上未经核验的残留 `evidence`）；
   - `_cascade_degraded_fields` 循环扫描其余 `status="found"` 的字段：① 凡含自引用（`name == fname`）或在 `evidence` 中引用了**因校验未通过被平台降级**的前置字段，一律递归降级；② 凡引用了模型自报 `not_found` 的前置字段且自身不具备其它有效真实支撑源（与核验器共用的 `has_supporting_real_source(..., self_field=fname)` 返回 `False`）的悬空衍生字段，同样递归降级为 `not_found` 直至不动点，并发出 `report_degraded` 事件。

## 相关页面

- [单智能体请求处理管道](request-pipeline.md)
- [模板模型与渲染机制](template-and-rendering.md)
- [确定性平台工具设计](deterministic-tools.md)
- [ADR-001：采用单智能体自主规划 + 强证据校验替代 Java 三 Agent 编排](../decisions/adr-001-single-agent-and-evidence.md)
- [ADR-004：采用 Jinja2 沙箱对齐 Pebble 渲染语义，并以 TrackedValue / TrackedList 精确判定报告完整度](../decisions/adr-004-jinja2-pebble-and-tracked-list.md)
