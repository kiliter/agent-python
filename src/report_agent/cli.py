"""命令行：启动服务、管理用户、初始化数据目录。

#Created By AiCoding(codex)
  report-agent serve [--host 0.0.0.0] [--port 8000]
  report-agent user add --username chenxiaoyun --display-name 陈晓芸 --role 业务维护
  report-agent init      # 只初始化数据目录（种子资源），不启动服务
"""

from __future__ import annotations

import argparse
import getpass
import sys

from .config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report-agent", description="智能申告报告填写平台")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="启动 HTTP 服务（单进程）")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
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

        uvicorn.run("report_agent.main:create_app", factory=True, host=args.host, port=args.port, workers=1,
                    log_level=settings.log_level.lower())
        return 0
    if args.cmd == "init":
        from .container import build_container

        c = build_container(settings, model=object())
        print(f"数据目录：{c.layout.root}，线上版本：{c.releases.live_rev()}")
        return 0
    if args.cmd == "user" and args.action == "add":
        from .api.auth import UserStore
        from .store.layout import DataLayout

        password = args.password or getpass.getpass("密码：")
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
