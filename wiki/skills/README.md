---
title: 12 个纯文本业务 Skill 总览
type: overview
tags: [skill, catalog, dependencies, sms, balance, pretty-number, template-router]
sources:
  - src/report_agent/seed/skills/accept-type/SKILL.md
  - src/report_agent/seed/skills/billing-cycle-sms/SKILL.md
  - src/report_agent/seed/skills/business-sms/SKILL.md
  - src/report_agent/seed/skills/number-portability-sms/SKILL.md
  - src/report_agent/seed/skills/original-package-name/SKILL.md
  - src/report_agent/seed/skills/pretty-number-info/SKILL.md
  - src/report_agent/seed/skills/qry-balance/SKILL.md
  - src/report_agent/seed/skills/reminder-sms/SKILL.md
  - src/report_agent/seed/skills/renewal-reminder-sms/SKILL.md
  - src/report_agent/seed/skills/second-confirmation-sms/SKILL.md
  - src/report_agent/seed/skills/template-router/SKILL.md
  - src/report_agent/seed/skills/verification-sms/SKILL.md
  - tools/java_migration/MAPPING.md
updated: 2026-11-12
---

# 12 个纯文本业务 Skill 总览

<!-- #Created By AiCoding(codex) -->

`src/report_agent/seed/skills/` 内置了 **12 个纯文本业务 Skill**：其中 **11 个填报取数与派生 Skill** 供 `AgentRunner` 在填写 33 个生产申告模板时按需加载（支持 `load_skill(names=[...])` 批量加载），组合平台提供的 [12 个确定性工具](../architecture/deterministic-tools.md) 完成取数、筛选、计算与证据提交；另外 **1 个聊天路由 Skill [template-router](template-router.md)** 专供嵌入式聊天窗口的 `ChatAgent` 在选模板阶段做分流推荐。所有 Skill 均仅由一个 `SKILL.md` 文件（YAML frontmatter + Markdown 操作手册）构成，不含任何可执行脚本。

## 1. 全量 Skill 矩阵

### 1.1 填报取数与派生 Skill（11 个，挂载于模板 `skills` 白名单）

| Skill 标识 | 中文标题 | 关联网关接口 | 产出的模板字段 | 上游字段依赖 | 依赖的核心确定性工具 |
|------------|----------|--------------|----------------|--------------|----------------------|
| [business-sms](business-sms.md) | 订购短信（办理成功告知短信） | `querySMSSendInfo` | `订购短信` | — | `date_range`、`call_api`、`query_result(normalizedContains + before="编号")` |
| [accept-type](accept-type.md) | 受理渠道 | 无（纯派生） | `受理渠道` | `订购短信` | `text_contains(normalize=false)` |
| [second-confirmation-sms](second-confirmation-sms.md) | 二次确认短信 | `querySMSSendInfo` | `二次确认短信` | —（可复用当日 `resultId`） | `date_range`、`call_api`、`query_result`（两级优先级） |
| [verification-sms](verification-sms.md) | 验证码短信 | `querySMSSendInfo` | `验证码短信` | —（可复用当日 `resultId`） | `date_range`、`call_api`、`query_result` |
| [original-package-name](original-package-name.md) | 原套餐名称 | `querySMSSendInfo` | `原套餐名称` | `订购短信` | `query_result`、`time_diff`、`regex_extract` |
| [reminder-sms](reminder-sms.md) | 提醒短信与提醒日期 | `querySMSSendInfo` | `提醒短信`、`提醒日期` | `订购短信` | `extract_dates`、`date_shift`、`call_api`、`query_result`、`format_date` |
| [renewal-reminder-sms](renewal-reminder-sms.md) | 续约提醒短信 | `querySMSSendInfo` | `续约提醒类型`、`到期续约提醒时间`、`到期续约提醒短信内容`、`是否续约成功`、`续约成功提醒时间`、`续约成功提醒短信内容` | `订购短信` | `extract_dates`、`date_shift`、`regex_extract`、`call_api`、`query_result(anyOf=...)`、`format_date` |
| [number-portability-sms](number-portability-sms.md) | 携号转网告知提醒短信 | `querySMSSendInfo` | `发送日期`、`携转资格回复短信` | —（可复用当日 `resultId`） | `date_range`、`call_api`、`query_result`、`format_date` |
| [billing-cycle-sms](billing-cycle-sms.md) | 账期短信提醒列表 | `querySMSSendInfo`（逐月） | `账期短信提醒列表`（`list`，5 列） | — | `expand_period`、`call_api`、`query_result(resultIds=..., between)`、`format_date` |
| [qry-balance](qry-balance.md) | 充值流水（余额流水查询） | `BOSS_QryBalanceFlowLog`（逐账期） | `充值流水`（`list`，4 列） | — | `expand_period`、`call_api`、`query_result(resultIds=..., between, prefixLen=8)` |
| [pretty-number-info](pretty-number-info.md) | 靓号信息 | `cc_pretty_num_info_query` | `靓号等级`、`靓号活动名称`、`手机号类别` | — | `call_api`、`query_result` |

### 1.2 聊天模板路由专用 Skill（1 个，供 `ChatAgent` 加载）

| Skill 标识 | 中文标题 | 关联网关接口 | 核心输出 | 发布交叉校验规则 |
|------------|----------|--------------|----------|------------------|
| [template-router](template-router.md) | 模板路由 | 无（`apis: []`） | 指导 `ChatAgent` 输出候选模板推荐（`RecommendPick`，最多 3 项） | `validate_skill` 解析 `### <ID>` 章节，双向核验覆盖全部在线模板（`100`～`132`）且不引用下线/不存在模板；填报模板禁止挂载该 Skill |

## 2. 上下游依赖与 `resultId` 共享拓扑

```mermaid
flowchart LR
    API_SMS["querySMSSendInfo (创建当日窗口)"] --> BS["business-sms (订购短信)"]
    API_SMS --> SC["second-confirmation-sms (二次确认短信)"]
    API_SMS --> VS["verification-sms (验证码短信)"]
    API_SMS --> NP["number-portability-sms (携转回复短信+发送日期)"]
    BS --> AT["accept-type (受理渠道)"]
    BS --> OP["original-package-name (原套餐名称, 复用当日 resultId)"]
    BS --> RM["reminder-sms (提醒短信+提醒日期, 查最大到期日当天)"]
    BS --> RN["renewal-reminder-sms (6个续约字段, 查最大到期日 ±31 天)"]
```

在单智能体共享工作区机制下：
1. **同日短信零重复调用**：同一个模板往往同时挂载 `business-sms`、`accept-type`、`second-confirmation-sms`、`verification-sms`（甚至 `original-package-name` 或 `number-portability-sms`）。它们对 `querySMSSendInfo` 的查询参数均为 `{手机号码, 创建时间当天 000000 ~ 235959}`，智能体只需在第一次调用 `call_api` 后直接复用同一个 `resultId`（且对 `idempotent: true` 的契约，即使模型并发重复发起同参数 `call_api`，`Workspace` 也会自动命中缓存复用已有 `resultId`），把前代 Java 版的 4～5 次并发网关调用压缩为 **1 次**。
2. **显式字段证据链与前置 `not_found` 防护**：推导类（`derive`）下游字段（如 `受理渠道`、`提醒日期`、续约提醒类型/时间）在 `订购短信` 为 `found` 时显式附带 `{"type": "field", "name": "订购短信"}` 证据，而当 `订购短信` 为 `not_found` 时直接提交 `status="not_found"`（带默认值的字段如 `受理渠道` 由模板 `whenMissing: value` 自动输出 `"其他"`，避免引用 `not_found` 前置字段被校验打回）；若上游 `订购短信` 交卷时因证据不合规被平台降级，`_cascade_degraded_fields` 会沿依赖链全量级联保护。原文引用类（`quote`）下游字段（如 `原套餐名称`、`提醒短信`）则按 `EvidenceChecker` 契约仅在 `evidence` 中填写命中记录的 `api` 证据，并在 `reasoning` 中说明上游 `订购短信` 依据。

## 3. 与前代 Java Groovy 版的演进差异概要

1. **去脚本化**：Java 版每个 Skill 拆分为 `SKILL.md` + `assembly.groovy` + `extract.groovy`；Python 版将参数组包收敛进声明式 `apis/*.yaml`，将抽取与算术逻辑收敛进平台确定性工具，业务侧只需维护一份可读的 Markdown。
2. **列表 0 行结果精确表达**：`billing-cycle-sms` 与 `qry-balance` 在各月网关均成功但无符合条件记录时，提交 `status="found", value=[]` 并附上结果为 0 行的 `query_result(total==0)` 或 `call_api(count==0)` 的工具 `callId` 证据（严禁引用 `load_skill`），渲染为空且运行状态保持 `SUCCESS`；而任意月份接口报错则提交 `not_found` 准确标为 `PARTIAL`。
3. **历史缺陷主动修复**：二期已修复 Java Groovy 中的 `reminder-sms` 活动编号误识别日期（R2）、`qry-balance` 纯年月正则回溯丢流水（R8）以及 `pretty-number-info` 不核对号码/空等级误判靓号/多活动名无分隔符（R5），详见 [Java 行为差异与二期主动修复台账](../lint/java-divergence.md)。

## 相关页面

- [Skill 详解：template-router（聊天模板路由）](template-router.md)
- [确定性平台工具设计](../architecture/deterministic-tools.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [3 个内置网关接口契约速查](../reference/apis-catalog.md)
- [ADR-002：采用纯文本 SKILL.md + 平台确定性工具原语替代 Groovy 脚本引擎](../decisions/adr-002-text-skill-and-deterministic-tools.md)
- [Java 行为差异与二期主动修复台账](../lint/java-divergence.md)
