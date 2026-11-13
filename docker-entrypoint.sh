#!/bin/sh
# #Created By AiCoding(codex) 容器启动脚本（单进程运行，数据目录挂载 PVC 到 /data）
set -e

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
DATA_DIR="${DATA_DIR:-/data}"
FRONTEND_DIST="${FRONTEND_DIST:-/app/frontend/dist}"
LLM_BASE_URL="${LLM_BASE_URL:-https://api.openai.com/v1}"
LLM_MODEL="${LLM_MODEL:-deepseek-v4-flash}"
GATEWAY_MODE="${GATEWAY_MODE:-mock}"
APP_ROOT_PATH="${APP_ROOT_PATH:-}"

if [ -z "${LLM_API_KEY:-}" ] || [ "${LLM_API_KEY:-}" = "dummy" ]; then
    echo "警告：环境变量 LLM_API_KEY 未配置或仍为默认值"
fi

echo "================================================"
echo "应用名称: report-agent (智能申告报告填写平台)"
echo "监听地址: $HOST:$PORT"
echo "数据目录: $DATA_DIR"
echo "前端目录: $FRONTEND_DIST"
echo "子路径前缀: ${APP_ROOT_PATH:-<根路径 />}"
echo "网关模式: $GATEWAY_MODE"
echo "LLM Base URL: $LLM_BASE_URL"
echo "LLM Model: $LLM_MODEL"
echo "================================================"

# 必须单进程：草稿写锁、发布锁、运行记录单写者都在进程内
exec report-agent serve --host "$HOST" --port "$PORT"
