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
- **动态枚举收窄与轻量浅拷贝（`prepare` 钩子）**：`_prepare_load_skill` 与 `_prepare_call_api` 采用字典浅拷贝动态改写工具参数的 JSON Schema `enum` 列表（同时约束 `load_skill` 的单值 `name` 与批量 `names` 元素枚举），使模型在 Schema 层面只能看到当前模板允许的 `allowed_skills` 与 `allowed_apis`。
- **分级重试与 `callId` 保底（`_fail_or_retry`）**：当模型传入不存在的 `resultId`、未知列名、非法正则或越界日期参数（含 `format_date` 格式异常）时，若 `ctx.retry < ctx.max_retries`，先登记失败调用并抛出 `ModelRetry` 引导模型修正参数；若重试耗尽，则返回携带本次 `"callId"` 的结构化 `{"callId": ..., "ok": False, "error": ...}`，让模型将该字段优雅标记为 `not_found`。

## 2. `tools.py` 核心实现细节

### 2.1 `load_skill` 与 `call_api`：批量加载、同工作区幂等去重与预览截断

1. **批量 Skill 加载（`load_skill`）**：兼容单值 `name="business-sms"` 与批量 `names=["business-sms", "accept-type"]`，一次调用即可拼接返回多个白名单内 `SKILL.md` 正文与接口参数提示，大幅减少多 Skill 模板的串行交互轮次。
2. **同工作区幂等 `call_api` 去重复用**：通过 `contract.validate_args(clean_args)` 校验 JSON Schema 后，若 `contract.idempotent == True`，按 `(name, canonical_json_args)` 检查 `Workspace`：已有在途请求时共享同一 `Future` 等待，已有 `ok == True` 成功结果时直接复用原 `ApiResult`（返回原 `resultId` 与预览并登记新 `callId`，不重复发 HTTP 请求也不重复保存 200KB `raw` 报文；`ok == False` 失败结果不缓存以便重试容错）。
3. **预览截断与 `callId` 返回**：`call_api` 成功与失败分支均返回 `"callId"`（`count == 0` 时其 `callId` 可直接作为合法空列表 `value=[]` 的核查证据）；`preview` 最多取 `contract.preview_rows(deps.settings.agent_preview_rows)` 行，单列超过 `maxPreviewChars` 自动截断加 `…`，强制模型通过 `query_result` 读取完整列值后再做判断与引用。

### 2.2 `query_result`：全量列名自检与单表/多表合并过滤引擎

- **参数与全量列名自检**：`_validate_condition_params` 校验 `prefixLen` 为正整数、`op="between"` 时 `endValue` 非空且 `value <= endValue`；同时合并契约声明列 `res.columns` 与实际记录键集构造 `all_cols`，只要 `all_cols` 非空（**即使 `records` 为 0 行**），统一校验 `where`、`anyOf`、`orderBy` 与投影 `columns` 中的列名，未知列名一律经 `_fail_or_retry` 报错并提示可用列，杜绝拼写错误静默返回空字典。
- **多结果集合并（`resultIds`）**：去重保序检查所有 `rid` 均存在且 `r.ok == True`（任一接口调用失败则直接返回带 `callId` 的 `ok=False`）；合并行在满足 `where`（AND）与 `anyOf`（OR）后统一按 `orderBy` 稳定排序，返回 `{callId, resultIds, total, rows}`，每行注入来源 `"resultId"` 与 `"row"`。
- **单结果集查询（`resultId`）**：返回 `{callId, resultId, total, rows}`（`total == 0` 时其 `callId` 是筛选后合法空列表 `value=[]` 的标准证明）。

## 3. `text_tools.py` 纯函数算法细节

| 函数 | 关键工程细节 |
|------|--------------|
| `normalize_text` / `text_contains` | `normalize_text` 执行 `unicodedata.normalize("NFKC", raw)` 并剥离 `FIXED_CHARS_TO_REMOVE`、`_ZERO_WIDTH_CHARS` 与 `extra_chars`；上层工具 `text_contains` 在 `normalize=True` 时默认追加剥离 `" \t\r\n\u3000"`，消除 PDF 跨行折行导致的业务名漏配 |
| `convert_date` / `format_date` | 将 `yyyy`/`MM`/`M`/`dd`/`d`/`HH`/`H`/`mm`/`m`/`ss`/`s` 编译为命名捕获组正则并构造真实 `datetime`；`format_date` 支持单值 `value` 或批量 `values: list[str]` 转换，异常统一走 `_fail_or_retry` |
| `date_range` | 废除盲目去非数字截取逻辑，严格识别带前缀文本中的合法分隔日期（如 `"受理时间：2026-1-12 03:04:05"` → `20260112`）与独立 8/14 位数字日期，并在 `unit="month"` 下原生支持 `yyyyMM`、`yyyy-M`、`yyyy/M`、`yyyy年M月` |
| `extract_dates` | 依次扫描四类规则：① 强制以显式 `[日号]` 结尾的 `yyyy年M月d日/号`（杜绝把 `"2026年10月5G特惠包"` / `"20元"` 误抽为日期）；② 同分隔符 `yyyy-M-d`/`yyyy/M/d`/`yyyy.M.d`；③ 前后不紧邻字母数字的独立 8 位 `yyyyMMdd`（排除 `25JS206149`、11 位手机号、14 位时间戳）；④ 不重叠且带 `defaultYear` 补全的 `M月d日/号`。返回保序去重 `dates`、升序 `sorted`、`min`、`max`、`count` |
| `date_shift` | `_parse_calendar_date` 兼容紧凑 8/14 位、分隔符日期及中文日期时间，基于 `timedelta` 精确推算 `baseDate`、`date`、`endDate`、`start`（`000000`）与 `end`（`235959`） |
| `expand_period` | 依次识别：① `$` 分隔账期：恰好双段合法年月 `A$B`（`A <= B`，如 `"202607$202610"`）按闭区间展开全部中间连续月份，多于 2 段或 `,`/`;` 分隔按离散月份去重，并**统一按月份升序输出** `months` 与 `monthRanges`；② 单一纯年月（展开整月 `01`～月末）；③ 显式区间连接符（`~`/`～`/`至`/`到`/`-`，跨度上限 `MAX_PERIOD_MONTHS = 36`）；④ 单日或时间戳 |
| `time_diff` | `_parse_timestamp` 支持紧凑 14 位、标准分隔符与中文时分秒，返回精确整数秒差 `diffSeconds`、`absSeconds` 与 `later` |
| `regex_extract` | `safe_regex_compile` 限制模式长度 `MAX_REGEX_LENGTH = 2000`，并通过 `re._parser` 语法树静态拦截“重复量词内部嵌套重复量词”（如 `(a+)+`）阻断同步 ReDoS 灾难性回溯；单次扫描文本限制 `MAX_REGEX_TEXT_LENGTH = 200_000` 字符；输出去重 `matches`、全量 `allMatches`、`first` 与 `count` |

## 相关页面

- [确定性平台工具设计](../architecture/deterministic-tools.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [AgentRunner 运行时组件剖析](agent-runner.md)
- [11 个纯文本业务 Skill 总览](../skills/README.md)
