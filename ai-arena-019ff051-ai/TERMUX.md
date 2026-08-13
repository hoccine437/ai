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
python3 -m pip install -r requirements.txt    # openai, httpx (both pure Python)
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
| OpenAI provider | `.env` with `OPENAI_API_KEY` | Uses `httpx` directly; `openai` is pinned for declared parity but not imported by the runtime. |
| numpy (audio processing) | `pkg install python-numpy` | **Do not** `pip install numpy` on Termux — no Android aarch64 wheels; pip will try to compile. It is opt-in (`audio` extra) and not needed for the core or for termux-api mic capture. |
| llama.cpp GGUF | build locally (`pkg`/compile) | Opt-in `local_llm` extra; heavy on mobile, use `OFFLINE_ONLY` with deterministic engines otherwise. |

## Pinned dependencies (2026-08-13)

`requirements.txt` / `requirements-dev.txt` / `setup.py` / `pyproject.toml`
are pinned to exact versions that **all support Python 3.9** — the pinned
`openai==2.48.0` and `httpx==0.28.1` are pure-Python wheels, installable on
Termux without a compiler.

## Verification status (honest)

- ✅ Verified in this repository: full regression suite **686 tests OK**
  (2 skipped) on Linux; engine boot + live developmental cycle + UI snapshot
  with `openai`/`httpx`/`numpy`/`sounddevice`/`llama-cpp` imports **blocked**
  (simulates a fresh Termux box with nothing installed).
- ⚠️ Not verified: real on-device Termux execution. The `TERMUX` platform
  branch (`VoiceEnvironment.detect_platform`, `TermuxAdapter`,
  `resources.is_termux`) is exercised only by code inspection here — mic
  capture and TTS have **not** been tested on an actual Android/Termux device.
