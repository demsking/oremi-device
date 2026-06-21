#
## Stage 1: Build environment
FROM python:3.12-slim AS install-dependencies-stage

# Copy the uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set the shell to /bin/bash and enable pipefail
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# Copy and install Python dependencies
WORKDIR /src
COPY uv.lock pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml


#
## Stage 2: Runtime environment
FROM python:3.12-slim

# Set the shell to /bin/bash and enable pipefail
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# Install dependencies
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    libportaudio2 \
    ffmpeg \
    pulseaudio-utils \
  && rm -rf /var/lib/apt/lists/*

# Copy built Python dependencies from the install-dependencies-stage stage
COPY --from=install-dependencies-stage /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=install-dependencies-stage /usr/local/bin/ /usr/local/bin/

# Binaries
COPY bin/* /opt/oremi/bin/
RUN chmod +x /opt/oremi/bin/*

# Copy application files
COPY scripts/pulse-client.conf /etc/pulse/client.conf
COPY pyproject.toml LICENSE /opt/oremi/
COPY oremi_device/ /opt/oremi/oremi_device

# Set environment variables
ENV PATH="/opt/oremi/bin:$PATH"
ENV PYTHONPATH="/opt/oremi"
ENV PYTHONUNBUFFERED="1"

ENV TZ="Africa/Douala"

ENV LOG_LEVEL="info"
ENV LOG_FILE=

ENV OREMI_DEVICE_LANGUAGE="fr"

WORKDIR /opt/oremi
ENTRYPOINT ["/opt/oremi/bin/entrypoint.sh"]
