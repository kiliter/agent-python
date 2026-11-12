---
title: ADR-005：Java 生产资源自动化迁移对拍体系与二期历史缺陷主动修复决策
type: decision
tags: [decision, adr, migration, bugfix, verification]
sources:
  - tools/java_migration/README.md
  - tools/java_migration/MAPPING.md
  - tools/java_migration/generate.py
  - tools/java_migration/verify_structure.py
  - tools/java_migration/verify_render.py
  - tools/java_migration/check_skills.py
updated: 2026-11-12
---

# ADR-005：Java 生产资源自动化迁移对拍体系与二期历史缺陷主动修复决策

<!-- #Created By AiCoding(codex) -->

- **状态**：已采纳（Accepted）
- **决策日期**：2026-11-12

## 1. 背景与问题

在将前代 Java 仓库的 33 个模板、28 个 `.rule` 文件、11 个 Skill 与 3 个网关接口迁移到 `agent-python` 的过程中，我们在构建自动化黄金对拍（Golden Harness）时发现了 Java 现网代码中潜伏的多处真实业务逻辑缺陷：
- **R2（`reminder-sms`）**：宽松日期正则将短信中的活动编号 `（编号：25JS206149）。\n1.` 误解析为 `20614901`（2061 年 49 月 1 日），由于 `20614901 > 20271201`，导致所有带编号的订购短信在现网永远查不到提醒短信；
- **R8（`qry-balance`）**：日期过滤正则回溯把纯年月入参 `202607` 拆成 `20260007`，导致传纯账期时查出的充值流水被 100% 误删；
- **R5（`pretty-number-info`）**：不校验返回记录 `msisdn` 是否等于被查号码、`grade` 为空时仍判为“靓号”、多档次活动名称无分隔符粘连；
- **R17（模板 `120` `有设备押金` 与模板 `111`/`114`/`115` `违约责任`）**：未找到时填充占位符 `"{{ 字段名 }}"`（非空字符串），导致 `{% if 有设备押金 %}` 或 `{% if 违约责任 %}` 恒为真，无记录分支成为永远不可达的死代码；
- **R7（同名入参告警）**：4 个模板（`106`、`107`、`131`、`132`）同时存在同名字段与入参 `客户号码`，引发混淆与发布校验告警。

团队面临核心抉择：是“为了对拍脚本 100% 机械相等而把 Java 的 Bug 原封不动搬过来”，还是“在保持正常路径等价的前提下主动修复这些已知缺陷”？

## 2. 决策内容

采取 **“一期先用自动化对拍锁定基线（暴露全部隐性差异） → 二期主动修复明确属于实现缺陷的 Bug，并将有意差异显式建档管理”** 的两步走策略：

1. **建立可重复执行的四层自动化校验套件（`tools/java_migration/`）**：
   - `verify_structure.py`：校验模板集合、ID、正文转换、字段/规则覆盖、`validate_all()` **0 error / 0 warning** 以及 AST 布尔占位符守卫（S8）与枚举字面量门禁（S9）；
   - `verify_render.py`：调用真实 Java `PebbleTemplateEngine` 对比数千个枚举与列表组合场景；
   - `check_skills.py`：调用真实 Java `XmlMapper` 逐字节对比网关 XML 报文，并在标准案例上验证契约判定与 Python 原语链输出；
   - `tests/test_migrated_seed.py`：纳入常规 `uv run pytest` 回归保护网。
2. **主动修复全部已证实的 Java 实现缺陷**：
   - 二期直接修复 R2（改用严格日历校验的 `extract_dates`，无日期时直接跳过查询不误取办理日）、R8（改用区分年月与具体日的 `expand_period`）、R5（匹配 `msisdn`、空 `grade` 视为非靓号、多活动名用 `、` 连接、`cc_pretty_num_info_query` 顶层报错严判失败）与 R17（模板 `120` `有设备押金` 及 `111`/`114` `违约责任` 设 `whenMissing: empty`、模板 `115` 补占位符守卫），并移除冗余入参 `客户号码`、补齐 `安装地址`/`标准资费` 推导等级与 `deadlineDate` 入参；
   - 在对拍脚本与 [lint/java-divergence.md](../lint/java-divergence.md) 中明确标注这些**有意修复项（Intentional Fixes）**，不再为了迁就旧版缺陷而扭曲新平台行为。

## 3. 后果与权衡

- **正面收益**：
  - 新平台上线即解决了旧系统长期存在的提醒短信查不出、纯账期无流水、无押金走错话术等高发业务质量问题；
  - 33 个生产模板实现零错误、零警告的干净治理基线。
- **注意事项**：
  - 在与旧版系统做线上灰度双跑比对时，上述修复场景会出现预期内的“新平台填出真实结果 / 走到正确分支、旧系统为空或走错分支”的正向差异，核对人员可查阅 [lint/java-divergence.md](../lint/java-divergence.md) 快速甄别。

## 相关页面

- [Java 行为差异与二期主动修复台账](../lint/java-divergence.md)
- [Java 资源迁移与一致性对拍指南](../guides/java-migration-and-verification.md)
- [reminder-sms：提醒短信与提醒日期](../skills/reminder-sms.md)
- [qry-balance：充值流水](../skills/qry-balance.md)
- [pretty-number-info：靓号信息](../skills/pretty-number-info.md)
