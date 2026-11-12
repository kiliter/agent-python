"""运行记录：runs/YYYY/MM/DD/index.jsonl（每次运行一行摘要） + <runId>.json（完整过程）。

#Created By AiCoding(codex)
写入由单个后台协程负责（队列串行化），请求处理协程只负责投递，避免多个协程同时追加同一个 JSONL。
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import secrets
import shutil
import string
import threading
import time
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .fsutil import append_line, read_json, read_jsonl, write_json
from .layout import DataLayout, InvalidResource, ensure_within

log = logging.getLogger(__name__)

_ALPHABET = string.ascii_lowercase + string.digits
RUN_ID_RE = re.compile(r"^(\d{8})[A-Za-z0-9_\-]{1,56}$")


def new_run_id() -> str:
    """运行编号：yyyyMMddHHmmssSSS + 7 位随机字符，前 8 位即日期目录。"""
    now = datetime.now()
    return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}" + "".join(
        secrets.choice(_ALPHABET) for _ in range(7))


def _day_dir(root: Path, d: date) -> Path:
    return root / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _percentile(sorted_vals: list[int], q: float) -> int:
    if not sorted_vals:
        return 0
    idx = max(0, min(len(sorted_vals) - 1, math.ceil(len(sorted_vals) * q) - 1))
    return sorted_vals[idx]


def _parse_run_day(run_id: str) -> date | None:
    if not isinstance(run_id, str):
        return None
    m = RUN_ID_RE.match(run_id)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _normalize_summary(raw: dict[str, Any]) -> dict[str, Any] | None:
    """规整单条运行摘要，跳过缺少合法 runId 的损坏记录。"""
    if not isinstance(raw, dict):
        return None
    run_id = raw.get("runId")
    if not isinstance(run_id, str) or _parse_run_day(run_id) is None:
        return None
    tid_raw = raw.get("templateId")
    try:
        tid: int | None = int(tid_raw) if tid_raw is not None and str(tid_raw).strip() != "" else None
    except (TypeError, ValueError):
        tid = None
    status = str(raw.get("status") or "FAILED")
    if status not in ("SUCCESS", "PARTIAL", "FAILED"):
        status = "FAILED"
    skills = [str(s) for s in (raw.get("skills") or []) if isinstance(s, (str, int)) and str(s)] \
        if isinstance(raw.get("skills"), list) else []
    api_calls: list[dict[str, Any]] = []
    if isinstance(raw.get("apiCalls"), list):
        for c in raw["apiCalls"]:
            if isinstance(c, dict) and c.get("name"):
                api_calls.append({"name": str(c["name"]), "ok": bool(c.get("ok")), "ms": _safe_int(c.get("ms"))})
    return {
        **raw,
        "runId": run_id,
        "startTime": str(raw.get("startTime") or ""),
        "templateId": tid,
        "templateName": str(raw.get("templateName") or ""),
        "rev": str(raw.get("rev") or "—"),
        "target": str(raw.get("target") or "online"),
        "entry": str(raw.get("entry") or "上游调用"),
        "operator": str(raw.get("operator") or ""),
        "status": status,
        "error": str(raw["error"]) if raw.get("error") else None,
        "mobile": str(raw.get("mobile") or ""),
        "busiName": str(raw.get("busiName") or ""),
        "found": _safe_int(raw.get("found")),
        "total": _safe_int(raw.get("total")),
        "durationMs": _safe_int(raw.get("durationMs")),
        "rounds": _safe_int(raw.get("rounds")),
        "skills": skills,
        "apiCalls": api_calls,
        "retries": _safe_int(raw.get("retries")),
        "batchNo": str(raw["batchNo"]) if raw.get("batchNo") else None,
    }


def _summary_from_detail(detail: dict[str, Any]) -> dict[str, Any] | None:
    """当 index.jsonl 缺失或半行损坏时，从详情 JSON 恢复摘要。"""
    if not isinstance(detail, dict):
        return None
    inputs = detail.get("inputs") if isinstance(detail.get("inputs"), dict) else {}
    api_results = detail.get("apiResults") if isinstance(detail.get("apiResults"), list) else []
    val_rounds = detail.get("validationRounds") if isinstance(detail.get("validationRounds"), list) else []
    extra = detail.get("extra") if isinstance(detail.get("extra"), dict) else {}
    fields = detail.get("fields") if isinstance(detail.get("fields"), list) else []
    found = detail.get("foundCount")
    if found is None:
        found = sum(1 for f in fields if isinstance(f, dict) and f.get("status") == "found")
    total = detail.get("totalCount")
    if total is None:
        total = len(fields)
    return _normalize_summary({
        "runId": detail.get("runId"),
        "startTime": detail.get("startTime") or "",
        "templateId": detail.get("templateId"),
        "templateName": detail.get("templateName") or "",
        "rev": detail.get("rev") or "—",
        "target": detail.get("target") or "online",
        "entry": detail.get("entry") or "上游调用",
        "operator": detail.get("operator") or "",
        "status": detail.get("status") or "FAILED",
        "error": detail.get("error"),
        "mobile": inputs.get("手机号码", ""),
        "busiName": inputs.get("业务名称", ""),
        "found": found,
        "total": total,
        "durationMs": detail.get("durationMs") or 0,
        "rounds": detail.get("rounds") or 0,
        "skills": detail.get("skillsLoaded") if isinstance(detail.get("skillsLoaded"), list) else [],
        "apiCalls": [{"name": r.get("api"), "ok": r.get("ok"), "ms": r.get("costMs")}
                     for r in api_results if isinstance(r, dict) and r.get("api")],
        "retries": len(val_rounds),
        "batchNo": detail.get("batchNo") or extra.get("batchNo"),
    })


def _normalize_detail(detail: dict[str, Any], run_id: str) -> dict[str, Any]:
    """补齐不完整历史详情文件的缺失字段，防止视图层 KeyError。"""
    inputs = detail.get("inputs") if isinstance(detail.get("inputs"), dict) else {}
    fields = [f for f in (detail.get("fields") or []) if isinstance(f, dict) and f.get("name")] \
        if isinstance(detail.get("fields"), list) else []
    found = detail.get("foundCount")
    if found is None:
        found = sum(1 for f in fields if f.get("status") == "found")
    total = detail.get("totalCount")
    if total is None:
        total = len(fields)
    status = str(detail.get("status") or "FAILED")
    if status not in ("SUCCESS", "PARTIAL", "FAILED"):
        status = "FAILED"
    return {
        **detail,
        "runId": str(detail.get("runId") or run_id),
        "startTime": str(detail.get("startTime") or ""),
        "templateId": detail.get("templateId"),
        "templateName": str(detail.get("templateName") or ""),
        "rev": str(detail.get("rev") or "—"),
        "target": str(detail.get("target") or "online"),
        "entry": str(detail.get("entry") or "上游调用"),
        "operator": str(detail.get("operator") or ""),
        "status": status,
        "error": str(detail["error"]) if detail.get("error") else None,
        "inputs": {str(k): ("" if v is None else str(v)) for k, v in inputs.items()},
        "document": str(detail.get("document") or ""),
        "report": str(detail.get("report") or ""),
        "fields": fields,
        "missingShown": list(detail.get("missingShown") or []) if isinstance(detail.get("missingShown"), list) else [],
        "foundCount": _safe_int(found),
        "totalCount": _safe_int(total),
        "durationMs": _safe_int(detail.get("durationMs")),
        "rounds": _safe_int(detail.get("rounds")),
        "usage": detail.get("usage") if isinstance(detail.get("usage"), dict) else {},
        "skillsLoaded": list(detail.get("skillsLoaded") or []) if isinstance(detail.get("skillsLoaded"), list) else [],
        "apiResults": [r for r in (detail.get("apiResults") or []) if isinstance(r, dict)]
        if isinstance(detail.get("apiResults"), list) else [],
        "toolCalls": [t for t in (detail.get("toolCalls") or []) if isinstance(t, dict)]
        if isinstance(detail.get("toolCalls"), list) else [],
        "validationRounds": list(detail.get("validationRounds") or [])
        if isinstance(detail.get("validationRounds"), list) else [],
        "events": [e for e in (detail.get("events") or []) if isinstance(e, dict)]
        if isinstance(detail.get("events"), list) else [],
    }


def _detail_from_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """当 <runId>.json 缺失或损坏但 index.jsonl 存在摘要时，构造降级详情以便查看。"""
    inputs: dict[str, str] = {}
    if summary.get("mobile"):
        inputs["手机号码"] = str(summary["mobile"])
    if summary.get("busiName"):
        inputs["业务名称"] = str(summary["busiName"])
    err = summary.get("error") or "运行详情文件缺失或已损坏，已从运行索引摘要恢复基础信息"
    return _normalize_detail({
        "runId": summary["runId"],
        "startTime": summary.get("startTime") or "",
        "templateId": summary.get("templateId"),
        "templateName": summary.get("templateName") or "",
        "rev": summary.get("rev") or "—",
        "target": summary.get("target") or "online",
        "entry": summary.get("entry") or "上游调用",
        "operator": summary.get("operator") or "",
        "status": summary.get("status") or "FAILED",
        "error": err,
        "inputs": inputs,
        "document": "",
        "report": "",
        "fields": [],
        "missingShown": [],
        "foundCount": _safe_int(summary.get("found")),
        "totalCount": _safe_int(summary.get("total")),
        "durationMs": _safe_int(summary.get("durationMs")),
        "rounds": _safe_int(summary.get("rounds")),
        "usage": {},
        "skillsLoaded": list(summary.get("skills") or []),
        "apiResults": [],
        "toolCalls": [],
        "validationRounds": [[] for _ in range(_safe_int(summary.get("retries")))],
        "events": [],
        "batchNo": summary.get("batchNo"),
        "recoveredFromIndex": True,
    }, summary["runId"])


class RunStore:
    """运行记录的写入（异步单写者）与查询（启动扫孤儿 + 按日索引指纹缓存）。"""

    _MAX_DAY_CACHE = 400

    def __init__(self, layout: DataLayout) -> None:
        self.root = layout.runs
        self._queue: asyncio.Queue[tuple[dict[str, Any], dict[str, Any]] | None] | None = None
        self._task: asyncio.Task | None = None
        self._stats_cache: tuple[float, dict[str, Any]] | None = None
        self._orphan_recovered = False
        self._cache_lock = threading.Lock()
        self._day_cache: OrderedDict[Path, tuple[tuple[int, int, int], list[dict[str, Any]]]] = OrderedDict()
        self._pending: OrderedDict[str, tuple[dict[str, Any], dict[str, Any]]] = OrderedDict()

    # ------------------------------------------------------------------ 写入与启动恢复
    async def start(self) -> None:
        if not self._orphan_recovered:
            await asyncio.to_thread(self._recover_all_orphans)
        if self._task is not None and not self._task.done():
            return
        queue: asyncio.Queue[tuple[dict[str, Any], dict[str, Any]] | None] = asyncio.Queue()
        self._queue = queue
        self._task = asyncio.create_task(self._writer(queue), name="run-store-writer")

    def _stat_day_sig(self, ddir: Path, *, include_dir_mtime: bool) -> tuple[int, int, int]:
        ddir_mtime = 0
        if include_dir_mtime:
            try:
                ddir_mtime = ddir.stat().st_mtime_ns
            except OSError:
                ddir_mtime = -1
        idx_path = ddir / "index.jsonl"
        try:
            st = idx_path.stat()
            return (ddir_mtime, st.st_mtime_ns, st.st_size)
        except OSError:
            return (ddir_mtime, 0, -1)

    def _store_day_cache(self, ddir: Path, sig: tuple[int, int, int], items: list[dict[str, Any]]) -> None:
        with self._cache_lock:
            self._day_cache[ddir] = (sig, items)
            self._day_cache.move_to_end(ddir)
            while len(self._day_cache) > self._MAX_DAY_CACHE:
                self._day_cache.popitem(last=False)

    def _recover_day_orphans(self, ddir: Path, by_id: dict[str, dict[str, Any]], *, heal_index: bool) -> int:
        """扫描单日目录下未登记到 index.jsonl 的孤儿详情文件，可选补写回索引。"""
        try:
            with os.scandir(ddir) as it:
                entries = [
                    e for e in it
                    if not e.name.startswith(".") and e.name.endswith(".json") and e.is_file()
                ]
        except OSError:
            return 0
        entries.sort(key=lambda e: e.name)
        recovered_count = 0
        for entry in entries:
            stem = entry.name[:-5]
            if stem in by_id or _parse_run_day(stem) is None:
                continue
            detail = read_json(Path(entry.path))
            if isinstance(detail, dict):
                detail.setdefault("runId", stem)
                recovered = _summary_from_detail(detail)
                if recovered is not None:
                    by_id[recovered["runId"]] = recovered
                    recovered_count += 1
                    if heal_index:
                        try:
                            append_line(
                                ddir / "index.jsonl",
                                json.dumps(recovered, ensure_ascii=False, separators=(",", ":")),
                            )
                        except OSError:
                            pass
        return recovered_count

    def _recover_all_orphans(self) -> None:
        """启动阶段执行一次孤儿文件恢复，避免日常分页查询反复全目录扫描 *.json。"""
        for _, ddir in self._day_dirs_between(date.min, date.max):
            by_id: dict[str, dict[str, Any]] = {}
            for raw in read_jsonl(ddir / "index.jsonl"):
                norm = _normalize_summary(raw)
                if norm is not None:
                    by_id[norm["runId"]] = norm
            n = self._recover_day_orphans(ddir, by_id, heal_index=True)
            if n:
                log.info("启动恢复 %s 下 %d 条孤儿运行记录至 index.jsonl", ddir, n)
            items = list(by_id.values())
            items.sort(key=lambda x: x["runId"])
            sig = self._stat_day_sig(ddir, include_dir_mtime=False)
            self._store_day_cache(ddir, sig, items)
        self._orphan_recovered = True

    async def stop(self) -> None:
        """停止前把队列中剩余的记录写完，并重置状态使后续投递退回同步落盘。"""
        queue, task = self._queue, self._task
        self._queue = None
        self._task = None
        if queue is not None and task is not None:
            await queue.put(None)
            await task

    def submit(self, summary: dict[str, Any], detail: dict[str, Any]) -> None:
        """投递一条运行记录。未启动后台写入（如单元测试、命令行、已停止后）时同步写入。"""
        if self._queue is None:
            self._write(summary, detail)
        else:
            norm = _normalize_summary(summary)
            if norm is not None:
                with self._cache_lock:
                    self._pending[norm["runId"]] = (norm, detail)
            self._stats_cache = None
            self._queue.put_nowait((summary, detail))

    async def _writer(self, queue: asyncio.Queue[tuple[dict[str, Any], dict[str, Any]] | None]) -> None:
        while True:
            item = await queue.get()
            if item is None:
                break
            try:
                await asyncio.to_thread(self._write, *item)
            except Exception:  # noqa: BLE001 - 写记录失败不能影响主流程
                run_id = str(item[0].get("runId") or "")
                if run_id:
                    with self._cache_lock:
                        self._pending.pop(run_id, None)
                log.exception("写入运行记录失败 runId=%s", item[0].get("runId"))

    def _run_path(self, run_id: str) -> tuple[date, Path, Path] | None:
        day = _parse_run_day(run_id)
        if day is None:
            return None
        d = _day_dir(self.root, day)
        try:
            p = ensure_within(d, d / f"{run_id}.json")
        except InvalidResource:
            return None
        return day, d, p

    def _write(self, summary: dict[str, Any], detail: dict[str, Any]) -> None:
        run_id = str(summary.get("runId") or "")
        try:
            loc = self._run_path(run_id)
            if loc is None:
                raise InvalidResource(f"运行编号「{run_id}」格式不合法")
            _, d, json_path = loc
            inc_dir = not self._orphan_recovered
            pre_sig = self._stat_day_sig(d, include_dir_mtime=inc_dir)
            write_json(json_path, detail)
            append_line(d / "index.jsonl", json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
            norm = _normalize_summary(summary)
            post_sig = self._stat_day_sig(d, include_dir_mtime=inc_dir)
            with self._cache_lock:
                cached = self._day_cache.get(d)
                if cached is not None and cached[0] == pre_sig and norm is not None:
                    prev_items = cached[1]
                    if not prev_items or prev_items[-1]["runId"] < norm["runId"]:
                        next_items = [*prev_items, norm]
                    else:
                        merged = {it["runId"]: it for it in prev_items}
                        merged[norm["runId"]] = norm
                        next_items = sorted(merged.values(), key=lambda x: x["runId"])
                    self._day_cache[d] = (post_sig, next_items)
                    self._day_cache.move_to_end(d)
                else:
                    self._day_cache.pop(d, None)
            self._stats_cache = None
        finally:
            if run_id:
                with self._cache_lock:
                    self._pending.pop(run_id, None)

    # ------------------------------------------------------------------ 查询
    def _day_dirs_between(self, date_from: date, date_to: date) -> list[tuple[date, Path]]:
        """按日期倒序返回磁盘上实际存在且落在 [date_from, date_to] 内的日期目录。"""
        if not self.root.exists() or date_from > date_to:
            return []
        found: list[tuple[date, Path]] = []
        for ydir in self.root.iterdir():
            if not ydir.is_dir() or not ydir.name.isdigit() or len(ydir.name) != 4:
                continue
            year = int(ydir.name)
            if year < date_from.year or year > date_to.year:
                continue
            for mdir in ydir.iterdir():
                if not mdir.is_dir() or not mdir.name.isdigit():
                    continue
                month = int(mdir.name)
                for ddir in mdir.iterdir():
                    if not ddir.is_dir() or not ddir.name.isdigit():
                        continue
                    try:
                        d = date(year, month, int(ddir.name))
                    except ValueError:
                        continue
                    if date_from <= d <= date_to:
                        found.append((d, ddir))
        found.sort(key=lambda x: x[0], reverse=True)
        return found

    def _read_day_summaries(self, ddir: Path) -> list[dict[str, Any]]:
        """读取单日全部运行摘要（命中 (mtime_ns, size) 内存缓存时免磁盘解析与目录扫描）。"""
        inc_dir = not self._orphan_recovered
        sig = self._stat_day_sig(ddir, include_dir_mtime=inc_dir)
        with self._cache_lock:
            cached = self._day_cache.get(ddir)
            if cached is not None and cached[0] == sig:
                self._day_cache.move_to_end(ddir)
                return cached[1]

        by_id: dict[str, dict[str, Any]] = {}
        for raw in read_jsonl(ddir / "index.jsonl"):
            norm = _normalize_summary(raw)
            if norm is not None:
                by_id[norm["runId"]] = norm
        if inc_dir:
            self._recover_day_orphans(ddir, by_id, heal_index=False)
        items = list(by_id.values())
        items.sort(key=lambda x: x["runId"])
        if self._stat_day_sig(ddir, include_dir_mtime=inc_dir) == sig:
            self._store_day_cache(ddir, sig, items)
        return items

    def get(self, run_id: str) -> dict[str, Any] | None:
        """按运行编号读取完整记录；优先命中异步待落盘队列，详情文件损坏时尝试从当日索引摘要降级恢复。"""
        loc = self._run_path(run_id)
        if loc is None:
            return None
        with self._cache_lock:
            pend = self._pending.get(run_id)
        if pend is not None:
            return _normalize_detail(pend[1], run_id)
        _, d, json_path = loc
        raw = read_json(json_path)
        if isinstance(raw, dict):
            return _normalize_detail(raw, run_id)
        for item in read_jsonl(d / "index.jsonl"):
            norm = _normalize_summary(item)
            if norm and norm["runId"] == run_id:
                log.warning("运行详情缺失或损坏，已从索引摘要恢复 runId=%s", run_id)
                return _detail_from_summary(norm)
        return None

    def list(self, date_from: date | None = None, date_to: date | None = None, limit: int = 200,
             predicate=None, offset: int = 0) -> list[dict[str, Any]]:
        """按日期倒序扫描摘要（默认最近 7 天），合并尚未落盘的内存项，支持 predicate 过滤与 offset 分页。"""
        if limit <= 0 or offset < 0:
            return []
        date_to = date_to or date.today()
        date_from = date_from or (date_to - timedelta(days=6))
        if date_from > date_to:
            return []
        with self._cache_lock:
            pending_summaries = [pair[0] for pair in self._pending.values()]
        pending_by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for p_item in pending_summaries:
            p_day = _parse_run_day(p_item["runId"])
            if p_day is not None and date_from <= p_day <= date_to:
                pending_by_day[p_day].append(p_item)

        day_map: dict[date, Path] = dict(self._day_dirs_between(date_from, date_to))
        for p_day in pending_by_day:
            day_map.setdefault(p_day, _day_dir(self.root, p_day))

        result: list[dict[str, Any]] = []
        skipped = 0
        for d in sorted(day_map.keys(), reverse=True):
            ddir = day_map[d]
            items = self._read_day_summaries(ddir) if ddir.is_dir() else []
            pend_list = pending_by_day.get(d)
            if pend_list:
                merged = {it["runId"]: it for it in items}
                for p_item in pend_list:
                    merged.setdefault(p_item["runId"], p_item)
                items = sorted(merged.values(), key=lambda x: x["runId"])
            for item in reversed(items):
                if predicate is not None and not predicate(item):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                result.append(item)
                if len(result) >= limit:
                    return result
        return result

    def stats_7d(self) -> dict[str, Any]:
        """最近 7 天的统计（缓存 60 秒）：模板运行次数/成功率/耗时、Skill 加载次数、接口调用情况。"""
        if self._stats_cache and time.monotonic() - self._stats_cache[0] < 60:
            return self._stats_cache[1]
        stats = self.window_stats(days=7)
        self._stats_cache = (time.monotonic(), stats)
        return stats

    def window_stats(self, days: int = 7, today: date | None = None) -> dict[str, Any]:
        """统计最近 days 天内的运行成功率、耗时分布、模板/Skill/接口调用与按日趋势。"""
        days = max(1, min(int(days), 365))
        end_day = today or date.today()
        start_day = end_day - timedelta(days=days - 1)
        items = self.list(date_from=start_day, date_to=end_day, limit=10**9)

        tpl_runs: dict[str, int] = defaultdict(int)
        tpl_ok: dict[str, int] = defaultdict(int)
        tpl_partial: dict[str, int] = defaultdict(int)
        tpl_failed: dict[str, int] = defaultdict(int)
        tpl_durations: dict[str, list[int]] = defaultdict(list)
        skill_loads: dict[str, int] = defaultdict(int)
        api_calls: dict[str, list[tuple[bool, int]]] = defaultdict(list)
        by_entry: dict[str, int] = defaultdict(int)
        daily_map: dict[str, dict[str, Any]] = {
            (start_day + timedelta(days=i)).isoformat(): {
                "date": (start_day + timedelta(days=i)).isoformat(),
                "total": 0, "success": 0, "partial": 0, "failed": 0, "_durations": [],
            }
            for i in range(days)
        }

        all_durations: list[int] = []
        total_ok = 0
        total_partial = 0
        total_failed = 0
        found_fields = 0
        total_fields = 0
        total_retries = 0

        for item in items:
            st = item.get("status")
            dur = _safe_int(item.get("durationMs"))
            all_durations.append(dur)
            found_fields += _safe_int(item.get("found"))
            total_fields += _safe_int(item.get("total"))
            total_retries += _safe_int(item.get("retries"))
            by_entry[str(item.get("entry") or "上游调用")] += 1

            if st == "SUCCESS":
                total_ok += 1
            elif st == "PARTIAL":
                total_partial += 1
            else:
                total_failed += 1

            run_day = _parse_run_day(item["runId"])
            if run_day and run_day.isoformat() in daily_map:
                bucket = daily_map[run_day.isoformat()]
                bucket["total"] += 1
                bucket["_durations"].append(dur)
                if st == "SUCCESS":
                    bucket["success"] += 1
                elif st == "PARTIAL":
                    bucket["partial"] += 1
                else:
                    bucket["failed"] += 1

            tid_val = item.get("templateId")
            if tid_val is not None:
                tid = str(tid_val)
                tpl_runs[tid] += 1
                tpl_durations[tid].append(dur)
                if st == "SUCCESS":
                    tpl_ok[tid] += 1
                elif st == "PARTIAL":
                    tpl_partial[tid] += 1
                else:
                    tpl_failed[tid] += 1

            for s in item.get("skills") or []:
                if s:
                    skill_loads[str(s)] += 1
            for a in item.get("apiCalls") or []:
                if isinstance(a, dict) and a.get("name"):
                    api_calls[str(a["name"])].append((bool(a.get("ok")), _safe_int(a.get("ms"))))

        all_durations.sort()
        total_runs = len(items)
        templates_summary: dict[str, dict[str, Any]] = {}
        for k, v in tpl_runs.items():
            durs = sorted(tpl_durations[k])
            templates_summary[k] = {
                "runs": v,
                "success": tpl_ok[k],
                "partial": tpl_partial[k],
                "failed": tpl_failed[k],
                "avgDurationMs": int(sum(durs) / len(durs)) if durs else 0,
                "p95DurationMs": _percentile(durs, 0.95),
            }

        daily_list: list[dict[str, Any]] = []
        for day_key in sorted(daily_map):
            b = daily_map[day_key]
            durs = b.pop("_durations")
            b["avgDurationMs"] = int(sum(durs) / len(durs)) if durs else 0
            daily_list.append(b)

        return {
            "templates": templates_summary,
            "skills": dict(skill_loads),
            "apis": dict(api_calls),
            "summary": {
                "windowDays": days,
                "total": total_runs,
                "success": total_ok,
                "partial": total_partial,
                "failed": total_failed,
                "successRate": round(total_ok * 100 / total_runs, 1) if total_runs else 0.0,
                "successRateText": f"{total_ok * 100 / total_runs:.1f}%" if total_runs else "—",
                "foundFields": found_fields,
                "totalFields": total_fields,
                "fieldHitRate": round(found_fields * 100 / total_fields, 1) if total_fields else 0.0,
                "avgDurationMs": int(sum(all_durations) / total_runs) if total_runs else 0,
                "p95DurationMs": _percentile(all_durations, 0.95),
                "maxDurationMs": all_durations[-1] if all_durations else 0,
                "totalRetries": total_retries,
                "byEntry": dict(by_entry),
                "daily": daily_list,
            },
        }

    def cleanup(self, keep_days: int) -> int:
        """删除超过保留天数的日期目录。"""
        if keep_days <= 0 or not self.root.exists():
            return 0
        cutoff = date.today() - timedelta(days=keep_days)
        removed = 0
        for ydir in self.root.iterdir():
            for mdir in ydir.iterdir() if ydir.is_dir() else []:
                for ddir in mdir.iterdir() if mdir.is_dir() else []:
                    try:
                        d = date(int(ydir.name), int(mdir.name), int(ddir.name))
                    except ValueError:
                        continue
                    if d < cutoff:
                        shutil.rmtree(ddir, ignore_errors=True)
                        with self._cache_lock:
                            self._day_cache.pop(ddir, None)
                        removed += 1
        if removed:
            self._stats_cache = None
        return removed
