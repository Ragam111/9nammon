#!/usr/bin/env bash
# serve.sh — เปิด LCA server ด้วยคำสั่งเดียว (เปิดให้คนใช้จริงบนเครื่องตัวเอง)
#
# ใช้งาน:
#   ./scripts/serve.sh                 # โหมด local: เข้าได้เฉพาะเครื่องนี้ (127.0.0.1:8420) = CEO เลย
#   ./scripts/serve.sh --lan           # เปิดให้เครื่องอื่นใน Wi-Fi/LAN เข้า (บังคับมี token อัตโนมัติ)
#   ./scripts/serve.sh --lan --token เลขลับของคุณ
#   ./scripts/serve.sh --port 9000 --dir /path/to/project
#
# เปิดให้คน "นอกวง" (อินเทอร์เน็ต) เข้า ดู docs/GO_LIVE.md (ต้องมี tunnel — อย่าเปิดพอร์ตตรง ๆ)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="127.0.0.1"
PORT="8420"
DIR="$ROOT"
TOKEN=""
LAN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --lan) LAN=1; HOST="0.0.0.0"; shift ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --dir) DIR="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ไม่รู้จัก option: $1 (ดู --help)"; exit 1 ;;
  esac
done

command -v python3 >/dev/null 2>&1 || { echo "[ปฏิเสธ] ไม่พบ python3 — ติดตั้งก่อน"; exit 1; }

# เปิดออกนอก 127.0.0.1 ต้องมี token เสมอ (server.py บังคับ) — ถ้าไม่ใส่มา สุ่มให้
if [ "$HOST" != "127.0.0.1" ] && [ -z "$TOKEN" ]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  echo "[token] ไม่ได้ใส่ --token มา สุ่มให้: $TOKEN"
  echo "        เก็บไว้ให้ดี — ต้องใช้เป็น X-Auth-Token เวลาเรียก API / bootstrap CEO"
fi

# เตือนถ้า Ollama ไม่ได้รัน (แชทจะ 502 จนกว่าจะเปิด) — ไม่บล็อก ส่วนอื่นใช้ได้
if command -v curl >/dev/null 2>&1; then
  if ! curl -fsS -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "[เตือน] ต่อ Ollama (localhost:11434) ไม่ได้ — /api/chat จะได้ 502"
    echo "        เปิดก่อนด้วย:  ollama serve &   แล้ว  ollama pull qwen2.5-coder:1.5b"
  fi
fi

echo "=== LCA serve ==="
echo "โปรเจกต์: $DIR"
echo "เปิดในเครื่อง: http://127.0.0.1:${PORT}  (หน้าแชท)  ·  http://127.0.0.1:${PORT}/dev  (ทรัพยากร/แอดมิน)"
if [ "$LAN" = "1" ]; then
  LANIP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "${LANIP:-}" ] && echo "เข้าจากเครื่องอื่นใน LAN: http://${LANIP}:${PORT}  (ต้องส่ง header X-Auth-Token)"
  echo "[ความปลอดภัย] โหมด LAN เปิดให้ทั้งวงเข้าถึง — rate limit + RBAC ทำงานอยู่ แต่ต้อง bootstrap CEO + ออก API key ให้ผู้ใช้ (ดู docs/GO_LIVE.md)"
fi

ARGS=("$DIR" --host "$HOST" --port "$PORT")
[ -n "$TOKEN" ] && ARGS+=(--token "$TOKEN")
exec python3 "$ROOT/server.py" "${ARGS[@]}"
