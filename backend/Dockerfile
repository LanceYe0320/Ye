# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml ./
COPY app/ app/

RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL maintainer="YE Project"
LABEL description="YE — AI Coding Assistant (Claude Code clone with GLM)"

# Minimal runtime deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application code
COPY app/ app/
COPY pyproject.toml ./

# Install ye command into PATH
RUN pip install --no-cache-dir -e .

# Data persistence
RUN mkdir -p /app/data
VOLUME /app/data

# Environment defaults (override at runtime)
ENV ZHIPU_MODEL=glm-5.1 \
    ZHIPU_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4/ \
    HOST=0.0.0.0 \
    PORT=8765 \
    DATA_DIR=/app/data

# ZHIPU_API_KEY must be provided at runtime
ENTRYPOINT ["ye"]
