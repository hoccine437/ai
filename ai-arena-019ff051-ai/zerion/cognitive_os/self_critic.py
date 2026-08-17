"""
ZERION live self-critic.

After reasoning / tool execution the result is reviewed before it becomes the
final response:

    reasoning_result -> confidence -> self-critic -> accept / revise /
    retry / escalate

Rules honored here:

- EMPTY output is never presented as success: one bounded RETRY with the
  relevant context, then honest ESCALATE (the runtime reports the real
  failure, never fabricated execution).
- LOW confidence on a DEEP (novel / ambiguous / complex / high-impact)
  task triggers ONE bounded REVISE pass in which the model critiques and
  corrects its own previous answer. A revision that is non-empty and
  materially different replaces the original; otherwise the original is
  kept.
- Tool results are validated: a tool that reported failure is reported
  honestly and never framed as successful execution.
- The critic is BOUNDED (default 1 revision per turn) — this is a runaway
  guard, not an inference timeout: each model call may still take as long as
  it needs.
"""

from typing import Any, Dict, List, Optional, Tuple

from zerion.cognitive_os.router_types import CognitiveResult, ResultStatus

DEFAULT_MAX_REVISIONS = 1
DEEP_LOW_CONFIDENCE_OUTPUT_CHARS = 40


class SelfCriticDecision:
    ACCEPT = "ACCEPT"
    REVISE = "REVISE"
    RETRY = "RETRY"
    ESCALATE = "ESCALATE"


class ZerionSelfCritic:
    def __init__(self, runtime: Any, *, max_revisions: int = DEFAULT_MAX_REVISIONS):
        self.runtime = runtime
        self.max_revisions = max(0, max_revisions)

    # -- public review ------------------------------------------------------

    async def review(self, task: Any, result: CognitiveResult, *,
                     user_text: str,
                     revisions_used: int) -> Tuple[str, str, Optional[str]]:
        """Review one result. Returns (decision, note, revised_output).

        ``revised_output`` is set only when a REVISE pass produced a better
        answer; ``note`` always explains what the critic actually did.
        """
        output = getattr(result, "output", None)

        # Tool/result validation: a failed execution is never success.
        if result.status == ResultStatus.SUCCESS and not output:
            return (SelfCriticDecision.ESCALATE,
                    "result reported success but produced no output — "
                    "refusing to present empty output as a response",
                    None)

        if output is None or not str(output).strip():
            if revisions_used >= self.max_revisions:
                errors = "; ".join(getattr(result, "errors", None) or [])
                return (SelfCriticDecision.ESCALATE,
                        f"no model output after {revisions_used} attempt(s)"
                        + (f": {errors}" if errors else ""),
                        None)
            return (SelfCriticDecision.RETRY,
                    "no usable output — retrying with the same context",
                    None)

        depth = self._task_depth(task)
        if depth == "DEEP" and revisions_used < self.max_revisions:
            if len(str(output).strip()) < DEEP_LOW_CONFIDENCE_OUTPUT_CHARS:
                return (SelfCriticDecision.REVISE,
                        "low-confidence signal: DEEP task with a very short "
                        "answer — one bounded critique pass",
                        None)
        return (SelfCriticDecision.ACCEPT,
                "result accepted without revision", None)

    # -- bounded revision pass (called by the runtime) -----------------------

    async def critique(self, task: Any, result: CognitiveResult, *,
                       full_prompt: str) -> Optional[str]:
        """One bounded REVISE pass: ask the model to critique and correct its
        previous answer in light of the original context. Returns the revised
        text when it is non-empty and materially different; None otherwise.
        """
        original = str(getattr(result, "output", "") or "")
        critique_prompt = (
            full_prompt
            + "\n\nCritique the previous answer for errors, missing "
              "verification, or overconfidence. If it needs correction, "
              "give the corrected answer now as ZERION. If it was correct, "
              "restate it more precisely.")
        try:
            revised = await self.runtime.cognitive_router.execute(
                task, critique_prompt, mode=getattr(result, "mode", None))
        except Exception:  # noqa: BLE001 — a failed critique never crashes
            return None
        new_text = str(getattr(revised, "output", "") or "").strip()
        if not new_text:
            return None
        if new_text == original.strip():
            return None
        return new_text

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _task_depth(task: Any) -> str:
        try:
            uncertainty = float(getattr(task, "uncertainty", 0.0) or 0.0)
            novelty = float(getattr(task, "novelty", 0.0) or 0.0)
            difficulty = float(getattr(task, "difficulty", 0.0) or 0.0)
            stakes = float(getattr(task, "stakes", 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            return "FAST"
        if (uncertainty + novelty + difficulty + stakes) >= 1.2:
            return "DEEP"
        if max(uncertainty, novelty) >= 0.5:
            return "DEEP"
        return "FAST"
