#!/usr/bin/env zsh
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🛑 Stopping Personal Knowledge Bot — WhatsApp stack..."

for service in whatsapp_api whatsapp_worker whatsapp_gateway; do
  PID_FILE="$ROOT/.pid_${service}"
  if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      kill "$PID" && echo "  ✓ ${service} stopped (PID $PID)"
    else
      echo "  ↩  ${service} was not running"
    fi
    rm -f "$PID_FILE"
  fi
done

pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "arq app.queue.worker.WorkerSettings" 2>/dev/null || true
pkill -f "whatsapp_gateway/index.js" 2>/dev/null || true

echo "  → Stopping Docker services..."
docker compose -f "$ROOT/docker-compose.yml" down

echo "  ✓ WhatsApp stack stopped."
