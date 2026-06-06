#!/bin/bash
# Exit immediately if a command exits with a non-zero status
set -e

echo "🔨 Instructing OCI VM to pull from Git and rebuild..."
# The -A flag enables SSH agent forwarding so the VM can temporarily use your local SSH key to pull from Git
ssh -A -i ~/Downloads/ssh-key-2026-05-27.key opc@100.68.227.114 \
  "which git >/dev/null 2>&1 || sudo dnf install -y git || sudo yum install -y git; \
   ssh-keygen -F github.com >/dev/null 2>&1 || (mkdir -p ~/.ssh && ssh-keyscan -t ed25519,ecdsa,rsa github.com >> ~/.ssh/known_hosts 2>/dev/null); \
   cd /home/opc/data/storyflow; \
   [ -d .git ] || (git init && git remote add origin git@github.com:kelvitz716/StoryFlow.git && git fetch && git reset --hard origin/master && git branch --set-upstream-to=origin/master master); \
   git fetch origin master && git reset --hard origin/master && (docker rm -f storyflow_app || true) && docker compose up -d --build"

echo "✅ Update successful!"
