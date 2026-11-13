"""FastAPI 应用入口。

#Created By AiCoding(codex)
启动：uvicorn report_agent.main:app --workers 1
必须单进程运行：草稿写锁、发布锁、运行记录单写者都在进程内。
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api.auth import LoginGuard, TokenService, UserStore
from .api.routes_chat import chat_router
from .api.routes_resources import router as resources_router
from .api.routes_system import admin_router, auth_router, report_router
from .api.routes_templates import router as templates_router
from .chat.service import ChatError
from .config import Settings, get_settings
from .container import Container, build_container
from .runtime.runner import InputValidationError, TemplateUnavailable
from .store.drafts import DraftConflict
from .store.git_repo import GitError
from .store.publisher import NothingToPublish, PublishError
from .store.releases import ReleaseNotFound
from .store.service import InvalidResource, ResourceNotFound

log = logging.getLogger("report_agent")


def setup_logging(settings: Settings) -> None:
    """控制台日志 + 可选的按天滚动文件日志（幂等防句柄泄漏）。"""
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    has_console = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in root.handlers
    )
    if not has_console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    target_log_file = (Path(settings.log_dir) / "report-agent.log").resolve() if settings.log_dir else None
    has_target_file = False
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler):
            existing_file = Path(getattr(h, "baseFilename", "")).resolve()
            if target_log_file is not None and existing_file == target_log_file:
                h.setFormatter(fmt)
                has_target_file = True
                continue
            if getattr(h, "_report_agent_managed", False):
                root.removeHandler(h)
                h.close()

    if target_log_file is not None and not has_target_file:
        target_log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.TimedRotatingFileHandler(
            target_log_file, when="midnight", backupCount=30, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        fh._report_agent_managed = True  # type: ignore[attr-defined]
        root.addHandler(fh)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _error(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, **extra})


def install_error_handlers(app: FastAPI) -> None:
    """统一错误响应：{code, message, ...}。"""

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        if isinstance(exc.detail, dict):
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return _error(422, "VALIDATION_ERROR", "请求参数不合法", errors=exc.errors())

    handlers = {
        ResourceNotFound: (404, "NOT_FOUND"), ReleaseNotFound: (404, "RELEASE_NOT_FOUND"),
        TemplateUnavailable: (404, "TEMPLATE_UNAVAILABLE"), InvalidResource: (400, "INVALID_RESOURCE"),
        NothingToPublish: (409, "NOTHING_TO_PUBLISH"),
    }
    for exc_type, (status, code) in handlers.items():
        def make(status=status, code=code):
            async def _h(_: Request, exc: Exception):
                return _error(status, code, str(exc).strip("'\""))
            return _h
        app.add_exception_handler(exc_type, make())

    @app.exception_handler(DraftConflict)
    async def _conflict(_: Request, exc: DraftConflict):
        return _error(409, "DRAFT_CONFLICT", f"草稿已被 {exc.current.get('updatedBy')} 于 {exc.current.get('updatedAt')} 修改",
                      current=exc.current)

    @app.exception_handler(PublishError)
    async def _publish(_: Request, exc: PublishError):
        return _error(422, "PUBLISH_BLOCKED", "校验未通过，不能发布", issues=[i.to_dict() for i in exc.issues])

    @app.exception_handler(InputValidationError)
    async def _input(_: Request, exc: InputValidationError):
        return _error(400, "INVALID_INPUT", str(exc), errors=exc.errors)

    @app.exception_handler(ChatError)
    async def _chat_error(_: Request, exc: ChatError):
        return _error(exc.status, exc.code, exc.message, **exc.details)

    @app.exception_handler(GitError)
    async def _git(_: Request, exc: GitError):
        log.error("Git 操作失败：%s", exc)
        return _error(500, "GIT_ERROR", "版本库操作失败，请联系管理员")


class _SubpathPrefixMiddleware:
    """兼容子路径反代（如 /agent）：自动剥离未由 Nginx 剥离的 prefix，并将 /agent 重定向至 /agent/。"""

    def __init__(self, app, prefix: str) -> None:
        self.app = app
        self.prefix = prefix
        self._prefix_slash = f"{prefix}/"
        self._prefix_bytes = prefix.encode("ascii")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            path: str = scope.get("path", "")
            if path == self.prefix and scope["type"] == "http":
                qs = scope.get("query_string", b"")
                location = self._prefix_slash + (f"?{qs.decode('latin-1')}" if qs else "")
                resp = RedirectResponse(url=location, status_code=307)
                await resp(scope, receive, send)
                return
            if path.startswith(self._prefix_slash):
                new_scope = dict(scope)
                new_scope["path"] = path[len(self.prefix):] or "/"
                raw_path = scope.get("raw_path")
                if isinstance(raw_path, (bytes, bytearray)) and raw_path.startswith(self._prefix_bytes):
                    new_scope["raw_path"] = bytes(raw_path[len(self._prefix_bytes):]) or b"/"
                await self.app(new_scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """创建应用。测试时可传入已组装好的 container。"""
    settings = settings or (container.settings if container else get_settings())
    setup_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = container or build_container(settings)
        eff = c.settings
        app.state.container = c
        users = UserStore(c.layout.config / "users.yaml")
        if users.count() == 0 and eff.admin_bootstrap_password:
            users.upsert("admin", eff.admin_bootstrap_password.get_secret_value(), "管理员", "系统维护")
            log.warning("已用 ADMIN_BOOTSTRAP_PASSWORD 创建 admin 账号，请登录后尽快修改密码")
        elif users.count() == 0:
            log.warning("还没有管理端用户，请执行：report-agent user add --username <名> --display-name <显示名>")
        app.state.users = users
        app.state.tokens = TokenService(TokenService.load_secret(eff, c.layout.config), eff.admin_token_ttl_s)
        app.state.login_guard = LoginGuard()
        app.state.report_keys = eff.report_api_key_set()
        if not app.state.report_keys:
            log.warning("未配置 REPORT_API_KEYS，上游接口 /api/v1/reports 不校验调用方")
        await c.runs.start()
        cleanup = asyncio.create_task(_cleanup_loop(c), name="runs-cleanup")
        log.info("服务启动完成：数据目录 %s，线上版本 %s，模型 %s，网关 %s", c.layout.root, c.releases.live_rev(),
                 eff.llm_model, eff.gateway_mode)
        try:
            yield
        finally:
            cleanup.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup
            if c.chat is not None:
                await c.chat.aclose()
            await c.runs.stop()
            await c.gateway.aclose()

    root_path = settings.normalized_root_path()
    app = FastAPI(title="智能申告报告填写平台", version="0.1.0", lifespan=lifespan)
    if root_path:
        app.add_middleware(_SubpathPrefixMiddleware, prefix=root_path)
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(templates_router)
    app.include_router(resources_router)
    app.include_router(admin_router)
    app.include_router(report_router)
    app.include_router(chat_router)

    @app.get("/healthz", tags=["系统"])
    def healthz(request: Request):
        c: Container = request.app.state.container
        return {"status": "UP", "liveRev": c.releases.live_rev()}

    dist = settings.frontend_dist
    if dist and Path(dist).exists():
        dist_dir = Path(dist).resolve()
        assets_dir = dist_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):
                return _error(404, "NOT_FOUND", f"接口 /{path} 不存在")
            try:
                target = (dist_dir / path).resolve()
            except OSError:
                return _error(404, "NOT_FOUND", "资源不存在")
            if path and target.is_file() and target.is_relative_to(dist_dir):
                return FileResponse(target)
            index_file = dist_dir / "index.html"
            if index_file.is_file():
                return FileResponse(index_file)
            return _error(404, "NOT_FOUND", "前端构建产物 index.html 不存在")

    return app


async def _cleanup_loop(c: Container) -> None:
    """每天清理一次过期运行记录与聊天会话。"""
    while True:
        try:
            removed = await asyncio.to_thread(c.runs.cleanup, c.settings.runs_keep_days)
            if removed:
                log.info("已清理 %d 天的过期运行记录", removed)
            if c.chat is not None:
                chat_removed = await asyncio.to_thread(c.chat.store.cleanup, c.settings.runs_keep_days)
                if chat_removed:
                    log.info("已清理 %d 个过期聊天会话文件", chat_removed)
        except Exception:  # noqa: BLE001
            log.exception("清理运行记录或聊天会话失败")
        await asyncio.sleep(24 * 3600)


def __getattr__(name: str):
    """uvicorn report_agent.main:app 时才创建应用，避免导入模块就读取配置。"""
    if name == "app":
        return create_app()
    raise AttributeError(name)
