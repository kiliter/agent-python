<!-- #Created By AiCoding(codex) Java 模板迁移工具与一致性校验说明 -->
# Java → Python 模板迁移

把 Java 版（`/Users/zhangjialin/IdeaProjects/agent`，Pebble 模板 + rule + Groovy Skill）的全部模板迁移为本项目的内置资源 `src/report_agent/seed/`，消除历史发布警告、修复原样迁移的 Java 缺陷、升级确定性工具用法，并用自动化校验套件持续回归验证。

## 迁移来源

- 模板：`pdf-agent-parse/src/main/resources/template/md/*.md`（33 个）。已核对与 Java 资源库 `AGILE_AGENT.AGENT_TEMPLATE_CFG` 已发布内容逐字一致（全局发布版本 1，无草稿）；模板 ID 100–132 记录在 `template_ids.yaml`，迁移后保持不变。
- 规则：`agent/rule/*.rule`。已核对与 `AGENT_RULE_ITEM_CFG` 一致。
- 字段来源：`agent/config/field-mappings.yml`；Skill：`agent/skills/*`（SKILL.md + assembly/extract.groovy，资源库中同为版本 1）。
- 服务层写死的策略（`IntelligentComplaintServiceImpl`）：受理日期策略、终端信息策略、按业务名称判断单据是否属于本次业务、Skill 值优先。它们已写进字段说明和系统提示词。

## 文件

| 文件 | 作用 |
|---|---|
| `generate.py` | 模板生成器（可重复执行）：`uv run python tools/java_migration/generate.py`。它整体重建 `seed/templates/`，并更新 `TEMPLATES.md` |
| `field_catalog.yaml` | 字段语义映射表：类型、证据、找不到时的处理、取值方法，以及按模板的覆盖项。修改字段定义改这里，再重新生成 |
| `template_ids.yaml` | 模板编码与 Java 资源库 ID 的对应表 |
| `TEMPLATES.md` | 逐模板对照表：字段数、中间字段、列表字段、Skill、入参，以及 Java 自己也忽略的 rule |
| `MAPPING.md` | Skill 与接口契约的对照表、二期已修复的 Java 缺陷及预期差异说明（R1–R17） |
| `verify_structure.py` | 一致性校验①：模板集合与 ID、正文机械转换、字段集合与 visible、rule 原文、Skill 覆盖、列表列、发布校验（要求 **0 errors, 0 warnings**） |
| `verify_render.py` | 一致性校验②：同一组字段值分别交给 Java 真实的 `PebbleTemplateEngine.render()` 和 Python 生产渲染路径，逐字比对（含模板 120 `有设备押金` 缺失分支修复验证） |
| `check_skills.py` | 一致性校验③：3 个接口的报文与 Java `xml-nytool` 逐字比对；11 个 Skill 使用平台确定性原语在 mock 数据上与 Groovy 输出对拍，并专项验证已修复的 4 类历史缺陷 |
| `smoke_run.py` | 端到端冒烟：真实大模型 + mock 网关试运行指定模板 |
| `analyze_java.py` | 分析 Java 模板变量与 rule（只用于人工审查） |
| `harness/*.java` | Java 侧标准答案程序。运行时自动编译，需要 JDK 21 和 Java 工程的 `target/classes`、`release/.../lib` |

`tests/test_migrated_seed.py` 已把上面的校验接入 `pytest`。Java 工程或 JDK 不在本机时，相关外部对拍用例自动跳过。

## 迁移规则

- **正文**：只做机械转换。`{% %}` 标签内 `elseif`→`elif`、`null`→`none`，换行统一为 LF，其余字符不动。
- **平台渲染对齐 Pebble**：
  - 每个标签（`{% %}`、`{# #}`、`{{ }}`）后面的一个换行会被去掉。
  - 新增 `hasDigit` 测试。
  - 新增 `list` 字段类型与 `TrackedList` 迭代追踪，区分合法空列表（`status="found", value=[]` → `SUCCESS`）与缺失列表（`status="not_found", value=null` → 生效分支遍历时标为 `PARTIAL`）。
- **字段集合**：等于 Java 正文中的全部变量，再加上 Java 的隐式依赖字段（rule 里 `{{受理渠道}}` 这类引用、映射为 SKILL 的字段），后者作为中间字段。
- **找不到时**：默认保留占位符，与 Java 一致。Java 链路保证一定有值的字段用默认值：受理渠道=其他、是否录音=|其他、有终端捆绑=false、手机号类别=非靓号、机卡匹配要求/安装地址=无、是否有套餐外扣费=否；需要置空的字段（如模板 120 `有设备押金`、列表字段）用 `whenMissing: empty`。
- **入参**：以当前系统中文入参名为准，全部非必填，不注入与正文字段重名的 `客户号码` 入参，发布校验保持 `0 errors, 0 warnings`。

## 二期已修复的 Java 缺陷与预期差异（详见 `MAPPING.md`）

1. **缺失占位符与换行**：Java 是 `{{ 字段 }}`，Python 是 `{{字段}}`；输出换行为 LF。
2. **列表字段空值 vs 缺失语义（R4）**：Java 中缺失列表会导致 Pebble 抛出 `Not an iterable object`；Python 区分接口成功无匹配行（提交 `status="found", value=[]`，状态 `SUCCESS`）与缺参/接口失败（提交 `status="not_found", value=null`，渲染为空且生效分支遍历时标记 `PARTIAL`）。
3. **入参收敛与零警告（R7）**：Python 只使用当前系统定义的中文入参名（`qry-balance` 号码优先级为 `充值号码` → `手机号码`；`pretty-number-info` 直接用 `手机号码`），彻底消除模板 106、107、131、132 的 `FIELD_SAME_AS_INPUT` 警告。
4. **已修复的 Java 逻辑与模板缺陷**：
   - **`reminder-sms` 活动编号误识为日期（R2）**：改用 `extract_dates` + `date_shift`，`（编号：25JS206149）。\n1.` 正确提取真实日期 `20271201`，不再误算成 `20614901`。
   - **`qry-balance` 纯年月回溯缺陷（R8）**：改用 `expand_period` + `query_result(resultIds, between)`，传入 `充值时间="202607"` 自动展开为 `20260701`～`20260731`，不再回溯成 `20260007` 丢光整月流水。
   - **模板 120 `{% if 有设备押金 %}` 死分支（R17）**：`有设备押金` 改为 `whenMissing: empty`，缺失时正确进入 `{% else %}` 输出 `- 无{{商品名称}}设备押金记录。`。
   - **`pretty-number-info` 号码核对与空 `grade` 判定（R5）**：按 `msisdn == 手机号码` 精确匹配，无匹配或 `grade` 为空时判为非靓号，多档 `event_name` JSON 数组提取非空项按 `、` 拼接。
