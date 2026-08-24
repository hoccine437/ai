"""
ZERION — SLICE 10.1 tests: ALWAYS-AVAILABLE VOICE PERCEPTION.

Covers the spec's 21 required test areas + the required end-to-end sequence
with REAL evidence only. Hardware-dependent paths (real microphone capture,
real STT engine output, real TTS playback) are marked
NOT_TESTABLE_IN_CURRENT_ENVIRONMENT and skipped — never fabricated.

The always-listening service is tested with an EXPLICITLY LABELED simulated
microphone (``SimulatedMicrophoneMonitor``, ``simulated=True`` in telemetry)
driving the REAL VAD, wake detector, state machine, event bus and cognitive
pipeline. The real environment path (no audio backend in this container) is
verified to report UNAVAILABLE honestly.
"""

import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from zerion.engine import AscendantEngine
from zerion.voice.audio import (
    AudioFrame,
    NullMicrophoneMonitor,
    RollingAudioBuffer,
    SimulatedMicrophoneMonitor,
)
from zerion.voice.perception_service import (
    ListeningMode,
    MicPhase,
    STTResult,
    VoiceHealth,
    VoicePerceptionService,
)
from zerion.voice.state_machine import VoiceState
from zerion.voice.vad import VoiceActivityDetector
from zerion.voice.wake_word import LayeredWakeWordDetector
from zerion.voice.watchdog import VoiceWatchdog


class FakeClock:
    """Deterministic clock for service/VAD/watchdog timing."""

    def __init__(self, start: float = 1000.0):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


async def _noop_sleep(delay: float) -> None:
    await asyncio.sleep(0)


class ScriptedSTT:
    """Deterministic fake STT: returns queued transcripts, labels simulated."""

    def __init__(self, *transcripts: str):
        self.queue = list(transcripts)
        self.calls = 0

    async def __call__(self, segment) -> STTResult:
        self.calls += 1
        if not self.queue:
            return STTResult("STT_UNAVAILABLE", provider="injected_stt",
                             reason="script exhausted", simulated=True)
        return STTResult("SUCCESS", transcript=self.queue.pop(0),
                         provider="injected_stt", simulated=True)


def _speech_frames(clock: FakeClock, vad: VoiceActivityDetector,
                   rms: float = 0.30, n: int = 2):
    """Yield (rms, advance) for a speech burst then end-of-speech silence.
    The generator pre-computes the same VAD transitions the service will see
    (shared clock + shared VAD instance), so segment completion is exact."""
    for _ in range(n):
        clock.advance(0.1)
        yield rms, 0.1
    for _ in range(10):
        clock.advance(0.2)
        yield 0.01, 0.2
        st = vad.process_frame(0.01)
        if st.turn_completed:
            return


class _VoiceServiceHarness:
    """Builds a standalone VoicePerceptionService against a REAL engine."""

    def __init__(self, engine, clock, stt=None, monitor=None,
                 watchdog=None, watchdog_interval_s=3600.0, **kw):
        self.clock = clock
        self.engine = engine
        monitor = monitor or SimulatedMicrophoneMonitor(now_fn=clock)
        self.monitor = monitor
        vad = kw.pop("vad", None) or VoiceActivityDetector(
            energy_threshold=0.05, silence_timeout_s=0.5,
            max_turn_duration_s=20.0, now_fn=clock)
        kw.setdefault("active_conversation_timeout_s", 10.0)
        kw.setdefault("barge_in_rms", 0.9)  # normal speech < barge threshold
        kw.setdefault("mic_retry_base_s", 1.0)
        kw.setdefault("mic_retry_max_s", 30.0)
        kw.setdefault("mic_retry_max_attempts", 4)
        kw.setdefault("sleep_fn", _noop_sleep)
        kw.setdefault("now_fn", clock)
        self.service = VoicePerceptionService(
            pipeline=engine.voice_pipeline,
            voice_env=engine.voice_env,
            event_bus=engine.event_bus,
            monitor=monitor,
            vad=vad,
            stt_transcriber=stt,
            watchdog=watchdog,
            watchdog_interval_s=watchdog_interval_s,
            **kw)
        # The background watchdog loop must never intervene in these tests.
        if watchdog is None:
            self.service.watchdog.timeout_s = 1e9

    async def start(self):
        return await self.service.start()

    async def feed_speech_segment(self, rms: float = 0.30, n: int = 2):
        for rms_v, _ in _speech_frames(self.clock, self.service.vad, rms, n):
            await self.service.feed_audio_frame(rms_v, source="simulated")

    async def feed_silence(self, n: int = 3):
        for _ in range(n):
            self.clock.advance(0.2)
            await self.service.feed_audio_frame(0.01, source="simulated")

    async def wait_idle(self, timeout_s: float = 5.0):
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            if not self.service._processing:
                return True
            await asyncio.sleep(0.02)
        return False


async def _boot_engine():
    d = tempfile.mkdtemp(prefix="s10_1_")
    engine = AscendantEngine(data_dir=d)
    await engine.start()
    return engine, d


class TestSlice101VoicePerception(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._engine = None
        self._dirs = []

    async def engine(self):
        if self._engine is None:
            self._engine, d = await _boot_engine()
            self._dirs.append(d)
        return self._engine

    def tearDown(self):
        async def _clean():
            if self._engine is not None:
                await self._engine.stop()
                self._engine = None
            for d in self._dirs:
                shutil.rmtree(d, ignore_errors=True)
        try:
            asyncio.get_event_loop().run_until_complete(_clean())
        except Exception:  # noqa: BLE001
            pass

    def _types(self):
        return [x["event_type"]
                for x in self._engine.ui_adapter.event_history(600)]

    # -- 1. continuous listening lifecycle ----------------------------------

    async def test_continuous_lifecycle_final_state_is_listening(self):
        engine = await self.engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion, status", "and keep listening")
        h = _VoiceServiceHarness(engine, clock, stt=stt)
        res = await h.start()
        self.assertEqual(res["phase"], "LISTENING")
        self.assertTrue(h.service.is_listening)
        self.assertEqual(h.service.health(), VoiceHealth.HEALTHY)

        # WAKE utterance -> full turn -> back to LISTENING (never STOPPED).
        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        self.assertEqual(h.service._mode, ListeningMode.ACTIVE_CONVERSATION)
        self.assertEqual(h.service._wake_detections, 1)
        self.assertEqual(h.service._turns_processed, 1)
        self.assertIsNotNone(h.service._last_turn)

        # Continuation without repeating the wake phrase.
        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        self.assertEqual(h.service._turns_processed, 2)

        # Still listening after turns: silence frame keeps the service alive.
        await h.service.feed_audio_frame(0.01, source="simulated")
        self.assertTrue(h.service.is_listening)

        for expected in ("VOICE_PERCEPTION_STARTED", "VOICE_MIC_INITIALIZING",
                         "VOICE_MIC_ACTIVE", "VOICE_SPEECH_DETECTED",
                         "VOICE_TRANSCRIPT_FINAL", "VOICE_RESPONSE_READY"):
            self.assertIn(expected, self._types(), msg=f"missing {expected}")

    # -- 3. wake word --------------------------------------------------------

    async def test_wake_detection_and_false_activation_rejection(self):
        engine = await self.engine()
        clock = FakeClock()
        stt = ScriptedSTT("the horizon is clear", "Zerion status")
        h = _VoiceServiceHarness(engine, clock, stt=stt)
        await h.start()

        # Non-wake utterance in WAKE_MODE -> rejected, no turn, no fabrication.
        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        self.assertEqual(h.service._turns_processed, 0)
        self.assertEqual(h.service._wake_detections, 0)
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        self.assertIn("WAKE_WORD_MISDETECTED", self._types())

        # Real wake activates the conversation.
        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        self.assertEqual(h.service._wake_detections, 1)
        self.assertEqual(h.service._turns_processed, 1)
        self.assertEqual(h.service._mode, ListeningMode.ACTIVE_CONVERSATION)

    async def test_wake_cooldown_suppresses_repeat_activation(self):
        engine = await self.engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion first", "Zerion again")
        h = _VoiceServiceHarness(
            engine, clock, stt=stt,
            wake_detector=LayeredWakeWordDetector(cooldown_seconds=5.0))
        await h.start()

        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        self.assertEqual(h.service._wake_detections, 1)

        # Fresh wake-mode evaluation: same wake phrase inside the cooldown
        # window (real elapsed time << 5s) must be suppressed.
        h.service._mode = ListeningMode.WAKE_MODE
        h.service._last_activity = 0.0
        before = len([t for t in self._types()
                      if t == "WAKE_WORD_MISDETECTED"])
        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        after = len([t for t in self._types()
                     if t == "WAKE_WORD_MISDETECTED"])
        self.assertGreater(after, before)  # cooldown suppressed re-activation
        self.assertEqual(h.service._wake_detections, 1)

    # -- 4. two listening modes ----------------------------------------------

    async def test_two_listening_modes_return_to_wake_after_inactivity(self):
        engine = await self.engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion open the door")
        h = _VoiceServiceHarness(engine, clock, stt=stt,
                                 active_conversation_timeout_s=5.0)
        await h.start()
        self.assertEqual(h.service._mode, ListeningMode.WAKE_MODE)

        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        self.assertEqual(h.service._mode, ListeningMode.ACTIVE_CONVERSATION)

        # Inactivity past the window -> back to WAKE_MODE.
        clock.advance(6.0)
        await h.service.feed_audio_frame(0.01, source="simulated")
        self.assertEqual(h.service._mode, ListeningMode.WAKE_MODE)
        modes = [x["payload"]["mode"] for x in
                 self._engine.ui_adapter.event_history(400)
                 if x["event_type"] == "VOICE_MODE_CHANGED"]
        self.assertIn("ACTIVE_CONVERSATION", modes)
        self.assertIn("WAKE_MODE", modes)

    # -- 5. VAD --------------------------------------------------------------

    async def test_vad_speech_segmentation_no_silence_to_stt(self):
        engine = await self.engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion status")
        h = _VoiceServiceHarness(engine, clock, stt=stt)
        await h.start()

        # Silence only -> STT never called, no segments.
        await h.feed_silence(5)
        self.assertEqual(stt.calls, 0)
        self.assertEqual(h.service._speech_segments, 0)

        # Speech burst -> VAD classifies it; one segment -> one STT call.
        states = []
        for rms_v, _ in _speech_frames(clock, h.service.vad):
            states.append(await h.service.feed_audio_frame(
                rms_v, source="simulated"))
        self.assertTrue(any(s.is_speech_active for s in states))
        self.assertTrue(any(s.turn_completed for s in states))
        self.assertTrue(await h.wait_idle())
        self.assertEqual(stt.calls, 1)
        self.assertEqual(h.service._speech_segments, 1)

    # -- 7. STT fallback -----------------------------------------------------

    async def test_stt_unavailable_is_honest_never_fabricated(self):
        engine = await self.engine()
        clock = FakeClock()
        # No injected STT and no real engine -> chain reports NO_PROVIDER.
        h = _VoiceServiceHarness(engine, clock, stt=None)
        await h.start()
        self.assertEqual(h.service.health(), VoiceHealth.DEGRADED)

        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        self.assertEqual(h.service._stt_unavailable_count, 1)
        self.assertIsNone(h.service._last_turn)  # nothing was "heard"
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        self.assertIn("VOICE_STT_UNAVAILABLE", self._types())
        self.assertNotIn("WAKE_WORD_DETECTED", self._types())

    # -- 8. TTS returns to listening -----------------------------------------

    async def test_tts_returns_to_listening_after_turn(self):
        engine = await self.engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion status")
        h = _VoiceServiceHarness(engine, clock, stt=stt)
        await h.start()
        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        turn = h.service._last_turn
        self.assertIsNotNone(turn)
        self.assertEqual(turn["voice_state"], "LISTENING")
        # Honest TTS result: no engine here -> VOICE_UNAVAILABLE (never fake).
        if engine.voice_env.detect_tts().status != "AVAILABLE":
            self.assertEqual(turn["tts_status"], "VOICE_UNAVAILABLE")
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        self.assertTrue(h.service.is_listening)

    # -- 9. barge-in ---------------------------------------------------------

    async def test_barge_in_interrupts_speaking_and_resumes(self):
        engine = await self.engine()
        clock = FakeClock()
        h = _VoiceServiceHarness(engine, clock, stt=None,
                                 barge_in_rms=0.20)
        await h.start()

        # ZERION speaking (TTS active) + an in-flight slow turn.
        h.service.pipeline.state_machine.transition(VoiceState.LISTENING,
                                                    reason="test")
        h.service.pipeline.state_machine.transition(VoiceState.THINKING,
                                                    reason="test")
        h.service.pipeline.state_machine.transition(VoiceState.SPEAKING,
                                                    reason="test_tts")
        original = h.service.pipeline.process_speech_input

        async def slow_turn(utterance):
            await asyncio.sleep(30.0)

        h.service.pipeline.process_speech_input = slow_turn
        try:
            h.service._mode = ListeningMode.ACTIVE_CONVERSATION
            await h.service.submit_transcript("do something")
            await asyncio.sleep(0.05)
            self.assertTrue(h.service._processing)

            # User speaks loudly while ZERION speaks -> mandatory barge-in.
            await h.service.feed_audio_frame(0.5, source="simulated")
            await asyncio.sleep(0.05)
            self.assertTrue(h.service._processing_task is None
                            or h.service._processing_task.done())
            self.assertEqual(h.service.pipeline.state_machine.state,
                             VoiceState.LISTENING)
            self.assertEqual(h.service._barge_ins, 1)
            self.assertIn("VOICE_BARGE_IN", self._types())
            self.assertIn("VOICE_INTERRUPTED", self._types())

            # Settle the segment that just started -> LISTENING.
            await h.feed_silence(4)
            self.assertEqual(h.service.phase, MicPhase.LISTENING)
        finally:
            h.service.pipeline.process_speech_input = original

    # -- 10. microphone failure & bounded recovery ---------------------------

    async def test_microphone_failure_bounded_backoff_then_recovery(self):
        engine = await self.engine()
        clock = FakeClock()
        recorded = []

        async def rec_sleep(delay):
            recorded.append(delay)
            await asyncio.sleep(0)

        monitor = SimulatedMicrophoneMonitor(now_fn=clock, fail_init=2)
        h = _VoiceServiceHarness(
            engine, clock, stt=None, monitor=monitor,
            sleep_fn=rec_sleep,
            mic_retry_base_s=1.0, mic_retry_max_s=30.0,
            mic_retry_max_attempts=4)
        res = await h.start()
        self.assertTrue(res["mic_available"])
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        # Bounded exponential backoff: base, then 2x, then success.
        self.assertEqual(h.service._mic_recovery_attempts, 2)
        self.assertIn(1.0, recorded)
        self.assertIn(2.0, recorded)
        self.assertEqual(monitor._init_attempts, 3)
        self.assertIn("VOICE_MIC_RECOVERING", self._types())
        self.assertIn("VOICE_MIC_ACTIVE", self._types())

    async def test_microphone_permanent_unavailability_no_infinite_retry(self):
        engine = await self.engine()
        clock = FakeClock()
        monitor = NullMicrophoneMonitor(now_fn=clock)
        h = _VoiceServiceHarness(engine, clock, stt=None, monitor=monitor)
        res = await h.start()
        self.assertFalse(res["mic_available"])
        self.assertEqual(h.service.phase, MicPhase.UNAVAILABLE)
        self.assertEqual(h.service.health(), VoiceHealth.UNAVAILABLE)
        self.assertFalse(h.service.is_listening)
        # Exactly ONE init attempt — never an infinite restart loop.
        self.assertEqual(monitor._init_attempts, 1)
        self.assertEqual(h.service._mic_recovery_attempts, 0)
        self.assertIn("VOICE_MIC_UNAVAILABLE", self._types())

    # -- 11. audio device changes --------------------------------------------

    async def test_audio_device_change_reinit_and_return_to_listening(self):
        engine = await self.engine()
        clock = FakeClock()
        monitor = SimulatedMicrophoneMonitor(now_fn=clock, device_changes=1)
        h = _VoiceServiceHarness(engine, clock, stt=None, monitor=monitor)
        await h.start()
        self.assertEqual(h.service.phase, MicPhase.LISTENING)

        self.assertTrue(monitor.emit_device_change())
        await h.service.feed_audio_frame(0.01, source="simulated")
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        self.assertTrue(h.service.is_listening)
        self.assertIn("VOICE_MIC_RECOVERING", self._types())
        self.assertGreaterEqual(h.service._mic_recovery_attempts, 1)

    # -- 12. phone call / system interruption --------------------------------

    async def test_system_pause_and_auto_recovery(self):
        engine = await self.engine()
        clock = FakeClock()
        monitor = SimulatedMicrophoneMonitor(now_fn=clock, system_pauses=1)
        h = _VoiceServiceHarness(engine, clock, stt=None, monitor=monitor)
        await h.start()
        self.assertTrue(h.service.is_listening)

        # Phone call / OS interruption -> never pretend to hear.
        self.assertTrue(monitor.emit_system_pause())
        await h.service.feed_audio_frame(0.30, source="simulated")
        self.assertEqual(h.service.phase, MicPhase.PAUSED_BY_SYSTEM)
        self.assertFalse(h.service.is_listening)
        self.assertIn("VOICE_MIC_UNAVAILABLE", self._types())

        # Access returns -> AUTO_RECOVERY -> LISTENING.
        monitor.resume_from_pause()
        await h.service.feed_audio_frame(0.01, source="simulated")
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        self.assertTrue(h.service.is_listening)

    # -- 13. Android / Termux -------------------------------------------------

    async def test_termux_reports_exact_limitation(self):
        engine = await self.engine()
        clock = FakeClock()
        with mock.patch.dict(os.environ, {"TERMUX_VERSION": "0.118.0"}):
            self.assertEqual(engine.voice_env.detect_platform(), "TERMUX")
            h = _VoiceServiceHarness(
                engine, clock, stt=None,
                monitor=NullMicrophoneMonitor(now_fn=clock))
            await h.start()
            self.assertEqual(h.service.phase, MicPhase.UNAVAILABLE)
            self.assertIn("Termux limitation",
                          h.service.telemetry()["mic_reason"])

    # -- 2. no UI dependency --------------------------------------------------

    async def test_ui_closed_voice_service_remains_active(self):
        engine = await self.engine()
        # No GenesisWebServer was ever started — the perception organ lives on
        # the engine, not the UI (engine.start() already started it).
        svc = engine.voice_perception
        tele = svc.telemetry()
        self.assertTrue(tele["service_started"])
        self.assertTrue(tele["independent_of_ui"])
        self.assertIn("VOICE_PERCEPTION_STARTED", self._types())
        # Real environment (no audio backend): honest UNAVAILABLE.
        self.assertEqual(tele["mic_phase"], "UNAVAILABLE")
        self.assertFalse(tele["is_listening"])

    # -- 18. watchdog ----------------------------------------------------------

    async def test_watchdog_restarts_only_the_stuck_component(self):
        engine = await self.engine()
        clock = FakeClock()
        watchdog = VoiceWatchdog(timeout_s=1.0, min_restart_interval_s=0.0,
                                 max_restarts_per_window=10, window_s=60.0,
                                 now_fn=clock)
        h = _VoiceServiceHarness(engine, clock, stt=None, watchdog=watchdog,
                                 sleep_fn=asyncio.sleep)
        await h.start()
        self.assertTrue(h.service.is_listening)

        # Fresh beats for the healthy components; VAD goes stale.
        await h.service.feed_audio_frame(0.01, source="simulated")
        clock.advance(3.0)
        h.service.watchdog.beat("mic_capture")
        h.service.watchdog.beat("audio_capture")

        report = await h.service.watchdog.check()
        self.assertIn("vad", report["stuck"])
        self.assertIn("vad", report["restarted"])
        self.assertEqual(report["restart_counts"].get("vad"), 1)
        # Only the stuck component restarts; mic stays untouched.
        self.assertNotIn("mic_capture", report["restarted"])
        self.assertNotIn("mic_capture", report["stuck"])
        # The full runtime was NOT restarted.
        snap = engine.ui_adapter.snapshot()
        self.assertEqual(snap["system"]["runtime_status"], "RUNNING")

    async def test_watchdog_rate_limits_restarts(self):
        engine = await self.engine()
        clock = FakeClock()
        watchdog = VoiceWatchdog(timeout_s=1.0, min_restart_interval_s=0.0,
                                 max_restarts_per_window=1, window_s=60.0,
                                 now_fn=clock)
        h = _VoiceServiceHarness(engine, clock, stt=None, watchdog=watchdog,
                                 sleep_fn=asyncio.sleep)
        await h.start()
        await h.service.feed_audio_frame(0.01, source="simulated")
        clock.advance(3.0)
        h.service.watchdog.beat("mic_capture")
        h.service.watchdog.beat("audio_capture")
        r1 = await h.service.watchdog.check()
        self.assertIn("vad", r1["restarted"])
        self.assertNotIn("mic_capture", r1["restarted"])

        # Re-stuck immediately: rate limited, suppressed, never a loop.
        clock.advance(3.0)
        h.service.watchdog.beat("mic_capture")
        h.service.watchdog.beat("audio_capture")
        r2 = await h.service.watchdog.check()
        self.assertTrue(any(s["component"] == "vad"
                            for s in r2["suppressed"]))
        self.assertNotIn("vad", r2["restarted"])

    # -- 15. memory safety -----------------------------------------------------

    async def test_bounded_audio_memory_rolling_buffer(self):
        buf = RollingAudioBuffer(max_frames=10, max_duration_s=60.0)
        t = 0.0
        for i in range(100):
            buf.append(AudioFrame(rms=float(i % 100) / 100.0, timestamp=t))
            t += 0.01
        self.assertEqual(buf.size, 10)
        seg = buf.extract_segment()
        self.assertEqual(len(seg), 10)
        self.assertEqual(buf.size, 0)  # extracted, not retained
        self.assertFalse(buf.stats()["persisted_to_disk"])

        # Duration cap also holds.
        buf2 = RollingAudioBuffer(max_frames=1000, max_duration_s=0.5)
        for i in range(100):
            buf2.append(AudioFrame(rms=0.1, timestamp=i * 0.1))
        self.assertLessEqual(buf2.retained_s, 0.51)

        # Service-level: the buffer never grows without bound while listening.
        engine = await self.engine()
        clock = FakeClock()
        h = _VoiceServiceHarness(engine, clock, stt=None)
        await h.start()
        for _ in range(500):
            clock.advance(0.01)
            await h.service.feed_audio_frame(0.01, source="simulated")
        self.assertLessEqual(h.service._buffer.size,
                             h.service._buffer.max_frames)

    # -- 14. battery / resource control -----------------------------------------

    async def test_cpu_resource_telemetry_is_measured(self):
        engine = await self.engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion status", "Zerion status")
        h = _VoiceServiceHarness(engine, clock, stt=stt)
        await h.start()
        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        tele = h.service.telemetry()
        self.assertGreaterEqual(tele["measured"]["cpu_s"], 0.0)
        self.assertGreater(tele["measured"]["frames_per_s"], 0.0)
        self.assertGreaterEqual(tele["counters"]["frames_total"], 4)
        self.assertEqual(tele["counters"]["turns_processed"], 2)
        self.assertGreaterEqual(tele["counters"]["speech_segments"], 2)

    # -- 19. health states ------------------------------------------------------

    async def test_health_state_matrix(self):
        engine = await self.engine()
        clock = FakeClock()

        # UNAVAILABLE: no microphone backend.
        h1 = _VoiceServiceHarness(
            engine, clock, stt=None,
            monitor=NullMicrophoneMonitor(now_fn=clock))
        await h1.start()
        self.assertEqual(h1.service.health(), VoiceHealth.UNAVAILABLE)

        # DEGRADED: mic active but STT unavailable (wake detector works).
        h2 = _VoiceServiceHarness(engine, clock, stt=None)
        await h2.start()
        self.assertEqual(h2.service.health(), VoiceHealth.DEGRADED)

        # HEALTHY: mic + VAD + wake + STT all operational.
        h3 = _VoiceServiceHarness(engine, clock,
                                  stt=ScriptedSTT("Zerion status"))
        await h3.start()
        self.assertEqual(h3.service.health(), VoiceHealth.HEALTHY)

        # RECOVERING: mic lost temporarily (device change / init / pause).
        h4 = _VoiceServiceHarness(engine, clock, stt=None)
        await h4.start()
        h4.service._phase = MicPhase.RECOVERING
        self.assertEqual(h4.service.health(), VoiceHealth.RECOVERING)

    # -- 17 & 20. real state only / absolute failure rule ----------------------

    async def test_never_claims_listening_or_heard_without_evidence(self):
        engine = await self.engine()
        clock = FakeClock()

        # No mic: is_listening must be False, phase not LISTENING.
        h1 = _VoiceServiceHarness(
            engine, clock, stt=None,
            monitor=NullMicrophoneMonitor(now_fn=clock))
        await h1.start()
        self.assertFalse(h1.service.is_listening)
        self.assertNotEqual(h1.service.phase, MicPhase.LISTENING)
        self.assertIsNone(h1.service._last_turn)

        # Mic active but STT unavailable: speech yields NO transcript, no turn.
        h2 = _VoiceServiceHarness(engine, clock, stt=None)
        await h2.start()
        await h2.feed_speech_segment()
        self.assertTrue(await h2.wait_idle())
        self.assertIsNone(h2.service._last_turn)
        self.assertEqual(h2.service.telemetry()["stt"]["status"],
                         "UNAVAILABLE")

        # The UI snapshot reflects REAL service telemetry, not a print().
        snap = engine.ui_adapter.snapshot()
        self.assertIn("perception", snap["voice"])
        self.assertIs(snap["voice"]["perception"]["is_listening"],
                      engine.voice_perception.is_listening)
        html = (Path(__file__).parent.parent / "zerion" / "ui"
                / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("I heard you", html)

    async def test_ui_presentation_never_claims_listening_without_mic(self):
        """Slice 10.1 rule 17 in the HUD: the pipeline's resting LISTENING
        slot must never be presented as a listening claim when the perception
        service confirms the mic is not active — and the HUD may show
        LISTENING only when the service reports is_listening=True."""
        engine = await self.engine()

        # No mic backend in this container: force the pipeline state machine
        # into its post-turn LISTENING resting slot. The HUD must stay honest.
        engine.voice_pipeline.state_machine.transition(VoiceState.LISTENING,
                                                       reason="test_resting")
        pres = engine.ui_adapter.snapshot()["presentation"]
        self.assertNotEqual(pres["runtime_state"], "LISTENING")
        vp = pres["voice_perception"]
        self.assertFalse(vp["is_listening"])
        self.assertIn("mic_phase", vp)
        self.assertEqual(vp["mic_phase"], "UNAVAILABLE")
        self.assertTrue(vp["reason"])  # exact reason exposed, never blank

        # Genuinely active mic -> LISTENING is truthful and shown.
        clock = FakeClock()
        old = engine.voice_perception
        await old.stop()
        h = _VoiceServiceHarness(engine, clock,
                                 stt=ScriptedSTT("Zerion status"))
        await h.start()
        engine.voice_perception = h.service
        try:
            self.assertTrue(h.service.is_listening)
            # Pipeline rests in its post-turn LISTENING slot with the mic
            # genuinely active -> the HUD's LISTENING claim is truthful.
            engine.voice_pipeline.state_machine.transition(
                VoiceState.LISTENING, reason="mic_active")
            pres = engine.ui_adapter.snapshot()["presentation"]
            self.assertEqual(pres["runtime_state"], "LISTENING")
            vp = pres["voice_perception"]
            self.assertTrue(vp["is_listening"])
            self.assertEqual(vp["mic_phase"], "LISTENING")
        finally:
            await h.service.stop()
            engine.voice_perception = old

    async def test_simulated_monitor_is_explicitly_labeled(self):
        engine = await self.engine()
        clock = FakeClock()
        h = _VoiceServiceHarness(engine, clock, stt=None)
        await h.start()
        mic = h.service.telemetry()["mic"]
        self.assertTrue(mic["simulated"])
        self.assertEqual(mic["kind"], "simulated")

    # -- 22. required end-to-end sequence ---------------------------------------

    async def test_required_e2e_sequence_ends_in_listening(self):
        engine = await self.engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion, status", "continue")
        h = _VoiceServiceHarness(engine, clock, stt=stt,
                                 barge_in_rms=0.20)
        await h.start()

        # ZERION STARTS -> VOICE SERVICE STARTS -> MICROPHONE ACTIVE.
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        self.assertTrue(h.service.is_listening)

        # USER: "Zerion..." -> WAKE DETECTED -> VAD -> OFFLINE STT
        # -> TRANSCRIPT -> COGNITIVE RUNTIME -> RESPONSE -> TTS -> LISTENING.
        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        self.assertEqual(h.service._turns_processed, 1)
        self.assertEqual(h.service._wake_detections, 1)
        turn = h.service._last_turn
        self.assertIsNotNone(turn)
        self.assertIn("Zerion", turn["raw_transcript"])
        if engine.voice_env.detect_tts().status != "AVAILABLE":
            self.assertEqual(turn["tts_status"], "VOICE_UNAVAILABLE")

        # USER INTERRUPTS while ZERION speaks -> TTS STOPS -> input resumes.
        h.service.pipeline.state_machine.transition(VoiceState.THINKING,
                                                    reason="e2e")
        h.service.pipeline.state_machine.transition(VoiceState.SPEAKING,
                                                    reason="e2e_speaking")
        await h.service.feed_audio_frame(0.5, source="simulated")
        self.assertEqual(h.service.pipeline.state_machine.state,
                         VoiceState.LISTENING)
        self.assertEqual(h.service._barge_ins, 1)
        self.assertEqual(h.service._mode, ListeningMode.ACTIVE_CONVERSATION)

        # NEW TRANSCRIPT -> COGNITIVE RUNTIME -> RESPONSE -> LISTENING AGAIN.
        await h.feed_speech_segment()
        self.assertTrue(await h.wait_idle())
        self.assertEqual(h.service._turns_processed, 2)

        # FINAL STATE: LISTENING — not STOPPED.
        self.assertEqual(h.service.phase, MicPhase.LISTENING)
        self.assertTrue(h.service.is_listening)

        for expected in ("VOICE_PERCEPTION_STARTED", "VOICE_MIC_ACTIVE",
                         "VOICE_SPEECH_DETECTED", "WAKE_WORD_DETECTED",
                         "VOICE_TRANSCRIPT_FINAL", "VOICE_RESPONSE_READY",
                         "VOICE_BARGE_IN", "VOICE_INTERRUPTED"):
            self.assertIn(expected, self._types(), msg=f"missing {expected}")

    # -- hardware-dependent: NOT_TESTABLE_IN_CURRENT_ENVIRONMENT -----------------

    async def test_real_microphone_capture_not_testable(self):
        """Real mic capture requires hardware. In this container the honest
        path (no backend) is verified; the marker is never silently passed."""
        engine = await self.engine()
        tele = engine.voice_perception.telemetry()
        if tele["mic_phase"] == "LISTENING":
            self.skipTest("NOT_TESTABLE_IN_CURRENT_ENVIRONMENT: real "
                          "microphone capture requires hardware")
        self.assertEqual(tele["mic_phase"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
