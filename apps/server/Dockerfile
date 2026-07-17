# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.8.22 AS uv

FROM python:3.12.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_HTTP_TIMEOUT=900 UV_CONCURRENT_DOWNLOADS=2 \
    uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_HTTP_TIMEOUT=900 UV_CONCURRENT_DOWNLOADS=2 \
    uv sync --frozen --no-dev

RUN groupadd --system --gid 10001 novel-platform \
    && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent \
        --shell /usr/sbin/nologin novel-platform \
    && mkdir -p /data/library \
    && chown 10001:10001 /data/library \
    && chmod 700 /data/library

USER 10001:10001

EXPOSE 8000
CMD ["uvicorn", "novel_platform.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
