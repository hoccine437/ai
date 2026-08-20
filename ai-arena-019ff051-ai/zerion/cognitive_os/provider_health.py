"""
Slice 6 — Provider health tracking.

A provider is never marked READY merely because its configuration exists:
status is derived from real call outcomes. Tracks availability, latency,
error rate, timeout rate, recent failures, resource usage and last successful
request, and feeds the router's selection scoring.
"""

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional

from zerion.cognitive_os.router_types import ProviderStatus

# After this many consecutive failures (or overall error-rate threshold) a
# configured provider is considered DEGRADED / UNAVAILABLE for routing.
DEGRADE_AFTER_FAILURES = 2
UNAVAILABLE_AFTER_FAILURES = 4
ERROR_RATE_DEGRADE = 0.4
ERROR_RATE_UNAVAILABLE = 0.8
WINDOW_S = 3600.0  # 1h sliding window for rates


@dataclass
class ProviderHealth:
    provider: str
    configured: bool = False                 # has valid config (key/models)
    integration_implemented: bool = True     # adapter can actually call it
    status: ProviderStatus = ProviderStatus.UNKNOWN
    total_calls: int = 0
    successes: int = 0
    failures: int = 0
    timeouts: int = 0
    consecutive_failures: int = 0
    recent_failures: List[Dict[str, Any]] = field(default_factory=list)
    latency_ema_ms: Optional[float] = None
    last_successful_request: Optional[float] = None
    last_error: str = ""
    resource_usage: Dict[str, Any] = field(default_factory=dict)
    unavailable_since: Optional[float] = None  # auto-recover after cooldown

    def error_rate(self) -> Optional[float]:
        if self.total_calls == 0:
            return None
        return self.failures / self.total_calls

    def timeout_rate(self) -> Optional[float]:
        if self.total_calls == 0:
            return None
        return self.timeouts / self.total_calls

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "configured": self.configured,
            "integration_implemented": self.integration_implemented,
            "status": self.status.value,
            "total_calls": self.total_calls,
            "successes": self.successes,
            "failures": self.failures,
            "timeouts": self.timeouts,
            "consecutive_failures": self.consecutive_failures,
            "error_rate": self.error_rate(),
            "timeout_rate": self.timeout_rate(),
            "latency_ema_ms": self.latency_ema_ms,
            "last_successful_request": self.last_successful_request,
            "last_error": self.last_error[:200],
            "resource_usage": dict(self.resource_usage),
        }


class ProviderHealthTracker:
    """In-memory health tracking, consulted by the router on every selection."""

    def __init__(self):
        self._health: Dict[str, ProviderHealth] = {}

    def register(self, provider: str, *, configured: bool,
                 integration_implemented: bool = True) -> ProviderHealth:
        h = self._health.setdefault(provider, ProviderHealth(provider=provider))
        h.configured = bool(configured)
        h.integration_implemented = bool(integration_implemented)
        h.status = self._derive_status(h)
        return h

    def get(self, provider: str) -> ProviderHealth:
        return self._health.setdefault(provider, ProviderHealth(provider=provider))

    def _derive_status(self, h: ProviderHealth) -> ProviderStatus:
        if not h.configured:
            return ProviderStatus.NOT_CONFIGURED
        if not h.integration_implemented:
            return ProviderStatus.UNAVAILABLE
        if h.total_calls == 0:
            # Configured + implemented but NEVER proven by a real call. It may
            # be routable, but its health is UNKNOWN — never "READY" from
            # configuration alone.
            return ProviderStatus.UNKNOWN
        err = h.error_rate() or 0.0
        if h.consecutive_failures >= UNAVAILABLE_AFTER_FAILURES or err >= ERROR_RATE_UNAVAILABLE:
            # Auto-recovery: after 60s cooldown, reset completely and try again
            if h.unavailable_since and (time.time() - h.unavailable_since) > 60:
                h.consecutive_failures = 0
                h.failures = 0
                h.total_calls = 0
                h.unavailable_since = None
                return ProviderStatus.UNKNOWN
            if h.unavailable_since is None:
                h.unavailable_since = time.time()
            return ProviderStatus.UNAVAILABLE
        if h.consecutive_failures >= DEGRADE_AFTER_FAILURES or err >= ERROR_RATE_DEGRADE:
            return ProviderStatus.DEGRADED
        return ProviderStatus.AVAILABLE

    def record_success(self, provider: str, latency_ms: Optional[float],
                       usage: Optional[Dict[str, Any]] = None) -> ProviderHealth:
        h = self.get(provider)
        h.total_calls += 1
        h.successes += 1
        h.consecutive_failures = 0
        h.last_successful_request = time.time()
        if latency_ms is not None:
            if h.latency_ema_ms is None:
                h.latency_ema_ms = latency_ms
            else:
                h.latency_ema_ms = 0.8 * h.latency_ema_ms + 0.2 * latency_ms
        if usage:
            h.resource_usage.update(usage)
        h.status = self._derive_status(h)
        return h

    def record_failure(self, provider: str, *, error: str = "",
                       timeout: bool = False,
                       failure_kind: str = "") -> ProviderHealth:
        h = self.get(provider)
        h.total_calls += 1
        h.failures += 1
        if timeout:
            h.timeouts += 1
        h.consecutive_failures += 1
        h.last_error = error or failure_kind
        h.recent_failures.append({
            "ts": time.time(),
            "error": (error or failure_kind)[:200],
            "timeout": bool(timeout),
        })
        # Keep the window bounded.
        cutoff = time.time() - WINDOW_S
        h.recent_failures = [f for f in h.recent_failures if f["ts"] >= cutoff]
        h.recent_failures = h.recent_failures[-20:]
        h.status = self._derive_status(h)
        return h

    def reset(self, provider: str) -> ProviderHealth:
        """Circuit-breaker reset: an operator acknowledges the environment was
        fixed (e.g. a GGUF backend was installed) and clears failure history
        so the provider can be routed again. Never fabricates success — the
        provider returns to UNKNOWN (configured, unproven) until a real call
        succeeds."""
        h = self.get(provider)
        h.total_calls = 0
        h.successes = 0
        h.failures = 0
        h.timeouts = 0
        h.consecutive_failures = 0
        h.recent_failures = []
        h.last_error = ""
        h.status = self._derive_status(h)
        return h

    def status(self, provider: str) -> ProviderStatus:
        return self.get(provider).status

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {name: h.to_dict()
                for name, h in sorted(self._health.items())}

    def eligible(self, provider: str) -> bool:
        """Routing eligibility: configured, implemented and not unavailable.
        UNKNOWN (configured but unproven) is routable with a neutral score;
        health is only ever proven by real call outcomes."""
        h = self.get(provider)
        return h.configured and h.integration_implemented and \
            h.status in (ProviderStatus.AVAILABLE, ProviderStatus.DEGRADED,
                         ProviderStatus.UNKNOWN)
