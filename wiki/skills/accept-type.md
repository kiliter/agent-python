---
title: Skill 详解：accept-type（受理渠道）
type: skill
tags: [skill, accept-type, channel, derive]
sources:
  - src/report_agent/seed/skills/accept-type/SKILL.md
updated: 2026-11-12
---

# `accept-type`：受理渠道

<!-- #Created By AiCoding(codex) -->

`accept-type` 根据已查出的 `订购短信` 正文关键词判定业务办理渠道，是模板正文中决定“线上/热线免签单段落”还是“线下营业厅电子协议单段落”以及决定 `受理日期` 取值规则的核心分流开关。

## 1. 基本契约

- **产出字段**：`受理渠道`（`type: enum`，枚举值 `["热线", "掌上营业厅", "其他"]`，`evidence: derive`，`whenMissing: value`，`defaultValue: "其他"`；在模板 131、132 中作为 `visible: false` 的中间字段驱动条件分支）
- **关联接口**：无（`apis: []`，纯上游字段派生，不发起任何网关请求）
- **上游依赖**：字段 `订购短信`（若尚未得出结论，必须先加载并执行 [business-sms](business-sms.md)）

## 2. 判定优先级与工具辅助

仅针对 `business-sms` 选定的**那唯一一条** `订购短信` 原文做不清洗的精确子串判断（可调用 `text_contains(target=关键词, text=订购短信原文, normalize=false)` 辅助核验），按固定顺序命中即停：

| 顺序 | `订购短信` 原文条件 | `受理渠道` 提交结果与渲染结论 |
|------|---------------------|-------------------------------|
| 1 | 包含 `热线渠道` | `status="found"`, `value="热线"` |
| 2 | 包含 `线上渠道` | `status="found"`, `value="掌上营业厅"` |
| 3 | 以上均不包含 | `status="found"`, `value="其他"` |
| — | 上游 `订购短信` 为 `not_found`（未查到、网关失败或入参缺失） | 提交 `status="not_found", value=null`（由模板 `whenMissing: value, defaultValue: "其他"` 自动输出 `"其他"`） |

> 注意：`热线渠道` 优先级高于 `线上渠道`；绝不可去非订购短信的其它短信记录中寻找渠道词。

## 3. 证据提交要求

- **当 `订购短信` 为 `found` 时**：提交 `status="found"`，在 `evidence` 中同时附上 `{"type": "field", "name": "订购短信"}` 以及该条订购短信记录 `{"type": "api", "resultId": ..., "row": ..., "column": "smsContent"}`（若调用了 `text_contains` 可附加其 `callId`）；
- **当 `订购短信` 为 `not_found` 时**：直接提交 `status="not_found", value=null`（`evidence: []`），严禁将 `not_found` 的前置字段作为 `found` 结论的唯一证据提交（否则会被 `EvidenceChecker` 拦截）。模板字段配置的 `whenMissing: value, defaultValue: "其他"` 保证报告依然稳定按 `"其他"` 分支渲染且不会误标 `PARTIAL`；若上游 `订购短信` 交卷时因证据校验不合规被系统降级，`_cascade_degraded_fields` 也会沿 `field` 证据自动级联降级。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [business-sms：订购短信](business-sms.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [33 个生产模板完整清单](../reference/templates-catalog.md)
