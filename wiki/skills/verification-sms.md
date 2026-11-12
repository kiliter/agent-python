---
title: Skill 详解：verification-sms（验证码短信）
type: skill
tags: [skill, sms, verification-sms, querySMSSendInfo]
sources:
  - src/report_agent/seed/skills/verification-sms/SKILL.md
  - src/report_agent/seed/apis/querySMSSendInfo.yaml
updated: 2026-11-12
---

# `verification-sms`：验证码短信

<!-- #Created By AiCoding(codex) -->

`verification-sms` 用于查询客户在工单创建当天办理业务时收到的动态验证码短信正文，用于核实线上或营业厅办理环节是否经过了本机动态口令校验。

## 1. 基本契约

- **产出字段**：`验证码短信`（`type: string`，`evidence: quote`，`quoteWhole: true`）
- **关联接口**：`querySMSSendInfo`
- **必填入参**：`手机号码`（11 位）、`业务名称`、`创建时间`（至少含 `yyyyMMdd`）；任一缺失不调接口，直接提交 `not_found`。

## 2. 确定性工具执行流程

1. **查询或复用当日短信**：调用 `date_range(time=创建时间, unit="day")` 获取当天 `000000`～`235959`，若本次运行已用相同参数查过 `querySMSSendInfo` 则直接复用 `resultId`，否则调用 `call_api`。
2. **结构化筛选**：对 `resultId` 调用 `query_result`：
   ```json
   {
     "resultId": "<resultId>",
     "where": [
       {"column": "smsContent", "op": "normalizedContains", "value": "<业务名称原文>"},
       {"column": "smsContent", "op": "contains", "value": "动态验证码"}
     ],
     "orderBy": {"column": "smsSendTime", "desc": true},
     "limit": 1
   }
   ```

## 3. 关键判定边界

- **固定关键词 `动态验证码`**：原文精确包含判断，仅含“验证码”或“短信验证码”但不含“动态验证码”的登录类短信一律不命中（与前代 Java 规则严格一致）；
- **全文匹配清洗后的业务名称**：使用 `normalizedContains` 在全文匹配入参 `业务名称`；
- **证据提交**：命中记录按 `smsSendTime` 倒序取最新一条，原样提交完整 `smsContent`，附带 `{"type": "api", "resultId": ..., "row": ..., "column": "smsContent"}`；未命中提交 `not_found`。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [business-sms：订购短信](business-sms.md)
- [second-confirmation-sms：二次确认短信](second-confirmation-sms.md)
- [强证据核验机制](../architecture/evidence-system.md)
