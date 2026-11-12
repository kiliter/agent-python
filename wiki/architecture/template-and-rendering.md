---
title: 模板模型与渲染机制
type: concept
tags: [architecture, template, jinja2, pebble, tracked-value, tracked-list]
sources:
  - src/report_agent/domain/template.py
  - src/report_agent/domain/jinja_env.py
  - src/report_agent/runtime/render.py
  - tools/java_migration/verify_render.py
updated: 2026-11-12
---

# 模板模型与渲染机制

<!-- #Created By AiCoding(codex) -->

本页介绍报告模板的双文件结构（`template.yaml` + `body.md.j2`）、字段缺失策略、Jinja2 沙箱对前代 Java Pebble 3.2.2 模板引擎的逐字兼容设计，以及基于 `TrackedValue` 与 `TrackedList` 的动态分支展示追踪原理。

## 1. 模板目录结构与领域模型

每个模板存放在独立目录 `templates/<id>/` 下（对应领域对象 `src/report_agent/domain/template.py#Template`）：

1. **`template.yaml`（`TemplateDefinition`）**：
   - 基本信息：`id`（整数，生产迁移模板为 `100`～`132`）、`name`、`description`、`offline`（是否已下线）。
   - `fields`（`list[FieldDef]`）：声明所有正文直接输出或循环内输出单元格的字段（`visible: true`，由 `printed_variables` 校验）与仅用于条件判断或上游传递的中间字段（`visible: false`，如模板 131/132 中的 `受理渠道`）：
     - `type`：`string` | `enum`（配 `values`）| `date`（可选配展示格式 `format`）| `list`（配子列定义 `columns: list[ColumnDef]`）。
     - `evidence`：`quote` | `input` | `derive`；可选 `quoteWhole: bool`。
     - `whenMissing`：标量字段处于 `not_found` 时的渲染回退策略：
       - `placeholder`（默认）：保留字面占位符 `{{字段名}}`；
       - `empty`：渲染为空字符串 `""`（用于可选金额、靓号等级，或 `{% if 有设备押金 %}` 这类靠非空判断真值的条件字段）；
       - `value`：渲染为固定 `defaultValue`（如 `受理渠道` 默认 `其他`，`手机号类别` 默认 `非靓号`；注意 `whenMissing == "value"` 的字段即使未找到已有兜底值，不会计入 `missingShown`）。
   - `inputs`（`list[InputDef]`）与关联 `skills`（`list[str]`）。
2. **`body.md.j2`**：Jinja2 报告正文模板。

## 2. 对齐 Java Pebble 3.2.2 的三项兼容定制（`domain/jinja_env.py`）

1. **`trim_blocks=True` + `_PebbleNewlineTrimExtension` 词法流裁剪**：
   - Pebble 3.2.2 默认开启 `newLineTrimming`，会吞掉每个 `{% %}`、`{# #}` **以及 `{{ }}` 变量输出标签**后面紧跟的**第一个换行符**，而 Jinja2 内置的 `trim_blocks=True` 只处理前两者。
   - `_PebbleNewlineTrimExtension.filter_stream` 在 Jinja2 词法流层面精准识别 `TOKEN_VARIABLE_END`（`}}`）后紧跟的 `TOKEN_DATA`，剥离其开头的单个 `\n`（不开启会误吞缩进的 `lstrip_blocks`，也不影响正文里的字面 `}}`）。
2. **自定义测试 `hasDigit`（`_test_has_digit`）**：
   - 在 `env.tests["hasDigit"]` 注册测试（模板写法如 `{% if 标准资费 is hasDigit %}`），对齐 Java `Character::isDigit`；`None`、`Undefined` 以及不含数字的缺失占位文本 `{{标准资费}}` 均安全返回 `False`。
3. **安全不可变沙箱（`_TrackedSandboxEnvironment`）**：
   - 继承自 `ImmutableSandboxedEnvironment`（禁止在模板中修改 `TrackedList` 或调用危险内省属性），移除 `cycler`/`joiner`/`lipsum`/`namespace` 等全局构造器。

## 3. `TrackedValue` 与 `TrackedList`：精准追踪实际展示字段

通过 `runtime/render.py#field_render` 与 `domain/jinja_env.py#render_body` 协作，平台在单次渲染中动态收集真正展示在报告中的字段集合 `used`：

### 3.1 标量包装器 `TrackedValue(str)` + `_TrackedCodeGenerator`

- **条件判断不记展示**：在 `{% if 受理渠道 == "热线" %}` 中做比较或布尔求值时不会经过 `finalize`，不记入 `used`；
- **字符串拼接与滤镜不断链**：重写 `strip`/`replace`/`lower`/`+` 并定制编译器 `_TrackedCodeGenerator`（拦截 Jinja2 `~` 拼接 `visit_Concat` 与 `+` 运算），确保 `{{ 字段A ~ 字段B }}` 拼接后仍保留所有关联字段名并在最终 `finalize` 输出时一并记入 `used`。

### 3.2 列表包装器 `TrackedList(list)` + `_ACTIVE_USED`

- **`{% if 列表 %}` 仅调 `bool()`（走 `__len__`）**：不会触发 `__iter__`，因此不会把未走到的列表误记为已展示；
- **`{% for item in 列表 %}` 触发 `__iter__`**：`_TrackedTemplate.render` 通过 `ContextVar`（`_ACTIVE_USED`）绑定当前环境的 `used` 集合。一旦生效分支执行 `{% for %}` 迭代 `TrackedList`，`__iter__` 立即将列表字段名写入 `active_used`：
  - 合法空列表（`status="found", value=[]`）：`missing=False`，状态为 `found`，不进 `missingShown` → **`SUCCESS`**；
  - 缺失列表（`status="not_found", value=None`）：`missing=True`，若模板生效分支遍历了该列表（且 `visible: true`），则进入 `missingShown` → **`PARTIAL`**；若该 `{% for %}` 位于未命中的 `{% if %}` 分支内未执行，则不进入 `used`，不影响 **`SUCCESS`**。

## 相关页面

- [单智能体请求处理管道](request-pipeline.md)
- [强证据核验机制](evidence-system.md)
- [ADR-004：采用 Jinja2 沙箱对齐 Pebble 渲染语义，并以 TrackedValue / TrackedList 精确判定报告完整度](../decisions/adr-004-jinja2-pebble-and-tracked-list.md)
- [新增与维护报告模板实操指南](../guides/add-template.md)
- [33 个生产模板完整清单](../reference/templates-catalog.md)
