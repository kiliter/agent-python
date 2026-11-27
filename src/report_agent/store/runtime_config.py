"""磁盘持久化的运行期热更新配置仓库（统一网关 + 大模型 / 智能体参数 + 版本历史与回退）。

#Created By AiCoding(codex)
目录结构（位于 data/config/runtime/，所有文件权限严格限制为 0600）：
├── current.json        当前生效配置与元数据（activeRev、operator、source、time、note、config）
├── index.jsonl         修订日志（c1, c2, ...，不含明文密钥）
└── revisions/
    └── cN.json         每个版本的完整不可变快照（含密钥，用于精确回退，权限 0600）
"""

from __future__ import annotations

import dataclasses
import logging
import math
import re
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import SecretStr

from ..config import Settings
from .fsutil import (
    _chmod_safe,
    append_audit,
    append_jsonl,
    atomic_write_bytes,
    fmt_time,
    now_iso,
    read_json,
    read_jsonl,
    write_json,
)
from .layout import DataLayout, InvalidResource, ensure_within
from .service import ResourceNotFound

log = logging.getLogger(__name__)

CONFIG_REV_RE = re.compile(r"^c[1-9][0-9]{0,9}$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_RAW_CTRL_NO_WS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_OR_CTRL_RE = re.compile(r"[\s\x00-\x1f\x7f]")
_ASCII_INT_RE = re.compile(r"[+-]?[0-9]+")

OutputMode = Literal["tool", "native", "json_object", "prompted"]
GatewayMode = Literal["mock", "live"]
XmlStyle = Literal["java", "clean"]
FieldKind = Literal[
    "url",
    "str",
    "secret",
    "api_keys",
    "enum",
    "bool",
    "optional_bool",
    "int",
    "optional_int",
    "float",
]

_VALID_OUTPUT_MODES: tuple[OutputMode, ...] = ("tool", "native", "json_object", "prompted")
_VALID_GATEWAY_MODES: tuple[GatewayMode, ...] = ("mock", "live")
_VALID_XML_STYLES: tuple[XmlStyle, ...] = ("java", "clean")
_MAX_TIMEOUT_S: float = 86400.0
_MAX_LLM_TOKENS: int = 2_000_000

_default_fallback_settings_cache: Settings | None = None
_default_fallback_lock = threading.Lock()


def _get_default_fallback_settings() -> Settings:
    """惰性获取不受当前进程环境变量污染的纯默认 Settings 实例，消除 import 期脏环境变量崩溃隐患。"""
    global _default_fallback_settings_cache
    if _default_fallback_settings_cache is None:
        with _default_fallback_lock:
            if _default_fallback_settings_cache is None:
                pure_defaults: dict[str, Any] = {}
                for field_name, field_info in Settings.model_fields.items():
                    if field_info.default_factory is not None:
                        pure_defaults[field_name] = field_info.default_factory()
                    else:
                        pure_defaults[field_name] = field_info.default
                _default_fallback_settings_cache = Settings(_env_file=None, **pure_defaults)
    return _default_fallback_settings_cache


@dataclass(frozen=True)
class ConfigFieldSpec:
    """单项运行配置的声明式元数据规格，统一驱动读写转换、脱敏展示、热更新补丁与区间校验。"""

    name: str
    settings_attr: str
    kind: FieldKind
    default: Any
    label: str = ""
    nullable: bool = False
    required: bool = False
    forbid_ctrl: bool = False
    min_val: int | float | None = None
    max_val: int | float | None = None
    gt_zero: bool = False
    choices: tuple[str, ...] = ()
    clear_kw: str = ""
    public_has: str = ""
    public_masked: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            object.__setattr__(self, "label", self.name)


_FIELD_SPECS: tuple[ConfigFieldSpec, ...] = (
    # LLM
    ConfigFieldSpec(
        "llmBaseUrl", "llm_base_url", "url", "https://api.openai.com/v1",
        label="大模型接口地址 llmBaseUrl", required=True,
    ),
    ConfigFieldSpec(
        "llmApiKey", "llm_api_key", "secret", "",
        clear_kw="clear_llm_api_key", public_has="hasLlmApiKey", public_masked="llmApiKeyMasked",
    ),
    ConfigFieldSpec(
        "llmModel", "llm_model", "str", "deepseek-v4-flash",
        label="模型名称 llmModel", required=True, forbid_ctrl=True,
    ),
    ConfigFieldSpec(
        "llmTemperature", "llm_temperature", "float", 0.0,
        label="采样温度 llmTemperature", min_val=0.0, max_val=2.0,
    ),
    ConfigFieldSpec(
        "llmMaxTokens", "llm_max_tokens", "optional_int", None,
        label="最大输出 Token 数 llmMaxTokens", nullable=True, min_val=1, max_val=_MAX_LLM_TOKENS,
    ),
    ConfigFieldSpec(
        "llmTimeoutS", "llm_timeout_s", "float", 120.0,
        label="模型请求超时 llmTimeoutS", gt_zero=True, max_val=_MAX_TIMEOUT_S,
    ),
    ConfigFieldSpec(
        "llmHttpRetries", "llm_http_retries", "int", 2,
        label="模型 HTTP 重试次数 llmHttpRetries", min_val=0, max_val=10,
    ),
    ConfigFieldSpec("llmParallelToolCalls", "llm_parallel_tool_calls", "optional_bool", True, nullable=True),
    ConfigFieldSpec("llmStrictTools", "llm_strict_tools", "optional_bool", None, nullable=True),
    ConfigFieldSpec("llmToolChoiceRequired", "llm_tool_choice_required", "optional_bool", None, nullable=True),
    # Agent & Tools
    ConfigFieldSpec(
        "agentOutputMode", "agent_output_mode", "enum", "tool",
        label="结构化交卷方式 agentOutputMode", choices=_VALID_OUTPUT_MODES,
    ),
    ConfigFieldSpec("agentNativeStrict", "agent_native_strict", "bool", True),
    ConfigFieldSpec(
        "agentOutputRetries", "agent_output_retries", "int", 3,
        label="证据校验重试次数 agentOutputRetries", min_val=0, max_val=10,
    ),
    ConfigFieldSpec(
        "agentToolRetries", "agent_tool_retries", "int", 2,
        label="工具参数重试次数 agentToolRetries", min_val=0, max_val=10,
    ),
    ConfigFieldSpec(
        "agentRequestLimit", "agent_request_limit", "int", 25,
        label="单次最大轮数 agentRequestLimit", min_val=1, max_val=200,
    ),
    ConfigFieldSpec(
        "agentToolCallsLimit", "agent_tool_calls_limit", "int", 120,
        label="单次最大工具调用数 agentToolCallsLimit", min_val=1, max_val=500,
    ),
    ConfigFieldSpec(
        "agentRunTimeoutS", "agent_run_timeout_s", "float", 600.0,
        label="单次运行总超时 agentRunTimeoutS", gt_zero=True, max_val=_MAX_TIMEOUT_S,
    ),
    ConfigFieldSpec(
        "agentMaxConcurrentRuns", "agent_max_concurrent_runs", "int", 8,
        label="最大并发运行数 agentMaxConcurrentRuns", min_val=1, max_val=128,
    ),
    ConfigFieldSpec(
        "agentPreviewRows", "agent_preview_rows", "int", 10,
        label="接口预览行数 agentPreviewRows", min_val=1, max_val=200,
    ),
    # Gateway
    ConfigFieldSpec(
        "gatewayMode", "gateway_mode", "enum", "mock",
        label="统一网关模式 gatewayMode", choices=_VALID_GATEWAY_MODES,
    ),
    ConfigFieldSpec("gatewayUrl", "gateway_url", "url", "", label="统一网关地址 gatewayUrl"),
    ConfigFieldSpec(
        "gatewayAppId", "gateway_app_id", "secret", "",
        clear_kw="clear_gateway_app_id", public_has="hasGatewayAppId", public_masked="gatewayAppIdMasked",
    ),
    ConfigFieldSpec(
        "gatewayAccessToken", "gateway_access_token", "secret", "",
        clear_kw="clear_gateway_access_token",
        public_has="hasGatewayAccessToken",
        public_masked="gatewayAccessTokenMasked",
    ),
    ConfigFieldSpec(
        "gatewayXmlStyle", "gateway_xml_style", "enum", "java",
        label="网关 XML 风格 gatewayXmlStyle", choices=_VALID_XML_STYLES,
    ),
    ConfigFieldSpec(
        "gatewayConnectTimeoutS", "gateway_connect_timeout_s", "float", 5.0,
        label="网关连接超时 gatewayConnectTimeoutS", gt_zero=True, max_val=_MAX_TIMEOUT_S,
    ),
    # Upstream & Embed Auth
    ConfigFieldSpec(
        "reportApiKeys", "report_api_keys", "api_keys", "",
        label="调用凭证 reportApiKeys", clear_kw="clear_report_api_keys",
    ),
    # Gateway concurrency & Retention
    ConfigFieldSpec(
        "gatewayMaxConcurrency", "gateway_max_concurrency", "int", 32,
        label="网关最大并发数 gatewayMaxConcurrency", min_val=1, max_val=512,
    ),
    ConfigFieldSpec(
        "releasesKeep", "releases_keep", "int", 50,
        label="发布快照保留数 releasesKeep", min_val=1, max_val=500,
    ),
    ConfigFieldSpec(
        "runsKeepDays", "runs_keep_days", "int", 90,
        label="运行与会话留存天数 runsKeepDays", min_val=0, max_val=3650,
    ),
    # Platform Tools Limits
    ConfigFieldSpec(
        "agentQueryDefaultLimit", "agent_query_default_limit", "int", 20,
        label="结果筛选默认行数 agentQueryDefaultLimit", min_val=1, max_val=500,
    ),
    ConfigFieldSpec(
        "agentQueryMaxLimit", "agent_query_max_limit", "int", 100,
        label="结果筛选最大行数 agentQueryMaxLimit", min_val=1, max_val=1000,
    ),
    ConfigFieldSpec(
        "agentMaxPeriodMonths", "agent_max_period_months", "int", 36,
        label="多账期展开跨度上限 agentMaxPeriodMonths", min_val=1, max_val=120,
    ),
    # Chat & Compaction
    ConfigFieldSpec(
        "chatMaxDocChars", "chat_max_doc_chars", "int", 12000,
        label="聊天单据最大字符数 chatMaxDocChars", min_val=500, max_val=200000,
    ),
    ConfigFieldSpec(
        "chatMaxHistoryMessages", "chat_max_history_messages", "int", 20,
        label="聊天最近原文消息数 chatMaxHistoryMessages", min_val=1, max_val=200,
    ),
    ConfigFieldSpec(
        "chatMaxRunCards", "chat_max_run_cards", "int", 8,
        label="聊天运行卡片注入上限 chatMaxRunCards", min_val=1, max_val=50,
    ),
    ConfigFieldSpec(
        "chatMaxMarkdownPreviewChars", "chat_max_markdown_preview_chars", "int", 1500,
        label="聊天报告预览截断字数 chatMaxMarkdownPreviewChars", min_val=100, max_val=20000,
    ),
    ConfigFieldSpec(
        "chatCompactTriggerMessages", "chat_compact_trigger_messages", "int", 24,
        label="自动压缩触发消息数 chatCompactTriggerMessages", min_val=2, max_val=500,
    ),
    ConfigFieldSpec(
        "chatCompactKeepRecent", "chat_compact_keep_recent", "int", 12,
        label="自动压缩保留消息数 chatCompactKeepRecent", min_val=1, max_val=200,
    ),
    ConfigFieldSpec(
        "chatManualCompactKeepRecent", "chat_manual_compact_keep_recent", "int", 6,
        label="手动压缩保留消息数 chatManualCompactKeepRecent", min_val=1, max_val=200,
    ),
    ConfigFieldSpec(
        "chatManualCompactMinSlice", "chat_manual_compact_min_slice", "int", 2,
        label="手动压缩最小归档条数 chatManualCompactMinSlice", min_val=1, max_val=100,
    ),
    ConfigFieldSpec(
        "chatMaxMemorySummaryChars", "chat_max_memory_summary_chars", "int", 1200,
        label="滚动记忆摘要上限 chatMaxMemorySummaryChars", min_val=200, max_val=10000,
    ),
    ConfigFieldSpec(
        "chatMaxSummaryMsgChars", "chat_max_summary_msg_chars", "int", 800,
        label="待压缩消息单条截取上限 chatMaxSummaryMsgChars", min_val=100, max_val=10000,
    ),
    ConfigFieldSpec(
        "chatRequestLimit", "chat_request_limit", "int", 8,
        label="聊天单轮最大请求轮数 chatRequestLimit", min_val=1, max_val=50,
    ),
    ConfigFieldSpec(
        "chatToolCallsLimit", "chat_tool_calls_limit", "int", 16,
        label="聊天单轮最大工具调用数 chatToolCallsLimit", min_val=1, max_val=100,
    ),
    ConfigFieldSpec(
        "chatTimeoutS", "chat_timeout_s", "float", 120.0,
        label="聊天单轮超时 chatTimeoutS", gt_zero=True, max_val=_MAX_TIMEOUT_S,
    ),
    ConfigFieldSpec(
        "chatSummaryRequestLimit", "chat_summary_request_limit", "int", 3,
        label="压缩摘要最大请求轮数 chatSummaryRequestLimit", min_val=1, max_val=20,
    ),
    ConfigFieldSpec(
        "chatSummaryToolCallsLimit", "chat_summary_tool_calls_limit", "int", 4,
        label="压缩摘要最大工具调用数 chatSummaryToolCallsLimit", min_val=1, max_val=30,
    ),
    ConfigFieldSpec(
        "chatSummaryTimeoutS", "chat_summary_timeout_s", "float", 60.0,
        label="压缩摘要超时 chatSummaryTimeoutS", gt_zero=True, max_val=_MAX_TIMEOUT_S,
    ),
)

_ORDERED_FIELDS: tuple[str, ...] = tuple(sp.name for sp in _FIELD_SPECS)
_NULLABLE_FIELDS: frozenset[str] = frozenset(sp.name for sp in _FIELD_SPECS if sp.nullable)
_STRING_FIELDS: frozenset[str] = frozenset(
    sp.name for sp in _FIELD_SPECS if sp.kind in ("url", "str", "secret", "api_keys")
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
    """校验 HTTP/HTTPS 地址合法性（含 IPv6 闭合语法与 1..65535 端口边界校验）。"""
    prefix = f"{label} " if not label.endswith(" ") else label
    if _WHITESPACE_OR_CTRL_RE.search(url):
        return f"{prefix}不能包含空白或控制字符"
    if not url.startswith(("http://", "https://")):
        return f"{prefix}必须以 http:// 或 https:// 开头"
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return f"{prefix}格式不合法（请检查 IPv6 地址格式及端口号范围 1~65535）"
    if not parsed.netloc or not parsed.hostname or parsed.netloc.endswith(":"):
        return f"{prefix}缺少有效的主机地址或端口"
    if port is not None and not (1 <= port <= 65535):
        return f"{prefix}端口号必须在 1~65535 之间"
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


def _check_int_bounds(
    parsed: int,
    label: str,
    errors: list[str],
    *,
    min_val: int | None = None,
    max_val: int | None = None,
) -> None:
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


def _coerce_int(
    val: Any,
    label: str,
    errors: list[str],
    *,
    min_val: int | None = None,
    max_val: int | None = None,
) -> int:
    if isinstance(val, bool):
        errors.append(f"{label}必须是整数")
        return min_val or 0
    parsed: int | None = None
    if isinstance(val, int):
        parsed = val
    elif isinstance(val, str) and val.strip():
        s = val.strip()
        if _ASCII_INT_RE.fullmatch(s):
            parsed = int(s)
    if parsed is None:
        errors.append(f"{label}必须是整数")
        return min_val or 0
    _check_int_bounds(parsed, label, errors, min_val=min_val, max_val=max_val)
    return parsed


def _coerce_optional_int(
    val: Any,
    label: str,
    errors: list[str],
    *,
    min_val: int = 1,
    max_val: int | None = None,
) -> int | None:
    if val is None or (isinstance(val, str) and val.strip().lower() in ("", "null", "none")):
        return None
    return _coerce_int(val, label, errors, min_val=min_val, max_val=max_val)


def _check_float_bounds(
    parsed: float,
    label: str,
    errors: list[str],
    *,
    min_val: float | None = None,
    max_val: float | None = None,
    gt_zero: bool = False,
) -> None:
    if math.isnan(parsed) or math.isinf(parsed):
        errors.append(f"{label}必须是有效数字")
        return
    if gt_zero and parsed <= 0:
        errors.append(f"{label}必须大于 0")
        return
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


def _coerce_float(
    val: Any,
    label: str,
    errors: list[str],
    *,
    min_val: float | None = None,
    max_val: float | None = None,
    gt_zero: bool = False,
) -> float:
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
    _check_float_bounds(parsed, label, errors, min_val=min_val, max_val=max_val, gt_zero=gt_zero)
    return parsed


def _resolve_secret(raw: Any, current_secret: str, clear_flag: bool, label: str, errors: list[str]) -> str:
    """解析单项密钥更新：支持空串/匹配掩码保留原值，严禁将未匹配的脱敏掩码串当作明文密钥写入。"""
    if clear_flag:
        return ""
    if raw is None:
        return current_secret
    if not isinstance(raw, str):
        errors.append(f"{label}必须是字符串")
        return current_secret
    cleaned = raw.strip()
    if not cleaned or cleaned == current_secret:
        return current_secret
    if current_secret and (cleaned == "***" or cleaned == mask_secret(current_secret)):
        return current_secret
    if "***" in cleaned:
        errors.append(f"{label}不能直接提交脱敏掩码，请输入完整新密钥或使用清空选项")
        return current_secret
    if _CONTROL_CHAR_RE.search(cleaned):
        errors.append(f"{label}包含非法控制字符")
        return current_secret
    return cleaned


def _resolve_api_keys(raw: Any, current_keys: str, clear_flag: bool, errors: list[str]) -> str:
    """解析多把逗号分隔 API Key：逐项还原唯一匹配的脱敏掩码，拒绝无法唯一匹配的掩码串误存为明文。"""
    if clear_flag:
        return ""
    if raw is None:
        return current_keys
    if not isinstance(raw, str):
        errors.append("调用凭证 reportApiKeys 必须是字符串")
        return current_keys
    if _RAW_CTRL_NO_WS_RE.search(raw):
        errors.append("调用凭证 reportApiKeys 包含非法控制字符")
        return current_keys
    cleaned = raw.strip()
    existing_list = split_api_keys(current_keys)
    masked_current = mask_api_keys(current_keys)
    if not cleaned:
        return current_keys
    if existing_list and (cleaned == "***" or cleaned == masked_current):
        return current_keys
    raw_tokens = [part.strip() for part in cleaned.split(",") if part.strip()]
    if not raw_tokens:
        return current_keys
    if existing_list and raw_tokens == [mask_secret(k) for k in existing_list]:
        return current_keys

    existing_set = set(existing_list)
    resolved: list[str] = []
    for k in dict.fromkeys(raw_tokens):
        if _WHITESPACE_OR_CTRL_RE.search(k):
            errors.append("调用凭证 reportApiKeys 单把密钥不能包含空白或控制字符")
            return current_keys
        if k in existing_set:
            resolved.append(k)
            continue
        if "***" in k:
            matches = [old_k for old_k in existing_list if mask_secret(old_k) == k]
            if len(matches) == 1:
                resolved.append(matches[0])
                continue
            errors.append(f"调用凭证 reportApiKeys 中的脱敏项「{k}」无法唯一匹配现有密钥，请输入完整新密钥或使用清空选项")
            return current_keys
        resolved.append(k)
    return ",".join(dict.fromkeys(resolved))


def _parse_storage_bool(val: Any, label: str) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
        raise ValueError(f"{label}必须是布尔值: {val!r}")
    raise TypeError(f"{label}必须是布尔值: {val!r}")


def _parse_storage_int(val: Any, label: str) -> int:
    if isinstance(val, bool):
        raise ValueError(f"{label}不能为布尔值")
    if isinstance(val, int):
        return val
    if isinstance(val, str) and _ASCII_INT_RE.fullmatch(val.strip()):
        return int(val.strip())
    raise ValueError(f"{label}必须是整数: {val!r}")


def _parse_storage_float(val: Any, label: str) -> float:
    if isinstance(val, bool):
        raise ValueError(f"{label}不能为布尔值")
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str) and val.strip():
        return float(val.strip())
    raise ValueError(f"{label}必须是有效数字: {val!r}")


def _read_spec_from_settings(sp: ConfigFieldSpec, s: Settings) -> Any:
    if sp.kind == "secret":
        obj = getattr(s, sp.settings_attr, None)
        return obj.get_secret_value() if hasattr(obj, "get_secret_value") else str(obj or "")
    if sp.kind == "api_keys":
        return ",".join(split_api_keys(getattr(s, sp.settings_attr, "") or ""))
    if sp.kind in ("url", "str"):
        return str(getattr(s, sp.settings_attr, None) or "").strip()
    if sp.kind == "enum":
        raw = getattr(s, sp.settings_attr, None)
        return raw if raw in sp.choices else sp.default
    if sp.kind == "bool":
        raw = getattr(s, sp.settings_attr, None)
        return bool(sp.default) if raw is None else bool(raw)
    if sp.kind == "optional_bool":
        if not hasattr(s, sp.settings_attr):
            return sp.default
        raw = getattr(s, sp.settings_attr)
        return raw if isinstance(raw, bool) else None
    if sp.kind == "int":
        raw = getattr(s, sp.settings_attr, None)
        return int(sp.default) if raw is None else int(raw)
    if sp.kind == "optional_int":
        raw = getattr(s, sp.settings_attr, None)
        return int(raw) if raw is not None else None
    raw = getattr(s, sp.settings_attr, None)
    return float(sp.default) if raw is None else float(raw)


def _read_spec_from_storage(sp: ConfigFieldSpec, data: dict[str, Any], base: RuntimeConfig) -> Any:
    fallback_val = getattr(base, sp.name)
    if sp.name not in data:
        return fallback_val
    val = data[sp.name]

    if sp.kind == "optional_int":
        if val is None or (isinstance(val, str) and val.strip().lower() in ("", "null", "none")):
            return None
        return _parse_storage_int(val, sp.label)

    if sp.kind == "optional_bool":
        if val is None or (isinstance(val, str) and val.strip().lower() in ("", "null", "none", "default", "auto")):
            return None
        return _parse_storage_bool(val, sp.label)

    if val is None:
        return fallback_val

    if sp.kind in ("url", "str"):
        if not isinstance(val, str):
            raise TypeError(f"{sp.label}必须是字符串")
        return val.strip()
    if sp.kind == "secret":
        if not isinstance(val, str):
            raise TypeError(f"{sp.label}必须是字符串")
        return val
    if sp.kind == "api_keys":
        if not isinstance(val, str):
            raise TypeError(f"{sp.label}必须是字符串")
        return ",".join(split_api_keys(val))

    if isinstance(val, str) and val.strip() == "":
        return fallback_val

    if sp.kind == "enum":
        return val if val in sp.choices else fallback_val
    if sp.kind == "bool":
        return _parse_storage_bool(val, sp.label)
    if sp.kind == "int":
        return _parse_storage_int(val, sp.label)
    return _parse_storage_float(val, sp.label)


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
        return cls(**{sp.name: _read_spec_from_settings(sp, s) for sp in _FIELD_SPECS})

    @classmethod
    def from_storage_dict(cls, data: dict[str, Any], fallback_settings: Settings | None = None) -> RuntimeConfig:
        """从磁盘字典恢复，缺失或非可空字段为空时自动回退到 fallback_settings。"""
        base = cls.from_settings(fallback_settings or _get_default_fallback_settings())
        if not isinstance(data, dict):
            return base
        return cls(**{sp.name: _read_spec_from_storage(sp, data, base) for sp in _FIELD_SPECS})

    def to_storage_dict(self) -> dict[str, Any]:
        """转换为落盘快照字典（含密钥，仅用于 0600 磁盘存储）。"""
        return {sp.name: getattr(self, sp.name) for sp in _FIELD_SPECS}

    def to_public_dict(self) -> dict[str, Any]:
        """转换为管理端公开字典（绝不暴露任何明文密钥）。"""
        out: dict[str, Any] = {}
        for sp in _FIELD_SPECS:
            val = getattr(self, sp.name)
            if sp.kind == "secret":
                out[sp.public_has] = bool(val)
                out[sp.public_masked] = mask_secret(val)
            elif sp.kind == "api_keys":
                keys = split_api_keys(val)
                out["hasReportApiKeys"] = bool(keys)
                out["reportApiKeysMasked"] = mask_api_keys(val)
                out["reportApiKeyCount"] = len(keys)
            else:
                out[sp.name] = val
        return out

    def to_effective_settings(self, base_settings: Settings) -> Settings:
        """基于启动环境变量 Settings 生成叠加当前运行配置后的生效 Settings 副本。"""
        updates = {
            sp.settings_attr: (SecretStr(getattr(self, sp.name)) if sp.kind == "secret" else getattr(self, sp.name))
            for sp in _FIELD_SPECS
        }
        return base_settings.model_copy(update=updates)

    def diff_keys(self, other: RuntimeConfig) -> list[str]:
        """按标准顺序返回两个配置之间发生变化的字段名列表。"""
        return [k for k in _ORDERED_FIELDS if getattr(self, k) != getattr(other, k)]

    def validate(self) -> None:
        """完整校验所有字段的合法性、区间上限与跨字段联动约束，不通过则抛出 RuntimeConfigValidationError。"""
        errors: list[str] = []
        for sp in _FIELD_SPECS:
            val = getattr(self, sp.name)
            if sp.kind == "url":
                if sp.required and not val:
                    errors.append(f"{sp.label} 不能为空")
                elif val:
                    err = _check_http_url(val, sp.label)
                    if err:
                        errors.append(err)
            elif sp.kind == "str":
                if sp.required and not val:
                    errors.append(f"{sp.label} 不能为空")
                elif val and sp.forbid_ctrl and _CONTROL_CHAR_RE.search(val):
                    errors.append(f"{sp.label} 包含非法控制字符")
            elif sp.kind == "secret":
                if val and _CONTROL_CHAR_RE.search(val):
                    errors.append(f"{sp.label}包含非法控制字符")
            elif sp.kind == "api_keys":
                for k in split_api_keys(val):
                    if _WHITESPACE_OR_CTRL_RE.search(k):
                        errors.append("调用凭证 reportApiKeys 单把密钥不能包含空白或控制字符")
                        break
            elif sp.kind == "enum":
                if val not in sp.choices:
                    errors.append(f"{sp.label} 不合法：{val}")
            elif sp.kind == "bool":
                if not isinstance(val, bool):
                    errors.append(f"{sp.label}必须是布尔值")
            elif sp.kind == "optional_bool":
                if val is not None and not isinstance(val, bool):
                    errors.append(f"{sp.label}必须是布尔值或 null")
            elif sp.kind == "int":
                if isinstance(val, bool) or not isinstance(val, int):
                    errors.append(f"{sp.label}必须是整数")
                else:
                    _check_int_bounds(
                        val, sp.label, errors,
                        min_val=int(sp.min_val) if sp.min_val is not None else None,
                        max_val=int(sp.max_val) if sp.max_val is not None else None,
                    )
            elif sp.kind == "optional_int":
                if val is not None:
                    if isinstance(val, bool) or not isinstance(val, int):
                        errors.append(f"{sp.label}必须是整数")
                    else:
                        _check_int_bounds(
                            val, sp.label, errors,
                            min_val=int(sp.min_val) if sp.min_val is not None else None,
                            max_val=int(sp.max_val) if sp.max_val is not None else None,
                        )
            elif sp.kind == "float":
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    errors.append(f"{sp.label}必须是有效数字")
                else:
                    _check_float_bounds(
                        float(val), sp.label, errors,
                        min_val=float(sp.min_val) if sp.min_val is not None else None,
                        max_val=float(sp.max_val) if sp.max_val is not None else None,
                        gt_zero=sp.gt_zero,
                    )

        # 跨字段联动约束
        if self.agentQueryDefaultLimit > self.agentQueryMaxLimit:
            errors.append("结果筛选默认行数 agentQueryDefaultLimit 不能大于最大行数 agentQueryMaxLimit")
        if self.gatewayMode == "live" and not self.gatewayUrl:
            errors.append("网关模式为 live 时必须配置网关地址 gatewayUrl")
        if self.chatCompactTriggerMessages <= self.chatCompactKeepRecent:
            errors.append("自动压缩触发消息数 chatCompactTriggerMessages 必须大于保留消息数 chatCompactKeepRecent")

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
        clear_flags = {
            "clear_llm_api_key": clear_llm_api_key,
            "clear_gateway_app_id": clear_gateway_app_id,
            "clear_gateway_access_token": clear_gateway_access_token,
            "clear_report_api_keys": clear_report_api_keys,
        }
        next_values: dict[str, Any] = {}

        for sp in _FIELD_SPECS:
            cur_val = getattr(self, sp.name)
            in_patch = sp.name in patch
            raw = patch.get(sp.name)

            if sp.kind == "secret":
                next_values[sp.name] = _resolve_secret(
                    raw, cur_val, clear_flags[sp.clear_kw], sp.name, errors
                )
            elif sp.kind == "api_keys":
                next_values[sp.name] = _resolve_api_keys(
                    raw, cur_val, clear_flags[sp.clear_kw], errors
                )
            elif sp.kind in ("url", "str"):
                if not in_patch or raw is None:
                    next_values[sp.name] = cur_val
                elif not isinstance(raw, str):
                    errors.append(f"{sp.name}必须是字符串")
                    next_values[sp.name] = cur_val
                else:
                    next_values[sp.name] = raw.strip()
            elif sp.kind == "enum":
                if not in_patch or raw is None:
                    next_values[sp.name] = cur_val
                else:
                    raw_mode = raw.strip() if isinstance(raw, str) else None
                    if raw_mode not in sp.choices:
                        errors.append(f"{sp.label} 必须是 {' / '.join(sp.choices)} 之一")
                        next_values[sp.name] = cur_val
                    else:
                        next_values[sp.name] = raw_mode
            elif sp.kind == "bool":
                if not in_patch or raw is None or (isinstance(raw, str) and raw.strip() == ""):
                    next_values[sp.name] = cur_val
                else:
                    next_values[sp.name] = _coerce_bool(raw, sp.label, errors)
            elif sp.kind == "optional_bool":
                next_values[sp.name] = _coerce_optional_bool(raw, sp.label, errors) if in_patch else cur_val
            elif sp.kind == "optional_int":
                next_values[sp.name] = (
                    _coerce_optional_int(
                        raw,
                        sp.label,
                        errors,
                        min_val=int(sp.min_val) if sp.min_val is not None else 1,
                        max_val=int(sp.max_val) if sp.max_val is not None else None,
                    )
                    if in_patch
                    else cur_val
                )
            elif sp.kind == "int":
                if not in_patch or raw is None or (isinstance(raw, str) and raw.strip() == ""):
                    next_values[sp.name] = int(cur_val)
                else:
                    next_values[sp.name] = _coerce_int(
                        raw,
                        sp.label,
                        errors,
                        min_val=int(sp.min_val) if sp.min_val is not None else None,
                        max_val=int(sp.max_val) if sp.max_val is not None else None,
                    )
            elif sp.kind == "float":
                if not in_patch or raw is None or (isinstance(raw, str) and raw.strip() == ""):
                    next_values[sp.name] = float(cur_val)
                else:
                    next_values[sp.name] = _coerce_float(
                        raw,
                        sp.label,
                        errors,
                        min_val=float(sp.min_val) if sp.min_val is not None else None,
                        max_val=float(sp.max_val) if sp.max_val is not None else None,
                        gt_zero=sp.gt_zero,
                    )

        if errors:
            raise RuntimeConfigValidationError(errors)

        candidate = RuntimeConfig(**next_values)
        candidate.validate()
        return candidate


if tuple(f.name for f in dataclasses.fields(RuntimeConfig)) != _ORDERED_FIELDS:  # pragma: no cover
    raise RuntimeError("RuntimeConfig 字段声明顺序与 _FIELD_SPECS 元数据表不一致")


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
        self._fallback_settings: Settings | None = None
        self._index_cache: tuple[tuple[int, int], list[dict[str, Any]]] | None = None
        self._public_cfg_cache: dict[str, dict[str, Any]] = {}

    def _effective_fallback(self) -> Settings:
        return self._fallback_settings or _get_default_fallback_settings()

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
        rev_path = self._revision_path(rev)
        prev_index = self.index_path.read_bytes() if self.index_path.is_file() else None
        write_json(rev_path, {"rev": rev, **meta_fields, "config": storage_dict}, mode=0o600)
        try:
            append_jsonl(self.index_path, {"rev": rev, **meta_fields}, mode=0o600)
            self._index_cache = None
            write_json(self.current_path, {"activeRev": rev, **meta_fields, "config": storage_dict}, mode=0o600)
        except BaseException:
            self._index_cache = None
            with suppress(OSError):
                rev_path.unlink(missing_ok=True)
            with suppress(OSError):
                if prev_index is None:
                    self.index_path.unlink(missing_ok=True)
                else:
                    atomic_write_bytes(self.index_path, prev_index, mode=0o600)
            raise
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
                    raw_rev = cur.get("activeRev")
                    if not isinstance(raw_rev, str) or not CONFIG_REV_RE.match(raw_rev):
                        raise ValueError(f"非法的 activeRev：{raw_rev!r}")
                    rev = raw_rev
                    raw_n = cur.get("n")
                    if isinstance(raw_n, bool):
                        raise ValueError("非法的修订序号 n")
                    n = int(raw_n) if raw_n is not None else int(rev[1:])
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
                return self.bootstrap_or_load(self._effective_fallback())
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
            fallback = self._effective_fallback()
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
                                rev_doc["config"], fallback_settings=fallback
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
                    rev_doc["config"], fallback_settings=self._effective_fallback()
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
                {
                    "rev": snap.rev,
                    "base": current.rev,
                    "targetRev": clean_target,
                    "reason": clean_reason,
                    "changedKeys": changed_keys,
                },
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
