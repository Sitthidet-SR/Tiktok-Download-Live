#!/usr/bin/env bash
# Install the recorder as a system service on Ubuntu Server (22.04 or newer).
# Run it on the VPS from inside the program folder, as your normal SSH user:
#   bash deploy/install-ubuntu.sh                      # recorder only (UI on 127.0.0.1:8080)
#   bash deploy/install-ubuntu.sh --quick-tunnel     # free Cloudflare link, no domain needed
#   bash deploy/install-ubuntu.sh --cloudflare https://rec.example.com
# --quick-tunnel runs a free Cloudflare Quick Tunnel: a random https://….trycloudflare.com
# address that changes whenever the server restarts (bash deploy/show-link.sh prints it).
# --cloudflare uses your own domain and asks for the tunnel token (hidden input).
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(id -un)"
PORT=8080
PUBLIC_URL=""
CLOUDFLARE=0
QUICK=0

while [ $# -gt 0 ]; do
  case "$1" in
    --cloudflare) CLOUDFLARE=1; PUBLIC_URL="${2:-}"; shift ;;
    --quick-tunnel) QUICK=1; PUBLIC_URL="trycloudflare" ;;
    --port) PORT="$2"; shift ;;
    *) echo "unknown option: $1"; exit 2 ;;
  esac
  shift
done
if [ "$CLOUDFLARE" = 1 ] && [[ "$PUBLIC_URL" != https://* ]]; then
  echo "ใส่ที่อยู่ที่จะเปิดหน้าเว็บด้วย เช่น --cloudflare https://rec.example.com"; exit 2
fi
if [ "$RUN_USER" = root ]; then
  echo "อย่ารันด้วย root: ใช้ผู้ใช้ปกติที่ SSH เข้ามา (สคริปต์จะเรียก sudo เอง)"; exit 2
fi

echo "==> ติดตั้ง python3, ffmpeg"
sudo apt-get update -q
sudo apt-get install -y -q python3 ffmpeg ca-certificates curl

echo "==> เตรียม config.json"
cd "$APP_DIR"
[ -f config.json ] || cp config.example.json config.json
chmod 600 config.json
# No Chrome on a server: cookies come from an uploaded cookies.txt.
python3 - "$PUBLIC_URL" <<'PY'
import json, sys
from ttlive.config import update_config
with open("config.json", encoding="utf-8") as f:
    raw = json.load(f)
values = {"cookies_from_browser": ""}
if raw.get("channels") == ["your_username", "another_channel"]:
    values["channels"] = []
if sys.argv[1]:
    values["public_url"] = sys.argv[1]
update_config("config.json", **values)
PY
for f in cookies.txt client_secret.json youtube_token.json; do
  [ -f "$f" ] && chmod 600 "$f"
done

echo "==> สร้าง systemd service: ttlive"
sudo tee /etc/systemd/system/ttlive.service >/dev/null <<UNIT
[Unit]
Description=TikTok Live Recorder (web UI on 127.0.0.1:$PORT)
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
# Only this machine (and cloudflared) can reach the UI; it is never opened on the internet directly
ExecStart=/usr/bin/python3 -m ttlive web --host 127.0.0.1 --port $PORT
Environment=PYTHONUNBUFFERED=1
# Clip names and YouTube titles use Thai time, whatever the server's clock is set to
Environment=TZ=Asia/Bangkok
Restart=on-failure
RestartSec=30
# Give ffmpeg time to close the last file and merge the clip on shutdown
KillSignal=SIGTERM
TimeoutStopSec=300
Nice=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable ttlive
sudo systemctl restart ttlive

install_cloudflared() {
  echo "==> ติดตั้ง cloudflared"
  if ! command -v cloudflared >/dev/null; then
    sudo mkdir -p --mode=0755 /usr/share/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
      | sudo tee /etc/apt/sources.list.d/cloudflared.list >/dev/null
    sudo apt-get update -q
    sudo apt-get install -y -q cloudflared
  fi
}

if [ "$QUICK" = 1 ]; then
  install_cloudflared
  sudo tee /etc/systemd/system/ttlive-tunnel.service >/dev/null <<UNIT
[Unit]
Description=Free Cloudflare Quick Tunnel to the TikTok recorder UI
After=network-online.target ttlive.service
Wants=network-online.target

[Service]
User=$RUN_USER
ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate --metrics 127.0.0.1:20241 --url http://127.0.0.1:$PORT
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
  sudo systemctl daemon-reload
  sudo systemctl enable ttlive-tunnel
  sudo systemctl restart ttlive-tunnel
fi

if [ "$CLOUDFLARE" = 1 ]; then
  install_cloudflared
  if systemctl is-active --quiet cloudflared; then
    echo "cloudflared รันอยู่แล้ว ข้ามขั้นนี้ (ถ้าจะเปลี่ยน tunnel: sudo cloudflared service uninstall แล้วรันสคริปต์ใหม่)"
  else
    echo "วาง tunnel token จาก Cloudflare Zero Trust (ตัวยาวๆ ขึ้นต้นด้วย eyJ…) แล้วกด Enter (จะไม่แสดงบนจอ):"
    read -rs CF_TOKEN
    echo
    if ! sudo cloudflared service install "$CF_TOKEN"; then
      echo "ติดตั้ง tunnel ไม่สำเร็จ ตรวจ token แล้วรันสคริปต์นี้ใหม่ (ตัวบันทึกไลฟ์ติดตั้งเสร็จแล้ว)"; exit 1
    fi
    unset CF_TOKEN
  fi
fi

sleep 3
if [ "$QUICK" = 1 ]; then
  echo
  bash "$APP_DIR/deploy/show-link.sh" || true
  echo "ดูลิงก์อีกครั้งเมื่อไรก็ได้: bash deploy/show-link.sh"
  exit 0
fi
TOKEN="$(cat "$APP_DIR/.web_token" 2>/dev/null || true)"
echo
systemctl --no-pager --lines=0 status ttlive || true
echo
echo "เสร็จแล้ว"
if [ -n "$PUBLIC_URL" ] && [ -n "$TOKEN" ]; then
  echo "เปิดหน้าเว็บ (ลิงก์นี้มีรหัสผ่านในตัว เก็บไว้คนเดียว): $PUBLIC_URL/?token=$TOKEN"
else
  echo "เปิดหน้าเว็บจากคอมด้วย SSH tunnel:  ssh -L $PORT:127.0.0.1:$PORT $RUN_USER@<ที่อยู่ VPS>"
  echo "แล้วเปิด http://localhost:$PORT"
fi
echo "ดู log: journalctl -u ttlive -f"
