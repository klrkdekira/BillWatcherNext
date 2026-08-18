# Base image pinned by digest as well as by tag, so a rebuild uses the bytes that were reviewed
# rather than whatever the tag points at today. Bumping it is a deliberate step: change the tag,
# re-resolve the digest with
#   docker buildx imagetools inspect python:<version>-slim-bookworm --format '{{.Manifest.Digest}}'
# and re-run `make check` and `make docker-build`. A stale digest fails the build loudly, which is
# the point — a silently changed base is how an image stops being the one that was scanned.
FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# The `s3` extra is part of the production runtime, not an option: `.env.example` and
# `compose.yaml` both configure the VersityGW gateway as the archive backend (ADR-013), and without
# boto3 the app refuses to start with its own documented configuration. `rag` is deliberately left
# out — it is off by default and would put an answer-provider SDK in every image.
RUN uv sync --locked --no-dev --no-editable --extra s3

FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
# Apply the base image's outstanding security updates. This is the one place the build is
# deliberately not byte-reproducible: apt resolves against Debian-Security as it stands at build
# time, and pinning that too would mean shipping a known-stale trust store. `ca-certificates` is
# the update that matters most here — the crawler verifies upstream TLS against this store, plus
# the intermediate the site omits (docs/upstream.md).
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

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
