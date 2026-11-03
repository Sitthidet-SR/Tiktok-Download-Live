#!/usr/bin/env bash
# Copy the program (and its settings, cookies and YouTube sign-in) from this computer to the VPS.
# Recordings, logs and the local access token stay here.
#   bash deploy/push-to-vps.sh ubuntu@203.0.113.10
set -euo pipefail
TARGET="${1:?usage: deploy/push-to-vps.sh user@host [remote folder]}"
REMOTE_DIR="${2:-TikTok-Download-Live}"
cd "$(dirname "$0")/.."
rsync -az --info=progress2 \
  --exclude .git/ --exclude recordings/ --exclude __pycache__/ --exclude '*.pyc' \
  --exclude ttlive.log --exclude .web_token --exclude '*.tmp' \
  ./ "$TARGET:$REMOTE_DIR/"
echo "คัดลอกแล้ว ต่อไป: ssh $TARGET แล้ว cd $REMOTE_DIR && bash deploy/install-ubuntu.sh --cloudflare https://<โดเมน>"
