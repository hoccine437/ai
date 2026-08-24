"""
Decision policy — principle 9: Zerion knows when to ACT, ASK, or RETREAT.

Deterministic, inspectable policy over the same evidence the runtime already
holds (task uncertainty/stakes, model availability, permissions, missing
information). No randomness, no hidden heuristics — every verdict carries an
explicit reason string so callers (CLI, UI, tests) can see WHY a decision was
made.

Rules (evaluated in order, first match wins):

1. permission denied  -> STOP          (unsafe/unauthorized: never proceed)
2. no model/provider  -> RETRY later   (nothing to execute; retryable)
3. high stakes AND (high uncertainty OR low confidence) -> ASK
   (high uncertainty + high stakes: human decision required)
4. high uncertainty   -> VERIFY        (verify before believing/acting)
5. missing info       -> DEFER         (blocked on missing information)
6. low risk + high confidence -> ACT
7. otherwise          -> WAIT          (re-evaluate later)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    ACT = "ACT"
    ASK = "ASK"
    WAIT = "WAIT"
    VERIFY = "VERIFY"
    RETRY = "RETRY"
    DEFER = "DEFER"
    STOP = "STOP"


@dataclass(frozen=True)
class DecisionVerdict:
    decision: Decision
    reason: str

    def to_dict(self) -> dict:
        return {"decision": self.decision.value, "reason": self.reason}


class DecisionPolicy:
    """Deterministic ACT/ASK/WAIT/VERIFY/RETRY/DEFER/STOP policy."""

    def decide(self, *,
               uncertainty: float = 0.0,
               stakes: float = 0.0,
               confidence: float = 0.0,
               missing_information: bool = False,
               permissions_allowed: bool = True,
               provider_available: bool = True) -> DecisionVerdict:
        if not permissions_allowed:
            return DecisionVerdict(
                Decision.STOP,
                "permission boundary denies this action (unsafe/unauthorized)")
        if not provider_available:
            return DecisionVerdict(
                Decision.RETRY,
                "no model provider available to execute — retry once one is")
        if stakes >= 0.7 and (uncertainty >= 0.7 or confidence < 0.3):
            return DecisionVerdict(
                Decision.ASK,
                f"high stakes ({stakes:.2f}) with high uncertainty "
                f"({uncertainty:.2f}) — human decision required")
        if uncertainty >= 0.7:
            return DecisionVerdict(
                Decision.VERIFY,
                f"high uncertainty ({uncertainty:.2f}) — verify before "
                f"treating output as established")
        if missing_information:
            return DecisionVerdict(
                Decision.DEFER,
                "missing information blocks a reliable action")
        if stakes < 0.3 and confidence >= 0.7:
            return DecisionVerdict(
                Decision.ACT,
                f"low risk ({stakes:.2f}) with high confidence "
                f"({confidence:.2f}) — safe to act")
        return DecisionVerdict(
            Decision.WAIT,
            f"no decisive condition met (uncertainty={uncertainty:.2f}, "
            f"stakes={stakes:.2f}, confidence={confidence:.2f}) — wait")
