#!/usr/bin/env bash
# Print the current Quick Tunnel link (with the access token). The address changes when the server restarts.
cd "$(dirname "$0")/.."
TOKEN="$(cat .web_token 2>/dev/null || true)"
for _ in $(seq 1 20); do
  HOST="$(curl -fs http://127.0.0.1:20241/quicktunnel | python3 -c 'import json,sys; print(json.load(sys.stdin).get("hostname",""))' 2>/dev/null || true)"
  [ -n "$HOST" ] && [ -n "$TOKEN" ] && break
  sleep 2
  TOKEN="$(cat .web_token 2>/dev/null || true)"
done
if [ -z "$HOST" ]; then
  echo "ยังไม่ได้ลิงก์จาก cloudflared ดู: journalctl -u ttlive-tunnel -n 30"; exit 1
fi
if [ -z "$TOKEN" ]; then
  echo "ตัวบันทึกยังไม่เริ่ม ดู: journalctl -u ttlive -n 30"; exit 1
fi
echo "เปิดหน้าเว็บ (ลิงก์นี้มีรหัสผ่านในตัว เก็บไว้คนเดียว): https://$HOST/?token=$TOKEN"
