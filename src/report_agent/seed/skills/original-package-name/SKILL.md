---
name: original-package-name
title: 原套餐名称
description: 套餐变更类模板需要“原套餐名称”时加载。以 business-sms 选定的订购短信发送时间为基准，从同一天短信中取时间最接近的“退订提醒”短信，提取其中的原套餐名称。依赖 business-sms。
apis:
  - querySMSSendInfo
---

<!-- #Created By AiCoding(codex) 迁移自 Java skills/original-package-name，二期升级采用 time_diff + regex_extract -->

# 原套餐名称

## 适用场景

模板字段 `原套餐名称`（如“套餐变更争议类”：将套餐由“原套餐名称”变更为“商品名称”）。

## 依赖

- 必须先有 `订购短信` 的结论：没有时先 `load_skill("business-sms")` 完成订购短信。
- `订购短信` 为 `not_found` 时**直接跳过**：不调用接口，`原套餐名称` 提交 `not_found`，`reasoning` 写“订购短信缺失，无法确定时间基准”。

## 需要的入参

| 入参 | 要求 |
|---|---|
| 手机号码 | 必须是 11 位数字，否则不调用接口，提交 `not_found` |
| 创建时间 | 至少能取出 `yyyyMMdd` |

（本 Skill 不使用“业务名称”做筛选。）

## 查询方法

1. `date_range(time=创建时间, unit="day")` → `start`、`end`。
2. `call_api("querySMSSendInfo", {"手机号码": 手机号码, "开始时间": start, "结束时间": end})`。这与 `business-sms` 的查询参数完全相同，**直接复用 `business-sms` 的 `resultId`**，不要重复调用。
3. `count=0` → `not_found`；`ok=false` → `not_found` 并写明失败原因。

## 识别步骤

### 第 1 步：确定时间基准（订购短信那条记录）

- 基准记录 = 正文与 `订购短信` 字段值**完全相同**（两边去掉首尾空白后相等）的记录；有多条相同正文时取 `smsSendTime` 最大的一条。
- 复用 `business-sms` 的 `resultId` 时，基准记录就是 `business-sms` 选中的那一行；否则用 `query_result` 的 `equals` 条件（`column="smsContent"`，`value=订购短信原文`，`orderBy={"column":"smsSendTime","desc":true}`，`limit=1`）定位。
- 找不到基准记录，或基准记录的 `smsSendTime` 去掉非数字后不足 14 位 → `not_found`。不得改用业务名称或语义相近的短信做基准。

### 第 2 步：取候选“退订提醒”短信

```json
{
  "resultId": "<resultId>",
  "where": [{"column": "smsContent", "op": "contains", "value": "退订提醒"}],
  "limit": 100,
  "columns": ["smsContent", "smsSendTime"]
}
```

- 关键词固定为“退订提醒”（原文包含，不清洗）。**不得**使用“退订成功”或其它短信兜底。
- 去掉 `smsSendTime` 去掉非数字后不足 14 位或不是合法日期时间的候选。
- 一条候选都没有 → `not_found`。

### 第 3 步：用 `time_diff` 精确计算秒级距离（严禁手算秒差）

1. 对每条候选短信，调用确定性工具 `time_diff(time1=候选smsSendTime, time2=订购短信smsSendTime)`，获取 `{callId, ok, diffSeconds, absSeconds, later}`。
2. 按 `absSeconds` 从小到大取距离最小的一条；若多条候选 `absSeconds` 完全相同（平手），取发送时间**较晚**的一条（即 `later == "time1"` 的候选，或 `smsSendTime` 较大的一条）。
3. 在 `reasoning` 中列出每条候选的 `row`、`smsSendTime`、`time_diff` 返回的 `absSeconds` 及最终选择。

示例：基准 `20260512100002`；候选 `20260512100010`（`absSeconds=8`）与 `20260512095959`（`absSeconds=3`）→ 选 `20260512095959`。

### 第 4 步：用 `regex_extract` 从选中短信中提取原套餐名称（只看这一条，提取不到不换下一条）

按顺序调用 `regex_extract`：

1. **固定结构优先**：调用 `regex_extract(pattern=r'办理的\s*[“"]([^”"]+)[”"]', text=选中短信smsContent, group=1)`。若 `count > 0` 且 `first` 去掉首尾空白后非空，取该值（去掉首尾空白）。
2. **首对双引号回退**：仅当第 1 步 `count == 0` 时，调用 `regex_extract(pattern=r'[“"]([^”"]+)[”"]', text=选中短信smsContent, group=1)`。若 `count > 0` 且 `first` 去掉首尾空白后非空，取该值（去掉首尾空白）。
3. 只认中文双引号 `“”` 或英文双引号 `""`；单引号 `‘’`、书名号等都不算。
4. 两种都提取不到 → 提交 `not_found`（不要去试下一条候选，也不要改写或猜测名称）。

示例：`【退订提醒】您已经中断了2023年6月办理的“最近原套餐”活动。` → `regex_extract` 返回 `first="最近原套餐"`。

## 提交要求

- `原套餐名称` 为原文引用（`quote`）字段：值为提取出的名称（不是整条短信），必须逐字出现在选中候选的 `smsContent` 中。
- `evidence` 只填 `[{"type":"api","resultId":...,"row":<选中候选的row>,"column":"smsContent"}]`（在 `reasoning` 中写明基准 `订购短信` 记录以及 `time_diff`、`regex_extract` 的调用结果，不要在 `quote` 字段 `evidence` 中附加 `field` 或 `tool` 类型）。
