#!/bin/bash
# Exit immediately if a command exits with a non-zero status
set -e

# Configuration with environment variable overrides (G5)
OCI_HOST="${OCI_HOST:-100.68.227.114}"
OCI_KEY="${OCI_KEY:-$HOME/Downloads/ssh-key-2026-05-27.key}"
OCI_GIT_URL="${OCI_GIT_URL:-https://github.com/kelvitz716/StoryFlow.git}"
REF="${1:-origin/master}"

# Validate REF against allowed characters (G5)
if ! [[ "$REF" =~ ^[A-Za-z0-9._/-]+$ ]]; then
    echo "❌ Error: Invalid REF format '$REF'" >&2
    exit 1
fi

echo "🔨 Instructing OCI VM to pull from Git and rebuild..."
echo "Target ref: $REF on $OCI_HOST"

# Optional signed commit/tag check command
VERIFY_CMD=""
if [ "${REQUIRE_SIGNED:-0}" = "1" ]; then
    VERIFY_CMD="git verify-commit HEAD 2>/dev/null || git verify-tag HEAD 2>/dev/null || (echo '❌ Verification failed: commit/tag not signed' >&2 && exit 1); "
fi

# Note: -A (SSH agent forwarding) removed for security (G5)
ssh -i "$OCI_KEY" "opc@$OCI_HOST" \
  "which git >/dev/null 2>&1 || sudo dnf install -y git || sudo yum install -y git; \
   cd /home/opc/data/storyflow; \
   if [ ! -d .git ]; then \
       git init && git remote add origin '$OCI_GIT_URL'; \
   else \
       git remote set-url origin '$OCI_GIT_URL'; \
   fi; \
   git fetch --tags origin && \
   git reset --hard '$REF' && \
   ${VERIFY_CMD}(docker rm -f storyflow_app || true) && \
   docker compose up -d --build"

echo "✅ Update successful!"

