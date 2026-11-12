---
title: 核心领域与平台工程术语表
type: reference
tags: [reference, glossary, terminology]
sources:
  - src/report_agent/domain/template.py
  - src/report_agent/runtime/evidence.py
  - src/report_agent/domain/jinja_env.py
  - src/report_agent/store/releases.py
updated: 2026-11-12
---

# 核心领域与平台工程术语表

<!-- #Created By AiCoding(codex) -->

| 术语 | 英文 / 代码符号 | 定义说明 |
|------|-----------------|----------|
| **单据文本** | `document` / `documentText` | 上游系统传入的电子协议单或工单附件纯文本内容（平台不做 PDF 二进制解析，按行编为 `L001`、`L002` 供单据引用溯源） |
| **交卷工具** | `submit_report` | 由 `build_report_model` 根据模板字段动态生成的严格 JSON Schema 工具，智能体在完成全部取数推理后调用它一次性提交所有字段值、证据与推理 |
| **原文引用证据** | `evidence: quote` | 最严格的证据等级：要求提交值必须在被引用的接口单元格或单据片段中逐字连续出现 |
| **整条引用** | `quoteWhole: true` | `quote` 的加强约束：要求提交值去掉首尾空白换行后与接口单元格全文完全相等，专门用于短信正文防截断 |
| **值转换工具白名单** | `VALUE_TOOLS` | 当 `derive` 字段在证据中引用该白名单内的确定性工具 `callId` 时，要求提交值必须严格等于该次工具输出的 `value`（当前仅包含 `{"format_date"}`） |
| **运行工作区** | `Workspace` | 单次请求隔离的内存账本，存放完整网关记录（`r1`..`rN`）、工具调用日志（`t1`..`tN`）与 SSE 过程事件 |
| **追踪标量 / 追踪列表** | `TrackedValue` / `TrackedList` | 渲染期的 `str` / `list` 子类包装器：仅在模板真正输出 `{{字段}}` 或进入 `{% for item in 列表 %}` 迭代时才把字段计入 `used_fields`，用于精准判定 `SUCCESS` 与 `PARTIAL` |
| **实际展示缺失字段** | `missingShown` | 正文已命中分支实际展示出来、但状态为 `not_found` 的字段名列表；`missingShown` 非空是运行状态判为 `PARTIAL` 的充要条件 |
| **级联降级** | `_cascade_degraded_fields` | 当某上游字段因证据核验失败被强制降为 `not_found` 时，自动将所有通过 `{"type":"field"}` 引用它的下游字段一并递归降为 `not_found` |
| **线上版本号** | `onlineRev` / `liveRev` | 全局发布版本号形如 `r1`, `r2`...；`liveRev` 指当前 `releases/current` 软链指向的全局版本，单资源的 `onlineRev` 指最后一次改动该资源的版本号 |
| **基线漂移** | `drift` (`baseRev != onlineRev`) | 草稿编辑期间他人发布了同一资源的新版本，导致当前草稿基于的 `baseRev` 落后于最新 `onlineRev` |
| **引用计数排空** | `ReloadableGatewayClient` | 在线热重载网关配置时，让旧槽位上的在途 HTTP 请求执行完毕后再自动关闭连接池的无损切换机制 |

## 相关页面

- [项目总览](../overview.md)
- [强证据核验机制](../architecture/evidence-system.md)
- [模板模型与渲染机制](../architecture/template-and-rendering.md)
- [文件化资源存储与 Git 原子发布机制](../architecture/resource-release-and-store.md)
