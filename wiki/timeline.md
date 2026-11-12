---
title: 项目演进时间线
type: overview
tags: [timeline, history, migration, milestones]
sources:
  - src/report_agent/runtime/runner.py
  - src/report_agent/store/runtime_config.py
  - tools/java_migration/README.md
  - tools/java_migration/MAPPING.md
updated: 2026-11-12
---

# 项目演进时间线

<!-- #Created By AiCoding(codex) -->

本页梳理 `agent-python`（`report-agent`）从第一阶段平台底座搭建，到全量承接前代 Java 版（`pdf-agent-parse`）业务资产，再到二期确定性原语增强与历史缺陷治理的完整演进脉络。

## 阶段一：全栈单智能体底座与 Git 版本化工作台搭建（`035997c`）

- **目标**：用 Python 3.13 + FastAPI + Pydantic AI 从零构建“零业务硬编码”的报告生成与资源治理平台，替代 Java 版复杂的三 Agent 编排、Groovy 脚本与 Oracle 资源表。
- **核心成果**：
  - 建立 `AgentRunner` 单智能体运行管道、动态 Pydantic 交卷模型 `build_report_model` 与 `EvidenceChecker`（`quote` / `input` / `derive` 三级证据核验 + 重试退回 + 部分挽救）。
  - 实现基于内部 Git 仓库（`repo/`）+ 不可变发布目录（`releases/rN/`）+ `releases/current` 原子软链接的资源治理体系，支持草稿叠加视图（`drafts/`）与乐观锁并发控制。
  - 完成 Vue 3 + TypeScript + Element Plus + CodeMirror 6 可视化工作台（`frontend/`），打通模板编辑、SSE 实时轨迹试运行、证据溯源高亮与版本发布回退闭环。

## 阶段二：运行期配置热重载、多形态网关解析与深度安全加固（`513ce23`）

- **目标**：满足生产运维免重启调优模型/网关参数、对接异构 JSON/XML 接口响应以及通过安全基线审计的要求。
- **核心成果**：
  - 新增 `RuntimeConfigStore`（`config/runtime/`，文件权限强制 `0600`）与引用计数平滑排空的 `ReloadableGatewayClient`，支持在线修改并回退 LLM 模型参数、网关地址与模式而在途请求不断流。
  - 扩充声明式接口契约 `domain/api_contract.py`：新增 `unified-gateway-json` 连接器、`RecordsSpec.mode`（`auto` / `object` / `list` / `scalar` / `none`）、嵌套扁平化 `flatten`、点分列抽取与内置动态时间占位符 `${$now}`。
  - 安全加固：XML 解析器挂载 `expat` 钩子阻断 `DOCTYPE` / `ENTITY` 防止 XXE 与 Billion Laughs 攻击；会话鉴权启用 PBKDF2-HMAC-SHA256（60 万次迭代）、HttpOnly `SameSite=Strict` Cookie 与连续失败 5 次锁定 5 分钟机制；`RunStore` 改造为单异步协程顺序写队列防止并发写坏 `index.jsonl`。

## 阶段三：Java 全量业务资产自动化迁移与四层对拍体系落地

- **目标**：将 Java 仓库（`pdf-agent-parse`）线上全部 33 个报告模板、11 个业务 Skill 与 3 个统一网关接口完整迁移至 `src/report_agent/seed/`，并用自动化工具证明等价性。
- **核心成果**：
  - 构建 `tools/java_migration/` 迁移工程：`generate.py` 读取 Java 模板、`*.rule`、`field-mappings.yml` 与 `field_catalog.yaml`，机械转换 Pebble 语法（`elseif -> elif`、`null -> none`）并生成 33 套 `template.yaml` + `body.md.j2`（ID `100`～`132`）。
  - 定制 `domain/jinja_env.py`（`_pebble_newline_trim` 控制行裁剪、`hasDigit` 函数、`TrackedValue` 分支追踪）与 `gateway/unified_xml.py`（Jackson 3 字母序顶层标签与 `xsi:nil="true"` 风格）。
  - 落地 `verify_structure.py`、`verify_render.py`（调用真实 Java `PebbleTemplateEngine` 逐字比对数千组合场景）与 `check_skills.py`（字节级比对 XML 请求报文与 Groovy 标准输出）。

## 阶段四：二期确定性工具扩充、列表空值追踪与 Java 历史缺陷主动治理

- **目标**：消除迁移阶段识别出的模型心算风险（R3）、列表字段空数组与缺失混淆问题，并主动修复前代 Java Groovy 脚本与模板中的多处线上历史缺陷，实现 **33 个模板 0 error / 0 warning** 高质量收口。
- **核心成果**：
  - **列表字段语义精确化**：区分合法 0 行查询结果（`status="found", value=[]`，核验工具/接口成功证据，渲染为 `SUCCESS`）与入参缺失/接口报错导致的 `status="not_found"`；新增 `TrackedList` 追踪 `{% for %}` 实际迭代分支，使正文中实际展示的缺失列表准确触发 `PARTIAL` 状态。
  - **平台确定性原语扩容至 12 个**：新增 `extract_dates`、`date_shift`、`expand_period`、`time_diff`、`regex_extract` 5 个工具，并为 `query_result` 扩充 `startsWith`、`between`、`prefixLen`、`anyOf`（OR 条件组）与 `resultIds`（跨月多结果集合并过滤排序），全面接管 Skill 中的日历运算、秒差排序与正则捕获。
  - **主动修复 Java 历史缺陷**：
    - 修复 `reminder-sms`（R2）将活动编号 `25JS206149` 误识别为 `20614901` 导致永远查不到提醒短信的缺陷；
    - 修复 `qry-balance`（R8）纯年月入参 `202607` 正则回溯为 `20260007` 误删全部充值流水的缺陷；
    - 修复 `pretty-number-info`（R5）不核对本机号码、空 `grade` 误判靓号及多档次活动名无分隔符拼接问题；
    - 修复模板 `120`（`宽带业务续约争议类`）字段 `有设备押金` 因 `whenMissing: placeholder` 使 `{% if 有设备押金 %}` 恒真、`{% else %}` 分支永远死代码的缺陷；
    - 清理模板 `106`、`107`、`131`、`132` 中冗余的同名入参 `客户号码`，消除全部 `FIELD_SAME_AS_INPUT` 告警。

## 相关页面

- [项目总览](overview.md)
- [确定性平台工具设计](architecture/deterministic-tools.md)
- [强证据核验机制](architecture/evidence-system.md)
- [ADR-005：Java 生产资源自动化迁移对拍体系与二期历史缺陷主动修复决策](decisions/adr-005-java-migration-and-bug-fixes.md)
- [Java 行为差异与二期主动修复台账](lint/java-divergence.md)
