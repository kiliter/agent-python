"""FastAPI 应用入口。

#Created By AiCoding(codex)
启动：uvicorn report_agent.main:app --workers 1
必须单进程运行：草稿写锁、发布锁、运行记录单写者都在进程内。
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.auth import LoginGuard, TokenService, UserStore
from .api.routes_resources import router as resources_router
from .api.routes_system import admin_router, auth_router, report_router
from .api.routes_templates import router as templates_router
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
    """控制台日志 + 可选的按天滚动文件日志。"""
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    if settings.log_dir:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.TimedRotatingFileHandler(settings.log_dir / "report-agent.log", when="midnight",
                                                       backupCount=30, encoding="utf-8")
        fh.setFormatter(fmt)
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

    @app.exception_handler(GitError)
    async def _git(_: Request, exc: GitError):
        log.error("Git 操作失败：%s", exc)
        return _error(500, "GIT_ERROR", "版本库操作失败，请联系管理员")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """创建应用。测试时可传入已组装好的 container。"""
    settings = settings or (container.settings if container else get_settings())
    setup_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = container or build_container(settings)
        app.state.container = c
        users = UserStore(c.layout.config / "users.yaml")
        if users.count() == 0 and settings.admin_bootstrap_password:
            users.upsert("admin", settings.admin_bootstrap_password.get_secret_value(), "管理员", "系统维护")
            log.warning("已用 ADMIN_BOOTSTRAP_PASSWORD 创建 admin 账号，请登录后尽快修改密码")
        elif users.count() == 0:
            log.warning("还没有管理端用户，请执行：report-agent user add --username <名> --display-name <显示名>")
        app.state.users = users
        app.state.tokens = TokenService(TokenService.load_secret(settings, c.layout.config), settings.admin_token_ttl_s)
        app.state.login_guard = LoginGuard()
        app.state.report_keys = settings.report_api_key_set()
        if not app.state.report_keys:
            log.warning("未配置 REPORT_API_KEYS，上游接口 /api/v1/reports 不校验调用方")
        await c.runs.start()
        cleanup = asyncio.create_task(_cleanup_loop(c), name="runs-cleanup")
        log.info("服务启动完成：数据目录 %s，线上版本 %s，模型 %s，网关 %s", c.layout.root, c.releases.live_rev(),
                 settings.llm_model, settings.gateway_mode)
        try:
            yield
        finally:
            cleanup.cancel()
            await c.runs.stop()
            await c.gateway.aclose()

    app = FastAPI(title="智能申告报告填写平台", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(auth_router)
    app.include_router(templates_router)
    app.include_router(resources_router)
    app.include_router(admin_router)
    app.include_router(report_router)

    @app.get("/healthz", tags=["系统"])
    def healthz(request: Request):
        c: Container = request.app.state.container
        return {"status": "UP", "liveRev": c.releases.live_rev()}

    dist = settings.frontend_dist
    if dist and Path(dist).exists():
        app.mount("/assets", StaticFiles(directory=Path(dist) / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return _error(404, "NOT_FOUND", f"接口 /{path} 不存在")
            target = (Path(dist) / path).resolve()
            if path and target.is_file() and Path(dist).resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(Path(dist) / "index.html")

    return app


async def _cleanup_loop(c: Container) -> None:
    """每天清理一次过期运行记录。"""
    while True:
        try:
            removed = await asyncio.to_thread(c.runs.cleanup, c.settings.runs_keep_days)
            if removed:
                log.info("已清理 %d 天的过期运行记录", removed)
        except Exception:  # noqa: BLE001
            log.exception("清理运行记录失败")
        await asyncio.sleep(24 * 3600)


def __getattr__(name: str):
    """uvicorn report_agent.main:app 时才创建应用，避免导入模块就读取配置。"""
    if name == "app":
        return create_app()
    raise AttributeError(name)
