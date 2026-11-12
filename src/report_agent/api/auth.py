"""管理端认证：用户文件 + HMAC 签名令牌（Bearer 或 HttpOnly Cookie），以及上游 API Key 校验。

#Created By AiCoding(codex)
用户保存在 data/config/users.yaml，密码使用 PBKDF2-SHA256（60 万次迭代）加盐哈希。
令牌无状态，退出登录时把令牌编号加入进程内吊销表（单实例部署，进程重启后令牌仍在有效期内可用）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import yaml
from fastapi import HTTPException, Request

from ..config import Settings
from ..store.fsutil import atomic_write_text
from ..store.layout import InvalidResource

log = logging.getLogger(__name__)

COOKIE_NAME = "ra_session"
_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or not isinstance(encoded, str) or not encoded:
        return False
    try:
        algo, iters, salt_b64, hash_b64 = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        iters_n = int(iters)
        if iters_n < 1 or iters_n > 10_000_000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt_b64), iters_n)
        return hmac.compare_digest(digest, base64.b64decode(hash_b64))
    except (ValueError, TypeError, OverflowError):
        return False


@dataclass(frozen=True)
class User:
    username: str
    displayName: str
    role: str


class UserStore:
    """用户文件读写。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError) as exc:
            log.error("用户配置文件无法读取 %s：%s", self.path, exc)
            return []
        if not isinstance(data, dict):
            return []
        raw_users = data.get("users")
        return [u for u in raw_users if isinstance(u, dict)] if isinstance(raw_users, list) else []

    def get(self, username: str) -> dict | None:
        return next((u for u in self._load() if u.get("username") == username), None)

    def count(self) -> int:
        return len(self._load())

    def upsert(self, username: str, password: str, display_name: str, role: str) -> None:
        username = username.strip()
        if not username or not password:
            raise InvalidResource("用户名和密码不能为空")
        with self._lock:
            users = [u for u in self._load() if u.get("username") != username]
            users.append({"username": username, "displayName": display_name.strip() or username, "role": role,
                          "passwordHash": hash_password(password)})
            atomic_write_text(self.path, yaml.safe_dump({"users": users}, allow_unicode=True, sort_keys=False))
            try:
                self.path.chmod(0o600)
            except OSError:
                pass


class TokenService:
    """签发与校验会话令牌。"""

    def __init__(self, secret: bytes, ttl_s: int) -> None:
        self.secret = secret
        self.ttl_s = ttl_s
        self._revoked: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def load_secret(settings: Settings, config_dir: Path) -> bytes:
        """优先使用配置的密钥；没有时在数据目录生成一个并持久化（权限 600）。"""
        if settings.admin_token_secret and settings.admin_token_secret.get_secret_value():
            return settings.admin_token_secret.get_secret_value().encode("utf-8")
        path = config_dir / ".token-secret"
        if path.exists():
            return path.read_bytes().strip()
        secret = secrets.token_urlsafe(48).encode()
        atomic_write_text(path, secret.decode())
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return secret

    def _sign(self, payload: bytes) -> str:
        return base64.urlsafe_b64encode(hmac.new(self.secret, payload, hashlib.sha256).digest()).decode().rstrip("=")

    def issue(self, user: User) -> str:
        body = json.dumps({"u": user.username, "d": user.displayName, "r": user.role,
                           "exp": int(time.time()) + self.ttl_s, "n": secrets.token_hex(8)},
                          ensure_ascii=False, separators=(",", ":")).encode()
        b64 = base64.urlsafe_b64encode(body).decode().rstrip("=")
        return f"{b64}.{self._sign(b64.encode())}"

    def verify(self, token: str) -> tuple[User, dict] | None:
        try:
            b64, sig = token.split(".", 1)
        except ValueError:
            return None
        if not hmac.compare_digest(sig, self._sign(b64.encode())):
            return None
        try:
            payload = json.loads(base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)))
        except (ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("u"), str) or not payload["u"]:
            return None
        try:
            exp = float(payload.get("exp", 0))
        except (TypeError, ValueError):
            return None
        if exp < time.time():
            return None
        with self._lock:
            if payload.get("n") in self._revoked:
                return None
        return User(payload["u"], str(payload.get("d") or payload["u"]), str(payload.get("r") or "")), payload

    def revoke(self, payload: dict) -> None:
        with self._lock:
            now = time.time()
            self._revoked = {k: v for k, v in self._revoked.items() if v > now}
            self._revoked[payload.get("n", "")] = float(payload.get("exp", now))


class LoginGuard:
    """登录失败限流：同一用户名连续失败 5 次锁定 5 分钟（带容量上限与抗用户名喷洒驱逐）。"""

    def __init__(self, max_failures: int = 5, lock_s: int = 300, max_entries: int = 4096) -> None:
        self.max_failures = max_failures
        self.lock_s = lock_s
        self.max_entries = max(16, int(max_entries))
        self._fails: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def check(self, username: str) -> None:
        now = time.time()
        with self._lock:
            count, until = self._fails.get(username, (0, 0.0))
            if until and until <= now:
                self._fails.pop(username, None)
                return
        if count >= self.max_failures and until > now:
            raise HTTPException(429, detail={"code": "LOGIN_LOCKED", "message": "登录失败次数过多，请 5 分钟后再试"})

    def fail(self, username: str) -> None:
        now = time.time()
        with self._lock:
            count, until = self._fails.pop(username, (0, 0.0))
            if until <= now:
                count = 0
            if len(self._fails) >= self.max_entries:
                self._fails = {k: v for k, v in self._fails.items() if v[1] > now}
            if len(self._fails) >= self.max_entries:
                # 优先淘汰尚未触发锁定的低频噪声条目，保护已被锁定的暴力破解目标不被冲刷解锁
                need = len(self._fails) - self.max_entries + 1
                unlocked_keys = [k for k, v in self._fails.items() if v[0] < self.max_failures][:need]
                for k in unlocked_keys:
                    self._fails.pop(k, None)
                while len(self._fails) >= self.max_entries:
                    self._fails.pop(next(iter(self._fails)))
            self._fails[username] = (count + 1, now + self.lock_s)

    def success(self, username: str) -> None:
        with self._lock:
            self._fails.pop(username, None)


def token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get(COOKIE_NAME)


def require_user(request: Request) -> User:
    """管理端接口依赖：必须已登录。"""
    tokens: TokenService = request.app.state.tokens
    token = token_from_request(request)
    verified = tokens.verify(token) if token else None
    if not verified:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED", "message": "未登录或登录已过期"})
    request.state.user = verified[0]
    request.state.token_payload = verified[1]
    return verified[0]


def require_report_key(request: Request) -> None:
    """上游业务接口依赖：配置了 REPORT_API_KEYS 时必须携带 X-API-Key。"""
    keys: set[str] = request.app.state.report_keys
    if not keys:
        return
    key = request.headers.get("x-api-key", "").strip()
    if not key:
        raise HTTPException(401, detail={"code": "INVALID_API_KEY", "message": "缺少上游调用凭证 X-API-Key"})
    if not any(hmac.compare_digest(key, k) for k in keys):
        raise HTTPException(401, detail={"code": "INVALID_API_KEY", "message": "API Key 无效"})
