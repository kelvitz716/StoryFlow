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
    local mask="$4"  # set to "mask" to hide default value
    local current_val="${!var_ref}"
    
    # Determine what to show as default in the prompt
    local display_default=""
    if [ -n "$current_val" ]; then
        if [ "$mask" == "mask" ] && [ ${#current_val} -gt 3 ]; then
            display_default="...${current_val: -3}"
        elif [ "$mask" == "mask" ]; then
            display_default="******"
        else
            display_default="$current_val"
        fi
        
        read -p "$prompt [$display_default]: " input
        if [ -z "$input" ]; then
            input="$current_val"
        fi
    else
        if [ -n "$default" ]; then
            if [ "$mask" == "mask" ] && [ ${#default} -gt 3 ]; then
                display_default="...${default: -3}"
            elif [ "$mask" == "mask" ]; then
                display_default="******"
            else
                display_default="$default"
            fi
            
            read -p "$prompt [$display_default]: " input
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
prompt_input "Enter Telegram Bot Token" "TELEGRAM_BOT_TOKEN" "$TELEGRAM_BOT_TOKEN" "mask"
prompt_input "Enter Telegram API ID" "TELEGRAM_API_ID" "$TELEGRAM_API_ID" "mask"
prompt_input "Enter Telegram API Hash" "TELEGRAM_API_HASH" "$TELEGRAM_API_HASH" "mask"
prompt_input "Enter Phone Number (for MTProto >50MB uploads)" "TELEGRAM_PHONE_NUMBER" "$TELEGRAM_PHONE_NUMBER" "mask"
prompt_input "Enter Session String (optional, for production)" "TELEGRAM_SESSION_STRING" "$TELEGRAM_SESSION_STRING" "mask"
prompt_input "Enter Admin User ID" "ADMIN_USER_ID" "618026357" "mask"
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

# Fix permissions for mounted directories (using container UID 1000)
# We use a temporary alpine container to chown the volumes. 
# This works even if the host user doesn't have sudo, because docker runs as root.
mkdir -p downloads cookies sessions data
echo "🔒 Setting permissions for volumes (UID 1000)..."
docker run --rm \
    -v "$(pwd)/downloads:/downloads" \
    -v "$(pwd)/cookies:/cookies" \
    -v "$(pwd)/sessions:/sessions" \
    -v "$(pwd)/data:/data" \
    alpine sh -c "chown -R 1000:1000 /downloads /cookies /sessions /data" || echo "⚠️  Warning: Permission fix failed."

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
