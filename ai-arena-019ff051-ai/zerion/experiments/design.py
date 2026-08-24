"""
Experiment Design Specifications and Protocols
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class ExperimentDesign:
    hypothesis_statement: str
    id: str = field(default_factory=lambda: f"exp_{uuid.uuid4().hex[:8]}")
    hypothesis_id: Optional[str] = None
    variable_name: str = "target_variable"
    control_condition: Any = None
    test_condition: Any = None
    execution_code: str = ""
    timeout_seconds: float = 5.0
    expected_outcome: Any = None
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "hypothesis_statement": self.hypothesis_statement,
            "hypothesis_id": self.hypothesis_id,
            "variable_name": self.variable_name,
            "control_condition": self.control_condition,
            "test_condition": self.test_condition,
            "execution_code": self.execution_code,
            "timeout_seconds": self.timeout_seconds,
            "expected_outcome": self.expected_outcome,
            "created_at": self.created_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperimentDesign":
        return cls(
            id=data.get("id", f"exp_{uuid.uuid4().hex[:8]}"),
            hypothesis_statement=data.get("hypothesis_statement", ""),
            hypothesis_id=data.get("hypothesis_id"),
            variable_name=data.get("variable_name", "target_variable"),
            control_condition=data.get("control_condition"),
            test_condition=data.get("test_condition"),
            execution_code=data.get("execution_code", ""),
            timeout_seconds=data.get("timeout_seconds", 5.0),
            expected_outcome=data.get("expected_outcome"),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {})
        )
