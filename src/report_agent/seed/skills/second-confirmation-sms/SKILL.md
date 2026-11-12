---
name: second-confirmation-sms
title: 二次确认短信
description: 模板需要“二次确认短信”（客户办理业务时收到、需要回复确认的短信正文）时加载。
apis:
  - querySMSSendInfo
---

<!-- #Created By AiCoding(codex) 迁移自 Java skills/second-confirmation-sms（SKILL.md + scripts/assembly.groovy + scripts/extract.groovy） -->

# 二次确认短信

## 适用场景

模板字段 `二次确认短信`。

## 需要的入参

| 入参 | 要求 |
|---|---|
| 手机号码 | 11 位手机号 |
| 业务名称 | 只用入参“业务名称”，不要用业务编码 |
| 创建时间 | 至少能取出 `yyyyMMdd` |

任何一项缺失时不要调用接口，字段提交 not_found。

## 查询方法

与 `business-sms` 完全相同（同一接口、同一天窗口）：

1. `date_range(time=创建时间, unit="day")` → `start`、`end`。
2. `call_api("querySMSSendInfo", {"手机号码": 手机号码, "开始时间": start, "结束时间": end})`；本次运行已用相同参数查过时直接复用 `resultId`。
3. `count=0`（含“无短信记录”）→ not_found；`ok=false` → not_found 并写明失败原因。

## 识别规则（必须用 query_result 执行）

**第一优先级：订购确认提醒**

```json
{
  "resultId": "<resultId>",
  "where": [
    {"column": "smsContent", "op": "normalizedContains", "value": "<入参业务名称原文>"},
    {"column": "smsContent", "op": "contains", "value": "回复"},
    {"column": "smsContent", "op": "contains", "value": "订购确认提醒"}
  ],
  "orderBy": {"column": "smsSendTime", "desc": true},
  "limit": 1
}
```

**只有第一优先级 `total=0` 时**，才执行第二优先级（把第三个条件换成 `订购提醒`）：

```json
{"column": "smsContent", "op": "contains", "value": "订购提醒"}
```

规则说明（与 Java 一致）：

1. 业务名称在**全文**中比较（不截取“编号”之前），两边按 `normalize_text` 规则清洗后包含即可（`normalizedContains`）。
2. 原文必须包含“回复”（原文比较，不清洗）。
3. 优先级：只要存在包含“订购确认提醒”的候选，就只在这些候选中取最新一条；一条都没有时，才在包含“订购提醒”的候选中取最新一条。
4. 同一优先级多条时按 `smsSendTime` 倒序取第一条。
5. 不排除退订类短信（Java 没有这条规则，不要自行添加）。

## 提交要求

- 值为命中记录 `smsContent` 的完整原文；证据 `{"type":"api","resultId":...,"row":...,"column":"smsContent"}`。
- 两个优先级都没有命中时提交 not_found，写明两次筛选的条件和结果数，不得改选其它短信。
