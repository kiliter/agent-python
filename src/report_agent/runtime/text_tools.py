"""确定性的文本与日期函数，供平台工具和证据校验使用。

#Created By AiCoding(codex)
normalize_text 与 Java StringCharCleaner 规则一致：NFKC 归一化后删除固定的中英文标点。
日期格式使用 Java 风格（yyyy、MM、M、dd、d、HH、H、mm、m、ss、s），与模板中的写法保持一致。
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import datetime

FIXED_CHARS_TO_REMOVE = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~！\"#$%&'（）*+，-。/：；<=>？@[\\]^_`{|}~"
_ZERO_WIDTH_CHARS = "\ufeff\u200b\u200c\u200d"
MAX_REGEX_LENGTH = 2000
_SEPARATED_DATE_RE = re.compile(r"^\s*(\d{4})\D+(\d{1,2})\D+(\d{1,2})(?!\d)")


def safe_regex_compile(pattern: str) -> re.Pattern[str]:
    """安全编译正则表达式，非法语法或超长模式统一抛出 ValueError。"""
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("正则表达式不能为空")
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ValueError(f"正则表达式长度超过上限（{MAX_REGEX_LENGTH}）")
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"正则表达式不合法：{exc}") from exc


def safe_regex_fullmatch(pattern: str, value: str) -> bool:
    """安全执行整串正则匹配；正则本身非法时抛出 ValueError。"""
    compiled = safe_regex_compile(pattern)
    return compiled.fullmatch(value or "") is not None


def normalize_text(text: str | None, extra_chars: str = "") -> str:
    """NFKC 归一化并删除固定标点和 extra_chars 中的字符。"""
    if text is None:
        return ""
    raw = str(text)
    if not raw or not raw.strip():
        return ""
    normalized = unicodedata.normalize("NFKC", raw)
    remove = set(unicodedata.normalize("NFKC", FIXED_CHARS_TO_REMOVE + _ZERO_WIDTH_CHARS + (extra_chars or "")))
    return "".join(ch for ch in normalized if ch not in remove)


def normalized_contains(content: str | None, target: str | None, extra_chars: str = "") -> bool:
    """清洗两边后判断包含；清洗后的 target 为空时返回 False。"""
    t = normalize_text(target, extra_chars)
    return bool(t) and t in normalize_text(content, extra_chars)


_TOKEN_RE = re.compile(r"yyyy|MM|M|dd|d|HH|H|mm|m|ss|s")
_TOKEN_REGEX = {"yyyy": r"(?P<y>\d{4})", "MM": r"(?P<mo>\d{2})", "M": r"(?P<mo>\d{1,2})",
                "dd": r"(?P<d>\d{2})", "d": r"(?P<d>\d{1,2})", "HH": r"(?P<h>\d{2})", "H": r"(?P<h>\d{1,2})",
                "mm": r"(?P<mi>\d{2})", "m": r"(?P<mi>\d{1,2})", "ss": r"(?P<s>\d{2})", "s": r"(?P<s>\d{1,2})"}


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("日期格式不能为空")
    out, pos, used = [], 0, set()
    for m in _TOKEN_RE.finditer(pattern):
        out.append(re.escape(pattern[pos:m.start()]))
        group = _TOKEN_REGEX[m.group(0)]
        name = group[4:group.index(">")]
        if name in used:
            raise ValueError(f"日期格式 {pattern} 中重复出现 {m.group(0)}")
        used.add(name)
        out.append(group)
        pos = m.end()
    if not used:
        raise ValueError(f"日期格式 {pattern} 未包含有效的日期占位符")
    out.append(re.escape(pattern[pos:]))
    return re.compile("^" + "".join(out) + "$")


def parse_date(value: str, pattern: str) -> datetime:
    """按 Java 风格格式解析日期。"""
    if value is None or not str(value).strip():
        raise ValueError("待解析的日期值不能为空")
    raw = str(value).strip()
    m = _pattern_regex(pattern).match(raw)
    if not m:
        raise ValueError(f"“{value}” 不符合格式 {pattern}")
    g = m.groupdict()
    return datetime(int(g.get("y") or 1970), int(g.get("mo") or 1), int(g.get("d") or 1),
                    int(g.get("h") or 0), int(g.get("mi") or 0), int(g.get("s") or 0))


def format_date(dt: datetime, pattern: str) -> str:
    """按 Java 风格格式输出日期。"""
    if not isinstance(pattern, str) or not pattern.strip() or not _TOKEN_RE.search(pattern):
        raise ValueError(f"目标日期格式 {pattern!r} 无效")
    values = {"yyyy": f"{dt.year:04d}", "MM": f"{dt.month:02d}", "M": str(dt.month), "dd": f"{dt.day:02d}",
              "d": str(dt.day), "HH": f"{dt.hour:02d}", "H": str(dt.hour), "mm": f"{dt.minute:02d}",
              "m": str(dt.minute), "ss": f"{dt.second:02d}", "s": str(dt.second)}
    return _TOKEN_RE.sub(lambda m: values[m.group(0)], pattern)


def convert_date(value: str, from_pattern: str, to_pattern: str) -> str:
    """日期格式转换，例如 20261005 / yyyyMMdd → 2026年10月5号。"""
    return format_date(parse_date(value, from_pattern), to_pattern)


def date_range(time_value: str, unit: str) -> tuple[str, str]:
    """计算某天或某月的起止时间（yyyyMMddHHmmss）。time_value 至少包含 yyyyMMdd 或分隔日期。"""
    if unit not in ("day", "month"):
        raise ValueError("unit 只能是 day 或 month")
    raw = str(time_value or "").strip()
    sep_match = _SEPARATED_DATE_RE.match(raw)
    if sep_match:
        dt = datetime(int(sep_match.group(1)), int(sep_match.group(2)), int(sep_match.group(3)))
    else:
        contig = re.search(r"\d{8}", raw)
        digits = contig.group(0) if contig else re.sub(r"\D", "", raw)
        if len(digits) < 8:
            raise ValueError("时间至少需要包含 yyyyMMdd 8 位数字")
        dt = datetime.strptime(digits[:8], "%Y%m%d")
    if unit == "day":
        day = dt.strftime("%Y%m%d")
        return day + "000000", day + "235959"
    last = calendar.monthrange(dt.year, dt.month)[1]
    return f"{dt.year:04d}{dt.month:02d}01000000", f"{dt.year:04d}{dt.month:02d}{last:02d}235959"
