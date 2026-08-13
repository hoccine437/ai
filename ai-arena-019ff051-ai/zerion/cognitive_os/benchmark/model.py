"""
Slice 9 — the deterministic benchmark model.

The SAME model drives BASELINE and ZERION trials. It is intentionally a
*flawed* model (hallucination, limited persistence, weak exploration, no
built-in verification) so that the benchmark can measure whether the Cognitive
Runtime's guidance (verification, failure learning, questions, experiments,
capabilities) actually changes outcomes. Its weaknesses are fixed,
configurable profile parameters — never tuned per outcome.

The model also implements the Slice 6 ``ModelProvider`` protocol so the same
deterministic substrate can be routed through the real router for the
provider-comparison section (rule 31).
"""

from dataclasses import dataclass, field
import itertools
import random
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

from zerion.cognitive_os.benchmark.types import AgentAction
from zerion.cognitive_os.benchmark.world import BenchmarkTask, BenchmarkWorld, ToolCall
from zerion.cognitive_os.provider_interface import (
    TEXT,
    ModelInfo,
    ProviderCall,
    RawProviderResponse,
)
from zerion.cognitive_os.router_types import ProviderStatus


@dataclass
class ModelProfile:
    """Fixed weaknesses of the benchmark model. Same profile for BASELINE and
    ZERION — only the runtime guidance differs."""

    hallucination_bias: float = 0.5        # P(invent a fact value, skip the tool)
    persistence_limit: int = 2             # max retries of one failed tool call
    guidance_retry_bonus: int = 2          # extra retries granted by failure guidance
    trust_first_source: bool = True        # contradiction: answer from first source
    exploration_limit: int = 2             # novel: max extra order-guesses after the memorized one
    guidance_acceptance: float = 0.9       # P(follow soft guidance: questions/memory)
    max_steps: int = 40

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hallucination_bias": self.hallucination_bias,
            "persistence_limit": self.persistence_limit,
            "guidance_retry_bonus": self.guidance_retry_bonus,
            "trust_first_source": self.trust_first_source,
            "exploration_limit": self.exploration_limit,
            "guidance_acceptance": self.guidance_acceptance,
            "max_steps": self.max_steps,
        }


@dataclass
class ModelContext:
    task: BenchmarkTask
    world: BenchmarkWorld
    step: int
    call_log: List[ToolCall]
    guidance: Dict[str, Any] = field(default_factory=dict)


class BenchmarkModel:
    """Deterministic, seeded, stateful planner over a task's memorized
    procedure, with fixed weaknesses and deterministic guidance consumption."""

    def __init__(self, profile: Optional[ModelProfile] = None, seed: int = 0,
                 provider_name: str = "deterministic_local",
                 model_id: str = "benchmark-model-d1"):
        self.profile = profile or ModelProfile()
        self.provider_name = provider_name
        self.model_id = model_id
        self.is_local = True
        self.field_profile = "FAST_FIELD"
        self.seed = seed
        self.rng = random.Random(seed)
        self._reset_state()

    def _reset_state(self) -> None:
        self.believed: Dict[str, Any] = {}
        self.order: List[str] = []
        self.order_value: Any = None
        self.orders_checked: List[List[str]] = []
        self.answered = False
        self.answer: Dict[str, Any] = {}
        self.retry_counts: Dict[Tuple[str, str], int] = {}
        self.strategy_switches = 0
        self.strategy_retries = 0   # repeated applications of a failed strategy
        self.requested_info: Optional[str] = None
        self.hallucinated_keys: List[str] = []
        self._capability: Optional[Dict[str, Any]] = None
        self._open_question: Optional[str] = None
        # Failure-learning state: a transient-failure guidance grant extends the
        # persistence limit (persistence_limit + guidance_retry_bonus).
        self._retry_bonus_active = False
        # Verification protocol: the model requests a reality check via the
        # check_answer tool; the agent executes it and sets verification_result.
        self.pending_check: Any = None
        self.verification_result: Optional[bool] = None
        # Adaptation / cross-domain scaling factor discovery.
        self._multiplier: Optional[float] = None
        self._multiplier_tried: List[float] = []
        self.phase: str = "A"
        # Long-horizon step tracking: the current pipeline step and a runtime
        # "redo this skipped step" signal.
        self._lh_step: int = 0
        self._lh_redo: Optional[str] = None
        # Novel: position in the current order pass (reset on order change).
        self._order_step: int = 0
        self.last_guidance: Dict[str, Any] = {}

    def reset(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            self.seed = seed
        self.rng = random.Random(self.seed)
        self._reset_state()

    # ------------------------------------------------------------------
    # Slice 6 ModelProvider protocol (router comparison path)
    # ------------------------------------------------------------------

    async def generate(self, call: ProviderCall) -> RawProviderResponse:
        return RawProviderResponse(
            output="[benchmark-model] deterministic response",
            latency_ms=0.1, usage=None, success=True)

    async def stream(self, call: ProviderCall) -> AsyncIterator[RawProviderResponse]:
        yield await self.generate(call)

    async def health_check(self) -> ProviderStatus:
        return ProviderStatus.AVAILABLE

    def capabilities(self) -> Set[str]:
        return {TEXT}

    def list_models(self) -> List[ModelInfo]:
        return [ModelInfo(model_id=self.model_id, provider=self.provider_name,
                          capabilities=self.capabilities(),
                          status=ProviderStatus.AVAILABLE,
                          status_reason="deterministic benchmark model",
                          format="deterministic")]

    def model_info(self, model_id: str) -> Optional[ModelInfo]:
        if model_id == self.model_id:
            return self.list_models()[0]
        return None

    # ------------------------------------------------------------------
    # Deterministic policy
    # ------------------------------------------------------------------

    def act(self, ctx: ModelContext) -> AgentAction:
        family = (ctx.task.metadata or {}).get("family", "")
        g = ctx.guidance or {}
        self._absorb_guidance(ctx, g)
        if self.answered:
            return AgentAction(kind="answer", claim=self.answer)
        if family in ("fetch_compute", "flaky_fetch", "capability_reuse",
                      "goal_persistence"):
            return self._act_fetch(ctx, g)
        if family == "contradiction":
            return self._act_contradiction(ctx, g)
        if family == "novel_algorithm":
            return self._act_novel(ctx, g)
        if family == "question_task":
            return self._act_question(ctx, g)
        if family == "long_horizon":
            return self._act_long_horizon(ctx, g)
        if family == "adaptation":
            return self._act_adaptation(ctx, g)
        if family == "cross_domain":
            return self._act_cross_domain(ctx, g)
        return AgentAction(kind="answer", claim={"value": None})

    # -- guidance absorption -------------------------------------------------

    def _absorb_guidance(self, ctx: ModelContext, g: Dict[str, Any]) -> None:
        # HARD signals (backed by observed reality) are always followed.
        vf = g.get("verification_failure")
        if isinstance(vf, dict) and vf.get("observed") is not None:
            obs = vf.get("observed", {})
            if isinstance(obs, dict):
                for k, v in obs.items():
                    self.believed[str(k)] = v
            self.strategy_switches += 1
        # Long-horizon: a skipped dependency must be re-executed (reality gap)
        # and everything downstream of it is invalidated (dependent results).
        sg = vf.get("step_gap") if isinstance(vf, dict) else None
        if isinstance(sg, str) and sg:
            steps = list((ctx.task.metadata or {}).get("steps", []))
            self._lh_redo = sg
            if sg in steps:
                gap_idx = steps.index(sg)
                self._lh_step = gap_idx
                for fn in steps[gap_idx:]:
                    self.believed.pop(f"apply:{fn}", None)

        # Failure-learning guidance: the tool is transiently flaky — keep
        # retrying past the default persistence limit.
        flaky = g.get("flaky_tool")
        if isinstance(flaky, dict) and flaky.get("transient"):
            self._retry_bonus_active = True

        order_res = g.get("order_result")
        if isinstance(order_res, dict) and order_res.get("order") is not None \
                and order_res.get("value") is not None:
            o = list(order_res["order"])
            if o not in self.orders_checked:
                self.orders_checked.append(o)
            self.order = o
            self.order_value = order_res["value"]

        exp = g.get("experiment_result")
        if isinstance(exp, dict) and exp.get("verdict") == "SUPPORTS":
            if exp.get("order") is not None:
                self.order = list(exp["order"])
                self.strategy_switches += 1
            if exp.get("multiplier") is not None:
                self._multiplier = float(exp["multiplier"])
                self.strategy_switches += 1

        cap = g.get("capability")
        if isinstance(cap, dict) and cap.get("validated"):
            self._capability = cap

        mi = g.get("missing_info")
        if isinstance(mi, str) and mi and not self.requested_info:
            self.requested_info = mi
            self.strategy_switches += 1

        q = g.get("question")
        if isinstance(q, dict) and q.get("text") \
                and self.rng.random() < self.profile.guidance_acceptance:
            self._open_question = q["text"]

    # -- fetch / reuse --------------------------------------------------------

    def _give_up_on(self, tool: str, key: str) -> bool:
        """The model abandons a tool after ``persistence_limit`` failed calls
        (or ``persistence_limit + guidance_retry_bonus`` when failure-learning
        guidance proved the failure is transient). Retries are counted from
        ACTUAL tool failures only — never internal reasoning steps."""
        limit = self.profile.persistence_limit
        if self._retry_bonus_active:
            limit += self.profile.guidance_retry_bonus
        return self.retry_counts.get((tool, key), 0) >= limit

    def _act_fetch(self, ctx: ModelContext, g: Dict[str, Any]) -> AgentAction:
        keys = list((ctx.task.metadata or {}).get("facts", []))
        factor = (ctx.task.metadata or {}).get("factor", 1)

        # Guidance: a validated capability short-circuits the compute path.
        if self._capability:
            if "capability_result" in self.believed:
                return self._answer(self.believed["capability_result"])
            facts = {k: self.believed.get(k) for k in keys}
            if all(facts.get(k) is not None for k in keys):
                return AgentAction(kind="tool", tool="__capability__",
                                   args={"name": self._capability["name"],
                                         "facts": facts, "factor": factor})

        missing = [k for k in keys if k not in self.believed]
        if missing:
            key = missing[0]
            if self._give_up_on("read_fact", key):
                # Abandon the failed tool: commit a guess instead of asking
                # again (the agent marks this "gave_up" and does not propagate
                # the tool's true value into the model's belief).
                val = self.rng.choice([3, 6, 9, 11, 14])
                self.believed[key] = val
                return AgentAction(kind="tool", tool="read_fact", args={"key": key},
                                   source="gave_up")
            if self.rng.random() < self.profile.hallucination_bias:
                val = self.rng.choice([3, 6, 9, 11, 14])
                self.believed[key] = val
                self.hallucinated_keys.append(key)
                # The model still "calls" the tool to stay in its plan, but the
                # agent will not propagate the true value into its belief.
                return AgentAction(kind="tool", tool="read_fact", args={"key": key},
                                   source="hallucinated")
            return AgentAction(kind="tool", tool="read_fact", args={"key": key})

        # All facts believed: compute the answer.
        vals = [self.believed[k] for k in keys]
        if not all(isinstance(v, (int, float)) for v in vals):
            return self._answer(None)
        total = sum(vals) * factor
        return self._answer(total)

    def _act_contradiction(self, ctx: ModelContext, g: Dict[str, Any]) -> AgentAction:
        vf = g.get("verification_failure")
        # Memorized: read docs first (the answer must be evidence-backed — a
        # read_source call is required in the log).
        if not any(tc.tool == "read_source" and tc.args.get("source") == "docs"
                   and tc.ok for tc in ctx.call_log):
            return AgentAction(kind="tool", tool="read_source", args={"source": "docs"})
        # Reality feedback overrides the first-source bias (trust_first_source).
        if isinstance(vf, dict) and vf.get("observed") is not None:
            return self._answer(vf["observed"])
        docs_val = next((tc.result for tc in reversed(ctx.call_log)
                         if tc.tool == "read_source"
                         and tc.args.get("source") == "docs" and tc.ok), None)
        val = str(docs_val).split("=")[-1].strip().split()[0] if "=" in str(docs_val) \
            else str(docs_val)
        return self._answer(val)

    def _act_novel(self, ctx: ModelContext, g: Dict[str, Any]) -> AgentAction:
        functions = list((ctx.task.metadata or {}).get("functions", []))
        exp = g.get("experiment_result")

        # If the runtime proved an order, adopt it. The proven order outranks
        # the model's own exploration: pending state is reset whenever the
        # guidance arrives (it may have been absorbed already by the shared
        # guidance handler, so the order may already equal exp['order'] while
        # a stale failed check still awaits a decision).
        if isinstance(exp, dict) and exp.get("order") is not None \
                and exp.get("verdict") == "SUPPORTS":
            if self.order != list(exp["order"]) or self.pending_check is not None:
                self.order = list(exp["order"])
                self.orders_checked = [list(self.order)]
                self.pending_check = None
                self.verification_result = None
                self._order_step = 0
                self.strategy_switches += 1

        # First call: memorize the (wrong) order [h, f, g].
        if not self.order:
            self.order = ["h", "f", "g"]
            self.orders_checked = [list(self.order)]

        # A computed order awaits reality feedback: ask the world (the check
        # is a real tool call in the log — never assumed).
        if self.pending_check is not None:
            if self.verification_result is None:
                return AgentAction(kind="tool", tool="check_answer",
                                   args={"value": self.pending_check})
            if self.verification_result:
                return self._answer(self.pending_check)
            # Wrong: explore a new permutation (bounded by exploration_limit).
            tried = [list(o) for o in self.orders_checked]
            if len(tried) - 1 < self.profile.exploration_limit:
                candidates = [list(perm) for perm in itertools.permutations(functions)
                              if list(perm) not in tried]
                if candidates:
                    self.order = self.rng.choice(candidates)
                    self.orders_checked.append(list(self.order))
                    self.pending_check = None
                    self.verification_result = None
                    self._order_step = 0
                    self.strategy_switches += 1
                else:
                    return self._answer(self.pending_check)  # best guess
            else:
                return self._answer(self.pending_check)  # best guess

        # Execute the current order one step at a time (agent fills the value
        # and completes the order -> pending_check).
        idx = self._order_step % len(self.order) if self.order else 0
        self._order_step += 1
        return AgentAction(kind="tool", tool="apply",
                           args={"fn": self.order[idx], "value": None})

    def _act_question(self, ctx: ModelContext, g: Dict[str, Any]) -> AgentAction:
        param = (ctx.task.metadata or {}).get("missing_param", "extra")
        base = self.believed.get("base")
        if base is None:
            base = next((tc.result for tc in reversed(ctx.call_log)
                         if tc.tool == "read_fact" and tc.args.get("key") == "base"
                         and tc.ok), None)
            if base is None:
                return AgentAction(kind="tool", tool="read_fact", args={"key": "base"})
            self.believed["base"] = base

        if param in self.believed:
            return self._answer(self.believed["base"] + self.believed[param])

        if self.requested_info:
            return AgentAction(kind="tool", tool="request_info",
                               args={"param": self.requested_info})

        if g.get("missing_info") or self._open_question:
            self.requested_info = param
            return AgentAction(kind="tool", tool="request_info", args={"param": param})

        # Baseline: invent the missing value.
        self.believed[param] = self.rng.choice([3, 6, 9, 11, 14])
        return self._answer(self.believed["base"] + self.believed[param])

    def _act_long_horizon(self, ctx: ModelContext, g: Dict[str, Any]) -> AgentAction:
        """Multiple dependent steps. The model carries the running value through
        each step; a skipped dependency (hallucinated step result) fails the
        task, and the runtime's step-gap guidance makes the model redo it."""
        steps = list((ctx.task.metadata or {}).get("steps", []))
        if "seed" not in self.believed:
            if self.rng.random() < self.profile.hallucination_bias:
                self.believed["seed"] = self.rng.choice([3, 6, 9, 11, 14])
                self.hallucinated_keys.append("seed")
                return AgentAction(kind="tool", tool="read_fact",
                                   args={"key": "seed"}, source="hallucinated")
            return AgentAction(kind="tool", tool="read_fact", args={"key": "seed"})

        if self._lh_redo:
            fn = self._lh_redo
            self._lh_redo = None
            return AgentAction(kind="tool", tool="apply",
                               args={"fn": fn, "value": self._pipeline_value(steps)})

        while self._lh_step < len(steps):
            fn = steps[self._lh_step]
            self._lh_step += 1
            if f"apply:{fn}" in self.believed:
                continue  # already executed (a hallucinated one is redone)
            if self.rng.random() < self.profile.hallucination_bias:
                self.believed[f"apply:{fn}"] = self.rng.choice([3, 6, 9, 11, 14])
                self.hallucinated_keys.append(f"apply:{fn}")
                continue  # critical dependency skipped
            return AgentAction(kind="tool", tool="apply",
                               args={"fn": fn, "value": self._pipeline_value(steps)})
        return self._answer(self._pipeline_value(steps))

    def _pipeline_value(self, steps: List[str]) -> Any:
        """The running value after every executed step so far (last executed
        step's result, or the seed before anything ran)."""
        value = self.believed.get("seed")
        for fn in steps:
            if f"apply:{fn}" in self.believed:
                value = self.believed[f"apply:{fn}"]
        return value

    def _act_adaptation(self, ctx: ModelContext, g: Dict[str, Any]) -> AgentAction:
        """Environment A validates sum; environment B validates sum * factor.
        The memorized multiplier (1.0) is only valid in A — after the change,
        reality feedback (or a runtime experiment) must supply the new factor."""
        keys = list((ctx.task.metadata or {}).get("facts", []))
        missing = [k for k in keys if k not in self.believed]
        if missing:
            key = missing[0]
            if self._give_up_on("read_fact", key):
                self.believed[key] = self.rng.choice([3, 6, 9, 11, 14])
                return AgentAction(kind="tool", tool="read_fact", args={"key": key},
                                   source="gave_up")
            if self.rng.random() < self.profile.hallucination_bias:
                self.believed[key] = self.rng.choice([3, 6, 9, 11, 14])
                self.hallucinated_keys.append(key)
                return AgentAction(kind="tool", tool="read_fact", args={"key": key},
                                   source="hallucinated")
            return AgentAction(kind="tool", tool="read_fact", args={"key": key})

        base = sum(self.believed[k] for k in keys)
        if self._multiplier is None:
            self._multiplier = 1.0
        value = base * self._multiplier

        if self.pending_check is None:
            self.pending_check = value
            return AgentAction(kind="tool", tool="check_answer", args={"value": value})
        if self.verification_result is None:
            return AgentAction(kind="tool", tool="check_answer",
                               args={"value": self.pending_check})
        if self.verification_result:
            return self._answer(self.pending_check)

        # Reality disagrees: adopt the runtime's proven multiplier; otherwise
        # the model repeats the now-invalid original strategy (counted).
        exp = g.get("experiment_result")
        if isinstance(exp, dict) and exp.get("verdict") == "SUPPORTS" \
                and exp.get("multiplier") is not None:
            self._multiplier = float(exp["multiplier"])
            self.strategy_switches += 1
            self.pending_check = None
            self.verification_result = None
            return self._act_adaptation(ctx, g)
        # Reality disagrees and no runtime guidance is available: repeating the
        # invalid strategy is counted, then the model answers its best guess
        # (it never loops forever waiting for help).
        self.strategy_retries += 1  # repeated failed strategy
        return self._answer(self.pending_check)

    def _act_cross_domain(self, ctx: ModelContext, g: Dict[str, Any]) -> AgentAction:
        """The memorized internal-domain rule (factor 1) is insufficient for
        external domains; the scaling factor must be discovered by testing.
        The model's memorized exploration order deliberately misses it, so the
        runtime's systematic experiment is the only reliable discovery path."""
        keys = list((ctx.task.metadata or {}).get("facts", []))
        missing = [k for k in keys if k not in self.believed]
        if missing:
            key = missing[0]
            if self._give_up_on("read_fact", key):
                self.believed[key] = self.rng.choice([3, 6, 9, 11, 14])
                return AgentAction(kind="tool", tool="read_fact", args={"key": key},
                                   source="gave_up")
            if self.rng.random() < self.profile.hallucination_bias:
                self.believed[key] = self.rng.choice([3, 6, 9, 11, 14])
                self.hallucinated_keys.append(key)
                return AgentAction(kind="tool", tool="read_fact", args={"key": key},
                                   source="hallucinated")
            return AgentAction(kind="tool", tool="read_fact", args={"key": key})

        base = sum(self.believed[k] for k in keys if k != "domain")
        if self._multiplier is None:
            self._multiplier = 1.0
        value = base * self._multiplier

        if self.pending_check is None:
            self.pending_check = value
            return AgentAction(kind="tool", tool="check_answer", args={"value": value})
        if self.verification_result is None:
            return AgentAction(kind="tool", tool="check_answer",
                               args={"value": self.pending_check})
        if self.verification_result:
            return self._answer(self.pending_check)

        exp = g.get("experiment_result")
        if isinstance(exp, dict) and exp.get("verdict") == "SUPPORTS" \
                and exp.get("multiplier") is not None:
            self._multiplier = float(exp["multiplier"])
            self.strategy_switches += 1
        else:
            candidates = [m for m in (3.0, 4.0, 0.5)
                          if m not in self._multiplier_tried]
            if candidates and len(self._multiplier_tried) < self.profile.exploration_limit:
                self._multiplier = candidates[0]
                self._multiplier_tried.append(self._multiplier)
                self.strategy_switches += 1
            else:
                return self._answer(self.pending_check)  # best guess (wrong)
        self.pending_check = None
        self.verification_result = None
        return self._act_cross_domain(ctx, g)

    def _answer(self, value: Any) -> AgentAction:
        self.answered = True
        self.answer = {"value": value}
        return AgentAction(kind="answer", claim=self.answer)
