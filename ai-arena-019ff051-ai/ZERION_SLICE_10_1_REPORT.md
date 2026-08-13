# ZERION — SLICE 10.1 REPORT
## ALWAYS-AVAILABLE VOICE PERCEPTION

Built on the REAL Slice 1–10 implementation. The microphone pipeline is a
continuous perception organ of ZERION: it starts with the runtime, runs with
no UI open, requires no button, and its normal state is LISTENING — not
WAITING_FOR_BUTTON. No new event bus, no duplicate cognitive runtime, no
cognition inside the voice layer.

**Date:** 2026-08-13
**Status:** Implemented, tested (24 Slice 10.1 tests + full regression 667),
wired into the engine (`engine.start()`), the CLI (`--voice`) and the HUD
(rule-17 LISTENING gate — the UI never claims listening without a real mic).

---

## 1. Architecture (spec 1/2)

```
MICROPHONE
  -> AudioInputMonitor (continuous, SoundDevice real / Null honest)
    -> RollingAudioBuffer (bounded, in-memory only)
      -> VAD (energy segmentation; silence is NEVER sent to STT)
        -> ListeningMode: WAKE_MODE | ACTIVE_CONVERSATION
          -> local-first STT chain (offline -> offline -> policy-gated online -> NO_PROVIDER)
            -> VOICE EVENT -> existing VoiceFirstInteractionPipeline
              -> CognitiveRuntime -> RESPONSE -> TTS -> return to LISTENING
```

- **UI: DISPLAY ONLY.** `VoicePerceptionService` is engine-scoped: it is
  started in `AscendantEngine.start()` and stopped in `AscendantEngine.stop()`,
  completely independent of `GenesisWebServer`. Closing the UI does not stop
  voice perception (verified by test `test_ui_closed_voice_service_remains_active`).
- **The voice layer is an interface, not the brain.** The service contains no
  goal logic, attention logic, question generation, hypothesis logic, belief
  revision, experiment logic, benchmark logic or self-modification logic. All
  cognition stays in the Slice 1–9 subsystems; the service routes transcripts
  through the existing `VoiceFirstInteractionPipeline`.

## 2. What was reused (no duplicates)

| Component | Source | How Slice 10.1 uses it |
|---|---|---|
| `LayeredWakeWordDetector` | Slice 10 `wake_word.py` | Wake detection on the STT transcript; sensitivity, cooldown, pronunciation tolerance, false-positive rejection all reused |
| `VoiceActivityDetector` | Slice 10 `vad.py` | Real energy-VAD segmentation; gained an optional injectable clock (`now_fn`, default unchanged) for deterministic testing |
| `VoiceStateMachine` | Slice 10 `state_machine.py` | Explicit states; `INTERRUPTED -> LISTENING` used as the barge-in landing |
| `VoiceFirstInteractionPipeline` | Slice 10 `pipeline.py` | The turn engine: wake -> cognitive routing -> TTS -> back to LISTENING (gained `resume_listening_after_interrupt`) |
| `VoiceEnvironment` | Slice 10 `providers.py` | Honest STT/TTS/wake/platform detection; offline engine chain |
| `AsyncEventBus` + `EventType` | Slice 1 runtime | All perception lifecycle events flow through the real bus |
| `VisualizationStateAdapter` | Slice 10 | UI consumes real perception telemetry through `snap["voice"]["perception"]` |

## 3. New components (Slice 10.1)

- **`zerion/voice/audio.py`**
  - `RollingAudioBuffer` — bounded rolling buffer (`max_frames` + `max_duration_s`);
    `extract_segment()` returns copies; nothing is ever persisted to disk.
  - `AudioInputMonitor` interface; `NullMicrophoneMonitor` (honest no-backend,
    `transient=False` → never retried forever); `SoundDeviceMicrophoneMonitor`
    (REAL capture via optional `sounddevice`, guarded import, honest binding
    failures); `SimulatedMicrophoneMonitor` (deterministic harness, always
    labeled `simulated=True`, with scriptable init failures, device changes
    and system pauses); `default_microphone_monitor()` picks real-or-Null.
- **`zerion/voice/watchdog.py`** — `VoiceWatchdog` with per-component heartbeats
  (mic_capture, audio_capture, vad, wake, stt, tts, pipeline), stuck detection,
  async component-level restart with verification, and rate limiting
  (`min_restart_interval` + per-window cap). It never restarts the runtime.
- **`zerion/voice/perception_service.py`** — `VoicePerceptionService`:
  - lifecycle `START -> INITIALIZE MIC -> LISTENING -> DETECT -> PROCESS ->
    RETURN TO LISTENING`; after TTS and after interruption it always returns
    to LISTENING (never permanently stops after one command)
  - listening modes: WAKE_MODE (local wake detection; only process speech after
    wake) and ACTIVE_CONVERSATION (configurable interaction window; no repeated
    wake phrase; inactivity → back to WAKE_MODE)
  - VAD-driven segmentation (`SILENCE / BACKGROUND_NOISE / SPEECH /
    END_OF_SPEECH`); no silence to STT
  - local-first STT chain with `STT_UNAVAILABLE` recorded on failure — never a
    fabricated transcript
  - mandatory barge-in: while SPEAKING, VAD speech ≥ threshold stops TTS
    (cancels the in-flight turn, publishes `VOICE_BARGE_IN` +
    `VOICE_INTERRUPTED`), captures the new speech, processes it, returns to
    LISTENING
  - microphone recovery with bounded exponential backoff
    (`base * 2^(attempts-1)` capped, max attempts) — permanent unavailability
    is reported once, never an infinite retry loop
  - audio device changes (bluetooth/wired/default mic) → safe re-init → LISTENING
  - external interruptions: `PAUSED_BY_SYSTEM` (never pretends to hear) with
    `AUTO_RECOVERY -> LISTENING` when access returns
  - Android/Termux: platform detection; exact OS limitation appended to the
    reason when background mic access is not possible (Termux needs
    `termux-api` + foreground audio; Android needs a foreground service with
    `RECORD_AUDIO`)
  - battery/resource: energy-VAD gating, bounded queue with drop-oldest
    backpressure, measured `cpu_s` (process time) + `frames_per_s` counters
  - health states: `HEALTHY` (mic+VAD+wake+STT), `DEGRADED` (wake works, STT
    unavailable), `RECOVERING` (mic lost temporarily), `UNAVAILABLE` (no mic)
  - REAL state only: `is_listening` is true ONLY when phase == LISTENING AND
    mic available AND monitor active; `phase`/`mode` are read-only properties;
    never "print('Listening...') and assume it is true"
  - watchdog wiring: heartbeat on every frame/turn; component restarts only
    (mic re-init, VAD reset, wake detector re-created, STT/TTS re-detected,
    pipeline state reset) — never the whole runtime

## 4. Event types added

`VOICE_PERCEPTION_STARTED`, `VOICE_PERCEPTION_STOPPED`, `VOICE_MIC_INITIALIZING`,
`VOICE_MIC_ACTIVE`, `VOICE_MIC_RECOVERING`, `VOICE_MIC_UNAVAILABLE`,
`VOICE_SPEECH_DETECTED`, `VOICE_MODE_CHANGED`, `VOICE_BARGE_IN`,
`VOICE_STT_UNAVAILABLE`, `VOICE_WATCHDOG_RESTARTED`.

Everything else (wake detected/misdetected, transcript final/partial,
interrupted, ended, response-ready, voice-started) is REUSED from Slice 10 —
nothing was duplicated.

## 5. Test results (run just now, not fabricated)

| Command (from `ai-arena-019ff051-ai/`) | Result |
|---|---|
| `python3 -m unittest tests.test_slice10_1_voice_perception -v` | **24 tests — OK, 0 failures, 0 errors, 0 skipped** |
| `python3 -m unittest discover -s tests -p "test_*.py"` | **667 tests — OK, 0 failures, 0 errors, 2 skipped** (Slice 10 baseline: 643; +24 Slice 10.1, zero regressions) |

Coverage vs the 21 required areas:

1. continuous listening lifecycle — `test_continuous_lifecycle_final_state_is_listening`
2. wake detection — `test_wake_detection_and_false_activation_rejection`
3. false activation cooldown — `test_wake_cooldown_suppresses_repeat_activation`
4. VAD — `test_vad_speech_segmentation_no_silence_to_stt`
5. speech segmentation — same test (SILENCE/SPEECH/END_OF_SPEECH states asserted)
6. STT — local-first chain + honest unavailability
   (`test_stt_unavailable_is_honest_never_fabricated`)
7. return-to-listening — `test_tts_returns_to_listening_after_turn`
8. barge-in — `test_barge_in_interrupts_speaking_and_resumes`
9. TTS interruption — same test (turn task cancelled, `VOICE_INTERRUPTED`)
10. microphone failure — `test_microphone_failure_bounded_backoff_then_recovery`
    (bounded exponential backoff, exact delays 1.0s/2.0s, 3 init attempts)
11. microphone recovery — same test (RECOVERING → LISTENING)
12. audio device change — `test_audio_device_change_reinit_and_return_to_listening`
13. provider failure — STT chain NO_PROVIDER path (test 6) + honest online
    policy gate
14. offline mode — offline STT/TTS chain + `OFFLINE_ONLY` behavior inherited
    from Slice 10 pipeline (no cloud audio streaming by design)
15. Termux environment — `test_termux_reports_exact_limitation`
16. UI closed while voice service remains active —
    `test_ui_closed_voice_service_remains_active`
17. voice watchdog — `test_watchdog_restarts_only_the_stuck_component` +
    `test_watchdog_rate_limits_restarts`
18. bounded audio memory — `test_bounded_audio_memory_rolling_buffer`
    (frame cap + duration cap + never persisted)
19. CPU/resource behavior — `test_cpu_resource_telemetry_is_measured`
    (measured cpu_s / frames_per_s, honest counters)
20. never-fake rules — `test_never_claims_listening_or_heard_without_evidence`
    + `test_simulated_monitor_is_explicitly_labeled`
    + **rule 17 in the HUD** — `test_ui_presentation_never_claims_listening_without_mic`
    (the pipeline's resting LISTENING slot is NEVER presented as a listening
    claim; the HUD shows LISTENING only when the voice service confirms
    `is_listening=True`)
21. health states — `test_health_state_matrix` (HEALTHY/DEGRADED/RECOVERING/UNAVAILABLE)

Required end-to-end sequence — `test_required_e2e_sequence_ends_in_listening`:

```
ZERION STARTS -> VOICE SERVICE STARTS -> MIC ACTIVE -> LISTENING
USER "Zerion..." -> WAKE DETECTED -> VAD -> OFFLINE STT -> TRANSCRIPT
-> COGNITIVE RUNTIME -> RESPONSE -> TTS -> LISTENING
USER INTERRUPTS -> TTS STOPS (VOICE_INTERRUPTED + VOICE_BARGE_IN)
-> VOICE INPUT RESUMES -> NEW TRANSCRIPT -> COGNITIVE RUNTIME -> RESPONSE
-> LISTENING AGAIN
```

**Final state: LISTENING** (asserted), not STOPPED.

Hardware-dependent paths are marked `NOT_TESTABLE_IN_CURRENT_ENVIRONMENT`
(real microphone capture; real STT engine audio; real TTS playback) — never
fabricated.

## 6. Real environment evidence (this container)

- No `sounddevice` installed → `default_microphone_monitor()` returns
  `NullMicrophoneMonitor`. On every engine boot the service reports
  `mic_phase: UNAVAILABLE`, `health: UNAVAILABLE`, `is_listening: False` with
  the exact reason — it never claims to listen without a microphone.
- No offline STT engine on PATH → STT chain reports `NO_PROVIDER` with the
  engines tried (whisper.cpp / openai-whisper / vosk); a speech segment
  produces `VOICE_STT_UNAVAILABLE`, no transcript, no turn.
- No offline TTS engine → turns report `VOICE_UNAVAILABLE` for speech output.
- `python3 main.py --voice` output (real run):
  ```
  [ZERION VOICE] perception service started (independent of UI: True)
  [ZERION VOICE] mic phase:     UNAVAILABLE
  [ZERION VOICE] health:        UNAVAILABLE
  [ZERION VOICE] is_listening:  False
  [ZERION VOICE] stt:           UNAVAILABLE (no offline STT engine found ...)
  [ZERION VOICE] NOT listening — reason: no audio input backend available ...
  ```
  The daemon runs with no UI; it reports the exact blocked layers and stays up.
- **HUD truth gate (verified live):** `zerion/ui/visualization_adapter.py`
  `_snap_presentation` now gates any LISTENING display on the perception
  service's real `is_listening`. Forcing the pipeline state machine into its
  post-turn LISTENING resting slot with no mic backend yields
  `runtime_state: IDLE` + `voice_perception.mic_phase: UNAVAILABLE` with the
  exact reason — verified end-to-end through the real `GenesisWebServer`
  (`GET /api/state` over a raw socket, 200 OK). `zerion/ui/index.html` gained
  a `MIC:` readout (`#micVal`) that renders the real phase (orange when not
  listening) with the reason as a tooltip — never a print() assumption.

## 7. Known limitations (honest)

- **Real mic capture / acoustic wake detection** are not exercisable in this
  container (no audio backend, no wake-on-audio engine). The service's audio
  path is verified with an explicitly-labeled `SimulatedMicrophoneMonitor` +
  injected STT; the real path is implemented behind `SoundDeviceMicrophoneMonitor`
  and the offline STT binaries and reports honestly when absent.
- **Barge-in TTS stop** cancels the awaiting turn and transitions to LISTENING
  immediately; a subprocess TTS engine already spawned may finish writing its
  output in the background (no portable kill handle in this environment).
  Real speaker-stop requires the platform's native audio layer.
- Wake detection runs on the local STT transcript (local whisper/vosk) — the
  raw mic stream is never sent to a cloud API. When no STT engine exists, wake
  detection cannot operate and the service reports DEGRADED with the reason.
- Online STT is policy-gated (`allow_online_stt=False` by default) and is an
  explicit adapter; it is NOT wired to any SDK in this slice and reports
  NOT_CONFIGURED honestly.

## 8. Files created / modified

**Created:** `zerion/voice/audio.py`, `zerion/voice/watchdog.py`,
`zerion/voice/perception_service.py`, `tests/test_slice10_1_voice_perception.py`,
`ZERION_SLICE_10_1_REPORT.md`.

**Modified:** `zerion/runtime/events.py` (11 perception event types),
`zerion/voice/vad.py` (optional `now_fn`, default unchanged),
`zerion/voice/pipeline.py` (`resume_listening_after_interrupt`),
`zerion/voice/__init__.py` (exports), `zerion/engine.py` (service wired into
start/stop), `zerion/ui/visualization_adapter.py` (`snap["voice"]["perception"]`
+ rule-17 LISTENING gate + `voice_perception` presentation summary),
`zerion/ui/index.html` (honest `MIC:` HUD readout), `zerion/cli.py` (`--voice`
daemon flag).

## Final rule

The voice layer is a persistent perception organ: it attempts to remain
available whenever the OS and hardware permit, it reports the exact limitation
when they do not (no impossible guarantees against device shutdown, OS
force-stop, revoked permission, hardware failure or another process owning the
mic), and it never claims to hear or listen without real evidence.
