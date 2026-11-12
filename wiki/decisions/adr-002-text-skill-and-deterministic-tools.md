---
title: ADR-002：采用纯文本 SKILL.md + 平台确定性工具原语替代 Groovy 脚本引擎
type: decision
tags: [decision, adr, skill, groovy, deterministic-tools, security]
sources:
  - src/report_agent/domain/skill.py
  - src/report_agent/runtime/tools.py
  - src/report_agent/runtime/text_tools.py
  - tools/java_migration/MAPPING.md
updated: 2026-11-12
---

# ADR-002：采用纯文本 `SKILL.md` + 平台确定性工具原语替代 Groovy 脚本引擎

<!-- #Created By AiCoding(codex) -->

- **状态**：已采纳（Accepted）
- **决策日期**：2026-11-12

## 1. 背景与问题

前代 Java 版中，每个业务 Skill 由 `SKILL.md` + `scripts/assembly.groovy`（组包）+ `scripts/extract.groovy`（解析与筛选）三部分组成，运行时通过 `GroovyScriptEngine` 动态编译执行。一旦允许在 Web 管理工作台在线编辑并发布 Skill，动态脚本方案面临两大顽疾：
1. **严重的安全沙箱边界隐患**：JVM 上的 `SecureASTCustomizer` 属于黑名单式 best-effort 沙箱，难以彻底防御反射/元编程逃逸（RCE），因此不敢向非研发人员开放工作台在线脚本编辑；
2. **业务维护成本高且易藏隐蔽 Bug**：非 Java/Groovy 研发的业务配置人员无法独立阅读和修改 Groovy 正则与 XML 解析代码，且手写脚本缺乏统一日历校验（实际滋生了 R2 活动编号当日期、R8 纯年月正则回溯等线上缺陷）。

但如果简单去掉脚本、把所有日期推算、秒差比较和正则提取交给大模型“裸算”，大模型又会出现闰年算错天数、秒数心算失误等问题。

## 2. 决策内容

采用 **“声明式网关契约（替代 `assembly.groovy`）+ 纯文本 `SKILL.md`（表达业务判定流程）+ 12 个平台确定性工具原语（替代 `extract.groovy` 中的精确计算）”** 三位一体架构：

1. **组包与基础解析声明化**：请求参数校验、XML/JSON 报文拼装（含 `${$now}` 占位符）、`noData`/`success` 判定及二维表抽取全部由 `apis/*.yaml` 声明驱动；
2. **计算与过滤工具化**：平台内置 `query_result`（支持多结果集合并 `resultIds`、`anyOf` OR 组合、`between`、`startsWith`、`normalizedContains`、`before`、`prefixLen`）、`normalize_text`、`text_contains`、`date_range`、`format_date`、`extract_dates`、`date_shift`、`expand_period`、`time_diff`、`regex_extract` 共 12 个无副作用纯函数工具（并对正则施加长度保护、对 XML 施加防 XXE 保护）；
3. **Skill 纯文本化**：`SKILL.md` 只包含 YAML frontmatter 与自然语言步骤，指导智能体在何时以何参数调用上述确定性工具。

## 3. 后果与权衡

- **正面收益**：
  - **彻底根除远程代码执行（RCE）攻击面**：工作台编辑发布的全部是纯 Markdown 与受 Schema 约束的 YAML，天然安全；
  - **消除模型算术误差**：跨月窗口展开、严格日历日期扫描、秒差绝对值计算均由经过完备单元测试的 Python 标准库函数执行；
  - **可观测性极佳**：原本黑盒执行的 Groovy 脚本内部步骤，现在变成时间线上清晰可见的 `extract_dates` → `date_shift` → `call_api` → `query_result` 工具轨迹，一眼即可定位哪一步过滤掉了候选记录。
- **代价与应对**：
  - 相比本地执行一次 Groovy 函数，模型串联 2～4 个确定性工具会多出 1～2 轮轻量 Tool Call 交互；由于单次传入工具的只是短字符串或 `resultId` 引用，增量耗时通常在百毫秒至秒级，完全处于申告后台处理可接受范围内。

## 相关页面

- [确定性平台工具设计](../architecture/deterministic-tools.md)
- [平台工具实现剖析](../components/platform-tools.md)
- [11 个纯文本业务 Skill 总览](../skills/README.md)
- [ADR-001：采用单智能体自主规划 + 强证据校验替代 Java 三 Agent 编排](adr-001-single-agent-and-evidence.md)
