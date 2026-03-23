#!/usr/bin/env bash
# ============================================================
# IEEE Paper Search — start both servers
# Run every time you want to use the app:  bash start.sh
# ============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/backend/venv"

if [ ! -d "$VENV_DIR" ]; then
    error "Virtual environment not found. Please run 'bash install.sh' first."
fi

# ── Kill any leftover processes on our ports ──────────────
for PORT in 8000 5173; do
    PID=$(lsof -ti :$PORT 2>/dev/null || true)
    if [ -n "$PID" ]; then
        warn "Port $PORT in use (PID $PID) — stopping it..."
        kill "$PID" 2>/dev/null || true
        sleep 1
    fi
done

# ── Start backend ─────────────────────────────────────────
info "Starting backend (port 8000)..."
source "$VENV_DIR/bin/activate"
cd "$SCRIPT_DIR/backend"
python -m uvicorn main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
deactivate
cd "$SCRIPT_DIR"

# Wait for backend to be ready
echo -n "  Waiting for backend"
for i in $(seq 1 20); do
    if curl -s http://127.0.0.1:8000/health >/dev/null 2>&1; then
        echo ""
        info "Backend ready"
        break
    fi
    echo -n "."
    sleep 0.5
done

# ── Start frontend ────────────────────────────────────────
info "Starting frontend (port 5173)..."
cd "$SCRIPT_DIR/frontend"
npm run dev -- --port 5173 &
FRONTEND_PID=$!
cd "$SCRIPT_DIR"
sleep 2

echo ""
echo -e "${CYAN}=================================================="
echo "  IEEE Paper Search is running!"
echo ""
echo "  Open in your browser:  http://localhost:5173"
echo ""
echo "  Press Ctrl+C to stop both servers."
echo -e "==================================================${NC}"
echo ""

# ── Trap Ctrl+C and cleanly stop both servers ─────────────
cleanup() {
    echo ""
    warn "Stopping servers..."
    kill "$BACKEND_PID"  2>/dev/null || true
    kill "$FRONTEND_PID" 2>/dev/null || true
    # Also kill any child npm/vite processes
    pkill -f "vite" 2>/dev/null || true
    info "Stopped. Goodbye!"
    exit 0
}
trap cleanup INT TERM

# Keep script alive
wait
