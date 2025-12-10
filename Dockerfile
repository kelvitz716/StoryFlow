FROM python:3.11-slim-bookworm

# Install system dependencies
# ffmpeg: required for yt-dlp post-processing
# git: required for some pip packages if installed from git
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p downloads cookies sessions data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DOWNLOAD_PATH=/app/downloads
ENV COOKIE_PATH=/app/cookies

# Run the application
CMD ["python", "storyflow.py"]
