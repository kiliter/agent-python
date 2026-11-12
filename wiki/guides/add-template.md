---
title: 新增与维护报告模板实操指南
type: guide
tags: [guide, template, jinja2, evidence, workbench]
sources:
  - src/report_agent/domain/template.py
  - src/report_agent/domain/jinja_env.py
  - src/report_agent/runtime/evidence.py
  - docs/frontend-api-handoff.md
updated: 2026-11-12
---

# 新增与维护报告模板实操指南

<!-- #Created By AiCoding(codex) -->

本指南面向业务维护人员与开发智能体，说明如何通过工作台界面或文件目录新建/调整一份申告报告模板，并避开证据校验与 Jinja2 条件分支的常见陷阱。

## 1. 两种维护途径

1. **推荐：通过 Vue 3 工作台在线编辑（运行期常规方式）**
   - 进入「模板管理」新建或复制模板 → 在「模板工作台（`/workbench`）」编辑正文、字段、入参、关联 Skill → 在「试运行」页签用真实或 Mock 单据验证 SSE 轨迹与证据溯源 → 点击「发布」生成新版本 `rN`。
2. **随包初始种子维护（修改 `src/report_agent/seed/templates/<id>/`）**
   - 仅用于变更首次初始化（`report-agent init`）时的内置资源；已初始化的 `DATA_DIR` 不会因修改 `seed/` 而自动覆盖。

## 2. 字段设计黄金法则（`template.yaml`）

### 2.1 选择正确的字段类型（`type`）

| `type` | 适用场景 | 必填附加属性 |
|--------|----------|--------------|
| `string` | 短信原文、套餐名、违约金条款、金额数字等自由文本 | — |
| `enum` | 固定有限取值的判定项（如 `受理渠道: [热线, 掌上营业厅, 其他]`、`是/否`） | `values: [...]`（至少 1 项） |
| `date` | 需要特定展示格式的日期（如 `2026年11月5号` 或 `2026-11-05`） | 强烈建议配置 `format`（如 `yyyy年M月d号`），平台会在交卷时强制校验格式并引导模型用 `format_date` |
| `list` | 多条流水或多月聚合记录（正文中用 `{% for item in 列表 %}` 遍历） | `columns: [{name, type, values?, description}]` |

### 2.2 选择恰当的证据等级（`evidence`）

- **`quote`（原文逐字引用，首选）**：凡是值应该原封不动出现在接口记录或单据里的字段一律选 `quote`；如果是**短信完整正文**，务必同时勾选 **`quoteWhole: true`**，防止模型截头去尾。
- **`input`（入参直取）**：直接搬运上游 `params`（或仅做日期格式转换）的字段（如 `商品名称` 取自入参 `业务名称`）。
- **`derive`（规则推导）**：需要模型根据关键词有无、数值对比或多行拼接得出结论的字段（如枚举判定、`账期短信提醒列表`、多档次顿号拼接的 `靓号活动名称`）。

### 2.3 正确配置缺失策略（`whenMissing`）——避开布尔条件死分支陷阱！

- 若字段在正文中直接打印 `{{ 违约金金额 }}` 且缺失时需要人工补填 → 选 `placeholder`（输出 `{{违约金金额}}`）。
- 若字段有明确业务兜底值（如 `受理渠道` 兜底 `其他`、`手机号类别` 兜底 `非靓号`） → 选 `value` 并填 `defaultValue`。
- **关键避坑**：若模板正文写了布尔真值判断 `{% if 有设备押金 %}押金{{有设备押金}}元{% else %}押金0元{% endif %}`，该字段的 `whenMissing` **必须设为 `empty`**（若该字段在其它段落仍需打印 `{{字段名}}` 占位符，则必须在条件中显式写 `{% if 字段名 and 字段名 != "{{字段名}}" %}`）！如果误设为 `placeholder` 且无守卫，未找到时变量值是字符串 `"{{有设备押金}}"`（非空字符串在 Jinja2 中布尔值为 `True`），会导致 `{% else %}` 分支永远无法走到（这正是二期修复的模板 `120` `有设备押金` 及模板 `111`/`114`/`115` `违约责任` 历史缺陷，现已由 `verify_structure.py` S8 AST 校验强拦截）。

### 2.4 中间字段（`visible: false`）与避免同名入参

- 如果某字段只出现在 `{% if 受理渠道 == "热线" %}` 条件判断里、或者只作为另一个字段的上游依赖，而正文中从不直接打印 `{{ 受理渠道 }}`，请将其设为 **`visible: false`**。
- **不要让字段 `name` 与 `inputs.key` 完全同名**：否则静态校验会产生 `FIELD_SAME_AS_INPUT` 告警，且容易让智能体混淆 `{"type": "input"}` 与 `{"type": "field"}` 证据（例如入参统一叫 `手机号码`，报告字段叫 `客户号码`）。

## 3. Jinja2 正文编写规范（`body.md.j2`）

1. **理解 Pebble 兼容换行规则**：Jinja2 环境开启了 `trim_blocks=True` 与 `_PebbleNewlineTrimExtension`，会自动去掉每个 `{% ... %}`、`{# ... #}` 及 `{{ ... }}` 标签后紧跟的单个换行符（与 Pebble 3.2.2 完全一致）。编写多分支模板时将控制标签独立成行即可保持紧凑排版，也可随时用工作台实时预览核对空行。
2. **判断数字金额用 `is hasDigit` 测试**：如 `{% if 违约金标准 is hasDigit %}违约金为{{违约金标准}}{% endif %}`，当字段未找到保留占位符时会自动返回 `False`。
3. **列表字段空结果与失败状态说明**：
   - 正文请直接写 `{% for item in 充值流水 %}...{% else %}...{% endfor %}`（**不要**外包 `{% if 充值流水 %}`，否则当列表处于 `not_found` 为空列表时 `{% if %}` 会短路跳过循环，导致 `TrackedList.__iter__` 未触发而漏判 `PARTIAL`；发布校验也会给出 `LIST_IN_IF_CONDITION` 告警）；
   - 当智能体核查各月接口均正常但无记录时，提交 `status="found", value=[]`，循环输出 0 次（或走 `{% else %}`）且整单状态为 `SUCCESS`；当接口报错提交 `not_found` 且正文走到了 `{% for %}` 分支时，平台 `TrackedList` 会自动将该单标为 `PARTIAL` 提醒复核。

## 4. 发布前检查清单

保存草稿后调用发布弹窗（底层 `POST /api/v1/templates/{id}/validate`）确认：
- [ ] `errors` 列表为空（无 Jinja2 语法错误、无正文中未定义的 `{{变量}}`）；
- [ ] `warnings` 列表为空（无未使用的僵尸字段、无与入参重名的字段）；
- [ ] 使用至少 1 条正例和 1 条缺数据反例完成在线「试运行」，确认时间线无 `report_rejected` 反复打回，且每个字段点击后右侧能精准高亮对应证据源。

## 相关页面

- [模板模型与渲染机制](../architecture/template-and-rendering.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [新增纯文本 Skill 与声明式网关接口契约指南](add-skill-and-api.md)
- [Vue 3 资源工作台前端剖析](../components/workbench-frontend.md)
