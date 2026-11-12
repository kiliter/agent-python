---
name: number-portability-sms
title: 携号转网告知提醒短信
description: 携号转网协议冲突类模板需要“发送日期”或“携转资格回复短信”时加载。查询创建时间当天的“携号转网告知提醒”短信，两个字段来自同一条记录，只查询一次。
apis:
  - querySMSSendInfo
---

<!-- #Created By AiCoding(codex) 迁移自 Java skills/number-portability-sms（SKILL.md + scripts/assembly.groovy + scripts/extract.groovy） -->

# 携号转网告知提醒短信

## 适用场景

模板字段 `发送日期`、`携转资格回复短信`（“客户号码于{{发送日期}}发送短信查询携转资格，我公司已回复短信告知：{{携转资格回复短信}}”）。两个字段**必须来自同一条短信记录**。

## 需要的入参

| 入参 | 要求 |
|---|---|
| 手机号码 | 必须是 11 位数字 |
| 创建时间 | 至少能取出 `yyyyMMdd` |

任一缺失或手机号不是 11 位数字时不要调用接口，两个字段提交 not_found。

## 查询方法

1. `date_range(time=创建时间, unit="day")` → `start`、`end`（当天 `000000` ～ `235959`）。
2. `call_api("querySMSSendInfo", {"手机号码": 手机号码, "开始时间": start, "结束时间": end})`；本次运行已用相同参数查过时直接复用 `resultId`。
3. `count=0`（含“无短信记录”）→ 两个字段 not_found；`ok=false` → not_found 并写明失败原因。

## 识别规则

```json
{
  "resultId": "<resultId>",
  "where": [{"column": "smsContent", "op": "contains", "value": "携号转网告知提醒"}],
  "orderBy": {"column": "smsSendTime", "desc": true},
  "limit": 1
}
```

- 关键词固定为“携号转网告知提醒”（原文包含，不清洗，不按业务名称过滤）；不得返回不含该关键词的普通短信。
- 多条命中时按 `smsSendTime` 倒序取第一条。没有命中 → 两个字段 not_found。

## 提交要求

- `携转资格回复短信`：选中记录 `smsContent` 完整原文；证据 `{"type":"api","resultId":...,"row":...,"column":"smsContent"}`。
- `发送日期`：同一条记录的 `smsSendTime` 用 `format_date(value=smsSendTime, fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd")` 转换（模板字段另行定义了展示格式时按模板格式），直接使用工具输出；证据为该 `format_date` 的 callId 加同一条记录的 `smsSendTime` 列。
