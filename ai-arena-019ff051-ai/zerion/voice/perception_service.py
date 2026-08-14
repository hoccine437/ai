"""
VoicePerceptionService — Slice 10.1.

ZERION is an ALWAYS-AVAILABLE voice-first system: the microphone pipeline runs
continuously whenever the operating system and hardware permit it, with no UI
open and no button press required. The normal state is LISTENING, not
WAITING_FOR_BUTTON.

Architecture (strict separation — this service is the perception organ, never
the cognitive engine):

    MICROPHONE
      -> AudioInputMonitor (continuous)
        -> RollingAudioBuffer (bounded, in-memory only)
          -> VAD (real energy segmentation, no silence sent to STT)
            -> WAKE MODE / ACTIVE CONVERSATION
              -> local-first STT chain
                -> VOICE EVENT -> existing VoiceFirstInteractionPipeline
                  -> CognitiveRuntime
                    -> RESPONSE -> TTS -> return to LISTENING

HONESTY RULES (spec 17/20):
- The service only ever reports LISTENING when the microphone pipeline is
  genuinely active (phase LISTENING + monitor.is_active()).
- It never claims "I heard you" without an actual transcript/event.
- STT failures record STT_UNAVAILABLE; transcripts are never fabricated.
- When the OS/hardware denies the microphone the service reports the exact
  limitation (UNAVAILABLE / PAUSED_BY_SYSTEM) and recovers when possible.
- Simulated monitors are always labeled ``simulated=True`` in telemetry.

This module contains no goal logic, attention logic, question generation,
hypothesis logic, belief revision, experiment logic, benchmark logic or
self-modification logic — all cognition stays in the Slice 1-9 subsystems.
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Callable, Dict, List, Optional

from zerion.runtime.events import Event, EventType
from zerion.voice.audio import (
    AudioFrame,
    AudioInputMonitor,
    NullMicrophoneMonitor,
    RollingAudioBuffer,
    default_microphone_monitor,
)
from zerion.voice.vad import VoiceActivityDetector, VADState
from zerion.voice.wake_word import LayeredWakeWordDetector
from zerion.voice.providers import (
    SpeechToTextProvider,
    VoiceEngineStatus,
    VoiceEnvironment,
)
from zerion.voice.state_machine import VoiceState
from zerion.voice.watchdog import VoiceWatchdog


class ListeningMode(str, Enum):
    WAKE_MODE = "WAKE_MODE"
    ACTIVE_CONVERSATION = "ACTIVE_CONVERSATION"


class MicPhase(str, Enum):
    """Exposed microphone state (spec 16), plus PAUSED_BY_SYSTEM (spec 12)."""
    MIC_OFF = "MIC_OFF"
    MIC_INITIALIZING = "MIC_INITIALIZING"
    LISTENING = "LISTENING"
    SPEECH_DETECTED = "SPEECH_DETECTED"
    TRANSCRIBING = "TRANSCRIBING"
    TRANSCRIPT_READY = "TRANSCRIPT_READY"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    RECOVERING = "RECOVERING"
    PAUSED_BY_SYSTEM = "PAUSED_BY_SYSTEM"
    UNAVAILABLE = "UNAVAILABLE"


class VoiceHealth(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class STTResult:
    status: str  # SUCCESS | STT_UNAVAILABLE | STT_ERROR
    transcript: str = ""
    provider: Optional[str] = None
    reason: str = ""
    latency_ms: float = 0.0
    simulated: bool = False


class VoicePerceptionService:
    def __init__(
        self,
        pipeline: Any,                      # VoiceFirstInteractionPipeline
        voice_env: Optional[VoiceEnvironment] = None,
        event_bus: Any = None,
        monitor: Optional[AudioInputMonitor] = None,
        wake_detector: Optional[LayeredWakeWordDetector] = None,
        vad: Optional[VoiceActivityDetector] = None,
        stt_transcriber: Optional[Callable[[List[AudioFrame]],
                                           Any]] = None,
        active_conversation_timeout_s: float = 15.0,
        barge_in_rms: float = 0.20,
        mic_retry_base_s: float = 1.0,
        mic_retry_max_s: float = 30.0,
        mic_retry_max_attempts: int = 6,
        retention_s: float = 8.0,
        allow_online_stt: bool = False,
        watchdog: Optional[VoiceWatchdog] = None,
        watchdog_interval_s: float = 5.0,
        now_fn: Optional[Callable[[], float]] = None,
        sleep_fn: Optional[Callable[[float], Any]] = None,
        publish: bool = True,
    ):
        self.pipeline = pipeline
        self.voice_env = voice_env or VoiceEnvironment()
        self.event_bus = event_bus
        self._now = now_fn or time.time
        self._sleep = sleep_fn or asyncio.sleep
        self._publish_enabled = publish

        # Real microphone monitor; default picks sounddevice when present else
        # an honest Null monitor. A simulation is never presented as hardware.
        self.monitor = monitor or default_microphone_monitor(
            on_frame=self._enqueue_frame, now_fn=self._now)

        self.wake_detector = wake_detector or LayeredWakeWordDetector()
        self.vad = vad or VoiceActivityDetector(now_fn=self._now)
        # Canonical local-first STT provider (Slice 10.1). Real offline engine
        # detection + execution; the cognitive runtime only ever consumes
        # structured transcript events.
        self.stt_provider = SpeechToTextProvider(voice_env=self.voice_env)
        self._stt_transcriber = stt_transcriber  # injectable (tests/demos)

        self.active_conversation_timeout_s = active_conversation_timeout_s
        self.barge_in_rms = barge_in_rms
        self.mic_retry_base_s = mic_retry_base_s
        self.mic_retry_max_s = mic_retry_max_s
        self.mic_retry_max_attempts = mic_retry_max_attempts
        self.retention_s = retention_s
        self.allow_online_stt = allow_online_stt

        self.watchdog = watchdog or VoiceWatchdog(now_fn=self._now)
        self._wire_watchdog()
        self._watchdog_interval_s = watchdog_interval_s

        self._buffer = RollingAudioBuffer(max_duration_s=retention_s)
        # The frame queue is created in start() so it binds to the running
        # event loop (the engine may be constructed outside a loop).
        self._frame_queue: Optional[asyncio.Queue] = None

        self._started = False
        self._phase = MicPhase.MIC_OFF
        self._mode = ListeningMode.WAKE_MODE
        self._mic_available = False
        self._mic_reason = ""
        self._mic_simulated = False
        self._segment_active = False
        self._segment_start: Optional[float] = None
        self._processing = False
        self._processing_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._consumer_task: Optional[asyncio.Task] = None

        self._last_activity = 0.0
        self._conversation_started_at: Optional[float] = None
        self._last_turn: Optional[Dict[str, Any]] = None
        self._last_tts_status: str = "NOT_ATTEMPTED"
        self._last_response: str = ""

        # Measured counters (never invented).
        self._frames_total = 0
        self._speech_segments = 0
        self._wake_detections = 0
        self._turns_processed = 0
        self._barge_ins = 0
        self._stt_unavailable_count = 0
        self._mic_recovery_attempts = 0
        self._stt_status = "UNKNOWN"
        self._stt_provider: Optional[str] = None
        self._started_at = 0.0
        self._cpu_start = 0.0

    # -- read-only public state (UI-safe; no mutation of internals) ---------

    @property
    def phase(self) -> MicPhase:
        """Real microphone phase. LISTENING only ever means the mic pipeline
        is genuinely active — never a print() assumption."""
        return self._phase

    @property
    def mode(self) -> ListeningMode:
        return self._mode

    # ======================================================================
    # lifecycle
    # ======================================================================

    async def start(self) -> Dict[str, Any]:
        if self._started:
            return {"status": "ALREADY_STARTED", "phase": self._phase.value}
        self._started = True
        self._started_at = self._now()
        self._cpu_start = time.process_time()
        self._frame_queue = asyncio.Queue(maxsize=256)
        await self._publish(EventType.VOICE_PERCEPTION_STARTED, {
            "service": "voice_perception",
            "independent_of_ui": True,
        }, priority=80)

        self._consumer_task = asyncio.create_task(self._frame_consumer())
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

        ok = await self._initialize_microphone()

        # STT status from the REAL environment (honest detection). An injected
        # transcriber (test/demo harness) counts as available but is always
        # labeled ``injected_stt`` so a simulation is never mistaken for a
        # real engine.
        stt_info = self.voice_env.detect_stt()
        self._stt_status = stt_info.status
        self._stt_provider = stt_info.name if stt_info.status == "AVAILABLE" \
            else None
        if self._stt_transcriber is not None:
            self._stt_status = VoiceEngineStatus.AVAILABLE
            self._stt_provider = "injected_stt"

        return {"status": "STARTED", "mic_available": ok,
                "phase": self._phase.value,
                "health": self.health().value,
                "stt": self._stt_status}

    async def stop(self) -> Dict[str, Any]:
        if not self._started:
            return {"status": "STOPPED", "phase": "MIC_OFF"}
        self._started = False
        for task in (self._consumer_task, self._monitor_task,
                     self._watchdog_task):
            if task is not None and not task.done():
                task.cancel()
        if self._processing_task is not None and not self._processing_task.done():
            self._processing_task.cancel()
        self._consumer_task = self._monitor_task = self._watchdog_task = None
        try:
            self.monitor.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self.pipeline.stop_listening()
        except Exception:  # noqa: BLE001
            pass
        self._phase = MicPhase.MIC_OFF
        self._mode = ListeningMode.WAKE_MODE
        self._buffer.clear()
        await self._publish(EventType.VOICE_PERCEPTION_STOPPED, {
            "phase": self._phase.value,
        }, priority=80)
        return {"status": "STOPPED", "phase": self._phase.value}

    async def _initialize_microphone(self) -> bool:
        """Open the microphone with bounded exponential backoff.

        Permanent unavailability (no backend, OS denial) is reported once —
        never an infinite retry loop. Transient failures (device busy, device
        swapped) retry with bounded exponential backoff up to
        ``mic_retry_max_attempts``.
        """
        self._phase = MicPhase.MIC_INITIALIZING
        await self._publish(EventType.VOICE_MIC_INITIALIZING, {
            "monitor": self.monitor.describe(),
        })
        attempts = 0
        while True:
            attempts += 1
            res = self.monitor.init()
            if res.get("status") == "OK":
                self._mic_available = True
                self._mic_reason = ""
                self._mic_simulated = bool(res.get("simulated", False))
                self._start_monitor_loop()
                self._phase = MicPhase.LISTENING
                self._last_activity = self._now()
                self.watchdog.beat("mic_capture")
                self.watchdog.beat("audio_capture")
                await self._publish(EventType.VOICE_MIC_ACTIVE, {
                    "device": res.get("device"),
                    "simulated": self._mic_simulated,
                    "monitor": self.monitor.describe(),
                })
                return True
            transient = bool(res.get("transient", True))
            reason = self._enrich_mic_reason(
                res.get("reason", "microphone unavailable"))
            if not transient or attempts >= self.mic_retry_max_attempts:
                self._mic_available = False
                self._mic_reason = reason
                self._phase = MicPhase.UNAVAILABLE
                await self._publish(EventType.VOICE_MIC_UNAVAILABLE, {
                    "reason": reason, "attempts": attempts,
                    "transient": transient,
                    "monitor": self.monitor.describe(),
                }, priority=85)
                return False
            # Bounded exponential backoff: base * 2^(attempts-1), capped.
            delay = min(self.mic_retry_max_s,
                        self.mic_retry_base_s * (2 ** (attempts - 1)))
            self._mic_recovery_attempts += 1
            self._phase = MicPhase.RECOVERING
            await self._publish(EventType.VOICE_MIC_RECOVERING, {
                "attempt": attempts, "delay_s": round(delay, 2),
                "reason": reason,
            })
            await self._sleep(delay)

    def _enrich_mic_reason(self, reason: str) -> str:
        """Append the exact OS/platform limitation when known (spec 13/23) so
        the report names the real constraint instead of a generic message."""
        try:
            platform = self.voice_env.detect_platform()
        except Exception:  # noqa: BLE001
            return reason
        if platform == "TERMUX":
            return (f"{reason} | Termux limitation: continuous background "
                    f"microphone requires termux-api "
                    f"(termux-microphone-record) plus a Termux session that "
                    f"holds the audio device; none detected")
        if platform == "ANDROID":
            return (f"{reason} | Android limitation: background microphone "
                    f"requires a foreground service with RECORD_AUDIO "
                    f"permission; not detected")
        return reason

    def _start_monitor_loop(self) -> None:
        try:
            self.monitor.start()
        except Exception:  # noqa: BLE001
            pass
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self.monitor.run())

    # ======================================================================
    # frame plumbing (thread-safe entry: sounddevice callback etc.)
    # ======================================================================

    def _enqueue_frame(self, frame: AudioFrame) -> None:
        """Called from any thread (audio callback). Bounded queue: drop-oldest
        on overflow so memory stays bounded."""
        if self._frame_queue is None:
            return
        try:
            self._frame_queue.put_nowait(frame)
        except asyncio.QueueFull:
            try:
                self._frame_queue.get_nowait()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._frame_queue.put_nowait(frame)
            except Exception:  # noqa: BLE001
                pass

    async def _frame_consumer(self) -> None:
        while self._started and self._frame_queue is not None:
            try:
                frame = await asyncio.wait_for(self._frame_queue.get(),
                                               timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            try:
                await self.feed_audio_frame(frame.rms, frame.samples,
                                            frame.source)
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001 — a bad frame must not kill listening
                pass

    # ======================================================================
    # continuous audio processing
    # ======================================================================

    async def feed_audio_frame(self, rms: float, samples: Optional[bytes] = None,
                               source: str = "audio") -> VADState:
        """One audio frame enters the perception pipeline.

        Public/testable entry used by the monitor consumer loop. Returns the
        VAD state for observability. Never claims listening unless the mic is
        actually active.
        """
        if not self._started or self._phase in (MicPhase.MIC_OFF,
                                                MicPhase.UNAVAILABLE):
            return self.vad.process_frame(0.0)
        self.watchdog.beat("audio_capture")
        self.watchdog.beat("mic_capture")
        self.watchdog.beat("vad")
        self._frames_total += 1
        frame = AudioFrame(rms=rms, timestamp=self._now(), samples=samples,
                           source=source)
        self._buffer.append(frame)

        # External audio interruption (phone call etc.): never pretend to hear.
        paused = getattr(self.monitor, "is_paused_by_system", lambda: False)()
        if paused:
            if self._phase != MicPhase.PAUSED_BY_SYSTEM:
                self._phase = MicPhase.PAUSED_BY_SYSTEM
                await self._publish(EventType.VOICE_MIC_UNAVAILABLE, {
                    "reason": "PAUSED_BY_SYSTEM: microphone access "
                              "temporarily unavailable (e.g. phone call)",
                    "attempts": 0, "transient": True,
                }, priority=85)
            return self.vad.process_frame(0.0)
        if self._phase == MicPhase.PAUSED_BY_SYSTEM:
            # AUTO_RECOVERY: access is back.
            self._phase = MicPhase.LISTENING
            self._last_activity = self._now()
            await self._publish(EventType.VOICE_MIC_ACTIVE, {
                "reason": "auto-recovery after system pause",
                "simulated": self._mic_simulated,
            })

        # Audio device change (bluetooth/wired/default mic) -> safe re-init.
        if getattr(self.monitor, "pending_device_change", lambda: False)():
            await self._handle_device_change()

        # Conversation window expiry (ACTIVE -> WAKE).
        await self._check_conversation_timeout()

        # BARGE-IN (mandatory): user speaks while ZERION speaks -> stop TTS,
        # capture the new speech.
        if (self.pipeline.state_machine.state == VoiceState.SPEAKING
                and rms >= self.barge_in_rms):
            await self._barge_in()

        vad = self.vad.process_frame(rms)
        if vad.is_speech_active:
            if not self._segment_active:
                self._segment_active = True
                self._segment_start = self._now()
                self._phase = MicPhase.SPEECH_DETECTED
                await self._publish(EventType.VOICE_SPEECH_DETECTED, {
                    "rms": round(rms, 4),
                    "listening_mode": self._mode.value,
                })
        elif self._segment_active and vad.turn_completed:
            # END_OF_SPEECH -> hand the segment to STT (never silence).
            self._segment_active = False
            self._segment_start = None
            self._speech_segments += 1
            segment = self._buffer.extract_segment()
            if self._processing:
                # A turn is already running; the overlapping segment is
                # honestly dropped (barge-in already handled above).
                self._phase = MicPhase.LISTENING
            else:
                await self._on_speech_segment_end(segment)
        return vad

    async def _on_speech_segment_end(self, segment: List[AudioFrame]) -> None:
        if not segment:
            self._phase = MicPhase.LISTENING
            return
        self._phase = MicPhase.TRANSCRIBING
        stt = await self._transcribe(segment)
        self.watchdog.beat("stt")
        if stt.status != "SUCCESS":
            self._stt_unavailable_count += 1
            await self._publish(EventType.VOICE_STT_UNAVAILABLE, {
                "provider": stt.provider or "NO_PROVIDER",
                "reason": stt.reason or "STT failed",
                "simulated": stt.simulated,
            }, priority=80)
            # No transcript was produced: nothing is claimed, ever.
            self._phase = MicPhase.LISTENING
            return
        self._phase = MicPhase.TRANSCRIPT_READY
        await self._handle_transcript(stt.transcript, via_stt=True,
                                      stt_provider=stt.provider or "stt")

    async def _transcribe(self, segment: List[AudioFrame]) -> STTResult:
        """Local-first STT chain through the canonical SpeechToTextProvider:
        injected transcriber (test harness, always labeled) -> real offline
        STT engine -> NO_PROVIDER. Never fabricates a transcript.
        """
        if self._stt_transcriber is not None:
            try:
                res = self._stt_transcriber(segment)
                if hasattr(res, "__await__"):
                    res = await res
                if isinstance(res, STTResult):
                    return res
                if isinstance(res, str) and res.strip():
                    return STTResult("SUCCESS", transcript=res.strip(),
                                     provider="injected_stt", simulated=True)
            except Exception as e:  # noqa: BLE001
                return STTResult("STT_ERROR", reason=f"{type(e).__name__}: {e}",
                                 provider="injected_stt", simulated=True)

        result = await asyncio.to_thread(
            self.stt_provider.transcribe, segment, self.allow_online_stt)
        return STTResult(
            status=result.get("status", "STT_ERROR"),
            transcript=result.get("transcript", ""),
            provider=result.get("provider"),
            reason=result.get("reason", ""),
            latency_ms=float(result.get("latency_ms", 0.0)),
        )

    # ======================================================================
    # transcript handling: wake mode vs active conversation
    # ======================================================================

    async def _handle_transcript(self, transcript: str, via_stt: bool,
                                 stt_provider: str) -> None:
        transcript = (transcript or "").strip()
        if not transcript:
            self._phase = MicPhase.LISTENING
            return
        if self._mode == ListeningMode.WAKE_MODE:
            wake = self.wake_detector.process_transcript(transcript)
            self.watchdog.beat("wake")
            if not wake.detected:
                await self._publish(EventType.WAKE_WORD_MISDETECTED, {
                    "rejection_reason": wake.rejection_reason,
                    "confidence": wake.confidence,
                })
                self._phase = MicPhase.LISTENING
                return
            self._wake_detections += 1
            await self._publish(EventType.WAKE_WORD_DETECTED, {
                "matched_phrase": wake.matched_phrase,
                "confidence": wake.confidence,
                "layer_triggered": wake.layer_triggered,
                "via_stt": via_stt,
                "stt_provider": stt_provider,
            }, priority=85)
            await self._enter_active_conversation()
            # Pass the full utterance so the pipeline's own wake detection
            # accepts it (single source of truth for command extraction).
            utterance = transcript
        else:
            utterance = transcript

        self._last_activity = self._now()
        self._processing = True
        self._processing_task = asyncio.create_task(
            self._run_turn(utterance))

    async def _enter_active_conversation(self) -> None:
        if self._mode != ListeningMode.ACTIVE_CONVERSATION:
            self._mode = ListeningMode.ACTIVE_CONVERSATION
            self._conversation_started_at = self._now()
            await self._publish(EventType.VOICE_MODE_CHANGED, {
                "mode": self._mode.value,
                "conversation_timeout_s": self.active_conversation_timeout_s,
            })
        self._last_activity = self._now()

    async def _check_conversation_timeout(self) -> None:
        if (self._mode == ListeningMode.ACTIVE_CONVERSATION
                and not self._processing):
            idle = self._now() - self._last_activity
            if idle > self.active_conversation_timeout_s:
                self._mode = ListeningMode.WAKE_MODE
                self._conversation_started_at = None
                await self._publish(EventType.VOICE_MODE_CHANGED, {
                    "mode": self._mode.value,
                    "reason": "inactivity timeout",
                    "idle_s": round(idle, 2),
                })
                try:
                    await self.pipeline.stop_listening()
                except Exception:  # noqa: BLE001
                    pass
                self._phase = MicPhase.LISTENING

    # ======================================================================
    # turn execution through the EXISTING cognitive pipeline
    # ======================================================================

    async def _run_turn(self, utterance: str) -> None:
        """One full voice turn through VoiceFirstInteractionPipeline (which
        routes through the real CognitiveRuntime and returns to LISTENING).
        Runs as a task so barge-in can cancel it."""
        self._phase = MicPhase.PROCESSING
        self.watchdog.beat("pipeline")
        try:
            turn = await self.pipeline.process_speech_input(utterance)
            if turn is not None:
                self._last_turn = turn.to_dict()
                self._last_tts_status = getattr(turn, "tts_status",
                                                "NOT_ATTEMPTED")
                self._last_response = getattr(turn, "cognitive_response", "")
            self._turns_processed += 1
        except asyncio.CancelledError:
            # Barge-in: TTS stopped, voice input resumes.
            try:
                await self.pipeline.resume_listening_after_interrupt()
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            self._processing = False
            self._processing_task = None
            self._last_activity = self._now()
            if self._started:
                # FINAL STATE IS ALWAYS LISTENING (never STOPPED) — unless the
                # whole service was stopped in the meantime.
                self._phase = MicPhase.LISTENING

    # ======================================================================
    # barge-in / interruption / device change
    # ======================================================================

    async def _barge_in(self) -> None:
        self._barge_ins += 1
        self._phase = MicPhase.INTERRUPTED
        await self._publish(EventType.VOICE_BARGE_IN, {
            "reason": "user speech detected while speaking",
            "barge_in_rms": self.barge_in_rms,
        }, priority=90)
        await self.pipeline.interrupt_speech()   # publishes VOICE_INTERRUPTED
        await self.pipeline.resume_listening_after_interrupt()
        if self._processing_task is not None and not self._processing_task.done():
            self._processing_task.cancel()
        self._segment_active = False
        self._segment_start = None
        self._last_activity = self._now()
        self._phase = MicPhase.LISTENING

    async def interrupt(self) -> None:
        """External interrupt request (UI stop, system interruption)."""
        if self._started:
            await self._barge_in()

    async def _handle_device_change(self) -> None:
        self._mic_recovery_attempts += 1
        self._phase = MicPhase.RECOVERING
        await self._publish(EventType.VOICE_MIC_RECOVERING, {
            "reason": "audio device change (bluetooth/wired/default mic)",
        })
        if self._monitor_task is not None and not self._monitor_task.done():
            self._monitor_task.cancel()
            self._monitor_task = None
        try:
            self.monitor.stop()
        except Exception:  # noqa: BLE001
            pass
        # Re-initialize the audio input safely (bounded).
        ok = await self._initialize_microphone()
        if not ok:
            return
        confirm = getattr(self.monitor, "confirm_device_change", None)
        if confirm is not None:
            confirm()
        self._phase = MicPhase.LISTENING

    # ======================================================================
    # text fallback (UI / terminal) — same wake + cognition path
    # ======================================================================

    async def submit_transcript(self, text: str) -> None:
        """Text-input fallback (UI/terminal). Goes through the same wake and
        cognition path as speech; no STT, no fabrication of audio."""
        if not self._started:
            return
        text = (text or "").strip()
        if not text:
            return
        if self._processing:
            return
        await self._handle_transcript(text, via_stt=False,
                                      stt_provider="text_input")

    # ======================================================================
    # watchdog wiring
    # ======================================================================

    def _wire_watchdog(self) -> None:
        self.watchdog.register("mic_capture",
                               restart=self._restart_mic,
                               verify=self._verify_mic)
        self.watchdog.register("audio_capture",
                               restart=self._restart_mic,
                               verify=self._verify_mic)
        self.watchdog.register("vad", restart=self._restart_vad,
                               verify=self._verify_vad)
        self.watchdog.register("wake", restart=self._restart_wake,
                               verify=self._verify_wake)
        self.watchdog.register("stt", restart=self._restart_stt,
                               verify=self._verify_stt)
        self.watchdog.register("tts", restart=self._restart_tts,
                               verify=self._verify_tts)
        self.watchdog.register("pipeline", restart=self._restart_pipeline,
                               verify=self._verify_pipeline)

    async def _restart_mic(self) -> None:
        if self._monitor_task is not None and not self._monitor_task.done():
            self._monitor_task.cancel()
            self._monitor_task = None
        try:
            self.monitor.stop()
        except Exception:  # noqa: BLE001
            pass
        await self._initialize_microphone()

    async def _restart_vad(self) -> None:
        self.vad.reset()

    async def _restart_wake(self) -> None:
        self.wake_detector = LayeredWakeWordDetector()

    async def _restart_stt(self) -> None:
        # Re-detect real engines (clear the environment cache first).
        try:
            self.voice_env._stt_cache = None
        except Exception:  # noqa: BLE001
            pass
        info = self.voice_env.detect_stt()
        self._stt_status = info.status
        self._stt_provider = info.name if info.status == "AVAILABLE" else None

    async def _restart_tts(self) -> None:
        try:
            self.voice_env._tts_cache = None
        except Exception:  # noqa: BLE001
            pass
        self.voice_env.detect_tts()

    async def _restart_pipeline(self) -> None:
        self.pipeline.state_machine.reset()
        try:
            self.pipeline.vad.reset()
        except Exception:  # noqa: BLE001
            pass

    def _verify_mic(self) -> bool:
        return self._mic_available and self.monitor.is_active()

    def _verify_vad(self) -> bool:
        try:
            self.vad.process_frame(0.0)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _verify_wake(self) -> bool:
        try:
            r = self.wake_detector.process_transcript("Zerion",
                                                      bypass_cooldown=True)
            return bool(r.detected)
        except Exception:  # noqa: BLE001
            return False

    def _verify_stt(self) -> bool:
        info = self.voice_env.detect_stt()
        self._stt_status = info.status
        return info.status == VoiceEngineStatus.AVAILABLE

    def _verify_tts(self) -> bool:
        return self.voice_env.detect_tts().status == VoiceEngineStatus.AVAILABLE

    def _verify_pipeline(self) -> bool:
        return self.pipeline.state_machine.state in (
            VoiceState.LISTENING, VoiceState.IDLE)

    async def _watchdog_loop(self) -> None:
        while self._started:
            await self._sleep(self._watchdog_interval_s)
            try:
                report = await self.watchdog.check()
            except Exception:  # noqa: BLE001
                continue
            if report["restarted"] or report["suppressed"]:
                for c in report["restarted"]:
                    self.watchdog.beat(c)
                await self._publish(EventType.VOICE_WATCHDOG_RESTARTED, {
                    "restarted": report["restarted"],
                    "suppressed": report["suppressed"],
                    "restart_counts": report["restart_counts"],
                }, priority=85)
                self._phase = MicPhase.LISTENING

    # ======================================================================
    # health & telemetry (REAL state only)
    # ======================================================================

    def health(self) -> VoiceHealth:
        if not self._started:
            return VoiceHealth.UNAVAILABLE
        if self._phase in (MicPhase.UNAVAILABLE, MicPhase.MIC_OFF):
            return VoiceHealth.UNAVAILABLE
        if self._phase in (MicPhase.MIC_INITIALIZING, MicPhase.RECOVERING,
                           MicPhase.PAUSED_BY_SYSTEM):
            return VoiceHealth.RECOVERING
        if not self._mic_available:
            return VoiceHealth.UNAVAILABLE
        if self._stt_status == VoiceEngineStatus.AVAILABLE:
            return VoiceHealth.HEALTHY
        # Wake detector works but STT unavailable -> DEGRADED (spec 19).
        return VoiceHealth.DEGRADED

    @property
    def is_listening(self) -> bool:
        """LISTENING is only ever true when the mic pipeline is genuinely
        active — never assumed from a print()."""
        return (self._started
                and self._phase == MicPhase.LISTENING
                and self._mic_available
                and self.monitor.is_active())

    def mic_status(self) -> str:
        """Canonical microphone status (spec 16): MIC_READY /
        MIC_UNAVAILABLE / LISTENING / TRANSCRIBING / TRANSCRIPT_READY /
        MIC_ERROR — derived from the REAL phase, never a hard-coded claim.
        """
        p = self._phase
        if not self._started:
            return "MIC_OFF"
        if p == MicPhase.UNAVAILABLE:
            return "MIC_UNAVAILABLE"
        if p in (MicPhase.INTERRUPTED,):
            return "MIC_ERROR"
        if p == MicPhase.TRANSCRIBING:
            return "TRANSCRIBING"
        if p == MicPhase.TRANSCRIPT_READY:
            return "TRANSCRIPT_READY"
        if p in (MicPhase.LISTENING, MicPhase.SPEECH_DETECTED,
                 MicPhase.RECOVERING, MicPhase.PAUSED_BY_SYSTEM):
            # Listening only counts when the mic pipeline is genuinely active.
            if self.is_listening:
                return "LISTENING"
            if p == MicPhase.RECOVERING:
                return "MIC_ERROR"
            return "MIC_UNAVAILABLE"
        if p == MicPhase.MIC_INITIALIZING:
            return "MIC_READY"
        if p in (MicPhase.PROCESSING, MicPhase.SPEAKING):
            return "LISTENING" if self.is_listening else p.value
        return p.value

    def telemetry(self) -> Dict[str, Any]:
        uptime = max(0.0, self._now() - self._started_at)
        frames_per_s = (self._frames_total / uptime) if uptime > 0.001 else 0.0
        cpu_s = max(0.0, time.process_time() - self._cpu_start)
        stt_info = self.voice_env.detect_stt()
        return {
            "service_started": self._started,
            "mic_phase": self._phase.value,
            "mic_status": self.mic_status(),
            "health": self.health().value,
            "is_listening": self.is_listening,
            "listening_mode": self._mode.value,
            "in_conversation": self._mode == ListeningMode.ACTIVE_CONVERSATION,
            "independent_of_ui": True,
            "mic": self.monitor.describe(),
            "mic_available": self._mic_available,
            "mic_reason": self._mic_reason or None,
            "simulated_mic": self._mic_simulated,
            "stt": {
                "status": stt_info.status,
                "provider": self._stt_provider,
                "reason": stt_info.reason,
            },
            "wake": {
                "source": "layered_transcript_detector",
                "available": True,
                "detections": self._wake_detections,
            },
            "watchdog": self.watchdog.health(),
            "buffer": self._buffer.stats(),
            "counters": {
                "frames_total": self._frames_total,
                "speech_segments": self._speech_segments,
                "turns_processed": self._turns_processed,
                "barge_ins": self._barge_ins,
                "stt_unavailable": self._stt_unavailable_count,
                "mic_recovery_attempts": self._mic_recovery_attempts,
            },
            "measured": {
                "cpu_s": round(cpu_s, 4),
                "frames_per_s": round(frames_per_s, 2),
                "uptime_s": round(uptime, 3),
            },
            "last_tts_status": self._last_tts_status,
            "last_turn": self._last_turn,
        }

    # ======================================================================
    # event publishing
    # ======================================================================

    async def _publish(self, event_type: EventType,
                       payload: Dict[str, Any], priority: int = 70) -> None:
        if not self._publish_enabled or self.event_bus is None:
            return
        try:
            await self.event_bus.publish(Event(
                event_type=event_type, payload=payload,
                source="voice_perception", priority=priority,
            ), dispatch_immediately=True)
        except Exception:  # noqa: BLE001 — voice must never crash on events
            pass
