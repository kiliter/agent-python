---
title: Skill 详解：number-portability-sms（携号转网告知提醒短信）
type: skill
tags: [skill, sms, number-portability-sms, querySMSSendInfo]
sources:
  - src/report_agent/seed/skills/number-portability-sms/SKILL.md
  - src/report_agent/seed/apis/querySMSSendInfo.yaml
updated: 2026-11-12
---

# `number-portability-sms`：携号转网告知提醒短信

<!-- #Created By AiCoding(codex) -->

`number-portability-sms` 服务于模板 `122`（`携号转网协议冲突类`），用于核查客户在工单创建当天发送携转资格查询指令后，系统下发的“携号转网告知提醒”回复短信及其发送日期。

## 1. 基本契约

- **产出字段**（两个字段必须来自**同一条**短信记录）：
  - `携转资格回复短信`（`type: string`，`evidence: quote`，`quoteWhole: true`）
  - `发送日期`（`type: date`，默认格式 `yyyy-MM-dd`，`evidence: derive`）
- **关联接口**：`querySMSSendInfo`
- **必填入参**：`手机号码`（11 位数字）、`创建时间`（至少含 `yyyyMMdd`）；任一缺失不调接口，两个字段均提交 `not_found`。

## 2. 确定性工具执行流程

1. **查询或复用当日短信**：调用 `date_range(time=创建时间, unit="day")` 获取工单创建当天 `000000`～`235959`；若同次运行中 `business-sms` 已用完全相同参数查询过 `querySMSSendInfo`，**直接复用该 `resultId`**，无需二次请求网关。
2. **筛选固定关键词**：调用 `query_result`：
   ```json
   {
     "resultId": "<resultId>",
     "where": [{"column": "smsContent", "op": "contains", "value": "携号转网告知提醒"}],
     "orderBy": {"column": "smsSendTime", "desc": true},
     "limit": 1
   }
   ```
   - 仅按固定原文关键词 `携号转网告知提醒` 过滤（不清洗，也不按 `业务名称` 过滤，因为携转资格短信列出的是客户身上所有在途限制协议）；
   - 多条命中取 `smsSendTime` 最新一条；未命中则两字段均为 `not_found`。
3. **日期转换与证据绑定**：
   - `携转资格回复短信` 提交完整 `smsContent`，引用该行 `smsContent` 列；
   - `发送日期` 调用 `format_date(value=smsSendTime, fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd")`（或按模板字段声明的 `format`），同时附上该 `format_date` 的 `tool` 证据与同一条记录的 `smsSendTime` 列 `api` 证据。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [business-sms：订购短信](business-sms.md)
- [强证据核验机制](../architecture/evidence-system.md)
