# Verification Log — v0.3.5 (live server + fake Ollama)

รันจริงด้วย `python server.py <dir> --port 8765 --token …` + fake Ollama (NDJSON stream) ที่ 127.0.0.1:11434
สคริปต์: curl ทีละขั้น (startup → auth → SSE → RBAC → quota → SQLite/export → guest → Ollama down → lockout)

```text
=== 1) Server startup & health ===
{"ok": true, "ollama": "up", "ram_pressure": false, "recommended_model": "qwen2.5-coder:1.5b", "recommend_reason": "ใช้ตามที่ขอ (RAM รับไหว)", "backend": {"backend": "cpu", "device": null, "ngl": "0", "source": "default"}, "network": {"bind": "127.0.0.1", "mode": "local", "auth_required": true}}
{"version": "unknown", "python": "3.13.16", "name": "LCA (Local Code Assistant)"}

=== 2) Auth: bootstrap CEO, create USER/ADMIN, login, /api/me, lockout ===
{"created": {"username": "boss", "role": "CEO", "active": true}, "bootstrap": true}
{"created": {"username": "alice", "role": "USER", "active": true}}
{"created": {"username": "ops", "role": "ADMIN", "active": true}}
alice token prefix: lcs_…  ops token prefix: lcs_…
{"username": "alice", "role": "USER", "tier": "paid", "source": "session", "expires_at": …}
-- no token:
HTTP 401


=== 3) SSE streaming via curl -N (/api/chat/stream and /api/vscode/chat) ===
HTTP/1.0 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
X-Accel-Buffering: no

data: {"delta": "สวัสดี"}

data: {"delta": " ครับ"}

data: {"delta": " (fake-ollama)"}

data: {"done": true}


-- vscode alias:
data: {"delta": "สวัสดี"}

data: {"delta": " ครับ"}

data: {"delta": " (fake-ollama)"}

data: {"done": true}


=== 4) RBAC: /dev hidden from USER/anon, open for ADMIN ===
anon  /dev  -> HTTP 302 Location=http://127.0.0.1:8765/login?next=/dev
USER  /dev  -> HTTP 403
ADMIN /dev  -> HTTP 200
USER  /api/admin/users -> HTTP 403
cookie-only on API (must be 401) -> HTTP 401

=== 5) Quota: free key 100/day -> 429, paid unlimited ===
free key: 101 calls ->     100 200       1 429 
free key call #102 body: {"error": "เกินโควตาการใช้งานรายวันของ API key นี้แล้ว (อัปเกรดเป็น tier paid เพื่อใช้ได้ไม่จำกัด)"}
paid key after 101: HTTP 200
usage summary: {"summary": {"total_units": 101, "total_cost": 0.1, "currency": "THB (ประมาณการ — ไม่ใช่การเรียกเก็บจริง)", "by_tier": {"free": {"units": 100, "events": 100, "unit_price": 0.0, "cost": 0.0}, "paid": {"units": 1, "events": 1, "unit_price

=== 6) SQLite persistence + Session Tape export + ownership ===
{"reply": "สวัสดี ครับ (fake-ollama)", "provider": "ollama", "model": "qwen2.5:0.5b", "conversation_id": 1, "message_id": 2, "status": "ok", "error": null, "usage": {"input_tokens": 264, "output_tokens": 6, "total_tokens": 270, "estimated": true}, "path": [{"id": 1, "uid": "01a1c
-- export json (first 200 chars):
{"format": "lca-chat-export", "version": 1, "schema_version": 10, "personas": [], "folders": [], "conversation": {"uid": "01a1cabd-f46a-7503-a956-5ffa4f3f1860", "title": "alice tape", "folder_uid": nu
-- export markdown:
# alice tape

> owner: alice · created_at: 1794402808938 · updated_at: 1794402808988 · uid: 01a1cabd-f46a-7503-a956-5ffa4f3f1860

## ผู้ใช้

สวัสดี ทดสอบเทป

## ผู้ช่วย (ollama/qwen2.5:0.5b)

สวัสดี ครับ (fake-ollama)

-- ops(ADMIN) reads alice conv -> HTTP 200
-- bob(USER) reads alice conv -> {"error": "ไม่มีสิทธิ์เข้าถึงการสนทนานี้"} HTTP 403
-- bob list sees: {"conversations": []}
-- files on disk:
conn_usage.db data org.json report.txt server.log stats.db usage.db 
lca.db conversations: [(1, 'alice tape', 'alice')]
messages: 2

=== 7) Guest mode (flag off -> 401; on -> 200, nothing persisted) ===
flag off: HTTP 401
{"updated": {"key": "guest_chat", "name": "Guest chat", "enabled": true}}

flag on, guest chat: {"reply": "สวัสดี ครับ (fake-ollama)"}
guest + conversation_id -> {"error": "guest ไม่บันทึกบทสนทนา — ล็อกอินเพื่อใช้ประวัติ"} HTTP 403
guest + cloud provider -> {"error": "guest ใช้ได้เฉพาะโมเดล local"} HTTP 403
messages after guest chat (unchanged): 2

=== 8) Ollama down -> clean error (no empty reply) ===
data: {"error": "stream จาก Ollama ไม่สำเร็จ: <urlopen error [Errno 111] Connection refused>", "status": "error", "partial": true}


HTTP 200
{"error": "เรียก Ollama ไม่สำเร็จ (ตรวจว่า `ollama serve` รันอยู่ไหม)"} HTTP 502

=== 9) Brute-force lockout (same IP) ===
-- 5 wrong passwords then correct one (expect 401 x5 then 429):
401 401 401 401 401 {"error": "ล็อกอินพลาดบ่อยเกินไป — รอ 1 นาทีแล้วลองใหม่"} -> HTTP 429
logout -> {"revoked": true}
after logout /api/me -> HTTP 401

server log (errors only):
[error] ต่อ Ollama ไม่ได้: <urlopen error [Errno 111] Connection refused>
```
