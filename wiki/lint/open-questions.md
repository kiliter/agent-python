---
title: 待业务确认事项与演进议题
type: lint
tags: [lint, open-questions, roadmap, business-rules]
sources:
  - tools/java_migration/MAPPING.md
  - tools/java_migration/TEMPLATES.md
  - tools/java_migration/verify_structure.py
  - src/report_agent/seed/templates/103/body.md.j2
  - src/report_agent/seed/templates/116/body.md.j2
  - src/report_agent/seed/templates/131/body.md.j2
  - docs/frontend-api-handoff.md
updated: 2026-11-27
---

# 待业务确认事项与演进议题

<!-- #Created By AiCoding(codex) -->

本页记录在代码与迁移规则梳理中发现的、技术上已妥善处理但建议与业务方核对确认的细微口径，以及平台下一阶段的演进方向。

## 1. 待业务侧最终核对的口径细节

1. **历史 `.rule` 文件中未被模板正文引用的孤立规则项（见 `tools/java_migration/TEMPLATES.md` 最后一列）**
   - 在前代 Java 仓库中，有 21 个模板对应的 `.rule` 文件里包含 `编号`、`活动名称`、`活动时间`、`活动内容`、`客户承诺` 等规则条目，但对应的模板 Markdown 正文中根本没有这些 `{{变量}}`（Java 运行时同样忽略了它们）。
   - 当前迁移保持与线上实际模板正文严格一致，未将这些未引用规则生成为冗余字段。后续业务侧修订模板时可确认是否属于早期废弃草稿残留（待业务确认）。

2. **`BOSS_QryBalanceFlowLog` 充值金额单位展示口径**
   - 接口返回的 `amount` 字段在现网样例中如 `5000`，前代 Java Groovy 与当前 Python `qry-balance` 均按原值直填至模板 `充值{{item.充值金额}}元`，不做“分转元”换算。灰度验证真实生产报文时建议再次核对现网网关该接口返回单位究竟是“元”还是“分”（待业务确认）。

3. **网关超时网络层的重试次数策略**
   - 为与前代 Java `WebClient` 默认不重试行为对齐，3 个迁移契约（`querySMSSendInfo`、`BOSS_QryBalanceFlowLog`、`cc_pretty_num_info_query`）当前的 `retry.maxAttempts` 均设为 `1`。由于这 3 个查询接口均为幂等只读接口（`idempotent: true`），生产切流前可由运维决定是否在契约中调为 `2` 以吸收偶发瞬时网络抖动（待业务确认）。

4. **模板 `116`（`增值业务扣费争议处理模板`）源自 Java 原模板的 `受理渠道` 枚举分支失配**
   - 在 `src/report_agent/seed/templates/116/body.md.j2` 第 38 行的条件分支（迁移自前代 Java 原模板，审查报告简记为 `受理渠道 == "合作方平台" or "一级电渠"` 类第三方电渠枚举失配，原模板实际字面量为 `{% elif 受理渠道 == "合作方平台" or 受理渠道 == "电视端" or 受理渠道 == "APP" or 受理渠道 == "短信" %}`）中，比较值不在 `accept-type` 产出的 `受理渠道` 枚举集合 `["热线", "掌上营业厅", "其他"]` 内，因此该 `elif` 分支在 Java 现网与当前 Python 版中均不可达（统一落入后续 `else` 分支）。
   - 为保持与 Java 原模板逐字等价（`S2`），当前未擅自改写该模板正文，并在 `tools/java_migration/verify_structure.py` 的 **S9** 枚举字面量 AST 门禁中将其显式登记为已知历史白名单；后续需业务侧确认是否应合并映射至 `"掌上营业厅"` 或扩展增值业务专属渠道判定规则（待业务确认）。

5. **模板 `131`（`过户业务受阻类`）源自 Java 原模板的三反引号代码围栏包裹控制语句残留**
   - 在 `src/report_agent/seed/templates/131/body.md.j2` 中，原前代 Java 模板使用三反引号代码围栏（`` ``` ``）包裹了 `{% if 手机号类别 == "靓号" %}`、`{% else %}` 与 `{% endif %}` 三处控制语句；控制语句经模板引擎求值消去后，会在最终渲染正文的开头、分支切换处或结尾输出空代码块。
   - 为保持迁移结构校验 **S2** 与 Java 现网输出逐字一致，当前暂未擅自删改模板正文，待业务侧核对下游工单系统是否依赖该围栏分隔或应予以清理（待业务确认）。

6. **模板 `103`（`业务办理告知争议类`）尾部三渠道分支告知话术与附件类型对应关系疑似错位**
   - 在 `src/report_agent/seed/templates/103/body.md.j2` 末尾的 `受理渠道` 三分支段落（第 47～65 行）中：`受理渠道 == "热线"` 分支写“业务受理单已明确标注……”并配二次确认短信附件，`受理渠道 == "掌上营业厅"` 分支写“我公司与客户于{沟通日期}的电话录音第{时间段}处已明确告知……”并配业务办理录音附件，`else`（其他渠道）分支写“办理页面已明确标注……”并配宣传页面附件，告知载体话术与渠道/附件类型的对应关系疑似错位。
   - 目前为保持 **S2** 与 Java 现网原模板逐字一致暂未擅改，待业务侧核对现网模板口径后确认是否调整（待业务确认）。

## 2. 平台后续演进议题

1. **异步批量回归任务队列**：在后端引入受控并发的后台回归任务执行器与进度推送，打通工作台「回归测试」页的一键全量回归与跨版本字段级对比报告。
2. **读写分离水平扩展模式**：当上游并发调用量需要多容器实例横向扩容时，支持只读推理 Worker 模式（禁用管理写路由，仅监听 `releases/current` 软链变更），将治理工作台写节点与高并发推理节点解耦。

## 相关页面

- [当前架构已知约束与注意事项](known-issues.md)
- [Java 行为差异与二期主动修复台账](java-divergence.md)
- [33 个生产模板完整清单](../reference/templates-catalog.md)
- [3 个内置网关接口契约速查](../reference/apis-catalog.md)
