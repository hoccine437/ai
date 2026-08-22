"""
World Tracker and Reality Drift Detector
"""

from dataclasses import dataclass
import time
from typing import Any, Dict, List, Optional
from zerion.world.epistemic import EpistemicStatus, EpistemicValue
from zerion.world.graph import WorldModel, WorldNode


@dataclass
class DriftAnomaly:
    node_id: str
    attribute_key: str
    expected_value: Any
    observed_value: Any
    delta_magnitude: float
    timestamp: float


class WorldTracker:
    def __init__(self, world_model: WorldModel):
        self.world = world_model
        self._drift_history: List[DriftAnomaly] = []

    def record_observation(
        self,
        node_id: str,
        attr_key: str,
        observed_val: Any,
        source: str = "sensor",
        node_type: str = "entity",
        node_name: Optional[str] = None
    ) -> Optional[DriftAnomaly]:
        """
        Records an actual observation. Compares against any PREDICTED or ASSUMED value
        to detect prediction errors or drift.
        """
        node = self.world.get_node(node_id)
        if not node:
            node = WorldNode(id=node_id, node_type=node_type, name=node_name or node_id)
            self.world.upsert_node(node)

        existing_attr = node.get_attribute(attr_key)
        anomaly = None

        if existing_attr and existing_attr.status in (EpistemicStatus.PREDICTED, EpistemicStatus.ASSUMED):
            # Compare predicted vs observed
            if existing_attr.value != observed_val:
                delta = 1.0
                if isinstance(existing_attr.value, (int, float)) and isinstance(observed_val, (int, float)):
                    denom = max(1e-5, abs(existing_attr.value))
                    delta = abs(observed_val - existing_attr.value) / denom

                anomaly = DriftAnomaly(
                    node_id=node_id,
                    attribute_key=attr_key,
                    expected_value=existing_attr.value,
                    observed_value=observed_val,
                    delta_magnitude=round(delta, 4),
                    timestamp=time.time()
                )
                self._drift_history.append(anomaly)

        # Update node attribute to OBSERVED ground truth
        node.set_attribute(
            key=attr_key,
            value=observed_val,
            status=EpistemicStatus.OBSERVED,
            confidence=1.0,
            source=source
        )
        self.world.upsert_node(node)
        return anomaly

    def get_recent_drifts(self, limit: int = 20) -> List[DriftAnomaly]:
        return self._drift_history[-limit:]
