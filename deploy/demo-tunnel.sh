#!/bin/bash
# Share the single-container demo from your own machine through a free Cloudflare quick tunnel.
#   deploy/demo-tunnel.sh        starts the container and the tunnel, prints the public URL
#   deploy/demo-tunnel.sh stop   stops both
# The URL only works while this machine, Docker and the tunnel are running, and it changes every run.
# Needs: Docker, cloudflared (brew install cloudflared), and GROQ_API_KEY in .env (or the environment).
set -euo pipefail
cd "$(dirname "$0")/.."
LOG=/tmp/copilot-tunnel.log
if [ "${1:-}" = "stop" ]; then
  pkill -f "cloudflared tunnel --url http://localhost:7860" 2>/dev/null || true
  docker rm -f copilot-space > /dev/null 2>&1 || true
  echo "stopped"; exit 0
fi
KEY=${GROQ_API_KEY:-$(grep -E '^GROQ_API_KEY=' .env 2>/dev/null | cut -d= -f2- || true)}
[ -n "$KEY" ] || KEY=$(grep -E '^LLM_API_KEY=' .env 2>/dev/null | cut -d= -f2- || true)
[ -n "$KEY" ] || { echo "Set GROQ_API_KEY in .env first"; exit 1; }
docker info > /dev/null 2>&1 || { echo "Docker is not running: start Docker Desktop first"; exit 1; }
docker image inspect copilot-space > /dev/null 2>&1 || {
  deploy/hf-space/build_space.sh /tmp/copilot-space && docker build -t copilot-space /tmp/copilot-space; }
docker rm -f copilot-space > /dev/null 2>&1 || true
docker run -d --name copilot-space -p 127.0.0.1:7860:7860 -e GROQ_API_KEY="$KEY" copilot-space > /dev/null
echo "Starting (first boot takes about a minute)..."
for _ in $(seq 1 90); do curl -sf http://localhost:7860/api/v1/health > /dev/null && break; sleep 3; done
sleep 25  # let the demo workspace seed finish
: > "$LOG"; nohup cloudflared tunnel --url http://localhost:7860 > "$LOG" 2>&1 &
for _ in $(seq 1 30); do URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1 || true); [ -n "${URL:-}" ] && break; sleep 2; done
echo "Public URL: ${URL:-not found, see $LOG}"
echo "Demo logins: demo_technician / demo_supervisor, password Demo-Copilot-2026"
