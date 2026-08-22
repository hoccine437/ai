# ZERION-X on Termux (Android)

The runtime is designed for ultra-portable execution on Android/Termux: the
**core is pure Python 3.9+ standard library** — no third-party imports at
module level anywhere in `zerion/` (verified by import-graph scan). The only
external dependency used by any code path is a *lazy* `httpx` import inside
`zerion/model_providers/openai_provider.py`, and even that path falls back to
a deterministic local engine when the deps or keys are absent.

## Install

```bash
# from the repo root (ai-arena-019ff051-ai/)
bash termux_setup.sh          # pkg install python termux-api + pip -r requirements.txt + verify
```

or manually:

```bash
pkg install -y python termux-api
python3 -m pip install -r requirements.txt    # httpx (pure Python); the openai SDK is intentionally not installed — see below
```

## What works with zero installs

| Capability | Status on Termux |
| :--- | :--- |
| Cognitive runtime (engine, cycles, memory, benchmarks) | ✅ pure stdlib, verified |
| Web UI (`python3 main.py --ui --port 8080`) | ✅ built-in asyncio server on `0.0.0.0` |
| SQLite-WAL persistence (`data/`) | ✅ stdlib `sqlite3` |
| Voice perception daemon (`--voice`) | ✅ runs; mic requires `termux-api` (see below) |
| Battery/compute tiering | ✅ `zerion/runtime/resources.py` + `zerion/integration/termux_adapter.py` detect Termux and query `termux-battery-status` when present |

## Optional capabilities

| Capability | How | Notes |
| :--- | :--- | :--- |
| Microphone | `termux-api` + `termux-microphone-record` | The runtime detects the `TERMUX` platform and reports an honest `MIC_OFF` + reason when termux-api is missing (never fakes listening). |
| TTS | `termux-api` → `termux-tts-speak` | Auto-detected on PATH (`zerion/voice/providers.py`). |
| Local STT | whisper.cpp / vosk / openai-whisper on PATH | Binary presence is detected, never assumed. |
| OpenAI provider | `.env` with `OPENAI_API_KEY` | Uses `httpx` directly (never the `openai` SDK, which is not installed on Termux — see “Pinned dependencies” below). |
| numpy (audio processing) | `pkg install python-numpy` | **Do not** `pip install numpy` on Termux — no Android aarch64 wheels; pip will try to compile. It is opt-in (`audio` extra) and not needed for the core or for termux-api mic capture. |
| llama.cpp GGUF | **`pkg install llama-cpp`** (prebuilt `llama-cli`; no compilation) | Real inference is wired into `LocalGGUFProvider`: it auto-detects `llama-cli`/`main` on PATH (Termux) or `llama-cpp-python` (desktop). Models live in `models/*.gguf` (`ai-arena-019ff051-ai/models/`). See “Real local GGUF inference” below. |

## Real local GGUF inference

Drop a `.gguf` file into `models/` — the `ai-arena-019ff051-ai/models/`
folder (any depth — discovery is recursive and validates the GGUF magic
header) and the runtime will detect, register, and route offline requests to
it. The model directory is resolved in this order:

1. `ZERION_MODELS_DIR` env var, if set (absolute or relative path).
2. `models/` next to the runtime — the canonical repo folder
   (`ai-arena-019ff051-ai/models`, a sibling of the `zerion` package).
3. `models/` relative to the current directory (legacy default).

Generation runs through a lazy backend chain:

1. **llama-cpp-python** (desktop/server: `pip install llama-cpp-python`)
2. **llama.cpp CLI** (`llama-cli`, or legacy `main`, on PATH — the Termux path:
   `pkg install llama-cpp`, a prebuilt llama.cpp that provides `llama-cli`)

> **Do NOT `pip install llama-cpp-python` on Termux.** There are no Android
> aarch64 wheels for it or for its `cmake` build dependency, so pip tries to
> compile cmake from source — and cmake's bootstrap fails with
> `iconv is required, but was not found` (this is the exact error a failed
> install leaves behind). On Termux use the prebuilt package instead:
> `pkg install llama-cpp`. If it is not available on your channel, build
> llama.cpp from source per the quick start below. Desktop/server machines
> (x86_64, aarch64 Linux/macOS/Windows) install llama-cpp-python normally.

If neither backend exists the provider returns an honest labeled fallback that
names the missing piece — it never fabricates model text. Tunables (env):
`ZERION_GGUF_BACKEND` (`auto|python|cli|none`), `ZERION_GGUF_THREADS`,
`ZERION_GGUF_CONTEXT` (default 2048), `ZERION_GGUF_MAX_TOKENS` (default 512),
`ZERION_GGUF_TEMPERATURE` (default 0.7), `ZERION_GGUF_TIMEOUT_SECONDS`,
`ZERION_GGUF_PROBE_TIMEOUT`.
Verify discovery with `python3 main.py --models`; if you keep the model
elsewhere, point the runtime at it explicitly:

```bash
ZERION_MODELS_DIR="$HOME/ai-arena-019ff051-ai/models" python3 main.py --models
```

GGUF models are heavy on mobile — prefer small quantizations, and
`OFFLINE_ONLY` + deterministic engines remain the zero-dependency fallback.

## Quick start — run with a local GGUF model (Termux)

```bash
# 1. Install the runtime deps (pure Python; the openai SDK is intentionally
#    not installed — see “Pinned dependencies” below)
python3 -m pip install -r requirements.txt

# 2. Drop your .gguf file(s) into models/ (or set ZERION_MODELS_DIR elsewhere)

# 3. Verify discovery — your model should be listed here
python3 main.py --models

# 4. Install a real inference backend: the llama.cpp CLI. Termux ships a
#    prebuilt package that provides `llama-cli` — no compilation needed.
#    (Never `pip install llama-cpp-python` here: no Android aarch64 wheels,
#    so pip compiles cmake from source and its bootstrap dies with
#    `iconv is required, but was not found`.)
pkg install -y llama-cpp

#    If `llama-cpp` is not on your channel, build llama-cli from source:
#    pkg install -y cmake ninja clang make git
#    cd ~ && git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
#    cmake -B build -DCMAKE_BUILD_TYPE=Release
#    cmake --build build -j2 --target llama-cli
#    cp build/bin/llama-cli "$PREFIX/bin/"
cd ~/ai-arena-019ff051-ai

# 5. Run the web UI (open http://localhost:8080 on the phone)
python3 main.py --ui --port 8080

# 6. In another Termux tab, ask the local model (offline — never touches cloud):
curl -s -X POST http://localhost:8080/api/command \
  -H 'Content-Type: application/json' \
  -d '{"command":"RUN_TASK","payload":{"prompt":"Explain reflection in Python","mode":"OFFLINE_ONLY"}}'
```

- The response’s `provider` should be `local_gguf`; if the backend is missing,
  the response returns an honest error naming the absent piece — never
  fabricated text.
- `python3 main.py --cycles 1` runs the autonomous flywheel with its built-in
  deterministic engines; GGUF inference is exercised through the router
  (`RUN_TASK` with `OFFLINE_ONLY`, or voice/daemon tasks), not the flywheel.
- Tunables: `ZERION_GGUF_BACKEND=cli`, `ZERION_GGUF_THREADS`,
  `ZERION_GGUF_CONTEXT`, `ZERION_GGUF_MAX_TOKENS`, `ZERION_GGUF_TEMPERATURE`,
  `ZERION_GGUF_TIMEOUT_SECONDS`, `ZERION_GGUF_PROBE_TIMEOUT` (the readiness
  probe's load+inference budget in seconds; **unlimited by default** — a
  first model load on a phone can take minutes).

## Pinned dependencies (2026-08-13)

`requirements.txt` / `requirements-dev.txt` / `setup.py` / `pyproject.toml`
are pinned to exact versions that **all support Python 3.9**, and everything
in the default install is pure Python — installable on Termux without a
compiler. The only runtime dependency is `httpx==0.28.1` (the OpenAI provider
calls `api.openai.com` with raw `httpx` and falls back to a deterministic
local engine when no key is set).

The `openai` SDK is deliberately **not** a dependency: the runtime never
imports it, and `openai` (2.x) requires `jiter`, a Rust package with no
prebuilt wheel for Termux/Android aarch64. Pinning it makes
`pip install -r requirements.txt` try to compile Rust on-device and fail with
the `maturin` / `aarch64-unknown-linux-android` build error. Desktop users who
want the SDK for their own scripts can `pip install openai` separately — the
runtime itself does not need it.

## Verification status (honest)

- ✅ Verified in this repository: full regression suite **686 tests OK**
  (2 skipped) on Linux; engine boot + live developmental cycle + UI snapshot
  with `openai`/`httpx`/`numpy`/`sounddevice`/`llama-cpp` imports **blocked**
  (simulates a fresh Termux box with nothing installed).
- ⚠️ Not verified: real on-device Termux execution. The `TERMUX` platform
  branch (`VoiceEnvironment.detect_platform`, `TermuxAdapter`,
  `resources.is_termux`) is exercised only by code inspection here — mic
  capture and TTS have **not** been tested on an actual Android/Termux device.
