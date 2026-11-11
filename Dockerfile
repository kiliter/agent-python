# #Created By AiCoding(codex) 后端镜像：单进程运行，数据目录挂载 PVC 到 /data
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev && chown -R app /app

ENV DATA_DIR=/data \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
# 必须单进程：写锁、发布锁、运行记录单写者都在进程内
CMD ["report-agent", "serve", "--host", "0.0.0.0", "--port", "8000"]
