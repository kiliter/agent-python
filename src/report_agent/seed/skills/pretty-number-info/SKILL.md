---
name: pretty-number-info
title: 靓号信息
description: 模板需要“靓号等级”“靓号活动名称”“手机号类别”（靓号/非靓号）任一字段时加载。一次查询靓号接口并按手机号码精确匹配，同时得到三个字段。
apis:
  - cc_pretty_num_info_query
---

<!-- #Created By AiCoding(codex) 迁移自 Java skills/pretty-number-info，二期修复号码精确匹配、空 grade 判非靓号及多档活动名称拼接 -->

# 靓号信息

## 适用场景

| 字段 | 取值 |
|---|---|
| 靓号等级 | 匹配记录 `grade` 原值（如 `GRADE_002`），不做翻译、格式化或加前后缀；非靓号时为空 |
| 靓号活动名称 | 匹配记录 `level_info.event_name` 中的非空活动名称（单值原样取用；多档 JSON 数组文本按 `、` 拼接），不做其它改写；非靓号或活动名称为空时为空 |
| 手机号类别 | `靓号` 或 `非靓号`（模板据此 `{% if 手机号类别 == "靓号" %}` 选择段落） |

## 需要的入参

- `手机号码`：直接使用入参 `手机号码`（**不读取名为“客户号码”的入参**）；必须恰好是 11 位数字（不做补全或猜测）。

不满足时不要调用接口：三个字段按“非靓号”的方式处理（见提交要求），`reasoning` 写明缺少有效 11 位手机号码。

## 查询方法

调用 `call_api("cc_pretty_num_info_query", {"手机号码": 手机号码})`，一次调用三个字段共用，不要重复调用。

| 接口结果 | 含义 |
|---|---|
| `ok=true`、`count≥1` | 进入下方“识别规则”，按 `msisdn == 手机号码` 与 `grade` 非空判定 |
| `ok=true`、`count=0`（`ret_code=1` 号码不存在，或无 `msisdn_list`） | 非靓号 |
| `ok=false`（`ret_code` 为 0、1 以外的值、HTTP 失败等） | 在 `reasoning` 写明失败原因，三个字段提交 `not_found`（由模板缺省值输出 `非靓号` 与空字符串） |

## 识别规则（`ok=true` 且 `count≥1` 时）

1. 用 `query_result` 按当前 `手机号码` 精确过滤记录（**不得**跳过号码核对直接取首条）：

```json
{
  "resultId": "<resultId>",
  "where": [{"column": "msisdn", "op": "equals", "value": "<11位手机号码>"}],
  "limit": 100
}
```

2. 判断是否为靓号：
   - 若 `total == 0`（无匹配当前 `手机号码` 的记录），或第一条匹配记录的 `grade` 列为空（空字符串/`null`）→ **按非靓号处理**（即使接口返回了记录，只要 `grade` 为空也不得判为“靓号”）。
   - 若匹配记录存在且 `grade` 非空 → **判为靓号**（取第一条匹配且 `grade` 非空的记录）：
     - `手机号类别` = `"靓号"`；
     - `靓号等级` = 该记录 `grade` 列原值；
     - `靓号活动名称` = 读取该记录 `level_info.event_name` 列：
       - 若为普通非空字符串（如 `"靓号低消活动A"`），原样取该字符串；
       - 若因多档 `level_info` 返回 JSON 数组文本（如 `'["活动A","活动B"]'`），提取其中所有非空字符串元素（去首尾空白），按出现顺序用中文顿号 `、` 拼接（如 `"活动A、活动B"`）；
       - 若为空字符串、空数组或全为空元素，则 `靓号活动名称` 提交 `not_found`。

## 提交要求

- **靓号（命中 `msisdn == 手机号码` 且 `grade` 非空）**：
  - `靓号等级`（`quote`）：值为 `grade` 原文，`evidence` 填 `[{"type":"api","resultId":...,"row":...,"column":"grade"}]`。
  - `靓号活动名称`（`derive`）：值为提取/拼接后的活动名称，`evidence` 引用该记录 `{"type":"api","resultId":...,"row":...,"column":"level_info.event_name"}`（及 `query_result` 的 `callId`）；活动名称为空时提交 `not_found`。
  - `手机号类别`（`derive`）：值为 `"靓号"`，`evidence` 引用该记录的 `msisdn` 与 `grade` 列（及 `query_result` 的 `callId`），`reasoning` 写明命中号码记录且 `grade` 非空。
- **非靓号（`count=0`、`msisdn` 无匹配、`grade` 为空，或接口失败/缺参）**：
  - `靓号等级`、`靓号活动名称`、`手机号类别` 全部提交 `not_found`，`reasoning` 写明具体原因（如“靓号接口无记录”“返回记录与手机号码不匹配”或“匹配记录 grade 为空，按非靓号处理”）；模板中 `手机号类别` 缺省值自动取 `"非靓号"`（走非靓号段落）。
