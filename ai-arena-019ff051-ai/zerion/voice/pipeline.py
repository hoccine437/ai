"""
Voice-First Interaction Pipeline for ZERION-X — Slice 10.

Architecture (strict separation — the voice layer is an interface, never the
cognitive engine):

    MICROPHONE -> STT -> VOICE EVENTS -> CognitiveRuntime -> RESPONSE EVENT -> TTS -> SPEAKER

- Every lifecycle step is published as a real event on the single repo
  AsyncEventBus (VOICE_STARTED / VOICE_TRANSCRIPT_PARTIAL / _FINAL /
  WAKE_WORD_DETECTED / _MISDETECTED / VOICE_INTERRUPTED / VOICE_ENDED /
  VOICE_ERROR / VOICE_RESPONSE_READY).
- The pipeline drives an explicit voice state machine with valid transitions.
- Commands are routed through the REAL Slice 1-9 CognitiveRuntime /
  CognitiveRouter. Responses are real: goal queries read the real objective
  store, status reads real maturity/acceleration measurements, and everything
  else goes through the model router — which returns a structured failure
  (never fabricated text) when no provider is available.
- TTS is honest: audio is only claimed when an offline engine actually
  synthesized it (``VoiceEnvironment.synthesize``); otherwise the turn reports
  VOICE_UNAVAILABLE and the text is returned for the client to display.
"""

import asyncio
from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional

from zerion.runtime.events import Event, EventType
from zerion.voice.wake_word import LayeredWakeWordDetector, WakeDetectionResult
from zerion.voice.vad import VoiceActivityDetector, VADState
from zerion.voice.session import SecureVoiceSessionManager
from zerion.voice.state_machine import (
    InvalidVoiceTransition,
    VoiceState,
    VoiceStateMachine,
)
from zerion.voice.providers import VoiceEnvironment
from zerion.ui.state_bridge import UIStateMode, UIStateBridge


@dataclass
class VoiceInteractionTurn:
    turn_id: str
    raw_transcript: str
    wake_result: WakeDetectionResult
    cognitive_response: str
    tool_executed: Optional[str]
    total_latency_ms: float
    interrupted: bool = False
    timestamp: float = field(default_factory=time.time)
    # Slice 10: honest evidence of what actually happened this turn.
    cognitive_status: str = "UNKNOWN"     # SUCCESS / ROUTING_FAILED / NOT_APPLICABLE
    voice_state: str = "IDLE"
    tts_status: str = "NOT_ATTEMPTED"     # AUDIO_GENERATED / AUDIO_PLAYED / VOICE_UNAVAILABLE / VOICE_ERROR
    tts_engine: Optional[str] = None
    audio_path: Optional[str] = None
    offline_mode: str = "AUTO"
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "raw_transcript": self.raw_transcript,
            "wake_detected": self.wake_result.detected,
            "matched_phrase": self.wake_result.matched_phrase,
            "cleaned_command": self.wake_result.cleaned_command,
            "cognitive_response": self.cognitive_response,
            "tool_executed": self.tool_executed,
            "total_latency_ms": self.total_latency_ms,
            "interrupted": self.interrupted,
            "cognitive_status": self.cognitive_status,
            "voice_state": self.voice_state,
            "tts_status": self.tts_status,
            "tts_engine": self.tts_engine,
            "audio_path": self.audio_path,
            "offline_mode": self.offline_mode,
            "errors": self.errors,
            "timestamp": self.timestamp,
        }


class VoiceFirstInteractionPipeline:
    def __init__(
        self,
        engine_ref: Any,
        ui_bridge: Optional[UIStateBridge] = None,
        continuous_conversation: bool = True,
        voice_env: Optional[VoiceEnvironment] = None,
    ):
        self.engine = engine_ref
        self.ui_bridge = ui_bridge or getattr(engine_ref, "ui_bridge", UIStateBridge())
        self.continuous_conversation = continuous_conversation

        self.wake_detector = LayeredWakeWordDetector()
        self.vad = VoiceActivityDetector()
        self.session_mgr = SecureVoiceSessionManager()
        self.voice_env = voice_env or VoiceEnvironment()
        self.state_machine = VoiceStateMachine()

        self._is_in_conversation = False
        self._current_speech_task: Optional[asyncio.Task] = None
        self._history: List[VoiceInteractionTurn] = []
        self._last_error: Optional[Dict[str, Any]] = None

    # -- event publishing --------------------------------------------------

    def _bus(self):
        return getattr(self.engine, "event_bus", None)

    async def _publish(self, event_type: EventType, payload: Dict[str, Any],
                       priority: int = 70) -> None:
        """Awaited so voice lifecycle events land on the bus (and reach the
        VisualizationStateAdapter) before the caller continues — deterministic
        ordering for tests and the UI event stream."""
        bus = self._bus()
        if bus is None:
            return
        try:
            await bus.publish(Event(
                event_type=event_type, payload=payload,
                source="voice_pipeline", priority=priority,
            ), dispatch_immediately=True)
        except Exception:  # noqa: BLE001 — voice must never crash on events
            pass

    async def _emit_voice_error(self, component: str, code: str, message: str,
                                recoverable: bool = True) -> None:
        self._last_error = {
            "component": component,
            "error_code": code,
            "message": message,
            "recoverable": recoverable,
            "timestamp": time.time(),
        }
        await self._publish(EventType.VOICE_ERROR, dict(self._last_error),
                            priority=80)
        try:
            self.state_machine.transition(VoiceState.ERROR, reason=code)
        except InvalidVoiceTransition:
            pass

    # -- listening lifecycle ------------------------------------------------

    async def start_listening(self) -> None:
        """START_LISTENING command: transition to LISTENING, publish VOICE_STARTED."""
        try:
            self.state_machine.transition(VoiceState.LISTENING,
                                          reason="start_listening")
        except InvalidVoiceTransition:
            return
        await self._publish(EventType.VOICE_STARTED, {
            "continuous_conversation": self.continuous_conversation,
            "voice_state": self.state_machine.state.value,
        })
        self.ui_bridge.set_listening_state(True)

    async def stop_listening(self) -> None:
        """STOP_LISTENING command: back to IDLE, publish VOICE_ENDED."""
        was_active = self.state_machine.state in (
            VoiceState.LISTENING, VoiceState.THINKING,
            VoiceState.EXECUTING, VoiceState.SPEAKING,
            VoiceState.INTERRUPTED)
        try:
            self.state_machine.transition(VoiceState.IDLE,
                                          reason="stop_listening")
        except InvalidVoiceTransition:
            pass
        self._is_in_conversation = False
        if was_active:
            await self._publish(EventType.VOICE_ENDED, {
                "voice_state": self.state_machine.state.value,
            })
        self.ui_bridge.set_listening_state(False)

    async def process_partial_transcript(self, transcript: str) -> None:
        """Real-time partial transcript from the browser STT layer."""
        await self._publish(EventType.VOICE_TRANSCRIPT_PARTIAL, {
            "transcript": transcript[:500],
            "voice_state": self.state_machine.state.value,
        })

    # -- audio / interruption ----------------------------------------------

    async def handle_audio_frame(self, rms_amplitude: float) -> VADState:
        """Processes real-time audio frame energy for VAD & barge-in."""
        self.ui_bridge.current_state.audio_amplitude_rms = rms_amplitude
        vad = self.vad.process_frame(rms_amplitude)
        speaking = (
            self.state_machine.state == VoiceState.SPEAKING
            or self.ui_bridge.current_state.runtime_state == UIStateMode.SPEAKING)
        if speaking and rms_amplitude >= 0.20:
            await self.interrupt_speech()
        return vad

    async def interrupt_speech(self) -> None:
        """Barge-in: cancel active TTS, publish VOICE_INTERRUPTED, return to
        LISTENING so the new user speech is processed."""
        if self._current_speech_task and not self._current_speech_task.done():
            self._current_speech_task.cancel()
            self._current_speech_task = None
        try:
            self.state_machine.transition(VoiceState.INTERRUPTED,
                                          reason="barge_in")
        except InvalidVoiceTransition:
            pass
        await self._publish(EventType.VOICE_INTERRUPTED, {
            "voice_state": self.state_machine.state.value,
        })
        self.ui_bridge.set_listening_state(True)
        self.ui_bridge.current_state.explanation_chain.insert(
            0, "VOICE: Natural conversational interruption triggered.")

    async def resume_listening_after_interrupt(self) -> None:
        """Slice 10.1: landing state after a barge-in. INTERRUPTED/SPEAKING
        -> LISTENING (idempotent), keeping the active conversation so the user
        does NOT have to repeat the wake phrase. The voice layer only; no
        cognition here."""
        if self.state_machine.state in (VoiceState.INTERRUPTED,
                                        VoiceState.SPEAKING):
            try:
                self.state_machine.transition(
                    VoiceState.LISTENING, reason="resume_after_barge_in")
            except InvalidVoiceTransition:
                pass
        self.ui_bridge.set_listening_state(True)
        self.ui_bridge.current_state.explanation_chain.insert(
            0, "VOICE: Listening resumed after interruption.")
    # -- main turn ----------------------------------------------------------

    async def process_speech_input(self, speech_transcript: str) -> VoiceInteractionTurn:
        t0 = time.perf_counter()
        turn_id = f"v_turn_{int(time.time() * 1000) % 100000}"

        await self._publish(EventType.VOICE_TRANSCRIPT_FINAL, {
            "transcript": speech_transcript[:500],
            "voice_state": self.state_machine.state.value,
        })

        # 1. Wake word (skipped while an active conversation is ongoing).
        wake_res = self.wake_detector.process_transcript(speech_transcript)
        if not self._is_in_conversation and not wake_res.detected:
            await self._publish(EventType.WAKE_WORD_MISDETECTED, {
                "transcript": speech_transcript[:200],
                "rejection_reason": wake_res.rejection_reason,
                "confidence": wake_res.confidence,
            })
            latency = (time.perf_counter() - t0) * 1000.0
            turn = VoiceInteractionTurn(
                turn_id=turn_id,
                raw_transcript=speech_transcript,
                wake_result=wake_res,
                cognitive_response="",
                tool_executed=None,
                total_latency_ms=round(latency, 2),
                cognitive_status="NOT_APPLICABLE",
                voice_state=self.state_machine.state.value,
                offline_mode=self._offline_mode_str(),
            )
            self._history.append(turn)
            return turn

        if wake_res.detected:
            await self._publish(EventType.WAKE_WORD_DETECTED, {
                "matched_phrase": wake_res.matched_phrase,
                "confidence": wake_res.confidence,
                "layer_triggered": wake_res.layer_triggered,
            })
        self._is_in_conversation = True
        try:
            self.state_machine.transition(VoiceState.LISTENING,
                                          reason="wake_word_accepted")
        except InvalidVoiceTransition:
            pass
        self.ui_bridge.set_listening_state(True)

        user_command = wake_res.cleaned_command if wake_res.detected else speech_transcript
        if not user_command.strip():
            user_command = "Status check"
        self.ui_bridge.current_state.active_goal = f"Voice Command: {user_command[:40]}"

        # 2. THINKING -> route through the REAL cognitive runtime.
        try:
            self.state_machine.transition(VoiceState.THINKING, reason="cognitive_routing")
        except InvalidVoiceTransition:
            pass
        self.ui_bridge.current_state.runtime_state = UIStateMode.THINKING
        self.ui_bridge.current_state.state_label = "THINKING"

        tool_name: Optional[str] = None
        cognitive_answer = ""
        cognitive_status = "UNKNOWN"
        errors: List[str] = []
        low = user_command.lower()

        if any(w in low for w in ["task", "objective", "todo", "goal"]):
            # Real goal-field query through the engine's persistent store.
            tool_name = "ObjectiveContinuityManager.list_active_objectives"
            try:
                self.state_machine.transition(VoiceState.EXECUTING,
                                              reason="goal_query")
            except InvalidVoiceTransition:
                pass
            self.ui_bridge.current_state.runtime_state = UIStateMode.EXECUTING
            self.ui_bridge.current_state.state_label = "EXECUTING"
            objs = (self.engine.continuous_objectives.list_active_objectives()
                    if hasattr(self.engine, "continuous_objectives") else [])
            primary = objs[0].title if objs else "None"
            cognitive_answer = (
                f"You have {len(objs)} active continuous objective"
                f"{'s' if len(objs) != 1 else ''}. "
                f"The primary objective is: {primary}.")
            cognitive_status = "SUCCESS"
        elif ("status" in low or "who are you" in low or "who are" in low):
            # Real measured runtime evidence, never hard-coded claims.
            tool_name = "CognitiveMaturityEvaluator.evaluate_from_evidence"
            mat = self.engine.maturity_evaluator.evaluate_from_evidence(
                _runtime_evidence(self.engine))
            accel = None
            if hasattr(self.engine, "learning_to_learn"):
                try:
                    accel = self.engine.learning_to_learn.calculate_learning_acceleration()
                except Exception:  # noqa: BLE001
                    accel = None
            accel_str = (f"{accel:.2f}x" if accel is not None else "UNKNOWN")
            cognitive_answer = (
                f"I am ZERION. Cognitive maturity: {mat.current_level.value}. "
                f"Learning acceleration: {accel_str}. "
                f"Active objectives: "
                f"{len(self.engine.continuous_objectives.list_active_objectives())}.")
            cognitive_status = "SUCCESS"
        else:
            # General command: route through the Slice 6 CognitiveRouter via
            # the real CognitiveRuntime. Honest outcome either way.
            tool_name = "CognitiveRuntime.execute_task"
            cognitive_status = await self._run_cognitive_task(user_command)

        # 3. Response event -> voice output.
        result = _latest_routing_result(self.engine)
        if result is not None and result.output is not None:
            cognitive_answer = str(result.output)
            cognitive_status = "SUCCESS"
        elif result is not None:
            errors = list(result.errors or [])
            cognitive_answer = (
                "I couldn't process that right now — no cognitive model "
                "provider is available. " +
                ("Reason: " + "; ".join(errors[:2]) + "." if errors else "")
            )
            if result.status.value in ("MODEL_LOAD_FAILURE", "MODEL_UNAVAILABLE",
                                       "ROUTING_FAILED", "NETWORK_UNAVAILABLE"):
                cognitive_status = result.status.value
            else:
                cognitive_status = "FAILURE"

        await self._publish(EventType.VOICE_RESPONSE_READY, {
            "turn_id": turn_id,
            "response": cognitive_answer[:1000],
            "cognitive_status": cognitive_status,
            "voice_state": self.state_machine.state.value,
        })

        # 4. SPEAKING with honest TTS (offline-first).
        tts_status = "NOT_ATTEMPTED"
        tts_engine: Optional[str] = None
        audio_path: Optional[str] = None
        if cognitive_answer:
            try:
                self.state_machine.transition(VoiceState.SPEAKING,
                                              reason="tts_output")
            except InvalidVoiceTransition:
                pass
            self.ui_bridge.set_speaking_state(True, audio_rms=0.75)
            self.ui_bridge.current_state.explanation_chain = [
                f"VOICE INPUT: '{user_command}'",
                f"COGNITIVE STATUS: {cognitive_status}",
                f"OUTPUT: '{cognitive_answer[:50]}'",
            ]
            tts_evidence = await asyncio.to_thread(
                self.voice_env.synthesize, cognitive_answer)
            tts_status = tts_evidence.get("status", "VOICE_UNAVAILABLE")
            tts_engine = tts_evidence.get("engine")
            audio_path = tts_evidence.get("path")
            if tts_status == "VOICE_UNAVAILABLE":
                self.ui_bridge.current_state.explanation_chain.insert(
                    0, "VOICE: speech output unavailable "
                       f"({tts_evidence.get('reason', 'no offline TTS engine')})")
        else:
            tts_status = "SKIPPED_EMPTY_RESPONSE"

        # 5. Return to listening/standby.
        if self.continuous_conversation:
            try:
                self.state_machine.transition(VoiceState.LISTENING,
                                              reason="turn_complete")
            except InvalidVoiceTransition:
                pass
            self.ui_bridge.set_listening_state(True)
        else:
            try:
                self.state_machine.transition(VoiceState.IDLE,
                                              reason="turn_complete")
            except InvalidVoiceTransition:
                pass
            self.ui_bridge.set_listening_state(False)
            self._is_in_conversation = False
        await self._publish(EventType.VOICE_ENDED, {
            "voice_state": self.state_machine.state.value,
        })

        latency = (time.perf_counter() - t0) * 1000.0
        turn = VoiceInteractionTurn(
            turn_id=turn_id,
            raw_transcript=speech_transcript,
            wake_result=wake_res,
            cognitive_response=cognitive_answer,
            tool_executed=tool_name,
            total_latency_ms=round(latency, 2),
            cognitive_status=cognitive_status,
            voice_state=self.state_machine.state.value,
            tts_status=tts_status,
            tts_engine=tts_engine,
            audio_path=audio_path,
            offline_mode=self._offline_mode_str(),
            errors=errors,
        )
        self._history.append(turn)
        return turn

    async def _run_cognitive_task(self, user_command: str) -> str:
        """Route a general command through the real CognitiveRuntime router."""
        runtime = getattr(self.engine, "cognitive_runtime", None)
        if runtime is None:
            return "FAILURE"
        from zerion.cognitive_os.router_types import (
            RoutingMode,
            Task,
            TaskType,
        )
        offline_mode = self._offline_mode_str()
        mode = (RoutingMode.OFFLINE_ONLY
                if offline_mode == "OFFLINE_ONLY"
                else RoutingMode.AUTO)
        task = Task(
            type=TaskType.CONVERSATION,
            description=f"Voice command: {user_command[:200]}",
            difficulty=0.3,
            uncertainty=0.4,
            novelty=0.3,
            stakes=0.1,
            goal_relevance=0.5,
            required_capabilities=set(),
            offline_required=(mode == RoutingMode.OFFLINE_ONLY),
            verification_required=False,
            metadata={"source": "voice_pipeline"},
        )
        result = await runtime.execute_task(task, user_command, mode=mode)
        _remember_routing_result(self.engine, result)
        return result.status.value if result.output is None else "SUCCESS"

    def _offline_mode_str(self) -> str:
        pulse = getattr(getattr(self.engine, "cognitive_runtime", None),
                        "cognitive_pulse", None)
        if pulse is not None:
            return getattr(pulse, "_offline_mode", "AUTO").value
        return "AUTO"

    def voice_state(self) -> Dict[str, Any]:
        return {
            "state_machine": self.state_machine.to_dict(),
            "in_conversation": self._is_in_conversation,
            "history_count": len(self._history),
            "last_error": self._last_error,
            "environment": self.voice_env.to_dict(),
        }


# -- tiny module-level helpers so the pipeline stays readable -----------------

_LAST_ROUTING_RESULT = {}


def _remember_routing_result(engine: Any, result: Any) -> None:
    _LAST_ROUTING_RESULT[id(engine)] = result


def _latest_routing_result(engine: Any):
    return _LAST_ROUTING_RESULT.get(id(engine))


def _runtime_evidence(engine: Any):
    from zerion.runtime.evidence import collect_runtime_evidence
    return collect_runtime_evidence(engine)
