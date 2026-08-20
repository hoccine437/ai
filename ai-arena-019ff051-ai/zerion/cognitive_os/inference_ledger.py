"""
Observable inference ledger (Slice 6 / runtime repair).

Every task the CognitiveRuntime sends to the model layer produces exactly two
records:

- ``InferenceRequest``  — what was asked, when, and what context was actually
  attached (never assumed; only sources that were really used are listed).
- ``InferenceResult``   — what came back: real generated text when the model
  ran, honest ``None`` output + structured error when it did not. No metric
  is fabricated: token counts, latency and termination reasons are recorded
  only when the underlying provider actually reports them.

The ledger is append-only and bounded (ring buffer). It is runtime-observable
via ``CognitiveRuntime.inference_ledger`` so the CLI/UI/tests can prove the
real path USER INPUT -> MODEL -> RESPONSE without trusting log prose.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class InferenceRequest:
    request_id: str
    user_input: str
    selected_model: Optional[str]
    selected_provider: Optional[str]
    context_sources: List[str]
    goal_id: Optional[str]
    cognitive_depth: Optional[str]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_input": self.user_input,
            "selected_model": self.selected_model,
            "selected_provider": self.selected_provider,
            "context_sources": list(self.context_sources),
            "goal_id": self.goal_id,
            "cognitive_depth": self.cognitive_depth,
            "timestamp": self.timestamp,
        }


@dataclass
class InferenceResult:
    request_id: str
    model: Optional[str]
    provider: Optional[str]
    generated_text: Optional[str]
    latency_ms: Optional[float]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    termination_reason: Optional[str]
    success: bool
    error: Optional[str]
    decision: Optional[str] = None
    decision_reason: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "model": self.model,
            "provider": self.provider,
            "generated_text": self.generated_text,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "termination_reason": self.termination_reason,
            "success": self.success,
            "error": self.error,
            "decision": self.decision,
            "decision_reason": self.decision_reason,
            "timestamp": self.timestamp,
        }


class InferenceLedger:
    """Bounded, append-only record of every real inference request/result."""

    def __init__(self, max_entries: int = 500):
        self.max_entries = max_entries
        self._requests: List[InferenceRequest] = []
        self._results: List[InferenceResult] = []

    def record_request(self, req: InferenceRequest) -> None:
        self._requests.append(req)
        if len(self._requests) > self.max_entries:
            self._requests = self._requests[-self.max_entries:]

    def complete_request(self, request_id: str, *, model: Optional[str],
                         provider: Optional[str]) -> None:
        """Fill in the selection once the router has actually decided.
        Recorded BEFORE execution (model/provider unknown then); this patches
        the request with the real selection from the result."""
        for req in self._requests:
            if req.request_id == request_id:
                req.selected_model = model
                req.selected_provider = provider
                break

    def record_result(self, res: InferenceResult) -> None:
        self._results.append(res)
        if len(self._results) > self.max_entries:
            self._results = self._results[-self.max_entries:]

    def requests(self) -> List[InferenceRequest]:
        return list(self._requests)

    def results(self) -> List[InferenceResult]:
        return list(self._results)

    def last_result(self) -> Optional[InferenceResult]:
        return self._results[-1] if self._results else None

    def last_request(self) -> Optional[InferenceRequest]:
        return self._requests[-1] if self._requests else None

    def count(self) -> int:
        return len(self._requests)

    def success_count(self) -> int:
        return sum(1 for r in self._results if r.success)

    def failure_count(self) -> int:
        return sum(1 for r in self._results if not r.success)

    def summary(self) -> Dict[str, Any]:
        return {
            "total": self.count(),
            "successes": self.success_count(),
            "failures": self.failure_count(),
            "last": self.last_result().to_dict()
            if self.last_result() is not None else None,
        }
