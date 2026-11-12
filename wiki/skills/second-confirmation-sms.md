---
title: Skill 详解：second-confirmation-sms（二次确认短信）
type: skill
tags: [skill, sms, second-confirmation-sms, querySMSSendInfo]
sources:
  - src/report_agent/seed/skills/second-confirmation-sms/SKILL.md
  - src/report_agent/seed/apis/querySMSSendInfo.yaml
updated: 2026-11-12
---

# `second-confirmation-sms`：二次确认短信

<!-- #Created By AiCoding(codex) -->

`second-confirmation-sms` 用于查询客户在工单创建当天办理业务过程中收到的、要求客户回复确认的二次确认短信正文，支撑模板中“是否经过客户二次确认”合规举证段落。

## 1. 基本契约

- **产出字段**：`二次确认短信`（`type: string`，`evidence: quote`，`quoteWhole: true`）
- **关联接口**：`querySMSSendInfo`
- **必填入参**：`手机号码`（11 位）、`业务名称`、`创建时间`（至少含 `yyyyMMdd`）；缺一即提交 `not_found`。

## 2. 查询与双优先级筛选流程

1. **查询或复用当日短信**：通过 `date_range(time=创建时间, unit="day")` 获取当天起止窗口，调用 `call_api("querySMSSendInfo", ...)`；若 `business-sms` 已用完全相同参数调用过，**直接复用该 `resultId`**。
2. **第一优先级筛选（`订购确认提醒`）**：调用 `query_result`：
   ```json
   {
     "resultId": "<resultId>",
     "where": [
       {"column": "smsContent", "op": "normalizedContains", "value": "<业务名称原文>"},
       {"column": "smsContent", "op": "contains", "value": "回复"},
       {"column": "smsContent", "op": "contains", "value": "订购确认提醒"}
     ],
     "orderBy": {"column": "smsSendTime", "desc": true},
     "limit": 1
   }
   ```
3. **第二优先级兜底（`订购提醒`）**：**当且仅当第一优先级返回 `total == 0` 时**，将第 3 个条件替换为 `{"column": "smsContent", "op": "contains", "value": "订购提醒"}` 再执行一次 `query_result`。

## 3. 与 `business-sms` 的关键规则区别

- **全文匹配业务名称**：二次确认短信通常不含活动明细列表，因此 `normalizedContains` 不加 `before: "编号"`，直接在全文匹配清洗后的业务名称；
- **必须包含“回复”二字**：原文包含（不清洗）；
- **严格先后优先级**：只要当天存在任何一条含“订购确认提醒”的匹配短信，哪怕有一条含“订购提醒”的短信发送时间更晚，也必须选用“订购确认提醒”中最新的一条；
- **提交要求**：命中时原样提交 `smsContent` 全文并引用对应 `api` 记录单元格；两级均未命中时提交 `not_found`。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [business-sms：订购短信](business-sms.md)
- [verification-sms：验证码短信](verification-sms.md)
- [平台工具实现剖析](../components/platform-tools.md)
