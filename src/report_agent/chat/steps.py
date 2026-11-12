"""运行过程事件脱敏映射：将内部 ProcessEvent 转换为前端聊天卡片展示的友好 RunStep。

#Created By AiCoding(codex)
绝不向步骤文本暴露业务网关原始报文、单据原文或客户手机号/证件号等隐私数据。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ..domain.resources import ResourceSet
from ..runtime.workspace import ProcessEvent

STEP_ICONS = frozenset({"start", "skill", "api", "filter", "tool", "check", "warn", "error", "done"})

_TOOL_LABELS: dict[str, str] = {
    "normalize_text": "文本清洗",
    "text_contains": "单据文本匹配",
    "date_range": "计算日期窗口",
    "format_date": "日期格式转换",
    "extract_dates": "提取单据日期",
    "date_shift": "日期偏移计算",
    "expand_period": "展开账期区间",
    "time_diff": "计算时间差",
    "regex_extract": "正则提取内容",
}

_SENSITIVE_DIGITS_RE = re.compile(r"\d{8,}")
_SINGLE_QUOTED_LITERAL_RE = re.compile(r"'[^']{4,}'")
_DOUBLE_QUOTED_LITERAL_RE = re.compile(r'"[^"]{4,}"')
_MAX_ERR_CHARS = 120


def _safe_nonneg_int(val: Any, default: int = 0) -> int:
    if isinstance(val, bool):
        return default
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        return default


def _sanitize_error(raw: Any, fallback: str = "未知错误") -> str:
    """清洗错误提示：折叠换行、掩码可能携带的单双引号入参字面量与长数字串，防止泄露客户隐私或原始报文。"""
    text = " ".join(str(raw or "").split()).strip()
    if not text:
        return fallback
    text = _SINGLE_QUOTED_LITERAL_RE.sub("'***'", text)
    text = _DOUBLE_QUOTED_LITERAL_RE.sub('"***"', text)
    text = _SENSITIVE_DIGITS_RE.sub("***", text)
    if len(text) > _MAX_ERR_CHARS:
        text = text[:_MAX_ERR_CHARS].rstrip() + "…"
    return text


def _unpack_event(ev: ProcessEvent | dict[str, Any]) -> tuple[str, int, dict[str, Any]]:
    """统一解包 ProcessEvent 实例或序列化后的事件字典。"""
    if isinstance(ev, ProcessEvent):
        return str(ev.type or ""), _safe_nonneg_int(ev.at_ms), dict(ev.data or {})
    if isinstance(ev, dict):
        ev_type = str(ev.get("type") or "")
        at_ms = _safe_nonneg_int(ev.get("atMs", ev.get("at_ms", 0)))
        nested = ev.get("data")
        data = {**ev, **nested} if isinstance(nested, dict) else dict(ev)
        return ev_type, at_ms, data
    return "", 0, {}


def _count_issue_fields(data: dict[str, Any]) -> int:
    """统计证据校验事件涉及的去重字段数。"""
    fields = data.get("fields")
    if isinstance(fields, list) and fields:
        uniq = {str(f) for f in fields if f is not None and str(f).strip()}
        if uniq:
            return len(uniq)
    issues = data.get("issues")
    if isinstance(issues, list) and issues:
        uniq_from_issues = {
            str(item["field"])
            for item in issues
            if isinstance(item, dict) and item.get("field")
        }
        if uniq_from_issues:
            return len(uniq_from_issues)
        return len(issues)
    return 1


class StepMapper:
    """有状态的单次运行步骤映射器，按可见步骤分配连续递增的 seq。"""

    def __init__(self, resources: ResourceSet | None = None, start_seq: int = 0) -> None:
        self.resources = resources
        self._seq = max(0, int(start_seq))
        self._last_at_ms = 0
        self.steps: list[dict[str, Any]] = []

    def _emit(self, icon: str, text: str, *, ok: bool, at_ms: int) -> dict[str, Any]:
        safe_icon = icon if icon in STEP_ICONS else "tool"
        step_at = max(0, int(at_ms))
        if step_at > self._last_at_ms:
            self._last_at_ms = step_at
        self._seq += 1
        step: dict[str, Any] = {
            "seq": self._seq,
            "atMs": step_at,
            "icon": safe_icon,
            "text": text,
            "ok": bool(ok),
        }
        self.steps.append(step)
        return dict(step)

    def append_custom(
        self,
        icon: str,
        text: str,
        *,
        ok: bool = True,
        at_ms: int | None = None,
    ) -> dict[str, Any]:
        """供运行正常完成、手动取消或未捕获异常时追加终态步骤。"""
        effective_ms = self._last_at_ms if at_ms is None else max(0, int(at_ms))
        return self._emit(icon, text, ok=ok, at_ms=effective_ms)

    def _skill_titles(self, args: dict[str, Any], result: dict[str, Any]) -> list[str]:
        titles_raw = result.get("titles")
        if isinstance(titles_raw, list):
            titles = [str(t).strip() for t in titles_raw if t is not None and str(t).strip()]
            if titles:
                return list(dict.fromkeys(titles))
        single = result.get("title")
        if single is not None and str(single).strip():
            return [str(single).strip()]

        # 失败场景等 result 无标题时，尝试从白名单资源字典反查公开 Skill 标题
        raw_names: list[str] = []
        if args.get("name") and str(args["name"]).strip():
            raw_names.append(str(args["name"]).strip())
        if isinstance(args.get("names"), list):
            for item in args["names"]:
                if item is not None and str(item).strip():
                    raw_names.append(str(item).strip())
        resolved: list[str] = []
        for sid in dict.fromkeys(raw_names):
            if self.resources is not None and sid in self.resources.skills:
                resolved.append(self.resources.skills[sid].title)
            elif len(sid) <= 64:
                resolved.append(sid)
        return resolved

    def _api_title(self, name: str, result: dict[str, Any]) -> str:
        if name and self.resources is not None and name in self.resources.apis:
            contract_title = self.resources.apis[name].title.strip()
            if contract_title:
                return contract_title
        res_title = result.get("title")
        if isinstance(res_title, str) and res_title.strip():
            return res_title.strip()
        return name or "业务接口"

    def _map_tool(self, data: dict[str, Any], at_ms: int) -> dict[str, Any]:
        tool_name = str(data.get("tool") or "")
        ok = bool(data.get("ok", True))
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        raw_result = data.get("result")
        result = raw_result if isinstance(raw_result, dict) else {}

        if tool_name == "load_skill":
            titles = self._skill_titles(args, result)
            joined = "、".join(titles)
            if ok:
                text = f"加载规则：{joined}" if joined else "加载规则说明"
            else:
                text = f"加载规则「{joined}」失败" if joined else "加载规则失败"
            return self._emit("skill", text, ok=ok, at_ms=at_ms)

        if tool_name == "call_api":
            api_name = str(args.get("name") or "")
            title = self._api_title(api_name, result)
            if ok:
                count = _safe_nonneg_int(result.get("count"))
                text = f"查询「{title}」：返回 {count} 条记录"
            else:
                err = _sanitize_error(result.get("error"), fallback="调用异常")
                text = f"查询「{title}」失败：{err}"
            return self._emit("api", text, ok=ok, at_ms=at_ms)

        if tool_name == "query_result":
            if ok:
                total = _safe_nonneg_int(result.get("total"))
                text = f"筛选记录：命中 {total} 条"
            else:
                err = _sanitize_error(result.get("error"), fallback="条件无效")
                text = f"筛选记录失败：{err}"
            return self._emit("filter", text, ok=ok, at_ms=at_ms)

        base_label = _TOOL_LABELS.get(tool_name, "执行辅助工具")
        if not ok:
            return self._emit("tool", f"{base_label}失败", ok=False, at_ms=at_ms)

        # 确定性工具仅附加安全的布尔/数量统计，绝不拼接客户文本、日期原值或正则匹配内容
        if tool_name == "text_contains" and isinstance(result.get("contains"), bool):
            text = f"{base_label}：{'已命中' if result['contains'] else '未命中'}"
        elif tool_name == "extract_dates" and "count" in result:
            text = f"{base_label}：识别到 {_safe_nonneg_int(result.get('count'))} 个日期"
        elif tool_name == "expand_period" and isinstance(result.get("months"), list):
            text = f"{base_label}：共 {len(result['months'])} 个账期月"
        elif tool_name == "regex_extract" and "count" in result:
            text = f"{base_label}：匹配 {_safe_nonneg_int(result.get('count'))} 处"
        else:
            text = base_label
        return self._emit("tool", text, ok=True, at_ms=at_ms)

    def feed(self, ev: ProcessEvent | dict[str, Any]) -> dict[str, Any] | None:
        """消费一条过程事件；忽略内部模型轮次/思考事件（返回 None 且不占用 seq）。"""
        ev_type, at_ms, data = _unpack_event(ev)
        if not ev_type or ev_type in ("model_request", "model_text"):
            return None

        if ev_type == "run_started":
            tpl_name = str(
                data.get("templateName")
                or (f"模板 {data['templateId']}" if data.get("templateId") is not None else "未知模板")
            )
            rev = str(data.get("rev") or "—")
            return self._emit("start", f"开始填写「{tpl_name}」（版本 {rev}）", ok=True, at_ms=at_ms)

        if ev_type == "tool":
            return self._map_tool(data, at_ms)

        if ev_type == "report_rejected":
            n = _count_issue_fields(data)
            return self._emit("warn", f"证据核验退回 {n} 个字段，正在重新核对", ok=True, at_ms=at_ms)

        if ev_type == "report_degraded":
            n = _count_issue_fields(data)
            return self._emit("warn", f"{n} 个字段未通过证据核验，已按未找到处理", ok=True, at_ms=at_ms)

        if ev_type == "report_accepted":
            return self._emit("check", "全部字段通过证据核验", ok=True, at_ms=at_ms)

        if ev_type == "run_failed":
            err = _sanitize_error(data.get("error"), fallback="未知错误")
            return self._emit("error", f"运行失败：{err}", ok=False, at_ms=at_ms)

        return None


def events_to_steps(
    events: Iterable[ProcessEvent | dict[str, Any]],
    resources: ResourceSet | None = None,
) -> list[dict[str, Any]]:
    """批量将历史运行记录中的过程事件列表转换为 RunStep 列表。"""
    mapper = StepMapper(resources=resources)
    for ev in events:
        mapper.feed(ev)
    return [dict(s) for s in mapper.steps]
