---
title: Skill 详解：original-package-name（原套餐名称）
type: skill
tags: [skill, sms, original-package-name, time-diff, regex-extract]
sources:
  - src/report_agent/seed/skills/original-package-name/SKILL.md
  - src/report_agent/runtime/text_tools.py
updated: 2026-11-12
---

# `original-package-name`：原套餐名称

<!-- #Created By AiCoding(codex) -->

`original-package-name` 服务于模板 `118`（`套餐变更争议类`：“将套餐由`{{原套餐名称}}`变更为`{{商品名称}}`”）。由于套餐变更成功瞬间系统会同时下发一条新套餐订购短信与一条旧套餐“退订提醒”短信，本 Skill 以 `订购短信` 发送时间为锚点，找出时间距离最近的那条“退订提醒”短信并提取双引号内的原套餐名称。

## 1. 基本契约

- **产出字段**：`原套餐名称`（`type: string`，`evidence: quote`）
- **关联接口**：`querySMSSendInfo`（与 `business-sms` 同日窗口，直接复用其 `resultId`）
- **上游依赖**：字段 `订购短信`（若 `订购短信` 为 `not_found`，直接跳过并返回 `not_found`，绝不自行猜测时间基准）
- **必填入参**：`手机号码`（11 位数字）、`创建时间`（本 Skill 筛选退订短信时不使用入参 `业务名称`，因为退订短信里写的是旧套餐名而非新业务名）

## 2. 确定性工具执行流程（二期升级版）

1. **锁定基准时间**：取 `business-sms` 命中的那条记录的 14 位 `smsSendTime` 作为基准时间戳（若跨结果集则用 `query_result` 的 `equals` 找到正文与 `订购短信` 相同的最新记录）。
2. **筛选“退订提醒”候选集**：在同一当日 `resultId` 上调用 `query_result`：
   ```json
   {
     "resultId": "<resultId>",
     "where": [{"column": "smsContent", "op": "contains", "value": "退订提醒"}],
     "limit": 100,
     "columns": ["smsContent", "smsSendTime"]
   }
   ```
   - 仅认固定词 `退订提醒`（不得拿“退订成功”兜底）；`total == 0` 时直接提交 `not_found`。
3. **用 `time_diff` 精确计算秒级距离**：
   - 对每条候选调用确定性工具 `time_diff(time1=候选smsSendTime, time2=订购短信smsSendTime)`，获取 `{callId, ok, diffSeconds, absSeconds, later}`（替代让大模型心算 `HH×3600+mm×60+ss`）；
   - 选择 `absSeconds` **最小**的一条；若两条 `absSeconds` 完全相等，取发送时间**较晚**的一条（即 `later == "time1"` 的候选）。
4. **用 `regex_extract` 从唯一选中短信提取名称**：
   - **只对第 3 步选中的那一条短信提取**（若提取不到直接报 `not_found`，绝不换下一条候选重试）：
   - 先调 `regex_extract(pattern=r'办理的\s*[“"]([^”"]+)[”"]', text=选中smsContent, group=1)` 提取“办理的“XXX””结构；
   - 若 `count == 0`，再调回退正则 `regex_extract(pattern=r'[“"]([^”"]+)[”"]', text=选中smsContent, group=1)` 取第一对中/英文双引号内文本（单引号、书名号不算）。

## 3. 证据提交要求

- 提交值为提取出的纯名称（去掉首尾空白），它在选中记录的 `smsContent` 中逐字连续出现，天然满足 `evidence: quote`；
- 由于 `quote` 字段只允许引用逐字来源，`evidence` 仅填选中退订提醒记录 `[{"type": "api", "resultId": ..., "row": <选中row>, "column": "smsContent"}]`（上游基准 `订购短信` 及 `time_diff`、`regex_extract` 的调用结果写入 `reasoning`，不放入 `quote` 字段的 `evidence` 数组中）。

## 相关页面

- [11 个纯文本业务 Skill 总览](README.md)
- [business-sms：订购短信](business-sms.md)
- [确定性平台工具设计](../architecture/deterministic-tools.md)
- [强证据核验机制](../architecture/evidence-system.md)
