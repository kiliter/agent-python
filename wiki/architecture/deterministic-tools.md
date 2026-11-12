---
title: 确定性平台工具设计
type: concept
tags: [architecture, tools, primitives, query-result, date, regex]
sources:
  - src/report_agent/runtime/tools.py
  - src/report_agent/runtime/text_tools.py
  - src/report_agent/runtime/evidence.py
updated: 2026-11-12
---

# 确定性平台工具设计

<!-- #Created By AiCoding(codex) -->

在从前代 Java Groovy 脚本架构向纯文本 `SKILL.md` 演进的过程中，最核心的架构挑战是：**大模型擅长阅读复杂协议与业务上下文，但在跨月日历推算、秒数相减、长文本正则提取、标点归一化比对与几十行表格精确筛选上容易产生心算误差**。

为此，平台确立了清晰的职责边界：**模型负责语义规划与工具编排，所有精确过滤、字符串清洗、日历运算、时间差与正则捕获一律下沉为通用确定性平台工具**。

## 1. 设计边界与三大铁律

1. **零业务耦合**：工具名、参数名与内部实现不包含任何特定电信业务词汇（没有 `parse_sms_date` 或 `filter_balance_flow`），全部抽象为通用数据与时间原语，任何新模板和新 Skill 均可直接组合复用。
2. **上下文防膨胀（Workspace Offloading）**：外部网关一次可能返回上百条短信或充值流水。`call_api` 只把完整记录存入内存 `Workspace`（分配 `r1`、`r2`），仅向模型返回总条数、列名与前 `AGENT_PREVIEW_ROWS`（默认 10）条截断预览；模型必须通过 `query_result` 下推条件精确取回目标完整行。
3. **值转换核验（`VALUE_TOOLS`）**：每次工具调用均在工作区分配递增 `callId`（`t1`、`t2`…），可作为 `derive` 字段或合法空列表（`value=[]`）的查询证据引用；其中 `format_date` 列入 `VALUE_TOOLS = {"format_date"}`，当 `derive` 字段引用其 `callId` 时，`EvidenceChecker` 强制核对提交值与该工具输出的 `value` 完全一致。

## 2. 12 个确定性平台工具全景矩阵（`runtime/tools.py#build_tools`）

| 分类 | 工具名 | 参数签名（除 `ctx` 外） | 返回核心结构 | 典型使用场景 |
|------|--------|------------------------|--------------|--------------|
| **资源与网关** | `load_skill` | `name: str` | Markdown 文本（含 `SKILL.md` 正文与可调用接口参数提示） | 按需读取当前模板白名单内的 Skill 完整步骤 |
| **资源与网关** | `call_api` | `name: str, args: dict` | `{resultId, ok, count, columns, preview, note}` | 按契约 JSON Schema 校验参数后调用网关（`live`/`mock`），分配 `resultId` |
| **结构化检索** | `query_result` | `resultId="", where=None, orderBy=None, limit=20, columns=None, *, anyOf=None, resultIds=None` | 单表 `{resultId, total, rows}`；多表 `{resultIds, total, rows}`（每行含 `resultId` 与 0 起始 `row`） | 在单次或跨月多次网关结果上执行 AND/OR 过滤、前缀闭区间比较与稳定排序 |
| **文本原语** | `normalize_text` | `text: str, extraChars: str = ""` | `{callId, value}` | NFKC 归一化 + 去除零宽字符、固定中英文标点及 `extraChars`（对齐 Java `StringCharCleaner`） |
| **文本原语** | `text_contains` | `target: str, text: str \| None = None, normalize: bool = True, extraChars: str = ""` | `{callId, contains, normalizedTarget}` | 判断关键词或业务名是否命中目标文本（省略 `text` 时查单据全文） |
| **日期与时间** | `date_range` | `time: str, unit: "day" \| "month"` | `{callId, start, end}` | 计算指定时间所在日或所在自然月首尾的 14 位时间戳（`000000` ～ `235959`） |
| **日期与时间** | `format_date` | `value: str, fromPattern: str, toPattern: str` | `{callId, ok, value}` | **唯一 `VALUE_TOOLS`**，按 Java 风格模式转换日期展示格式（如 `yyyyMMddHHmmss` → `yyyy-MM-dd`） |
| **日期与时间** | `extract_dates` | `text: str \| None = None, defaultYear: str \| int \| None = None` | `{callId, ok, dates, sorted, min, max, count}` | 按 4 条严格规则扫描并经真实日历校验提取 8 位 `yyyyMMdd` 日期（不误匹配活动编号/手机号/流水号），直接返回最小 `min` 与最大 `max` |
| **日期与时间** | `date_shift` | `date: str, days: int = 0, endDays: int \| None = None` | `{callId, ok, baseDate, date, endDate, start, end}` | 按真实日历（含大小月、跨年、闰年）加减天数，支持一步输出 `[days, endDays]` 的 14 位 `start` / `end` 窗口 |
| **日期与时间** | `expand_period` | `period: str` | `{callId, ok, months, monthRanges, startDate, endDate, startTime, endTime}` | 解析 `$`/`,` 多账期、`-`/`~`/`至`/`到` 区间、纯年月或具体日期，展开闭区间 `yyyyMM` 列表与精确起止日期（最长 36 个月） |
| **日期与时间** | `time_diff` | `time1: str, time2: str` | `{callId, ok, diffSeconds, absSeconds, later}` | 计算两个时间戳精确秒差 `time1 - time2`、绝对秒差 `absSeconds` 及先后关系 `later`（`"time1"\|"time2"\|"equal"`） |
| **正则提取** | `regex_extract` | `pattern: str, text: str \| None = None, group: int = 1` | `{callId, ok, matches, allMatches, first, count}` | 使用安全编译正则提取非空捕获组（无括号且 `group=1` 时自动提取整段匹配），返回保序去重 `matches` 与首个命中 `first` |

> 注：`text_contains`、`extract_dates` 与 `regex_extract` 的 `text` 参数省略或传 `None` 时，均默认直接读取当前工作区的完整单据文本 `ctx.deps.document`。

## 3. 重点工具组合范式

### 3.1 `query_result` 的高级过滤与跨结果集合并

`query_result`（`src/report_agent/runtime/tools.py`）支持完备的单表与跨月多表合并检索能力：

- **7 种比较操作符（`Condition.op`）**：
  - 原样比较：`equals`、`contains`、`notContains`、`startsWith`、`between`（闭区间 `[value, endValue]`）；
  - 清洗比较：`normalizedContains`、`normalizedNotContains`（两侧先经 `normalize_text` 清洗再判断包含）。
- **列值截断修饰符**：
  - `before`：若列值中出现 `before` 子串，只截取第一次出现之前的前缀参与比较（如 `business-sms` 中 `before="编号"` 只比对短信头部）；
  - `prefixLen`：截取列值前 `prefixLen` 个字符再比较（`op="between"` 且列文本长度不足 `prefixLen` 时安全判为不命中，常用于对 14 位 `payDatetime` 取 `prefixLen=8` 做日期区间过滤）。
- **`anyOf`（OR 条件组）**：行必须同时满足 `where` 中全部条件（AND），且满足 `anyOf` 中至少一个条件（OR），一步完成 `renewal-reminder-sms` 中“匹配业务名称 **或** 匹配任一活动编号”的复合筛选。
- **`resultIds`（跨批次合并查询）**：支持一次传入多个成功接口调用结果（如 `resultIds=["r1", "r2"]`），合并过滤并统一按 `orderBy` 稳定排序，输出每行同时携带各自原始的 `resultId` 与 `row`（任一 `rid` 不存在或 `ok=False` 时拒绝合并返回 `ok=False`）。

### 3.2 严格日期扫描替代脆弱手写正则（`extract_dates` + `date_shift`）

在 `reminder-sms` 与 `renewal-reminder-sms` 中，从订购短信提取活动到期日并计算查询窗口：
1. 调用 `extract_dates(text=订购短信原文, defaultYear=创建时间)`：按 4 条严格规则扫描（① `yyyy年M月d日/号`；② 同分隔符 `yyyy-M-d`/`yyyy/M/d`/`yyyy.M.d`；③ 前后不紧邻字母数字的独立 8 位 `yyyyMMdd`；④ 用 `defaultYear` 补齐且不重叠的 `M月d日/号`），全部经 `datetime.date` 真实日历验证，绝不把 `25JS206149`、11 位手机号或 14/20 位数字串误当成日期，直接读取返回的 `max`；
2. 接着调用 `date_shift(date=max, days=0)`（当天窗口）或 `date_shift(date=max, days=-31, endDays=31)`（前后各 31 天跨月窗口），一步拿到 14 位 `start` 与 `end`。

## 相关页面

- [单智能体请求处理管道](request-pipeline.md)
- [强证据核验机制](evidence-system.md)
- [平台工具实现剖析](../components/platform-tools.md)
- [11 个纯文本业务 Skill 总览](../skills/README.md)
- [ADR-002：采用纯文本 SKILL.md + 平台确定性工具原语替代 Groovy 脚本引擎](../decisions/adr-002-text-skill-and-deterministic-tools.md)
