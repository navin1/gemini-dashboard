#!/usr/bin/env bash
# dev.sh — setup, start, and stop the Gemini Dashboard locally
# Usage: ./dev.sh [setup|start|stop|restart|status]

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$PROJECT_ROOT/.venv"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
PID_FILE="$PROJECT_ROOT/.dev.pids"
LOG_DIR="$PROJECT_ROOT/.logs"
BACKEND_PORT=8000
FRONTEND_PORT=5173

# ── helpers ──────────────────────────────────────────────────────────────────

log()  { printf '\033[1;34m[dev]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[ ✓ ]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[err]\033[0m %s\n' "$*" >&2; exit 1; }

port_in_use() { lsof -iTCP:"$1" -sTCP:LISTEN -t &>/dev/null; }

kill_port() {
  local port=$1
  local pids
  pids=$(lsof -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    warn "Port $port is busy — killing PIDs: $pids"
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 0.5
  fi
}

# ── setup ─────────────────────────────────────────────────────────────────────

cmd_setup() {
  log "Running first-time setup..."

  # .env check
  if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    if [[ -f "$PROJECT_ROOT/.env.example" ]]; then
      cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
      warn ".env not found — copied from .env.example. Fill in your credentials before starting."
    else
      die ".env not found and no .env.example to copy. Create .env manually."
    fi
  else
    ok ".env exists"
  fi

  # Python virtual environment
  if [[ ! -d "$VENV" ]]; then
    log "Creating Python virtual environment at .venv ..."
    python3 -m venv "$VENV"
  else
    ok "Virtual environment already exists"
  fi

  # Python dependencies
  log "Installing Python dependencies..."
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$BACKEND_DIR/requirements.txt"
  ok "Python dependencies installed"

  # Playwright Chromium (needed for PDF export)
  log "Installing Playwright Chromium..."
  "$VENV/bin/playwright" install chromium
  ok "Playwright Chromium installed"

  # Node dependencies
  log "Installing Node.js dependencies..."
  (cd "$FRONTEND_DIR" && npm install --silent)
  ok "Node dependencies installed"

  # Runtime directories
  mkdir -p "$PROJECT_ROOT/data"
  ok "Runtime directories ready"

  log ""
  ok "Setup complete. Run './dev.sh start' to launch the app."
}

# ── start ─────────────────────────────────────────────────────────────────────

cmd_start() {
  # Prereqs
  [[ -f "$PROJECT_ROOT/.env" ]] || die ".env missing — run './dev.sh setup' first."
  [[ -d "$VENV" ]]              || die "Virtual env missing — run './dev.sh setup' first."
  [[ -d "$FRONTEND_DIR/node_modules" ]] || die "node_modules missing — run './dev.sh setup' first."

  # Already running?
  if [[ -f "$PID_FILE" ]]; then
    warn "PID file exists — servers may already be running. Run './dev.sh status' or './dev.sh stop' first."
    exit 1
  fi

  # Free up ports
  kill_port "$BACKEND_PORT"
  kill_port "$FRONTEND_PORT"

  mkdir -p "$LOG_DIR"

  # Start backend
  log "Starting backend on port $BACKEND_PORT ..."
  (
    cd "$BACKEND_DIR"
    PYTHONPATH="$BACKEND_DIR" \
    "$VENV/bin/uvicorn" main:app --reload --port "$BACKEND_PORT" \
      --log-level "${UVICORN_LOG_LEVEL:-info}" \
      >> "$LOG_DIR/backend.log" 2>&1
  ) &
  BACKEND_PID=$!

  # Wait for backend to be ready (up to 15 s)
  log "Waiting for backend to come up..."
  for i in $(seq 1 30); do
    if curl -sf "http://localhost:$BACKEND_PORT/api/health" &>/dev/null; then
      ok "Backend is up (PID $BACKEND_PID)"
      break
    fi
    sleep 0.5
    if [[ $i -eq 30 ]]; then
      warn "Backend didn't respond after 15 s. Check $LOG_DIR/backend.log"
    fi
  done

  # Start frontend
  log "Starting frontend on port $FRONTEND_PORT ..."
  (
    cd "$FRONTEND_DIR"
    npm run dev -- --port "$FRONTEND_PORT" \
      >> "$LOG_DIR/frontend.log" 2>&1
  ) &
  FRONTEND_PID=$!

  # Save PIDs
  echo "BACKEND_PID=$BACKEND_PID" > "$PID_FILE"
  echo "FRONTEND_PID=$FRONTEND_PID" >> "$PID_FILE"

  # Wait for Vite (up to 10 s)
  log "Waiting for frontend to come up..."
  for i in $(seq 1 20); do
    if curl -sf "http://localhost:$FRONTEND_PORT" &>/dev/null; then
      ok "Frontend is up (PID $FRONTEND_PID)"
      break
    fi
    sleep 0.5
    if [[ $i -eq 20 ]]; then
      warn "Frontend didn't respond after 10 s. Check $LOG_DIR/frontend.log"
    fi
  done

  echo ""
  ok "Dashboard running:"
  printf "   App     → \033[1;36mhttp://localhost:%s\033[0m\n" "$FRONTEND_PORT"
  printf "   API     → \033[1;36mhttp://localhost:%s\033[0m\n" "$BACKEND_PORT"
  printf "   API docs→ \033[1;36mhttp://localhost:%s/docs\033[0m\n" "$BACKEND_PORT"
  echo ""
  log "Logs: $LOG_DIR/"
  log "Stop with: ./dev.sh stop"
}

# ── stop ──────────────────────────────────────────────────────────────────────

cmd_stop() {
  if [[ ! -f "$PID_FILE" ]]; then
    warn "No PID file found — servers may not be running."
    # Try to kill by port anyway
    kill_port "$BACKEND_PORT"
    kill_port "$FRONTEND_PORT"
    return
  fi

  source "$PID_FILE"

  if [[ -n "${BACKEND_PID:-}" ]]; then
    log "Stopping backend (PID $BACKEND_PID)..."
    kill "$BACKEND_PID" 2>/dev/null && ok "Backend stopped" || warn "Backend PID $BACKEND_PID not found"
  fi

  if [[ -n "${FRONTEND_PID:-}" ]]; then
    log "Stopping frontend (PID $FRONTEND_PID)..."
    kill "$FRONTEND_PID" 2>/dev/null && ok "Frontend stopped" || warn "Frontend PID $FRONTEND_PID not found"
  fi

  # Also clean up any orphaned port listeners
  kill_port "$BACKEND_PORT"
  kill_port "$FRONTEND_PORT"

  rm -f "$PID_FILE"
  ok "All servers stopped."
}

# ── restart ───────────────────────────────────────────────────────────────────

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

# ── status ────────────────────────────────────────────────────────────────────

cmd_status() {
  echo ""
  if port_in_use "$BACKEND_PORT"; then
    ok "Backend  is running on port $BACKEND_PORT"
  else
    warn "Backend  is NOT running (port $BACKEND_PORT is free)"
  fi

  if port_in_use "$FRONTEND_PORT"; then
    ok "Frontend is running on port $FRONTEND_PORT"
  else
    warn "Frontend is NOT running (port $FRONTEND_PORT is free)"
  fi

  if [[ -f "$PID_FILE" ]]; then
    echo ""
    log "PID file contents:"
    cat "$PID_FILE"
  fi
  echo ""
}

# ── dispatch ──────────────────────────────────────────────────────────────────

CMD="${1:-help}"

case "$CMD" in
  setup)   cmd_setup   ;;
  start)   cmd_start   ;;
  stop)    cmd_stop    ;;
  restart) cmd_restart ;;
  status)  cmd_status  ;;
  *)
    echo ""
    echo "Usage: ./dev.sh <command>"
    echo ""
    echo "Commands:"
    echo "  setup    — install all dependencies (run once)"
    echo "  start    — free ports, then start backend + frontend"
    echo "  stop     — stop both servers"
    echo "  restart  — stop then start"
    echo "  status   — check if servers are running"
    echo ""
    ;;
esac
