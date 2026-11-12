---
title: Java 行为差异与二期主动修复台账
type: lint
tags: [lint, java-divergence, bugfix, migration, parity]
sources:
  - tools/java_migration/MAPPING.md
  - tools/java_migration/TEMPLATES.md
  - tools/java_migration/field_catalog.yaml
  - src/report_agent/seed/skills/reminder-sms/SKILL.md
  - src/report_agent/seed/skills/qry-balance/SKILL.md
  - src/report_agent/seed/skills/pretty-number-info/SKILL.md
updated: 2026-11-12
---

# Java 行为差异与二期主动修复台账

<!-- #Created By AiCoding(codex) -->

本页完整登记 `agent-python` 相比前代 Java 版（`pdf-agent-parse`）的全部行为差异，严格区分 **“二期主动修复的前代历史 Bug（正向改进）”** 与 **“架构升级带来的受控边界差异”**，供灰度双跑比对与验收审计直接核查。

## 1. 二期主动修复的前代 Java 历史缺陷（共 5 项）

以下项目在 Java 线上代码中属于明确的正则/逻辑/模板配置缺陷，一期迁移对拍暴露后，已在二期主动根治：

| 编号 | 涉及资源 / 模块 | 前代 Java 版的缺陷表现 | `agent-python` 二期修复方案 | 双跑比对预期表现 |
|------|-----------------|------------------------|----------------------------|------------------|
| **R2** | Skill `reminder-sms`（模板 `105`/`108`/`120`/`129`） | 宽松日期正则 `(\d{4})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})` 无日历校验，将订购短信中普遍存在的 `（编号：25JS206149）。\n1.` 误解析为 `20614901`，取最大值后去查 2061 年 49 月，导致现网提醒短信几乎 100% 查不到 | 改用平台确定性工具 `extract_dates`（严格日期分隔符 + 真实日历合法性校验，非空 `deadlineDate` 优先，无合法日期时回退 `创建时间` 当天）+ `date_shift`，忽略活动编号，精准提取真实截止日（如 `20271201`） | Python 成功填出真实的 `提醒日期` 与 `提醒短信`；Java 为空占位符 |
| **R8** | Skill `qry-balance`（模板 `106`/`107`） | 过滤阶段正则 `(20\d{2})\D*(\d{1,2})\D*(\d{1,2})` 在入参 `充值时间` 仅含年月（如 `202607`）时发生正则回溯，强行拆成 `2026`+`0`+`7` = `20260007`，把整月合法流水全部误删 | 改用 `expand_period` + `query_result(resultIds=..., where=[between prefixLen=8])`：纯年月 `202607` 自动展开为整月闭区间 `startDate="20260701", endDate="20260731"`，完整保留当月全部流水并倒序排列 | 纯年月入参下 Python 正常输出当月充值流水列表；Java 输出空 |
| **R5** | Skill `pretty-number-info`（模板 `131`/`132`） | ① Groovy 代码不比对 `msisdn` 是否等于被查手机号；② 记录存在但 `grade` 为空时仍输出 `手机号类别=靓号` 造成病句；③ 多档次 `event_name` 无分隔符粘连成一串 | ① `query_result` 精确匹配 `msisdn == 手机号码`；② `grade` 为空统一按非靓号处理（默认输出 `非靓号`）；③ 多档次 JSON 数组活动名称去空后以中文顿号 `、` 连接（`靓号活动名称` 为 `evidence: derive`） | 空等级或多档次靓号下 Python 话术准确通顺 |
| **R17** | 模板 `120`（`宽带业务续约争议类`）字段 `有设备押金` | Java 未找到该字段时填入占位符 `"{{ 有设备押金 }}"`（非空字符串），导致模板 `{% if 有设备押金 %}` 恒为 `true`，`{% else %}- 无{{商品名称}}设备押金记录。{% endif %}` 分支永远不可达 | 在 `field_catalog.yaml` 与模板定义中将该字段 `whenMissing` 设为 `empty`（未找到时为空串 `""`），使无押金工单正常走入 `{% else %}` 分支 | 无设备押金工单下 Python 正确输出 `- 无{{商品名称}}设备押金记录。`；Java 错误输出带占位符的有押金分支 |
| **R7** | 模板 `106`/`107`/`131`/`132` 同名入参 `客户号码` | 同时存在字段 `客户号码` 与入参 `客户号码`，产生 4 条 `FIELD_SAME_AS_INPUT` 告警且引发号码取数顺序歧义 | 从模板 `inputs` 移除冗余的 `客户号码`：`qry-balance` 号码优先级收敛为 `充值号码`（含 `extraInfo`）→ `手机号码`；`pretty-number-info` 统一取 `手机号码`；33 模板达成 **0 error / 0 warning** | 标准入参下结果完全一致，静态治理零告警 |

## 2. 架构升级带来的受控边界差异（等价或更优）

| 编号 | 维度 | Java 版行为 | Python 版行为 | 影响评估 |
|------|------|------------|--------------|----------|
| **R1** | 余额流水 `request_time` | Groovy 取当前时间 `yyyyMMddHHmmss` | 契约使用内置占位符 `request_time: ${$now}` 动态注入当前 `yyyyMMddHHmmss` | **完全等价**（报文逐字节一致） |
| **R4** | 列表字段 0 行结果与缺失 | Groovy 返回 `[]`；网关报错时抛异常 | 合法查得 0 行提交 `status="found", value=[]`（状态 `SUCCESS`）；缺参或网关报错提交 `not_found`，由 `TrackedList` 在迭代分支标为 `PARTIAL` | **渲染结果完全一致**，且运行状态区分度显著提升 |
| **R9** | 单日短信接口业务报错（非“无短信记录”） | Groovy `extract` 不检查 `resp_code`，静默视同无短信返回空 | 契约 `success` 校验 `resp_code == '0000'`，非 `0000` 且不含“无短信记录”时判为 `ok=false` → 字段 `not_found` | 最终报告渲染展示相同（如 `受理渠道` 均回退默认 `其他`），但工作台能清晰观测到网关报错并标记 `PARTIAL` |
| **R10** | 非标准分隔符的 `创建时间` | 直接去非数字取前 8 位（若传 `"2026-5-1"` 会错截成 `"202651..."`） | `date_range` 识别标准分隔格式并做日历合法性校验 | 标准 14 位 `yyyyMMddHHmmss` 下完全一致；非标短月日下 Python 更稳健 |
| **R11** | 服务层 5 项硬编码后处理 | 散落在 `IntelligentComplaintServiceImpl` Java 代码中 | 完整内化到 `system-prompt.md`、模板字段 `description` 与 `EvidenceChecker` 中，平台代码零硬编码 | 业务语义一致且对维护人员透明可见 |
| **R12** | 文本归一化（`normalize_text`） | `StringCharCleaner` 去除空白与中英文标点 | 在对齐全部标点基础上，额外剥离不可见零宽字符 `\ufeff\u200b\u200c\u200d` | 消除复制粘贴带入零宽字符导致的偶发漏配 |
| **R13** | 同日短信重复查询 | 多个 `SkillAgent` 各自独立请求一次 `querySMSSendInfo` | 单智能体在 `Workspace` 内直接复用相同参数的 `resultId` | 数据完全相同，网关请求量减少 60%～80% |
| **占位符空格** | 未找到字段的保留占位符格式 | Pebble 输出部分带空格的 `{{ 字段名 }}` | Python 统一输出紧凑的 `{{字段名}}` | 语义一致（`verify_render.py` 归一化此格式差异） |

## 相关页面

- [ADR-005：Java 生产资源自动化迁移对拍体系与二期历史缺陷主动修复决策](../decisions/adr-005-java-migration-and-bug-fixes.md)
- [Java 资源迁移与一致性对拍指南](../guides/java-migration-and-verification.md)
- [当前架构已知约束与注意事项](known-issues.md)
- [待业务确认事项与演进议题](open-questions.md)
