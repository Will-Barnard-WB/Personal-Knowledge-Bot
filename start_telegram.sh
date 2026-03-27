#!/usr/bin/env zsh
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

API_PID_FILE="$ROOT/.pid_telegram_api"
WORKER_PID_FILE="$ROOT/.pid_telegram_worker"
GATEWAY_PID_FILE="$ROOT/.pid_telegram_gateway"

API_LOG="$LOG_DIR/api_telegram.log"
WORKER_LOG="$LOG_DIR/worker_telegram.log"
GATEWAY_LOG="$LOG_DIR/telegram_gateway.log"
DOCKER_LOG="$LOG_DIR/docker.log"

API_CMD="uvicorn app.main_telegram:app --host 0.0.0.0 --port 8001"
WORKER_CMD="arq app.queue.worker_telegram.WorkerTelegramSettings"
GATEWAY_PORT="3001"

run_docker() {
  echo "  → Starting Docker services..."
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
    echo "    Last Docker output:"
    tail -n 20 "$DOCKER_LOG" 2>/dev/null || true
    exit 1
  fi
  wait "$COMPOSE_PID"
  COMPOSE_EXIT=$?
  set -e
  if [[ "$COMPOSE_EXIT" -ne 0 ]]; then
    echo "  ✗ Docker compose failed (exit $COMPOSE_EXIT)"
    tail -n 20 "$DOCKER_LOG" 2>/dev/null || true
    exit "$COMPOSE_EXIT"
  fi
  echo "  ✓ Docker services started"
  for i in {1..20}; do
    nc -z localhost 6379 2>/dev/null && nc -z localhost 5432 2>/dev/null && break
    sleep 1
  done
  echo "  ✓ Postgres + Redis ready"
}

start_fastapi() {
  echo "  → Starting Telegram FastAPI stack..."
  source "$ROOT/.venv/bin/activate"
  EXISTING=$(pgrep -f "$API_CMD" | head -n 1 || true)
  if [[ -n "$EXISTING" ]]; then
    echo "$EXISTING" > "$API_PID_FILE"
    echo "  ✓ FastAPI already running (PID $EXISTING)"
    return
  fi
  nohup ${=API_CMD} >"$API_LOG" 2>&1 &
  echo $! > "$API_PID_FILE"
  sleep 1
  if ! kill -0 "$(cat "$API_PID_FILE")" 2>/dev/null; then
    echo "  ✗ FastAPI failed to start. Last lines:"
    tail -n 40 "$API_LOG" 2>/dev/null || true
    exit 1
  fi
  echo "  ✓ FastAPI started (PID $(cat "$API_PID_FILE")) — logs: $API_LOG"
}

start_worker() {
  echo "  → Starting Telegram worker..."
  source "$ROOT/.venv/bin/activate"
  EXISTING=$(pgrep -f "$WORKER_CMD" | head -n 1 || true)
  if [[ -n "$EXISTING" ]]; then
    echo "$EXISTING" > "$WORKER_PID_FILE"
    echo "  ✓ Worker already running (PID $EXISTING)"
    return
  fi
  nohup ${=WORKER_CMD} >"$WORKER_LOG" 2>&1 &
  echo $! > "$WORKER_PID_FILE"
  sleep 1
  if ! kill -0 "$(cat "$WORKER_PID_FILE")" 2>/dev/null; then
    echo "  ✗ Worker failed to start. Last lines:"
    tail -n 40 "$WORKER_LOG" 2>/dev/null || true
    exit 1
  fi
  echo "  ✓ Worker started (PID $(cat "$WORKER_PID_FILE")) — logs: $WORKER_LOG"
}

start_gateway() {
  echo "  → Starting Telegram gateway..."
  EXISTING=$(lsof -nP -iTCP:${GATEWAY_PORT} -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $2}' || true)
  if [[ -n "$EXISTING" ]]; then
    echo "$EXISTING" > "$GATEWAY_PID_FILE"
    echo "  ✓ Gateway already running (PID $EXISTING)"
    return
  fi
  cd "$ROOT/telegram_gateway"
  nohup node index.js >"$GATEWAY_LOG" 2>&1 &
  echo $! > "$GATEWAY_PID_FILE"
  sleep 1
  if ! kill -0 "$(cat "$GATEWAY_PID_FILE")" 2>/dev/null; then
    echo "  ✗ Gateway failed to start. Last lines:"
    tail -n 60 "$GATEWAY_LOG" 2>/dev/null || true
    exit 1
  fi
  echo "  ✓ Gateway started (PID $(cat "$GATEWAY_PID_FILE")) — logs: $GATEWAY_LOG"
}

health_summary() {
  echo "\n  Waiting for services to be healthy..."
  sleep 4
  API_STATUS=$(curl -sf http://localhost:8001/health 2>/dev/null || echo "unreachable")
  GW_STATUS=$(curl -sf http://localhost:${GATEWAY_PORT}/health 2>/dev/null || echo "unreachable")
  echo "\n┌─────────────────────────────────────────┐"
  echo "│  Personal Knowledge Bot — Telegram      │"
  echo "├─────────────────────────────────────────┤"
  printf "│  API:      %-30s│\n" "$API_STATUS"
  printf "│  Gateway:  %-30s│\n" "$GW_STATUS"
  echo "└─────────────────────────────────────────┘"
  echo ""
  echo "  Logs:  tail -f $API_LOG"
  echo "         tail -f $WORKER_LOG"
  echo "         tail -f $GATEWAY_LOG"
  echo ""
  echo "  Stop:  ./stop_telegram.sh"
}

echo "🚀 Starting Personal Knowledge Bot — Telegram stack..."
run_docker
start_fastapi
start_worker
start_gateway
health_summary
