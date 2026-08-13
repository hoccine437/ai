"""
Pressure Field Engine and Active Gradient Aggregator
"""

from dataclasses import dataclass, field
import time
from typing import Dict, List, Optional
from zerion.pressure.signals import PressureSignal, SignalType
from zerion.world.graph import WorldModel
from zerion.self_model.introspector import SelfModel
from zerion.identity.persistence import IdentityCore


class PressureField:
    def __init__(self, decay_rate: float = 0.05):
        self.decay_rate = decay_rate
        self._signals: Dict[str, PressureSignal] = {}
        self._last_evaluated_at: float = time.time()

    def inject_signal(self, signal: PressureSignal):
        self._signals[signal.id] = signal

    def get_signal(self, signal_id: str) -> Optional[PressureSignal]:
        return self._signals.get(signal_id)

    def sample_field(
        self,
        world_model: Optional[WorldModel] = None,
        self_model: Optional[SelfModel] = None,
        identity_core: Optional[IdentityCore] = None
    ) -> List[PressureSignal]:
        """
        Actively scans connected subsystems for latent pressures:
        1. World Model: Epistemic UNKNOWNs, unverified causal hypotheses, high drift.
        2. Self Model: Low reliability capabilities (< 0.5), active limitations.
        3. Identity Core: Incomplete long-term objectives with zero recent progress.
        """
        now = time.time()

        if world_model:
            # Check for unknown nodes or unverified causal hypotheses
            for node in world_model.list_nodes():
                for attr_k, attr_v in node.attributes.items():
                    if attr_v.status.value == "UNKNOWN":
                        self.inject_signal(PressureSignal(
                            signal_type=SignalType.KNOWLEDGE_GAP,
                            magnitude=0.7,
                            source=f"world_node:{node.id}:{attr_k}",
                            description=f"Unknown property '{attr_k}' on entity '{node.name}'",
                            metadata={"node_id": node.id, "key": attr_k}
                        ))

            for hyp in world_model._causal_hypotheses.values():
                if not hyp.verified and hyp.falsification_attempts == 0:
                    self.inject_signal(PressureSignal(
                        signal_type=SignalType.OPPORTUNITY,
                        magnitude=0.65,
                        source=f"causal_hyp:{hyp.id}",
                        description=f"Untested causal hypothesis: '{hyp.cause}' causes '{hyp.effect}'",
                        metadata={"hyp_id": hyp.id}
                    ))

        if self_model:
            for cap in self_model._capabilities.values():
                if cap.invocations > 2 and cap.reliability < 0.6:
                    self.inject_signal(PressureSignal(
                        signal_type=SignalType.CAPABILITY_GAP,
                        magnitude=1.0 - cap.reliability,
                        source=f"self_cap:{cap.name}",
                        description=f"Low reliability ({cap.reliability * 100:.1f}%) on capability '{cap.name}'",
                        metadata={"capability": cap.name, "reliability": cap.reliability}
                    ))

        if identity_core:
            for obj in identity_core.list_objectives(active_only=True):
                if obj.progress < 1.0 and (now - obj.updated_at) > 3600:
                    self.inject_signal(PressureSignal(
                        signal_type=SignalType.UNFINISHED_GOAL,
                        magnitude=min(1.0, (obj.priority / 100.0) * (1.0 - obj.progress)),
                        source=f"objective:{obj.id}",
                        description=f"Long-term objective '{obj.title}' is stalled at {obj.progress * 100:.1f}%",
                        metadata={"objective_id": obj.id}
                    ))

        # Apply time decay to older signals
        active_signals = []
        for sid, sig in list(self._signals.items()):
            age_hours = (now - sig.timestamp) / 3600.0
            decayed_mag = sig.magnitude * max(0.1, (1.0 - (self.decay_rate * age_hours)))
            sig.magnitude = round(decayed_mag, 4)
            if sig.magnitude >= 0.15:
                active_signals.append(sig)
            else:
                del self._signals[sid]

        self._last_evaluated_at = now
        return sorted(active_signals, key=lambda s: s.magnitude, reverse=True)

    @property
    def total_pressure(self) -> float:
        if not self._signals:
            return 0.0
        return round(sum(s.magnitude for s in self._signals.values()), 3)
