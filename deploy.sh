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
TELEGRAM_PHONE_NUMBER=$(get_env_val "TELEGRAM_PHONE_NUMBER")
TELEGRAM_SESSION_STRING=$(get_env_val "TELEGRAM_SESSION_STRING")
ADMIN_USER_ID=$(get_env_val "ADMIN_USER_ID")
MODE=$(get_env_val "MODE")

# 1. Prompt for configuration
echo "Please configure the application:"
prompt_input "Enter Telegram Bot Token" "TELEGRAM_BOT_TOKEN" "$TELEGRAM_BOT_TOKEN"
prompt_input "Enter Telegram API ID" "TELEGRAM_API_ID" "$TELEGRAM_API_ID"
prompt_input "Enter Telegram API Hash" "TELEGRAM_API_HASH" "$TELEGRAM_API_HASH"
prompt_input "Enter Phone Number (for MTProto >50MB uploads)" "TELEGRAM_PHONE_NUMBER" "$TELEGRAM_PHONE_NUMBER"
prompt_input "Enter Session String (optional, for production)" "TELEGRAM_SESSION_STRING" "$TELEGRAM_SESSION_STRING"
prompt_input "Enter Admin User ID" "ADMIN_USER_ID" "618026357"
prompt_input "Enter Mode (telegram/cli)" "MODE" "telegram"

# 2. Write to .env
echo "📝 Updating .env file..."
cat > .env <<EOF
# Admin Configuration
ADMIN_USER_ID=$ADMIN_USER_ID

# Snapchat API Configuration
SNAPCHAT_API_BASE_URL=https://snapstories.netlify.app

# Download Configuration
DOWNLOAD_PATH=/app/downloads
COOKIE_PATH=/app/cookies

# Rate Limiting
MAX_REQUESTS_PER_MINUTE=30
RETRY_MAX_ATTEMPTS=3
RETRY_INITIAL_WAIT=2
RETRY_MAX_WAIT=60

# Telegram Bot
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN

# MTProto API for large files >50MB (optional)
# Get credentials from https://my.telegram.org
TELEGRAM_API_ID=$TELEGRAM_API_ID
TELEGRAM_API_HASH=$TELEGRAM_API_HASH
TELEGRAM_PHONE_NUMBER=$TELEGRAM_PHONE_NUMBER

# MTProto Session String (optional, for production)
# Generate with: python scripts/generate_session.py
TELEGRAM_SESSION_STRING=$TELEGRAM_SESSION_STRING

# Mode: cli or telegram
MODE=$MODE
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
