# ── Stage 1: Builder ─────────────────────────────────────────────────────────
# Pinned digest — update when you intentionally upgrade the base image.
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS builder

# Install system build-time dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install Python dependencies into a dedicated prefix so we can copy them
# cleanly without dragging build tools into the runtime image.
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS runtime

# Only runtime system dependencies (no build-essential, no git)
# ffmpeg: required for yt-dlp post-processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DOWNLOAD_PATH=/app/downloads
ENV COOKIE_PATH=/app/cookies

# Copy pre-built packages from builder stage
COPY --from=builder /install /usr/local

# Create storyflow user first and prepare data directories
RUN groupadd -r storyflow && useradd -r -g storyflow -u 1000 -m -d /app storyflow && \
    mkdir -p downloads cookies sessions data logs && \
    chown -R storyflow:storyflow /app

# Copy application code (respects .dockerignore — no dev artifacts)
COPY --chown=storyflow:storyflow . .

# Switch to non-root user
USER storyflow

# Run the update entrypoint script
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]

