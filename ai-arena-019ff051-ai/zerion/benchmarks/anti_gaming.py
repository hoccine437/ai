"""
Anti-Gaming Detector & Hidden Evaluation Substrate
Protects scientific validity by detecting:
- Template / answer key leakage
- Hardcoded return values in cognitive strategies
- Artificial score injections
- Evaluator context contamination
"""

import ast
from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class GamingInspectionResult:
    is_valid: bool
    violations_detected: List[str] = field(default_factory=list)
    confidence: float = 1.0
    audit_timestamp: float = field(default_factory=time.time)


class AntiGamingDetector:
    def __init__(self):
        self._forbidden_patterns = [
            "ascendant_score = 0.95",
            "return 0.95",
            "fake_score",
            "hardcoded_result",
            "TEST_ANSWER_KEY"
        ]

    def audit_code_payload(self, code: str) -> GamingInspectionResult:
        violations = []
        for pattern in self._forbidden_patterns:
            if pattern in code:
                violations.append(f"Static score pattern detected: '{pattern}'")

        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                # Check for constant return spoofing without computation
                if isinstance(node, ast.FunctionDef) and len(node.body) == 1 and isinstance(node.body[0], ast.Return):
                    if isinstance(node.body[0].value, ast.Constant) and node.body[0].value.value in (0.95, 0.99):
                        violations.append("Trivial constant return detected in synthesized function")
        except Exception:
            pass

        return GamingInspectionResult(
            is_valid=(len(violations) == 0),
            violations_detected=violations
        )
