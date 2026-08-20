"""
Slice 9 — metric calculation.

Every value here is computed from ACTUAL trial records. Nothing is invented:
when a statistic cannot be computed (no samples, division by zero) the result
is None and the caller reports UNKNOWN / NOT_MEASURED.

EffectiveTaskPerformance (the primary metric) is defined transparently:

    ETP = success_rate x (1 - time_penalty) x (1 - retry_penalty)

    success_rate  = successes / trials            (denominator always reported)
    time_penalty  = min(0.5, max(0.0, median_time_s / timeout_s - 0.5))
                   (solutions finishing within half the task timeout pay no
                    time penalty; up to a 50% penalty at the timeout)
    retry_penalty = min(0.3, 0.05 x median_tool_retries)
                   (repeatedly retrying failed tool calls costs up to 30%)

Success rate dominates; time and retry penalties are secondary and capped.
ETP is only meaningful PER TASK (or per task class), never as a blind average
of unrelated tasks. Raw metrics are always reported alongside the score.
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _stdev(values: List[float]) -> Optional[float]:
    """Sample standard deviation; None for n < 2 (undefined)."""
    if len(values) < 2:
        return None
    m = sum(values) / len(values)
    variance = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


@dataclass
class Statistics:
    """Summary of one numeric metric across trials. Fields that cannot be
    computed (n < 2 for std/CI) are None — never guessed."""

    n: int
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    ci95_low: Optional[float] = None
    ci95_high: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n": self.n,
            "mean": None if self.mean is None else round(self.mean, 6),
            "median": None if self.median is None else round(self.median, 6),
            "std": None if self.std is None else round(self.std, 6),
            "ci95_low": None if self.ci95_low is None else round(self.ci95_low, 6),
            "ci95_high": None if self.ci95_high is None else round(self.ci95_high, 6),
        }


def summarize(values: List[float]) -> Optional[Statistics]:
    """Mean / median / sample std / normal-approximation 95% CI for a list of
    measured values. Empty input -> None (caller reports UNKNOWN)."""
    if not values:
        return None
    n = len(values)
    mean = _mean(values)
    median = _median(values)
    std = _stdev(values)
    ci_low = ci_high = None
    if std is not None and n >= 2:
        margin = 1.96 * std / math.sqrt(n)
        ci_low = mean - margin
        ci_high = mean + margin
    return Statistics(n=n, mean=mean, median=median, std=std,
                      ci95_low=ci_low, ci95_high=ci_high)


def improve(zerion_value: float, baseline_value: float) -> Optional[float]:
    """Metric-specific ratio Zerion / baseline. None when the denominator is
    zero or negative (an undefined ratio is reported UNKNOWN, never 0x)."""
    if baseline_value is None or baseline_value <= 0.0:
        return None
    if zerion_value is None:
        return None
    return zerion_value / baseline_value


def wilson_ci(successes: int, n: int, z: float = 1.96) -> Optional[tuple]:
    """Wilson score interval for a proportion (successes / n). None when n == 0."""
    if n <= 0:
        return None
    p_hat = successes / n
    denom = 1 + z * z / n
    centre = (p_hat + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p_hat * (1 - p_hat) / n) + (z * z / (4 * n * n))) / denom
    low = max(0.0, centre - margin)
    high = min(1.0, centre + margin)
    return low, high


@dataclass
class EffectiveTaskPerformance:
    """The primary metric for ONE task (or one task class) and mode.

    ``score`` uses the documented definition above. The raw components are
    always carried alongside so the score is never a black box.
    """

    task_id: str
    mode: str
    n: int
    successes: int
    success_rate: float
    time_penalty: float
    retry_penalty: float
    score: float
    components: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.components is None:
            self.components = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "mode": self.mode,
            "n": self.n,
            "successes": self.successes,
            "success_rate": round(self.success_rate, 4),
            "time_penalty": round(self.time_penalty, 4),
            "retry_penalty": round(self.retry_penalty, 4),
            "score": round(self.score, 4),
            "components": dict(self.components),
        }


def effective_task_performance(
    task_id: str,
    mode: str,
    successes: int,
    n: int,
    total_time_values: List[float],
    tool_retry_values: List[float],
    timeout_s: float,
) -> Optional[EffectiveTaskPerformance]:
    """Compute ETP for one task/mode from measured trial values. n == 0 -> None."""
    if n <= 0:
        return None
    success_rate = successes / n
    median_time = _median(total_time_values)
    median_retries = _median(tool_retry_values)

    time_penalty = 0.0
    if median_time is not None and timeout_s > 0:
        time_penalty = min(0.5, max(0.0, median_time / timeout_s - 0.5))
    retry_penalty = 0.0
    if median_retries is not None:
        retry_penalty = min(0.3, 0.05 * median_retries)

    score = success_rate * (1.0 - time_penalty) * (1.0 - retry_penalty)
    return EffectiveTaskPerformance(
        task_id=task_id,
        mode=mode,
        n=n,
        successes=successes,
        success_rate=success_rate,
        time_penalty=time_penalty,
        retry_penalty=retry_penalty,
        score=score,
        components={
            "median_time_s": None if median_time is None else round(median_time, 6),
            "median_tool_retries": None if median_retries is None else round(median_retries, 4),
            "timeout_s": timeout_s,
        },
    )
