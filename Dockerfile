# Multi-stage build leveraging the official uv binary
FROM ghcr.io/astral-sh/uv:latest AS uv_bin

FROM python:3.12-slim-bookworm

# Copy the uv binary from the official uv image
COPY --from=uv_bin /uv /uvx /bin/

# Environment configurations for Python and uv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install dependencies using uv sync --frozen (no dev dependencies)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy project files and migration scripts
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY entrypoint.sh ./

# Make entrypoint script executable
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
