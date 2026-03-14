#!/usr/bin/env zsh
# ─── Personal Knowledge Bot — Stop ────────────────────────────────────────────

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🛑 Stopping Personal Knowledge Bot..."

# ── Kill tracked PIDs ─────────────────────────────────────────────────────────
for service in api worker gateway; do
  PID_FILE="$ROOT/.pid_$service"
  if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      kill "$PID" && echo "  ✓ $service stopped (PID $PID)"
    else
      echo "  ↩  $service was not running"
    fi
    rm -f "$PID_FILE"
  fi
done

# ── Kill any stragglers by name ───────────────────────────────────────────────
pkill -f "uvicorn app.main:app"  2>/dev/null || true
pkill -f "arq app.queue.worker.WorkerSettings" 2>/dev/null || true
pkill -f "node index.js" 2>/dev/null || true

# ── Stop Docker services ──────────────────────────────────────────────────────
echo "  → Stopping Docker services..."
docker compose -f "$ROOT/docker-compose.yml" down
echo "  ✓ Postgres + Redis stopped"

echo ""
echo "  All services stopped."
