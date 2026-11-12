---
title: ADR-003：采用文件系统 + 内部 Git 版本库 + releases/current 原子软链替代关系型数据库资源表
type: decision
tags: [decision, adr, store, git, symlink, release]
sources:
  - src/report_agent/store/layout.py
  - src/report_agent/store/git_repo.py
  - src/report_agent/store/releases.py
  - src/report_agent/store/publisher.py
updated: 2026-11-12
---

# ADR-003：采用文件系统 + 内部 Git 版本库 + `releases/current` 原子软链替代关系型数据库资源表

<!-- #Created By AiCoding(codex) -->

- **状态**：已采纳（Accepted）
- **决策日期**：2026-11-12

## 1. 背景与问题

前代 Java 版在后期引入了 7 张关系型数据库表（开发环境兼容老旧的 Oracle 11.2 `ojdbc8:19.32`，生产环境对接 OceanBase Oracle 模式）存放模板、规则、Skill、字段映射与全局发布版本号，每次请求轮询一次 `AGENT_PUBLISH_VERSION_CFG` 表判断快照是否需要重建。该方案带来了显著的运维与开发负担：
- 本地启动、CI 测试与新环境交付都强依赖外部 Oracle/OceanBase 实例与 DBA 手工执行 DDL；
- 模板正文、YAML 与 Markdown 本质上是结构化文本文档，塞进数据库 CLOB 字段后做跨版本行级 Diff、按单资源独立保存草稿、按任意历史版本恢复快照都需要编写繁琐的 SQL 状态表逻辑。

## 2. 决策内容

去除所有关系型数据库依赖，采用 **本地持久化卷（`DATA_DIR`）+ 内部 Git 仓库（`repo/`）+ 不可变版本目录（`releases/rN/`）+ POSIX 原子软链切换（`releases/current`）**：

1. **草稿与线上物理隔离**：未发布的修改独立写入 `drafts/<kind>/<key>/`（配 `.meta.json` 乐观锁 `revision`），工作台通过内存 Overlay 生成 `"draft"` 叠加快照试运行，绝不污染线上；
2. **Git 作为唯一版本真相源**：单资源发布时，将草稿拷入 `repo/`，经全树 `validate_all()` 零错误校验后提交 Git Commit（附结构化 `Rev` / `Operator` Trailers）；
3. **不可变快照与无锁原子切换**：每次发布导出完整只读目录 `releases/rN/`，通过临时软链接 + `os.replace` 原子更新 `releases/current -> rN`；线上请求直接按 `current` 软链指向的 `rN` 命中内存缓存快照，无需轮询数据库；
4. **容量自管理**：磁盘仅保留最近 `RELEASES_KEEP = 50` 个展开目录，访问或回退更早版本时自动通过 `git archive <commit>` 秒级原地恢复。

## 3. 后果与权衡

- **正面收益**：
  - **开箱即用**：`uv run report-agent serve` 一条命令即可在任意开发机或单容器内完整启动全栈工作台，零外部中间件依赖；
  - **毫秒级紧急止血**：`POST /releases/emergency-switch` 只需一次原子软链接切换即可在毫秒内将全站切回任意稳定历史版本；
  - **可读可审计**：所有配置资产、运行记录（按日分区的 JSON + `index.jsonl`）与审计日志均为纯文本文件，可直接用标准 Unix 工具备份、检索和排障。
- **约束边界**：
  - 依赖本地 POSIX 文件系统软链接与进程内互斥锁/单写队列，因此**服务必须以单进程（`workers=1`）运行在挂载持久化卷的实例上**；若未来需要多副本水平扩展，可将计算无状态化（只读挂载共享发布目录或对象存储快照），保留单主管理节点负责写操作与发布。

## 相关页面

- [文件化资源存储与 Git 原子发布机制](../architecture/resource-release-and-store.md)
- [本地开发、测试与部署指南](../guides/dev-test-and-deploy.md)
- [当前架构已知约束与注意事项](../lint/known-issues.md)
