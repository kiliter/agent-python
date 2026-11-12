# 项目知识库维护日志（Log）

<!-- #Created By AiCoding(codex) -->

本文件按时间顺序只追加记录 `wiki/` 的初始化、资料摄入（`ingest`）、专题沉淀（`query`）与全库健康检查（`lint`）历史。格式约定见 [SCHEMA.md](SCHEMA.md)。

## [2026-11-12] ingest | 初始化 agent-python LLM Wiki 知识库与 AGENTS.md

- 通读 `src/report_agent/`（`api`、`domain`、`gateway`、`runtime`、`store`、`seed`）、`frontend/`、`tools/java_migration/`、`tests/` 与 `docs/frontend-api-handoff.md`，建立根目录 `AGENTS.md`（及 `CLAUDE.md` 软链接）与完整的 `wiki/` 三层知识库。
- 编写核心架构页（`architecture/` 5 篇）、组件剖析页（`components/` 5 篇）、业务 Skill 卡片（`skills/` 12 篇）、架构决策记录（`decisions/` ADR-001～ADR-005）、实操指南（`guides/` 5 篇）、参考速查表（`reference/` 4 篇）与质量差异审计台账（`lint/` 3 篇）。
- 完整记录与前代 Java 版（`pdf-agent-parse`）的架构演进关系、33 个生产模板（`100`～`132`）、11 个纯文本 Skill、3 个声明式网关接口契约与 12 个确定性平台工具。

## [2026-11-12] lint | 对齐二期 platform 与 migration 最终落地契约并完成全库健康检查

- 对照二期 `@platform` 最终落地的 `config.py`、`runtime/{runner,evidence,tools,text_tools}.py` 与 `domain/jinja_env.py`，逐字核准全部环境变量名（`AGENT_*`、`GATEWAY_MODE=live|mock`、`REPORT_API_KEYS`）、12 个确定性工具入参/返回字典结构、`TrackedList` 渲染分支追踪及列表空结果 `status="found", value=[]` 证据校验规则。
- 对照二期 `@migration` 最终落地的 `seed/skills/*/SKILL.md`、`seed/templates/100..132/`、`TEMPLATES.md` 与 `MAPPING.md`，对齐 R2（`reminder-sms`）、R5（`pretty-number-info`）、R7（移除同名入参 `客户号码`，33 模板 `validate_all` 0 error / 0 warning）、R8（`qry-balance` 纯年月整月展开）与 R17（模板 120 `有设备押金` `whenMissing: empty`）全部细节及 2,240 个 Pebble/Jinja2 渲染对拍场景。
- 执行全库只读自动化 Lint：确认 `CLAUDE.md -> AGENTS.md` 软链接有效、42 个带头页面 YAML frontmatter 与 `sources` 路径 100% 合法、全库相对链接零断链、`wiki/index.md` 零遗漏零孤立页。
