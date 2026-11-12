---
name: renewal-reminder-sms
title: 续约提醒短信
description: 合约延续类模板需要“续约提醒类型”“到期续约提醒时间”“到期续约提醒短信内容”“是否续约成功”“续约成功提醒时间”“续约成功提醒短信内容”任一字段时加载。按订购短信中的最大合法日期查询前后 31 天短信，一次识别到期续约/到期结束提醒和续约成功提醒。依赖 business-sms。
apis:
  - querySMSSendInfo
---

<!-- #Created By AiCoding(codex) 迁移自 Java skills/renewal-reminder-sms，二期升级采用 extract_dates + date_shift + regex_extract + query_result(anyOf) -->

# 续约提醒短信

## 适用场景

一次查询同时填写以下 6 个字段（只查询一次，不要拆成多次接口调用）：

| 字段 | 含义 |
|---|---|
| 续约提醒类型 | 只能是 `到期延续` 或 `到期结束` |
| 到期续约提醒时间 | 提醒短信发送日期 `yyyy-MM-dd` |
| 到期续约提醒短信内容 | 提醒短信原文 |
| 是否续约成功 | 找到续约成功提醒时为 `是`；**找不到时不得填“否”**，提交 `not_found` |
| 续约成功提醒时间 | 续约成功提醒发送日期 `yyyy-MM-dd` |
| 续约成功提醒短信内容 | 续约成功提醒原文 |

## 依赖与入参

| 来源 | 要求 |
|---|---|
| 字段 `订购短信` | 必须先有结论（没有时先 `load_skill("business-sms")`）；为 `not_found` 时**跳过**，6 个字段全部 `not_found` |
| 入参 手机号码 | 必须是 11 位数字，否则不调用接口，6 个字段 `not_found` |
| 入参 业务名称 | 用于匹配短信（可为空，为空时只用活动编号匹配） |
| 入参 创建时间 | 给“M月d日”这类不带年份的日期补年份 |
| 入参 deadlineDate（或模板定义的截止日期入参，可选） | 模板提供且非空时一并提取日期参与取最大值 |

## 第 1 步：用 `extract_dates` 确定到期基准日

1. 调用 `extract_dates(text=订购短信, defaultYear=创建时间)` 提取订购短信中全部经日历校验的合法日期（若入参还传入了非空 `deadlineDate`，一并调用 `extract_dates(text=deadlineDate, defaultYear=创建时间)` 后取两者的最大 `yyyyMMdd`）。
2. 若没有任何合法日期（`count == 0`）→ 跳过查询，6 个字段提交 `not_found`，`reasoning` 写“订购短信中未找到合法日期”。
3. 取最大合法日期 `max` 作为到期基准日 `max_date`（8 位 `yyyyMMdd`）。

示例：`测试活动（编号：25JS204106），2026年8月1日到2028年8月1日。` → `extract_dates` 返回 `["20260801", "20280801"]`，`max = "20280801"`。

## 第 2 步：用 `date_shift` 计算前后 31 天窗口并查询

1. 调用 `date_shift(date=max_date, days=-31, endDays=31)`，直接使用返回的 `start`（基准日前 31 天 `000000`）和 `end`（基准日后 31 天 `235959`），不要手算跨月或闰年日期。
   - 例：`max_date="20280801"` → `start="20280701000000"`，`end="20280901235959"`。
2. 调用 `call_api("querySMSSendInfo", {"手机号码": 手机号码, "开始时间": start, "结束时间": end})`。
3. `count=0`（含“无短信记录”）→ 6 个字段 `not_found`；`ok=false` → 6 个字段 `not_found` 并写明失败原因（不得当作无短信）。

## 第 3 步：用 `regex_extract` 提取活动编号并用 `query_result(anyOf=...)` 一步筛选

1. 调用 `regex_extract(pattern=r"[（(]编号[:：]\s*([A-Za-z0-9_-]+)[）)]", text=订购短信)` 提取全部活动编号（`matches` 列表；若订购短信中的“编号”未带括号，可用 `r"编号\s*[:：]?\s*([A-Za-z0-9_-]+)"` 提取）。
2. 构造 `anyOf` 或条件列表（满足任一即属于本次业务）：
   - 若入参 `业务名称` 非空：`{"column": "smsContent", "op": "normalizedContains", "value": "<业务名称>"}`；
   - 对提取到的每个活动编号：`{"column": "smsContent", "op": "normalizedContains", "value": "<活动编号>"}`。
   - 若 `业务名称` 为空且未提取到任何活动编号 → 6 个字段全部 `not_found`。
3. 一次调用 `query_result` 筛出属于本次业务的全部短信并按发送时间倒序排列（无需分多次查询手工合并）：

```json
{
  "resultId": "<resultId>",
  "anyOf": [
    {"column": "smsContent", "op": "normalizedContains", "value": "<业务名称>"},
    {"column": "smsContent", "op": "normalizedContains", "value": "<活动编号1>"}
  ],
  "orderBy": {"column": "smsSendTime", "desc": true},
  "limit": 100
}
```

## 第 4 步：识别

在第 3 步返回的 `rows`（已按 `smsSendTime` 倒序）中识别两类提醒（关键词均为原文包含判断，不清洗，可用 `text_contains(normalize=false)` 核对）：

**A. 续约成功提醒**：正文原文包含 `【续约成功提醒】` 或 `[续约成功提醒]` 的短信，取 `rows` 中第一条（即 `smsSendTime` 最新一条）。

**B. 到期提醒**：对 `rows` 中每条短信按顺序判定类型：
1. 正文包含 `【续约确认提醒】` 或 `[续约确认提醒]` → `到期延续`（正文中“如回复取消…不再享受”之类的条件性说明不影响判定）。
2. 否则正文包含 `【到期提醒】` 或 `[到期提醒]` 时：
   - 包含任一结束词 `次月起失效`、`到期自动关闭`、`活动结束后自动失效`、`到期后自动失效`、`不再延续` → `到期结束`（结束词优先）；
   - 否则包含任一延续词 `下月继续生效`、`继续生效`、`自动延续`、`自动续订`、`自动续展` → `到期延续`；
   - 都不包含 → 不是候选。
3. 其它短信不是候选。

取所有有类型的候选中排序最靠前的一条（即 `smsSendTime` 最新一条）。

## 提交要求

- 有到期提醒（B）时：
  - `续约提醒类型` = 该条的类型；
  - `到期续约提醒时间` = `format_date(value=smsSendTime, fromPattern="yyyyMMddHHmmss", toPattern="yyyy-MM-dd")` 的输出；
  - `到期续约提醒短信内容` = 该条 `smsContent` 原文。
- 有续约成功提醒（A）时：
  - `续约提醒类型` **改为** `到期延续`（续约成功是最终证据，覆盖 B 的判定；即使没有 B 也填 `到期延续`）；
  - `是否续约成功` = `是`；
  - `续约成功提醒时间` = 该条 `smsSendTime` 经 `format_date` 转成 `yyyy-MM-dd`；
  - `续约成功提醒短信内容` = 该条 `smsContent` 原文。
- 没有 A：`是否续约成功`、`续约成功提醒时间`、`续约成功提醒短信内容` 提交 `not_found`（**不得**推断为“否”）。
- 既没有 A 也没有 B：6 个字段全部 `not_found`。
- 证据要求：
  - 原文引用字段（`到期续约提醒短信内容`、`续约成功提醒短信内容`）：`evidence` 仅填对应记录 `[{"type":"api","resultId":...,"row":...,"column":"smsContent"}]`；
  - 时间推导字段（`到期续约提醒时间`、`续约成功提醒时间`）：`evidence` 引用对应 `format_date` 的 `{"type":"tool","callId":...}`、对应记录 `smsSendTime` 列及 `{"type":"field","name":"订购短信"}`；
  - 枚举推导字段（`续约提醒类型`、`是否续约成功`）：`evidence` 引用对应记录 `smsContent` 列、相关工具 `callId`（`extract_dates`、`date_shift`、`regex_extract`、`query_result`）及 `{"type":"field","name":"订购短信"}`，在 `reasoning` 中写明命中的关键词。
