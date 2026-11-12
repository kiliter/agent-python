# 项目知识库 Schema（LLM Wiki 维护规范）

<!-- #Created By AiCoding(codex) -->

本知识库按 Karpathy 提出的 [LLM Wiki 模式](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 组织，并与前代 Java 仓库（`pdf-agent-parse`）的知识库范式保持一致。人负责提供需求与业务背景；LLM Agent 负责调研源码、编写综述、维护交叉链接与日常健康检查。本文件是 Agent 维护 `wiki/` 时必须遵守的元规范。

## 1. 三层结构与事实优先级

| 层 | 位置 | 维护者 | 说明 |
|----|------|--------|------|
| 原始资料（Raw Sources） | 仓库中除 `wiki/` 以外的全部内容：`src/report_agent/`、`frontend/`、`tools/java_migration/`、`tests/`、`docs/`、`pyproject.toml`、`README.md`、`AGENTS.md`、Git 历史 | 人与开发智能体 | 维护 Wiki 时将原始资料视为**只读事实源**，不得为迁就文档去反向篡改业务代码 |
| 知识库（Wiki） | `wiki/` | LLM Agent | 项目总览、架构概念、组件剖析、业务 Skill 卡片、ADR 决策、操作指南、速查表与 Lint 清单 |
| 规范层（Schema） | `wiki/SCHEMA.md`（本文件） | 人与 LLM 共同演进 | 目录结构、YAML frontmatter 契约、链接规则与 Ingest / Query / Lint 维护流程 |

当不同来源出现描述冲突时，严格按以下优先级采信事实：

> **运行时 Python/TS 源码（`src/`、`frontend/src/`） > 内置生产资源（`src/report_agent/seed/`） > 自动化测试与对拍脚本（`tests/`、`tools/java_migration/`） > Git 提交历史 > 工程交接文档（`docs/`、`README.md`、`AGENTS.md`）**

发现工程文档与源码不一致时，Wiki 一律以当前源码为准，并在 [lint/known-issues.md](lint/known-issues.md) 或 [lint/java-divergence.md](lint/java-divergence.md) 中登记差异背景。

## 2. 目录约定

```text
wiki/
├── SCHEMA.md          # 本文件：Wiki 组织与维护规范（无 YAML frontmatter）
├── index.md           # 全库总目录：每页一行相对链接 + 一句话摘要（查询入口）
├── log.md             # 按时间顺序只追加的维护日志（无 YAML frontmatter）
├── overview.md        # 项目全局总览、与 Java 版对比及核心规模指标
├── timeline.md        # 从单智能体底座、全栈工作台到 Java 全量迁移与二期演进的时间线
├── architecture/      # 架构概念页：跨模块的机制、数据流与核心设计契约
├── components/        # 组件实体页：后端核心包与前端工作台的模块职责剖析
├── skills/            # 业务 Skill 页：README 总览 + 11 个纯文本 Skill 逐一拆解
├── decisions/         # 架构决策记录（ADR-001 ~ ADR-005）
├── guides/            # 实操指南：新增模板/Skill/接口、本地联调部署、迁移对拍、故障排查
├── reference/         # 速查手册：环境变量配置、33 个生产模板清单、3 个接口契约清单、术语表
└── lint/              # 质量与差异审计：已知限制、Java 行为差异与主动修复台账、待确认问题
```

## 3. 页面格式规范

除 `SCHEMA.md` 和 `log.md` 外，`wiki/` 下**所有** `.md` 页面都必须以标准 YAML frontmatter 开头：

```yaml
---
title: 页面标题
type: overview | concept | component | skill | decision | guide | reference | lint
tags: [标签1, 标签2]
sources:
  - src/report_agent/runtime/runner.py
  - src/report_agent/runtime/evidence.py
updated: 2026-11-12
---
```

正文编写规则：

1. **语言约定**：正文统一使用中文，技术专有名词保留英文原名（如 Pydantic AI、ReAct、SSE、Jinja2、`TrackedList`、`Workspace`）。
2. **禁止写源码行号**：引用源码位置时一律写 `路径#类名`、`路径#函数名` 或 `路径#常量名`（如 `src/report_agent/runtime/runner.py#AgentRunner.run`），`sources` 列表只写相对仓库根目录的文件路径，**严禁写入易随提交漂移的行号**。
3. **双向与底部关联链接**：页面间统一使用相对路径 Markdown 链接（如 `[证据核验机制](../architecture/evidence-system.md)`）。除 `SCHEMA.md` 与 `log.md` 外，每个页面末尾必须包含 `## 相关页面` 小节，列出 2～6 个上下游或同域关联页面，确保全库零孤立页、零断链。
4. **聚焦高价值结论**：提炼跨文件协作关系、状态机边界、为什么这样设计以及容易踩坑的约束；能从单行代码字面读出的琐碎细节无需堆砌。
5. **安全红线**：严禁写入任何真实的 API Key、口令哈希原文、Cookie 密钥或现网客户隐私数据。涉及敏感环境变量时仅写出变量名（如 `LLM_API_KEY`、`REPORT_API_KEYS`）与配置机制。
6. **待确认事项标注**：对需要业务侧最终拍板的策略或边界，在正文标注「（待业务确认）」并同步汇总至 [lint/open-questions.md](lint/open-questions.md)。

## 4. 维护流程

### 4.1 Ingest（摄入代码或资源变更）

触发时机：新增或修改平台工具、证据核验规则、Jinja2 渲染器、模板/Skill/网关契约、前端工作台能力，或完成一批迁移修复提交后。

1. 对照源码与测试核实变更后的真实行为（例如工具参数签名、发布校验告警数、模板入参列表）。
2. 同步更新对应的 `architecture/`、`components/`、`skills/`、`reference/` 与 `lint/` 页面；若涉及架构级取舍，新增或更新 `decisions/adr-*.md`。
3. 若新增或重命名页面，同步更新 `index.md` 对应分类目录与相邻页面的 `## 相关页面`。
4. 在 `log.md` 末尾追加一条 `ingest` 记录。

### 4.2 Query（基于 Wiki 回答问题）

1. 先读 `index.md` 定位最相关的 1～3 个页面，再深入阅读目标页面。
2. 结合页面 `sources` 指向的源码文件快速核对关键符号是否仍然最新。
3. 若排查出了新的隐蔽结论或排障路径，沉淀回 `guides/troubleshooting.md` 或对应概念页，并在 `log.md` 记录。

### 4.3 Lint（全库健康检查）

在每次大规模变更收口或发布前执行以下快速核对命令，确保 Wiki 数字、清单与链接 100% 准确：

```bash
# 1. 核对生产内置资源规模（期望：33 个模板、11 个 Skill、3 个网关契约）
ls -1 src/report_agent/seed/templates | wc -l
ls -1 src/report_agent/seed/skills | wc -l
ls -1 src/report_agent/seed/apis/*.yaml | wc -l

# 2. 核对平台工具注册数量（期望：12 个工具）与 VALUE_TOOLS 集合
uv run python -c "
from report_agent.runtime.tools import build_tools
from report_agent.runtime.evidence import VALUE_TOOLS
tools = build_tools(2)
print('registered tools:', len(tools), [t.name for t in tools])
print('VALUE_TOOLS:', VALUE_TOOLS)
"

# 3. 核对全量生产资源发布校验（期望：0 errors, 0 warnings）
uv run python -c "
from pathlib import Path
from report_agent.domain.resources import load_resource_dir, validate_all
rs = load_resource_dir(Path('src/report_agent/seed'))
issues = validate_all(rs)
print('errors:', [i for i in issues if i.level == 'error'])
print('warnings:', [i for i in issues if i.level == 'warning'])
"
```

此外，用只读 Python 脚本校验：
- `CLAUDE.md` 是指向 `AGENTS.md` 的有效相对软链接；
- `wiki/` 下除 `SCHEMA.md`、`log.md` 外全部页面均含合法 YAML frontmatter（`title`/`type`/`tags`/`sources`/`updated`）；
- `wiki/` 内所有相对 Markdown 链接目标文件 100% 存在，`wiki/index.md` 完整登记所有页面且无孤立页。

## 5. `log.md` 追加格式

每条记录使用统一标题格式，便于按时间检索（`grep "^## \[" wiki/log.md | tail -5`）：

```markdown
## [YYYY-MM-DD] ingest | 变更或资料摘要
## [YYYY-MM-DD] query | 专题问答沉淀摘要
## [YYYY-MM-DD] lint | 健康检查与对齐范围
```

每条记录下用 2～5 条精炼列表说明更新了哪些页面及核心结论变更。
