---
title: Java 资源迁移与一致性对拍指南
type: guide
tags: [guide, java-migration, pebble, verification, harness]
sources:
  - tools/java_migration/README.md
  - tools/java_migration/generate.py
  - tools/java_migration/field_catalog.yaml
  - tools/java_migration/verify_structure.py
  - tools/java_migration/verify_render.py
  - tools/java_migration/check_skills.py
  - tools/java_migration/smoke_run.py
updated: 2026-11-12
---

# Java 资源迁移与一致性对拍指南

<!-- #Created By AiCoding(codex) -->

`tools/java_migration/` 目录提供了一整套可重复执行的迁移生成与四层黄金标准对拍（Golden Harness）工具链，用于在对齐或演进自前代 Java 仓库（默认读取 `/Users/zhangjialin/IdeaProjects/agent`，可通过环境变量 `JAVA_AGENT_HOME` 指定）的 33 个模板、11 个 Skill 与 3 个接口契约时提供数学级信心保障。

## 1. 目录文件分工

| 文件 / 目录 | 作用 |
|------------|------|
| `template_ids.yaml` | 33 个模板编码到 Java 资源库 `AGENT_TEMPLATE_CFG` 真实主键 ID（`100`～`132`）的固定映射 |
| `field_catalog.yaml` | 所有模板字段的精细语义字典（类型 `string`/`enum`/`date`/`list`、枚举值、列表列定义、证据模式 `quote`/`input`/`derive`、`quoteWhole`、`whenMissing`、补充提取指引） |
| `generate.py` | 读取 Java `template/md/*.md`、`agent/rule/*.rule`、`field-mappings.yml` 与 `field_catalog.yaml`，自动生成 `src/report_agent/seed/templates/100..132/` 与对照表 `TEMPLATES.md` |
| `verify_structure.py` | 静态结构与发布零告警检查（无需 JDK 与大模型） |
| `verify_render.py` | 调用真实 Java `PebbleTemplateEngine` 与 Python Jinja2 沙箱做数千场景逐字渲染比对 |
| `check_skills.py` | 校验 Skill/契约 Schema，并调用 Java `XmlMapper` 与 `GroovyScriptEngine` 对拍报文与逻辑 |
| `smoke_run.py` | 在临时数据目录副本上使用真实大模型 + Mock 网关端到端试跑指定模板 |
| `harness/*.java` | `PebbleRenderHarness.java`、`JavaXmlRequestHarness.java`、`JavaSkillGoldenHarness.java` 三个反射/引擎桥接驱动 |

## 2. 四层验证操作步骤

### 第一层：重新生成模板（修改 `field_catalog.yaml` 或 `generate.py` 后）

```bash
uv run python tools/java_migration/generate.py
```
> 注意：`generate.py` 只重写 `seed/templates/` 与 `tools/java_migration/TEMPLATES.md`，**不会**覆盖手工精调过的 `seed/skills/` 与 `seed/apis/`。

### 第二层：静态结构与发布校验（`verify_structure.py`）

```bash
uv run python tools/java_migration/verify_structure.py
```
逐项检查 `S1`～`S7`：
- `S1`：33 个模板集合与 ID 一一对应；
- `S2`：`body.md.j2` 与 Java 模板经 `elseif -> elif`、`null -> none` 转换后逐字相等；
- `S3`：字段集合覆盖全部正文变量与隐式 Skill 依赖字段，且 `visible` 标记准确；
- `S4`：Java `.rule` 中每条有效规则原文均完整保留在对应字段 `description` 中；
- `S5`/`S6`：Skill 依赖闭包完整、接口引用存在、`{% for %}` 循环属性均在 `list` 字段列定义中；
- `S7`：全量资源 `validate_all()` **0 error、0 warning**。

### 第三层：网关报文、Skill 逻辑与 Pebble 逐字渲染对拍

当本机存在前代 Java 编译产物（`pdf-agent-parse/target/classes`）与本地 Maven 仓库（`~/.m2/repository`）及 JDK `javac`/`java` 时，脚本自动编译运行 Java Harness：

```bash
# 对拍 3 个接口 XML 请求报文（字节级一致）及 11 个 Skill 原语逻辑（自动豁免登记的有意修复项）
uv run python tools/java_migration/check_skills.py

# 对拍 33 个模板在全找到、全缺失、枚举全组合、列表 0/1/3 行下的渲染文本（自动识别模板 120 有设备押金修复差异）
uv run python tools/java_migration/verify_render.py
```

若 CI 机器未挂载 Java 仓库或 JDK，`tests/test_migrated_seed.py` 会自动执行纯 Python 侧的全量契约、结构与核心渲染校验并优雅跳过外部 JVM 调用。

### 第四层：真实大模型端到端冒烟（`smoke_run.py`）

配置好 `.env` 中的 `LLM_API_KEY`、`LLM_BASE_URL` 与 `LLM_MODEL` 后：

```bash
# 默认试跑模板 101，也可传任意模板 ID（如 112 合约延续、118 套餐变更、119 套餐费用）
uv run python tools/java_migration/smoke_run.py 101
```
脚本会自动把 `DATA_DIR`（保留 `releases/current` 软链接）拷入临时目录、强制 `gateway_mode="mock"` 执行完整推理与证据核验，打印每个字段的回填值、是否触发重试退回以及最终报告，跑完自动清理临时目录，绝不污染本地数据。

## 相关页面

- [ADR-005：Java 生产资源自动化迁移对拍体系与二期历史缺陷主动修复决策](../decisions/adr-005-java-migration-and-bug-fixes.md)
- [Java 行为差异与二期主动修复台账](../lint/java-divergence.md)
- [33 个生产模板完整清单](../reference/templates-catalog.md)
- [本地开发、测试与部署指南](dev-test-and-deploy.md)
