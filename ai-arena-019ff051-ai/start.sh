#!/bin/bash
# ZERION — Web UI launcher (Gemini primary)
# Usage: sh start.sh [port]
# Launches the MASTER ENTRYPOINT main2.py (single central runtime).

set -e
cd "$(dirname "$0")"

PORT="${1:-${PORT:-8080}}"
export GEMINI_API_KEY="${GEMINI_API_KEY:-}"

echo "[ZERION] Starting central runtime (main2.py) on port $PORT..."
echo "[ZERION] Model: gemini-2.5-flash"
echo "[ZERION] Tools: 100 | Agents: 21"

exec python3 main2.py --port "$PORT"
