FROM python:3.12-slim-bookworm

# Install system dependencies
# ffmpeg: required for yt-dlp post-processing
# git: required for some pip packages if installed from git
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create storyflow user
RUN groupadd -r storyflow && useradd -r -g storyflow -u 1000 -m -d /app storyflow

# Create necessary directories and set permissions
RUN mkdir -p downloads cookies sessions data logs && \
    chown -R storyflow:storyflow /app

# Switch to non-root user
USER storyflow

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DOWNLOAD_PATH=/app/downloads
ENV COOKIE_PATH=/app/cookies

# Run the update entrypoint script
ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
