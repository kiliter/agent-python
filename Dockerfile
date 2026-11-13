# #Created By AiCoding(codex) 前后端一体化镜像（参考 agent/Dockerfile 多阶段构建 + 非 root 用户 + 时区 + entrypoint）
# 阶段 1：构建前端静态产物（Vue 3 + Vite，默认相对路径 base=./ 兼容任意反代子路径）
FROM node:22-alpine AS frontend-builder

ARG VITE_BASE_PATH=./
ENV VITE_BASE_PATH=$VITE_BASE_PATH

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

# 阶段 2：构建后端 Python 依赖环境（uv 离线锁定）
FROM python:3.13-slim AS backend-builder

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# 阶段 3：最终运行镜像（前后端归集到 /app，数据目录挂载 PVC 到 /data）
FROM python:3.13-slim

WORKDIR /app

# 安装运行时依赖：git（资源版本库必需）与 tzdata（设置上海时区）
RUN apt-get update && apt-get install -y --no-install-recommends git tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo 'Asia/Shanghai' >/etc/timezone

# 创建 paasopt 用户（UID 2000，与现有容器规范一致）
RUN groupadd paasopt && useradd -g paasopt -m paasopt -u 2000

# 拷贝后端虚拟环境、源码及前端构建产物
COPY --from=backend-builder /app/.venv /app/.venv
COPY --from=backend-builder /app/src /app/src
COPY --from=backend-builder /app/pyproject.toml /app/README.md ./
COPY --from=frontend-builder /frontend/dist /app/frontend/dist

RUN mkdir -p /data && chown -R paasopt:paasopt /app /data

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chown paasopt:paasopt /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

ENV DATA_DIR=/data \
    FRONTEND_DIST=/app/frontend/dist \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER 2000
EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
