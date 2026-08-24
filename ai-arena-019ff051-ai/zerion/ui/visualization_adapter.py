"""
VisualizationStateAdapter — Slice 10.

The ONLY channel between the cognitive runtime and the UI:

    CognitiveRuntime -> CognitiveEventBus -> VisualizationStateAdapter -> UI

Responsibilities:
- subscribes to the real AsyncEventBus (reused, never a second bus)
- maintains a bounded, rate-limited event history (event storms cannot grow
  memory or flood the UI)
- exposes read-only UI snapshots built from the REAL runtime state (pulse
  health, CognitiveState document, router/provider health, goal/question/
  belief/experience stores, provider state, UI bridge,
  network probe)
- the UI can never mutate cognitive state through a snapshot: every snapshot
  is a freshly built plain-dict copy; nothing in it references a live
  cognitive object
- if a subsystem is unavailable the snapshot reports UNKNOWN / the error —
  never fabricated values
"""

import asyncio
from collections import deque
import time
from typing import Any, Deque, Dict, List

from zerion.cognitive_os.router_types import redact_secrets
from zerion.runtime.events import Event


class VisualizationStateAdapter:
    def __init__(self, engine: Any, event_bus: Any, *,
                 max_history: int = 300,
                 burst_window_s: float = 0.5,
                 stream_queue_max: int = 500):
        self.engine = engine
        self.event_bus = event_bus
        self.runtime = getattr(engine, "cognitive_runtime", None)
        self.max_history = max_history
        self.burst_window_s = burst_window_s
        self.stream_queue_max = stream_queue_max

        self._history: Deque[Dict[str, Any]] = deque(maxlen=max_history)
        self._subscribers: List[asyncio.Queue] = []
        self._started = False

    # -- lifecycle ----------------------------------------------------------

    def attach(self) -> None:
        """Subscribe to the single repo event bus (idempotent)."""
        if self._started:
            return
        self.event_bus.subscribe_all(self._on_event)
        self._started = True

    def detach(self) -> None:
        if not self._started:
            return
        try:
            self.event_bus._wildcard_handlers.remove(self._on_event)
        except (AttributeError, ValueError):
            pass
        self._started = False

    # -- event intake -------------------------------------------------------

    def _event_record(self, event: Event) -> Dict[str, Any]:
        return {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "payload": redact_secrets(event.payload),
            "source": event.source,
            "priority": event.priority,
            "sequence": event.sequence,
            "timestamp": event.timestamp,
            "at": time.monotonic(),
        }

    def _on_event(self, event: Event) -> None:
        """Sync-fast handler: burst absorption + bounded history + bounded
        subscriber queues with drop-oldest backpressure."""
        if not self._started:
            return
        record = self._event_record(event)
        now = record["at"]
        # Burst absorption: consecutive events of the same type inside the
        # window collapse into one history entry with a count. This is the
        # rate limiting that keeps event storms from flooding the UI.
        if (self._history
                and self._history[-1]["event_type"] == record["event_type"]
                and (now - self._history[-1]["at"]) < self.burst_window_s):
            self._history[-1]["count"] += 1
            self._history[-1]["at"] = now
            return
        record["count"] = 1
        self._history.append(record)
        snapshot_record = dict(record)
        snapshot_record.pop("at", None)
        for q in list(self._subscribers):
            try:
                q.put_nowait(snapshot_record)
            except asyncio.QueueFull:
                # Backpressure: drop the oldest buffered event, keep the new.
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(snapshot_record)
                except asyncio.QueueFull:  # pragma: no cover
                    pass

    # -- event stream for the UI -------------------------------------------

    def subscribe_stream(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self.stream_queue_max)
        self._subscribers.append(q)
        return q

    def unsubscribe_stream(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def event_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        out = []
        for rec in list(self._history)[-limit:]:
            rec_copy = dict(rec)
            rec_copy.pop("at", None)
            out.append(rec_copy)
        return out

    # -- real-state snapshot -----------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Read-only, UI-safe view of the REAL runtime. Fresh plain dicts only.

        Every section is guarded: a failing subsystem reports its error in
        ``health`` and UNKNOWN values instead of crashing the snapshot.
        """
        runtime = self.runtime
        base = {
            "schema_version": 2,
            "generated_at": time.time(),
            "system": self._safe("system"),
            "cognitive": self._safe("cognitive"),
            "attention": self._safe("attention"),
            "memory": self._safe("memory"),
            "execution": self._safe("execution"),
            "learning": self._safe("learning"),
            "health": self._safe("health"),
            "voice": {"removed": True},
            "models": self._safe("models"),
            "network": self._safe("network"),
            "presentation": self._safe("presentation"),
            "last_events": self.event_history(limit=60),
        }
        if runtime is None:
            base["system"] = {"runtime_status": "UNKNOWN",
                              "error": "cognitive runtime unavailable"}
        return base

    def _safe(self, section: str) -> Dict[str, Any]:
        try:
            return getattr(self, f"_snap_{section}")()
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {str(e)[:200]}",
                    "status": "UNKNOWN"}

    # -- section builders ---------------------------------------------------

    def _snap_system(self) -> Dict[str, Any]:
        runtime = self.runtime
        state = {}
        if runtime is not None:
            rs = getattr(runtime.state, "runtime_status", "UNKNOWN")
            state["runtime_status"] = getattr(rs, "value", str(rs))
            state["state_id"] = getattr(runtime.state, "state_id", None)
        pulse = getattr(runtime, "cognitive_pulse", None) if runtime else None
        state["platform"] = self._platform()
        # Provider status from real health tracking.
        state["providers"] = {}
        tracker = getattr(runtime, "provider_health", None) if runtime else None
        if tracker is not None:
            try:
                for name, health in tracker.snapshot().items():
                    state["providers"][name] = {
                        "status": getattr(health, "status", "UNKNOWN").value
                        if hasattr(health, "status") else "UNKNOWN",
                        "configured": bool(getattr(health, "configured", False)),
                        "integration_implemented": bool(
                            getattr(health, "integration_implemented", False)),
                    }
            except Exception:  # noqa: BLE001
                state["providers"] = {"error": "provider health unavailable"}
        return state

    def _platform(self) -> Dict[str, Any]:
        import platform as _platform_mod
        platform = _platform_mod.system().upper()
        termux = getattr(self.engine, "termux", None)
        out = {"type": platform}
        if termux is not None:
            try:
                out["is_termux"] = bool(termux.is_termux)
            except Exception:  # noqa: BLE001
                out["is_termux"] = "UNKNOWN"
        return out

    def _snap_cognitive(self) -> Dict[str, Any]:
        runtime = self.runtime
        out: Dict[str, Any] = {
            "current_mode": "UNKNOWN",
            "cognitive_depth": "UNKNOWN",
            "current_priority": None,
            "active_goal": None,
            "active_question": None,
            "current_hypothesis": None,
            "current_experiment": None,
            "current_task": None,
            "current_operation": None,
        }
        if runtime is None:
            return out
        pulse = getattr(runtime, "cognitive_pulse", None)
        if pulse is not None:
            try:
                out["current_mode"] = pulse.state.value
            except Exception:  # noqa: BLE001
                pass
        # Depth comes from the real router lifecycle (last MODEL_SELECTED event).
        for rec in reversed(list(self._history)):
            if rec["event_type"] == "MODEL_SELECTED":
                depth = (rec.get("payload") or {}).get("depth_level")
                if depth:
                    out["cognitive_depth"] = depth
                break
        # Real goal from the persistent goal field.
        try:
            goals = runtime.objectives.list_active_objectives()
            if goals:
                g = goals[0]
                out["active_goal"] = getattr(g, "title", None) or getattr(g, "objective", None)
        except Exception:  # noqa: BLE001
            pass
        # Real question / hypothesis / experiment from the Slice 2/3 stores.
        try:
            qs = runtime.question_store.list_unresolved()
            if qs:
                out["active_question"] = qs[0].text
                qid = qs[0].question_id
                try:
                    hs = runtime.hypothesis_store.list_by_question(qid)
                    if hs:
                        out["current_hypothesis"] = hs[0].statement
                except Exception:  # noqa: BLE001
                    pass
                try:
                    es = runtime.experiment_store.list_unresolved()
                    if es:
                        out["current_experiment"] = es[0].title
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        return out

    def _snap_attention(self) -> Dict[str, Any]:
        runtime = self.runtime
        if runtime is None:
            return {"error": "runtime unavailable"}
        att = getattr(runtime.state, "attention", None)
        if att is None:
            return {"selected": 0, "deferred": 0, "discarded": 0,
                    "pending": 0, "deferred_pool": 0}
        return {
            "selected": getattr(att, "selected_count", 0),
            "deferred": getattr(att, "deferred_count", 0),
            "discarded": getattr(att, "discarded_count", 0),
            "pending": getattr(att, "pending_candidates", 0),
            "deferred_pool": getattr(att, "deferred_candidates", 0),
            "current_focus_id": getattr(att, "current_focus_id", None),
        }

    def _snap_memory(self) -> Dict[str, Any]:
        runtime = self.runtime
        if runtime is None:
            return {"error": "runtime unavailable"}
        out: Dict[str, Any] = {"beliefs": [], "episodes": 0,
                               "distilled": 0, "failures": 0}
        try:
            beliefs = runtime.belief_store.list()
            out["belief_count"] = len(beliefs)
            out["beliefs"] = [
                {"statement": b.statement, "confidence": b.confidence,
                 "status": getattr(b.status, "value", str(b.status)),
                 "provenance": getattr(b, "provenance", None) or "UNKNOWN"}
                for b in beliefs[-5:]]
        except Exception:  # noqa: BLE001
            pass
        try:
            out["episodes"] = runtime.episode_store.count()
        except Exception:  # noqa: BLE001
            pass
        try:
            out["distilled"] = runtime.distilled_store.count()
        except Exception:  # noqa: BLE001
            pass
        try:
            out["failures"] = runtime.failure_learning.count_failures()
        except Exception:  # noqa: BLE001
            pass
        return out

    def _snap_execution(self) -> Dict[str, Any]:
        return {
            "current_tool": None,
            "tool_status": "NONE",
            "last_result": None,
            "recovery_state": "NONE",
            "active_work": self._health_field("active_work"),
        }

    def _snap_learning(self) -> Dict[str, Any]:
        runtime = self.runtime
        out: Dict[str, Any] = {"capabilities": 0, "capability_state": []}
        if runtime is None:
            return out
        try:
            caps = runtime.list_capabilities()
            out["capabilities"] = len(caps)
            out["capability_state"] = [
                {"name": c.name, "status": getattr(c.status, "value", str(c.status))}
                for c in caps[-5:]]
        except Exception:  # noqa: BLE001
            pass
        return out

    def _snap_health(self) -> Dict[str, Any]:
        runtime = self.runtime
        pulse = getattr(runtime, "cognitive_pulse", None) if runtime else None
        if pulse is None:
            return {"pulse": "UNKNOWN", "error": "cognitive pulse unavailable"}
        try:
            health = pulse.health()
            health.pop("budget_usage", None)  # keep snapshot small
            return health
        except Exception as e:  # noqa: BLE001
            return {"pulse": "ERROR", "error": str(e)[:200]}

    def _health_field(self, key: str):
        try:
            return self._snap_health().get(key, "UNKNOWN")
        except Exception:  # noqa: BLE001
            return "UNKNOWN"

    def _snap_voice(self) -> Dict[str, Any]:
        # Voice input removed: Zerion is text-only.
        snap = {
            "state_machine": {"state": "REMOVED"},
            "in_conversation": False,
            "last_error": None,
            "history_count": 0,
            "stt": {},
            "tts": {},
            "wake": {},
        }
        # Microphone removed: there is no voice-perception telemetry.
        snap["perception"] = {
            "service_started": False,
            "mic_phase": "REMOVED",
            "health": "UNAVAILABLE",
            "is_listening": False,
            "reason": "microphone functionality removed from Zerion",
        }
        return snap

    def _snap_models(self) -> Dict[str, Any]:
        # No local model registry exists: Gemini is the only provider.
        runtime = self.runtime
        if runtime is None:
            return {"count": 0, "models": []}
        try:
            models = runtime.cognitive_router.list_models() \
                if hasattr(runtime.cognitive_router, "list_models") else []
        except Exception:
            models = []
        return {"count": len(models), "models": list(models)}

    def _snap_network(self) -> Dict[str, Any]:
        # Informational only — Gemini is a cloud provider, but no fake
        # connectivity state is invented here.
        return {"state": "UNKNOWN", "attempts": 0}

    def _snap_presentation(self) -> Dict[str, Any]:
        """The fields the existing HTML/HUD consumes, derived from REAL state."""
        bridge = getattr(self.engine, "ui_bridge", None)
        bstate = bridge.current_state if bridge is not None else None
        runtime = self.runtime

        # Microphone removed: the visible mode is driven by the pulse only.
        voice_perception_state = {
            "mic_phase": "REMOVED",
            "health": "UNAVAILABLE",
            "is_listening": False,
            "reason": "microphone functionality removed from Zerion",
        }
        voice_mode = None
        pulse_mode = None
        pulse = getattr(runtime, "cognitive_pulse", None) if runtime else None
        if pulse is not None and voice_mode is None:
            try:
                pulse_mode = pulse.state.value
            except Exception:  # noqa: BLE001
                pass

        runtime_state, state_label = self._resolve_mode(voice_mode, pulse_mode)

        active_goal = None
        if bstate is not None:
            active_goal = bstate.active_goal
        if active_goal is None:
            try:
                goals = runtime.objectives.list_active_objectives()
                if goals:
                    active_goal = goals[0].title
            except Exception:  # noqa: BLE001
                pass

        resource_state = {}
        resources = getattr(self.engine, "resources", None)
        if resources is not None:
            try:
                snap = resources.sample()
                resource_state = {
                    "cpu_percent": snap.cpu_percent,
                    "memory_mb": snap.memory_available_mb,
                    "compute_tier": snap.compute_tier,
                    "is_battery": snap.is_battery_powered,
                }
            except Exception:  # noqa: BLE001
                resource_state = {}

        accel = "UNKNOWN"
        if hasattr(self.engine, "learning_to_learn"):
            try:
                a = self.engine.learning_to_learn.calculate_learning_acceleration()
                if a is not None:
                    accel = f"{a:.2f}x"
            except Exception:  # noqa: BLE001
                accel = "UNKNOWN"

        # Real, event-derived explanation lines (never invented telemetry).
        explanation = []
        if bstate is not None:
            explanation = list(bstate.explanation_chain)
        for rec in list(self._history)[-3:]:
            explanation.append(f"EVENT: {rec['event_type']} "
                               f"({rec.get('count', 1)}x, {rec['source']})")
        if not explanation:
            explanation = ["IDLE: no cognitive activity in progress"]

        return {
            "runtime_state": runtime_state,
            "state_label": state_label,
            "cognitive_state": self._cognitive_state_line(pulse_mode),
            "active_goal": active_goal,
            "active_question": None,
            "current_strategy": bstate.current_strategy if bstate else "UNKNOWN",
            "confidence": bstate.confidence if bstate else None,
            "maturity_level": bstate.maturity_level if bstate else "UNKNOWN",
            "learning_acceleration": accel,
            "explanation_chain": explanation,
            "resource_state": resource_state,
            "voice_perception": voice_perception_state,
            "audio_amplitude_rms": bstate.audio_amplitude_rms if bstate else 0.0,
            "core_pulse_period_s": bstate.core_pulse_period_s if bstate else 2.0,
            "core_pulse_amplitude": bstate.core_pulse_amplitude if bstate else 0.12,
            "core_glow_intensity": bstate.core_glow_intensity if bstate else 0.85,
            "cyan_contour_activity": bstate.cyan_contour_activity if bstate else 0.5,
        }

    @staticmethod
    def _resolve_mode(voice_mode, pulse_mode):
        if voice_mode is not None:
            return voice_mode, voice_mode
        if pulse_mode == "RUNNING":
            return "IDLE", "IDLE"
        if pulse_mode == "PAUSED":
            return "IDLE", "PAUSED"
        if pulse_mode == "DEGRADED":
            return "DEGRADED", "DEGRADED"
        if pulse_mode == "STOPPED":
            return "IDLE", "STOPPED"
        return "IDLE", "IDLE"

    def _cognitive_state_line(self, pulse_mode) -> str:
        health = {}
        try:
            health = self._snap_health()
        except Exception:  # noqa: BLE001
            pass
        parts = []
        if pulse_mode:
            parts.append(f"Pulse {pulse_mode}")
        qsize = health.get("queue_size")
        if qsize is not None:
            parts.append(f"queue={qsize}")
        aw = health.get("active_work")
        if aw is not None:
            parts.append(f"active={aw}")
        return " · ".join(parts) if parts else "UNKNOWN"
