---
title: Skill 详解：business-sms（订购短信）
type: skill
tags: [skill, sms, business-sms, querySMSSendInfo]
sources:
  - src/report_agent/seed/skills/business-sms/SKILL.md
  - src/report_agent/seed/apis/querySMSSendInfo.yaml
updated: 2026-11-12
---

# `business-sms`：订购短信（办理成功告知短信）

<!-- #Created By AiCoding(codex) -->

`business-sms` 是平台被引用最广泛的基础核心 Skill（覆盖 31 个生产模板）：既负责直接产出模板字段 `订购短信`，又是 `accept-type`、`original-package-name`、`reminder-sms`、`renewal-reminder-sms` 四个下游 Skill 的必经上游，同时在单据缺失或不含本次业务名称时充当单据抽取的兜底文本源。

## 1. 基本契约

- **产出字段**：`订购短信`（`type: string`，`evidence: quote`，`quoteWhole: true`）
- **关联接口**：`querySMSSendInfo`
- **必填入参**：`手机号码`（11 位）、`业务名称`（不得用业务编码替代）、`创建时间`（至少含 `yyyyMMdd`）；任一缺失时不调接口，直接提交 `not_found`。

## 2. 确定性工具执行流程

1. **计算当日窗口**：调用 `date_range(time=创建时间, unit="day")`，得到工单创建当天的 `start`（`yyyyMMdd000000`）与 `end`（`yyyyMMdd235959`）。
2. **调用或复用短信接口**：调用 `call_api("querySMSSendInfo", {"手机号码": 手机号码, "开始时间": start, "结束时间": end})`（同次运行已有相同参数 `resultId` 时直接复用）。
   - `ok=true` 且 `count=0`（含网关返回“无短信记录”）或 `ok=false` → 提交 `not_found`。
3. **结构化筛选（严禁目测）**：调用 `query_result`：
   ```json
   {
     "resultId": "<resultId>",
     "where": [
       {"column": "smsContent", "op": "normalizedContains", "value": "<业务名称原文>", "before": "编号"},
       {"column": "smsContent", "op": "notContains", "value": "退订提醒"},
       {"column": "smsContent", "op": "notContains", "value": "退订成功"}
     ],
     "orderBy": {"column": "smsSendTime", "desc": true},
     "limit": 1
   }
   ```

## 3. 关键业务边界

- **严格限定在第一个“编号”之前匹配**：很多营销活动短信正文下半部分会罗列“1. 业务A；2. 业务B”，若全文匹配极易把其他活动的短信误判为本次订购短信。`before: "编号"` 保证只在存在“编号”时截取头部比对（无“编号”时比对全文），头部未命中绝不回退全文。
- **标点无关清洗**：`normalizedContains` 自动对短信头部与入参 `业务名称` 执行 NFKC + 去标点归一化（例如全角括号 `（个人版）` 与半角 `(个人版)` 视为一致）。
- **整条原文提交**：命中后原样提交 `smsContent` 完整原文（含换行），证据为 `{"type": "api", "resultId": ..., "row": ..., "column": "smsContent"}`。
- **绝不副产“受理日期”**：前代 Java Groovy 脚本曾顺带输出短信日期作为受理日期，随即被服务层 `removeSmsAcceptDate` 删掉。Python 版明确规定本 Skill 只负责 `订购短信`，任何情况下不得用短信发送时间去填 `受理日期`。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [accept-type：受理渠道](accept-type.md)
- [original-package-name：原套餐名称](original-package-name.md)
- [reminder-sms：提醒短信与提醒日期](reminder-sms.md)
- [renewal-reminder-sms：续约提醒短信](renewal-reminder-sms.md)
