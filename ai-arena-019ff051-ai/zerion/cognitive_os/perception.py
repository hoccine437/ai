"""
Perception Processor for Cognitive OS
Ingests environment, hardware, and runtime signals into structured perception frames.
"""

import time
from typing import Any, Dict, List, Optional
from zerion.cognitive_os.attention import PerceptionFrame


class PerceptionProcessor:
    def __init__(self):
        self._frame_history: List[PerceptionFrame] = []

    def capture_frame(
        self,
        source: str,
        metrics: Dict[str, float],
        signals: Optional[Dict[str, Any]] = None,
        epistemic_tags: Optional[Dict[str, str]] = None
    ) -> PerceptionFrame:
        frame = PerceptionFrame(
            source=source,
            raw_signals=signals or {},
            observed_metrics=metrics,
            epistemic_tags=epistemic_tags or {k: "MEASURED" for k in metrics.keys()},
            timestamp=time.time()
        )
        self._frame_history.append(frame)
        if len(self._frame_history) > 100:
            self._frame_history = self._frame_history[-100:]
        return frame

    def get_latest_frame(self) -> Optional[PerceptionFrame]:
        return self._frame_history[-1] if self._frame_history else None
