"""
Slice 9 — deterministic task worlds and mock tools.

Each task family gets a seeded ``BenchmarkWorld``: ground truth is reachable
ONLY through tools (no hidden answer in the prompt, no evaluator info in the
model context). Tools have controlled, deterministic failure modes (flaky
tool, contradictory sources, malformed output) so recovery and verification
are measurable. The evaluator is external to the agent and checks both the
answer AND the actual tool-call log — a hallucinated success (claim without
a matching tool call) fails the task objectively.
"""

from dataclasses import dataclass, field
import hashlib
import random
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from zerion.cognitive_os.benchmark.types import BenchmarkTask


@dataclass
class ToolCall:
    tool: str
    args: Dict[str, Any]
    ok: bool
    result: Any
    error: str = ""
    latency_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "args": dict(self.args),
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "latency_s": round(self.latency_s, 6),
        }


class BenchmarkTool:
    """A deterministic mock tool. ``flaky_first`` makes it fail the first N
    calls (controlled failure), then succeed."""

    def __init__(self, name: str, fn: Callable[[Dict[str, Any]], Any],
                 flaky_first: int = 0, latency_s: float = 0.0005):
        self.name = name
        self._fn = fn
        self.flaky_first = flaky_first
        self.latency_s = latency_s

    def call(self, args: Dict[str, Any], call_index: int) -> Tuple[bool, Any, str]:
        if self.flaky_first > 0 and call_index < self.flaky_first:
            return False, None, (
                f"{self.name} failed (transient, attempt {call_index + 1}/{self.flaky_first})")
        try:
            return True, self._fn(dict(args)), ""
        except Exception as e:  # noqa: BLE001
            return False, None, f"{type(e).__name__}: {e}"


@dataclass
class BenchmarkWorld:
    """The deterministic ground truth for one task. Tools are the only way to
    observe it; the evaluator checks answer AND the tool-call log."""

    task: BenchmarkTask
    facts: Dict[str, Any] = field(default_factory=dict)          # key -> value
    sources: Dict[str, Any] = field(default_factory=dict)        # source name -> text
    authoritative: str = ""                                       # source that is truth
    correct_answer: Any = None
    required_tool_calls: List[str] = field(default_factory=list)  # must appear in log
    seed: int = 0
    flaky_first: Dict[str, int] = field(default_factory=dict)     # tool name -> failures
    max_steps: int = 30
    timeout_s: float = 60.0
    tools: Dict[str, BenchmarkTool] = field(default_factory=dict)
    # Adaptation support: environment phase A -> B. check_answer honors the
    # active mode so a strategy that was valid in A stops validating in B.
    mode: str = "A"
    mode_factor: float = 1.0
    mode_b_answer: Any = None

    def __post_init__(self) -> None:
        self._register_default_tools()

    def set_mode(self, mode: str) -> None:
        """Flip the environment phase (adaptation family)."""
        self.mode = mode

    def _register_default_tools(self) -> None:
        rng = random.Random(f"world-{self.task.task_id}-{self.seed}")

        def _read_fact(args: Dict[str, Any]) -> Any:
            key = str(args.get("key", ""))
            if key not in self.facts:
                raise KeyError(f"unknown fact '{key}'")
            return self.facts[key]

        def _read_source(args: Dict[str, Any]) -> Any:
            name = str(args.get("source", ""))
            if name not in self.sources:
                raise KeyError(f"unknown source '{name}'")
            return self.sources[name]

        def _compute(args: Dict[str, Any]) -> Any:
            op = str(args.get("op", "sum"))
            values = list(args.get("values", []))
            if not isinstance(values, list) or not all(
                    isinstance(v, (int, float)) for v in values):
                raise ValueError("compute requires a list of numbers")
            if op == "sum":
                return sum(values)
            if op == "product":
                p = 1
                for v in values:
                    p *= v
                return p
            if op == "scale":
                # multiply the first value by the second (capability reuse)
                if len(values) != 2:
                    raise ValueError("scale requires exactly 2 values")
                return values[0] * values[1]
            raise ValueError(f"unknown op '{op}'")

        def _apply(args: Dict[str, Any]) -> Any:
            fn = str(args.get("fn", ""))
            value = args.get("value")
            if fn == "f":
                return value * 2 + 1
            if fn == "g":
                return value + 10
            if fn == "h":
                return value - 3
            raise ValueError(f"unknown function '{fn}'")

        def _read_mode(args: Dict[str, Any]) -> Any:
            # Adaptation family: the current environment phase (A or B).
            return self.mode

        def _check_answer(args: Dict[str, Any]) -> Any:
            # World validator tool: True only for the truth. Adaptation family
            # validates against the ACTIVE mode's ground truth.
            if (self.task.metadata or {}).get("family") == "adaptation":
                target = self.mode_b_answer if self.mode == "B" else self.correct_answer
                return args.get("value") == target
            return args.get("value") == self.correct_answer

        def _request_info(args: Dict[str, Any]) -> Any:
            # 'Human' answer channel for underspecified tasks: returns the
            # missing parameter value. Only reachable through this tool.
            param = str(args.get("param", ""))
            meta = self.task.metadata or {}
            if meta.get("family") == "question_task" and param == meta.get("missing_param"):
                instance = int(meta.get("instance", 0))
                return 6 + instance
            raise KeyError(f"no provider for missing info '{param}'")

        lat = 0.0003 + 0.0002 * rng.random()
        self.tools["read_fact"] = BenchmarkTool(
            "read_fact", _read_fact,
            flaky_first=self.flaky_first.get("read_fact", 0), latency_s=lat)
        self.tools["read_source"] = BenchmarkTool(
            "read_source", _read_source, latency_s=lat)
        self.tools["compute"] = BenchmarkTool("compute", _compute, latency_s=0.0004)
        self.tools["apply"] = BenchmarkTool("apply", _apply, latency_s=0.0003)
        family = (self.task.metadata or {}).get("family", "")
        # The world validator is available to every family that needs reality
        # testing (novel order discovery, adaptation, cross-domain rules,
        # capability validation). check_answer is a real tool call in the log.
        if family in ("novel_algorithm", "adaptation", "cross_domain",
                      "capability_reuse", "long_horizon"):
            self.tools["check_answer"] = BenchmarkTool("check_answer", _check_answer,
                                                       latency_s=0.0002)
        if family == "question_task":
            self.tools["request_info"] = BenchmarkTool("request_info", _request_info,
                                                       latency_s=0.0002)
        if family == "adaptation":
            self.tools["read_mode"] = BenchmarkTool("read_mode", _read_mode,
                                                    latency_s=0.0001)

    def call_tool(self, name: str, args: Dict[str, Any],
                  call_index: int) -> ToolCall:
        tool = self.tools.get(name)
        if tool is None:
            return ToolCall(name, args, False, None, error=f"unknown tool '{name}'")
        t0 = time.perf_counter()
        ok, result, err = tool.call(args, call_index)
        lat = time.perf_counter() - t0
        return ToolCall(name, args, ok, result, error=err, latency_s=lat)

    def evaluate(self, answer: Any, log: List[ToolCall]) -> Tuple[bool, Dict[str, Any]]:
        """Objective evaluation: answer must match ground truth AND every
        required tool call must appear in the log."""
        # Adaptation tasks change truth mid-trial: the FINAL truth is the
        # post-change (mode B) answer when the environment flipped.
        truth = self.correct_answer
        if self.mode == "B" and self.mode_b_answer is not None:
            truth = self.mode_b_answer
        detail: Dict[str, Any] = {"expected": truth}
        ok = answer == truth
        detail["answer_matches"] = bool(ok)
        missing = [r for r in self.required_tool_calls
                   if not any(tc.tool == r for tc in log)]
        detail["missing_required_calls"] = missing
        if missing:
            detail["reason"] = f"missing required tool call(s): {missing}"
            return False, detail
        # Long-horizon tasks require the DEPENDENT call sequence to actually be
        # executed, in order (a critical dependency that is skipped fails the
        # task even if the final value happens to match).
        required_seq = (self.task.metadata or {}).get("required_sequence")
        if required_seq:
            skipped = self._missing_sequence(log, required_seq)
            if skipped:
                detail["missing_sequence"] = skipped
                detail["reason"] = f"required call sequence not executed: {skipped}"
                return False, detail
        if not ok:
            detail["reason"] = f"answer {answer!r} != ground truth {truth!r}"
            return False, detail
        detail["reason"] = ""
        return True, detail

    @staticmethod
    def _missing_sequence(log: List[ToolCall], seq: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Greedy subsequence match of the required calls against the log.
        Returns the entries that never matched (empty = full sequence ran)."""
        idx = 0
        for tc in log:
            if idx >= len(seq):
                break
            entry = seq[idx]
            if tc.tool != entry.get("tool"):
                continue
            expected = entry.get("args") or {}
            if all(tc.args.get(k) == v for k, v in expected.items()):
                idx += 1
        return list(seq[idx:]) if idx < len(seq) else []


# ---------------------------------------------------------------------------
# Task family builders. Each returns (BenchmarkTask, world_factory(seed)).
# The world always references the exact registered task object.
# ---------------------------------------------------------------------------

def _family_task(**kw: Any) -> BenchmarkTask:
    return BenchmarkTask(**kw)


def build_fetch_compute(instance: int = 0) -> Tuple[BenchmarkTask, Any]:
    """TOOL_EXECUTION: fetch two facts and compute the sum. The evaluator
    requires BOTH facts to be actually fetched (anti-hallucination)."""
    pairs = [
        ({"a": 7, "b": 5}, 12),
        ({"a": 3, "b": 9}, 12),
        ({"a": 4, "b": 6}, 10),
        ({"a": 8, "b": 2}, 10),
        ({"a": 11, "b": 7}, 18),
    ]
    facts, answer = pairs[instance % len(pairs)]
    task = _family_task(
        task_id=f"bm_tool_{instance}",
        category="TOOL_EXECUTION",
        description=(
            "Read fact 'a' and fact 'b' from the data store, then compute "
            "their sum and report it as the answer. The answer must be "
            "supported by the actual data."),
        available_tools=["read_fact", "compute"],
        success_criteria=["answer equals the true sum",
                          "both facts were actually read from the store"],
        failure_criteria=["answer is a guess not backed by the store",
                          "a required fact was never read"],
        difficulty=0.3, novelty=0.2, stakes=0.3,
        timeout_s=30.0,
        resource_budget={"tool_calls": 12},
        metadata={"family": "fetch_compute", "facts": list(facts.keys()),
                  "instance": instance},
    )

    def make(seed: int) -> BenchmarkWorld:
        return BenchmarkWorld(
            task=task, facts=dict(facts), correct_answer=answer, seed=seed,
            required_tool_calls=["read_fact", "read_fact"], max_steps=12,
            timeout_s=task.timeout_s)
    return task, make


def build_flaky_fetch(instance: int = 0) -> Tuple[BenchmarkTask, Any]:
    """FAILURE_RECOVERY: the read tool is flaky (fails the first N calls)
    then succeeds. Success requires recovery, not giving up."""
    specs = [
        ({"a": 7, "b": 5}, 12, 3),
        ({"a": 3, "b": 9}, 12, 2),
        ({"a": 4, "b": 6}, 10, 4),
        ({"a": 8, "b": 2}, 10, 2),
        ({"a": 11, "b": 7}, 18, 3),
    ]
    facts, answer, fail_first = specs[instance % len(specs)]
    task = _family_task(
        task_id=f"bm_recovery_{instance}",
        category="FAILURE_RECOVERY",
        description=(
            "Read fact 'a' and fact 'b' from the data store, compute their "
            "sum and report it. The store can be temporarily unavailable: "
            "recover and retry instead of giving up or guessing."),
        available_tools=["read_fact", "compute"],
        success_criteria=["answer equals the true sum",
                          "both facts were actually read"],
        failure_criteria=["gave up after a transient failure",
                          "answered from a guess"],
        difficulty=0.5, novelty=0.3, stakes=0.4,
        timeout_s=30.0,
        resource_budget={"tool_calls": 20},
        metadata={"family": "flaky_fetch", "facts": list(facts.keys()),
                  "instance": instance},
    )

    def make(seed: int) -> BenchmarkWorld:
        return BenchmarkWorld(
            task=task, facts=dict(facts), correct_answer=answer, seed=seed,
            required_tool_calls=["read_fact", "read_fact"],
            flaky_first={"read_fact": fail_first}, max_steps=20,
            timeout_s=task.timeout_s)
    return task, make


def build_contradiction(instance: int = 0) -> Tuple[BenchmarkTask, Any]:
    """REALITY_VERIFICATION: two sources disagree; the config file is
    authoritative. Answering from the doc alone is wrong."""
    specs = [
        ({"docs": "The service listens on port 8080",
          "config": "port = 9090"}, "9090"),
        ({"docs": "Default timeout is 30 seconds",
          "config": "timeout = 60"}, "60"),
        ({"docs": "The flag is enabled by default",
          "config": "flag = false"}, "false"),
        ({"docs": "Retries are capped at 2",
          "config": "retries = 5"}, "5"),
        ({"docs": "The API version is v1",
          "config": "api_version = v2"}, "v2"),
    ]
    sources, answer = specs[instance % len(specs)]
    task = _family_task(
        task_id=f"bm_reality_{instance}",
        category="REALITY_VERIFICATION",
        description=(
            "Determine the true value of the setting. The documentation and "
            "the configuration file disagree; the configuration file is "
            "authoritative. Resolve the conflict with evidence."),
        available_tools=["read_source"],
        success_criteria=["answer matches the configuration file"],
        failure_criteria=["answer matches only the documentation",
                          "asserted a value without checking the config"],
        difficulty=0.5, novelty=0.4, stakes=0.5,
        timeout_s=30.0,
        resource_budget={"tool_calls": 12},
        metadata={"family": "contradiction", "sources": list(sources.keys()),
                  "authoritative": "config", "instance": instance},
    )

    def make(seed: int) -> BenchmarkWorld:
        return BenchmarkWorld(
            task=task, sources=dict(sources), authoritative="config",
            correct_answer=answer, seed=seed,
            required_tool_calls=["read_source"], max_steps=12,
            timeout_s=task.timeout_s)
    return task, make


def build_novel_algorithm(instance: int = 0) -> Tuple[BenchmarkTask, Any]:
    """NOVEL_PROBLEM_SOLVING: the correct composition of f/g/h is NOT the
    obvious/memorized order. Only testing the right composition succeeds."""
    p = 4 + instance
    answer = 2 * (p - 3 + 10) + 1   # f(g(h(p)))
    task = _family_task(
        task_id=f"bm_novel_{instance}",
        category="NOVEL_PROBLEM_SOLVING",
        description=(
            f"Compute the value of the pipeline for input p={p}. The pipeline "
            "applies three transformations f, g, h to the value, one after "
            "another. The documentation does not specify the order; you must "
            "determine the correct order by testing. Available functions: f, g, h."),
        available_tools=["apply"],
        success_criteria=["answer equals the true pipeline result"],
        failure_criteria=["applied the wrong order",
                          "asserted a result without testing"],
        difficulty=0.8, novelty=0.9, stakes=0.5,
        timeout_s=45.0,
        resource_budget={"tool_calls": 24},
        metadata={"family": "novel_algorithm", "input": p,
                  "functions": ["f", "g", "h"], "correct_order": ["f", "g", "h"],
                  "instance": instance},
    )

    def make(seed: int) -> BenchmarkWorld:
        return BenchmarkWorld(
            task=task, facts={"p": p}, correct_answer=answer, seed=seed,
            required_tool_calls=["apply"], max_steps=24,
            timeout_s=task.timeout_s)
    return task, make


def build_capability_reuse(instance: int = 0) -> Tuple[BenchmarkTask, Any]:
    """CAPABILITY_REUSE: compute a 'discounted total' = sum(facts) * factor.
    The learning phase validates a capability; the eval phase reuses it."""
    specs = [
        ({"a": 5, "b": 3, "c": 2}, 2, 20),
        ({"a": 4, "b": 6, "c": 1}, 3, 33),
        ({"a": 7, "b": 2, "c": 5}, 2, 28),
        ({"a": 1, "b": 9, "c": 4}, 2, 28),
        ({"a": 8, "b": 4, "c": 6}, 3, 54),
    ]
    facts, factor, answer = specs[instance % len(specs)]
    task = _family_task(
        task_id=f"bm_reuse_{instance}",
        category="CAPABILITY_REUSE",
        description=(
            f"Read facts a, b, c from the store, compute their sum and "
            f"multiply it by the discount factor {factor}. Report the "
            "discounted total."),
        available_tools=["read_fact", "compute"],
        success_criteria=["answer equals the true discounted total",
                          "all facts were actually read"],
        failure_criteria=["guessed the total",
                          "skipped a required fact"],
        difficulty=0.4, novelty=0.3, stakes=0.4,
        timeout_s=30.0,
        resource_budget={"tool_calls": 12},
        metadata={"family": "capability_reuse", "facts": list(facts.keys()),
                  "factor": factor, "instance": instance},
    )

    def make(seed: int) -> BenchmarkWorld:
        return BenchmarkWorld(
            task=task, facts=dict(facts), correct_answer=answer, seed=seed,
            required_tool_calls=["read_fact", "read_fact", "read_fact"],
            max_steps=14, timeout_s=task.timeout_s)
    return task, make


def build_question_task(instance: int = 0) -> Tuple[BenchmarkTask, Any]:
    """QUESTION_GENERATION: the task is underspecified; the correct next
    action is to identify the missing parameter, request it, then use it."""
    missing_value = 6 + instance
    task = _family_task(
        task_id=f"bm_question_{instance}",
        category="QUESTION_GENERATION",
        description=(
            "Compute 'total = base + extra'. The value of 'extra' is unknown "
            "and is NOT in the store — you must identify that this "
            "information is missing and request it explicitly."),
        available_tools=["read_fact"],
        success_criteria=["identified the missing parameter",
                          "final answer used the requested value"],
        failure_criteria=["invented a value for 'extra' without asking",
                          "gave up"],
        difficulty=0.6, novelty=0.6, stakes=0.3,
        timeout_s=30.0,
        resource_budget={"tool_calls": 10},
        metadata={"family": "question_task", "missing_param": "extra",
                  "instance": instance},
    )

    def make(seed: int) -> BenchmarkWorld:
        return BenchmarkWorld(
            task=task, facts={"base": 10}, correct_answer=10 + missing_value,
            seed=seed, required_tool_calls=[], max_steps=10,
            timeout_s=task.timeout_s)
    return task, make


def build_long_horizon(instance: int = 0) -> Tuple[BenchmarkTask, Any]:
    """LONG_HORIZON_COMPLETION: several dependent steps. A critical dependency
    (one apply call) must actually be executed — skipping it fails the task
    regardless of the final value."""
    specs = [
        (3, ["h", "g", "f"]),
        (5, ["h", "g", "f"]),
        (7, ["h", "g", "f"]),
        (4, ["h", "g", "f"]),
        (6, ["h", "g", "f"]),
    ]
    seed_val, steps = specs[instance % len(specs)]
    value = seed_val
    for fn in steps:  # h: -3, g: +10, f: *2+1
        if fn == "h":
            value = value - 3
        elif fn == "g":
            value = value + 10
        else:
            value = value * 2 + 1
    answer = value
    task = _family_task(
        task_id=f"bm_long_horizon_{instance}",
        category="LONG_HORIZON_COMPLETION",
        description=(
            f"Compute the pipeline result for input p={seed_val}. Apply the "
            "transformations in the documented order h, then g, then f, "
            "carrying the running value through each step. Every step must "
            "actually be executed as a tool call; the final value is the answer."),
        available_tools=["read_fact", "apply"],
        success_criteria=["answer equals the true pipeline result",
                          "every dependent step was actually executed as a tool call"],
        failure_criteria=["a critical dependency was skipped",
                          "final value guessed"],
        difficulty=0.7, novelty=0.5, stakes=0.5,
        timeout_s=45.0,
        resource_budget={"tool_calls": 20},
        metadata={"family": "long_horizon", "input": seed_val, "steps": steps,
                  "required_sequence": [
                      {"tool": "read_fact", "args": {"key": "seed"}},
                      {"tool": "apply", "args": {"fn": "h"}},
                      {"tool": "apply", "args": {"fn": "g"}},
                      {"tool": "apply", "args": {"fn": "f"}},
                  ],
                  "instance": instance},
    )

    def make(seed: int) -> BenchmarkWorld:
        return BenchmarkWorld(
            task=task, facts={"seed": seed_val}, correct_answer=answer, seed=seed,
            required_tool_calls=["read_fact", "apply"], max_steps=16,
            timeout_s=task.timeout_s)
    return task, make


def build_goal_persistence(instance: int = 0) -> Tuple[BenchmarkTask, Any]:
    """GOAL_PERSISTENCE: while holding a long-term goal, the runtime must
    survive a process restart and keep the goal (priority, progress,
    dependencies, next action). The task itself is an unrelated fetch
    interaction run after the restart; goal survival is measured separately."""
    specs = [(5, 3, 8), (7, 2, 9), (4, 6, 10), (8, 5, 13), (3, 9, 12)]
    a, b, answer = specs[instance % len(specs)]
    task = _family_task(
        task_id=f"bm_goal_{instance}",
        category="GOAL_PERSISTENCE",
        description=(
            "While holding a long-term goal (with priority, progress, "
            "dependencies and a next action), perform an unrelated read-and-sum "
            "task after a process restart. The goal must survive the restart."),
        available_tools=["read_fact"],
        success_criteria=["unrelated task completed correctly",
                          "goal survived restart with priority, progress, "
                          "dependencies and next action"],
        failure_criteria=["goal lost on restart",
                          "unrelated task failed"],
        difficulty=0.6, novelty=0.4, stakes=0.6,
        timeout_s=30.0,
        resource_budget={"tool_calls": 12},
        metadata={"family": "goal_persistence", "facts": ["a", "b"],
                  "instance": instance},
    )

    def make(seed: int) -> BenchmarkWorld:
        return BenchmarkWorld(
            task=task, facts={"a": a, "b": b}, correct_answer=answer, seed=seed,
            required_tool_calls=["read_fact", "read_fact"], max_steps=12,
            timeout_s=task.timeout_s)
    return task, make


def build_adaptation(instance: int = 0) -> Tuple[BenchmarkTask, Any]:
    """ADAPTATION: environment A validates sum; the environment then changes
    (phase B) so the valid strategy becomes sum * factor. Repeating the
    original strategy after the change is a failure, not persistence."""
    specs = [
        (7, 5, 3, 36),
        (4, 6, 2, 20),
        (8, 2, 4, 40),
        (3, 9, 2, 24),
        (11, 7, 3, 54),
    ]
    a, b, factor, b_answer = specs[instance % len(specs)]
    task = _family_task(
        task_id=f"bm_adapt_{instance}",
        category="ADAPTATION",
        description=(
            "Read facts a and b, compute their sum and check it against "
            "reality. After the environment changes (phase B), the valid "
            "strategy becomes sum * factor (factor unknown; discover it by "
            "testing). Adapting means changing strategy, not repeating the "
            "old one."),
        available_tools=["read_fact", "compute", "read_mode", "check_answer"],
        success_criteria=["correct in environment A",
                          "correct in environment B after the change"],
        failure_criteria=["repeated the original strategy after the change"],
        difficulty=0.8, novelty=0.7, stakes=0.6,
        timeout_s=45.0,
        resource_budget={"tool_calls": 24},
        metadata={"family": "adaptation", "facts": ["a", "b"],
                  "factor": factor, "instance": instance},
    )

    def make(seed: int) -> BenchmarkWorld:
        return BenchmarkWorld(
            task=task, facts={"a": a, "b": b}, correct_answer=a + b,
            mode_factor=factor, mode_b_answer=b_answer, seed=seed,
            required_tool_calls=["read_fact", "read_fact", "check_answer"],
            max_steps=20, timeout_s=task.timeout_s)
    return task, make


def build_cross_domain(instance: int = 0) -> Tuple[BenchmarkTask, Any]:
    """CROSS_DOMAIN_REASONING: the same arithmetic applies across domains, but
    the 'external' domain applies a scaling factor the memorized procedure does
    not know; the factor must be discovered by testing against reality."""
    specs = [
        ({"a": 4, "b": 6, "domain": "external"}, 20),
        ({"a": 5, "b": 3, "domain": "internal"}, 8),
        ({"a": 7, "b": 2, "domain": "external"}, 18),
        ({"a": 1, "b": 9, "domain": "external"}, 20),
        ({"a": 8, "b": 4, "domain": "internal"}, 12),
    ]
    facts, answer = specs[instance % len(specs)]
    domain = facts["domain"]
    multiplier = 2 if domain == "external" else 1
    task = _family_task(
        task_id=f"bm_cross_{instance}",
        category="CROSS_DOMAIN_REASONING",
        description=(
            f"Compute the result for the {domain} domain: read facts a and b "
            "and the domain, sum a and b, then apply the domain scaling rule "
            "(external domains are scaled; the factor is discoverable by "
            "testing against reality)."),
        available_tools=["read_fact", "check_answer"],
        success_criteria=["answer equals the true domain-scaled result",
                          "domain fact was read"],
        failure_criteria=["applied the internal-domain rule to the external domain",
                          "guessed the factor"],
        difficulty=0.7, novelty=0.6, stakes=0.4,
        timeout_s=40.0,
        resource_budget={"tool_calls": 18},
        metadata={"family": "cross_domain", "facts": ["a", "b", "domain"],
                  "domain": domain, "multiplier": multiplier,
                  "instance": instance},
    )

    def make(seed: int) -> BenchmarkWorld:
        return BenchmarkWorld(
            task=task, facts=dict(facts), correct_answer=answer, seed=seed,
            required_tool_calls=["read_fact", "read_fact", "read_fact",
                                 "check_answer"],
            max_steps=16, timeout_s=task.timeout_s)
    return task, make


_TASK_BUILDERS = {
    "fetch_compute": build_fetch_compute,
    "flaky_fetch": build_flaky_fetch,
    "contradiction": build_contradiction,
    "novel_algorithm": build_novel_algorithm,
    "capability_reuse": build_capability_reuse,
    "question_task": build_question_task,
    "long_horizon": build_long_horizon,
    "goal_persistence": build_goal_persistence,
    "adaptation": build_adaptation,
    "cross_domain": build_cross_domain,
}


def make_world(task: BenchmarkTask, seed: int) -> BenchmarkWorld:
    """Build the deterministic world for a task from its family metadata."""
    family = (task.metadata or {}).get("family")
    builder = _TASK_BUILDERS.get(family)
    if builder is None:
        raise ValueError(f"no world builder for family '{family}' (task {task.task_id})")
    _, make = builder((task.metadata or {}).get("instance", 0))
    return make(seed)


def world_fingerprint(world: BenchmarkWorld) -> str:
    """Deterministic fingerprint of a world's ground truth (integrity/version
    tracking — never exposed to the agent)."""
    blob = repr({
        "task": world.task.task_id,
        "facts": world.facts,
        "sources": world.sources,
        "authoritative": world.authoritative,
        "correct": world.correct_answer,
        "required": world.required_tool_calls,
        "seed": world.seed,
    })
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
