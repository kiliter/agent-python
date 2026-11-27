"""公共敏感信息脱敏工具：统一屏蔽密钥凭证、URL 认证参数与本地文件系统路径。

#Created By AiCoding(codex)
供运行时（runner/router/composite/tools）、网关层与 API/SSE 异常响应复用，
确保对外错误信息与过程事件不泄露 LLM_API_KEY、ra_ 调用密钥、Bearer 令牌或宿主机路径。
"""

from __future__ import annotations

import re
from typing import Any

_BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{6,}")
_API_KEY_PREFIX_RE = re.compile(r"\b(?:ra|sk|rk|ak|pk)[_-][A-Za-z0-9_\-]{6,}\b", re.IGNORECASE)
_CREDENTIAL_KV_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|authorization)"
    r"(\s*[:=]\s*)([^\s,;'\"&]+)"
)
_URL_USERINFO_RE = re.compile(r"(https?://)([^/\s:@]+):([^/\s@]+)@")
_URL_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|secret|password|key)=)([^&#\s'\"<>]+)"
)
_POSIX_PATH_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s:=(,'\"\uff1a]))"
    r"(?:/(?:Users|home|var|etc|tmp|private|opt|app|root|srv|mnt|Volumes)(?:/[^\s:'\",;()\[\]{}]*)?)"
)
_WIN_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s:'\",;()\[\]{}]+")


def sanitize_sensitive_text(
    raw: Any,
    fallback: str = "未知错误",
    *,
    max_chars: int = 500,
) -> str:
    """屏蔽文本中的凭证密钥、URL 敏感参数与本地绝对路径，保留正常业务诊断语义。#Created By AiCoding(codex)"""
    text = " ".join(str(raw or "").split()).strip()
    if not text:
        return fallback
    text = _URL_USERINFO_RE.sub(r"\1***:***@", text)
    text = _URL_QUERY_SECRET_RE.sub(r"\1***", text)
    text = _BEARER_TOKEN_RE.sub("Bearer ***", text)
    text = _API_KEY_PREFIX_RE.sub("***", text)
    text = _CREDENTIAL_KV_RE.sub(r"\1\2***", text)
    text = _POSIX_PATH_RE.sub("***", text)
    text = _WIN_PATH_RE.sub("***", text)
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    return text
