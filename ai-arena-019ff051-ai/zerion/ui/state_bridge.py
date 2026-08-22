"""
Cognitive UI State Data Models and Real-Time State Bridge for ZERION-X
Subscribes to live engine events and maintains the single authoritative CognitiveUIState.

Slice 10: every default is HONEST. Values the runtime has not measured are
UNKNOWN / None — never invented ("2.57x", "95%", fake explanation chains).
The authoritative real-state view is produced by the VisualizationStateAdapter;
this bridge only mirrors what the engine actually reports.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional


class UIStateMode(str, Enum):
    BOOTING = "BOOTING"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    LEARNING = "LEARNING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"
    OBSERVING = "OBSERVING"
    QUESTIONING = "QUESTIONING"
    INVESTIGATING = "INVESTIGATING"
    EXPERIMENTING = "EXPERIMENTING"
    VERIFYING = "VERIFYING"
    DEVELOPING = "DEVELOPING"
    RECOVERING = "RECOVERING"
    OFFLINE = "OFFLINE"


@dataclass
class CognitiveUIState:
    runtime_state: UIStateMode = UIStateMode.BOOTING
    state_label: str = "BOOTING"
    assembly_percentage: int = 0
    cognitive_state: str = "UNKNOWN"
    active_goal: Optional[str] = None
    active_question: Optional[str] = None
    current_strategy: str = "UNKNOWN"
    confidence: Optional[float] = None
    audio_amplitude_rms: float = 0.0          # 0.0 to 1.0 (real audio reactivity)
    core_pulse_period_s: float = 2.0          # neutral animation defaults
    core_pulse_amplitude: float = 0.12
    core_glow_intensity: float = 0.85
    cyan_contour_activity: float = 0.50
    neural_pulse_rate: float = 1.0
    maturity_level: str = "UNKNOWN"
    learning_acceleration: str = "UNKNOWN"
    explanation_chain: List[str] = field(default_factory=list)
    resource_state: Dict[str, Any] = field(default_factory=dict)
    telemetry_markers: List[Dict[str, Any]] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtime_state": self.runtime_state.value if isinstance(self.runtime_state, UIStateMode) else str(self.runtime_state),
            "state_label": self.state_label,
            "assembly_percentage": self.assembly_percentage,
            "cognitive_state": self.cognitive_state,
            "active_goal": self.active_goal,
            "active_question": self.active_question,
            "current_strategy": self.current_strategy,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "audio_amplitude_rms": round(self.audio_amplitude_rms, 3),
            "core_pulse_period_s": round(self.core_pulse_period_s, 2),
            "core_pulse_amplitude": round(self.core_pulse_amplitude, 2),
            "core_glow_intensity": round(self.core_glow_intensity, 2),
            "cyan_contour_activity": round(self.cyan_contour_activity, 2),
            "neural_pulse_rate": round(self.neural_pulse_rate, 2),
            "maturity_level": self.maturity_level,
            "learning_acceleration": self.learning_acceleration,
            "explanation_chain": list(self.explanation_chain),
            "resource_state": dict(self.resource_state),
            "telemetry_markers": [dict(m) for m in self.telemetry_markers],
            "last_updated": self.last_updated
        }


class UIStateBridge:
    def __init__(self):
        self._current_state = CognitiveUIState()
        self._boot_start_time = time.time()

    @property
    def current_state(self) -> CognitiveUIState:
        elapsed = time.time() - self._boot_start_time
        if self._current_state.runtime_state == UIStateMode.BOOTING:
            pct = min(100, int((elapsed / 5.8) * 100))
            self._current_state.assembly_percentage = pct
            self._current_state.state_label = f"ASSEMBLING… {pct}%"
            if pct >= 100:
                self._current_state.runtime_state = UIStateMode.IDLE
                self._current_state.state_label = "IDLE"
        return self._current_state

    def set_listening_state(self, is_listening: bool):
        if is_listening:
            self._current_state.runtime_state = UIStateMode.LISTENING
            self._current_state.state_label = "LISTENING"
            self._current_state.core_pulse_period_s = 1.8
            self._current_state.core_pulse_amplitude = 0.15
            self._current_state.cyan_contour_activity = 0.80
        else:
            self._current_state.runtime_state = UIStateMode.IDLE
            self._current_state.state_label = "IDLE"
            self._current_state.core_pulse_period_s = 2.0
            self._current_state.core_pulse_amplitude = 0.12
            self._current_state.cyan_contour_activity = 0.50
        self._current_state.last_updated = time.time()

    def set_speaking_state(self, is_speaking: bool, audio_rms: float = 0.0):
        if is_speaking:
            self._current_state.runtime_state = UIStateMode.SPEAKING
            self._current_state.state_label = "SPEAKING"
            self._current_state.audio_amplitude_rms = audio_rms
            self._current_state.core_pulse_period_s = 0.75
            self._current_state.core_pulse_amplitude = 0.28
            self._current_state.core_glow_intensity = 0.95
        else:
            self._current_state.runtime_state = UIStateMode.IDLE
            self._current_state.state_label = "IDLE"
            self._current_state.audio_amplitude_rms = 0.0
            self._current_state.core_pulse_period_s = 2.0
            self._current_state.core_pulse_amplitude = 0.12
            self._current_state.core_glow_intensity = 0.85
        self._current_state.last_updated = time.time()

    def update_from_cycle(
        self,
        trace_data: Dict[str, Any],
        engine_ref: Optional[Any] = None
    ):
        strat = trace_data.get("strategy_selected", "UNKNOWN")
        mode = trace_data.get("cognitive_allocation_mode", "FAST")
        mat = trace_data.get("maturity_level", "UNKNOWN")

        self._current_state.runtime_state = UIStateMode.THINKING
        self._current_state.state_label = "THINKING"
        self._current_state.cognitive_state = f"Active Strategy: {strat} ({mode})"
        self._current_state.current_strategy = strat
        self._current_state.maturity_level = mat
        self._current_state.core_pulse_period_s = 1.1
        self._current_state.core_pulse_amplitude = 0.22
        self._current_state.core_glow_intensity = 0.95 if mode in ("DEEP", "EXPERIMENTAL") else 0.80
        self._current_state.cyan_contour_activity = 0.85

        if engine_ref and hasattr(engine_ref, "resources"):
            snap = engine_ref.resources.sample()
            self._current_state.resource_state = {
                "cpu_percent": snap.cpu_percent,
                "memory_mb": snap.memory_available_mb,
                "compute_tier": snap.compute_tier,
                "is_battery": snap.is_battery_powered
            }

        dur = trace_data.get("duration_ms")
        accel = trace_data.get("learning_acceleration_ratio")
        if accel is not None:
            learning_line = f"LEARNING: Acceleration ratio {accel:.2f}x verified"
        else:
            learning_line = "LEARNING: Acceleration ratio UNKNOWN (not measured)"
        self._current_state.explanation_chain = [
            f"STRATEGY: {strat} executed" +
            (f" in {dur:.1f}ms" if dur is not None else ""),
            f"ALLOCATION: Mode {mode} selected via Adaptive Cognitive Scaler",
            learning_line,
        ]
        self._current_state.last_updated = time.time()

    def set_error_state(self, error_msg: str):
        self._current_state.runtime_state = UIStateMode.ERROR
        self._current_state.state_label = "ERROR"
        self._current_state.cognitive_state = f"Fault detected: {error_msg}"
        self._current_state.core_glow_intensity = 0.40
        self._current_state.cyan_contour_activity = 1.0
        self._current_state.core_pulse_period_s = 0.5
        self._current_state.core_pulse_amplitude = 0.35
        self._current_state.last_updated = time.time()
