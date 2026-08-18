FROM python:3.12.5-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12.5-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN groupadd --gid 10001 billwatcher \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin billwatcher \
    && mkdir -p /var/lib/billwatcher/blobs /app \
    && chown -R 10001:10001 /var/lib/billwatcher /app
WORKDIR /app
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 alembic.ini ./
COPY --chown=10001:10001 migrations ./migrations
# The versioned evaluation set is an operator gate, so it ships with the image.
COPY --chown=10001:10001 docs/evals ./docs/evals
USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["billwatcher", "serve", "--host", "0.0.0.0", "--port", "8000"]
