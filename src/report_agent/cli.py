"""命令行：启动服务、管理用户、初始化数据目录。

#Created By AiCoding(codex)
  report-agent serve [--host 0.0.0.0] [--port 8000] [--reload]
  report-agent user add --username chenxiaoyun --display-name 陈晓芸 --role 业务维护
  report-agent init      # 只初始化数据目录（种子资源），不启动服务
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
from pathlib import Path
import sys
from typing import Any

from .config import get_settings

_BG_TASKS: set[asyncio.Task[Any]] = set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report-agent", description="智能申告报告填写平台")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="启动 HTTP 服务（单进程）")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--reload",
        action="store_true",
        help="开发态代码热重载（仅监听 report_agent 源码目录，不因 DATA_DIR 写入触发误重启）",
    )
    serve.add_argument(
        "--reload-dir",
        action="append",
        dest="reload_dirs",
        default=[],
        help="配合 --reload 指定额外监听目录（可重复传入）",
    )
    user = sub.add_parser("user", help="管理端用户")
    user_sub = user.add_subparsers(dest="action", required=True)
    add = user_sub.add_parser("add", help="新增或重置用户")
    add.add_argument("--username", required=True)
    add.add_argument("--display-name", required=True)
    add.add_argument("--role", default="业务维护")
    add.add_argument("--password", help="不传时交互输入（推荐）")
    sub.add_parser("init", help="初始化数据目录")
    args = parser.parse_args(argv)
    settings = get_settings()

    if args.cmd == "serve":
        import uvicorn

        run_kwargs: dict[str, Any] = {
            "factory": True,
            "host": args.host,
            "port": args.port,
            "log_level": settings.log_level.lower(),
            "proxy_headers": True,
            "forwarded_allow_ips": settings.forwarded_allow_ips,
        }
        if args.reload:
            # 默认精准监听包自身源码目录，避免数据目录（runs/chats/audit.jsonl）写入导致反复误重载
            pkg_dir = str(Path(__file__).resolve().parent)
            reload_dirs = list(dict.fromkeys([pkg_dir, *(args.reload_dirs or [])]))
            run_kwargs["reload"] = True
            run_kwargs["reload_dirs"] = reload_dirs
        else:
            run_kwargs["workers"] = 1
        uvicorn.run("report_agent.main:create_app", **run_kwargs)
        return 0
    if args.cmd == "init":
        from .container import build_container

        c = build_container(settings, model=object())
        try:
            print(f"数据目录：{c.layout.root}，线上版本：{c.releases.live_rev()}")
        finally:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(c.gateway.aclose())
            else:
                task = loop.create_task(c.gateway.aclose())
                _BG_TASKS.add(task)
                task.add_done_callback(_BG_TASKS.discard)
        return 0
    if args.cmd == "user" and args.action == "add":
        from .api.auth import UserStore
        from .store.layout import DataLayout

        password = args.password if args.password is not None else getpass.getpass("密码：")
        if len(password) < 8:
            print("密码至少 8 位", file=sys.stderr)
            return 2
        layout = DataLayout(settings.data_dir)
        layout.ensure()
        UserStore(layout.config / "users.yaml").upsert(args.username, password, args.display_name, args.role)
        print(f"已保存用户 {args.username}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
