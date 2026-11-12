"""回归用例存储：cases/<templateId>/<caseId>.yaml。

#Created By AiCoding(codex)
用例是测试数据，不参与发布版本（不随紧急切换回退），直接原子写文件。
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .fsutil import atomic_write_text, now_iso
from .layout import CASE_ID_RE, DataLayout, InvalidResource, ensure_within

log = logging.getLogger(__name__)
_CASE_ID_RE = CASE_ID_RE
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_YAML_TOP_KEY_RE = re.compile(
    rb'^(?:[A-Za-z0-9_\-\x80-\xff]+|"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\')\s*:(?:\s|$)'
)
_MAX_VALID_CACHE = 8192


class CaseDef(BaseModel):
    """一条回归用例。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str = ""
    source: str = "手工新建"
    inputs: dict[str, str] = Field(default_factory=dict)
    documentText: str = ""
    expectedValues: dict[str, str] = Field(default_factory=dict)
    lastResult: str = "未执行"
    lastRunId: str | None = None
    updatedAt: str = ""


class CaseStore:
    """用例增删改查（count 采用目录扫描 + 文件指纹轻量校验缓存，避免全量反序列化）。"""

    def __init__(self, layout: DataLayout, lock: threading.RLock) -> None:
        self.layout = layout
        self.lock = lock
        self._cache_lock = threading.Lock()
        self._valid_cache: dict[str, tuple[int, int, bool]] = {}

    def _dir(self, tid: int) -> Path:
        if not isinstance(tid, int) or isinstance(tid, bool) or tid <= 0:
            raise InvalidResource("模板编号必须为正整数")
        return ensure_within(self.layout.cases, self.layout.cases / str(tid))

    def _case_path(self, tid: int, case_id: str) -> Path:
        if not isinstance(case_id, str) or not _CASE_ID_RE.match(case_id):
            raise InvalidResource("用例编号只能包含字母、数字、下划线和短横线（1~40 位）")
        d = self._dir(tid)
        return ensure_within(d, d / f"{case_id}.yaml")

    def _remember_validity(self, path_str: str, mtime_ns: int, size: int, valid: bool) -> None:
        with self._cache_lock:
            if len(self._valid_cache) >= _MAX_VALID_CACHE and path_str not in self._valid_cache:
                self._valid_cache.pop(next(iter(self._valid_cache)), None)
            self._valid_cache[path_str] = (mtime_ns, size, valid)

    def _is_valid_case_file(self, path_str: str, mtime_ns: int, size: int) -> bool:
        """轻量判定用例文件是否为合法键值映射 YAML（命中指纹缓存时 0 文件打开开销）。"""
        if size <= 0:
            return False
        with self._cache_lock:
            cached = self._valid_cache.get(path_str)
        if cached is not None and cached[0] == mtime_ns and cached[1] == size:
            return cached[2]

        valid = False
        try:
            with open(path_str, "rb") as fp:
                head = fp.read(512)
            if head.startswith(b"\xef\xbb\xbf"):
                head = head[3:]
            for raw_line in head.splitlines():
                stripped = raw_line.strip()
                if not stripped or stripped.startswith(b"#") or stripped == b"---":
                    continue
                if stripped.startswith(b"{"):
                    with open(path_str, "rb") as fp_full:
                        parsed = yaml.load(fp_full.read(), Loader=_YAML_LOADER)
                    valid = isinstance(parsed, dict)
                else:
                    valid = bool(_YAML_TOP_KEY_RE.match(stripped))
                break
        except (OSError, yaml.YAMLError):
            valid = False

        self._remember_validity(path_str, mtime_ns, size, valid)
        return valid

    @staticmethod
    def _load_file(path: Path) -> CaseDef | None:
        try:
            raw = yaml.load(path.read_text(encoding="utf-8", errors="replace"), Loader=_YAML_LOADER)
        except (yaml.YAMLError, OSError) as exc:
            log.warning("读取用例文件失败 %s：%s", path, exc)
            return None
        if raw is None:
            return None
        if not isinstance(raw, dict):
            log.warning("用例文件结构不是对象 %s", path)
            return None
        raw.setdefault("id", path.stem)
        try:
            return CaseDef.model_validate(raw)
        except ValidationError as exc:
            log.warning("用例文件校验失败 %s：%s", path, exc)
            return None

    def list(self, tid: int) -> list[CaseDef]:
        d = self._dir(tid)
        if not d.exists():
            return []
        cases: list[CaseDef] = []
        for p in sorted(d.glob("*.yaml")):
            if p.name.startswith(".") or not _CASE_ID_RE.match(p.stem):
                continue
            case = self._load_file(p)
            try:
                st = p.stat()
                self._remember_validity(str(p), st.st_mtime_ns, st.st_size, case is not None)
            except OSError:
                pass
            if case is not None:
                cases.append(case)
        return cases

    def count(self, tid: int) -> int:
        """快速统计模板下合法回归用例数量（仅扫描目录项与轻量头校验，不执行全量 YAML 反序列化）。"""
        d = self._dir(tid)
        if not d.is_dir():
            return 0
        total = 0
        try:
            with os.scandir(d) as it:
                for entry in it:
                    name = entry.name
                    if name.startswith(".") or not name.endswith(".yaml"):
                        continue
                    stem = name[:-5]
                    if not _CASE_ID_RE.match(stem):
                        continue
                    try:
                        if not entry.is_file():
                            continue
                        st = entry.stat()
                    except OSError:
                        continue
                    if self._is_valid_case_file(entry.path, st.st_mtime_ns, st.st_size):
                        total += 1
        except OSError:
            return 0
        return total

    def get(self, tid: int, case_id: str) -> CaseDef | None:
        p = self._case_path(tid, case_id)
        if not p.is_file():
            return None
        return self._load_file(p)

    def next_id(self, tid: int) -> str:
        nums = [int(m.group(1)) for c in self.list(tid) if (m := re.match(r"C-(\d+)$", c.id))]
        return f"C-{(max(nums, default=0) + 1):02d}"

    def save(self, tid: int, case: CaseDef) -> CaseDef:
        p = self._case_path(tid, case.id)
        case.updatedAt = now_iso()
        with self.lock:
            atomic_write_text(p, yaml.safe_dump(case.model_dump(), allow_unicode=True, sort_keys=False, width=1000))
            try:
                st = p.stat()
                self._remember_validity(str(p), st.st_mtime_ns, st.st_size, True)
            except OSError:
                pass
        return case

    def delete(self, tid: int, case_id: str) -> bool:
        p = self._case_path(tid, case_id)
        with self.lock:
            if p.is_file():
                p.unlink()
                with self._cache_lock:
                    self._valid_cache.pop(str(p), None)
                return True
        return False

    def copy_all(self, src_tid: int, dst_tid: int) -> int:
        """复制模板时一并复制用例。"""
        n = 0
        for case in self.list(src_tid):
            self.save(dst_tid, case.model_copy(update={"source": f"复制自模板 {src_tid}"}))
            n += 1
        return n

    @staticmethod
    def from_payload(data: dict[str, Any], base: CaseDef | None = None) -> CaseDef:
        """兼容前端 RegressionCase：mobile/busiName/createTime/busiMonth 映射到 inputs。"""
        merged = base.model_dump() if base else {}
        merged.update({k: v for k, v in data.items() if v is not None})
        raw_inputs = merged.get("inputs")
        inputs = {str(k): ("" if v is None else str(v))
                  for k, v in (raw_inputs.items() if isinstance(raw_inputs, dict) else ())}
        for front_key, input_key in (("mobile", "手机号码"), ("busiName", "业务名称"),
                                     ("createTime", "创建时间"), ("busiMonth", "业务月份")):
            if data.get(front_key) is not None:
                inputs[input_key] = str(data[front_key])
        merged["inputs"] = inputs
        if isinstance(merged.get("expectedValues"), dict):
            merged["expectedValues"] = {str(k): ("" if v is None else str(v))
                                        for k, v in merged["expectedValues"].items()}
        try:
            return CaseDef.model_validate(merged)
        except ValidationError as exc:
            raise InvalidResource(f"用例数据不合法：{exc}") from exc
