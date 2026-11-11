"""证据校验：核对模型提交的每个字段值是否真的出自它声称的来源。

#Created By AiCoding(codex)
  quote  ：引用的接口记录/单据片段必须存在，值必须逐字出现在原文中（quoteWhole 时必须完全相等）；
  input  ：值必须等于引用的入参；
  derive ：引用的来源都必须存在；引用了 format_date 等产出值的工具时，值必须等于工具输出。
不通过的字段把原因返回给模型重新提交，超过重试次数后该字段按“找不到”处理。
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any

from ..domain.template import FieldDef, Template
from .workspace import Workspace

VALUE_TOOLS = {"format_date"}
_MAX_SHOW = 300
_ZERO_WIDTH_SET = frozenset("\ufeff\u200b\u200c\u200d")
_STRICT_NUM_RE = re.compile(r"^[+-]?(?:0|[1-9]\d*)(?:\.\d+)?$")


def scalar_to_str(value: Any) -> str:
    """把标量安全转换为文本（区分 None、bool 与数值，避免 None 变成 'None' 或 True 误当 1）。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value) if math.isfinite(value) else ""
    return str(value)


def _short(text: Any, n: int = _MAX_SHOW) -> str:
    s = scalar_to_str(text)
    return s if len(s) <= n else s[:n] + "…"


def _normalize_line_endings(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch not in _ZERO_WIDTH_SET)
    return cleaned.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_ws_with_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    """将连续空白（含全角空格、NBSP、换行、制表符）折叠为单空格，并保留回原字符串的起止偏移映射。"""
    out_chars: list[str] = []
    spans: list[tuple[int, int]] = []
    ws_start: int | None = None
    for idx, ch in enumerate(text):
        if ch in _ZERO_WIDTH_SET:
            continue
        if ch.isspace():
            if out_chars and ws_start is None:
                ws_start = idx
            continue
        if ws_start is not None:
            out_chars.append(" ")
            spans.append((ws_start, idx))
            ws_start = None
        out_chars.append(ch)
        spans.append((idx, idx + 1))
    return "".join(out_chars), spans


def _collapse_ws(text: str) -> str:
    norm, _ = _normalize_ws_with_map(text)
    return norm


def _as_decimal(val: Any) -> Decimal | None:
    if isinstance(val, bool) or val is None:
        return None
    if isinstance(val, int):
        return Decimal(val)
    if isinstance(val, float):
        return Decimal(str(val)) if math.isfinite(val) else None
    if isinstance(val, str):
        s = val.strip()
        if _STRICT_NUM_RE.match(s):
            try:
                return Decimal(s)
            except InvalidOperation:
                return None
    return None


def _values_equivalent(submitted: Any, source: Any) -> bool:
    """比对提交值与来源值（支持空白归一化、布尔大小写兼容及非前导零数值等价）。"""
    if submitted is None or source is None:
        return False
    if isinstance(submitted, bool) or isinstance(source, bool):
        sub_s = scalar_to_str(submitted).strip().lower()
        src_s = scalar_to_str(source).strip().lower()
        return sub_s in ("true", "false") and sub_s == src_s
    sub_str = scalar_to_str(submitted)
    src_str = scalar_to_str(source)
    if sub_str == src_str or _collapse_ws(sub_str) == _collapse_ws(src_str):
        return bool(_collapse_ws(sub_str))
    sub_num = _as_decimal(submitted)
    src_num = _as_decimal(source)
    if sub_num is not None and src_num is not None:
        return sub_num == src_num
    return False


def _contains_with_ws(container: str, target: str) -> bool:
    """判断 target 是否出现在 container 中（优先逐字包含，其次空白归一化包含）。"""
    if not target or not target.strip():
        return False
    if target in container:
        return True
    norm_target = _collapse_ws(target)
    if not norm_target:
        return False
    return norm_target in _collapse_ws(container)


def locate_quote_in_document(document: str, quote: str, value: str | None = None) -> list[dict[str, int]]:
    """在单据原文中定位引用片段的全部匹配位置，返回按偏移排序的 {offset, endOffset, line, endLine} 列表。"""
    if not document or not quote or not quote.strip():
        return []
    lines_keep = document.splitlines(keepends=True)
    line_starts: list[int] = []
    acc = 0
    for ln in lines_keep:
        line_starts.append(acc)
        acc += len(ln)

    def _span_to_loc(start: int, end: int) -> dict[str, int]:
        last = max(start, end - 1)
        while last > start and document[last] in "\r\n":
            last -= 1
        start_line = bisect_right(line_starts, start) if line_starts else 1
        end_line = bisect_right(line_starts, last) if line_starts else 1
        return {"offset": start, "endOffset": end, "line": max(1, start_line), "endLine": max(1, end_line)}

    raw_spans: list[tuple[int, int]] = []
    pos = 0
    while (idx := document.find(quote, pos)) != -1:
        raw_spans.append((idx, idx + len(quote)))
        pos = idx + 1

    if not raw_spans:
        norm_doc, doc_map = _normalize_ws_with_map(document)
        norm_quote = _collapse_ws(quote)
        if norm_quote and norm_doc:
            pos = 0
            while (idx := norm_doc.find(norm_quote, pos)) != -1:
                orig_start = doc_map[idx][0]
                orig_end = doc_map[idx + len(norm_quote) - 1][1]
                if not raw_spans or raw_spans[-1] != (orig_start, orig_end):
                    raw_spans.append((orig_start, orig_end))
                pos = idx + 1

    if len(raw_spans) > 1 and value and value.strip():
        narrowed = [sp for sp in raw_spans if _contains_with_ws(document[sp[0]:sp[1]], value)]
        if narrowed:
            raw_spans = narrowed

    return [_span_to_loc(s, e) for s, e in raw_spans]


@dataclass
class FieldIssue:
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


class EvidenceChecker:
    """对一次交卷做证据校验。"""

    def __init__(self, template: Template, inputs: dict[str, Any], document: str, workspace: Workspace) -> None:
        self.template = template
        self.inputs = inputs or {}
        self.document = document or ""
        self.ws = workspace

    def check(self, report: dict[str, dict[str, Any]]) -> list[FieldIssue]:
        if not isinstance(report, dict):
            return [FieldIssue(f.name, "报告结构不合法") for f in self.template.definition.fields]
        issues: list[FieldIssue] = []
        found_field_refs: dict[str, list[str]] = {}
        for f in self.template.definition.fields:
            ans = report.get(f.name)
            if ans is None or not isinstance(ans, dict):
                issues.append(FieldIssue(f.name, "缺少该字段的结论"))
                continue
            status = ans.get("status")
            if status == "not_found":
                continue
            if status != "found":
                issues.append(FieldIssue(f.name, f"无效的字段状态 {status!r}，只能是 found 或 not_found"))
                continue
            field_msgs = self._check_field(f, ans)
            issues.extend(FieldIssue(f.name, m) for m in field_msgs)
            raw_ev = ans.get("evidence") or []
            if isinstance(raw_ev, list):
                refs = [str(e.get("name") or "") for e in raw_ev if isinstance(e, dict) and e.get("type") == "field"]
                if refs:
                    found_field_refs[f.name] = refs

        for start in found_field_refs:
            stack = [(n, [start, n]) for n in found_field_refs.get(start, []) if n != start]
            visited: set[str] = set()
            while stack:
                curr, path = stack.pop()
                if curr == start:
                    issues.append(FieldIssue(start, f"字段证据引用存在循环依赖：{' -> '.join(path)}"))
                    break
                if curr in visited:
                    continue
                visited.add(curr)
                for nxt in found_field_refs.get(curr, []):
                    stack.append((nxt, [*path, nxt]))
        return issues

    # ------------------------------------------------------------------
    def _check_field(self, f: FieldDef, ans: dict[str, Any]) -> list[str]:
        raw_value = ans.get("value")
        value = scalar_to_str(raw_value)
        if raw_value is None or value.strip() == "":
            return ["status=found 但 value 为空；找不到请提交 not_found"]
        raw_evidence = ans.get("evidence") or []
        if not isinstance(raw_evidence, list) or not raw_evidence:
            return ["缺少证据 evidence"]
        evidence = [e for e in raw_evidence if isinstance(e, dict)]
        if len(evidence) != len(raw_evidence):
            return ["evidence 中存在格式不合法的条目"]
        if f.type == "enum" and f.values and value not in f.values:
            return [f"值「{value}」不在可选范围 {f.values} 内"]

        msgs: list[str] = []
        if f.evidence == "quote":
            quotes = [e for e in evidence if e.get("type") in ("api", "document")]
            invalid_types = [e.get("type") for e in evidence if e.get("type") not in ("api", "document")]
            if invalid_types:
                msgs.append(f"原文引用字段不允许使用 {invalid_types} 类型证据")
            if not quotes:
                return ["原文引用字段必须引用接口记录（type=api）或单据片段（type=document）"]
            for e in quotes:
                msgs.extend(self._check_quote(f, raw_value, value, e))
        elif f.evidence == "input":
            refs = [e for e in evidence if e.get("type") == "input"]
            invalid_types = [e.get("type") for e in evidence if e.get("type") != "input"]
            if invalid_types:
                msgs.append(f"入参字段不允许使用 {invalid_types} 类型证据")
            if not refs:
                return ["入参字段必须引用入参（type=input）"]
            for e in refs:
                key = e.get("key")
                if not isinstance(key, str) or key not in self.inputs:
                    msgs.append(f"入参「{key}」没有传入")
                elif self.inputs[key] is None or scalar_to_str(self.inputs[key]).strip() == "":
                    msgs.append(f"入参「{key}」为空，不能作为 found 证据")
                elif not _values_equivalent(raw_value, self.inputs[key]):
                    msgs.append(f"值「{_short(value)}」与入参「{key}」的值「{_short(self.inputs[key])}」不一致")
        else:
            value_tool_outputs: list[Any] = []
            for e in evidence:
                msgs.extend(self._check_ref_exists(f, e))
                if e.get("type") == "tool":
                    call = self.ws.tool_calls.get(str(e.get("callId") or ""))
                    if call and call.ok and call.tool in VALUE_TOOLS and isinstance(call.output, dict):
                        value_tool_outputs.append(call.output.get("value", ""))
            if value_tool_outputs and not any(_values_equivalent(raw_value, out) for out in value_tool_outputs):
                shown = [scalar_to_str(o) for o in value_tool_outputs]
                msgs.append(f"值「{value}」与引用的工具输出 {shown} 不一致；请直接使用工具输出")
        return msgs

    def _check_quote(self, f: FieldDef, raw_value: Any, value: str, e: dict[str, Any]) -> list[str]:
        if e.get("type") == "api":
            raw_cell, cell, err = self._cell(e)
            if err:
                return [err]
            assert cell is not None
            where = f"{e.get('resultId')} 第 {e.get('row')} 行 {e.get('column')}"
            if f.quoteWhole and _normalize_line_endings(value) != _normalize_line_endings(cell):
                return [f"必须整条原样引用：{where} 的原文是「{_short(cell, 600)}」，提交的值与原文不完全一致"]
            if not f.quoteWhole and not _contains_with_ws(cell, value) and not _values_equivalent(raw_value, raw_cell):
                return [f"值「{_short(value)}」没有逐字出现在 {where} 的原文「{_short(cell)}」中"]
            return []
        quote = scalar_to_str(e.get("quote"))
        if not quote.strip():
            return ["单据引用缺少 quote"]
        if not locate_quote_in_document(self.document, quote):
            return [f"单据中找不到片段「{_short(quote)}」，请从单据原文逐字复制"]
        if f.quoteWhole and _normalize_line_endings(value) != _normalize_line_endings(quote):
            return [f"必须整段原样引用：值应与引用片段「{_short(quote)}」完全一致"]
        if not f.quoteWhole and not _contains_with_ws(quote, value):
            return [f"值「{_short(value)}」没有逐字出现在引用片段「{_short(quote)}」中"]
        return []

    def _cell(self, e: dict[str, Any]) -> tuple[Any, str | None, str | None]:
        rid = str(e.get("resultId") or "")
        res = self.ws.results.get(rid)
        if res is None:
            return None, None, f"接口结果 {rid} 不存在"
        if not res.ok:
            return None, None, f"接口结果 {rid} 调用失败，不能作为证据"
        row = e.get("row")
        if isinstance(row, bool) or not isinstance(row, int) or row < 0 or row >= len(res.records):
            return None, None, f"{rid} 没有第 {row} 行（共 {len(res.records)} 行，从 0 开始）"
        col = str(e.get("column") or "")
        rec = res.records[row]
        if col not in rec:
            return None, None, f"{rid} 第 {row} 行没有列 {col}，可用列：{list(rec.keys())}"
        raw_cell = rec[col]
        return raw_cell, scalar_to_str(raw_cell), None

    def _check_ref_exists(self, f: FieldDef, e: dict[str, Any]) -> list[str]:
        t = e.get("type")
        if t == "api":
            _, _, err = self._cell(e)
            return [err] if err else []
        if t == "document":
            quote = scalar_to_str(e.get("quote"))
            return [] if quote.strip() and locate_quote_in_document(self.document, quote) else [
                f"单据中找不到片段「{_short(quote)}」"
            ]
        if t == "input":
            key = e.get("key")
            return [] if isinstance(key, str) and key in self.inputs else [f"入参「{key}」没有传入"]
        if t == "tool":
            cid = str(e.get("callId") or "")
            call = self.ws.tool_calls.get(cid)
            if call is None:
                return [f"工具调用 {cid} 不存在"]
            if not call.ok:
                return [f"工具调用 {cid} 执行失败，不能作为证据"]
            return []
        if t == "field":
            target_name = str(e.get("name") or "")
            if target_name == f.name:
                return [f"字段「{f.name}」不能引用自身作为证据"]
            return [] if self.template.definition.field(target_name) else [f"字段「{target_name}」不存在"]
        return [f"未知的证据类型 {t}"]


def format_issues(issues: list[FieldIssue]) -> str:
    """给模型看的重填说明。"""
    lines = ["以下字段的证据校验没有通过，请核对原文后重新提交全部字段（其它字段保持不变）："]
    lines += [f"- {i.field}：{i.message}" for i in issues]
    return "\n".join(lines)
