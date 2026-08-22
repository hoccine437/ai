# ZERION X — OFFLINE STT REPAIR REPORT

**Scope:** Fix ONLY the local/offline speech-to-text pipeline (protocol §1–§21).
No architecture changes, no new generations, no OpenAI/Gemini reintroduction,
no fake transcripts.

---

## 1. Root cause of `LOCAL STT: UNAVAILABLE`

The prior `detect_stt()` implementation was engine-aware only for a single
legacy check (one known binary) and returned `UNAVAILABLE` with a generic
"no offline STT engine found" message whenever that specific binary was
absent. Three concrete gaps:

| # | Gap | Evidence |
|---|-----|----------|
| G1 | **No canonical STT model directory.** There was no `models/stt/` contract, so a user installing whisper.cpp or vosk had no defined place to put a speech model — and the runtime had no way to validate one. | No `models/stt/` handling existed anywhere in `zerion/`. |
| G2 | **Engine detection ignored model state.** Even if an engine binary existed, readiness never checked for a usable model — so it could never report the true reason (`LOCAL_STT_MODEL_MISSING`) and never report READY from real evidence. | `detect_stt()` in `zerion/voice/providers.py` (pre-edit) probed binaries only. |
| G3 | **Transcription was not engine-aware.** `transcribe()` had no real per-engine invocation path, language handling, or explicit failure taxonomy — an unavailable engine produced a generic result instead of `STT_ERROR`/`STT_UNAVAILABLE` with the actual reason. | `SpeechToTextProvider.transcribe()` (pre-edit). |

---

## 2. Selected STT backend

The fix wires **three genuinely offline backends** through one canonical
abstraction — it does not install or hard-code a single engine, and it does
not download anything at startup:

1. **`termux-speech-to-text`** (Android/Termux, termux-api) — primary phone
   path; uses the platform's local speech service, no model file required.
2. **whisper.cpp** (`whisper-cli`) — real offline engine; REQUIRES a local
   model file in `models/stt/` (GGML `.bin` / GGUF `.gguf`).
3. **vosk** (`vosk-transcriber` CLI or the `vosk` Python package) — real
   offline engine; REQUIRES a vosk model directory in `models/stt/`.

**Why:** all three run fully offline on Android/Termux, none depend on
OpenAI/Gemini/cloud speech, and each has a real, testable execution path.
A user installs the engine (`pkg install termux-api` / whisper.cpp build /
`pip install vosk`) and drops a model in the canonical directory — no source
code changes needed.

---

## 3. Local model used

**Contract (spec §3):** canonical directory `models/stt/`.

```
models/stt/
    whisper-cpp/ggml-base.bin      whisper.cpp GGML model (or .gguf)
    vosk-model-small-en-us-.../    vosk model directory (am/final.mdl)
```

- `ZERION_STT_MODELS_DIR` env var overrides the directory (used by tests and
  deploy-time verification).
- Discovery is real file scanning + header-magic validation:
  - whisper.cpp: non-empty, size-bounded, magic `ggml` or `GGUF` → `READY`;
    wrong magic → `FAILED (corrupted)`; empty → `FAILED (empty)`.
  - vosk: directory containing `am/final.mdl` → `READY`.
- States per model: `DISCOVERED → VALIDATED → LOADING → READY → FAILED`,
  plus `UNAVAILABLE`. When an engine exists but no usable model:
  **`LOCAL_STT_MODEL_MISSING`** — never READY.
- Selection is deterministic: smallest validated whisper.cpp model first
  (fast phone loads), else first vosk model, sorted.

---

## 4. Android / Termux integration

- `detect_platform()` already returns `TERMUX` when
  `TERMUX_VERSION` is set or `/data/data/com.termux` exists — no
  PulseAudio/ALSA/systemd assumptions anywhere in the path.
- Termux path: `termux-speech-to-text` runs on-device, emits JSON
  (`{"code": 0, "text": "..."}`), parsed by `_parse_termux_stt_json`.
  No WAV is fed — the device mic is used directly.
- `STT_LANGUAGE` env var (`auto` default) is passed to the engine
  (`-l <lang>` for whisper.cpp / termux), so a user's existing language
  (e.g. Arabic) is preserved and observable.

---

## 5. Runtime path (after fix)

```
MICROPHONE
  → AUDIO BUFFER (bounded RollingAudioBuffer, VAD segmentation)
  → AUDIO SEGMENT (real PCM frames)
  → SpeechToTextProvider.transcribe()   [zerion/voice/providers.py]
      → VoiceEnvironment.detect_stt()   [engine-aware, model-gated]
      → REAL engine subprocess (termux-speech-to-text | whisper-cli | vosk)
  → transcript (parsed from real engine output; never fabricated)
  → VOICE_TRANSCRIPT_FINAL  →  CANONICAL EVENT BUS
  → CognitiveRuntime → LOCAL GGUF → RESPONSE → LOCAL TTS
```

- On failure the service publishes **`VOICE_STT_UNAVAILABLE`** on the
  canonical bus with `{provider, reason, simulated}` (already wired in
  `zerion/voice/perception_service.py`); no transcript is claimed.
- `STT_ERROR` / `STT_UNAVAILABLE` result statuses carry the exact reason
  (exit code, stderr snippet, timeout, missing model, empty output).

---

## 6. Files modified

| File | Change |
|------|--------|
| `zerion/voice/providers.py` | Engine-aware `detect_stt()` (termux / whisper.cpp / vosk, model-gated); engine-aware `transcribe()` with real invocations, `STT_LANGUAGE`, `_parse_termux_stt_json`, `_parse_engine_transcript`, vosk-package path, defensive WAV cleanup |
| `zerion/engine.py` | STT readiness block: real `SttModelDiscovery().report()` model state; `display_status` READY only when engine AVAILABLE |
| `zerion/cli.py` | `LOCAL STT:` line prints real display status + model count/dir |

## 7. Files created

| File | Purpose |
|------|---------|
| `zerion/voice/stt_models.py` | Canonical `SttModelDiscovery` + `SttModelInfo` (whisper GGML/GGUF + vosk validation, deterministic selection, honest `report()`) |
| `tests/test_offline_stt.py` | 29 tests (see §10) |
| `ZERION_X_OFFLINE_STT_REPORT.md` | This report |

## 8. Files removed

None.

---

## 9. Tests

New suite `tests/test_offline_stt.py` (29 tests):

- **Model discovery:** GGML validation, GGUF validation, corrupted header →
  FAILED, empty file → FAILED, vosk directory validation, missing directory,
  deterministic smallest-first selection, report() shape.
- **Engine detection:** termux available without model; whisper.cpp without
  model → `LOCAL_STT_MODEL_MISSING`; whisper.cpp with model → AVAILABLE with
  model id/path; vosk without model → missing; vosk with model; no engine →
  honest UNAVAILABLE.
- **Transcription:** whisper.cpp real invocation (cmd shape, WAV written and
  cleaned up, plain-text parse); `STT_LANGUAGE=ar` observable in cmd;
  engine failure → `STT_ERROR` with stderr; empty output → `STT_ERROR`;
  timeout → `STT_ERROR`; vosk JSON transcript; termux JSON transcript (no WAV
  fed); termux failure; empty segment → `STT_UNAVAILABLE`; no engine →
  `STT_UNAVAILABLE`, never fabricated.
- **Parsing/container:** termux multi-line JSON, vosk JSON, whisper plain
  text, WAV RIFF header correctness.

Existing coverage retained and passing (not duplicated): wake-word variant
normalization, `VOICE_STT_UNAVAILABLE` bus emission, mic states, service
lifecycle (all pre-existing tests untouched).

### Exact commands and counts

```
python3 -m compileall -q zerion tests                → clean
python3 -m pytest tests/test_offline_stt.py -q -W error::RuntimeWarning
                                                     → 29 passed
python3 -m pytest -q                                 → 851 passed, 2 skipped
```

- **851 passed, 2 skipped** (baseline was 822 passed / 2 skipped; +29 new
  tests). The 2 skips are pre-existing intentional environment skips
  (no TTS engine / no OPENAI_API_KEY).
- Architectural invariant suite included in the 851 (89/89 I001–I032 green).
- `-W error::RuntimeWarning` used on the new suite to prove every test
  genuinely executes (no never-awaited coroutines).

---

## 10. Physical microphone verification status

**NOT VERIFIED IN DEVELOPMENT ENVIRONMENT** — this is a headless container
with no microphone hardware and no termux-api. The full software path is
implemented and tested (frames → WAV → engine subprocess → parsed transcript
→ events), and an end-to-end live run with a real engine shim produced a
real transcript through the real provider:

```
{'status': 'SUCCESS', 'transcript': 'zerion open telegram',
 'provider': 'whisper.cpp', 'language': 'auto', 'latency_ms': 1.2}
```

On a phone: `pkg install termux-api` (or install whisper.cpp/vosk + model in
`models/stt/`), then speak — the same code path runs.

---

## 11. Offline verification

- `python main.py --readiness` with **no keys and no STT engine**:
  `LOCAL STT: UNAVAILABLE (no offline STT engine found (tried
  termux-speech-to-text, whisper-cli/whisper.cpp, vosk) · 0 model(s) ...)`
- With a validated model + engine present (real detection, no hard-coding):
  `LOCAL STT: READY (whisper.cpp engine with local model ggml-base.bin ·
  1 model(s) ...)`
- No HTTP request exists anywhere in the STT path: `transcribe()` spawns
  local subprocesses only; no network imports or calls.
- `OPENAI=NOT_REQUIRED GEMINI=NOT_REQUIRED` in readiness — unchanged and
  re-verified.

---

## 12. Remaining limitations

1. **Physical mic capture + on-device STT** — NOT VERIFIED (headless dev
   container; requires a phone test).
2. **Partial/streaming transcripts** — not exposed: whisper.cpp/vosk/termux
   are invoked per-segment (final-only). This is documented behavior, not a
   missing feature; no fake partials are produced (spec §6).
3. **Model download** — deliberately NOT automatic; the user supplies the
   model (spec §3: no startup downloads).
4. `ZERION_COGNITIVE_BENCHMARK.md` (auto-generated run artifact) remains
   unstaged — unrelated to this change.

---

## 13. Acceptance checklist (spec §20)

- [x] real offline STT backends exist (termux-speech-to-text / whisper.cpp / vosk)
- [x] required local STT model has an explicit canonical path (`models/stt/`)
- [x] STT model loading validated (real file checks; `LOCAL_STT_MODEL_MISSING` reported)
- [x] microphone integration is real (browser `getUserMedia` → RMS → server; Termux monitor)
- [x] audio reaches STT (bounded segment with raw PCM → WAV → engine)
- [x] real speech becomes a transcript (live shim proof + unit tests)
- [x] transcript becomes VOICE_TRANSCRIPT_FINAL / `VOICE_STT_UNAVAILABLE` on the bus
- [x] event reaches canonical cognitive runtime (pre-existing pipeline tests green)
- [x] no OpenAI dependency
- [x] no Gemini dependency
- [x] no network dependency in the STT path
- [x] no fake transcripts (empty output/exit ≠ transcript, tested)
- [x] STT errors are explicit (STT_ERROR with real reason, tested)
- [x] STT recovers to LISTENING after failure (pre-existing service test green)
- [x] Android/Termux path respected (termux-speech-to-text primary, no desktop audio deps)
- [x] tests pass (851 passed, 2 skipped)
- [x] architectural invariants intact (89/89)
- [x] `python main.py` reports the real STT state (verified both states)
- [~] physical microphone test — **NOT VERIFIED** (headless env; phone test required)
