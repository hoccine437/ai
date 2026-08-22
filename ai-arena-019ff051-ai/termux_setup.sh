#!/usr/bin/env bash
# ZERION-X — Termux bootstrap.
# Run inside Termux, from the repo root (ai-arena-019ff051-ai/).
# The core runtime is pure Python 3.9+ standard library: it runs with ZERO
# third-party packages. This script installs the optional provider dep
# (httpx — pure Python; the openai SDK is intentionally not installed because
# its jiter dependency has no Termux/Android aarch64 wheel) plus termux-api
# for mic/TTS, then verifies the engine and the full test suite.
set -e

cd "$(dirname "$0")"

echo "[1/3] Installing base Termux packages..."
pkg update -y
# termux-api enables termux-microphone-record (mic) and termux-tts-speak (TTS).
pkg install -y python termux-api

echo "[2/3] Installing pinned Python deps from requirements.txt..."
python3 -m pip install -r requirements.txt

echo "[3/3] Verifying engine import + full test suite..."
python3 -c "from zerion.engine import AscendantEngine; print('engine import OK')"
python3 -m unittest discover -s tests -p 'test_*.py'

cat <<'EOF'

ZERION-X ready on Termux. Next steps:

  # Web UI (accessible from the same device at http://localhost:8080)
  python3 main.py --ui --port 8080

  # Always-available voice perception daemon (needs termux-api for the mic)
  python3 main.py --voice

  # One autonomous developmental cycle
  python3 main.py --cycles 1

Optional (not required for the core):
  - Local GGUF inference: `pkg install llama-cpp` (prebuilt llama-cli; never
    pip install llama-cpp-python on Termux — no Android aarch64 wheels, and
    pip's cmake source build fails on iconv). Then drop .gguf files into
    models/ and run `python3 main.py --models` to verify discovery.
  - Local STT: install whisper.cpp / vosk via pkg or build; the runtime
    auto-detects them on PATH (see zerion/voice/providers.py).
  - OpenAI/Gemini providers: copy .env.example to .env and set your keys.
  - numpy for audio processing: use `pkg install python-numpy` (pip wheels for
    numpy do not build reliably on Termux); sounddevice is not needed for the
    core or for termux-api-based mic capture.
EOF
