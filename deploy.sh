#!/bin/bash

# Exit on error
set -e

echo "🚀 StoryFlow Deployment Script"
echo "=============================="

# Function to get value from .env safely
get_env_val() {
    local key=$1
    if [ -f .env ]; then
        grep "^${key}=" .env | cut -d'=' -f2- | tr -d '"' | tr -d "'"
    fi
}

# Function to prompt with default
prompt_input() {
    local prompt="$1"
    local var_ref="$2"
    local default="$3"
    local current_val="${!var_ref}"

    if [ -n "$current_val" ]; then
        read -p "$prompt [$current_val]: " input
        if [ -z "$input" ]; then
            input="$current_val"
        fi
    else
        if [ -n "$default" ]; then
            read -p "$prompt [$default]: " input
            if [ -z "$input" ]; then
                input="$default"
            fi
        else
            read -p "$prompt: " input
        fi
    fi
    # Assign the value back to the variable name passed in var_ref
    eval "$var_ref=\"\$input\""
}

# Load current values
TELEGRAM_BOT_TOKEN=$(get_env_val "TELEGRAM_BOT_TOKEN")
TELEGRAM_API_ID=$(get_env_val "TELEGRAM_API_ID")
TELEGRAM_API_HASH=$(get_env_val "TELEGRAM_API_HASH")
MODE=$(get_env_val "MODE")

# 1. Prompt for configuration
echo "Please configure the application:"
prompt_input "Enter Telegram Bot Token" "TELEGRAM_BOT_TOKEN" 
prompt_input "Enter Telegram API ID" "TELEGRAM_API_ID" 
prompt_input "Enter Telegram API Hash" "TELEGRAM_API_HASH" 
prompt_input "Enter Mode (telegram/cli)" "MODE" "telegram"

# 2. Write to .env
echo "📝 Updating .env file..."
cat > .env <<EOF
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_API_ID=$TELEGRAM_API_ID
TELEGRAM_API_HASH=$TELEGRAM_API_HASH
MODE=$MODE
DOWNLOAD_PATH=/app/downloads
COOKIE_PATH=/app/cookies
EOF

# 3. Build Docker Image
echo "🔨 Building Docker image (this may take a minute)..."
docker build -t storyflow .

# 4. Prepare directories
mkdir -p downloads cookies sessions

# 5. Run Container
echo "🏃 Starting container..."
# Stop existing container if running
docker stop storyflow_app 2>/dev/null || true
docker rm storyflow_app 2>/dev/null || true

# Fix permissions for mounted directories (fixes Permission Denied errors)
# chmod 777 ensures the internal container user can write regardless of UID
mkdir -p downloads cookies sessions data
chmod -R 777 downloads cookies sessions data 2>/dev/null || true

# Run with host networking to avoid some DNS issues, or just standard bridge. 
# Added :z to volumes for SELinux support (required on Fedora/CentOS/RHEL)
docker run -d \
    --name storyflow_app \
    --restart unless-stopped \
    --env-file .env \
    -v "$(pwd)/downloads:/app/downloads:z" \
    -v "$(pwd)/cookies:/app/cookies:z" \
    -v "$(pwd)/sessions:/app/sessions:z" \
    -v "$(pwd)/data:/app/data:z" \
    storyflow

echo "✅ Deployment successful! Container 'storyflow_app' is running."
echo "📜 View logs with: docker logs -f storyflow_app"
