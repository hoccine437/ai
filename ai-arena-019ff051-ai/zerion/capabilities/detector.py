"""
Capability Gap Detection and 10-Class Failure Taxonomy
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid


class GapType(str, Enum):
    KNOWLEDGE_GAP = "knowledge_gap"
    TOOL_GAP = "tool_gap"
    REASONING_GAP = "reasoning_gap"
    PERCEPTION_GAP = "perception_gap"
    PLANNING_GAP = "planning_gap"
    VERIFICATION_GAP = "verification_gap"
    COMPUTE_LIMITATION = "compute_limitation"
    MODEL_LIMITATION = "model_limitation"
    MEMORY_LIMITATION = "memory_limitation"
    EXECUTION_LIMITATION = "execution_limitation"


@dataclass
class CapabilityGap:
    id: str = field(default_factory=lambda: f"gap_{uuid.uuid4().hex[:8]}")
    gap_type: GapType = GapType.TOOL_GAP
    task_goal: str = ""
    error_message: str = ""
    missing_capability_name: str = ""
    required_inputs: List[str] = field(default_factory=list)
    expected_outputs: List[str] = field(default_factory=list)
    urgency: float = 0.8
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "gap_type": self.gap_type.value if isinstance(self.gap_type, GapType) else str(self.gap_type),
            "task_goal": self.task_goal,
            "error_message": self.error_message,
            "missing_capability_name": self.missing_capability_name,
            "required_inputs": self.required_inputs,
            "expected_outputs": self.expected_outputs,
            "urgency": round(self.urgency, 4),
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }


class CapabilityGapDetector:
    def __init__(self):
        pass

    def classify_failure(
        self,
        task_goal: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> CapabilityGap:
        err_lower = error_message.lower()
        ctx = context or {}

        # Default classification heuristics
        if "not found" in err_lower or "no tool" in err_lower or "missing function" in err_lower or "no module" in err_lower:
            gap_type = GapType.TOOL_GAP
        elif "timeout" in err_lower or "memory" in err_lower or "out of memory" in err_lower:
            gap_type = GapType.COMPUTE_LIMITATION
        elif "unknown property" in err_lower or "epistemic void" in err_lower or "missing data" in err_lower:
            gap_type = GapType.KNOWLEDGE_GAP
        elif "contradiction" in err_lower or "invariant violation" in err_lower:
            gap_type = GapType.VERIFICATION_GAP
        elif "planning" in err_lower or "cycle detected" in err_lower:
            gap_type = GapType.PLANNING_GAP
        elif "sensor" in err_lower or "unobserved" in err_lower:
            gap_type = GapType.PERCEPTION_GAP
        elif "model" in err_lower or "rate limit" in err_lower:
            gap_type = GapType.MODEL_LIMITATION
        elif "permission" in err_lower or "sandbox" in err_lower:
            gap_type = GapType.EXECUTION_LIMITATION
        else:
            gap_type = GapType.REASONING_GAP

        missing_cap = f"solve_{gap_type.value}_{task_goal.lower().replace(' ', '_')[:25]}"

        return CapabilityGap(
            gap_type=gap_type,
            task_goal=task_goal,
            error_message=error_message,
            missing_capability_name=missing_cap,
            required_inputs=["context", "parameters"],
            expected_outputs=["result", "evidence"],
            urgency=0.85
        )
