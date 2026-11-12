---
name: verification-sms
title: 验证码短信
description: 模板需要“验证码短信”（客户办理业务时收到的动态验证码短信正文）时加载。
apis:
  - querySMSSendInfo
---

<!-- #Created By AiCoding(codex) 迁移自 Java skills/verification-sms（SKILL.md + scripts/assembly.groovy + scripts/extract.groovy） -->

# 验证码短信

## 适用场景

模板字段 `验证码短信`。

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

```json
{
  "resultId": "<resultId>",
  "where": [
    {"column": "smsContent", "op": "normalizedContains", "value": "<入参业务名称原文>"},
    {"column": "smsContent", "op": "contains", "value": "动态验证码"}
  ],
  "orderBy": {"column": "smsSendTime", "desc": true},
  "limit": 1
}
```

1. 业务名称在**全文**中比较，两边按 `normalize_text` 规则清洗后包含（`normalizedContains`）。
2. 原文必须包含“动态验证码”（原文比较，不清洗；“验证码”“短信验证码”等其它写法不算）。
3. 多条命中时按 `smsSendTime` 倒序取第一条。

## 提交要求

- 值为命中记录 `smsContent` 的完整原文；证据 `{"type":"api","resultId":...,"row":...,"column":"smsContent"}`。
- 没有命中时提交 not_found，写明筛选条件和候选数量。
