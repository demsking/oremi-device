#
## Stage 1: Builder
FROM python:3.12-alpine3.21 AS builder

ENV UV_LINK_MODE=copy

# Set the shell to /bin/ash and enable pipefail
SHELL ["/bin/ash", "-eo", "pipefail", "-c"]

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install build tools for dependencies without Alpine wheels on all target architectures.
RUN apk add --no-cache build-base alsa-lib-dev

# Change the working directory
WORKDIR /app

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-dev --locked --no-install-project --compile-bytecode

#
## Stage 2: Final
FROM python:3.12-alpine3.21

# Set the shell to /bin/ash and enable pipefail
SHELL ["/bin/ash", "-eo", "pipefail", "-c"]

RUN apk add --no-cache \
  alsa-lib \
  build-base \
  ffmpeg \
  pulseaudio-utils \
  tzdata

RUN adduser -D -h /oremi oremi && mkdir -p /oremi/data

WORKDIR /oremi

COPY --from=builder /app/.venv /oremi/.venv
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

COPY scripts/pulse-client.conf /etc/pulse/client.conf
COPY --chown=oremi:oremi pyproject.toml LICENSE ./
COPY --chown=oremi:oremi device/ ./device/

ENV PATH="/oremi/.venv/bin:$PATH"
ENV PYTHONPATH="/oremi:/oremi/.venv/lib/python3.12/site-packages"
ENV PYTHONUNBUFFERED="1"

ENV TZ="UTC"

ENV OREMI_DEVICE_LOG_LEVEL="INFO"
ENV OREMI_DEVICE_LOG_FILE=

ENV OREMI_DEVICE_LANGUAGE="fr"
ENV OREMI_DEVICE_DATA="/oremi/data"

VOLUME /oremi/data

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["sh", "-c", "tr '\\0' ' ' < /proc/1/cmdline | grep -q '^python /oremi/device'"]

CMD ["python", "/oremi/device"]
