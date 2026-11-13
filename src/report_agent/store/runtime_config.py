"""磁盘持久化的运行期热更新配置仓库（统一网关 + 大模型 / 智能体参数 + 版本历史与回退）。

#Created By AiCoding(codex)
目录结构（位于 data/config/runtime/，所有文件权限严格限制为 0600）：
├── current.json        当前生效配置与元数据（activeRev、operator、source、time、note、config）
├── index.jsonl         修订日志（c1, c2, ...，不含明文密钥）
└── revisions/
    └── cN.json         每个版本的完整不可变快照（含密钥，用于精确回退，权限 0600）
"""

from __future__ import annotations

import logging
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import SecretStr

from ..config import Settings
from .fsutil import _chmod_safe, append_audit, append_jsonl, fmt_time, now_iso, read_json, read_jsonl, write_json
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
    "reportApiKeys",
    "gatewayMaxConcurrency",
    "releasesKeep",
    "runsKeepDays",
    "agentQueryDefaultLimit",
    "agentQueryMaxLimit",
    "agentMaxPeriodMonths",
    "chatMaxDocChars",
    "chatMaxHistoryMessages",
    "chatMaxRunCards",
    "chatMaxMarkdownPreviewChars",
    "chatCompactTriggerMessages",
    "chatCompactKeepRecent",
    "chatManualCompactKeepRecent",
    "chatManualCompactMinSlice",
    "chatMaxMemorySummaryChars",
    "chatMaxSummaryMsgChars",
    "chatRequestLimit",
    "chatToolCallsLimit",
    "chatTimeoutS",
    "chatSummaryRequestLimit",
    "chatSummaryToolCallsLimit",
    "chatSummaryTimeoutS",
)

_NULLABLE_FIELDS: frozenset[str] = frozenset({
    "llmMaxTokens",
    "llmParallelToolCalls",
    "llmStrictTools",
    "llmToolChoiceRequired",
})

_STRING_FIELDS: frozenset[str] = frozenset({
    "llmBaseUrl",
    "llmApiKey",
    "llmModel",
    "gatewayUrl",
    "gatewayAppId",
    "gatewayAccessToken",
    "reportApiKeys",
})


def _read_int(s: Any, attr: str, default: int) -> int:
    val = getattr(s, attr, None)
    return default if val is None else int(val)


def _read_float(s: Any, attr: str, default: float) -> float:
    val = getattr(s, attr, None)
    return default if val is None else float(val)


def _read_bool(s: Any, attr: str, default: bool) -> bool:
    val = getattr(s, attr, None)
    return default if val is None else bool(val)


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


def split_api_keys(raw: str | None) -> list[str]:
    """按逗号切分调用 API Key 字符串，返回去首尾空白且保序去重的非空列表。"""
    if not raw or not isinstance(raw, str):
        return []
    return list(dict.fromkeys(k.strip() for k in raw.split(",") if k.strip()))


def mask_api_keys(raw: str | None) -> str:
    """按逗号切分非空 API Key，逐项脱敏后以 ', ' 连接；为空返回 ''。"""
    keys = split_api_keys(raw)
    if not keys:
        return ""
    return ", ".join(mask_secret(k) for k in keys)


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


def _resolve_api_keys(raw: Any, current_keys: str, clear_flag: bool, errors: list[str]) -> str:
    if clear_flag:
        return ""
    if raw is None:
        return current_keys
    if not isinstance(raw, str):
        errors.append("调用凭证 reportApiKeys 必须是字符串")
        return current_keys
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", raw):
        errors.append("调用凭证 reportApiKeys 包含非法控制字符")
        return current_keys
    cleaned = raw.strip()
    masked_current = mask_api_keys(current_keys)
    if not cleaned or cleaned == "***" or cleaned == masked_current:
        return current_keys
    keys = split_api_keys(cleaned)
    if not keys or ", ".join(keys) == masked_current:
        return current_keys
    for k in keys:
        if _WHITESPACE_OR_CTRL_RE.search(k):
            errors.append("调用凭证 reportApiKeys 单把密钥不能包含空白或控制字符")
            return current_keys
    return ",".join(keys)


@dataclass(frozen=True)
class RuntimeConfig:
    """受版本化热更新管理的全部运行参数。"""

    # LLM
    llmBaseUrl: str = "https://api.openai.com/v1"
    llmApiKey: str = ""
    llmModel: str = "deepseek-v4-flash"
    llmTemperature: float = 0.0
    llmMaxTokens: int | None = None
    llmTimeoutS: float = 120.0
    llmHttpRetries: int = 2
    llmParallelToolCalls: bool | None = True
    llmStrictTools: bool | None = None
    llmToolChoiceRequired: bool | None = None
    # Agent & Tools
    agentOutputMode: OutputMode = "tool"
    agentNativeStrict: bool = True
    agentOutputRetries: int = 3
    agentToolRetries: int = 2
    agentRequestLimit: int = 25
    agentToolCallsLimit: int = 120
    agentRunTimeoutS: float = 600.0
    agentMaxConcurrentRuns: int = 8
    agentPreviewRows: int = 10
    # Gateway
    gatewayMode: GatewayMode = "mock"
    gatewayUrl: str = ""
    gatewayAppId: str = ""
    gatewayAccessToken: str = ""
    gatewayXmlStyle: XmlStyle = "java"
    gatewayConnectTimeoutS: float = 5.0
    # Upstream & Embed Auth
    reportApiKeys: str = ""
    # Gateway concurrency & Retention
    gatewayMaxConcurrency: int = 32
    releasesKeep: int = 50
    runsKeepDays: int = 90
    # Platform Tools Limits
    agentQueryDefaultLimit: int = 20
    agentQueryMaxLimit: int = 100
    agentMaxPeriodMonths: int = 36
    # Chat & Compaction
    chatMaxDocChars: int = 12000
    chatMaxHistoryMessages: int = 20
    chatMaxRunCards: int = 8
    chatMaxMarkdownPreviewChars: int = 1500
    chatCompactTriggerMessages: int = 24
    chatCompactKeepRecent: int = 12
    chatManualCompactKeepRecent: int = 6
    chatManualCompactMinSlice: int = 2
    chatMaxMemorySummaryChars: int = 1200
    chatMaxSummaryMsgChars: int = 800
    chatRequestLimit: int = 8
    chatToolCallsLimit: int = 16
    chatTimeoutS: float = 120.0
    chatSummaryRequestLimit: int = 3
    chatSummaryToolCallsLimit: int = 4
    chatSummaryTimeoutS: float = 60.0

    @classmethod
    def from_settings(cls, s: Settings) -> RuntimeConfig:
        """从 Settings（环境变量 / .env）提取初始运行配置。"""
        llm_api_key_obj = getattr(s, "llm_api_key", None)
        gw_app_id_obj = getattr(s, "gateway_app_id", None)
        gw_token_obj = getattr(s, "gateway_access_token", None)
        raw_out_mode = getattr(s, "agent_output_mode", None)
        raw_gw_mode = getattr(s, "gateway_mode", None)
        raw_xml_style = getattr(s, "gateway_xml_style", None)
        raw_max_tokens = getattr(s, "llm_max_tokens", None)
        return cls(
            llmBaseUrl=str(getattr(s, "llm_base_url", None) or "").strip(),
            llmApiKey=llm_api_key_obj.get_secret_value() if llm_api_key_obj else "",
            llmModel=str(getattr(s, "llm_model", None) or "").strip(),
            llmTemperature=_read_float(s, "llm_temperature", 0.0),
            llmMaxTokens=int(raw_max_tokens) if raw_max_tokens is not None else None,
            llmTimeoutS=_read_float(s, "llm_timeout_s", 120.0),
            llmHttpRetries=_read_int(s, "llm_http_retries", 2),
            llmParallelToolCalls=getattr(s, "llm_parallel_tool_calls", True),
            llmStrictTools=getattr(s, "llm_strict_tools", None),
            llmToolChoiceRequired=getattr(s, "llm_tool_choice_required", None),
            agentOutputMode=raw_out_mode if raw_out_mode in _VALID_OUTPUT_MODES else "tool",
            agentNativeStrict=_read_bool(s, "agent_native_strict", True),
            agentOutputRetries=_read_int(s, "agent_output_retries", 3),
            agentToolRetries=_read_int(s, "agent_tool_retries", 2),
            agentRequestLimit=_read_int(s, "agent_request_limit", 25),
            agentToolCallsLimit=_read_int(s, "agent_tool_calls_limit", 120),
            agentRunTimeoutS=_read_float(s, "agent_run_timeout_s", 600.0),
            agentMaxConcurrentRuns=_read_int(s, "agent_max_concurrent_runs", 8),
            agentPreviewRows=_read_int(s, "agent_preview_rows", 10),
            gatewayMode=raw_gw_mode if raw_gw_mode in _VALID_GATEWAY_MODES else "mock",
            gatewayUrl=str(getattr(s, "gateway_url", None) or "").strip(),
            gatewayAppId=gw_app_id_obj.get_secret_value() if gw_app_id_obj else "",
            gatewayAccessToken=gw_token_obj.get_secret_value() if gw_token_obj else "",
            gatewayXmlStyle=raw_xml_style if raw_xml_style in _VALID_XML_STYLES else "java",
            gatewayConnectTimeoutS=_read_float(s, "gateway_connect_timeout_s", 5.0),
            reportApiKeys=",".join(split_api_keys(getattr(s, "report_api_keys", "") or "")),
            gatewayMaxConcurrency=_read_int(s, "gateway_max_concurrency", 32),
            releasesKeep=_read_int(s, "releases_keep", 50),
            runsKeepDays=_read_int(s, "runs_keep_days", 90),
            agentQueryDefaultLimit=_read_int(s, "agent_query_default_limit", 20),
            agentQueryMaxLimit=_read_int(s, "agent_query_max_limit", 100),
            agentMaxPeriodMonths=_read_int(s, "agent_max_period_months", 36),
            chatMaxDocChars=_read_int(s, "chat_max_doc_chars", 12000),
            chatMaxHistoryMessages=_read_int(s, "chat_max_history_messages", 20),
            chatMaxRunCards=_read_int(s, "chat_max_run_cards", 8),
            chatMaxMarkdownPreviewChars=_read_int(s, "chat_max_markdown_preview_chars", 1500),
            chatCompactTriggerMessages=_read_int(s, "chat_compact_trigger_messages", 24),
            chatCompactKeepRecent=_read_int(s, "chat_compact_keep_recent", 12),
            chatManualCompactKeepRecent=_read_int(s, "chat_manual_compact_keep_recent", 6),
            chatManualCompactMinSlice=_read_int(s, "chat_manual_compact_min_slice", 2),
            chatMaxMemorySummaryChars=_read_int(s, "chat_max_memory_summary_chars", 1200),
            chatMaxSummaryMsgChars=_read_int(s, "chat_max_summary_msg_chars", 800),
            chatRequestLimit=_read_int(s, "chat_request_limit", 8),
            chatToolCallsLimit=_read_int(s, "chat_tool_calls_limit", 16),
            chatTimeoutS=_read_float(s, "chat_timeout_s", 120.0),
            chatSummaryRequestLimit=_read_int(s, "chat_summary_request_limit", 3),
            chatSummaryToolCallsLimit=_read_int(s, "chat_summary_tool_calls_limit", 4),
            chatSummaryTimeoutS=_read_float(s, "chat_summary_timeout_s", 60.0),
        )

    @classmethod
    def from_storage_dict(cls, data: dict[str, Any], fallback_settings: Settings | None = None) -> RuntimeConfig:
        """从磁盘字典恢复，缺失或非可空字段为空时自动回退到 fallback_settings。"""
        base = cls.from_settings(fallback_settings or _DEFAULT_FALLBACK_SETTINGS)
        merged = base.to_storage_dict()
        if isinstance(data, dict):
            for k in _ORDERED_FIELDS:
                if k not in data:
                    continue
                val = data[k]
                if k not in _NULLABLE_FIELDS and val is None:
                    continue
                if k not in _NULLABLE_FIELDS and k not in _STRING_FIELDS and isinstance(val, str) and val.strip() == "":
                    continue
                merged[k] = val
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
            reportApiKeys=",".join(split_api_keys(str(merged["reportApiKeys"] or ""))),
            gatewayMaxConcurrency=int(merged["gatewayMaxConcurrency"]),
            releasesKeep=int(merged["releasesKeep"]),
            runsKeepDays=int(merged["runsKeepDays"]),
            agentQueryDefaultLimit=int(merged["agentQueryDefaultLimit"]),
            agentQueryMaxLimit=int(merged["agentQueryMaxLimit"]),
            agentMaxPeriodMonths=int(merged["agentMaxPeriodMonths"]),
            chatMaxDocChars=int(merged["chatMaxDocChars"]),
            chatMaxHistoryMessages=int(merged["chatMaxHistoryMessages"]),
            chatMaxRunCards=int(merged["chatMaxRunCards"]),
            chatMaxMarkdownPreviewChars=int(merged["chatMaxMarkdownPreviewChars"]),
            chatCompactTriggerMessages=int(merged["chatCompactTriggerMessages"]),
            chatCompactKeepRecent=int(merged["chatCompactKeepRecent"]),
            chatManualCompactKeepRecent=int(merged["chatManualCompactKeepRecent"]),
            chatManualCompactMinSlice=int(merged["chatManualCompactMinSlice"]),
            chatMaxMemorySummaryChars=int(merged["chatMaxMemorySummaryChars"]),
            chatMaxSummaryMsgChars=int(merged["chatMaxSummaryMsgChars"]),
            chatRequestLimit=int(merged["chatRequestLimit"]),
            chatToolCallsLimit=int(merged["chatToolCallsLimit"]),
            chatTimeoutS=float(merged["chatTimeoutS"]),
            chatSummaryRequestLimit=int(merged["chatSummaryRequestLimit"]),
            chatSummaryToolCallsLimit=int(merged["chatSummaryToolCallsLimit"]),
            chatSummaryTimeoutS=float(merged["chatSummaryTimeoutS"]),
        )

    def to_storage_dict(self) -> dict[str, Any]:
        """转换为落盘快照字典（含密钥，仅用于 0600 磁盘存储）。"""
        return {k: getattr(self, k) for k in _ORDERED_FIELDS}

    def to_public_dict(self) -> dict[str, Any]:
        """转换为管理端公开字典（绝不暴露任何明文密钥）。"""
        keys = split_api_keys(self.reportApiKeys)
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
            "hasReportApiKeys": bool(keys),
            "reportApiKeysMasked": mask_api_keys(self.reportApiKeys),
            "reportApiKeyCount": len(keys),
            "gatewayMaxConcurrency": self.gatewayMaxConcurrency,
            "releasesKeep": self.releasesKeep,
            "runsKeepDays": self.runsKeepDays,
            "agentQueryDefaultLimit": self.agentQueryDefaultLimit,
            "agentQueryMaxLimit": self.agentQueryMaxLimit,
            "agentMaxPeriodMonths": self.agentMaxPeriodMonths,
            "chatMaxDocChars": self.chatMaxDocChars,
            "chatMaxHistoryMessages": self.chatMaxHistoryMessages,
            "chatMaxRunCards": self.chatMaxRunCards,
            "chatMaxMarkdownPreviewChars": self.chatMaxMarkdownPreviewChars,
            "chatCompactTriggerMessages": self.chatCompactTriggerMessages,
            "chatCompactKeepRecent": self.chatCompactKeepRecent,
            "chatManualCompactKeepRecent": self.chatManualCompactKeepRecent,
            "chatManualCompactMinSlice": self.chatManualCompactMinSlice,
            "chatMaxMemorySummaryChars": self.chatMaxMemorySummaryChars,
            "chatMaxSummaryMsgChars": self.chatMaxSummaryMsgChars,
            "chatRequestLimit": self.chatRequestLimit,
            "chatToolCallsLimit": self.chatToolCallsLimit,
            "chatTimeoutS": self.chatTimeoutS,
            "chatSummaryRequestLimit": self.chatSummaryRequestLimit,
            "chatSummaryToolCallsLimit": self.chatSummaryToolCallsLimit,
            "chatSummaryTimeoutS": self.chatSummaryTimeoutS,
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
                "report_api_keys": self.reportApiKeys,
                "gateway_max_concurrency": self.gatewayMaxConcurrency,
                "releases_keep": self.releasesKeep,
                "runs_keep_days": self.runsKeepDays,
                "agent_query_default_limit": self.agentQueryDefaultLimit,
                "agent_query_max_limit": self.agentQueryMaxLimit,
                "agent_max_period_months": self.agentMaxPeriodMonths,
                "chat_max_doc_chars": self.chatMaxDocChars,
                "chat_max_history_messages": self.chatMaxHistoryMessages,
                "chat_max_run_cards": self.chatMaxRunCards,
                "chat_max_markdown_preview_chars": self.chatMaxMarkdownPreviewChars,
                "chat_compact_trigger_messages": self.chatCompactTriggerMessages,
                "chat_compact_keep_recent": self.chatCompactKeepRecent,
                "chat_manual_compact_keep_recent": self.chatManualCompactKeepRecent,
                "chat_manual_compact_min_slice": self.chatManualCompactMinSlice,
                "chat_max_memory_summary_chars": self.chatMaxMemorySummaryChars,
                "chat_max_summary_msg_chars": self.chatMaxSummaryMsgChars,
                "chat_request_limit": self.chatRequestLimit,
                "chat_tool_calls_limit": self.chatToolCallsLimit,
                "chat_timeout_s": self.chatTimeoutS,
                "chat_summary_request_limit": self.chatSummaryRequestLimit,
                "chat_summary_tool_calls_limit": self.chatSummaryToolCallsLimit,
                "chat_summary_timeout_s": self.chatSummaryTimeoutS,
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

        if not (1 <= self.agentQueryDefaultLimit <= 500):
            errors.append("结果筛选默认行数 agentQueryDefaultLimit 必须在 1~500 之间")
        if not (1 <= self.agentQueryMaxLimit <= 1000):
            errors.append("结果筛选最大行数 agentQueryMaxLimit 必须在 1~1000 之间")
        if self.agentQueryDefaultLimit > self.agentQueryMaxLimit:
            errors.append("结果筛选默认行数 agentQueryDefaultLimit 不能大于最大行数 agentQueryMaxLimit")
        if not (1 <= self.agentMaxPeriodMonths <= 120):
            errors.append("多账期展开跨度上限 agentMaxPeriodMonths 必须在 1~120 之间")

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
        if not (1 <= self.gatewayMaxConcurrency <= 512):
            errors.append("网关最大并发数 gatewayMaxConcurrency 必须在 1~512 之间")

        if not (1 <= self.releasesKeep <= 500):
            errors.append("发布快照保留数 releasesKeep 必须在 1~500 之间")
        if not (0 <= self.runsKeepDays <= 3650):
            errors.append("运行与会话留存天数 runsKeepDays 必须在 0~3650 之间")

        if not (500 <= self.chatMaxDocChars <= 200000):
            errors.append("聊天单据最大字符数 chatMaxDocChars 必须在 500~200000 之间")
        if not (1 <= self.chatMaxHistoryMessages <= 200):
            errors.append("聊天最近原文消息数 chatMaxHistoryMessages 必须在 1~200 之间")
        if not (1 <= self.chatMaxRunCards <= 50):
            errors.append("聊天运行卡片注入上限 chatMaxRunCards 必须在 1~50 之间")
        if not (100 <= self.chatMaxMarkdownPreviewChars <= 20000):
            errors.append("聊天报告预览截断字数 chatMaxMarkdownPreviewChars 必须在 100~20000 之间")
        if not (2 <= self.chatCompactTriggerMessages <= 500):
            errors.append("自动压缩触发消息数 chatCompactTriggerMessages 必须在 2~500 之间")
        if not (1 <= self.chatCompactKeepRecent <= 200):
            errors.append("自动压缩保留消息数 chatCompactKeepRecent 必须在 1~200 之间")
        if self.chatCompactTriggerMessages <= self.chatCompactKeepRecent:
            errors.append("自动压缩触发消息数 chatCompactTriggerMessages 必须大于保留消息数 chatCompactKeepRecent")
        if not (1 <= self.chatManualCompactKeepRecent <= 200):
            errors.append("手动压缩保留消息数 chatManualCompactKeepRecent 必须在 1~200 之间")
        if not (1 <= self.chatManualCompactMinSlice <= 100):
            errors.append("手动压缩最小归档条数 chatManualCompactMinSlice 必须在 1~100 之间")
        if not (200 <= self.chatMaxMemorySummaryChars <= 10000):
            errors.append("滚动记忆摘要上限 chatMaxMemorySummaryChars 必须在 200~10000 之间")
        if not (100 <= self.chatMaxSummaryMsgChars <= 10000):
            errors.append("待压缩消息单条截取上限 chatMaxSummaryMsgChars 必须在 100~10000 之间")
        if not (1 <= self.chatRequestLimit <= 50):
            errors.append("聊天单轮最大请求轮数 chatRequestLimit 必须在 1~50 之间")
        if not (1 <= self.chatToolCallsLimit <= 100):
            errors.append("聊天单轮最大工具调用数 chatToolCallsLimit 必须在 1~100 之间")
        if math.isnan(self.chatTimeoutS) or math.isinf(self.chatTimeoutS) or self.chatTimeoutS <= 0:
            errors.append("聊天单轮超时 chatTimeoutS 必须大于 0")
        if not (1 <= self.chatSummaryRequestLimit <= 20):
            errors.append("压缩摘要最大请求轮数 chatSummaryRequestLimit 必须在 1~20 之间")
        if not (1 <= self.chatSummaryToolCallsLimit <= 30):
            errors.append("压缩摘要最大工具调用数 chatSummaryToolCallsLimit 必须在 1~30 之间")
        if math.isnan(self.chatSummaryTimeoutS) or math.isinf(self.chatSummaryTimeoutS) or self.chatSummaryTimeoutS <= 0:
            errors.append("压缩摘要超时 chatSummaryTimeoutS 必须大于 0")

        for k in split_api_keys(self.reportApiKeys):
            if _WHITESPACE_OR_CTRL_RE.search(k):
                errors.append("调用凭证 reportApiKeys 单把密钥不能包含空白或控制字符")
                break

        if errors:
            raise RuntimeConfigValidationError(errors)

    def apply_patch(
        self,
        patch: dict[str, Any],
        *,
        clear_llm_api_key: bool = False,
        clear_gateway_app_id: bool = False,
        clear_gateway_access_token: bool = False,
        clear_report_api_keys: bool = False,
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

        def _num_int(key: str, label: str, *, min_val: int, max_val: int) -> int:
            raw = patch.get(key)
            if key not in patch or raw is None or (isinstance(raw, str) and raw.strip() == ""):
                return int(getattr(self, key))
            return _coerce_int(raw, label, errors, min_val=min_val, max_val=max_val)

        def _num_float(
            key: str,
            label: str,
            *,
            min_val: float | None = None,
            max_val: float | None = None,
            gt_zero: bool = False,
        ) -> float:
            raw = patch.get(key)
            if key not in patch or raw is None or (isinstance(raw, str) and raw.strip() == ""):
                return float(getattr(self, key))
            return _coerce_float(raw, label, errors, min_val=min_val, max_val=max_val, gt_zero=gt_zero)

        llm_base_url = _str_field("llmBaseUrl", self.llmBaseUrl, "llmBaseUrl")
        llm_model = _str_field("llmModel", self.llmModel, "llmModel")
        llm_temperature = _num_float("llmTemperature", "采样温度 llmTemperature", min_val=0.0, max_val=2.0)
        llm_max_tokens = (
            _coerce_optional_int(patch["llmMaxTokens"], "最大输出 Token 数 llmMaxTokens", errors, min_val=1)
            if "llmMaxTokens" in patch
            else self.llmMaxTokens
        )
        llm_timeout_s = _num_float("llmTimeoutS", "模型请求超时 llmTimeoutS", gt_zero=True)
        llm_http_retries = _num_int("llmHttpRetries", "模型 HTTP 重试次数 llmHttpRetries", min_val=0, max_val=10)
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
        output_retries = _num_int("agentOutputRetries", "证据校验重试次数 agentOutputRetries", min_val=0, max_val=10)
        tool_retries = _num_int("agentToolRetries", "工具参数重试次数 agentToolRetries", min_val=0, max_val=10)
        request_limit = _num_int("agentRequestLimit", "单次最大轮数 agentRequestLimit", min_val=1, max_val=200)
        tool_calls_limit = _num_int("agentToolCallsLimit", "单次最大工具调用数 agentToolCallsLimit", min_val=1, max_val=500)
        run_timeout_s = _num_float("agentRunTimeoutS", "单次运行总超时 agentRunTimeoutS", gt_zero=True)
        max_concurrent = _num_int("agentMaxConcurrentRuns", "最大并发运行数 agentMaxConcurrentRuns", min_val=1, max_val=128)
        preview_rows = _num_int("agentPreviewRows", "接口预览行数 agentPreviewRows", min_val=1, max_val=200)
        query_default_limit = _num_int("agentQueryDefaultLimit", "结果筛选默认行数 agentQueryDefaultLimit", min_val=1, max_val=500)
        query_max_limit = _num_int("agentQueryMaxLimit", "结果筛选最大行数 agentQueryMaxLimit", min_val=1, max_val=1000)
        max_period_months = _num_int("agentMaxPeriodMonths", "多账期展开跨度上限 agentMaxPeriodMonths", min_val=1, max_val=120)

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

        connect_timeout_s = _num_float("gatewayConnectTimeoutS", "网关连接超时 gatewayConnectTimeoutS", gt_zero=True)
        gateway_max_concurrency = _num_int("gatewayMaxConcurrency", "网关最大并发数 gatewayMaxConcurrency", min_val=1, max_val=512)
        releases_keep = _num_int("releasesKeep", "发布快照保留数 releasesKeep", min_val=1, max_val=500)
        runs_keep_days = _num_int("runsKeepDays", "运行与会话留存天数 runsKeepDays", min_val=0, max_val=3650)

        chat_max_doc_chars = _num_int("chatMaxDocChars", "聊天单据最大字符数 chatMaxDocChars", min_val=500, max_val=200000)
        chat_max_history = _num_int("chatMaxHistoryMessages", "聊天最近原文消息数 chatMaxHistoryMessages", min_val=1, max_val=200)
        chat_max_run_cards = _num_int("chatMaxRunCards", "聊天运行卡片注入上限 chatMaxRunCards", min_val=1, max_val=50)
        chat_max_md_preview = _num_int("chatMaxMarkdownPreviewChars", "聊天报告预览截断字数 chatMaxMarkdownPreviewChars", min_val=100, max_val=20000)
        chat_compact_trigger = _num_int("chatCompactTriggerMessages", "自动压缩触发消息数 chatCompactTriggerMessages", min_val=2, max_val=500)
        chat_compact_keep = _num_int("chatCompactKeepRecent", "自动压缩保留消息数 chatCompactKeepRecent", min_val=1, max_val=200)
        chat_manual_keep = _num_int("chatManualCompactKeepRecent", "手动压缩保留消息数 chatManualCompactKeepRecent", min_val=1, max_val=200)
        chat_manual_min_slice = _num_int("chatManualCompactMinSlice", "手动压缩最小归档条数 chatManualCompactMinSlice", min_val=1, max_val=100)
        chat_max_summary_chars = _num_int("chatMaxMemorySummaryChars", "滚动记忆摘要上限 chatMaxMemorySummaryChars", min_val=200, max_val=10000)
        chat_max_summary_msg = _num_int("chatMaxSummaryMsgChars", "待压缩消息单条截取上限 chatMaxSummaryMsgChars", min_val=100, max_val=10000)
        chat_req_limit = _num_int("chatRequestLimit", "聊天单轮最大请求轮数 chatRequestLimit", min_val=1, max_val=50)
        chat_tool_limit = _num_int("chatToolCallsLimit", "聊天单轮最大工具调用数 chatToolCallsLimit", min_val=1, max_val=100)
        chat_timeout_s = _num_float("chatTimeoutS", "聊天单轮超时 chatTimeoutS", gt_zero=True)
        chat_sum_req_limit = _num_int("chatSummaryRequestLimit", "压缩摘要最大请求轮数 chatSummaryRequestLimit", min_val=1, max_val=20)
        chat_sum_tool_limit = _num_int("chatSummaryToolCallsLimit", "压缩摘要最大工具调用数 chatSummaryToolCallsLimit", min_val=1, max_val=30)
        chat_sum_timeout_s = _num_float("chatSummaryTimeoutS", "压缩摘要超时 chatSummaryTimeoutS", gt_zero=True)

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
        report_api_keys = _resolve_api_keys(
            patch.get("reportApiKeys"),
            self.reportApiKeys,
            clear_report_api_keys,
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
            reportApiKeys=report_api_keys,
            gatewayMaxConcurrency=gateway_max_concurrency,
            releasesKeep=releases_keep,
            runsKeepDays=runs_keep_days,
            agentQueryDefaultLimit=query_default_limit,
            agentQueryMaxLimit=query_max_limit,
            agentMaxPeriodMonths=max_period_months,
            chatMaxDocChars=chat_max_doc_chars,
            chatMaxHistoryMessages=chat_max_history,
            chatMaxRunCards=chat_max_run_cards,
            chatMaxMarkdownPreviewChars=chat_max_md_preview,
            chatCompactTriggerMessages=chat_compact_trigger,
            chatCompactKeepRecent=chat_compact_keep,
            chatManualCompactKeepRecent=chat_manual_keep,
            chatManualCompactMinSlice=chat_manual_min_slice,
            chatMaxMemorySummaryChars=chat_max_summary_chars,
            chatMaxSummaryMsgChars=chat_max_summary_msg,
            chatRequestLimit=chat_req_limit,
            chatToolCallsLimit=chat_tool_limit,
            chatTimeoutS=chat_timeout_s,
            chatSummaryRequestLimit=chat_sum_req_limit,
            chatSummaryToolCallsLimit=chat_sum_tool_limit,
            chatSummaryTimeoutS=chat_sum_timeout_s,
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


def _format_keys_summary(prefix: str, changed_keys: list[str]) -> str:
    preview_keys = ", ".join(changed_keys[:4])
    suffix = f" 等 {len(changed_keys)} 项" if len(changed_keys) > 4 else ""
    return f"{prefix}（{preview_keys}{suffix}）"


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
        self._index_cache: tuple[tuple[int, int], list[dict[str, Any]]] | None = None
        self._public_cfg_cache: dict[str, dict[str, Any]] = {}

    def _ensure_dirs(self) -> None:
        self.revisions_dir.mkdir(parents=True, exist_ok=True)
        _chmod_safe(self.root, 0o700)
        _chmod_safe(self.revisions_dir, 0o700)

    def _revision_path(self, rev: str) -> Path:
        if not isinstance(rev, str) or not CONFIG_REV_RE.match(rev):
            raise InvalidResource(f"运行配置版本号「{rev}」格式不合法")
        return ensure_within(self.revisions_dir, self.revisions_dir / f"{rev}.json")

    def exists(self) -> bool:
        """磁盘上是否已存在持久化的运行配置（含 current.json 丢失但索引或历史快照仍存在的待恢复态）。"""
        if self.current_path.is_file() or self.index_path.is_file():
            return True
        return self.revisions_dir.is_dir() and any(
            CONFIG_REV_RE.match(p.stem) for p in self.revisions_dir.glob("c*.json")
        )

    def _index_sig(self) -> tuple[int, int]:
        try:
            st = self.index_path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return (0, -1)

    def _read_index_entries(self) -> list[dict[str, Any]]:
        sig = self._index_sig()
        if self._index_cache is not None and self._index_cache[0] == sig:
            return list(self._index_cache[1])
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
        self._index_cache = (sig, valid)
        return list(valid)

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
        storage_dict = cfg.to_storage_dict()
        meta_fields = {
            "n": n,
            "time": ts,
            "operator": operator,
            "type": type_label,
            "source": source,
            "summary": summary,
            "note": note,
            "changedKeys": list(changed_keys),
        }
        write_json(self._revision_path(rev), {"rev": rev, **meta_fields, "config": storage_dict}, mode=0o600)
        append_jsonl(self.index_path, {"rev": rev, **meta_fields}, mode=0o600)
        self._index_cache = None
        write_json(self.current_path, {"activeRev": rev, **meta_fields, "config": storage_dict}, mode=0o600)
        self._public_cfg_cache[rev] = cfg.to_public_dict()
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

    def bootstrap_or_load(self, settings: Settings) -> RuntimeSnapshot:
        """启动时调用：若无持久化文件则从环境变量初始化释放 c1；若已存在则加载磁盘生效配置。"""
        with self.lock:
            if self._fallback_settings != settings:
                self._public_cfg_cache.clear()
            self._fallback_settings = settings
            self._ensure_dirs()
            self._cleanup_tmp_files()
            cur = read_json(self.current_path)
            if isinstance(cur, dict) and isinstance(cur.get("config"), dict):
                try:
                    rev = str(cur.get("activeRev") or "c1")
                    if not CONFIG_REV_RE.match(rev):
                        rev = "c1"
                    n = int(cur.get("n") or rev[1:])
                    cfg = RuntimeConfig.from_storage_dict(cur["config"], fallback_settings=settings)
                    cfg.validate()
                except (TypeError, ValueError, RuntimeConfigValidationError) as exc:
                    log.warning("current.json 字段损坏或不合法，尝试从历史快照恢复：%s", exc)
                else:
                    ts = str(cur.get("time") or now_iso())
                    op = str(cur.get("operator") or "system")
                    type_label = str(cur.get("type") or "初始化")
                    source = str(cur.get("source") or type_label)
                    summary = str(cur.get("summary") or "")
                    note = str(cur.get("note") or "")
                    changed_keys = [str(k) for k in (cur.get("changedKeys") or []) if isinstance(k, str)]
                    normalized_dict = cfg.to_storage_dict()
                    meta_fields = {
                        "n": n,
                        "time": ts,
                        "operator": op,
                        "type": type_label,
                        "source": source,
                        "summary": summary,
                        "note": note,
                        "changedKeys": changed_keys,
                    }
                    # 兼容旧版 current.json 缺失新增字段（如 reportApiKeys）时归一化回写保存
                    if cur["config"] != normalized_dict:
                        write_json(
                            self.current_path,
                            {"activeRev": rev, **meta_fields, "config": normalized_dict},
                            mode=0o600,
                        )
                    # 确保对应的不可变版本快照与索引行均存在（兼容崩溃恢复自愈）
                    rev_path = self._revision_path(rev)
                    if not rev_path.exists():
                        write_json(rev_path, {"rev": rev, **meta_fields, "config": normalized_dict}, mode=0o600)
                    if not any(e["rev"] == rev for e in self._read_index_entries()):
                        append_jsonl(self.index_path, {"rev": rev, **meta_fields}, mode=0o600)
                        self._index_cache = None
                    _chmod_safe(self.current_path, 0o600)
                    if self.index_path.exists():
                        _chmod_safe(self.index_path, 0o600)
                    self._public_cfg_cache[rev] = cfg.to_public_dict()
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

            # 若 current.json 缺失或损坏，优先从 index.jsonl 或 revisions/c*.json 最近一个有效快照恢复
            candidates: list[dict[str, Any]] = list(reversed(self._read_index_entries()))
            seen_revs = {c["rev"] for c in candidates}
            if self.revisions_dir.is_dir():
                disk_revs = sorted(
                    (p.stem for p in self.revisions_dir.glob("c*.json") if CONFIG_REV_RE.match(p.stem)),
                    key=lambda r: int(r[1:]),
                    reverse=True,
                )
                for r in disk_revs:
                    if r not in seen_revs:
                        candidates.append({"rev": r, "n": int(r[1:])})

            for entry in candidates:
                rev_doc = read_json(self._revision_path(entry["rev"]))
                if not isinstance(rev_doc, dict) or not isinstance(rev_doc.get("config"), dict):
                    continue
                try:
                    cfg = RuntimeConfig.from_storage_dict(rev_doc["config"], fallback_settings=settings)
                    cfg.validate()
                    n = int(entry["n"])
                except (TypeError, ValueError, RuntimeConfigValidationError):
                    continue
                rev = entry["rev"]
                ts = str(rev_doc.get("time") or entry.get("time") or now_iso())
                op = str(rev_doc.get("operator") or entry.get("operator") or "system")
                type_label = str(rev_doc.get("type") or entry.get("type") or "恢复")
                source = str(rev_doc.get("source") or entry.get("source") or type_label)
                summary = str(rev_doc.get("summary") or entry.get("summary") or "")
                note = str(rev_doc.get("note") or entry.get("note") or "")
                raw_ck = rev_doc.get("changedKeys") or entry.get("changedKeys") or []
                changed_keys = [str(k) for k in raw_ck if isinstance(k, str)]
                meta_fields = {
                    "n": n,
                    "time": ts,
                    "operator": op,
                    "type": type_label,
                    "source": source,
                    "summary": summary,
                    "note": note,
                    "changedKeys": changed_keys,
                }
                write_json(
                    self.current_path,
                    {"activeRev": rev, **meta_fields, "config": cfg.to_storage_dict()},
                    mode=0o600,
                )
                if not any(e["rev"] == rev for e in self._read_index_entries()):
                    append_jsonl(self.index_path, {"rev": rev, **meta_fields}, mode=0o600)
                    self._index_cache = None
                self._public_cfg_cache[rev] = cfg.to_public_dict()
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
        """按版本号倒序返回全部配置历史（脱敏展示，命中内存缓存时免重复读取快照文件）。"""
        with self.lock:
            active = self.active()
            entries = self._read_index_entries()
            out: list[dict[str, Any]] = []
            for e in reversed(entries):
                rev = e["rev"]
                masked_cfg = self._public_cfg_cache.get(rev)
                if masked_cfg is None:
                    rev_doc = read_json(self._revision_path(rev))
                    if isinstance(rev_doc, dict) and isinstance(rev_doc.get("config"), dict):
                        try:
                            snap_cfg = RuntimeConfig.from_storage_dict(
                                rev_doc["config"], fallback_settings=self._fallback_settings
                            )
                            masked_cfg = snap_cfg.to_public_dict()
                            self._public_cfg_cache[rev] = masked_cfg
                        except (TypeError, ValueError):
                            masked_cfg = {}
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
                        "config": dict(masked_cfg),
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
        clear_report_api_keys: bool = False,
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
                clear_report_api_keys=clear_report_api_keys,
            )
            changed_keys = current.config.diff_keys(new_cfg)
            if not changed_keys:
                return current, False
            clean_note = (note or "").strip()
            snap = self._write_revision(
                cfg=new_cfg,
                operator=operator,
                type_label="修改",
                source="管理端热更新",
                summary=_format_keys_summary("更新运行配置", changed_keys),
                note=clean_note,
                changed_keys=changed_keys,
            )
            append_audit(
                self.layout.audit,
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
            try:
                target_cfg = RuntimeConfig.from_storage_dict(
                    rev_doc["config"], fallback_settings=self._fallback_settings
                )
            except (TypeError, ValueError) as exc:
                raise RuntimeConfigValidationError([f"运行配置版本 {clean_target} 数据已损坏：{exc}"]) from exc
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
            append_audit(
                self.layout.audit,
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
            snap = self._write_revision(
                cfg=env_cfg,
                operator=operator,
                type_label="环境同步",
                source="环境变量同步",
                summary=_format_keys_summary("从环境变量同步", changed_keys),
                note=clean_note,
                changed_keys=changed_keys,
            )
            append_audit(
                self.layout.audit,
                "runtime-config-sync-env",
                operator,
                {"rev": snap.rev, "base": current.rev, "changedKeys": changed_keys, "note": clean_note},
            )
            return snap, True
