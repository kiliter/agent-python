"""确定性的文本与日期函数，供平台工具和证据校验使用。

#Created By AiCoding(codex)
normalize_text 与 Java StringCharCleaner 规则一致：NFKC 归一化后删除固定的中英文标点。
日期格式使用 Java 风格（yyyy、MM、M、dd、d、HH、H、mm、m、ss、s），与模板中的写法保持一致。
"""

from __future__ import annotations

import calendar
from datetime import date as _date, datetime, timedelta
from functools import lru_cache
import re
from typing import Any
import unicodedata

from ..domain.template import (
    MAX_REGEX_LENGTH as MAX_REGEX_LENGTH,
    safe_regex_compile as safe_regex_compile,
    safe_regex_fullmatch as safe_regex_fullmatch,
)

FIXED_CHARS_TO_REMOVE = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~！\"#$%&'（）*+，-。/：；<=>？@[\\]^_`{|}~"
_ZERO_WIDTH_CHARS = "\ufeff\u200b\u200c\u200d"
MAX_REGEX_TEXT_LENGTH = 200_000
MAX_PERIOD_MONTHS = 36

# #Created By AiCoding(codex) extract_dates 严格日历扫描规则（中文规则必须以显式“日/号”结尾，防止误吸套餐/月租/折扣数字）
_DATE_RULE1_CN_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_DATE_RULE2_SEP_RE = re.compile(r"(?<![A-Za-z0-9])(19\d{2}|20\d{2})([-/.])(\d{1,2})\2(\d{1,2})(?!\d)")
_DATE_RULE3_COMPACT_RE = re.compile(r"(?<![A-Za-z0-9])(19\d{2}|20\d{2})(\d{2})(\d{2})(?![A-Za-z0-9])")
_DATE_COMPACT_OPT_TIME_SCAN_RE = re.compile(
    r"(?<![A-Za-z0-9])(19\d{2}|20\d{2})(\d{2})(\d{2})(?:\d{4}|\d{6})?(?![A-Za-z0-9])"
)
_YM_CN_SCAN_RE = re.compile(r"(?<![A-Za-z0-9])(19\d{2}|20\d{2})\s*年\s*(\d{1,2})\s*月(?!\s*\d)")
_YM_SEP_SCAN_RE = re.compile(r"(?<![A-Za-z0-9])(19\d{2}|20\d{2})([-/.])(\d{1,2})(?![-\d/.])")
_YM_COMPACT_SCAN_RE = re.compile(r"(?<![A-Za-z0-9])(19\d{2}|20\d{2})(0[1-9]|1[0-2])(?![A-Za-z0-9])")
_DATE_RULE4_MD_RE = re.compile(r"(?<!\d)(?<!年)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
_TRAILING_DIGIT_OR_YEAR_RE = re.compile(r"(?:\d|年)\s*$")
_LEADING_YEAR_RE = re.compile(r"^(19\d{2}|20\d{2})(?!\d)")
_INDEPENDENT_YEAR_RE = re.compile(r"(?<![A-Za-z0-9])(19\d{2}|20\d{2})(?!\d)")

# #Created By AiCoding(codex) date_shift / expand_period / time_diff 精确解析规则
_COMPACT_YMD_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_COMPACT_YMDHMS_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$")
_SEP_YMD_OPT_TIME_RE = re.compile(
    r"^(\d{4})([-/.])(\d{1,2})\2(\d{1,2})(?:[T\s]+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$"
)
_CN_YMD_OPT_TIME_RE = re.compile(
    r"^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?"
    r"(?:\s*(\d{1,2})\s*(?:时|:)\s*(\d{1,2})(?:\s*(?:分|:)\s*(\d{1,2})\s*秒?)?)?$"
)
_PURE_YM_COMPACT_RE = re.compile(r"^(\d{4})(\d{2})$")
_PURE_YM_SEP_RE = re.compile(r"^(\d{4})([-/.])(\d{1,2})$")
_PURE_YM_CN_RE = re.compile(r"^(\d{4})\s*年\s*(\d{1,2})\s*月$")
_MULTI_PERIOD_SPLIT_RE = re.compile(r"[\$,，;；、]")
_EXPLICIT_RANGE_SPLIT_RE = re.compile(r"\s*(?:~|～|至|到|—|–)\s*")
_SEP_TIMESTAMP_RE = re.compile(r"^(\d{4})([-/.])(\d{1,2})\2(\d{1,2})[T\s]+(\d{1,2}):(\d{1,2}):(\d{1,2})$")
_CN_TIMESTAMP_RE = re.compile(
    r"^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?\s*"
    r"(\d{1,2})\s*(?:时|:)\s*(\d{1,2})\s*(?:分|:)\s*(\d{1,2})\s*秒?$"
)


@lru_cache(maxsize=64)
def _build_remove_table(extra_chars: str) -> dict[int, None]:
    """缓存 NFKC 归一化后的标点与附加字符删除转换表，避免逐行过滤时重复构造集合。#Created By AiCoding(codex)"""
    chars = unicodedata.normalize("NFKC", FIXED_CHARS_TO_REMOVE + _ZERO_WIDTH_CHARS + extra_chars)
    return str.maketrans("", "", chars)


def normalize_text(text: str | None, extra_chars: str = "") -> str:
    """NFKC 归一化并删除固定标点和 extra_chars 中的字符。"""
    if text is None:
        return ""
    raw = str(text)
    if not raw or not raw.strip():
        return ""
    return unicodedata.normalize("NFKC", raw).translate(_build_remove_table(extra_chars or ""))


def normalized_contains(content: str | None, target: str | None, extra_chars: str = "") -> bool:
    """清洗两边后判断包含；清洗后的 target 为空时返回 False。"""
    t = normalize_text(target, extra_chars)
    return bool(t) and t in normalize_text(content, extra_chars)


_TOKEN_RE = re.compile(r"yyyy|MM|M|dd|d|HH|H|mm|m|ss|s")
_TOKEN_REGEX = {"yyyy": r"(?P<y>\d{4})", "MM": r"(?P<mo>\d{2})", "M": r"(?P<mo>\d{1,2})",
                "dd": r"(?P<d>\d{2})", "d": r"(?P<d>\d{1,2})", "HH": r"(?P<h>\d{2})", "H": r"(?P<h>\d{1,2})",
                "mm": r"(?P<mi>\d{2})", "m": r"(?P<mi>\d{1,2})", "ss": r"(?P<s>\d{2})", "s": r"(?P<s>\d{1,2})"}


@lru_cache(maxsize=128)
def _compile_date_pattern(pattern: str) -> re.Pattern[str]:
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


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("日期格式不能为空")
    return _compile_date_pattern(pattern)


def parse_date(value: str, pattern: str) -> datetime:
    """按 Java 风格格式解析日期。"""
    if value is None or isinstance(value, bool) or not str(value).strip():
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


def _extract_date_from_text(raw: str) -> _date | None:
    """从整串或带前缀文本中严格提取首个真实日历日期，绝不盲拼非连续数字。#Created By AiCoding(codex)"""
    try:
        return _parse_calendar_date(raw)
    except ValueError:
        pass
    best: tuple[int, int, _date] | None = None
    for regex, is_sep in ((_DATE_RULE1_CN_RE, False), (_DATE_RULE2_SEP_RE, True), (_DATE_COMPACT_OPT_TIME_SCAN_RE, False)):
        for m in regex.finditer(raw):
            y = int(m.group(1))
            mo = int(m.group(3)) if is_sep else int(m.group(2))
            d = int(m.group(4)) if is_sep else int(m.group(3))
            dt = _try_make_date(y, mo, d)
            if dt is None:
                continue
            cand = (m.start(), m.end(), dt)
            if best is None or cand[:2] < best[:2]:
                best = cand
    return best[2] if best is not None else None


def _extract_year_month_from_text(raw: str) -> tuple[int, int] | None:
    """从整串或带前缀文本中提取合法年月 (year, month)。#Created By AiCoding(codex)"""
    ym = _try_parse_pure_year_month(raw)
    if ym is not None:
        return ym
    candidates: list[tuple[int, int, int, int]] = []
    for regex, is_sep in ((_DATE_RULE1_CN_RE, False), (_DATE_RULE2_SEP_RE, True), (_DATE_COMPACT_OPT_TIME_SCAN_RE, False)):
        for m in regex.finditer(raw):
            y = int(m.group(1))
            mo = int(m.group(3)) if is_sep else int(m.group(2))
            d = int(m.group(4)) if is_sep else int(m.group(3))
            dt = _try_make_date(y, mo, d)
            if dt is not None:
                candidates.append((m.start(), m.end(), dt.year, dt.month))
    for regex, m_group in ((_YM_CN_SCAN_RE, 2), (_YM_SEP_SCAN_RE, 3), (_YM_COMPACT_SCAN_RE, 2)):
        for m in regex.finditer(raw):
            year, month = int(m.group(1)), int(m.group(m_group))
            if 1900 <= year <= 2099 and 1 <= month <= 12:
                candidates.append((m.start(), m.end(), year, month))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2], candidates[0][3]


def date_range(time_value: str, unit: str) -> tuple[str, str]:
    """计算某天或某月的起止时间（yyyyMMddHHmmss）。#Created By AiCoding(codex)

    严格按边界提取日期（绝不盲拼非数字前缀后的散落数字）；unit="month" 时额外支持 6 位年月（yyyyMM / yyyy-M / yyyy年M月）。
    """
    if unit not in ("day", "month"):
        raise ValueError("unit 只能是 day 或 month")
    if time_value is None or isinstance(time_value, bool):
        raise ValueError("时间不能为空")
    raw = str(time_value).strip()
    if not raw:
        raise ValueError("时间不能为空")
    if unit == "day":
        dt = _extract_date_from_text(raw)
        if dt is None:
            raise ValueError(f"无法从“{time_value}”解析出合法日期（支持 yyyyMMdd、yyyyMMddHHmmss、yyyy-M-d、yyyy年M月d日）")
        day = dt.strftime("%Y%m%d")
        return day + "000000", day + "235959"
    ym = _extract_year_month_from_text(raw)
    if ym is None:
        raise ValueError(f"无法从“{time_value}”解析出合法年月或日期（支持 yyyyMM、yyyy-M、yyyy年M月、yyyyMMdd）")
    year, month = ym
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}{month:02d}01000000", f"{year:04d}{month:02d}{last:02d}235959"


# ============================================================================ 二期确定性原语函数
# #Created By AiCoding(codex)
def _try_make_date(year: int, month: int, day: int) -> _date | None:
    """校验真实日历合法性，非法日期返回 None。#Created By AiCoding(codex)"""
    try:
        return _date(year, month, day)
    except ValueError:
        return None


def _extract_default_year(default_year: str | int | None) -> int | None:
    """从 defaultYear 中提取合法的 4 位年份（1900~2099）。#Created By AiCoding(codex)"""
    if default_year is None or isinstance(default_year, bool):
        return None
    raw = str(default_year).strip()
    if not raw:
        return None
    if raw.isdigit():
        if len(raw) in (4, 6, 8, 12, 14) and (raw.startswith("19") or raw.startswith("20")):
            return int(raw[:4])
        return None
    m = _LEADING_YEAR_RE.match(raw)
    if m:
        return int(m.group(1))
    m2 = _INDEPENDENT_YEAR_RE.search(raw)
    return int(m2.group(1)) if m2 else None


def extract_dates(
    text: str | None = None,
    defaultYear: str | int | None = None,
    *,
    default_year: str | int | None = None,
) -> dict[str, Any]:
    """从文本中按严格规则扫描并经真实日历校验提取日期（yyyyMMdd）。#Created By AiCoding(codex)

    支持四类规则：
    1. 中文年月日：`yyyy年M月d日/号`
    2. 同分隔符年月日：`yyyy-M-d`、`yyyy/M/d`、`yyyy.M.d`（前后不紧邻字母数字）
    3. 独立 8 位数字：`yyyyMMdd`（前后不紧邻字母数字，不匹配活动编号或手机号/流水号子串）
    4. 无年份前缀的 `M月d日/号`：仅当传入合法 `defaultYear` 且不与带年份片段重叠时启用
    """
    source = "" if text is None else str(text)
    eff_default = defaultYear if defaultYear is not None else default_year
    covered_spans: list[tuple[int, int]] = []
    found_hits: list[tuple[int, int, str]] = []

    for rule_idx, regex in ((1, _DATE_RULE1_CN_RE), (2, _DATE_RULE2_SEP_RE), (3, _DATE_RULE3_COMPACT_RE)):
        for m in regex.finditer(source):
            start, end = m.span()
            covered_spans.append((start, end))
            if rule_idx == 2:
                y, mo, d = int(m.group(1)), int(m.group(3)), int(m.group(4))
            else:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt = _try_make_date(y, mo, d)
            if dt is not None:
                found_hits.append((start, end, dt.strftime("%Y%m%d")))

    year_fallback = _extract_default_year(eff_default)
    if year_fallback is not None:
        for m in _DATE_RULE4_MD_RE.finditer(source):
            start, end = m.span()
            if any(not (end <= cs or start >= ce) for cs, ce in covered_spans):
                continue
            if _TRAILING_DIGIT_OR_YEAR_RE.search(source, 0, start):
                continue
            dt = _try_make_date(year_fallback, int(m.group(1)), int(m.group(2)))
            if dt is not None:
                found_hits.append((start, end, dt.strftime("%Y%m%d")))

    found_hits.sort(key=lambda item: (item[0], item[1]))
    dates: list[str] = []
    seen: set[str] = set()
    for _, _, ymd in found_hits:
        if ymd not in seen:
            seen.add(ymd)
            dates.append(ymd)
    sorted_dates = sorted(dates)
    return {
        "dates": dates,
        "sorted": sorted_dates,
        "min": sorted_dates[0] if sorted_dates else None,
        "max": sorted_dates[-1] if sorted_dates else None,
        "count": len(dates),
    }


def _parse_calendar_date(raw_date: str) -> _date:
    """解析单个日期或时间戳文本为真实日历 date，非法输入抛出 ValueError。#Created By AiCoding(codex)"""
    if raw_date is None or isinstance(raw_date, bool):
        raise ValueError("日期不能为空")
    raw = str(raw_date).strip()
    if not raw:
        raise ValueError("日期不能为空")

    m = _COMPACT_YMD_RE.match(raw)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1900 <= y <= 2099):
            raise ValueError(f"日期年份超出合法范围：{raw_date}")
        return _date(y, mo, d)

    m = _COMPACT_YMDHMS_RE.match(raw)
    if m:
        y, mo, d, hh, mi, ss = (int(m.group(i)) for i in range(1, 7))
        if not (1900 <= y <= 2099):
            raise ValueError(f"日期年份超出合法范围：{raw_date}")
        return datetime(y, mo, d, hh, mi, ss).date()

    for regex in (_SEP_YMD_OPT_TIME_RE, _CN_YMD_OPT_TIME_RE):
        m = regex.match(raw)
        if m:
            if regex is _SEP_YMD_OPT_TIME_RE:
                y, mo, d = int(m.group(1)), int(m.group(3)), int(m.group(4))
                hh = int(m.group(5) or 0)
                mi = int(m.group(6) or 0)
                ss = int(m.group(7) or 0)
            else:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                hh = int(m.group(4) or 0)
                mi = int(m.group(5) or 0)
                ss = int(m.group(6) or 0)
            if not (1900 <= y <= 2099):
                raise ValueError(f"日期年份超出合法范围：{raw_date}")
            return datetime(y, mo, d, hh, mi, ss).date()

    raise ValueError(f"无法解析日期“{raw_date}”，支持 yyyyMMdd、yyyyMMddHHmmss、yyyy-M-d、yyyy/M/d、yyyy.M.d、yyyy年M月d日")


def date_shift(
    date: str,
    days: int = 0,
    endDays: int | None = None,
    *,
    end_days: int | None = None,
) -> dict[str, Any]:
    """按基准日期与天数偏移计算目标日期及起止时间窗口。#Created By AiCoding(codex)"""
    if isinstance(days, bool) or not isinstance(days, int):
        raise ValueError("days 必须是整数")
    eff_end = endDays if endDays is not None else end_days
    if eff_end is not None and (isinstance(eff_end, bool) or not isinstance(eff_end, int)):
        raise ValueError("endDays 必须是整数")
    base = _parse_calendar_date(date)
    start_dt = base + timedelta(days=days)
    end_dt = base + timedelta(days=days if eff_end is None else eff_end)
    if start_dt > end_dt:
        raise ValueError(f"起始偏移日期 {start_dt:%Y%m%d} 不能晚于结束偏移日期 {end_dt:%Y%m%d}")
    base_s = base.strftime("%Y%m%d")
    start_s = start_dt.strftime("%Y%m%d")
    end_s = end_dt.strftime("%Y%m%d")
    return {
        "baseDate": base_s,
        "date": start_s,
        "endDate": end_s,
        "start": start_s + "000000",
        "end": end_s + "235959",
    }


def _make_month_item(year: int, month: int) -> dict[str, str]:
    """生成单个月份的起止日期与时间戳字典。#Created By AiCoding(codex)"""
    last_day = calendar.monthrange(year, month)[1]
    ym = f"{year:04d}{month:02d}"
    start_d = f"{ym}01"
    end_d = f"{ym}{last_day:02d}"
    return {
        "month": ym,
        "startDate": start_d,
        "endDate": end_d,
        "start": start_d + "000000",
        "end": end_d + "235959",
    }


def _try_parse_pure_year_month(raw: str) -> tuple[int, int] | None:
    """尝试把文本解析为纯年月 (year, month)；格式不匹配返回 None，月份越界抛出 ValueError。#Created By AiCoding(codex)"""
    s = raw.strip()
    for regex, m_group in ((_PURE_YM_COMPACT_RE, 2), (_PURE_YM_SEP_RE, 3), (_PURE_YM_CN_RE, 2)):
        m = regex.match(s)
        if m:
            year, month = int(m.group(1)), int(m.group(m_group))
            if not (1900 <= year <= 2099):
                raise ValueError(f"账期年份超出合法范围：{raw}")
            if not (1 <= month <= 12):
                raise ValueError(f"账期月份不合法：{raw}")
            return year, month
    return None


def _parse_period_endpoint(raw: str, *, is_end: bool) -> _date:
    """解析区间端点：纯年月左端取 01 日、右端取当月最后一天；到日或时间戳取当日。#Created By AiCoding(codex)"""
    ym = _try_parse_pure_year_month(raw)
    if ym is not None:
        year, month = ym
        day = calendar.monthrange(year, month)[1] if is_end else 1
        return _date(year, month, day)
    return _parse_calendar_date(raw)


def _split_period_range(raw: str) -> tuple[str, str] | None:
    """识别区间连接符并切分左右端点；区分日期内部连字符与区间连字符。#Created By AiCoding(codex)"""
    parts = _EXPLICIT_RANGE_SPLIT_RE.split(raw)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    if len(parts) > 2:
        raise ValueError(f"区间连接符过多，无法解析：{raw}")

    if "-" not in raw:
        return None

    valid_splits: list[tuple[str, str]] = []
    for idx, ch in enumerate(raw):
        if ch != "-":
            continue
        left = raw[:idx].strip()
        right = raw[idx + 1:].strip()
        if not left or not right:
            continue
        try:
            _parse_period_endpoint(left, is_end=False)
            _parse_period_endpoint(right, is_end=True)
            valid_splits.append((left, right))
        except ValueError:
            continue
    if len(valid_splits) == 1:
        return valid_splits[0]
    return None


def expand_period(period: str) -> dict[str, Any]:
    """解析账期、单日或日期/年月区间，展开涉及的月份列表与总体起止窗口。#Created By AiCoding(codex)"""
    if period is None or isinstance(period, bool):
        raise ValueError("账期/日期文本不能为空")
    raw = str(period).strip()
    if not raw:
        raise ValueError("账期/日期文本不能为空")

    # 1. 多账期分隔（$、,、，、;、；、顿号）：
    #    - 恰好 2 段 A$B 且 A <= B 时按闭区间展开连续月份（对齐 Java billing-cycle-sms）；
    #    - 多于 2 段、无序 2 段或其它列表分隔符时按离散月份去重，并统一按月份升序排列输出。
    if _MULTI_PERIOD_SPLIT_RE.search(raw):
        segments = [seg.strip() for seg in _MULTI_PERIOD_SPLIT_RE.split(raw)]
        if any(not seg for seg in segments):
            raise ValueError(f"多账期列表存在空段：{period}")
        parsed_yms: list[tuple[int, int]] = []
        for seg in segments:
            ym = _try_parse_pure_year_month(seg)
            if ym is None:
                raise ValueError(f"无法将账期段“{seg}”解析为合法年月（如 yyyyMM、yyyy-M 或 yyyy年M月）")
            parsed_yms.append(ym)

        is_dollar_pair = "$" in raw and not re.search(r"[,，;；、]", raw) and len(parsed_yms) == 2
        if is_dollar_pair and parsed_yms[0] <= parsed_yms[1]:
            (y1, m1), (y2, m2) = parsed_yms
            total_months = (y2 - y1) * 12 + (m2 - m1) + 1
            if total_months > MAX_PERIOD_MONTHS:
                raise ValueError(f"区间跨度为 {total_months} 个月，超过上限（{MAX_PERIOD_MONTHS} 个月）")
            month_items: list[dict[str, str]] = []
            cur_y, cur_m = y1, m1
            for _ in range(total_months):
                month_items.append(_make_month_item(cur_y, cur_m))
                if cur_m == 12:
                    cur_y += 1
                    cur_m = 1
                else:
                    cur_m += 1
        else:
            unique_yms = sorted(set(parsed_yms))
            if len(unique_yms) > MAX_PERIOD_MONTHS:
                raise ValueError(f"账期月份数量为 {len(unique_yms)} 个月，超过上限（{MAX_PERIOD_MONTHS} 个月）")
            month_items = [_make_month_item(y, m) for y, m in unique_yms]

        overall_start = month_items[0]["startDate"]
        overall_end = month_items[-1]["endDate"]
        return {
            "months": [m["month"] for m in month_items],
            "monthRanges": month_items,
            "startDate": overall_start,
            "endDate": overall_end,
            "startTime": overall_start + "000000",
            "endTime": overall_end + "235959",
        }

    # 2. 单一纯年月
    ym = _try_parse_pure_year_month(raw)
    if ym is not None:
        item = _make_month_item(*ym)
        return {
            "months": [item["month"]],
            "monthRanges": [item],
            "startDate": item["startDate"],
            "endDate": item["endDate"],
            "startTime": item["start"],
            "endTime": item["end"],
        }

    # 3. 区间连接符（~、～、至、到，或两个端点之间的 -）
    range_pair = _split_period_range(raw)
    if range_pair is not None:
        left_raw, right_raw = range_pair
        start_dt = _parse_period_endpoint(left_raw, is_end=False)
        end_dt = _parse_period_endpoint(right_raw, is_end=True)
        if start_dt > end_dt:
            raise ValueError(f"区间起始日期 {start_dt:%Y%m%d} 不能晚于结束日期 {end_dt:%Y%m%d}")
        total_months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month) + 1
        if total_months > MAX_PERIOD_MONTHS:
            raise ValueError(f"区间跨度为 {total_months} 个月，超过上限（{MAX_PERIOD_MONTHS} 个月）")
        month_items = []
        cur_y, cur_m = start_dt.year, start_dt.month
        for _ in range(total_months):
            month_items.append(_make_month_item(cur_y, cur_m))
            if cur_m == 12:
                cur_y += 1
                cur_m = 1
            else:
                cur_m += 1
        overall_start = start_dt.strftime("%Y%m%d")
        overall_end = end_dt.strftime("%Y%m%d")
        return {
            "months": [m["month"] for m in month_items],
            "monthRanges": month_items,
            "startDate": overall_start,
            "endDate": overall_end,
            "startTime": overall_start + "000000",
            "endTime": overall_end + "235959",
        }

    # 4. 单一具体日期或时间戳
    day_dt = _parse_calendar_date(raw)
    item = _make_month_item(day_dt.year, day_dt.month)
    day_s = day_dt.strftime("%Y%m%d")
    return {
        "months": [item["month"]],
        "monthRanges": [item],
        "startDate": day_s,
        "endDate": day_s,
        "startTime": day_s + "000000",
        "endTime": day_s + "235959",
    }


def _parse_timestamp(raw_time: str) -> datetime:
    """解析精确到秒的时间戳（14位紧凑格式、分隔符格式或中文格式）。#Created By AiCoding(codex)"""
    if raw_time is None or isinstance(raw_time, bool):
        raise ValueError("时间戳不能为空")
    raw = str(raw_time).strip()
    if not raw:
        raise ValueError("时间戳不能为空")

    m = _COMPACT_YMDHMS_RE.match(raw)
    if m:
        y, mo, d, hh, mi, ss = (int(m.group(i)) for i in range(1, 7))
        if not (1900 <= y <= 2099):
            raise ValueError(f"时间戳年份超出合法范围：{raw_time}")
        return datetime(y, mo, d, hh, mi, ss)

    m = _SEP_TIMESTAMP_RE.match(raw)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(3)), int(m.group(4))
        hh, mi, ss = int(m.group(5)), int(m.group(6)), int(m.group(7))
        if not (1900 <= y <= 2099):
            raise ValueError(f"时间戳年份超出合法范围：{raw_time}")
        return datetime(y, mo, d, hh, mi, ss)

    m = _CN_TIMESTAMP_RE.match(raw)
    if m:
        y, mo, d, hh, mi, ss = (int(m.group(i)) for i in range(1, 7))
        if not (1900 <= y <= 2099):
            raise ValueError(f"时间戳年份超出合法范围：{raw_time}")
        return datetime(y, mo, d, hh, mi, ss)

    raise ValueError(f"无法解析时间戳“{raw_time}”，支持 yyyyMMddHHmmss、yyyy-M-d HH:mm:ss、yyyy/M/d HH:mm:ss")


def time_diff(time1: str, time2: str) -> dict[str, Any]:
    """计算两个时间戳之间的精确秒级差值（time1 - time2）。#Created By AiCoding(codex)"""
    dt1 = _parse_timestamp(time1)
    dt2 = _parse_timestamp(time2)
    delta = dt1 - dt2
    diff_seconds = delta.days * 86400 + delta.seconds
    later = "time1" if diff_seconds > 0 else ("time2" if diff_seconds < 0 else "equal")
    return {
        "diffSeconds": diff_seconds,
        "absSeconds": abs(diff_seconds),
        "later": later,
    }


def regex_extract(pattern: str, text: str | None = None, group: int = 1) -> dict[str, Any]:
    """使用安全编译的正则表达式提取非空匹配项。#Created By AiCoding(codex)"""
    if isinstance(group, bool) or not isinstance(group, int) or group < 0:
        raise ValueError("group 必须是非负整数")
    re_prog = safe_regex_compile(pattern)
    if group > re_prog.groups:
        if group == 1 and re_prog.groups == 0:
            eff_group = 0
        else:
            raise ValueError(f"group={group} 超出正则捕获组数量（共 {re_prog.groups} 个捕获组）")
    else:
        eff_group = group

    source = "" if text is None else str(text)
    if len(source) > MAX_REGEX_TEXT_LENGTH:
        raise ValueError(f"待匹配文本长度超过安全上限（{MAX_REGEX_TEXT_LENGTH} 字符）")
    matches: list[str] = []
    all_matches: list[str] = []
    seen: set[str] = set()
    for m in re_prog.finditer(source):
        val = m.group(eff_group)
        if not val:
            continue
        all_matches.append(val)
        if val not in seen:
            seen.add(val)
            matches.append(val)
    return {
        "matches": matches,
        "allMatches": all_matches,
        "first": matches[0] if matches else None,
        "count": len(matches),
    }
