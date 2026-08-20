"""
ZERION — TERMUX PRIMARY VOICE PATH regression tests (voice repair mission).

The Termux path is the REAL Android voice pipeline:

    termux-speech-to-text owns the microphone
      -> continuous listener loop (the loop IS the mic)
        -> transcript
          -> VOICE_TRANSCRIPT_FINAL on the canonical CognitiveEventBus
            -> CognitiveRuntime -> response
              -> back to LISTENING (repeat)

These tests exercise the actual ``VoicePerceptionService`` / pipeline / event
bus code with the Termux environment FIXED to report
``termux-speech-to-text`` (the same branch real Termux takes) and a clearly
labeled injected STT transcriber (``simulated=True``) standing in for the
device recognizer. Everything else — the listener loop, wake detection,
event publishing, cognitive turn, TTS attempt, failure recovery, repeated
listening — is the real runtime path.

Hardware-dependent claims (real device mic capture, real on-device
recognition, real speaker output) are NOT_TESTABLE_IN_CURRENT_ENVIRONMENT
and are never fabricated here.
"""

import asyncio
import shutil
import tempfile
import unittest

from zerion.engine import AscendantEngine
from zerion.runtime.events import EventType
from zerion.voice.audio import NullMicrophoneMonitor
from zerion.voice.perception_service import (
    MicPhase,
    STTResult,
    VoiceHealth,
    VoicePerceptionService,
)
from zerion.voice.providers import (
    VoiceEngineInfo,
    VoiceEngineStatus,
    VoiceEnvironment,
)
from zerion.voice.watchdog import VoiceWatchdog


class FakeClock:
    """Deterministic clock for service timing."""

    def __init__(self, start: float = 1000.0):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


async def _noop_sleep(delay: float) -> None:
    await asyncio.sleep(0)


class TermuxSTTEnvironment(VoiceEnvironment):
    """VoiceEnvironment fixed to the Termux primary path: the on-device
    speech recognizer is present and owns the microphone."""

    def __init__(self):
        super().__init__()
        self._stt_cache = VoiceEngineInfo(
            "STT", "termux-speech-to-text", VoiceEngineStatus.AVAILABLE,
            reason="Android/Termux on-device speech recognizer found "
                   "(termux-api); no model file required",
            engine_binary="/fake/bin/termux-speech-to-text",
            details={"offline": True, "platform": "TERMUX",
                     "model_required": False})


class ScriptedSTT:
    """Deterministic fake device recognizer: returns queued transcripts,
    then reports STT_UNAVAILABLE (the real exhausted-engine state). Always
    labeled simulated — never mistaken for a real engine."""

    def __init__(self, *transcripts: str):
        self.queue = list(transcripts)
        self.calls = 0
        self.failures = 0

    async def __call__(self, segment) -> STTResult:
        self.calls += 1
        if not self.queue:
            self.failures += 1
            return STTResult("STT_UNAVAILABLE", provider="injected_stt",
                             reason="script exhausted", simulated=True)
        return STTResult("SUCCESS", transcript=self.queue.pop(0),
                         provider="injected_stt", simulated=True)


class FailingSTT:
    """Deterministic failing recognizer (mission §15: STT failure)."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, segment) -> STTResult:
        self.calls += 1
        return STTResult("STT_ERROR", provider="injected_stt",
                         reason="simulated recognizer crash", simulated=True)


class EmptySTT:
    """Deterministic empty-transcript recognizer (mission §15)."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, segment) -> STTResult:
        self.calls += 1
        return STTResult("SUCCESS", transcript="   ",
                         provider="injected_stt", simulated=True)


def _termux_service(engine, clock, stt, **kw) -> VoicePerceptionService:
    kw.setdefault("sleep_fn", _noop_sleep)
    kw.setdefault("now_fn", clock)
    kw.setdefault("watchdog_interval_s", 3600.0)
    kw.setdefault("active_conversation_timeout_s", 10.0)
    svc = VoicePerceptionService(
        pipeline=engine.voice_pipeline,
        voice_env=TermuxSTTEnvironment(),
        event_bus=engine.event_bus,
        monitor=NullMicrophoneMonitor(),
        stt_transcriber=stt,
        **kw)
    svc.watchdog.timeout_s = 1e9  # the watchdog must never intervene here
    return svc


async def _wait_until(pred, timeout_s: float = 10.0) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.02)
    return False


def _turns_done(svc, n: int) -> bool:
    """n turns processed AND the service is idle again (the listener loop
    restores LISTENING only in ``_run_turn``'s finally)."""
    return (svc._turns_processed >= n and not svc._processing)


def _event_types_on_bus(engine, source: str) -> list:
    return [x["event_type"]
            for x in engine.ui_adapter.event_history(1000)
            if x.get("source") == source]


class TestTermuxPrimaryVoicePath(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._engine = None
        self._dirs = []
        self._services = []

    async def _boot_engine(self):
        d = tempfile.mkdtemp(prefix="termux_voice_")
        self._dirs.append(d)
        engine = AscendantEngine(data_dir=d)
        await engine.start()
        self._engine = engine
        return engine

    def tearDown(self):
        async def _clean():
            for svc in self._services:
                try:
                    await svc.stop()
                except Exception:  # noqa: BLE001
                    pass
                await asyncio.sleep(0.05)  # let cancellations land
            if self._engine is not None:
                await self._engine.stop()
                self._engine = None
            for d in self._dirs:
                shutil.rmtree(d, ignore_errors=True)
        try:
            asyncio.get_event_loop().run_until_complete(_clean())
        except Exception:  # noqa: BLE001
            pass

    # -- 1. Termux listener mode is real and resident -----------------------

    async def test_termux_listener_mode_activates_and_stays_resident(self):
        engine = await self._boot_engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion, status")
        svc = _termux_service(engine, clock, stt)
        self._services.append(svc)

        res = await svc.start()
        self.assertEqual(res["status"], "STARTED")
        # The Termux primary path is active: the listener loop IS the mic.
        self.assertTrue(svc._termux_listener_mode)
        self.assertEqual(svc.phase, MicPhase.LISTENING)
        self.assertTrue(svc.is_listening)
        self.assertEqual(svc.mic_status(), "LISTENING")
        self.assertEqual(svc.health(), VoiceHealth.HEALTHY)
        self.assertEqual(svc._stt_provider, "injected_stt")
        self.assertIsNotNone(svc._listener_task)
        self.assertFalse(svc._listener_task.done())
        self.assertIn("VOICE_MIC_ACTIVE",
                      _event_types_on_bus(engine, "voice_perception"))

    # -- 2. readiness semantics: AVAILABLE — NOT PROBED, then READY ---------

    async def test_stt_readiness_is_earned_by_a_real_transcript(self):
        # Wire the ENGINE's own perception service to the Termux path so the
        # readiness banner reflects the same object the user sees.
        d = tempfile.mkdtemp(prefix="termux_readiness_")
        self._dirs.append(d)
        engine = AscendantEngine(data_dir=d)
        engine.voice_env._stt_cache = TermuxSTTEnvironment()._stt_cache
        stt = ScriptedSTT("Zerion, status")
        engine.voice_perception._stt_transcriber = stt
        await engine.start()
        self._engine = engine
        self._services.append(engine.voice_perception)

        # Before any utterance: the engine exists but was never probed.
        banner = engine.local_readiness()
        self.assertEqual(banner["stt"]["display_status"],
                         "AVAILABLE — NOT PROBED")
        self.assertNotEqual(banner["stt"]["display_status"], "READY")
        self.assertEqual(banner["microphone"]["status"], "LISTENING")

        # One real utterance lands a transcript -> READY is earned.
        ok = await _wait_until(
            lambda: engine.voice_perception._stt_success_count >= 1)
        self.assertTrue(ok, "no transcript was produced")
        banner = engine.local_readiness()
        self.assertEqual(banner["stt"]["display_status"], "READY")
        self.assertTrue(engine.voice_perception.is_listening)

    # -- 3. transcript -> VOICE_TRANSCRIPT_FINAL -> cognition ----------------

    async def test_transcript_reaches_cognition_and_emits_event(self):
        engine = await self._boot_engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion, status")
        svc = _termux_service(engine, clock, stt)
        self._services.append(svc)
        await svc.start()

        ok = await _wait_until(lambda: _turns_done(svc, 1))
        self.assertTrue(ok, "voice turn never completed")
        self.assertEqual(svc._stt_success_count, 1)

        finals = [x for x in engine.ui_adapter.event_history(1000)
                  if x["event_type"] == "VOICE_TRANSCRIPT_FINAL"]
        self.assertTrue(finals, "VOICE_TRANSCRIPT_FINAL never reached the bus")
        payload = finals[0]["payload"]
        # Event contract (mission §5): structured final event.
        self.assertEqual(payload.get("type"), "VOICE_TRANSCRIPT_FINAL")
        self.assertIn("text", payload)
        self.assertEqual(payload.get("text"), "Zerion, status")
        self.assertIn("timestamp", payload)
        self.assertEqual(payload.get("source"), "local_stt")

        # The transcript reached the REAL cognitive pipeline with a response.
        self.assertIsNotNone(svc._last_turn)
        self.assertTrue(svc._last_response)
        self.assertIn("VOICE_RESPONSE_READY",
                      _event_types_on_bus(engine, "voice_pipeline"))

    # -- 4. repeated listening (mission §14: 3 consecutive commands) ---------

    async def test_three_consecutive_utterances(self):
        engine = await self._boot_engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion, status",
                          "second command", "third command")
        svc = _termux_service(engine, clock, stt)
        self._services.append(svc)
        await svc.start()

        ok = await _wait_until(lambda: _turns_done(svc, 3))
        self.assertTrue(ok, f"only {svc._turns_processed}/3 turns processed")
        self.assertEqual(svc._turns_processed, 3)
        self.assertEqual(svc._stt_success_count, 3)
        # Still listening after three interactions — the loop never exits.
        self.assertTrue(svc.is_listening)
        self.assertEqual(svc.phase, MicPhase.LISTENING)

    # -- 5. STT failure keeps the runtime alive ------------------------------

    async def test_stt_failure_is_controlled_and_runtime_stays_alive(self):
        engine = await self._boot_engine()
        clock = FakeClock()
        stt = FailingSTT()
        svc = _termux_service(engine, clock, stt)
        self._services.append(svc)
        await svc.start()

        ok = await _wait_until(
            lambda: "VOICE_STT_UNAVAILABLE"
            in _event_types_on_bus(engine, "voice_perception"))
        self.assertTrue(ok, "controlled STT failure event never emitted")
        self.assertGreaterEqual(svc._stt_unavailable_count, 1)
        # No fabricated transcript, no turn, service alive and listening.
        self.assertEqual(svc._stt_success_count, 0)
        self.assertEqual(svc._turns_processed, 0)
        self.assertTrue(svc._started)
        self.assertTrue(svc.is_listening)
        self.assertEqual(svc.phase, MicPhase.LISTENING)

    # -- 6. empty transcript is ignored safely --------------------------------

    async def test_empty_transcript_ignored_and_loop_continues(self):
        engine = await self._boot_engine()
        clock = FakeClock()
        stt = EmptySTT()
        svc = _termux_service(engine, clock, stt)
        self._services.append(svc)
        await svc.start()

        ok = await _wait_until(lambda: stt.calls >= 2)
        self.assertTrue(ok, "listener stopped after empty transcripts")
        # Empty input: no turn, no event, no fabrication, still listening.
        self.assertEqual(svc._turns_processed, 0)
        self.assertEqual(svc._stt_success_count, 0)
        self.assertTrue(svc.is_listening)
        self.assertEqual(svc.phase, MicPhase.LISTENING)

    # -- 7. STT failure followed by a successful utterance (recovery) --------

    async def test_recovery_from_stt_failure_then_success(self):
        engine = await self._boot_engine()
        clock = FakeClock()

        class FlakySTT:
            def __init__(self):
                self.calls = 0

            async def __call__(self, segment) -> STTResult:
                self.calls += 1
                if self.calls == 1:
                    return STTResult("STT_ERROR", provider="injected_stt",
                                     reason="first attempt failed",
                                     simulated=True)
                return STTResult("SUCCESS", transcript="Zerion, status",
                                 provider="injected_stt", simulated=True)

        stt = FlakySTT()
        svc = _termux_service(engine, clock, stt)
        self._services.append(svc)
        await svc.start()

        # The first (failed) capture must not kill the loop: the next capture
        # succeeds and produces a real turn.
        ok = await _wait_until(lambda: _turns_done(svc, 1))
        self.assertTrue(ok, "no recovery turn after STT failure")
        self.assertGreaterEqual(svc._stt_unavailable_count, 1)
        self.assertGreaterEqual(svc._turns_processed, 1)
        self.assertTrue(svc.is_listening)

    # -- 8. provider unavailable -> honest state, no false READY -------------

    async def test_provider_unavailable_reports_honest_state(self):
        engine = await self._boot_engine()
        banner = engine.local_readiness()
        # This container has no STT engine: the banner must NOT claim READY.
        self.assertNotEqual(banner["stt"]["display_status"], "READY")
        self.assertIn(banner["stt"]["display_status"],
                      ("UNAVAILABLE", "AVAILABLE — NOT PROBED"))
        # And the microphone must not claim LISTENING without a real backend.
        self.assertNotEqual(banner["microphone"]["status"], "LISTENING")
        self.assertFalse(engine.voice_perception.is_listening)

    # -- 9. offline guarantee: no online adapter is ever invoked -------------

    async def test_offline_path_never_touches_online_stt(self):
        engine = await self._boot_engine()
        clock = FakeClock()
        stt = ScriptedSTT("Zerion, status")
        svc = _termux_service(engine, clock, stt)
        self._services.append(svc)
        # Explicitly forbid online fallback — the canonical default.
        self.assertFalse(svc.allow_online_stt)
        await svc.start()
        ok = await _wait_until(lambda: _turns_done(svc, 1))
        self.assertTrue(ok, "offline turn never completed")
        # The turn's offline mode comes from the REAL pulse routing.
        self.assertEqual(svc._last_turn.get("offline_mode"), "OFFLINE_ONLY")
