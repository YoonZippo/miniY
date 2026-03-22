#!/bin/bash
# update.sh for GCP Server
# Usage: chmod +x update.sh && ./update.sh

echo "[INFO] Fetching latest code from GitHub..."
git fetch --all
git reset --hard origin/main
git clean -fd

echo "[INFO] Rebuilding and restarting Docker containers..."
sudo docker compose up -d --build

echo "[SUCCESS] miniY bot is updated and running."
