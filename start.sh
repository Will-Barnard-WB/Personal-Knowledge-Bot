#!/usr/bin/env zsh
# ─── Personal Knowledge Bot — Start ───────────────────────────────────────────
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

echo "🚀 Starting Personal Knowledge Bot..."

# ── 1. Docker (Postgres + Redis) ──────────────────────────────────────────────
echo "  → Starting Docker services..."
docker compose -f "$ROOT/docker-compose.yml" up -d
# Wait until Redis is actually accepting connections
for i in {1..20}; do
  nc -z localhost 6379 2>/dev/null && nc -z localhost 5432 2>/dev/null && break
  sleep 1
done
echo "  ✓ Postgres + Redis ready"

# ── 2. FastAPI ────────────────────────────────────────────────────────────────
echo "  → Starting FastAPI..."
source "$ROOT/.venv/bin/activate"
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  > "$LOG_DIR/api.log" 2>&1 &
echo $! > "$ROOT/.pid_api"
echo "  ✓ FastAPI started (PID $(cat "$ROOT/.pid_api")) — logs: logs/api.log"

# ── 3. ARQ Worker ─────────────────────────────────────────────────────────────
echo "  → Starting ARQ worker..."
nohup arq app.queue.worker.WorkerSettings \
  > "$LOG_DIR/worker.log" 2>&1 &
echo $! > "$ROOT/.pid_worker"
echo "  ✓ ARQ worker started (PID $(cat "$ROOT/.pid_worker")) — logs: logs/worker.log"

# ── 4. WhatsApp Gateway ───────────────────────────────────────────────────────
echo "  → Starting WhatsApp gateway..."
cd "$ROOT/whatsapp_gateway"
nohup node index.js \
  > "$LOG_DIR/gateway.log" 2>&1 &
echo $! > "$ROOT/.pid_gateway"
echo "  ✓ Gateway started (PID $(cat "$ROOT/.pid_gateway")) — logs: logs/gateway.log"

# ── 5. Health check ───────────────────────────────────────────────────────────
echo ""
echo "  Waiting for services to be healthy..."
sleep 4

API_STATUS=$(curl -sf http://localhost:8000/health 2>/dev/null || echo "unreachable")
GW_STATUS=$(curl -sf http://localhost:3000/health 2>/dev/null || echo "unreachable")

echo ""
echo "┌─────────────────────────────────────────┐"
echo "│  Personal Knowledge Bot — Status         │"
echo "├─────────────────────────────────────────┤"
printf "│  API:      %-30s│\n" "$API_STATUS"
printf "│  Gateway:  %-30s│\n" "$GW_STATUS"
echo "└─────────────────────────────────────────┘"
echo ""
echo "  Logs:  tail -f $LOG_DIR/api.log"
echo "         tail -f $LOG_DIR/worker.log"
echo "         tail -f $LOG_DIR/gateway.log"
echo ""
echo "  Stop:  ./stop.sh"
