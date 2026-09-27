# One Python image; the command picks the process. The `worker` target adds Chromium, which only
# the main worker needs (backend, worker-model and migrate stay slim).
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

RUN useradd --system --uid 10000 --home-dir /app muse \
    && mkdir -p /data/artifacts && chown muse:muse /data/artifacts
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY src/ ./src/
RUN uv sync --frozen --no-dev

USER muse
EXPOSE 8000
CMD ["uvicorn", "muse.api.main:app", "--host", "0.0.0.0", "--port", "8000"]


FROM base AS worker
USER root
RUN playwright install --with-deps chromium && chmod -R a+rX /opt/playwright \
    && mkdir -p /data/browser-profile && chown muse:muse /data/browser-profile
USER muse
