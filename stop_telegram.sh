#!/usr/bin/env zsh
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🛑 Stopping Personal Knowledge Bot — Telegram stack..."

for service in telegram_api telegram_worker telegram_gateway; do
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

pkill -f "uvicorn app.main_telegram:app" 2>/dev/null || true
pkill -f "arq app.queue.worker_telegram.WorkerTelegramSettings" 2>/dev/null || true
pkill -f "telegram_gateway/index.js" 2>/dev/null || true

echo "  → Stopping Docker services..."
docker compose -f "$ROOT/docker-compose.yml" down

echo "  ✓ Telegram stack stopped."
