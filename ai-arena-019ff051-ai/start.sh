#!/bin/bash
# ZERION — Web UI launcher (Gemini 3.1 Flash)
# Usage: sh start.sh [port]

set -e
cd "$(dirname "$0")"

PORT="${1:-${PORT:-8080}}"
export GEMINI_API_KEY="${GEMINI_API_KEY:-}"

echo "[ZERION] Starting web interface on port $PORT..."
echo "[ZERION] Model: gemini-3.1-flash"
echo "[ZERION] Tools: 100 | Agents: 21"

exec python3 main.py --port "$PORT"
