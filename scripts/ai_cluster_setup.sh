#!/usr/bin/env bash
# =============================================================================
# ai_cluster_setup.sh — LCA AI Cluster Setup (ทุก service ในไฟล์เดียว)
#
# Master Node (PC/Linux)   : 192.168.1.10  — Ollama + LiteLLM + Open WebUI
# Worker Node (Notebook)   : 192.168.1.20  — Secondary Ollama node
#
# Usage:
#   ./ai_cluster_setup.sh              # ติดตั้งทุก service (ไม่เปิด tunnel)
#   ./ai_cluster_setup.sh --tunnel     # ติดตั้ง + เปิด Cloudflare Tunnel
#   ./ai_cluster_setup.sh --verify     # ตรวจ service ทั้งหมด (ไม่ติดตั้งอะไร)
#   ./ai_cluster_setup.sh --stop       # หยุดทุก service
#   ./ai_cluster_setup.sh --worker     # ติดตั้งเฉพาะ Ollama (Worker Node)
# =============================================================================
set -euo pipefail

MASTER_IP="192.168.1.10"
OLLAMA_PORT=11434
WEBUI_PORT=3000
LITELLM_PORT=4000
LCA_PORT=8420

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GRN}✔${NC} $*"; }
err()  { echo -e "${RED}✘${NC} $*" >&2; }
info() { echo -e "${YLW}▶${NC} $*"; }

# ── 1. Ollama (LAN mode) ──────────────────────────────────────────────────────
phase_ollama() {
  info "Phase 1: Ollama — เปิด LAN port ${OLLAMA_PORT}"
  if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  sudo mkdir -p /etc/systemd/system/ollama.service.d
  printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:%s"\n' "$OLLAMA_PORT" \
    | sudo tee /etc/systemd/system/ollama.service.d/lan.conf >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now ollama
  sleep 2
  sudo ufw allow "$OLLAMA_PORT"/tcp 2>/dev/null || true
  ok "Ollama: http://0.0.0.0:${OLLAMA_PORT}"
}

# ── 2. LiteLLM Proxy (API token + multi-provider: Ollama / Claude / Gemini) ──
phase_litellm() {
  info "Phase 2: LiteLLM Proxy — API token + multi-backend :${LITELLM_PORT}"
  MASTER_KEY="${LITELLM_MASTER_KEY:-sk-lca-$(openssl rand -hex 12)}"
  mkdir -p "$HOME/.lca"
  cat > "$HOME/.lca/litellm.yaml" <<YAML
model_list:
  - model_name: ollama/default
    litellm_params:
      model: ollama/qwen2.5-coder:1.5b
      api_base: http://host.docker.internal:${OLLAMA_PORT}
  - model_name: claude-haiku
    litellm_params:
      model: claude-3-haiku-20240307
      api_key: "os.environ/ANTHROPIC_API_KEY"
  - model_name: gemini-flash
    litellm_params:
      model: gemini/gemini-1.5-flash
      api_key: "os.environ/GEMINI_API_KEY"
general_settings:
  master_key: "${MASTER_KEY}"
  database_url: "sqlite:////data/litellm.db"
YAML
  docker rm -f litellm 2>/dev/null || true
  docker run -d --name litellm --restart unless-stopped \
    -p "${LITELLM_PORT}:4000" \
    -v "$HOME/.lca/litellm.yaml:/app/config.yaml:ro" \
    -v "$HOME/.lca:/data" \
    -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
    -e GEMINI_API_KEY="${GEMINI_API_KEY:-}" \
    --add-host=host.docker.internal:host-gateway \
    ghcr.io/berriai/litellm:main-latest \
    --config /app/config.yaml --port 4000
  sudo ufw allow "$LITELLM_PORT"/tcp 2>/dev/null || true
  printf '\nLITELLM_MASTER_KEY=%s\n' "$MASTER_KEY" >> "$HOME/.lca/.env"
  ok "LiteLLM: http://localhost:${LITELLM_PORT}  key=${MASTER_KEY}"
}

# ── 3. Open WebUI ─────────────────────────────────────────────────────────────
phase_webui() {
  info "Phase 3: Open WebUI — :${WEBUI_PORT}"
  LLM_KEY=$(grep LITELLM_MASTER_KEY "$HOME/.lca/.env" 2>/dev/null | cut -d= -f2 || echo "sk-lca-local")
  docker rm -f open-webui 2>/dev/null || true
  docker run -d --name open-webui --restart unless-stopped \
    -p "${WEBUI_PORT}:8080" \
    -v open-webui:/app/backend/data \
    -e OLLAMA_BASE_URL="http://${MASTER_IP}:${OLLAMA_PORT}" \
    -e OPENAI_API_BASE_URL="http://host.docker.internal:${LITELLM_PORT}/v1" \
    -e OPENAI_API_KEY="$LLM_KEY" \
    --add-host=host.docker.internal:host-gateway \
    ghcr.io/open-webui/open-webui:main
  sudo ufw allow "$WEBUI_PORT"/tcp 2>/dev/null || true
  ok "Open WebUI: http://${MASTER_IP}:${WEBUI_PORT}"
}

# ── 4. Cloudflare Tunnel (เปิด HTTPS สาธารณะ ไม่ต้อง login) ─────────────────
phase_tunnel() {
  info "Phase 4: Cloudflare Tunnel → https://*.trycloudflare.com"
  if ! command -v cloudflared &>/dev/null; then
    curl -fsSL -o /usr/local/bin/cloudflared \
      https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
    chmod +x /usr/local/bin/cloudflared
  fi
  pkill cloudflared 2>/dev/null || true
  nohup cloudflared tunnel --url "http://localhost:${WEBUI_PORT}" \
    > /tmp/cf-tunnel.log 2>&1 &
  sleep 4
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/cf-tunnel.log | head -1)
  ok "Tunnel URL: ${URL:-ดู /tmp/cf-tunnel.log}"
}

# ── 5. Verify — ตรวจทุก service ──────────────────────────────────────────────
phase_verify() {
  info "Phase 5: Verify services"
  local pass=0 fail=0
  _check() {
    if curl -sf --max-time 3 "$2" >/dev/null 2>&1; then ok "$1"; (( pass++ )); else err "$1 — ไม่ตอบ: $2"; (( fail++ )); fi
  }
  _check "Ollama      :${OLLAMA_PORT}" "http://localhost:${OLLAMA_PORT}/api/version"
  _check "LiteLLM     :${LITELLM_PORT}" "http://localhost:${LITELLM_PORT}/health"
  _check "Open WebUI  :${WEBUI_PORT}" "http://localhost:${WEBUI_PORT}"
  _check "LCA Server  :${LCA_PORT}" "http://localhost:${LCA_PORT}/api/version"
  echo ""
  [[ $fail -eq 0 ]] && ok "ทุก service พร้อม ($pass/4)" || err "$fail service ยังไม่พร้อม"
  return $fail
}

# ── Main ──────────────────────────────────────────────────────────────────────
case "${1:-all}" in
  --verify) phase_verify ;;
  --worker) phase_ollama ;;
  --tunnel) phase_tunnel ;;
  --stop)
    docker stop open-webui litellm 2>/dev/null || true
    sudo systemctl stop ollama
    pkill cloudflared 2>/dev/null || true
    ok "Services stopped" ;;
  all)
    phase_ollama
    phase_litellm
    phase_webui
    [[ "${2:-}" == "--tunnel" ]] && phase_tunnel
    phase_verify ;;
  *) echo "Usage: $0 [all [--tunnel] | --verify | --stop | --worker | --tunnel]" ;;
esac
