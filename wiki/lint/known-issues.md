---
title: 当前架构已知约束与注意事项
type: lint
tags: [lint, known-issues, constraints, mock, single-process]
sources:
  - src/report_agent/cli.py
  - src/report_agent/gateway/mock.py
  - docs/frontend-api-handoff.md
  - tools/java_migration/MAPPING.md
updated: 2026-11-12
---

# 当前架构已知约束与注意事项

<!-- #Created By AiCoding(codex) -->

本页汇总当前仓库在架构边界、本地调试与工程交接中的已知约束，供研发与运维排障参考。

## 1. 单进程运行约束（`workers=1`）

- **现状**：`src/report_agent/cli.py#serve` 硬编码 `workers=1`。这是因为 `Publisher`（Git 工作区写入与版本号递增锁）、`RunStore`（单协程异步写 `index.jsonl` 队列）、`AuthService`（内存登录失败计数与吊销令牌表）以及 `ReloadableGatewayClient`（内存热更新槽位）均为单进程状态模型。
- **影响与建议**：单进程异步事件循环（`asyncio` + `httpx` 异步 I/O）本身可轻松支撑多路并发大模型与网关请求（默认 `AGENT_MAX_CONCURRENT_RUNS=8`、支持运行期动态扩缩的 `_DynamicLimiter`，网关并发上限 `GATEWAY_MAX_CONCURRENCY=32`；同时登录 PBKDF2 校验已卸载至受限线程池，且 `safe_regex_compile` 拦截嵌套量词 ReDoS，防止阻塞事件循环）。切勿在同一 `DATA_DIR` 上启动多 Worker 进程；若未来吞吐需求超出单机上限，应拆分为“单主治理工作台实例 + 多无状态只读推理副本”。

## 2. 本地 Mock 网关不按时间/账期动态过滤（R15）

- **现状**：`gateway/mock.py#MockGatewayClient` 根据 `{api_name}.{route_value}.xml` 或 `{api_name}.xml` 查找静态响应报文，不会解析请求体内的 `startDate`/`endDate` 或 `cycle` 做服务端过滤。
- **影响**：在 `GATEWAY_MODE=mock` 下调试跨多个自然月查询的模板（如模板 `119` 的 `billing-cycle-sms` 传 `202610$202611`、模板 `106` 的 `qry-balance` 传跨月范围）时，每次月度 `call_api` 都会返回同一份静态 XML。
  - `billing-cycle-sms` 由于按短信自身 `smsSendTime` 前 6 位归属月份，仍能自动去重归位；
  - `qry-balance` 在跨多账期 Mock 调用时，静态样例流水会出现重复行（仅发生在本地静态 Mock 下，真实统一网关按 `cycle` 分月返回，不存在该问题）。

## 3. 批量异步回归任务属于后续阶段能力

- **现状**：单条回归用例的创建（含从真实运行一键转存 `fromRunId`）与在线试跑已完整闭环；但全模板一键批量并发回归对比接口（`docs/frontend-api-handoff.md` 第 3.6 节提及的 `/regression/execute`、`/regression/diffs`）因每条用例均需消耗真实大模型推理，规划为独立后台异步任务队列在后续迭代建设。
- **当前替代方案**：代码与资源改动验证优先运行确定性对拍套件（`verify_structure.py`、`verify_render.py`、`check_skills.py` 与 `uv run pytest`），单模板端到端效果验证使用工作台「试运行」或 `tools/java_migration/smoke_run.py`。

## 4. `docs/frontend-api-handoff.md` 中的历史阶段记录

- `docs/frontend-api-handoff.md` 第 5 节的 `ProcessEvent.type` 表格编写于一期，当时仅列举了最初的 7 个平台工具名；二期平台工具已扩充至 **12 个**（新增 `extract_dates`、`date_shift`、`expand_period`、`time_diff`、`regex_extract`），时间线组件对任意新工具名均通用渲染，以 [确定性平台工具设计](../architecture/deterministic-tools.md) 与 `src/report_agent/runtime/tools.py` 为准。

## 相关页面

- [Java 行为差异与二期主动修复台账](java-divergence.md)
- [待业务确认事项与演进议题](open-questions.md)
- [本地开发、测试与部署指南](../guides/dev-test-and-deploy.md)
- [常见故障排查手册](../guides/troubleshooting.md)
