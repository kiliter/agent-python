---
title: 平台工具实现剖析
type: component
tags: [component, runtime, tools, text-tools, query-result, security]
sources:
  - src/report_agent/runtime/tools.py
  - src/report_agent/runtime/text_tools.py
updated: 2026-11-12
---

# 平台工具实现剖析

<!-- #Created By AiCoding(codex) -->

平台向智能体暴露的全部 **12 个确定性工具**实现在 `src/report_agent/runtime/tools.py`（`build_tools` 工具包装与工作区记录）与 `src/report_agent/runtime/text_tools.py`（纯函数文本、日期、区间与正则算法）两个模块中。

## 1. 工具装配与容错重试（`build_tools` + `_fail_or_retry`）

`build_tools(tool_retries)` 创建 12 个 Pydantic AI `Tool[RunDeps]` 实例（默认 `max_retries=2`）：
- **动态枚举收窄（`prepare` 钩子）**：`_prepare_load_skill` 与 `_prepare_call_api` 在运行期动态改写工具参数的 JSON Schema `enum` 列表，使模型在 Schema 层面就只能看到当前模板允许加载的 `allowed_skills` 与允许调用的 `allowed_apis`。
- **分级重试与平滑降级（`_fail_or_retry`）**：当模型传入了不存在的 `resultId`、非法的正则或越界的日期参数时，若 `ctx.retry < ctx.max_retries`，先登记失败调用并抛出 `ModelRetry` 引导模型修正参数；若重试耗尽，则直接返回结构化 `{"ok": False, "error": ...}` 而非炸断整次报告运行，让模型将该字段优雅标记为 `not_found`。

## 2. `tools.py` 核心实现细节

### 2.1 `call_api`：契约校验、网关隔离与预览截断

1. 检查接口名在 `deps.allowed_apis` 内，并通过 `contract.validate_args(clean_args)` 校验 JSON Schema；
2. 调用 `deps.gateway.invoke(contract, clean_args)`（外包异常捕获兜底转为 `ApiCallResult(ok=False)`），生成 `ApiResult` 存入 `deps.workspace.add_result(result)`（分配 `r1`, `r2`…）；
3. 返回给模型的 `preview` 最多取 `contract.preview_rows(deps.settings.agent_preview_rows)` 行（带 0 起始的 `row` 索引），单列超过 `maxPreviewChars` 自动截断加 `…`，强制模型通过 `query_result` 读取完整列值后再做判断与引用。

### 2.2 `query_result`：单表/多表合并过滤引擎

- **参数自检（`_validate_condition_params`）**：强制校验 `prefixLen` 为正整数、`op="between"` 时 `endValue` 非空且 `value <= endValue`。
- **多结果集合并（`resultIds`）**：去重保序检查所有 `rid` 均存在且 `r.ok == True`（任一接口调用失败则直接返回 `ok=False`，禁止在残缺账期结果上静默漏数据）；合并行在满足 `where`（AND）与 `anyOf`（OR）后统一按 `orderBy` 稳定排序，每行注入来源 `"resultId"` 与 `"row"`。
- **单结果集查询（`resultId`）**：保持轻量返回 `{resultId, total, rows}`，每行注入 0 起始 `"row"`。

## 3. `text_tools.py` 纯函数算法细节

| 函数 | 关键工程细节 |
|------|--------------|
| `normalize_text` | 先做 `unicodedata.normalize("NFKC", raw)`，再剥离 `FIXED_CHARS_TO_REMOVE`（中英文标点）、`_ZERO_WIDTH_CHARS`（`\ufeff\u200b\u200c\u200d`）与调用方传入的 `extra_chars` |
| `convert_date` / `parse_date` | 将 `yyyy`/`MM`/`M`/`dd`/`d`/`HH`/`H`/`mm`/`m`/`ss`/`s` 编译为命名捕获组正则 `_pattern_regex` 并构造真实 `datetime`，拦截重复占位符与非法日历值 |
| `extract_dates` | 依次扫描四类规则：① `yyyy年M月d日/号`；② 同分隔符 `yyyy-M-d`/`yyyy/M/d`/`yyyy.M.d`；③ 前后不紧邻字母数字的独立 8 位 `yyyyMMdd`（排除 `25JS206149`、11 位手机号、14 位时间戳与长流水号）；④ 不与前三条跨度重叠且带 `defaultYear` 补全的 `M月d日/号`（`defaultYear` 支持传 4/6/8/12/14 位数字或日期串自动提取 1900～2099 年份）。返回保序去重 `dates`、升序 `sorted`、`min`、`max`、`count` |
| `date_shift` | `_parse_calendar_date` 兼容紧凑 8/14 位、分隔符日期及中文日期时间，基于 `timedelta` 精确推算 `baseDate`、`date`、`endDate`、`start`（`000000`）与 `end`（`235959`） |
| `expand_period` | 依次识别：① 多账期分隔（`$`/`,`/`，`/`;`/`；`/`、`）；② 单一纯年月（`202607`/`2026-07`/`2026年7月`，展开整月 `01`～月末，彻底根除 `202607` 正则回溯问题）；③ 显式区间连接符（`~`/`～`/`至`/`到` 及智能区分日期内部连字符的双端 `-` 区间，跨度上限 `MAX_PERIOD_MONTHS = 36`）；④ 单日或时间戳 |
| `time_diff` | `_parse_timestamp` 支持紧凑 14 位、标准分隔符与中文时分秒，返回精确整数秒差 `diffSeconds`、`absSeconds` 与 `later` |
| `regex_extract` | `safe_regex_compile` 限制模式长度 `MAX_REGEX_LENGTH = 2000` 并捕获语法错误；无捕获组且 `group=1` 时自动退回 `group=0`，输出去重 `matches`、全量 `allMatches`、`first` 与 `count` |

## 相关页面

- [确定性平台工具设计](../architecture/deterministic-tools.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [AgentRunner 运行时组件剖析](agent-runner.md)
- [11 个纯文本业务 Skill 总览](../skills/README.md)
