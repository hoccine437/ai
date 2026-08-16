"""
Slice 6 — CognitiveRouter.

Provider-independent dispatch: Task -> ModelSelection -> execution -> result.
- selection is DETERMINISTIC (identical inputs -> identical selection)
- FAST_FIELD / DEEP_FIELD come from the task's actual properties (depth score)
- OFFLINE_ONLY never touches cloud providers, and never fabricates output when
  no usable local model exists
- failover follows an explicit fallback chain within retry/budget policy —
  provider failure is recorded, never retried forever, and never equals system
  failure
- provider health and historical performance feed selection (cold start is
  UNKNOWN / INSUFFICIENT_DATA — performance is never invented)

The router depends only on provider_interface protocol types. Provider SDKs
live exclusively in adapters.
"""

import asyncio
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

from zerion.cognitive_os.gguf_discovery import (
    LocalModelDiscovery,
    ModelLoadManager,
    resolve_models_dir,
)
from zerion.cognitive_os.performance_ledger import PerformanceLedger
from zerion.cognitive_os.provider_health import ProviderHealthTracker
from zerion.cognitive_os.provider_interface import (
    RETRIABLE_FAILURES,
    ModelProvider,
    ProviderCall,
    ProviderFailureKind,
    RawProviderResponse,
)
from zerion.cognitive_os.router_types import (
    CognitiveDepthLevel,
    CognitiveDepthScore,
    CognitiveField,
    CognitiveResult,
    ModelSelection,
    ProviderStatus,
    ResultStatus,
    RoutingMode,
    Task,
    VerificationStatus,
    redact_secrets,
)

DEFAULT_ROUTING_POLICY_VERSION = 6
DEFAULT_PROVIDER_TIMEOUT_S = 30.0
# Local GGUF inference includes the model load, which on Android/Termux can
# take minutes for a 9B-class file — a fixed 30 s budget would kill llama-cli
# mid-load on every turn. Default 300 s; ZERION_GGUF_TIMEOUT_SECONDS overrides.
DEFAULT_LOCAL_PROVIDER_TIMEOUT_S = 300.0
DEFAULT_MAX_ATTEMPTS = 2


def _local_timeout_from_env() -> float:
    raw = os.environ.get("ZERION_GGUF_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_LOCAL_PROVIDER_TIMEOUT_S
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_LOCAL_PROVIDER_TIMEOUT_S


class ModelSelector:
    """Pure, deterministic scoring of candidate (provider, model) pairs."""

    def __init__(self, depth: Optional[CognitiveDepthScore] = None,
                 policy_version: int = DEFAULT_ROUTING_POLICY_VERSION,
                 budget_weights: Optional[Dict[str, float]] = None):
        self.depth = depth or CognitiveDepthScore()
        self.policy_version = policy_version
        self.budget_weights = budget_weights or {
            "capability": 0.35,
            "health": 0.20,
            "performance": 0.20,
            "offline": 0.10,
            "field": 0.05,
            "cost": 0.05,
            "latency": 0.05,
        }

    @staticmethod
    def _capability_match(required: Set[str], provided: Set[str]) -> float:
        if not required:
            return 1.0
        if not provided:
            return 0.0
        covered = required & provided
        if covered == required:
            return 1.0
        return len(covered) / len(required)  # partial coverage

    def score_candidate(self, *, provider: str, model: str,
                        capabilities: Set[str], is_local: bool,
                        task: Task, mode: RoutingMode,
                        health_status: ProviderStatus,
                        ledger: Optional[PerformanceLedger],
                        cost_estimate: Optional[float],
                        latency_estimate: Optional[float],
                        field: Optional[CognitiveField] = None,
                        field_profile: Optional[str] = None) -> float:
        w = self.budget_weights

        cap = self._capability_match(task.required_capabilities, capabilities)
        if cap <= 0.0:
            return -1.0  # ineligible

        health_map = {
            ProviderStatus.AVAILABLE: 1.0,
            ProviderStatus.UNKNOWN: 0.5,
            ProviderStatus.DEGRADED: 0.3,   # proven to be failing recently
            ProviderStatus.NOT_CONFIGURED: 0.0,
            ProviderStatus.UNAVAILABLE: 0.0,
        }
        health_score = health_map.get(health_status, 0.0)

        perf = 0.5
        if ledger is not None:
            perf = ledger.routing_weight(
                task_type=task.type.value, provider=provider, model=model,
                difficulty=task.difficulty,
                domain=str(task.metadata.get("domain", "general")))

        if mode == RoutingMode.OFFLINE_ONLY:
            offline_score = 1.0 if is_local else 0.0
        else:
            offline_score = 0.5  # neutral outside offline-only

        # Match computation depth to the task's actual properties: a provider
        # that declares the task's field profile is preferred (deterministic).
        if field is None:
            field = self.depth.field(task)
        field_score = 0.5
        if field_profile is not None:
            field_score = 1.0 if field_profile == field.value else 0.0

        cost_score = 0.5
        if task.cost_budget_cents and cost_estimate is not None:
            cost_score = max(0.0, 1.0 - (cost_estimate / task.cost_budget_cents))
        elif cost_estimate is not None:
            cost_score = max(0.0, 1.0 - cost_estimate / 100.0)

        latency_score = 0.5
        if task.latency_budget_ms and latency_estimate is not None:
            latency_score = max(0.0, 1.0 - (latency_estimate / task.latency_budget_ms))
        elif latency_estimate is not None:
            latency_score = max(0.0, 1.0 - latency_estimate / 2000.0)

        score = (w["capability"] * cap
                 + w["health"] * health_score
                 + w["performance"] * perf
                 + w["offline"] * offline_score
                 + w["field"] * field_score
                 + w["cost"] * cost_score
                 + w["latency"] * latency_score)
        if mode == RoutingMode.ONLINE_PREFERRED and not is_local:
            score += 0.05  # explicit preference, deterministic
        return round(score, 4)


class CognitiveRouter:
    """Routes tasks across registered ModelProviders. No provider SDKs here."""

    def __init__(self, *, health: Optional[ProviderHealthTracker] = None,
                 ledger: Optional[PerformanceLedger] = None,
                 local_models: Optional[LocalModelDiscovery] = None,
                 load_manager: Optional[ModelLoadManager] = None,
                 depth: Optional[CognitiveDepthScore] = None,
                 policy_version: int = DEFAULT_ROUTING_POLICY_VERSION,
                 provider_timeout_s: float = DEFAULT_PROVIDER_TIMEOUT_S,
                 local_provider_timeout_s: Optional[float] = None,
                 max_attempts: int = DEFAULT_MAX_ATTEMPTS,
                 emit: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None):
        self.health = health or ProviderHealthTracker()
        self.ledger = ledger
        self.local_models = local_models or \
            LocalModelDiscovery(models_dir=resolve_models_dir("models"))
        self.load_manager = load_manager or ModelLoadManager(self.local_models)
        self.selector = ModelSelector(depth=depth, policy_version=policy_version)
        self.policy_version = policy_version
        self.provider_timeout_s = provider_timeout_s
        self.local_provider_timeout_s = \
            local_provider_timeout_s if local_provider_timeout_s is not None \
            else _local_timeout_from_env()
        self.max_attempts = max(1, max_attempts)
        self.emit = emit
        self._providers: Dict[str, ModelProvider] = {}
        self._provider_order: List[str] = []
        self._models: Dict[str, Dict[str, Dict[str, Any]]] = {}

    # -- registration -------------------------------------------------------

    def register_provider(self, provider: ModelProvider, *,
                          configured: bool,
                          integration_implemented: bool = True) -> None:
        name = provider.provider_name
        if name in self._providers:
            raise ValueError(f"provider {name} already registered")
        self._providers[name] = provider
        self._provider_order.append(name)
        self.health.register(name, configured=configured,
                             integration_implemented=integration_implemented)
        self._models[name] = {
            m.model_id: {"capabilities": set(m.capabilities),
                         "size_bytes": m.size_bytes,
                         "context_window": m.context_window,
                         "status": m.status,
                         "path": m.path}
            for m in provider.list_models()
        }

    def providers(self) -> List[str]:
        return list(self._provider_order)

    # -- candidate enumeration ----------------------------------------------

    def _routable(self, provider_name: str, mode: RoutingMode) -> bool:
        """Normal routing eligibility, plus offline-only LAST RESORT for the
        local provider.

        In OFFLINE_ONLY the local provider is the only legal choice. A slow
        phone loading a 9B model legitimately times out and trips the health
        circuit breaker — but that is not a permanent failure: the provider
        must still be attempted (with its long, size-aware timeout) so real
        inference can succeed when the load finally completes. The attempt is
        a REAL call; if it fails again the failure is reported honestly.
        """
        if self.health.eligible(provider_name):
            return True
        provider = self._providers.get(provider_name)
        if provider is None or not getattr(provider, "is_local", False):
            return False
        if mode != RoutingMode.OFFLINE_ONLY:
            return False
        h = self.health.get(provider_name)
        if not (h.configured and h.integration_implemented):
            return False
        models = self._models.get(provider_name, {})
        return any(m["status"] in (ProviderStatus.AVAILABLE,
                                    ProviderStatus.UNKNOWN)
                   for m in models.values())

    def _candidates(self, task: Task, mode: RoutingMode,
                    required: Set[str],
                    field: Optional[CognitiveField] = None) -> List[Tuple[float, str, str, bool]]:
        """All eligible (provider, model) pairs, scored. Deterministic order.
        In OFFLINE_ONLY a degraded/unavailable LOCAL provider with a usable
        model is kept as a scored last resort (see ``_routable``)."""
        out: List[Tuple[float, str, str, bool]] = []
        for name in self._provider_order:
            if not self._routable(name, mode):
                continue
            provider = self._providers[name]
            is_local = bool(getattr(provider, "is_local", False))
            if mode == RoutingMode.OFFLINE_ONLY and not is_local:
                continue  # offline-only must never call cloud providers
            models = self._models.get(name, {})
            for model_id in sorted(models):
                m = models[model_id]
                if m["status"] not in (ProviderStatus.AVAILABLE, ProviderStatus.UNKNOWN):
                    continue
                caps = m["capabilities"]
                if required and not (caps & required):
                    continue
                cost = self._estimate_cost(name, model_id, task)
                latency = self._estimate_latency(name, model_id, task)
                field_profile = getattr(provider, "field_profile", None)
                score = self.selector.score_candidate(
                    provider=name, model=model_id, capabilities=caps,
                    is_local=is_local, task=task, mode=mode,
                    health_status=self.health.status(name),
                    ledger=self.ledger, cost_estimate=cost,
                    latency_estimate=latency, field=field,
                    field_profile=field_profile)
                if score >= 0.0:
                    out.append((score, name, model_id, is_local))
        # Stable, deterministic order: score desc, then provider, then model.
        out.sort(key=lambda t: (-t[0], t[1], t[2]))
        return out

    def _estimate_cost(self, provider: str, model_id: str,
                       task: Task) -> Optional[float]:
        if self.ledger is not None:
            s = self.ledger.stats(task_type=task.type.value, provider=provider,
                                  model=model_id)
            if s.avg_cost_cents is not None and not s.insufficient_data:
                return round(s.avg_cost_cents, 4)
        return None

    def _estimate_latency(self, provider: str, model_id: str,
                          task: Task) -> Optional[float]:
        if self.ledger is not None:
            s = self.ledger.stats(task_type=task.type.value, provider=provider,
                                  model=model_id)
            if s.avg_latency_ms is not None and not s.insufficient_data:
                return round(s.avg_latency_ms, 2)
        return None

    # -- routing ------------------------------------------------------------

    def route(self, task: Task, mode: RoutingMode = RoutingMode.AUTO,
              historical_failure_rate: float = 0.0) -> ModelSelection:
        """Pure selection — no execution. Deterministic for identical inputs."""
        depth_score = self.selector.depth.score(task, historical_failure_rate)
        depth_level = self.selector.depth.level(task, historical_failure_rate)
        field = self.selector.depth.field(task, historical_failure_rate)

        candidates = self._candidates(task, mode, task.required_capabilities,
                                      field=field)
        if not candidates:
            return ModelSelection(
                provider="", model="",
                reason=["no eligible provider: " + self._no_candidate_reason(task, mode)],
                routing_policy_version=self.policy_version,
                depth_score=depth_score, depth_level=depth_level, field=field,
                mode=mode, confidence=0.0)

        top_score, provider, model, _is_local = candidates[0]
        chain = [{"provider": p, "model": m} for _, p, m, _ in candidates[1:]]
        reasons = self._build_reasons(task, mode, provider, model, top_score,
                                      depth_score, depth_level, field, chain)

        return ModelSelection(
            provider=provider, model=model, reason=reasons,
            estimated_cost_cents=self._estimate_cost(provider, model, task),
            estimated_latency_ms=self._estimate_latency(provider, model, task),
            capabilities=self._models.get(provider, {}).get(model, {}).get("capabilities", set()),
            confidence=top_score,
            fallback_chain=chain,
            routing_policy_version=self.policy_version,
            depth_score=depth_score, depth_level=depth_level, field=field,
            mode=mode,
        )

    def _no_candidate_reason(self, task: Task, mode: RoutingMode) -> str:
        reasons: List[str] = []
        for name in self._provider_order:
            h = self.health.get(name)
            if not self.health.eligible(name):
                # Honest cause: health carries the last REAL failure (e.g. a
                # MODEL_LOAD_FAILURE naming the missing GGUF backend) instead
                # of a generic "no provider" message.
                err = (h.last_error or h.status.value)[:160]
                reasons.append(f"{name}: {err} (health={h.status.value})")
                continue
            provider = self._providers[name]
            is_local = bool(getattr(provider, "is_local", False))
            if mode == RoutingMode.OFFLINE_ONLY and not is_local:
                continue
            models = self._models.get(name, {})
            if task.required_capabilities and not any(
                    m["capabilities"] & task.required_capabilities
                    for m in models.values()):
                reasons.append(f"{name}: no model with required capabilities")
                continue
            reasons.append(f"{name}: no usable model")
        if mode == RoutingMode.OFFLINE_ONLY:
            reasons.append("offline-only mode: cloud providers excluded")
        return "; ".join(reasons) if reasons else "no provider registered"

    def _build_reasons(self, task: Task, mode: RoutingMode, provider: str,
                       model: str, score: float, depth_score: float,
                       depth_level: CognitiveDepthLevel, field: CognitiveField,
                       chain: List[Dict[str, str]]) -> List[str]:
        reasons = [
            f"field={field.value} (depth {depth_score:.3f} -> {depth_level.value})",
            f"provider={provider} model={model} covers required capabilities",
        ]
        h = self.health.get(provider)
        err = "n/a" if h.error_rate() is None else round(h.error_rate(), 3)
        reasons.append(f"health={h.status.value} (err_rate={err})")
        if self.ledger is not None:
            s = self.ledger.stats(task_type=task.type.value, provider=provider,
                                  model=model)
            if s.insufficient_data:
                reasons.append(f"performance=INSUFFICIENT_DATA (samples={s.samples})")
            else:
                reasons.append(f"performance=success_rate {s.success_rate:.3f} "
                               f"(samples={s.samples})")
        if mode == RoutingMode.OFFLINE_ONLY:
            reasons.append("offline-only: local provider only")
        reasons.append(f"score={score:.4f} (capability {self._budget_weights_str()})")
        if chain:
            reasons.append("fallback chain: " + " -> ".join(
                f"{c['provider']}/{c['model']}" for c in chain))
        return reasons

    def _budget_weights_str(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in
                         sorted(self.selector.budget_weights.items()))

    # -- execution ----------------------------------------------------------

    async def execute(self, task: Task, prompt: str,
                      mode: RoutingMode = RoutingMode.AUTO,
                      selection: Optional[ModelSelection] = None,
                      historical_failure_rate: float = 0.0) -> CognitiveResult:
        """Run the task through the selected provider with failover within
        retry/budget policy. Never returns fabricated output."""
        await self._emit("ROUTING_STARTED", {"task_id": task.task_id,
                                             "type": task.type.value,
                                             "mode": mode.value})
        sel = selection or self.route(task, mode=mode,
                                      historical_failure_rate=historical_failure_rate)
        await self._emit("MODEL_SELECTED", sel.to_dict(redact=True))

        if not sel.provider:
            result = CognitiveResult(
                task_id=task.task_id, status=ResultStatus.ROUTING_FAILED,
                errors=sel.reason, mode=mode,
                verification_required=task.verification_required)
            await self._emit("ROUTING_FAILED", result.to_dict(redact=True))
            return result

        chain: List[Dict[str, str]] = [{"provider": sel.provider, "model": sel.model}]
        chain.extend(sel.fallback_chain)
        attempts = 0
        last_status: ResultStatus = ResultStatus.ROUTING_FAILED
        last_errors: List[str] = []
        last_provider = ""

        for idx, step in enumerate(chain):
            if attempts >= self.max_attempts:
                break
            provider_name = step["provider"]
            model_id = step["model"]
            provider = self._providers.get(provider_name)
            if provider is None or not self._routable(provider_name, mode):
                last_errors.append(f"{provider_name}: provider unavailable")
                continue
            is_local = bool(getattr(provider, "is_local", False))
            if mode == RoutingMode.OFFLINE_ONLY and not is_local:
                last_errors.append(f"{provider_name}: cloud provider forbidden in OFFLINE_ONLY")
                continue

            attempts += 1
            last_provider = provider_name
            await self._emit("PROVIDER_CALLED", {"task_id": task.task_id,
                                                 "provider": provider_name,
                                                 "model": model_id,
                                                 "attempt": attempts})
            timeout = self._timeout_for(task, provider_name)
            call = ProviderCall(task=task, prompt=prompt, model_id=model_id,
                                timeout_s=timeout)
            try:
                resp = await asyncio.wait_for(provider.generate(call), timeout=timeout)
            except asyncio.TimeoutError:
                self.health.record_failure(provider_name, error="timeout", timeout=True)
                last_status = ResultStatus.TIMEOUT
                last_errors.append(f"{provider_name}/{model_id}: timeout")
                await self._emit("PROVIDER_FAILED", {"provider": provider_name,
                                                     "model": model_id,
                                                     "error": "timeout"})
                if attempts < self.max_attempts and idx + 1 < len(chain):
                    await self._emit("FAILOVER_STARTED", {"task_id": task.task_id,
                                                          "from": provider_name,
                                                          "reason": "timeout"})
                continue  # timeout is retriable within budget
            except Exception as e:  # noqa: BLE001
                self.health.record_failure(provider_name, error=str(e)[:200])
                last_status = ResultStatus.PROVIDER_UNAVAILABLE
                last_errors.append(f"{provider_name}/{model_id}: {str(e)[:200]}")
                await self._emit("PROVIDER_FAILED", {"provider": provider_name,
                                                     "model": model_id,
                                                     "error": str(e)[:200]})
                if attempts < self.max_attempts and idx + 1 < len(chain):
                    await self._emit("FAILOVER_STARTED", {"task_id": task.task_id,
                                                          "from": provider_name,
                                                          "reason": "exception"})
                continue

            if resp.success:
                self.health.record_success(provider_name, resp.latency_ms)
                if self.ledger is not None:
                    self.ledger.record_outcome(
                        task=task, provider=provider_name, model=model_id,
                        success=True, latency_ms=resp.latency_ms, cost_cents=None)
                usage = dict(resp.usage or {})
                # Model identity (spec §39): provider, model filename, backend
                # and inference timestamp ride on every successful result so
                # cognition is traceable to the actual local execution.
                identity = {
                    "provider": provider_name,
                    "model": model_id,
                    "backend": usage.get("backend", "UNKNOWN"),
                    "timestamp": usage.get("timestamp"),
                    "task_id": task.task_id,
                }
                result = CognitiveResult(
                    task_id=task.task_id, provider=provider_name, model=model_id,
                    output=resp.output, latency_ms=resp.latency_ms,
                    usage=usage, status=ResultStatus.SUCCESS,
                    verification_required=task.verification_required,
                    verification_status=VerificationStatus.MODEL_OUTPUT,
                    confidence=resp.confidence, mode=mode,
                    metadata={"routing_policy_version": self.policy_version,
                              "depth_level": sel.depth_level.value if sel.depth_level else None,
                              "model_identity": identity})
                await self._emit("PROVIDER_SUCCEEDED", {"provider": provider_name,
                                                        "model": model_id,
                                                        "latency_ms": resp.latency_ms})
                await self._emit("ROUTING_COMPLETED", {"task_id": task.task_id,
                                                       "status": "SUCCESS"})
                return result

            # Structured provider failure.
            kind = resp.failure_kind or ProviderFailureKind.PROVIDER_UNAVAILABLE
            kind_str = kind.value
            self.health.record_failure(provider_name, error=resp.error or kind_str,
                                       timeout=kind == ProviderFailureKind.TIMEOUT,
                                       failure_kind=kind_str)
            last_status = resp.result_status
            last_errors.append(f"{provider_name}/{model_id}: {resp.error or kind_str}")
            await self._emit("PROVIDER_FAILED", {"provider": provider_name,
                                                 "model": model_id,
                                                 "error": resp.error or kind_str,
                                                 "kind": kind_str})
            if kind in RETRIABLE_FAILURES and attempts < self.max_attempts \
                    and idx + 1 < len(chain):
                await self._emit("FAILOVER_STARTED", {"task_id": task.task_id,
                                                      "from": provider_name,
                                                      "reason": kind_str})
                continue
            # Non-retriable (or budget exhausted, or no fallback remains):
            # structured failure, no retry.
            break

        result = CognitiveResult(
            task_id=task.task_id, provider=last_provider, model="",
            output=None, status=last_status, errors=last_errors, mode=mode,
            verification_required=task.verification_required)
        await self._emit("ROUTING_FAILED", result.to_dict(redact=True))
        return result

    def _timeout_for(self, task: Task, provider_name: str) -> float:
        provider = self._providers.get(provider_name)
        is_local = bool(getattr(provider, "is_local", False))
        base = (self.local_provider_timeout_s if is_local
                else self.provider_timeout_s)
        if not task.latency_budget_ms:
            return base
        budget = task.latency_budget_ms / 1000.0
        if is_local:
            # Local inference includes the model load; a generic latency
            # budget must never starve a real local call into a spurious
            # timeout on a slow device.
            return max(60.0, min(budget, base))
        return max(0.1, min(budget, base))

    async def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self.emit is None:
            return
        try:
            await self.emit(event_type, redact_secrets(payload))
        except Exception:  # noqa: BLE001 — event emission must not break routing
            pass
