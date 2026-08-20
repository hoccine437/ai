#!/bin/sh
# ZERION-X ASCENDANT — Startup Script
# Starts both the Python cognitive backend and the Next.js phone UI.
#
# Usage:
#   sh ./start.sh              # Start both backend + UI
#   sh ./start.sh --backend    # Start backend only (interactive CLI)
#   sh ./start.sh --ui         # Start UI only (Next.js dev server)
#
# On Android/Termux, the UI is accessible at http://localhost:3000
# The backend runs on port 8080.

set -e

BACKEND_PORT="${BACKEND_PORT:-8080}"
UI_PORT="${UI_PORT:-3000}"

cd "$(dirname "$0")"

case "${1:-}" in
  --backend)
    echo "[ZERION] Starting backend only on port $BACKEND_PORT..."
    exec python3 main.py --ui --port "$BACKEND_PORT"
    ;;
  --ui)
    echo "[ZERION] Starting UI only on port $UI_PORT..."
    cd ZERION-UI-main
    exec npx next dev --port "$UI_PORT" --hostname 0.0.0.0
    ;;
  *)
    echo "╔══════════════════════════════════════════╗"
    echo "║     ZERION-X ASCENDANT — Launching       ║"
    echo "╠══════════════════════════════════════════╣"
    echo "║  Backend: http://localhost:$BACKEND_PORT          ║"
    echo "║  UI:      http://localhost:$UI_PORT            ║"
    echo "║                                          ║"
    echo "║  Open http://localhost:$UI_PORT on your    ║"
    echo "║  phone browser to use ZERION.            ║"
    echo "╚══════════════════════════════════════════╝"
    echo ""

    # Start the Python backend in background
    echo "[ZERION] Starting Python backend on port $BACKEND_PORT..."
    python3 main.py --ui --port "$BACKEND_PORT" &
    BACKEND_PID=$!

    # Wait for backend to be ready (check every 2 seconds, max 30s)
    echo "[ZERION] Waiting for backend to be ready..."
    READY=0
    for i in $(seq 1 15); do
      if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$BACKEND_PORT/')" 2>/dev/null; then
        READY=1
        break
      fi
      sleep 2
    done

    if [ "$READY" = "1" ]; then
      echo "[ZERION] Backend is ready."
    else
      echo "[ZERION] Backend may still be starting up. Continuing anyway..."
    fi

    # Start the Next.js UI in foreground
    echo "[ZERION] Starting Next.js UI on port $UI_PORT..."
    cd ZERION-UI-main
    npx next dev --port "$UI_PORT" --hostname 0.0.0.0 &
    UI_PID=$!

    echo ""
    echo "[ZERION] Both services started."
    echo "  Backend PID: $BACKEND_PID"
    echo "  UI PID:      $UI_PID"
    echo ""
    echo "  Open http://localhost:$UI_PORT in your phone browser."
    echo "  Press Ctrl+C to stop both."
    echo ""

    # Trap Ctrl+C to kill both
    trap "kill $BACKEND_PID $UI_PID 2>/dev/null; echo '[ZERION] Stopped.'; exit 0" INT TERM

    # Wait for either to exit
    wait
    ;;
esac
