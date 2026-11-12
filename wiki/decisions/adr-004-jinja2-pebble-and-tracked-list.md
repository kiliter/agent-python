---
title: ADR-004：采用 Jinja2 沙箱对齐 Pebble 渲染语义，并以 TrackedValue / TrackedList 精确判定报告完整度
type: decision
tags: [decision, adr, jinja2, pebble, tracked-value, tracked-list, rendering]
sources:
  - src/report_agent/domain/jinja_env.py
  - src/report_agent/runtime/render.py
  - src/report_agent/runtime/runner.py
  - tools/java_migration/verify_render.py
updated: 2026-11-12
---

# ADR-004：采用 Jinja2 沙箱对齐 Pebble 渲染语义，并以 `TrackedValue` / `TrackedList` 精确判定报告完整度

<!-- #Created By AiCoding(codex) -->

- **状态**：已采纳（Accepted）
- **决策日期**：2026-11-12

## 1. 背景与问题

在将 33 个线上模板从 Java Pebble `3.2.2` 迁移至 Python 生态时，面临两项关键技术挑战：

1. **渲染逐字等价性要求**：上游工单系统与质检规范对报告的段落换行、标点与条件分支输出非常敏感。Jinja2 默认的 `trim_blocks` 行为与 Pebble 的独立控制行裁剪规则存在细微但广泛的换行差异，且模板中使用了 Pebble 自定义函数 `hasDigit(...)`。
2. **条件分支下的运行状态误判问题**：一个综合模板可能定义了 20 多个字段，但针对某笔“热线渠道、无违约金、无终端捆绑”的投诉，模板正文的 `{% if %}` 分支实际上只输出了其中 8 个字段。如果按“全表所有 `visible` 字段是否都找到”来判断运行成功与否，其余 12 个根本不需要出现在报告里的 `not_found` 字段会让几乎所有工单都被误标为 `PARTIAL`；反之，对于列表字段（`type: list`），如果列表因接口故障处于 `not_found`，直接传入普通空列表 `[]` 又会导致 `{% for %}` 静默跳过、漏报 `PARTIAL`。

## 2. 决策内容

1. **Jinja2 沙箱定制兼容 Pebble（`domain/jinja_env.py`）**：
   - 使用 `ImmutableSandboxedEnvironment` 子类 `_TrackedSandboxEnvironment` 杜绝模板修改列表或调用任意属性；
   - 实现 `trim_blocks=True` + `_PebbleNewlineTrimExtension` 词法扩展：对齐 Pebble 3.2.2 默认 `newLineTrimming`，去掉 `{% %}`、`{# #}` 与 `{{ }}` 标签后紧跟的单个换行，并注册 `hasDigit` 测试（`is hasDigit`）；
   - 迁移正文时仅机械替换标签内的 `elseif -> elif` 与 `null -> none`，并用 `verify_render.py` 驱动真实 Java `PebbleTemplateEngine` 对拍全组合场景。
2. **用 `TrackedValue` 与 `TrackedList` 在渲染期动态收集 `used_fields`**：
   - 标量字段包装为 `TrackedValue(str)`：参与 `{% if %}` 比较不记展示，仅在 `{{ 字段 }}` 经 `finalize` 输出到正文时才加入 `used_fields`；
   - 列表字段包装为 `TrackedList(list)`：参与 `{% if 列表 %}` 布尔测试不记展示，仅在真正进入 `{% for item in 列表 %}` 调用 `__iter__`（或直接 `{{ 列表 }}`）时加入 `used_fields`；
   - 结合二期列表空值契约（合法 0 行提交 `status="found", value=[]`，缺参/报错提交 `status="not_found"`），精准实现：**查清无记录 → `SUCCESS`；走到的分支里缺字段或漏列表 → `PARTIAL`；未走到的分支缺字段 → 不影响 `SUCCESS`**。

## 3. 后果与权衡

- **正面收益**：
  - 33 个迁移模板与 Java Pebble 渲染输出达到逐字等价（仅除已主动修复的模板 `120` `有设备押金` 与模板 `111`/`114`/`115` `违约责任` 占位符死分支历史缺陷外）；
  - `SUCCESS` / `PARTIAL` 状态具备极高的业务信噪比：`PARTIAL` 真正代表“最终交付给坐席的报告里存在未填出的缺口（`missingShown`）”，可直接作为人工复核队列的分流依据。
- **注意事项**：
  - 模板作者在用字段本身做布尔条件（`{% if 某字段 %}`）时，若希望“字段未找到时走 `{% else %}` 分支”，必须将该字段的 `whenMissing` 设为 `empty`（或在条件中写 `!= "{{某字段}}"` 守卫，不能裸用默认的 `placeholder`）；对于 `list` 字段则应直接用 `{% for ... %}{% else %}{% endfor %}` 而避免外包 `{% if 列表 %}`（静态校验 `LIST_IN_IF_CONDITION` 与 `verify_structure.py` S8 已自动守护）。

## 相关页面

- [模板模型与渲染机制](../architecture/template-and-rendering.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [新增与维护报告模板实操指南](../guides/add-template.md)
- [Java 行为差异与二期主动修复台账](../lint/java-divergence.md)
