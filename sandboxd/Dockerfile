FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# Runs as root inside its container only to open the Docker socket. Compose drops all caps,
# sets no-new-privileges and a read-only rootfs.
EXPOSE 8080
CMD ["uvicorn", "sandboxd.main:build", "--factory", "--host", "0.0.0.0", "--port", "8080"]
