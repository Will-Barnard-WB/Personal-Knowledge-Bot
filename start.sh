#!/usr/bin/env zsh
# ─── Personal Knowledge Bot — Start ───────────────────────────────────────────
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

echo "🚀 Starting Personal Knowledge Bot..."

# ── 1. Docker (Postgres + Redis) ──────────────────────────────────────────────
echo "  → Starting Docker services..."
DOCKER_LOG="$LOG_DIR/docker.log"
rm -f "$DOCKER_LOG"

set +e
docker compose -f "$ROOT/docker-compose.yml" up -d >"$DOCKER_LOG" 2>&1 &
COMPOSE_PID=$!

COMPOSE_TIMEOUT_SECONDS=90
for ((i=1; i<=COMPOSE_TIMEOUT_SECONDS; i++)); do
  if ! kill -0 "$COMPOSE_PID" 2>/dev/null; then
    break
  fi
  sleep 1
done

if kill -0 "$COMPOSE_PID" 2>/dev/null; then
  kill "$COMPOSE_PID" 2>/dev/null || true
  wait "$COMPOSE_PID" 2>/dev/null || true
  echo "  ✗ Docker compose timed out after ${COMPOSE_TIMEOUT_SECONDS}s"
  echo "    Check Docker Desktop is running and try again."
  echo "    Last Docker output:"
  tail -n 20 "$DOCKER_LOG" 2>/dev/null || true
  exit 1
fi

wait "$COMPOSE_PID"
COMPOSE_EXIT=$?
set -e

if [[ "$COMPOSE_EXIT" -ne 0 ]]; then
  echo "  ✗ Docker compose failed (exit $COMPOSE_EXIT)"
  echo "    Last Docker output:"
  tail -n 20 "$DOCKER_LOG" 2>/dev/null || true
  exit "$COMPOSE_EXIT"
fi

echo "  ✓ Docker services started"
# Wait until Redis is actually accepting connections
for i in {1..20}; do
  nc -z localhost 6379 2>/dev/null && nc -z localhost 5432 2>/dev/null && break
  sleep 1
done
echo "  ✓ Postgres + Redis ready"

# ── 2. FastAPI ────────────────────────────────────────────────────────────────
echo "  → Starting FastAPI..."
source "$ROOT/.venv/bin/activate"
EXISTING_API_PID=$(pgrep -f "uvicorn app.main:app --host 0.0.0.0 --port 8000" | head -n 1 || true)
if [[ -n "$EXISTING_API_PID" ]]; then
  echo "$EXISTING_API_PID" > "$ROOT/.pid_api"
  echo "  ✓ FastAPI already running (PID $EXISTING_API_PID)"
else
  nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    > "$LOG_DIR/api.log" 2>&1 &
  echo $! > "$ROOT/.pid_api"
  sleep 1
  if ! kill -0 "$(cat "$ROOT/.pid_api")" 2>/dev/null; then
    echo "  ✗ FastAPI failed to start. Last log lines:"
    tail -n 40 "$LOG_DIR/api.log" 2>/dev/null || true
    exit 1
  fi
  echo "  ✓ FastAPI started (PID $(cat "$ROOT/.pid_api")) — logs: logs/api.log"
fi

# ── 3. ARQ Worker ─────────────────────────────────────────────────────────────
echo "  → Starting ARQ worker..."
EXISTING_WORKER_PID=$(pgrep -f "arq app.queue.worker.WorkerSettings" | head -n 1 || true)
if [[ -n "$EXISTING_WORKER_PID" ]]; then
  echo "$EXISTING_WORKER_PID" > "$ROOT/.pid_worker"
  echo "  ✓ ARQ worker already running (PID $EXISTING_WORKER_PID)"
else
  nohup arq app.queue.worker.WorkerSettings \
    > "$LOG_DIR/worker.log" 2>&1 &
  echo $! > "$ROOT/.pid_worker"
  sleep 1
  if ! kill -0 "$(cat "$ROOT/.pid_worker")" 2>/dev/null; then
    echo "  ✗ ARQ worker failed to start. Last log lines:"
    tail -n 40 "$LOG_DIR/worker.log" 2>/dev/null || true
    exit 1
  fi
  echo "  ✓ ARQ worker started (PID $(cat "$ROOT/.pid_worker")) — logs: logs/worker.log"
fi

# ── 4. WhatsApp Gateway ───────────────────────────────────────────────────────
echo "  → Starting WhatsApp gateway..."
EXISTING_GATEWAY_PID=$(lsof -nP -iTCP:3000 -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $2}' || true)
if [[ -n "$EXISTING_GATEWAY_PID" ]]; then
  echo "$EXISTING_GATEWAY_PID" > "$ROOT/.pid_gateway"
  echo "  ✓ Gateway already running (PID $EXISTING_GATEWAY_PID)"
else
  cd "$ROOT/whatsapp_gateway"
  nohup node index.js \
    > "$LOG_DIR/gateway.log" 2>&1 &
  echo $! > "$ROOT/.pid_gateway"
  sleep 1
  if ! kill -0 "$(cat "$ROOT/.pid_gateway")" 2>/dev/null; then
    echo "  ✗ Gateway failed to start. Last log lines:"
    tail -n 60 "$LOG_DIR/gateway.log" 2>/dev/null || true
    exit 1
  fi
  echo "  ✓ Gateway started (PID $(cat "$ROOT/.pid_gateway")) — logs: logs/gateway.log"
fi

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
