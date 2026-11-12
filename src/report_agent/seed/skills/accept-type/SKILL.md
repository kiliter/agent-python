---
name: accept-type
title: 受理渠道
description: 模板需要“受理渠道”（热线 / 掌上营业厅 / 其他）时加载。受理渠道由订购短信正文中的关键词判定，不单独调用接口，依赖 business-sms。
apis: []
---

<!-- #Created By AiCoding(codex) 迁移自 Java skills/accept-type（SKILL.md + scripts/extract.groovy，dependencies: business-sms） -->

# 受理渠道

## 适用场景

模板字段 `受理渠道`（取值只能是 `热线`、`掌上营业厅`、`其他`）。

## 依赖

本字段完全由 `订购短信` 派生，**不调用任何接口**：

1. 如果 `订购短信` 还没有结论，先 `load_skill("business-sms")` 并按其方法得到订购短信。
2. 只看 business-sms 选定的那**一条**订购短信，不要在其它短信里找渠道关键词。

## 判定规则（按顺序，命中即停止）

对订购短信 `smsContent` 原文做**原文包含**判断（不清洗；可用 `text_contains(target=关键词, text=订购短信原文, normalize=false)` 辅助）：

| 顺序 | 订购短信正文包含 | 受理渠道 |
|---|---|---|
| 1 | `热线渠道` | 热线 |
| 2 | `线上渠道` | 掌上营业厅 |
| 3 | 都不包含 | 其他 |
| — | 订购短信为 not_found（没查到、接口失败、入参缺失） | 其他 |

注意：先判断“热线渠道”，两者都包含时结果是“热线”。

## 提交要求

- **当 `订购短信` 为 `found` 时**：提交 `status="found"`，值为 `"热线"`、`"掌上营业厅"` 或 `"其他"`；`evidence` 引用 `{"type":"field","name":"订购短信"}` 及订购短信对应的记录 `{"type":"api","resultId":...,"row":...,"column":"smsContent"}`（用了 `text_contains` 时一并加 `{"type":"tool","callId":...}`），`reasoning` 写明命中的渠道关键词或未含渠道关键词。
- **当 `订购短信` 为 `not_found`（未查到、接口失败、入参缺失）时**：提交 `status="not_found"`、`value=null`，`reasoning` 写明“订购短信未找到，由模板默认值按其他处理”（严禁引用状态为 `not_found` 的前置字段作为 `found` 证据；模板已配置 `whenMissing: value, defaultValue: "其他"`，会自动输出 `"其他"`）。
