---
name: ai-cluster-setup
description: >
  ตั้งค่า AI Server Cluster บน LAN — Ollama LAN mode, LiteLLM Proxy (API token +
  multi-provider), Open WebUI Docker, Cloudflare Tunnel HTTPS.
  Master: PC/Linux 192.168.1.10 | Worker: Notebook 192.168.1.20
  เรียกใช้เมื่อ: ตั้ง/ซ่อม AI server, เพิ่มโมเดลใหม่, เปิด tunnel, debug LAN

skill_created: "2026-11-04"
version: "1.0"
script: "scripts/ai_cluster_setup.sh"
---

# AI Cluster Setup — Skill

## Architecture

```
LAN 192.168.1.x
┌─────────────────────────────────────────────────┐
│  Master Node (PC/Linux) : 192.168.1.10          │
│  ├── Ollama       :11434  (LAN open, 0.0.0.0)   │
│  ├── LiteLLM      :4000   (API token proxy)      │
│  │   └── backends: Ollama local / Claude / Gemini│
│  ├── Open WebUI   :3000   (Docker)               │
│  └── LCA Server   :8420   (python server.py)     │
│                                                   │
│  Worker Node (Notebook) : 192.168.1.20           │
│  └── Ollama       :11434  (LAN open)             │
└─────────────────────────────────────────────────┘
            │ Cloudflare Tunnel (optional)
            └──► https://*.trycloudflare.com  (HTTPS สาธารณะ)
```

## Commands

```bash
# ติดตั้งทุก service (Master Node)
./scripts/ai_cluster_setup.sh

# ติดตั้ง + เปิด Tunnel สาธารณะ
./scripts/ai_cluster_setup.sh all --tunnel

# ตรวจสุขภาพ service (ไม่ติดตั้งอะไร)
./scripts/ai_cluster_setup.sh --verify

# Worker Node เท่านั้น (ติดตั้ง Ollama)
./scripts/ai_cluster_setup.sh --worker

# หยุดทุก service
./scripts/ai_cluster_setup.sh --stop
```

## Environment Variables (เก็บใน ~/.lca/.env — gitignored)

```
LITELLM_MASTER_KEY=sk-lca-<random>   # สร้างอัตโนมัติตอนรัน phase_litellm
ANTHROPIC_API_KEY=sk-ant-...          # ต้องตั้งเองถ้าจะใช้ Claude
GEMINI_API_KEY=AIza...                # ต้องตั้งเองถ้าจะใช้ Gemini
```

## AI Backends (ผ่าน LiteLLM :4000)

| model_name | provider | ต้องการ |
|---|---|---|
| `ollama/default` | Ollama local | ไม่ต้อง key — ฟรี |
| `claude-haiku` | Anthropic API | `ANTHROPIC_API_KEY` |
| `gemini-flash` | Google GenAI | `GEMINI_API_KEY` |

ใช้ผ่าน OpenAI-compatible endpoint:
```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model":"ollama/default","messages":[{"role":"user","content":"hello"}]}'
```

## 3-Agent Development Pattern (สไตล์ 9arm)

ใช้สำหรับงานที่ซับซ้อน — 3 agent ทำงานต่อกัน:

| Agent | ชื่อ | บทบาท | หลักการ |
|---|---|---|---|
| 1 | **Leader** | วิเคราะห์ task, แบ่งงาน, review ผล | ไม่แต่งเติม, ถามก่อนสร้าง, 9arm logic |
| 2 | **Engineer** | เขียนโค้ด, ออกแบบ, implement | Minimal viable, test-first, stdlib ก่อน |
| 3 | **QA Chef** | ทดสอบ, ตรวจก่อน deploy, block ถ้าไม่ผ่าน | ไม่ allow merge ถ้า test < 100%, ไม่ skip test |

ตัวอย่างการใช้ใน Claude Code:
```
Leader → "แบ่ง task เป็น: (1) เพิ่ม endpoint X (2) เขียน test (3) verify"
Engineer → เขียน app/feature_x.py + tests/test_feature_x.py
QA Chef → รัน python -m unittest, เช็ค security, approve ถ้าผ่าน
```

## Troubleshooting

| ปัญหา | วิธีแก้ |
|---|---|
| Ollama ไม่ตอบ LAN | `sudo systemctl status ollama` → เช็ค `OLLAMA_HOST=0.0.0.0:11434` |
| Docker container ไม่ start | `docker logs open-webui` หรือ `docker logs litellm` |
| Cloudflare URL ไม่ขึ้น | `cat /tmp/cf-tunnel.log` |
| LAN เข้าไม่ถึง port | `sudo ufw allow 11434 3000 4000` แล้ว retry |
| LiteLLM key หาย | `cat ~/.lca/.env` |

## Ports Summary

| Service | Port | Access |
|---|---|---|
| Ollama | 11434 | LAN (0.0.0.0) |
| LiteLLM Proxy | 4000 | LAN |
| Open WebUI | 3000 | LAN + Tunnel |
| LCA Server | 8420 | LAN |
