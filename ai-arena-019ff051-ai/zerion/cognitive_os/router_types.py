"""
Slice 6 — Cognitive Router type system.

Provider-independent structures only. The cognitive runtime must not care which
model provides its cognitive substrate; these types are the contract between
the runtime and any model provider.

No OpenAI / Google / llama.cpp objects appear here, by construction.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional, Set
import uuid


class TaskType(str, Enum):
    REASONING = "REASONING"
    CODING = "CODING"
    RETRIEVAL = "RETRIEVAL"
    VISION = "VISION"
    AUDIO = "AUDIO"
    CONVERSATION = "CONVERSATION"
    PLANNING = "PLANNING"
    TOOL_USE = "TOOL_USE"
    ANALYSIS = "ANALYSIS"
    ARCHITECTURE = "ARCHITECTURE"
    OTHER = "OTHER"


class RoutingMode(str, Enum):
    # OFFLINE_ONLY removed: there is no local model and no offline brain.
    ONLINE_ALLOWED = "ONLINE_ALLOWED"
    ONLINE_PREFERRED = "ONLINE_PREFERRED"
    AUTO = "AUTO"


class ProviderStatus(str, Enum):
    AVAILABLE = "AVAILABLE"          # genuinely usable right now
    DEGRADED = "DEGRADED"            # usable but failing / slow recently
    UNAVAILABLE = "UNAVAILABLE"      # configured but not functional
    NOT_CONFIGURED = "NOT_CONFIGURED"  # missing credentials/config
    UNKNOWN = "UNKNOWN"              # no calls yet — never assume from config


class ResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    QUOTA_FAILURE = "QUOTA_FAILURE"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"
    RESOURCE_EXHAUSTION = "RESOURCE_EXHAUSTION"
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    MODEL_LOAD_FAILURE = "MODEL_LOAD_FAILURE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    ROUTING_FAILED = "ROUTING_FAILED"
    CANCELLED = "CANCELLED"


class VerificationStatus(str, Enum):
    """Model output is NEVER automatically truth.

    MODEL_OUTPUT   — produced by a model (Slice 3: MODEL_GENERATED evidence)
    OBSERVED_RESULT — corroborated by real-world/tool observation (OBSERVED)
    VERIFIED_RESULT — passed verification against reality (verified belief)
    """

    MODEL_OUTPUT = "MODEL_OUTPUT"
    OBSERVED_RESULT = "OBSERVED_RESULT"
    VERIFIED_RESULT = "VERIFIED_RESULT"


class CognitiveField(str, Enum):
    FAST_FIELD = "FAST_FIELD"
    DEEP_FIELD = "DEEP_FIELD"


@dataclass
class Task:
    """A structured task the router must dispatch (never a bare string)."""

    type: TaskType = TaskType.REASONING
    description: str = ""
    difficulty: float = 0.0          # 0..1
    uncertainty: float = 0.0         # 0..1
    novelty: float = 0.0             # 0..1
    stakes: float = 0.0              # 0..1
    goal_relevance: float = 0.0      # 0..1
    latency_budget_ms: Optional[int] = None
    cost_budget_cents: Optional[float] = None
    required_capabilities: Set[str] = field(default_factory=set)
    verification_required: bool = False  # output must not become truth unaided
    metadata: Dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:12]}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "type": self.type.value,
            "description": self.description,
            "difficulty": self.difficulty,
            "uncertainty": self.uncertainty,
            "novelty": self.novelty,
            "stakes": self.stakes,
            "goal_relevance": self.goal_relevance,
            "latency_budget_ms": self.latency_budget_ms,
            "cost_budget_cents": self.cost_budget_cents,
            "required_capabilities": sorted(self.required_capabilities),
            "verification_required": self.verification_required,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Cognitive depth score — explicit, deterministic, inspectable, configurable.
# ---------------------------------------------------------------------------

@dataclass
class DepthWeights:
    uncertainty: float = 0.25
    novelty: float = 0.15
    stakes: float = 0.20
    goal_relevance: float = 0.10
    contradiction: float = 0.10
    historical_failure_rate: float = 0.10
    expected_value: float = 0.10

    def as_dict(self) -> Dict[str, float]:
        return {
            "uncertainty": self.uncertainty,
            "novelty": self.novelty,
            "stakes": self.stakes,
            "goal_relevance": self.goal_relevance,
            "contradiction": self.contradiction,
            "historical_failure_rate": self.historical_failure_rate,
            "expected_value": self.expected_value,
        }


class CognitiveDepthLevel(str, Enum):
    D0_REFLEX = "D0_REFLEX"                     # lookup / deterministic rule
    D1_DIRECT_REASONING = "D1_DIRECT_REASONING"  # single-pass fast model
    D2_VERIFICATION = "D2_VERIFICATION"          # direct + deterministic verifier
    D3_MULTI_HYPOTHESIS = "D3_MULTI_HYPOTHESIS"  # competing hypotheses
    D4_EXPERIMENTATION = "D4_EXPERIMENTATION"    # sandbox/reality tests
    D5_ADVERSARIAL_CHALLENGE = "D5_ADVERSARIAL_CHALLENGE"  # independent challenge
    D6_ARCHITECTURE_INVESTIGATION = "D6_ARCHITECTURE_INVESTIGATION"


DEFAULT_DEPTH_THRESHOLDS = [0.20, 0.35, 0.50, 0.65, 0.75, 0.85]


class CognitiveDepthScore:
    """Explicit, deterministic, configurable depth scoring.

    Identical inputs produce identical scores. "Deep" is never defined as
    calling a model multiple times — it is a property of the task itself.
    """

    def __init__(self,
                 weights: Optional[DepthWeights] = None,
                 thresholds: Optional[List[float]] = None):
        self.weights = weights or DepthWeights()
        self.thresholds = thresholds or list(DEFAULT_DEPTH_THRESHOLDS)
        if len(self.thresholds) != 6:
            raise ValueError("depth thresholds must have exactly 6 cutoffs (D0..D6)")

    @staticmethod
    def _clamp(v: float) -> float:
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.0
        return max(0.0, min(1.0, v))

    def score(self, task: Task, historical_failure_rate: float = 0.0) -> float:
        """Raw depth score in [0, 1] from task properties only."""
        md = task.metadata or {}
        w = self.weights
        contradiction = self._clamp(md.get("contradiction", 0.0))
        expected_value = self._clamp(md.get("expected_value", 0.5))
        return round(
            (w.uncertainty * self._clamp(task.uncertainty)
             + w.novelty * self._clamp(task.novelty)
             + w.stakes * self._clamp(task.stakes)
             + w.goal_relevance * self._clamp(task.goal_relevance)
             + w.contradiction * contradiction
             + w.historical_failure_rate * self._clamp(historical_failure_rate)
             + w.expected_value * expected_value),
            4,
        )

    def level(self, task: Task, historical_failure_rate: float = 0.0) -> CognitiveDepthLevel:
        s = self.score(task, historical_failure_rate)
        if s < self.thresholds[0]:
            return CognitiveDepthLevel.D0_REFLEX
        if s < self.thresholds[1]:
            return CognitiveDepthLevel.D1_DIRECT_REASONING
        if s < self.thresholds[2]:
            return CognitiveDepthLevel.D2_VERIFICATION
        if s < self.thresholds[3]:
            return CognitiveDepthLevel.D3_MULTI_HYPOTHESIS
        if s < self.thresholds[4]:
            return CognitiveDepthLevel.D4_EXPERIMENTATION
        if s < self.thresholds[5]:
            return CognitiveDepthLevel.D5_ADVERSARIAL_CHALLENGE
        return CognitiveDepthLevel.D6_ARCHITECTURE_INVESTIGATION

    def field(self, task: Task, historical_failure_rate: float = 0.0) -> CognitiveField:
        lvl = self.level(task, historical_failure_rate)
        if lvl in (CognitiveDepthLevel.D0_REFLEX,
                   CognitiveDepthLevel.D1_DIRECT_REASONING,
                   CognitiveDepthLevel.D2_VERIFICATION):
            return CognitiveField.FAST_FIELD
        return CognitiveField.DEEP_FIELD


# ---------------------------------------------------------------------------
# Selection & result
# ---------------------------------------------------------------------------

@dataclass
class ModelSelection:
    """The router's structural explanation of why a model was chosen."""

    provider: str
    model: str
    reason: List[str] = field(default_factory=list)
    estimated_cost_cents: Optional[float] = None   # None = unknown, never invented
    estimated_latency_ms: Optional[float] = None   # None = unknown, never invented
    capabilities: Set[str] = field(default_factory=set)
    confidence: float = 0.0
    fallback_chain: List[Dict[str, str]] = field(default_factory=list)  # ordered
    routing_policy_version: int = 6
    depth_score: float = 0.0
    depth_level: Optional[CognitiveDepthLevel] = None
    field: Optional[CognitiveField] = None
    mode: RoutingMode = RoutingMode.AUTO

    def to_dict(self, redact: bool = True) -> Dict[str, Any]:
        data = {
            "provider": self.provider,
            "model": self.model,
            "reason": list(self.reason),
            "estimated_cost_cents": self.estimated_cost_cents,
            "estimated_latency_ms": self.estimated_latency_ms,
            "capabilities": sorted(self.capabilities),
            "confidence": round(self.confidence, 4),
            "fallback_chain": list(self.fallback_chain),
            "routing_policy_version": self.routing_policy_version,
            "depth_score": self.depth_score,
            "depth_level": self.depth_level.value if self.depth_level else None,
            "field": self.field.value if self.field else None,
            "mode": self.mode.value,
        }
        if redact:
            return redact_secrets(data)
        return data


@dataclass
class CognitiveResult:
    """Provider-independent result. Never fabricates tokens/cost/latency/
    confidence: absent telemetry stays None / UNKNOWN."""

    task_id: str
    provider: str = ""
    model: str = ""
    output: Optional[str] = None          # None on failure — no canned answers
    latency_ms: Optional[float] = None
    usage: Optional[Dict[str, Any]] = None   # only real usage from the provider
    status: ResultStatus = ResultStatus.ROUTING_FAILED
    errors: List[str] = field(default_factory=list)
    verification_required: bool = False
    verification_status: VerificationStatus = VerificationStatus.MODEL_OUTPUT
    confidence: Optional[float] = None
    mode: RoutingMode = RoutingMode.AUTO
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, redact: bool = True) -> Dict[str, Any]:
        data = {
            "task_id": self.task_id,
            "provider": self.provider,
            "model": self.model,
            "output": self.output,
            "latency_ms": self.latency_ms,
            "usage": self.usage,
            "status": self.status.value,
            "errors": list(self.errors),
            "verification_required": self.verification_required,
            "verification_status": self.verification_status.value,
            "confidence": self.confidence,
            "mode": self.mode.value,
            "metadata": dict(self.metadata),
        }
        if redact:
            return redact_secrets(data)
        return data


# ---------------------------------------------------------------------------
# Secret redaction (defense in depth: provider config never leaks into logs,
# events, UI state or selection explanations).
# ---------------------------------------------------------------------------

_SECRET_PATTERN_KEYS = (
    "api_key", "apikey", "api-key", "token", "secret", "password",
    "authorization", "auth", "credential", "private_key", "private-key",
    "access_key", "client_secret",
)

# Defense in depth: even a string VALUE that looks like a credential token is
# scrubbed (e.g. a selection explanation that accidentally embedded a key).
_TOKEN_PATTERNS = (
    r"(sk|pk|rk|vk)-[A-Za-z0-9_\-]{3,}",      # OpenAI-style sk-...
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",         # Authorization headers
    r"ghp_[A-Za-z0-9]{15,}",                    # GitHub PAT
    r"xox[baprs]-[A-Za-z0-9\-]{10,}",           # Slack tokens
    r"AIza[0-9A-Za-z\-_]{20,}",                 # Google API keys
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",       # PEM private keys
)


def _looks_secret_key(key: str) -> bool:
    k = str(key).strip().lower().replace(" ", "_").replace("-", "_")
    return any(p in k for p in _SECRET_PATTERN_KEYS)


def _scrub_string(value: str) -> str:
    import re
    out = value
    for pattern in _TOKEN_PATTERNS:
        out = re.sub(pattern, "[REDACTED]", out)
    return out


def redact_secrets(obj: Any) -> Any:
    """Recursively scrub secret-looking keys and token-shaped values in any
    dict/list/string structure."""
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if _looks_secret_key(k):
                out[k] = "[REDACTED]" if v not in (None, "") else v
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [redact_secrets(v) for v in obj]
    if isinstance(obj, str):
        return _scrub_string(obj)
    return obj


def now_ts() -> float:
    return time.time()
