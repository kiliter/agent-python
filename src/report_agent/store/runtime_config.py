"""磁盘持久化的运行期热更新配置仓库（统一网关 + 大模型 / 智能体参数 + 版本历史与回退）。

#Created By AiCoding(codex)
目录结构（位于 data/config/runtime/，所有文件权限严格限制为 0600）：
├── current.json        当前生效配置与元数据（activeRev、operator、source、time、note、config）
├── index.jsonl         修订日志（c1, c2, ...，不含明文密钥）
└── revisions/
    └── cN.json         每个版本的完整不可变快照（含密钥，用于精确回退，权限 0600）
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import SecretStr

from ..config import Settings
from .fsutil import _fsync_dir, append_line, fmt_time, now_iso, read_json, read_jsonl
from .layout import DataLayout, InvalidResource, ensure_within
from .service import ResourceNotFound

log = logging.getLogger(__name__)

CONFIG_REV_RE = re.compile(r"^c[1-9]\d{0,9}$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_OR_CTRL_RE = re.compile(r"[\s\x00-\x1f\x7f]")

OutputMode = Literal["tool", "native", "json_object", "prompted"]
GatewayMode = Literal["mock", "live"]
XmlStyle = Literal["java", "clean"]

_VALID_OUTPUT_MODES: tuple[OutputMode, ...] = ("tool", "native", "json_object", "prompted")
_VALID_GATEWAY_MODES: tuple[GatewayMode, ...] = ("mock", "live")
_VALID_XML_STYLES: tuple[XmlStyle, ...] = ("java", "clean")
_DEFAULT_FALLBACK_SETTINGS = Settings(_env_file=None)

_ORDERED_FIELDS: tuple[str, ...] = (
    "llmBaseUrl",
    "llmApiKey",
    "llmModel",
    "llmTemperature",
    "llmMaxTokens",
    "llmTimeoutS",
    "llmHttpRetries",
    "llmParallelToolCalls",
    "llmStrictTools",
    "llmToolChoiceRequired",
    "agentOutputMode",
    "agentNativeStrict",
    "agentOutputRetries",
    "agentToolRetries",
    "agentRequestLimit",
    "agentToolCallsLimit",
    "agentRunTimeoutS",
    "agentMaxConcurrentRuns",
    "agentPreviewRows",
    "gatewayMode",
    "gatewayUrl",
    "gatewayAppId",
    "gatewayAccessToken",
    "gatewayXmlStyle",
    "gatewayConnectTimeoutS",
)


class RuntimeConfigValidationError(InvalidResource):
    """运行配置参数校验失败（映射为 HTTP 400）。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("；".join(errors))
        self.errors = errors


def mask_secret(value: str | None) -> str:
    """脱敏密钥用于管理端展示：空串返回 ""，短密钥返回 "***"，长密钥保留前缀与末 4 位（如 sk-***abcd）。"""
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    if len(value) <= 10:
        return f"{value[:2]}***{value[-2:]}"
    return f"{value[:3]}***{value[-4:]}"


def _chmod_safe(path_or_fd: Path | int, mode: int) -> None:
    try:
        if isinstance(path_or_fd, int):
            if hasattr(os, "fchmod"):
                os.fchmod(path_or_fd, mode)
        else:
            path_or_fd.chmod(mode)
    except OSError:
        pass


def _atomic_write_json_600(path: Path, data: Any) -> None:
    """以 0o600 权限原子写入 JSON 文件（先设置临时文件权限再落盘替换，避免任何权限裸露窗口）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        _chmod_safe(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        _chmod_safe(Path(tmp), 0o600)
        os.replace(tmp, path)
        _chmod_safe(path, 0o600)
        _fsync_dir(path.parent)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _append_jsonl_600(path: Path, entry: dict[str, Any]) -> None:
    """以 0o600 权限追加一行 JSONL 记录并 fsync。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        _chmod_safe(fd, 0o600)
        with os.fdopen(fd, "ab") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    _chmod_safe(path, 0o600)


def _check_http_url(url: str, label: str) -> str | None:
    if _WHITESPACE_OR_CTRL_RE.search(url):
        return f"{label}不能包含空白或控制字符"
    if not url.startswith(("http://", "https://")):
        return f"{label}必须以 http:// 或 https:// 开头"
    parsed = urlsplit(url)
    if not parsed.netloc or not parsed.hostname:
        return f"{label}缺少有效的主机地址"
    return None


def _coerce_bool(val: Any, label: str, errors: list[str]) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
    errors.append(f"{label}必须是布尔值")
    return False


def _coerce_optional_bool(val: Any, label: str, errors: list[str]) -> bool | None:
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ("null", "none", "default", "auto"):
            return None
        if low == "true":
            return True
        if low == "false":
            return False
    errors.append(f"{label}必须是布尔值或 null")
    return None


def _coerce_int(val: Any, label: str, errors: list[str], *, min_val: int | None = None,
                max_val: int | None = None) -> int:
    if isinstance(val, bool):
        errors.append(f"{label}必须是整数")
        return min_val or 0
    parsed: int | None = None
    if isinstance(val, int):
        parsed = val
    elif isinstance(val, str) and val.strip():
        s = val.strip()
        if re.fullmatch(r"[+-]?\d+", s):
            parsed = int(s)
    if parsed is None:
        errors.append(f"{label}必须是整数")
        return min_val or 0
    if min_val is not None and parsed < min_val:
        if max_val is not None:
            errors.append(f"{label}必须在 {min_val}~{max_val} 之间")
        else:
            errors.append(f"{label}必须大于等于 {min_val}")
    elif max_val is not None and parsed > max_val:
        if min_val is not None:
            errors.append(f"{label}必须在 {min_val}~{max_val} 之间")
        else:
            errors.append(f"{label}必须小于等于 {max_val}")
    return parsed


def _coerce_optional_int(val: Any, label: str, errors: list[str], *, min_val: int = 1) -> int | None:
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    return _coerce_int(val, label, errors, min_val=min_val)


def _coerce_float(val: Any, label: str, errors: list[str], *, min_val: float | None = None,
                  max_val: float | None = None, gt_zero: bool = False) -> float:
    if isinstance(val, bool):
        errors.append(f"{label}必须是数字")
        return 1.0
    parsed: float | None = None
    if isinstance(val, (int, float)):
        parsed = float(val)
    elif isinstance(val, str) and val.strip():
        try:
            parsed = float(val.strip())
        except ValueError:
            parsed = None
    if parsed is None or math.isnan(parsed) or math.isinf(parsed):
        errors.append(f"{label}必须是有效数字")
        return 1.0
    if gt_zero and parsed <= 0:
        errors.append(f"{label}必须大于 0")
    else:
        if min_val is not None and parsed < min_val:
            if max_val is not None:
                errors.append(f"{label}必须在 {min_val:g}~{max_val:g} 之间")
            else:
                errors.append(f"{label}必须大于等于 {min_val:g}")
        elif max_val is not None and parsed > max_val:
            if min_val is not None:
                errors.append(f"{label}必须在 {min_val:g}~{max_val:g} 之间")
            else:
                errors.append(f"{label}必须小于等于 {max_val:g}")
    return parsed


def _resolve_secret(raw: Any, current_secret: str, clear_flag: bool, label: str, errors: list[str]) -> str:
    if clear_flag:
        return ""
    if raw is None:
        return current_secret
    if not isinstance(raw, str):
        errors.append(f"{label}必须是字符串")
        return current_secret
    cleaned = raw.strip()
    if not cleaned or cleaned == "***" or cleaned == mask_secret(current_secret):
        return current_secret
    if _CONTROL_CHAR_RE.search(cleaned):
        errors.append(f"{label}包含非法控制字符")
        return current_secret
    return cleaned


@dataclass(frozen=True)
class RuntimeConfig:
    """受版本化热更新管理的全部运行参数。"""

    # LLM
    llmBaseUrl: str
    llmApiKey: str
    llmModel: str
    llmTemperature: float
    llmMaxTokens: int | None
    llmTimeoutS: float
    llmHttpRetries: int
    llmParallelToolCalls: bool | None
    llmStrictTools: bool | None
    llmToolChoiceRequired: bool | None
    # Agent
    agentOutputMode: OutputMode
    agentNativeStrict: bool
    agentOutputRetries: int
    agentToolRetries: int
    agentRequestLimit: int
    agentToolCallsLimit: int
    agentRunTimeoutS: float
    agentMaxConcurrentRuns: int
    agentPreviewRows: int
    # Gateway
    gatewayMode: GatewayMode
    gatewayUrl: str
    gatewayAppId: str
    gatewayAccessToken: str
    gatewayXmlStyle: XmlStyle
    gatewayConnectTimeoutS: float

    @classmethod
    def from_settings(cls, s: Settings) -> RuntimeConfig:
        """从 Settings（环境变量 / .env）提取初始运行配置。"""
        return cls(
            llmBaseUrl=(s.llm_base_url or "").strip(),
            llmApiKey=s.llm_api_key.get_secret_value() if s.llm_api_key else "",
            llmModel=(s.llm_model or "").strip(),
            llmTemperature=float(s.llm_temperature),
            llmMaxTokens=int(s.llm_max_tokens) if s.llm_max_tokens is not None else None,
            llmTimeoutS=float(s.llm_timeout_s),
            llmHttpRetries=int(s.llm_http_retries),
            llmParallelToolCalls=s.llm_parallel_tool_calls,
            llmStrictTools=s.llm_strict_tools,
            llmToolChoiceRequired=s.llm_tool_choice_required,
            agentOutputMode=s.agent_output_mode,
            agentNativeStrict=bool(s.agent_native_strict),
            agentOutputRetries=int(s.agent_output_retries),
            agentToolRetries=int(s.agent_tool_retries),
            agentRequestLimit=int(s.agent_request_limit),
            agentToolCallsLimit=int(s.agent_tool_calls_limit),
            agentRunTimeoutS=float(s.agent_run_timeout_s),
            agentMaxConcurrentRuns=int(s.agent_max_concurrent_runs),
            agentPreviewRows=int(s.agent_preview_rows),
            gatewayMode=s.gateway_mode,
            gatewayUrl=(s.gateway_url or "").strip(),
            gatewayAppId=s.gateway_app_id.get_secret_value() if s.gateway_app_id else "",
            gatewayAccessToken=s.gateway_access_token.get_secret_value() if s.gateway_access_token else "",
            gatewayXmlStyle=s.gateway_xml_style,
            gatewayConnectTimeoutS=float(s.gateway_connect_timeout_s),
        )

    @classmethod
    def from_storage_dict(cls, data: dict[str, Any], fallback_settings: Settings | None = None) -> RuntimeConfig:
        """从磁盘字典恢复，缺失的新增字段自动回退到 fallback_settings。"""
        base = cls.from_settings(fallback_settings or _DEFAULT_FALLBACK_SETTINGS)
        merged = base.to_storage_dict()
        if isinstance(data, dict):
            for k in _ORDERED_FIELDS:
                if k in data:
                    merged[k] = data[k]
        return cls(
            llmBaseUrl=str(merged["llmBaseUrl"] or "").strip(),
            llmApiKey=str(merged["llmApiKey"] or ""),
            llmModel=str(merged["llmModel"] or "").strip(),
            llmTemperature=float(merged["llmTemperature"]),
            llmMaxTokens=int(merged["llmMaxTokens"]) if merged["llmMaxTokens"] is not None else None,
            llmTimeoutS=float(merged["llmTimeoutS"]),
            llmHttpRetries=int(merged["llmHttpRetries"]),
            llmParallelToolCalls=merged["llmParallelToolCalls"] if isinstance(merged["llmParallelToolCalls"], bool) else None,
            llmStrictTools=merged["llmStrictTools"] if isinstance(merged["llmStrictTools"], bool) else None,
            llmToolChoiceRequired=merged["llmToolChoiceRequired"] if isinstance(merged["llmToolChoiceRequired"], bool) else None,
            agentOutputMode=merged["agentOutputMode"] if merged["agentOutputMode"] in _VALID_OUTPUT_MODES else base.agentOutputMode,
            agentNativeStrict=bool(merged["agentNativeStrict"]),
            agentOutputRetries=int(merged["agentOutputRetries"]),
            agentToolRetries=int(merged["agentToolRetries"]),
            agentRequestLimit=int(merged["agentRequestLimit"]),
            agentToolCallsLimit=int(merged["agentToolCallsLimit"]),
            agentRunTimeoutS=float(merged["agentRunTimeoutS"]),
            agentMaxConcurrentRuns=int(merged["agentMaxConcurrentRuns"]),
            agentPreviewRows=int(merged["agentPreviewRows"]),
            gatewayMode=merged["gatewayMode"] if merged["gatewayMode"] in _VALID_GATEWAY_MODES else base.gatewayMode,
            gatewayUrl=str(merged["gatewayUrl"] or "").strip(),
            gatewayAppId=str(merged["gatewayAppId"] or ""),
            gatewayAccessToken=str(merged["gatewayAccessToken"] or ""),
            gatewayXmlStyle=merged["gatewayXmlStyle"] if merged["gatewayXmlStyle"] in _VALID_XML_STYLES else base.gatewayXmlStyle,
            gatewayConnectTimeoutS=float(merged["gatewayConnectTimeoutS"]),
        )

    def to_storage_dict(self) -> dict[str, Any]:
        """转换为落盘快照字典（含密钥，仅用于 0600 磁盘存储）。"""
        return {k: getattr(self, k) for k in _ORDERED_FIELDS}

    def to_public_dict(self) -> dict[str, Any]:
        """转换为管理端公开字典（绝不暴露任何明文密钥）。"""
        return {
            "llmBaseUrl": self.llmBaseUrl,
            "hasLlmApiKey": bool(self.llmApiKey),
            "llmApiKeyMasked": mask_secret(self.llmApiKey),
            "llmModel": self.llmModel,
            "llmTemperature": self.llmTemperature,
            "llmMaxTokens": self.llmMaxTokens,
            "llmTimeoutS": self.llmTimeoutS,
            "llmHttpRetries": self.llmHttpRetries,
            "llmParallelToolCalls": self.llmParallelToolCalls,
            "llmStrictTools": self.llmStrictTools,
            "llmToolChoiceRequired": self.llmToolChoiceRequired,
            "agentOutputMode": self.agentOutputMode,
            "agentNativeStrict": self.agentNativeStrict,
            "agentOutputRetries": self.agentOutputRetries,
            "agentToolRetries": self.agentToolRetries,
            "agentRequestLimit": self.agentRequestLimit,
            "agentToolCallsLimit": self.agentToolCallsLimit,
            "agentRunTimeoutS": self.agentRunTimeoutS,
            "agentMaxConcurrentRuns": self.agentMaxConcurrentRuns,
            "agentPreviewRows": self.agentPreviewRows,
            "gatewayMode": self.gatewayMode,
            "gatewayUrl": self.gatewayUrl,
            "hasGatewayAppId": bool(self.gatewayAppId),
            "gatewayAppIdMasked": mask_secret(self.gatewayAppId),
            "hasGatewayAccessToken": bool(self.gatewayAccessToken),
            "gatewayAccessTokenMasked": mask_secret(self.gatewayAccessToken),
            "gatewayXmlStyle": self.gatewayXmlStyle,
            "gatewayConnectTimeoutS": self.gatewayConnectTimeoutS,
        }

    def to_effective_settings(self, base_settings: Settings) -> Settings:
        """基于启动环境变量 Settings 生成叠加当前运行配置后的生效 Settings 副本。"""
        return base_settings.model_copy(
            update={
                "llm_base_url": self.llmBaseUrl,
                "llm_api_key": SecretStr(self.llmApiKey),
                "llm_model": self.llmModel,
                "llm_temperature": self.llmTemperature,
                "llm_max_tokens": self.llmMaxTokens,
                "llm_timeout_s": self.llmTimeoutS,
                "llm_http_retries": self.llmHttpRetries,
                "llm_parallel_tool_calls": self.llmParallelToolCalls,
                "llm_strict_tools": self.llmStrictTools,
                "llm_tool_choice_required": self.llmToolChoiceRequired,
                "agent_output_mode": self.agentOutputMode,
                "agent_native_strict": self.agentNativeStrict,
                "agent_output_retries": self.agentOutputRetries,
                "agent_tool_retries": self.agentToolRetries,
                "agent_request_limit": self.agentRequestLimit,
                "agent_tool_calls_limit": self.agentToolCallsLimit,
                "agent_run_timeout_s": self.agentRunTimeoutS,
                "agent_max_concurrent_runs": self.agentMaxConcurrentRuns,
                "agent_preview_rows": self.agentPreviewRows,
                "gateway_mode": self.gatewayMode,
                "gateway_url": self.gatewayUrl,
                "gateway_app_id": SecretStr(self.gatewayAppId),
                "gateway_access_token": SecretStr(self.gatewayAccessToken),
                "gateway_xml_style": self.gatewayXmlStyle,
                "gateway_connect_timeout_s": self.gatewayConnectTimeoutS,
            }
        )

    def diff_keys(self, other: RuntimeConfig) -> list[str]:
        """按标准顺序返回两个配置之间发生变化的字段名列表。"""
        return [k for k in _ORDERED_FIELDS if getattr(self, k) != getattr(other, k)]

    def validate(self) -> None:
        """完整校验所有字段的合法性与区间约束，不通过则抛出 RuntimeConfigValidationError。"""
        errors: list[str] = []
        if not self.llmBaseUrl:
            errors.append("大模型接口地址 llmBaseUrl 不能为空")
        else:
            err = _check_http_url(self.llmBaseUrl, "大模型接口地址 llmBaseUrl ")
            if err:
                errors.append(err)

        if not self.llmModel:
            errors.append("模型名称 llmModel 不能为空")
        elif _CONTROL_CHAR_RE.search(self.llmModel):
            errors.append("模型名称 llmModel 包含非法控制字符")

        if math.isnan(self.llmTemperature) or math.isinf(self.llmTemperature) or not (0.0 <= self.llmTemperature <= 2.0):
            errors.append("采样温度 llmTemperature 必须在 0~2 之间")
        if self.llmMaxTokens is not None and self.llmMaxTokens < 1:
            errors.append("最大输出 Token 数 llmMaxTokens 必须大于等于 1")
        if math.isnan(self.llmTimeoutS) or math.isinf(self.llmTimeoutS) or self.llmTimeoutS <= 0:
            errors.append("模型请求超时 llmTimeoutS 必须大于 0")
        if not (0 <= self.llmHttpRetries <= 10):
            errors.append("模型 HTTP 重试次数 llmHttpRetries 必须在 0~10 之间")

        if self.agentOutputMode not in _VALID_OUTPUT_MODES:
            errors.append(f"结构化交卷方式 agentOutputMode 不合法：{self.agentOutputMode}")
        if not (0 <= self.agentOutputRetries <= 10):
            errors.append("证据校验重试次数 agentOutputRetries 必须在 0~10 之间")
        if not (0 <= self.agentToolRetries <= 10):
            errors.append("工具参数重试次数 agentToolRetries 必须在 0~10 之间")
        if not (1 <= self.agentRequestLimit <= 200):
            errors.append("单次最大轮数 agentRequestLimit 必须在 1~200 之间")
        if not (1 <= self.agentToolCallsLimit <= 500):
            errors.append("单次最大工具调用数 agentToolCallsLimit 必须在 1~500 之间")
        if math.isnan(self.agentRunTimeoutS) or math.isinf(self.agentRunTimeoutS) or self.agentRunTimeoutS <= 0:
            errors.append("单次运行总超时 agentRunTimeoutS 必须大于 0")
        if not (1 <= self.agentMaxConcurrentRuns <= 128):
            errors.append("最大并发运行数 agentMaxConcurrentRuns 必须在 1~128 之间")
        if not (1 <= self.agentPreviewRows <= 200):
            errors.append("接口预览行数 agentPreviewRows 必须在 1~200 之间")

        if self.gatewayMode not in _VALID_GATEWAY_MODES:
            errors.append(f"统一网关模式 gatewayMode 不合法：{self.gatewayMode}")
        if self.gatewayMode == "live" and not self.gatewayUrl:
            errors.append("网关模式为 live 时必须配置网关地址 gatewayUrl")
        if self.gatewayUrl:
            err = _check_http_url(self.gatewayUrl, "统一网关地址 gatewayUrl ")
            if err:
                errors.append(err)
        if self.gatewayXmlStyle not in _VALID_XML_STYLES:
            errors.append(f"网关 XML 风格 gatewayXmlStyle 不合法：{self.gatewayXmlStyle}")
        if (
            math.isnan(self.gatewayConnectTimeoutS)
            or math.isinf(self.gatewayConnectTimeoutS)
            or self.gatewayConnectTimeoutS <= 0
        ):
            errors.append("网关连接超时 gatewayConnectTimeoutS 必须大于 0")

        if errors:
            raise RuntimeConfigValidationError(errors)

    def apply_patch(
        self,
        patch: dict[str, Any],
        *,
        clear_llm_api_key: bool = False,
        clear_gateway_app_id: bool = False,
        clear_gateway_access_token: bool = False,
    ) -> RuntimeConfig:
        """在当前配置上应用局部或全量更新补丁，处理密钥保留/清空并做严格类型与边界校验。"""
        errors: list[str] = []

        def _str_field(key: str, default: str, label: str) -> str:
            if key not in patch or patch[key] is None:
                return default
            if not isinstance(patch[key], str):
                errors.append(f"{label}必须是字符串")
                return default
            return patch[key].strip()

        llm_base_url = _str_field("llmBaseUrl", self.llmBaseUrl, "llmBaseUrl")
        llm_model = _str_field("llmModel", self.llmModel, "llmModel")
        llm_temperature = (
            _coerce_float(patch["llmTemperature"], "采样温度 llmTemperature", errors, min_val=0.0, max_val=2.0)
            if "llmTemperature" in patch and patch["llmTemperature"] is not None
            else self.llmTemperature
        )
        llm_max_tokens = (
            _coerce_optional_int(patch["llmMaxTokens"], "最大输出 Token 数 llmMaxTokens", errors, min_val=1)
            if "llmMaxTokens" in patch
            else self.llmMaxTokens
        )
        llm_timeout_s = (
            _coerce_float(patch["llmTimeoutS"], "模型请求超时 llmTimeoutS", errors, gt_zero=True)
            if "llmTimeoutS" in patch and patch["llmTimeoutS"] is not None
            else self.llmTimeoutS
        )
        llm_http_retries = (
            _coerce_int(patch["llmHttpRetries"], "模型 HTTP 重试次数 llmHttpRetries", errors, min_val=0, max_val=10)
            if "llmHttpRetries" in patch and patch["llmHttpRetries"] is not None
            else self.llmHttpRetries
        )
        llm_parallel = (
            _coerce_optional_bool(patch["llmParallelToolCalls"], "llmParallelToolCalls", errors)
            if "llmParallelToolCalls" in patch
            else self.llmParallelToolCalls
        )
        llm_strict_tools = (
            _coerce_optional_bool(patch["llmStrictTools"], "llmStrictTools", errors)
            if "llmStrictTools" in patch
            else self.llmStrictTools
        )
        llm_tool_choice = (
            _coerce_optional_bool(patch["llmToolChoiceRequired"], "llmToolChoiceRequired", errors)
            if "llmToolChoiceRequired" in patch
            else self.llmToolChoiceRequired
        )

        output_mode: Any = self.agentOutputMode
        if "agentOutputMode" in patch and patch["agentOutputMode"] is not None:
            raw_mode = str(patch["agentOutputMode"]).strip() if isinstance(patch["agentOutputMode"], str) else None
            if raw_mode not in _VALID_OUTPUT_MODES:
                errors.append(f"结构化交卷方式 agentOutputMode 必须是 {' / '.join(_VALID_OUTPUT_MODES)} 之一")
            else:
                output_mode = raw_mode

        native_strict = (
            _coerce_bool(patch["agentNativeStrict"], "agentNativeStrict", errors)
            if "agentNativeStrict" in patch and patch["agentNativeStrict"] is not None
            else self.agentNativeStrict
        )
        output_retries = (
            _coerce_int(patch["agentOutputRetries"], "证据校验重试次数 agentOutputRetries", errors, min_val=0, max_val=10)
            if "agentOutputRetries" in patch and patch["agentOutputRetries"] is not None
            else self.agentOutputRetries
        )
        tool_retries = (
            _coerce_int(patch["agentToolRetries"], "工具参数重试次数 agentToolRetries", errors, min_val=0, max_val=10)
            if "agentToolRetries" in patch and patch["agentToolRetries"] is not None
            else self.agentToolRetries
        )
        request_limit = (
            _coerce_int(patch["agentRequestLimit"], "单次最大轮数 agentRequestLimit", errors, min_val=1, max_val=200)
            if "agentRequestLimit" in patch and patch["agentRequestLimit"] is not None
            else self.agentRequestLimit
        )
        tool_calls_limit = (
            _coerce_int(
                patch["agentToolCallsLimit"], "单次最大工具调用数 agentToolCallsLimit", errors, min_val=1, max_val=500
            )
            if "agentToolCallsLimit" in patch and patch["agentToolCallsLimit"] is not None
            else self.agentToolCallsLimit
        )
        run_timeout_s = (
            _coerce_float(patch["agentRunTimeoutS"], "单次运行总超时 agentRunTimeoutS", errors, gt_zero=True)
            if "agentRunTimeoutS" in patch and patch["agentRunTimeoutS"] is not None
            else self.agentRunTimeoutS
        )
        max_concurrent = (
            _coerce_int(
                patch["agentMaxConcurrentRuns"],
                "最大并发运行数 agentMaxConcurrentRuns",
                errors,
                min_val=1,
                max_val=128,
            )
            if "agentMaxConcurrentRuns" in patch and patch["agentMaxConcurrentRuns"] is not None
            else self.agentMaxConcurrentRuns
        )
        preview_rows = (
            _coerce_int(patch["agentPreviewRows"], "接口预览行数 agentPreviewRows", errors, min_val=1, max_val=200)
            if "agentPreviewRows" in patch and patch["agentPreviewRows"] is not None
            else self.agentPreviewRows
        )

        gateway_mode: Any = self.gatewayMode
        if "gatewayMode" in patch and patch["gatewayMode"] is not None:
            raw_gw_mode = str(patch["gatewayMode"]).strip() if isinstance(patch["gatewayMode"], str) else None
            if raw_gw_mode not in _VALID_GATEWAY_MODES:
                errors.append(f"统一网关模式 gatewayMode 必须是 {' / '.join(_VALID_GATEWAY_MODES)} 之一")
            else:
                gateway_mode = raw_gw_mode

        gateway_url = _str_field("gatewayUrl", self.gatewayUrl, "gatewayUrl")

        xml_style: Any = self.gatewayXmlStyle
        if "gatewayXmlStyle" in patch and patch["gatewayXmlStyle"] is not None:
            raw_style = str(patch["gatewayXmlStyle"]).strip() if isinstance(patch["gatewayXmlStyle"], str) else None
            if raw_style not in _VALID_XML_STYLES:
                errors.append(f"网关 XML 风格 gatewayXmlStyle 必须是 {' / '.join(_VALID_XML_STYLES)} 之一")
            else:
                xml_style = raw_style

        connect_timeout_s = (
            _coerce_float(
                patch["gatewayConnectTimeoutS"], "网关连接超时 gatewayConnectTimeoutS", errors, gt_zero=True
            )
            if "gatewayConnectTimeoutS" in patch and patch["gatewayConnectTimeoutS"] is not None
            else self.gatewayConnectTimeoutS
        )

        llm_api_key = _resolve_secret(
            patch.get("llmApiKey"), self.llmApiKey, clear_llm_api_key, "llmApiKey", errors
        )
        gateway_app_id = _resolve_secret(
            patch.get("gatewayAppId"), self.gatewayAppId, clear_gateway_app_id, "gatewayAppId", errors
        )
        gateway_access_token = _resolve_secret(
            patch.get("gatewayAccessToken"),
            self.gatewayAccessToken,
            clear_gateway_access_token,
            "gatewayAccessToken",
            errors,
        )

        if errors:
            raise RuntimeConfigValidationError(errors)

        candidate = RuntimeConfig(
            llmBaseUrl=llm_base_url,
            llmApiKey=llm_api_key,
            llmModel=llm_model,
            llmTemperature=llm_temperature,
            llmMaxTokens=llm_max_tokens,
            llmTimeoutS=llm_timeout_s,
            llmHttpRetries=llm_http_retries,
            llmParallelToolCalls=llm_parallel,
            llmStrictTools=llm_strict_tools,
            llmToolChoiceRequired=llm_tool_choice,
            agentOutputMode=output_mode,
            agentNativeStrict=native_strict,
            agentOutputRetries=output_retries,
            agentToolRetries=tool_retries,
            agentRequestLimit=request_limit,
            agentToolCallsLimit=tool_calls_limit,
            agentRunTimeoutS=run_timeout_s,
            agentMaxConcurrentRuns=max_concurrent,
            agentPreviewRows=preview_rows,
            gatewayMode=gateway_mode,
            gatewayUrl=gateway_url,
            gatewayAppId=gateway_app_id,
            gatewayAccessToken=gateway_access_token,
            gatewayXmlStyle=xml_style,
            gatewayConnectTimeoutS=connect_timeout_s,
        )
        candidate.validate()
        return candidate


@dataclass(frozen=True)
class RuntimeSnapshot:
    """当前生效或某次修订的完整状态。"""

    rev: str
    n: int
    time: str
    operator: str
    type: str
    source: str
    summary: str
    note: str
    changed_keys: list[str]
    config: RuntimeConfig

    def to_public_state(self) -> dict[str, Any]:
        return {
            "activeRev": self.rev,
            "updatedAt": fmt_time(self.time),
            "operator": self.operator,
            "source": self.source,
            "note": self.note,
            "config": self.config.to_public_dict(),
        }


class RuntimeConfigStore:
    """磁盘持久化的版本化运行配置存储。"""

    def __init__(self, layout: DataLayout, lock: threading.RLock) -> None:
        self.layout = layout
        self.lock = lock
        self.root = layout.config / "runtime"
        self.revisions_dir = self.root / "revisions"
        self.current_path = self.root / "current.json"
        self.index_path = self.root / "index.jsonl"
        self._active: RuntimeSnapshot | None = None
        self._fallback_settings: Settings = _DEFAULT_FALLBACK_SETTINGS

    def _ensure_dirs(self) -> None:
        self.revisions_dir.mkdir(parents=True, exist_ok=True)
        _chmod_safe(self.root, 0o700)
        _chmod_safe(self.revisions_dir, 0o700)

    def _revision_path(self, rev: str) -> Path:
        if not isinstance(rev, str) or not CONFIG_REV_RE.match(rev):
            raise InvalidResource(f"运行配置版本号「{rev}」格式不合法")
        return ensure_within(self.revisions_dir, self.revisions_dir / f"{rev}.json")

    def exists(self) -> bool:
        """磁盘上是否已存在持久化的运行配置。"""
        return self.current_path.is_file()

    def _read_index_entries(self) -> list[dict[str, Any]]:
        valid: list[dict[str, Any]] = []
        for item in read_jsonl(self.index_path):
            rev = item.get("rev")
            if not isinstance(rev, str) or not CONFIG_REV_RE.match(rev):
                continue
            try:
                n = int(item.get("n") or rev[1:])
            except (TypeError, ValueError):
                continue
            valid.append({**item, "n": n})
        valid.sort(key=lambda e: e["n"])
        return valid

    def _next_number(self) -> int:
        max_n = max((int(e["n"]) for e in self._read_index_entries()), default=0)
        if self.revisions_dir.exists():
            for p in self.revisions_dir.glob("c*.json"):
                stem = p.stem
                if CONFIG_REV_RE.match(stem):
                    max_n = max(max_n, int(stem[1:]))
        if self._active is not None:
            max_n = max(max_n, self._active.n)
        return max_n + 1

    def _cleanup_tmp_files(self) -> None:
        for folder in (self.root, self.revisions_dir):
            if not folder.exists():
                continue
            for tmp in folder.glob(".*.tmp"):
                tmp.unlink(missing_ok=True)

    def _write_revision(
        self,
        *,
        cfg: RuntimeConfig,
        operator: str,
        type_label: str,
        source: str,
        summary: str,
        note: str,
        changed_keys: list[str],
    ) -> RuntimeSnapshot:
        self._ensure_dirs()
        n = self._next_number()
        rev = f"c{n}"
        ts = now_iso()
        snap_doc = {
            "rev": rev,
            "n": n,
            "time": ts,
            "operator": operator,
            "type": type_label,
            "source": source,
            "summary": summary,
            "note": note,
            "changedKeys": list(changed_keys),
            "config": cfg.to_storage_dict(),
        }
        _atomic_write_json_600(self._revision_path(rev), snap_doc)
        index_entry = {
            "rev": rev,
            "n": n,
            "time": ts,
            "operator": operator,
            "type": type_label,
            "source": source,
            "summary": summary,
            "note": note,
            "changedKeys": list(changed_keys),
        }
        _append_jsonl_600(self.index_path, index_entry)
        current_doc = {
            "activeRev": rev,
            "n": n,
            "time": ts,
            "operator": operator,
            "type": type_label,
            "source": source,
            "summary": summary,
            "note": note,
            "changedKeys": list(changed_keys),
            "config": cfg.to_storage_dict(),
        }
        _atomic_write_json_600(self.current_path, current_doc)
        snap = RuntimeSnapshot(
            rev=rev,
            n=n,
            time=ts,
            operator=operator,
            type=type_label,
            source=source,
            summary=summary,
            note=note,
            changed_keys=list(changed_keys),
            config=cfg,
        )
        self._active = snap
        return snap

    def _audit(self, action: str, operator: str, detail: dict[str, Any]) -> None:
        append_line(
            self.layout.audit,
            json.dumps({"time": now_iso(), "action": action, "operator": operator, **detail}, ensure_ascii=False),
        )

    def bootstrap_or_load(self, settings: Settings) -> RuntimeSnapshot:
        """启动时调用：若无持久化文件则从环境变量初始化释放 c1；若已存在则加载磁盘生效配置。"""
        with self.lock:
            self._fallback_settings = settings
            self._ensure_dirs()
            self._cleanup_tmp_files()
            cur = read_json(self.current_path)
            if isinstance(cur, dict) and isinstance(cur.get("config"), dict):
                rev = str(cur.get("activeRev") or "c1")
                if not CONFIG_REV_RE.match(rev):
                    rev = "c1"
                n = int(cur.get("n") or rev[1:])
                cfg = RuntimeConfig.from_storage_dict(cur["config"], fallback_settings=settings)
                ts = str(cur.get("time") or now_iso())
                op = str(cur.get("operator") or "system")
                type_label = str(cur.get("type") or "初始化")
                source = str(cur.get("source") or type_label)
                summary = str(cur.get("summary") or "")
                note = str(cur.get("note") or "")
                changed_keys = [str(k) for k in (cur.get("changedKeys") or []) if isinstance(k, str)]
                # 确保对应的不可变版本快照也存在（兼容崩溃恢复）
                rev_path = self._revision_path(rev)
                if not rev_path.exists():
                    _atomic_write_json_600(
                        rev_path,
                        {
                            "rev": rev,
                            "n": n,
                            "time": ts,
                            "operator": op,
                            "type": type_label,
                            "source": source,
                            "summary": summary,
                            "note": note,
                            "changedKeys": changed_keys,
                            "config": cfg.to_storage_dict(),
                        },
                    )
                _chmod_safe(self.current_path, 0o600)
                if self.index_path.exists():
                    _chmod_safe(self.index_path, 0o600)
                snap = RuntimeSnapshot(
                    rev=rev,
                    n=n,
                    time=ts,
                    operator=op,
                    type=type_label,
                    source=source,
                    summary=summary,
                    note=note,
                    changed_keys=changed_keys,
                    config=cfg,
                )
                self._active = snap
                return snap

            # 若 current.json 缺失但历史索引存在（极端崩溃场景），优先从最近一个有效快照恢复
            entries = self._read_index_entries()
            for entry in reversed(entries):
                rev_doc = read_json(self._revision_path(entry["rev"]))
                if isinstance(rev_doc, dict) and isinstance(rev_doc.get("config"), dict):
                    cfg = RuntimeConfig.from_storage_dict(rev_doc["config"], fallback_settings=settings)
                    rev = entry["rev"]
                    n = int(entry["n"])
                    ts = str(rev_doc.get("time") or entry.get("time") or now_iso())
                    op = str(rev_doc.get("operator") or entry.get("operator") or "system")
                    type_label = str(rev_doc.get("type") or entry.get("type") or "恢复")
                    source = str(rev_doc.get("source") or entry.get("source") or type_label)
                    summary = str(rev_doc.get("summary") or entry.get("summary") or "")
                    note = str(rev_doc.get("note") or entry.get("note") or "")
                    changed_keys = [str(k) for k in (entry.get("changedKeys") or []) if isinstance(k, str)]
                    _atomic_write_json_600(
                        self.current_path,
                        {
                            "activeRev": rev,
                            "n": n,
                            "time": ts,
                            "operator": op,
                            "type": type_label,
                            "source": source,
                            "summary": summary,
                            "note": note,
                            "changedKeys": changed_keys,
                            "config": cfg.to_storage_dict(),
                        },
                    )
                    snap = RuntimeSnapshot(
                        rev=rev,
                        n=n,
                        time=ts,
                        operator=op,
                        type=type_label,
                        source=source,
                        summary=summary,
                        note=note,
                        changed_keys=changed_keys,
                        config=cfg,
                    )
                    self._active = snap
                    log.warning("current.json 缺失或损坏，已从最近快照 %s 自动恢复", rev)
                    return snap

            # 首次启动：将环境变量配置释放到磁盘生成 c1
            cfg = RuntimeConfig.from_settings(settings)
            snap = self._write_revision(
                cfg=cfg,
                operator="system",
                type_label="初始化",
                source="环境变量初始化",
                summary="启动初始化（从环境变量释放）",
                note="",
                changed_keys=[],
            )
            log.info("已将启动运行配置从环境变量初始化落盘：%s (%s)", snap.rev, self.current_path)
            return snap

    def active(self) -> RuntimeSnapshot:
        with self.lock:
            if self._active is None:
                return self.bootstrap_or_load(self._fallback_settings)
            return self._active

    def active_rev(self) -> str:
        return self.active().rev

    def to_effective_settings(self, base_settings: Settings) -> Settings:
        return self.active().config.to_effective_settings(base_settings)

    def public_state(self) -> dict[str, Any]:
        return self.active().to_public_state()

    def revisions(self) -> list[dict[str, Any]]:
        """按版本号倒序返回全部配置历史（脱敏展示）。"""
        with self.lock:
            active = self.active()
            entries = self._read_index_entries()
            out: list[dict[str, Any]] = []
            for e in reversed(entries):
                rev = e["rev"]
                rev_doc = read_json(self._revision_path(rev))
                if isinstance(rev_doc, dict) and isinstance(rev_doc.get("config"), dict):
                    snap_cfg = RuntimeConfig.from_storage_dict(rev_doc["config"], fallback_settings=self._fallback_settings)
                    masked_cfg = snap_cfg.to_public_dict()
                elif rev == active.rev:
                    masked_cfg = active.config.to_public_dict()
                else:
                    masked_cfg = {}
                out.append(
                    {
                        "rev": rev,
                        "time": fmt_time(e.get("time")),
                        "operator": e.get("operator") or "system",
                        "type": e.get("type") or "修改",
                        "summary": e.get("summary") or "",
                        "note": e.get("note") or "",
                        "online": rev == active.rev,
                        "changedKeys": list(e.get("changedKeys") or []),
                        "config": masked_cfg,
                    }
                )
            return out

    def update(
        self,
        patch: dict[str, Any],
        operator: str,
        *,
        clear_llm_api_key: bool = False,
        clear_gateway_app_id: bool = False,
        clear_gateway_access_token: bool = False,
        note: str = "",
    ) -> tuple[RuntimeSnapshot, bool]:
        """校验并持久化新运行配置版本；若无任何键值变化则返回 (当前快照, False)。"""
        with self.lock:
            current = self.active()
            new_cfg = current.config.apply_patch(
                patch,
                clear_llm_api_key=clear_llm_api_key,
                clear_gateway_app_id=clear_gateway_app_id,
                clear_gateway_access_token=clear_gateway_access_token,
            )
            changed_keys = current.config.diff_keys(new_cfg)
            if not changed_keys:
                return current, False
            clean_note = (note or "").strip()
            preview_keys = ", ".join(changed_keys[:4])
            suffix = f" 等 {len(changed_keys)} 项" if len(changed_keys) > 4 else ""
            summary = f"更新运行配置（{preview_keys}{suffix}）"
            snap = self._write_revision(
                cfg=new_cfg,
                operator=operator,
                type_label="修改",
                source="管理端热更新",
                summary=summary,
                note=clean_note,
                changed_keys=changed_keys,
            )
            self._audit(
                "runtime-config-update",
                operator,
                {"rev": snap.rev, "base": current.rev, "changedKeys": changed_keys, "note": clean_note},
            )
            return snap, True

    def rollback(self, target_rev: str, reason: str, operator: str) -> RuntimeSnapshot:
        """从历史快照 target_rev 生成一个新版本 c{N+1} 并切换生效。"""
        clean_target = (target_rev or "").strip()
        if not CONFIG_REV_RE.match(clean_target):
            raise InvalidResource(f"运行配置版本号「{target_rev}」格式不合法")
        with self.lock:
            rev_path = self._revision_path(clean_target)
            rev_doc = read_json(rev_path)
            if not isinstance(rev_doc, dict) or not isinstance(rev_doc.get("config"), dict):
                raise ResourceNotFound(f"运行配置版本 {clean_target} 不存在")
            target_cfg = RuntimeConfig.from_storage_dict(rev_doc["config"], fallback_settings=self._fallback_settings)
            target_cfg.validate()
            current = self.active()
            changed_keys = current.config.diff_keys(target_cfg)
            clean_reason = (reason or "").strip()
            summary = f"回退运行配置至 {clean_target}" + (f"（{clean_reason}）" if clean_reason else "")
            snap = self._write_revision(
                cfg=target_cfg,
                operator=operator,
                type_label="回退",
                source=f"回退自 {clean_target}",
                summary=summary,
                note=clean_reason,
                changed_keys=changed_keys,
            )
            self._audit(
                "runtime-config-rollback",
                operator,
                {"rev": snap.rev, "base": current.rev, "targetRev": clean_target, "reason": clean_reason,
                 "changedKeys": changed_keys},
            )
            return snap

    def sync_from_env(self, env_settings: Settings, operator: str, note: str = "") -> tuple[RuntimeSnapshot, bool]:
        """重新读取启动环境变量配置；若有差异则生成新修订版本并生效，否则直接返回当前状态。"""
        with self.lock:
            env_cfg = RuntimeConfig.from_settings(env_settings)
            env_cfg.validate()
            current = self.active()
            changed_keys = current.config.diff_keys(env_cfg)
            if not changed_keys:
                return current, False
            clean_note = (note or "").strip()
            preview_keys = ", ".join(changed_keys[:4])
            suffix = f" 等 {len(changed_keys)} 项" if len(changed_keys) > 4 else ""
            summary = f"从环境变量同步（{preview_keys}{suffix}）"
            snap = self._write_revision(
                cfg=env_cfg,
                operator=operator,
                type_label="环境同步",
                source="环境变量同步",
                summary=summary,
                note=clean_note,
                changed_keys=changed_keys,
            )
            self._audit(
                "runtime-config-sync-env",
                operator,
                {"rev": snap.rev, "base": current.rev, "changedKeys": changed_keys, "note": clean_note},
            )
            return snap, True
