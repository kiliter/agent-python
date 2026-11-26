"""复合工单汇总大模板：Jinja2 沙箱校验与多子报告确定性拼装渲染。

#Created By AiCoding(codex)
一个申诉工单（单个号码）可能关联多个商品/业务并分别命中不同模板；
各子项独立通过 AgentRunner 强证据核验与渲染后，由本模块套入可版本化管理的
`composite-template.md.j2` 汇总大模板进行确定性拼装（零业务硬编码、零幻觉）。
"""

from __future__ import annotations

from typing import Any

from jinja2 import TemplateError, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

COMPOSITE_TEMPLATE_FILE = "composite-template.md.j2"
COMPOSITE_TEMPLATE_KEY = "composite-template"

# #Created By AiCoding(codex) 默认复合工单汇总大模板（平台内置兜底，管理端可在线可视化编辑并发布覆盖）
DEFAULT_COMPOSITE_TEMPLATE = """{%- if order.平台流水号 or order.手机号码 -%}
关于{% if order.平台流水号 %}工单「{{ order.平台流水号 }}」{% endif %}{% if order.手机号码 %}（号码：{{ order.手机号码 }}）{% endif %}涉及 {{ summary.totalItems }} 项业务的核查情况汇总如下：
{%- else -%}
本次共核查 {{ summary.totalItems }} 项业务，具体情况汇总如下：
{%- endif %}

{% for item in items -%}
### {{ loop.index }}、关于【{{ item.label }}】核查情况（{{ item.templateName }}）
{% if item.status == 'FAILED' -%}
核查未完成：{{ item.error or '运行失败，请人工复核' }}
{%- else -%}
{{ item.report }}
{%- endif %}

{% endfor -%}
{%- if summary.partialCount > 0 or summary.failedCount > 0 -%}
---
> 核查汇总提示：共 {{ summary.totalItems }} 项业务，其中完全核出 {{ summary.successCount }} 项{% if summary.partialCount > 0 %}、部分字段待补 {{ summary.partialCount }} 项{% endif %}{% if summary.failedCount > 0 %}、未完成 {{ summary.failedCount }} 项{% endif %}，请复核后再确认回传。
{%- endif -%}
"""

_COMPOSITE_ENV = SandboxedEnvironment(
    autoescape=False,
    trim_blocks=False,
    lstrip_blocks=False,
)


class CompositeTemplateError(ValueError):
    """汇总大模板语法或渲染失败。"""

    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


def validate_composite_template(text: str) -> list[str]:
    """校验汇总大模板 Jinja2 语法与基础渲染可用性，返回错误列表（空列表表示通过）。#Created By AiCoding(codex)"""
    if not isinstance(text, str) or not text.strip():
        return ["汇总大模板内容不能为空"]
    try:
        tpl = _COMPOSITE_ENV.from_string(text)
    except TemplateSyntaxError as exc:
        return [f"汇总大模板第 {exc.lineno} 行语法错误：{exc.message}"]
    except TemplateError as exc:
        return [f"汇总大模板解析错误：{exc}"]
    try:
        tpl.render(**sample_composite_context())
    except TemplateError as exc:
        return [f"汇总大模板样例渲染失败：{exc}"]
    except Exception as exc:  # noqa: BLE001
        return [f"汇总大模板样例渲染异常：{exc}"]
    return []


def build_composite_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    """统计多商品子项的完成情况。"""
    success = sum(1 for it in items if it.get("status") == "SUCCESS")
    partial = sum(1 for it in items if it.get("status") == "PARTIAL")
    failed = len(items) - success - partial
    return {
        "totalItems": len(items),
        "successCount": success,
        "partialCount": partial,
        "failedCount": failed,
    }


def render_composite_report(
    template_text: str | None,
    *,
    order: dict[str, Any],
    items: list[dict[str, Any]],
) -> str:
    """用 Jinja2 沙箱环境将多份经强证据校验的子报告确定性拼装为完整大报告。#Created By AiCoding(codex)"""
    source = (template_text or "").strip() or DEFAULT_COMPOSITE_TEMPLATE
    summary = build_composite_summary(items)
    try:
        tpl = _COMPOSITE_ENV.from_string(source)
        rendered = tpl.render(order=dict(order or {}), items=list(items), summary=summary)
    except TemplateSyntaxError as exc:
        raise CompositeTemplateError(f"汇总大模板第 {exc.lineno} 行语法错误：{exc.message}", line=exc.lineno) from exc
    except TemplateError as exc:
        raise CompositeTemplateError(f"汇总大模板渲染失败：{exc}") from exc
    return rendered.strip()


def sample_composite_context() -> dict[str, Any]:
    """管理端预览汇总大模板用的脱敏多商品样例上下文（对应典型 1 号码 × 3 商品复合工单）。#Created By AiCoding(codex)"""
    order = {
        "平台流水号": "部转-20261100123473",
        "手机号码": "13900001234",
        "申诉内容": "未经过本人允许添加会员及保底套餐，要求核查并处理。",
    }
    items = [
        {
            "index": 1,
            "label": "套餐接续直降80元加享翻倍流量（12个月）",
            "templateId": 104,
            "templateName": "业务办理未授权争议处理类",
            "status": "SUCCESS",
            "statusLabel": "成功",
            "foundCount": 8,
            "totalCount": 8,
            "missingShown": [],
            "error": None,
            "runId": "sample-r1",
            "params": {"业务名称": "套餐接续直降80元加享翻倍流量（12个月）", "创建时间": "20251012000000", "商品类型": "营销案"},
            "report": "经核查，号码 13900001234 于 2025年10月12日通过营业厅渠道办理「套餐接续直降80元加享翻倍流量（12个月）」，已查验办理协议及成功告知短信。",
        },
        {
            "index": 2,
            "label": "任我选会员15元优享版",
            "templateId": 116,
            "templateName": "增值业务扣费争议处理模板",
            "status": "SUCCESS",
            "statusLabel": "成功",
            "foundCount": 6,
            "totalCount": 6,
            "missingShown": [],
            "error": None,
            "runId": "sample-r2",
            "params": {"业务名称": "任我选会员15元优享版", "创建时间": "20251012000000", "商品类型": "套餐"},
            "report": "经核查，号码 13900001234 于 2025年10月12日订购「任我选会员15元优享版」，标准资费 15元/月，已核实订购短信记录。",
        },
        {
            "index": 3,
            "label": "全家保底消费融合套餐99元",
            "templateId": 104,
            "templateName": "业务办理未授权争议处理类",
            "status": "PARTIAL",
            "statusLabel": "部分缺失",
            "foundCount": 6,
            "totalCount": 7,
            "missingShown": ["二次确认短信"],
            "error": None,
            "runId": "sample-r3",
            "params": {"业务名称": "全家保底消费融合套餐99元", "创建时间": "20251012000000", "商品类型": "套餐"},
            "report": "经核查，号码 13900001234 于 2025年10月12日办理「全家保底消费融合套餐99元」，标准资费 99元/月；二次确认短信暂未查询到（{{二次确认短信}}）。",
        },
    ]
    return {"order": order, "items": items, "summary": build_composite_summary(items)}
