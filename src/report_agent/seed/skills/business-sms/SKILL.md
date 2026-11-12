---
name: business-sms
title: 订购短信（办理成功告知短信）
description: 模板需要“订购短信”（客户办理业务、活动、套餐后收到的办理成功告知短信正文）时加载；受理渠道、原套餐名称、提醒短信、续约提醒等字段也以它为上游，需要这些字段时同样先加载本 Skill。
apis:
  - querySMSSendInfo
---

<!-- #Created By AiCoding(codex) 迁移自 Java skills/business-sms（SKILL.md + scripts/assembly.groovy + scripts/extract.groovy） -->

# 订购短信

## 适用场景

- 模板字段 `订购短信`。
- 下游 Skill 的上游：`accept-type`（受理渠道）、`original-package-name`（原套餐名称）、`reminder-sms`（提醒短信/提醒日期）、`renewal-reminder-sms`（续约提醒）。其中推导类（`derive`）下游字段通过字段证据 `{"type":"field","name":"订购短信"}` 引用本字段结论；原文引用类（`quote`）下游字段在 `evidence` 中只填命中记录的 `api` 证据，并在 `reasoning` 中说明上游 `订购短信` 依据。

## 需要的入参

| 入参 | 要求 |
|---|---|
| 手机号码 | 11 位手机号 |
| 业务名称 | 只用入参“业务名称”，不要用业务编码 |
| 创建时间 | 工单创建时间，通常为 `yyyyMMddHHmmss`，至少要能取出 `yyyyMMdd` |

任何一项缺失或为空时**不要调用接口**，`订购短信` 提交 not_found，reasoning 写明缺少哪个入参。

## 查询方法

1. 调用 `date_range(time=创建时间, unit="day")`，得到创建时间当天的 `start`（`yyyyMMdd000000`）和 `end`（`yyyyMMdd235959`）。
2. 调用 `call_api("querySMSSendInfo", {"手机号码": 手机号码, "开始时间": start, "结束时间": end})`。
   - 同一次运行中如果已经用**完全相同的三个参数**调用过 `querySMSSendInfo`（例如其它短信类 Skill 已查过当天短信），直接复用那次的 `resultId`，不要重复调用。
3. 结果判断：
   - `ok=true` 且 `count=0`（包括接口返回“无短信记录”）：当天没有短信，`订购短信` 提交 not_found。
   - `ok=false`：如实按 not_found 提交并写明接口失败原因，不得猜测短信内容。

## 识别规则（必须用 query_result 执行，不要目测）

对上一步的 `resultId` 调用一次 `query_result`：

```json
{
  "resultId": "<resultId>",
  "where": [
    {"column": "smsContent", "op": "normalizedContains", "value": "<入参业务名称原文>", "before": "编号"},
    {"column": "smsContent", "op": "notContains", "value": "退订提醒"},
    {"column": "smsContent", "op": "notContains", "value": "退订成功"}
  ],
  "orderBy": {"column": "smsSendTime", "desc": true},
  "limit": 1
}
```

规则说明（与 Java 完全一致，任何一条都不能省略或放宽）：

1. **只比较第一个“编号”之前的部分**：短信中出现“编号”时，只用第一个“编号”之前的头部与业务名称比较；没有“编号”的短信用全文。头部没有命中时**不得**再用全文兜底（活动正文中的“业务1”“业务2”明细名称会造成误配）。
2. 比较前两边都按 `normalize_text` 规则清洗（NFKC 归一化 + 删除固定中英文标点），清洗后的短信头部必须**包含**清洗后的业务名称；`normalizedContains` 已经做了这一步，`value` 直接传入参原文。
3. 排除**全文**包含“退订提醒”或“退订成功”的短信（原文比较，不清洗）。
4. 多条命中时按 `smsSendTime` 倒序取第一条（发送时间相同则保留接口返回顺序中靠前的一条，`query_result` 的排序已保证）。

## 提交要求

- `订购短信`：值为命中记录 `smsContent` 列的**完整原文**（含换行，不得删改、截断或补标点）；证据 `{"type":"api","resultId":"<resultId>","row":<row>,"column":"smsContent"}`。
- 没有命中时提交 not_found，reasoning 写明筛选条件和当天短信总数，不得退而求其次选一条不符合规则的短信。
- 记住命中记录的 `resultId`、`row` 和 `smsSendTime`，下游 Skill（原套餐名称等）要用到。

## 不负责的内容

- Java 的 extract 会同时输出由 `smsSendTime` 转换的“受理日期”（`yyyy-MM-dd`），但服务层 `removeSmsAcceptDate` 会**丢弃**这个副产物。**本 Skill 不产出受理日期，任何情况下都不得用短信发送时间填写受理日期**；受理日期的来源规则见模板字段说明（热线/掌上营业厅取入参“业务月份”，其他渠道只取属于本次业务的单据）。
