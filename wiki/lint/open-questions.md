---
title: 待业务确认事项与演进议题
type: lint
tags: [lint, open-questions, roadmap, business-rules]
sources:
  - tools/java_migration/MAPPING.md
  - tools/java_migration/TEMPLATES.md
  - docs/frontend-api-handoff.md
updated: 2026-11-12
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

## 2. 平台后续演进议题

1. **异步批量回归任务队列**：在后端引入受控并发的后台回归任务执行器与进度推送，打通工作台「回归测试」页的一键全量回归与跨版本字段级对比报告。
2. **读写分离水平扩展模式**：当上游并发调用量需要多容器实例横向扩容时，支持只读推理 Worker 模式（禁用管理写路由，仅监听 `releases/current` 软链变更），将治理工作台写节点与高并发推理节点解耦。

## 相关页面

- [当前架构已知约束与注意事项](known-issues.md)
- [Java 行为差异与二期主动修复台账](java-divergence.md)
- [33 个生产模板完整清单](../reference/templates-catalog.md)
- [3 个内置网关接口契约速查](../reference/apis-catalog.md)
