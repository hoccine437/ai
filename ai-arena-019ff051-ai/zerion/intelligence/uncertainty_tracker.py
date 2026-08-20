"""
UncertaintyTracker — Tracks what Zerion knows, doesn't know, and why.

Instead of a single confidence number, this system tracks:
- Per-belief state: KNOWN, SUPPORTED, LIKELY, UNCERTAIN, ASSUMED, UNKNOWN, CONTRADICTED
- Sources of uncertainty: missing info, conflicting evidence, weak model, etc.
- Decision-relevant uncertainty: which uncertainty matters for the current decision
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class BeliefState(Enum):
    """States of knowledge for any belief."""
    KNOWN = "known"              # Verified, high confidence
    SUPPORTED = "supported"       # Has evidence, reasonable confidence
    LIKELY = "likely"             # Probable but not verified
    UNCERTAIN = "uncertain"       # Low confidence, could be wrong
    ASSUMED = "assumed"           # Unverified assumption
    UNKNOWN = "unknown"           # No information
    CONTRADICTED = "contradicted" # Conflicting evidence exists


class UncertaintySource(Enum):
    """Where uncertainty comes from."""
    MISSING_INFORMATION = "missing_information"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    WEAK_MODEL = "weak_model"
    UNRELIABLE_SOURCE = "unreliable_source"
    AMBIGUOUS_GOAL = "ambiguous_goal"
    UNKNOWN_EXTERNAL_STATE = "unknown_external_state"
    INSUFFICIENT_EXPERIENCE = "insufficient_experience"
    NOVEL_SITUATION = "novel_situation"
    COMPETING_HYPOTHESES = "competing_hypotheses"
    TIME_PRESSURE = "time_pressure"


@dataclass
class Belief:
    """A single belief with its state and metadata."""
    id: str = ""
    content: str = ""
    state: BeliefState = BeliefState.ASSUMED
    confidence: float = 0.5
    source: str = ""
    evidence: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    uncertainty_sources: List[UncertaintySource] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    access_count: int = 0
    dependencies: List[str] = field(default_factory=list)  # IDs of other beliefs
    context: str = ""

    @property
    def is_reliable(self) -> bool:
        """Is this belief reliable enough for decision-making?"""
        return self.state in (BeliefState.KNOWN, BeliefState.SUPPORTED) and self.confidence >= 0.7

    @property
    def needs_verification(self) -> bool:
        """Should this belief be verified before using in important decisions?"""
        return self.state in (BeliefState.ASSUMED, BeliefState.UNCERTAIN, BeliefState.CONTRADICTED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "state": self.state.value,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "evidence_count": len(self.evidence),
            "contradictions_count": len(self.contradictions),
            "uncertainty_sources": [u.value for u in self.uncertainty_sources],
            "is_reliable": self.is_reliable,
            "needs_verification": self.needs_verification,
        }


@dataclass
class UncertaintyAssessment:
    """Assessment of uncertainty in the current situation."""
    # Overall uncertainty level (0-1)
    overall_uncertainty: float = 0.0

    # Primary source of uncertainty
    primary_source: Optional[UncertaintySource] = None

    # All active uncertainty sources
    sources: List[Tuple[UncertaintySource, float]] = field(default_factory=list)

    # Beliefs that contribute most to uncertainty
    uncertain_beliefs: List[str] = field(default_factory=list)

    # What information would reduce uncertainty the most
    highest_value_information: List[str] = field(default_factory=list)

    # Should we proceed or gather more information?
    recommendation: str = "proceed"

    def to_prompt_context(self) -> str:
        """Format for LLM context."""
        parts = [f"UNCERTAINTY: {self.overall_uncertainty:.2f}"]
        if self.primary_source:
            parts.append(f"PRIMARY_SOURCE: {self.primary_source.value}")
        if self.uncertain_beliefs:
            parts.append(f"UNCERTAIN_ABOUT: {'; '.join(self.uncertain_beliefs[:3])}")
        if self.highest_value_information:
            parts.append(f"NEED_INFO: {'; '.join(self.highest_value_information[:3])}")
        parts.append(f"RECOMMENDATION: {self.recommendation}")
        return "\n".join(parts)


# ── Uncertainty patterns for input analysis ───────────────────────────────────

UNCERTAINTY_PATTERNS: Dict[UncertaintySource, List[str]] = {
    UncertaintySource.MISSING_INFORMATION: [
        r"\b(don.t\s+know|not\s+sure|unclear|unknown|missing|lack)\b",
        r"\b(how\s+much|how\s+many|how\s+long|when\s+exactly)\b",
    ],
    UncertaintySource.CONFLICTING_EVIDENCE: [
        r"\b(but|however|on\s+the\s+other\s+hand|contradicts|conflicts)\b",
    ],
    UncertaintySource.AMBIGUOUS_GOAL: [
        r"\b(which|what\s+exactly|clarify|meaning|intent)\b",
    ],
    UncertaintySource.NOVEL_SITUATION: [
        r"\b(never\s+seen|new|first\s+time|novel|unprecedented)\b",
    ],
    UncertaintySource.TIME_PRESSURE: [
        r"\b(urgent|asap|now|quickly|fast|immediately|hurry)\b",
    ],
}


class UncertaintyTracker:
    """Tracks the state of Zerion's knowledge and sources of uncertainty.
    
    Instead of a single confidence score, this provides a nuanced picture
    of what Zerion knows, what it doesn't know, and what it would need
    to know to make a better decision.
    """

    def __init__(self):
        self._beliefs: Dict[str, Belief] = {}
        self._belief_counter: int = 0

    def register_belief(
        self,
        content: str,
        *,
        state: BeliefState = BeliefState.ASSUMED,
        confidence: float = 0.5,
        source: str = "",
        evidence: Optional[List[str]] = None,
        context: str = "",
    ) -> Belief:
        """Register a new belief."""
        self._belief_counter += 1
        belief = Belief(
            id=f"belief_{self._belief_counter}",
            content=content,
            state=state,
            confidence=confidence,
            source=source,
            evidence=evidence or [],
            context=context,
        )
        self._beliefs[belief.id] = belief
        return belief

    def update_belief(
        self,
        belief_id: str,
        *,
        new_evidence: Optional[str] = None,
        contradiction: Optional[str] = None,
        state: Optional[BeliefState] = None,
        confidence_delta: float = 0.0,
    ) -> Optional[Belief]:
        """Update a belief with new evidence or contradictions."""
        belief = self._beliefs.get(belief_id)
        if not belief:
            return None

        belief.last_updated = time.time()

        if new_evidence:
            belief.evidence.append(new_evidence)
            belief.confidence = min(1.0, belief.confidence + 0.1)
            if belief.state == BeliefState.ASSUMED:
                belief.state = BeliefState.SUPPORTED

        if contradiction:
            belief.contradictions.append(contradiction)
            belief.confidence = max(0.0, belief.confidence - 0.15)
            if belief.state in (BeliefState.KNOWN, BeliefState.SUPPORTED):
                belief.state = BeliefState.CONTRADICTED

        if state:
            belief.state = state

        if confidence_delta:
            belief.confidence = max(0.0, min(1.0, belief.confidence + confidence_delta))

        return belief

    def assess_situation_uncertainty(
        self,
        user_input: str,
        intent: str = "",
        available_info: Optional[Dict[str, Any]] = None,
        past_failures: Optional[List[str]] = None,
    ) -> UncertaintyAssessment:
        """Assess uncertainty for the current situation.
        
        Returns a structured assessment of what's uncertain and what
        information would be most valuable.
        """
        assessment = UncertaintyAssessment()
        info = available_info or {}
        lower = user_input.lower()

        # 1. Detect uncertainty sources from input
        source_scores: Dict[UncertaintySource, float] = {}
        for source, patterns in UNCERTAINTY_PATTERNS.items():
            for pattern in patterns:
                import re
                if re.search(pattern, lower):
                    source_scores[source] = source_scores.get(source, 0) + 0.3

        # 2. Check if we have relevant knowledge
        if not info.get("has_memory"):
            source_scores[UncertaintySource.INSUFFICIENT_EXPERIENCE] = (
                source_scores.get(UncertaintySource.INSUFFICIENT_EXPERIENCE, 0) + 0.2
            )

        # 3. Check if this is a novel situation
        if not info.get("has_similar_past"):
            source_scores[UncertaintySource.NOVEL_SITUATION] = (
                source_scores.get(UncertaintySource.NOVEL_SITUATION, 0) + 0.15
            )

        # 4. Check for past failures on similar topics
        if past_failures:
            source_scores[UncertaintySource.WEAK_MODEL] = (
                source_scores.get(UncertaintySource.WEAK_MODEL, 0) + 0.2
            )

        # 5. Ambiguity detection
        if any(w in lower for w in ["it", "this", "that", "ها", "ton"]):
            source_scores[UncertaintySource.AMBIGUOUS_GOAL] = (
                source_scores.get(UncertaintySource.AMBIGUOUS_GOAL, 0) + 0.25
            )

        # Build assessment
        if source_scores:
            sorted_sources = sorted(source_scores.items(), key=lambda x: x[1], reverse=True)
            assessment.sources = sorted_sources
            assessment.primary_source = sorted_sources[0][0]
            assessment.overall_uncertainty = min(1.0, sum(v for _, v in sorted_sources[:3]) / 3)

        # 6. Generate highest-value information questions
        if assessment.primary_source == UncertaintySource.MISSING_INFORMATION:
            assessment.highest_value_information = [
                "What specific details are missing?",
                "What would resolve the ambiguity?",
            ]
        elif assessment.primary_source == UncertaintySource.CONFLICTING_EVIDENCE:
            assessment.highest_value_information = [
                "What evidence supports each side?",
                "Which evidence is more reliable?",
            ]
        elif assessment.primary_source == UncertaintySource.AMBIGUOUS_GOAL:
            assessment.highest_value_information = [
                "What does the user actually want?",
                "What would success look like?",
            ]
        elif assessment.primary_source == UncertaintySource.NOVEL_SITUATION:
            assessment.highest_value_information = [
                "What related situations have we seen?",
                "What assumptions are we making?",
            ]

        # 7. Recommendation
        if assessment.overall_uncertainty > 0.7:
            assessment.recommendation = "gather_information"
        elif assessment.overall_uncertainty > 0.4:
            assessment.recommendation = "proceed_with_caution"
        else:
            assessment.recommendation = "proceed"

        return assessment

    def get_relevant_beliefs(self, query: str, top_k: int = 5) -> List[Belief]:
        """Retrieve beliefs relevant to a query."""
        import re
        query_words = set(re.findall(r"[a-z0-9]{2,}", query.lower()))
        scored: List[Tuple[float, Belief]] = []

        for belief in self._beliefs.values():
            belief_words = set(re.findall(r"[a-z0-9]{2,}", belief.content.lower()))
            overlap = len(query_words & belief_words)
            if overlap > 0:
                score = overlap / max(len(query_words), 1) * belief.confidence
                scored.append((score, belief))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [b for _, b in scored[:top_k]]

    def get_all_beliefs(self) -> List[Belief]:
        """Get all tracked beliefs."""
        return list(self._beliefs.values())

    def count_by_state(self) -> Dict[str, int]:
        """Count beliefs by state."""
        counts: Dict[str, int] = {}
        for belief in self._beliefs.values():
            key = belief.state.value
            counts[key] = counts.get(key, 0) + 1
        return counts
