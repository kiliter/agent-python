#!/bin/sh
# #Created By AiCoding(codex) 容器启动脚本（单进程运行，数据目录挂载 PVC 到 /data）
set -e

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
DATA_DIR="${DATA_DIR:-/data}"
FRONTEND_DIST="${FRONTEND_DIST:-/app/frontend/dist}"
APP_ROOT_PATH="${APP_ROOT_PATH:-}"

# 支持透传 report-agent 子命令（init / user / serve / --help / -h）或任意自定义命令（如 sh / python）
if [ "$#" -gt 0 ]; then
    case "$1" in
        init|user|--help|-h)
            exec report-agent "$@"
            ;;
        serve)
            ;;
        *)
            exec "$@"
            ;;
    esac
fi

if [ -z "${LLM_API_KEY:-}" ] || [ "${LLM_API_KEY:-}" = "dummy" ]; then
    if [ -f "$DATA_DIR/config/runtime/current.json" ]; then
        echo "提示：环境变量 LLM_API_KEY 未显式传入，将以运行时热更新配置为准"
    else
        echo "警告：环境变量 LLM_API_KEY 未配置或仍为默认值"
    fi
fi

echo "================================================"
echo "应用名称: report-agent (智能申告报告填写平台)"
echo "监听地址: $HOST:$PORT"
echo "数据目录: $DATA_DIR"
echo "前端目录: $FRONTEND_DIST"
echo "子路径前缀: ${APP_ROOT_PATH:-<根路径 />}"
echo "网关模式: ${GATEWAY_MODE:-<以运行时热更新配置或默认 mock 为准>}"
echo "LLM Base URL: ${LLM_BASE_URL:-<以运行时热更新配置或默认 https://api.openai.com/v1 为准>}"
echo "LLM Model: ${LLM_MODEL:-<以运行时热更新配置或默认 deepseek-v4-flash 为准>}"
echo "================================================"

# 必须单进程：草稿写锁、发布锁、运行记录单写者都在进程内
if [ "$#" -gt 0 ]; then
    exec report-agent "$@"
fi
exec report-agent serve --host "$HOST" --port "$PORT"
