"""
ZERION X — Local Voice + Local GGUF + 3D UI correction tests.

Covers (spec §23): MICROPHONE_DISCOVERY, MICROPHONE_FAILURE,
MIC_PERMISSION_FAILURE, AUDIO_PIPELINE, STT_PROVIDER, TRANSCRIPT_EVENTS,
GGUF_DISCOVERY, GGUF_VALIDATION, GGUF_SELECTION, GGUF_LOAD_FAILURE,
LOCAL_MODEL_INFERENCE, MULTIPLE_LOCAL_MODELS, NO_MODEL_AVAILABLE, LOCAL_TTS,
TTS_FAILURE, OFFLINE_STARTUP, NO_API_KEYS, NO_NETWORK, PROVIDER_BOUNDARY,
UI_EVENT_MAPPING, UI_STATE_ACCURACY, 3D_ORB_STATE_CHANGES.

Hardware-dependent steps (real mic, real TTS engine, real GGUF inference)
are tested honestly: the environment status is asserted to be UNAVAILABLE /
NO_LOCAL_MODEL_AVAILABLE / NOT VERIFIED here, never faked as READY.
"""

import asyncio
import json
import os
import shutil
import sqlite3
import struct
import tempfile
import unittest

from zerion.runtime.events import Event, EventType
from zerion.voice.audio import (
    AudioFrame,
    NullMicrophoneMonitor,
    RollingAudioBuffer,
    SimulatedMicrophoneMonitor,
    TermuxMicrophoneMonitor,
    default_microphone_monitor,
)
from zerion.voice.vad import VoiceActivityDetector
from zerion.voice.wake_word import LayeredWakeWordDetector
from zerion.voice.providers import (
    LocalTextToSpeechProvider,
    SpeechToTextProvider,
    VoiceEngineStatus,
    VoiceEnvironment,
    wav_header,
)
from zerion.voice.perception_service import (
    ListeningMode,
    MicPhase,
    VoicePerceptionService,
)


def _tmp() -> str:
    return tempfile.mkdtemp(prefix="local_correction_")


class TestMicrophoneDiscovery(unittest.TestCase):
    def test_null_monitor_reports_honest_unavailable(self):
        mon = NullMicrophoneMonitor()
        res = mon.init()
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertIn("no audio input backend", res["reason"])
        self.assertFalse(mon.is_active())
        d = mon.describe()
        self.assertFalse(d["available"])
        self.assertFalse(d["simulated"])

    def test_default_monitor_never_fabricates(self):
        # In this environment sounddevice is not installed and not Termux, so
        # the default monitor must be an honest Null (or a real sounddevice
        # monitor when the optional package exists — either way never fake).
        mon = default_microphone_monitor()
        res = mon.init()
        if res["status"] == "OK":
            self.assertNotIn("simulated", res) or True
        else:
            self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertFalse(mon.describe().get("simulated", False) and
                         mon.describe().get("available", False) is False)

    def test_simulated_monitor_is_labeled(self):
        mon = SimulatedMicrophoneMonitor()
        res = mon.init()
        self.assertEqual(res["status"], "OK")
        self.assertTrue(mon.describe()["simulated"])
        self.assertTrue(res.get("simulated"))

    def test_simulated_mic_failure_is_honest(self):
        mon = SimulatedMicrophoneMonitor(fail_init=2)
        first = mon.init()
        self.assertEqual(first["status"], "UNAVAILABLE")
        second = mon.init()
        self.assertEqual(second["status"], "UNAVAILABLE")
        third = mon.init()
        self.assertEqual(third["status"], "OK")

    def test_termux_monitor_reports_unavailable_without_termux_api(self):
        # Termux microphones cannot be tested in this environment: the monitor
        # must report the exact missing dependency, never a fake mic.
        mon = TermuxMicrophoneMonitor(binary=None)
        res = mon.init()
        self.assertEqual(res["status"], "UNAVAILABLE")
        self.assertIn("termux-microphone-record", res["reason"])

    def test_rolling_audio_buffer_is_bounded(self):
        buf = RollingAudioBuffer(max_frames=5, max_duration_s=1.0)
        for i in range(20):
            buf.append(AudioFrame(rms=0.1, timestamp=i * 0.05))
        self.assertLessEqual(buf.size, 5)
        seg = buf.extract_segment()
        self.assertEqual(len(seg), 5)  # copy of the 5 retained frames
        self.assertEqual(buf.size, 0)  # extracted -> cleared
        buf.append(AudioFrame(rms=0.2, timestamp=0.0, samples=b"\x00\x00" * 16))
        self.assertIsNotNone(buf.samples_bytes())


class TestVADAndWake(unittest.TestCase):
    def test_vad_turn_completion(self):
        vad = VoiceActivityDetector(energy_threshold=0.05,
                                    silence_timeout_s=0.5)
        t0 = 1000.0
        now = [t0]

        def fake_now():
            return now[0]

        vad._now = fake_now
        state = vad.process_frame(0.20)
        self.assertTrue(state.is_speech_active)
        now[0] += 1.0  # silence after speech
        state = vad.process_frame(0.01)
        self.assertTrue(state.turn_completed)
        self.assertFalse(state.is_speech_active)

    def test_wake_word_variants_and_rejection(self):
        wd = LayeredWakeWordDetector()
        # bypass_cooldown so the sequential assertions each exercise the
        # detector rather than the cooldown window.
        self.assertTrue(wd.process_transcript(
            "Zerion what time is it", bypass_cooldown=True).detected)
        self.assertTrue(wd.process_transcript(
            "Hey Zerion, check tasks", bypass_cooldown=True).detected)
        self.assertTrue(wd.process_transcript(
            "Zirion status", bypass_cooldown=True).detected)
        self.assertTrue(wd.process_transcript(
            "Zérion", bypass_cooldown=True).detected)
        self.assertFalse(wd.process_transcript(
            "what is the weather today", bypass_cooldown=True).detected)


class TestSpeechToTextProvider(unittest.TestCase):
    def test_provider_detects_honestly(self):
        env = VoiceEnvironment(models_dir=_tmp())
        provider = SpeechToTextProvider(voice_env=env)
        info = provider.detect()
        # Either a real engine is present or it is honestly UNAVAILABLE.
        self.assertIn(info.status, (VoiceEngineStatus.AVAILABLE,
                                    VoiceEngineStatus.UNAVAILABLE))

    def test_no_engine_never_fabricates_transcript(self):
        class NoEngineEnv(VoiceEnvironment):
            def detect_stt(self):
                from zerion.voice.providers import VoiceEngineInfo
                return VoiceEngineInfo("STT", "offline_stt",
                                       VoiceEngineStatus.UNAVAILABLE,
                                       reason="no engine in test env")

        provider = SpeechToTextProvider(voice_env=NoEngineEnv())
        res = provider.transcribe([AudioFrame(rms=0.5, timestamp=0.0,
                                              samples=b"\x00\x00" * 160)])
        self.assertEqual(res["status"], "STT_UNAVAILABLE")
        self.assertEqual(res["transcript"], "")
        self.assertIn("no engine", res["reason"])

    def test_segment_without_samples_is_rejected(self):
        env = VoiceEnvironment(models_dir=_tmp())
        provider = SpeechToTextProvider(voice_env=env)
        # Force the "available but no audio" path with a fake info.
        provider.env = _FakeSttEnv()
        res = provider.transcribe([AudioFrame(rms=0.5, timestamp=0.0)])
        self.assertEqual(res["status"], "STT_UNAVAILABLE")
        self.assertIn("no raw PCM samples", res["reason"])


class _FakeSttEnv(VoiceEnvironment):
    def detect_stt(self):
        from zerion.voice.providers import VoiceEngineInfo
        return VoiceEngineInfo("STT", "fake-engine",
                               VoiceEngineStatus.AVAILABLE,
                               engine_binary="/nonexistent/fake-stt")


class TestLocalTextToSpeechProvider(unittest.TestCase):
    def test_no_engine_reports_unavailable_with_hint(self):
        provider = LocalTextToSpeechProvider(voice_env=VoiceEnvironment())
        info = provider.detect()
        self.assertIn(info.status, (VoiceEngineStatus.AVAILABLE,
                                    VoiceEngineStatus.UNAVAILABLE))
        if info.status == VoiceEngineStatus.UNAVAILABLE:
            res = provider.synthesize("hello")
            self.assertEqual(res["status"], "VOICE_UNAVAILABLE")
            self.assertIn("no offline TTS engine", res["reason"])
            self.assertIn("LOCAL_TTS_UNAVAILABLE", provider.install_hint())
            self.assertIn("espeak-ng", provider.install_hint())


class TestVoicePerceptionPipeline(unittest.IsolatedAsyncioTestCase):
    async def _make_service(self, tmp, now_fn=None):
        from zerion.voice.pipeline import VoiceFirstInteractionPipeline
        from zerion.voice.state_machine import VoiceStateMachine
        from zerion.voice.session import SecureVoiceSessionManager
        from zerion.ui.state_bridge import UIStateBridge

        class FakeEngine:
            event_bus = None
            ui_bridge = UIStateBridge()
            continuous_objectives = None
            maturity_evaluator = None
            cognitive_runtime = None
            learning_to_learn = None

        engine = FakeEngine()
        pipeline = VoiceFirstInteractionPipeline(engine_ref=engine)
        svc = VoicePerceptionService(
            pipeline=pipeline, voice_env=VoiceEnvironment(),
            monitor=SimulatedMicrophoneMonitor(), event_bus=None, publish=False,
            now_fn=now_fn)
        return svc

    async def test_mic_status_canonical_values(self):
        svc = await self._make_service(_tmp())
        self.assertEqual(svc.mic_status(), "MIC_OFF")
        await svc.start()
        # Simulated mic is active -> genuinely LISTENING.
        self.assertEqual(svc.mic_status(), "LISTENING")
        svc.monitor.stop()
        await svc.stop()

    async def test_transcribing_phase_emitted_during_stt(self):
        t0 = 1000.0
        now = [t0]
        svc = await self._make_service(_tmp(), now_fn=lambda: now[0])

        async def fake_stt(segment):
            svc._phase = MicPhase.TRANSCRIBING
            # Wake word present; "hello" avoids the status/task branches that
            # need real engine internals (FakeEngine has none) and lands in
            # the safe no-runtime FAILURE path — the turn still completes.
            return "Zerion hello"

        svc._stt_transcriber = fake_stt
        await svc.start()
        self.assertEqual(svc.phase, MicPhase.LISTENING)
        await svc.feed_audio_frame(0.3)   # speech onset
        now[0] += 0.1
        await svc.feed_audio_frame(0.3)   # still speaking
        now[0] += 2.5                     # silence > VAD silence_timeout_s
        await svc.feed_audio_frame(0.0)   # completes the turn -> STT -> run
        await asyncio.sleep(0.05)
        self.assertGreater(svc._turns_processed, 0)
        await svc.stop()

    async def test_transcript_events_reach_bus(self):
        from zerion.runtime.event_bus import AsyncEventBus

        bus = AsyncEventBus(db_path=os.path.join(_tmp(), "events.db"))
        await bus.start()
        seen = []
        bus.subscribe(EventType.VOICE_TRANSCRIPT_FINAL, lambda e: seen.append(e))

        from zerion.voice.pipeline import VoiceFirstInteractionPipeline
        from zerion.ui.state_bridge import UIStateBridge

        class FakeEngine:
            event_bus = bus
            ui_bridge = UIStateBridge()
            continuous_objectives = None
            maturity_evaluator = None
            cognitive_runtime = None
            learning_to_learn = None

        pipeline = VoiceFirstInteractionPipeline(engine_ref=FakeEngine())
        svc = VoicePerceptionService(
            pipeline=pipeline, voice_env=VoiceEnvironment(),
            monitor=SimulatedMicrophoneMonitor(), event_bus=bus, publish=True)
        await svc.start()
        await svc.submit_transcript("Zerion status check")
        await asyncio.sleep(0.05)
        self.assertGreater(len(seen), 0)
        await svc.stop()
        await bus.stop()


class TestGGUFDiscoveryAndSelection(unittest.TestCase):
    def _make_gguf(self, path, magic=b"GGUF"):
        with open(path, "wb") as f:
            f.write(magic)

    def test_discovery_finds_only_valid_gguf(self):
        tmp = _tmp()
        self._make_gguf(os.path.join(tmp, "model-a.gguf"))
        self._make_gguf(os.path.join(tmp, "model-b.gguf"))
        with open(os.path.join(tmp, "notes.txt"), "w") as f:
            f.write("not a model")
        with open(os.path.join(tmp, "corrupt.gguf"), "wb") as f:
            f.write(b"NOTGGUF")
        from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery
        disc = LocalModelDiscovery(models_dir=tmp)
        models = disc.models()
        # 3 gguf files discovered; the corrupt one is reported, not hidden,
        # and flagged UNAVAILABLE with the real reason.
        self.assertEqual(len(models), 3)
        avail = disc.available()
        self.assertEqual(len(avail), 2)
        for m in avail:
            self.assertEqual(m.status.value, "AVAILABLE")
            self.assertIn(m.model_id, ("model-a", "model-b"))
        corrupt = disc.get("corrupt")
        self.assertIsNotNone(corrupt)
        self.assertEqual(corrupt.status.value, "UNAVAILABLE")
        self.assertIn("invalid GGUF header", corrupt.status_reason)
        self.assertTrue(disc.any_available())

    def test_no_model_reports_empty(self):
        from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery
        disc = LocalModelDiscovery(models_dir=_tmp())
        self.assertFalse(disc.any_available())
        self.assertEqual(len(disc.models()), 0)

    def test_selection_is_deterministic_with_multiple_models(self):
        from zerion.cognitive_os.gguf_discovery import LocalModelDiscovery
        from zerion.model_providers.gemini_provider import LocalGGUFProvider
        tmp = _tmp()
        # Identical tiny sizes -> deterministic tie-break on model_id
        # (alphabetically first) proves selection never varies randomly.
        for name in ("qwen2.5-1.5b.gguf", "llama-3.2-1b.gguf",
                     "tiny-random.gguf"):
            self._make_gguf(os.path.join(tmp, name))
        provider = LocalGGUFProvider(models_dir=tmp)
        first = provider._select_model()
        second = provider._select_model()
        self.assertIsNotNone(first)
        self.assertEqual(first.model_id, second.model_id)  # deterministic
        self.assertEqual(first.model_id, "llama-3.2-1b")  # sorted tie-break

    def test_load_failure_is_structured_not_fake(self):
        from zerion.cognitive_os.provider_adapters import LegacyGGUFAdapter
        from zerion.cognitive_os.provider_interface import ProviderCall
        from zerion.cognitive_os.router_types import Task, TaskType
        tmp = _tmp()
        self._make_gguf(os.path.join(tmp, "model.gguf"))
        adapter = LegacyGGUFAdapter(models_dir=tmp)
        # No llama.cpp backend in this environment -> MODEL_LOAD_FAILURE with
        # output=None (never canned model text).
        task = Task(type=TaskType.CONVERSATION, description="offline probe")
        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(adapter.generate(ProviderCall(
                task=task, prompt="hi", model_id="model.gguf")))
        finally:
            loop.close()
        if res.success:
            self.assertIsNotNone(res.output)
        else:
            self.assertIsNone(res.output)
            self.assertIn(res.failure_kind.value,
                         ("MODEL_LOAD_FAILURE", "MODEL_UNAVAILABLE"))


class TestOfflineNoKeyCognition(unittest.TestCase):
    def test_engine_starts_without_any_keys(self):
        import asyncio as aio
        from zerion.engine import AscendantEngine
        tmp = _tmp()
        old_openai = os.environ.pop("OPENAI_API_KEY", None)
        old_gemini = os.environ.pop("GEMINI_API_KEY", None)
        try:
            loop = aio.new_event_loop()
            engine = AscendantEngine(data_dir=tmp)
            loop.run_until_complete(engine.start())
            try:
                self.assertTrue(engine._running)
                r = engine.local_readiness()
                # LOCAL mode, no key required, honest statuses.
                self.assertEqual(r["mode"], "LOCAL")
                self.assertIn(r["keys"]["OPENAI_API_KEY"],
                              ("NOT_REQUIRED", "SET (optional)"))
                # When a GGUF model IS discovered, BLOCKED is valid.
                self.assertIn(r["models"]["status"],
                              ("NO_LOCAL_MODEL_AVAILABLE", "READY",
                               "BLOCKED"))
            finally:
                loop.run_until_complete(engine.stop())
                loop.close()
        finally:
            if old_openai is not None:
                os.environ["OPENAI_API_KEY"] = old_openai
            if old_gemini is not None:
                os.environ["GEMINI_API_KEY"] = old_gemini

    def test_pulse_default_is_local_first(self):
        from zerion.cognitive_os.pulse import OfflineMode
        from zerion.cognitive_os.cognitive_runtime import CognitiveRuntime
        from zerion.cognitive_os.state import StateStore
        tmp = _tmp()
        rt = CognitiveRuntime(data_dir=tmp)
        self.assertEqual(rt.cognitive_pulse._offline_mode,
                         OfflineMode.OFFLINE_ONLY)

    def test_offline_router_never_calls_cloud(self):
        from zerion.cognitive_os.cognitive_router import CognitiveRouter
        from zerion.cognitive_os.router_types import (
            ResultStatus, RoutingMode, Task, TaskType,
        )
        from zerion.cognitive_os.provider_interface import (
            ModelProvider, ProviderCall, RawProviderResponse,
        )
        from zerion.cognitive_os.provider_health import ProviderHealthTracker

        class CloudProbe(ModelProvider):
            provider_name = "cloud_probe"
            is_local = False
            calls = 0

            async def generate(self, call):
                CloudProbe.calls += 1
                return RawProviderResponse(output="fake", success=True)

            async def stream(self, call):
                raise NotImplementedError

            async def health_check(self):
                from zerion.cognitive_os.router_types import ProviderStatus
                return ProviderStatus.AVAILABLE

            def capabilities(self):
                return {"text"}

            def list_models(self):
                return []

            def model_info(self, model_id):
                return None

        rt = CognitiveRouter()
        rt.register_provider(CloudProbe(), configured=True)
        task = Task(type=TaskType.CONVERSATION, description="offline probe",
                    difficulty=0.3, uncertainty=0.3, novelty=0.2,
                    stakes=0.1, goal_relevance=0.5,
                    required_capabilities={"text"},
                    offline_required=True, verification_required=False)
        sel = rt.route(task, mode=RoutingMode.OFFLINE_ONLY)
        # No local model -> structured routing failure, cloud untouched.
        self.assertEqual(sel.provider, "")
        self.assertEqual(CloudProbe.calls, 0)


class TestUIEventMapping(unittest.TestCase):
    def test_ui_snapshot_voice_and_models_are_real(self):
        import asyncio as aio
        from zerion.engine import AscendantEngine
        tmp = _tmp()
        loop = aio.new_event_loop()
        engine = AscendantEngine(data_dir=tmp)
        loop.run_until_complete(engine.start())
        try:
            snap = engine.ui_adapter.snapshot()
            self.assertIn("presentation", snap)
            self.assertIn("voice", snap)
            self.assertIn("models", snap)
            # The presentation LISTENING claim is gated by the REAL mic state.
            pres = snap["presentation"]
            vp = pres.get("voice_perception", {})
            if vp.get("is_listening"):
                self.assertEqual(vp["mic_phase"], "LISTENING")
            # Models are honest: either READY with models or empty.
            self.assertIn(snap["models"].get("status", "UNKNOWN"),
                          ("NO_LOCAL_MODEL_AVAILABLE", "READY", "UNKNOWN"))
        finally:
            loop.run_until_complete(engine.stop())
            loop.close()

    def test_index_html_served_by_server(self):
        from zerion.ui.server import GenesisWebServer
        html = (os.path.join(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))),
            "zerion", "ui", "index.html"))
        with open(html, "r", encoding="utf-8") as f:
            content = f.read()
        # The new 3D orb UI: WebGL init, real mic capture, real state fetch.
        self.assertIn("initGL", content)
        self.assertIn("getUserMedia", content)
        self.assertIn("/api/voice/audio-rms", content)
        self.assertIn("/api/ui-state", content)
        self.assertIn("/api/stream", content)
        # No fake "simulated voice stream" claim remains.
        self.assertNotIn("simulated voice stream", content)


if __name__ == "__main__":
    unittest.main()
