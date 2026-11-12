---
title: ADR-001：采用单智能体自主规划 + 强证据校验替代 Java 三 Agent 编排
type: decision
tags: [decision, adr, single-agent, evidence, architecture]
sources:
  - src/report_agent/runtime/runner.py
  - src/report_agent/runtime/evidence.py
  - src/report_agent/runtime/output_model.py
updated: 2026-11-12
---

# ADR-001：采用单智能体自主规划 + 强证据校验替代 Java 三 Agent 编排

<!-- #Created By AiCoding(codex) -->

- **状态**：已采纳（Accepted）
- **决策日期**：2026-11-12

## 1. 背景与问题

前代 Java 版（`pdf-agent-parse`）将一次申告报告生成拆分为三个独立 Agent 阶段：
1. **`PlanAgent`**：调用一次 LLM 生成拓扑分阶段计划 `ExecutionPlan`；
2. **`SkillAgent`**：按阶段为**每个 Skill 字段单独启动一个独立 ReAct 循环**；
3. **`KvAgent`**：最后再调一次 LLM 从单据文本和 `completedKv` 中抽取剩余字段，并在服务层 `IntelligentComplaintServiceImpl` 中堆叠大量硬编码善后策略（如 `removeSmsAcceptDate`、`applyAcceptDatePolicy`、`resolveKvSourceText`、`applyTerminalInfoPolicy`）。

该设计在实际运行中暴露出三个结构性痛点：
- **重复网关与 Token 开销大**：一个常见模板挂载 `business-sms`、`second-confirmation-sms`、`verification-sms` 等 4 个同日短信 Skill 时，4 个互不感知的 `SkillAgent` 会对同一手机号同一天重复发起 4 次网关调用与 4 套 LLM 对话；
- **跨阶段上下文割裂**：`KvAgent` 看不到 `SkillAgent` 的原始候选集，当单据不包含本次业务名称需回退读取订购短信时，只能靠服务层硬编码字符串拼接特判；
- **缺乏通用防幻觉校验**：`KvAgent` 直接输出 `Map<String, String>`，无法核验某个单据字段究竟是原文真有还是模型脑补，也无法向工作台提供点击跳转定位到具体单据行或接口单元格的证据链。

## 2. 决策内容

在 `agent-python` 中彻底取消多 Agent 拆分与服务层业务硬编码，改为 **“单智能体共享工作区（`AgentRunner` + `Workspace`）+ 动态严格 Schema 交卷（`submit_report`）+ 强证据核验与级联降级（`EvidenceChecker`）”**：

1. 全程由单个 Pydantic AI `Agent` 自主阅读字段规格、按需调用 `load_skill` 并共享同一个 `Workspace` 中的 `resultId`（同日短信只需调用 1 次网关）；
2. 所有业务兜底规则（如“单据无本次业务时从订购短信提取”“受理渠道决定受理日期来源”）统一写入系统提示词与对应字段 `description`，平台代码保持零业务特判；
3. 交卷时由 `@agent.output_validator` 对每个字段强制执行 `quote` / `input` / `derive` 证据核验：不合规时精确退回违规字段重填，重试耗尽后执行单点降级（`_salvage_partial_report`）与沿 `field` 依赖链的级联降级（`_cascade_degraded_fields`）。

## 3. 后果与权衡

- **正面收益**：
  - 单次工单的模型请求轮次与外部网关调用次数显著下降，响应延迟更低；
  - 实现了 100% 字段级可追溯（工作台支持一键高亮接口记录行/列与单据行号），彻底拦截逐字引用类字段的模型幻觉；
  - 平台内核干净纯粹，新增任何新业务品类模板都无需改动 Python 代码。
- **代价与应对**：
  - 单次上下文需容纳多个字段的定义，当模板字段极多（如模板 119 含 29 个字段）时对模型的指令遵循与结构化输出能力要求更高；通过“渐进式 Skill 目录披露（只按需加载）”+“网关响应预览截断（`query_result` 按需取行）”+“`ModelRetry` 精准纠错”有效控制了上下文规模与准确率。

## 相关页面

- [项目总览](../overview.md)
- [单智能体请求处理管道](../architecture/request-pipeline.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [ADR-002：采用纯文本 SKILL.md + 平台确定性工具原语替代 Groovy 脚本引擎](adr-002-text-skill-and-deterministic-tools.md)
