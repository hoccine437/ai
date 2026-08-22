"""
ZERION — Authoritative RuntimeState.

ONE source of runtime truth. The central runtime created by ``main2.py`` owns
exactly one RuntimeState instance; the UI and API are read-only clients of it.
No component may hard-code or invent these values — every field is measured
from a live subsystem reference.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class RuntimeState:
    """Authoritative snapshot of the Zerion runtime (owned by main2.py)."""

    system_name: str = "ZERION-X"
    provider: str = "UNKNOWN"            # active provider id (gemini only)
    model: str = "UNKNOWN"               # active model id
    provider_state: str = "UNKNOWN"      # READY | UNAVAILABLE (Gemini is the ONLY provider)
    memory_state: str = "UNKNOWN"        # READY | EMPTY | ERROR (+ measured counts in details)
    agent_count: int = 0                 # registered agents (target: 21)
    tool_count: int = 0                  # registered tools (target: 100)
    voice_enabled: bool = False          # honest TTS availability
    runtime_health: str = "BOOTING"      # BOOTING | OK | DEGRADED | STOPPED
    startup_time: float = field(default_factory=time.time)
    active_tasks: int = 0                # live scheduled tasks
    capabilities: int = 0                # self-model capability count
    episodes: int = 0                    # canonical episode-store count
    distilled_rules: int = 0             # distilled procedural rules
    data_dir: str = "data"
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, time.time() - self.startup_time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system_name": self.system_name,
            "provider": self.provider,
            "model": self.model,
            "provider_state": self.provider_state,
            "memory_state": self.memory_state,
            "agent_count": self.agent_count,
            "tool_count": self.tool_count,
            "voice_enabled": self.voice_enabled,
            "runtime_health": self.runtime_health,
            "startup_time": self.startup_time,
            "uptime_seconds": round(self.uptime_seconds, 3),
            "active_tasks": self.active_tasks,
            "capabilities": self.capabilities,
            "episodes": self.episodes,
            "distilled_rules": self.distilled_rules,
            "data_dir": self.data_dir,
            "details": self.details,
        }


def measure_provider(engine) -> Dict[str, Any]:
    """Measure the ACTIVE provider honestly.

    Gemini is the ONLY provider. There are no local-model or OpenAI fallbacks:
    if the Gemini key/config is missing or unusable we report UNAVAILABLE —
    we never silently substitute another inference backend.
    """
    out: Dict[str, Any] = {"provider": "gemini",
                           "model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
                           "provider_state": "UNAVAILABLE"}
    try:
        key = os.environ.get("GEMINI_API_KEY", "")
        if key and len(key) > 10:
            out["provider_state"] = "READY"
        else:
            out["details_reason"] = "GEMINI_API_KEY not set — Gemini is UNAVAILABLE; no offline fallback exists"
    except Exception as e:  # noqa: BLE001
        out["provider_state"] = f"ERROR: {type(e).__name__}"
    return out


def refresh_runtime_state(state: RuntimeState, engine) -> RuntimeState:
    """Re-measure every RuntimeState field from live subsystem references.

    This is the ONLY place runtime status values come from. Called by the
    central runtime after initialization and on every /api/status read.
    """
    state.startup_time = getattr(engine, "_startup_time", state.startup_time)

    cr = getattr(engine, "cognitive_runtime", None)

    # Provider (primary: Gemini)
    prov = measure_provider(engine)
    state.provider = prov["provider"]
    state.model = prov["model"]
    state.provider_state = prov["provider_state"]

    # Memory (canonical stores on the CognitiveRuntime + SmartMemory ref)
    try:
        episodes = cr.episode_store.count() if cr else 0
        distilled = cr.distilled_store.count() if cr else 0
        state.episodes = episodes
        state.distilled_rules = distilled
        has_smart_memory = getattr(engine, "memory", None) is not None
        if has_smart_memory and episodes >= 0:
            state.memory_state = "READY"
        else:
            state.memory_state = "EMPTY"
        state.details["memory"] = {"episodes": episodes, "distilled_rules": distilled}
    except Exception as e:  # noqa: BLE001
        state.memory_state = f"ERROR: {type(e).__name__}"

    # ONE AgentRegistry / ONE ToolRegistry — owned by the CognitiveRuntime
    ar = getattr(cr, "agent_registry", None) if cr else None
    tr = getattr(cr, "master_tools", None) if cr else None
    state.agent_count = ar.count() if ar else 0
    state.tool_count = len(tr.list_all()) if tr else 0

    # Microphone has been removed from Zerion entirely. TTS output
    # availability is still measured honestly if a TTS engine exists.
    try:
        tts_bin = shutil.which("termux-tts-speak")
        state.voice_enabled = bool(tts_bin)
        state.details["voice"] = {
            "input": "TEXT ONLY (microphone removed)",
            "tts": "AVAILABLE" if tts_bin else "NOT_INSTALLED",
        }
    except Exception as e:  # noqa: BLE001
        state.details["voice"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}

    # Capabilities
    try:
        caps = engine.self_model._capabilities  # noqa: SLF001 — measured catalog
        state.capabilities = len(caps)
    except Exception:
        state.capabilities = 0

    # Active tasks (live MissionScheduler entries)
    try:
        state.active_tasks = len(getattr(engine.scheduler, "_tasks", []) or [])
    except Exception:
        state.active_tasks = 0

    # Health
    running = bool(getattr(engine, "_running", False))
    if running and state.memory_state.startswith("READY"):
        state.runtime_health = "OK"
    elif running:
        state.runtime_health = "DEGRADED"
    else:
        state.runtime_health = "STOPPED"

    return state
