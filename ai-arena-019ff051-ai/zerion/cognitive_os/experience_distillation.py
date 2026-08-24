"""
Slice 4 — ExperienceDistillation.

EPISODE -> ANALYZE -> DISTILL -> VALIDATE -> REUSABLE RULE.

Distillation is deterministic and evidence-referencing: every distilled item
records the episodes and evidence it came from. Validation is the gate that turns
a candidate into reusable knowledge:

- one successful episode is NEVER universal knowledge (needs repeatability)
- counterexamples weaken or reject
- confidence is computed by an explicit formula from evidence counts
- causal items stay CAUSAL_HYPOTHESIS unless OBSERVED experimental evidence
  (Slice 3) supports them — correlation is never converted into causation
- model-generated lessons are stored as data but can never be validated
"""

import time
from typing import Any, Dict, List, Optional

from zerion.cognitive_os.episode import (
    EpisodeMode,
    EpisodeStore,
    ExperienceEpisode,
)
from zerion.cognitive_os.distilled import (
    CausalityStatus,
    DistilledExperience,
    DistilledExperienceStore,
    DistilledType,
    ValidationStatus,
)
from zerion.cognitive_os.failure_learning import (
    FailureRecord,
    FailureStore,
)
from zerion.cognitive_os.evidence import EvidenceMode, EvidenceStore


class ExperienceDistillation:
    def __init__(self,
                 episode_store: EpisodeStore,
                 distilled_store: DistilledExperienceStore,
                 failure_store: Optional[FailureStore] = None,
                 evidence_store: Optional[EvidenceStore] = None,
                 min_episodes_to_validate: int = 3,
                 validate_confidence_threshold: float = 0.7):
        self.episodes = episode_store
        self.distilled = distilled_store
        self.failures = failure_store
        self.evidence = evidence_store
        self.min_episodes_to_validate = min_episodes_to_validate
        self.validate_confidence_threshold = validate_confidence_threshold

    # --- Distillation ----------------------------------------------------------

    def distill_episode(self, episode: ExperienceEpisode) -> List[DistilledExperience]:
        """Extract candidate items from one episode. Nothing is promoted here:
        every item starts CANDIDATE with low confidence and references the
        episode + evidence it came from."""
        produced: List[DistilledExperience] = []
        if episode.mode == EpisodeMode.SIMULATED:
            return produced  # simulated episodes inform planning only, never rules

        failures = self._failures_of(episode)
        if not failures and not episode.actions:
            return produced

        if failures:
            for failure in failures:
                item = self._prevention_rule(episode, failure)
                merged = self._merge_or_create(item)
                if merged is not None:
                    produced.append(merged)
        elif episode.success:
            item = self._procedure(episode)
            merged = self._merge_or_create(item)
            if merged is not None:
                produced.append(merged)

        if (episode.question_ids or episode.hypothesis_ids
                or episode.experiment_ids):
            item = self._causal_pattern(episode)
            merged = self._merge_or_create(item)
            if merged is not None:
                produced.append(merged)
        return produced

    def _failures_of(self, episode: ExperienceEpisode) -> List[FailureRecord]:
        if self.failures is None:
            return []
        records = []
        for fid in episode.failures:
            f = self.failures.get_failure(fid)
            if f is not None:
                records.append(f)
        return records

    def _prevention_rule(self, episode: ExperienceEpisode,
                         failure: FailureRecord) -> DistilledExperience:
        signals = failure.signals or ["the reported error"]
        statement = (f"'{failure.action}' fails when "
                     f"{', '.join(signals)}.")
        action = (f"Before executing '{failure.action}', check the conditions "
                  f"implied by {', '.join(signals)}; on failure, verify them "
                  f"before retrying.")
        return DistilledExperience(
            type=DistilledType.FAILURE_PREVENTION_RULE,
            statement=statement,
            conditions=failure.context or episode.context,
            action=action,
            expected_outcome=f"'{failure.action}' succeeds when the conditions hold",
            evidence=list(failure.evidence),
            confidence=0.3,
            source_episodes=[episode.episode_id],
            provenance={
                "source": "experience_distillation",
                "derived_from": "failure_record",
                "failure_id": failure.failure_id,
                "signals": failure.signals,
                "repeat_count_at_distillation": failure.repeat_count,
            },
            revision_history=[{"event": "distilled", "at": time.time(),
                               "episode_id": episode.episode_id,
                               "status": ValidationStatus.CANDIDATE.value}],
        )

    def _procedure(self, episode: ExperienceEpisode) -> DistilledExperience:
        actions = "; ".join(str(a.get("action", "")) for a in episode.actions)
        return DistilledExperience(
            type=DistilledType.PROCEDURE,
            statement=(f"The action sequence [{actions}] succeeded in "
                       f"'{episode.context}'."),
            conditions=episode.context,
            action=actions,
            expected_outcome="success",
            evidence=[],
            confidence=0.25,
            source_episodes=[episode.episode_id],
            provenance={"source": "experience_distillation",
                        "derived_from": "successful_episode",
                        "episode_mode": episode.mode.value},
            revision_history=[{"event": "distilled", "at": time.time(),
                               "episode_id": episode.episode_id,
                               "status": ValidationStatus.CANDIDATE.value}],
        )

    def _causal_pattern(self, episode: ExperienceEpisode) -> DistilledExperience:
        """A causal claim from correlation alone stays a HYPOTHESIS. Only
        OBSERVED experimental evidence (Slice 3) can ever promote it."""
        return DistilledExperience(
            type=DistilledType.CAUSAL_PATTERN,
            statement=(f"In '{episode.context}', the actions taken and the "
                       f"observed outcomes are associated."),
            conditions=episode.context,
            action="",
            expected_outcome="",
            evidence=[],
            confidence=0.2,
            source_episodes=[episode.episode_id],
            causality_status=CausalityStatus.CAUSAL_HYPOTHESIS,
            provenance={"source": "experience_distillation",
                        "derived_from": "episode_analysis",
                        "note": "correlational — causation not established"},
            revision_history=[{"event": "distilled", "at": time.time(),
                               "episode_id": episode.episode_id,
                               "status": ValidationStatus.CANDIDATE.value,
                               "causality": CausalityStatus.CAUSAL_HYPOTHESIS.value}],
        )

    def _merge_or_create(self, item: DistilledExperience
                         ) -> Optional[DistilledExperience]:
        """Duplicate lessons merge their source episodes instead of being stored
        twice (adversarial 'duplicate lesson' is handled here)."""
        existing = self.distilled.get_by_fingerprint(item.fingerprint)
        if existing is None:
            self.distilled.put(item)
            return item
        for ep in item.source_episodes:
            if ep not in existing.source_episodes:
                existing.source_episodes.append(ep)
        for ev in item.evidence:
            if ev not in existing.evidence:
                existing.evidence.append(ev)
        existing.updated_at = time.time()
        existing.revision_history.append({
            "event": "merged_episode", "at": time.time(),
            "episode_id": item.source_episodes[0] if item.source_episodes else "",
            "status": existing.validation_status.value,
        })
        self.distilled.put(existing)
        return existing

    # --- Validation ------------------------------------------------------------

    def validate_lessons(self) -> List[Dict[str, Any]]:
        """Re-validate every non-terminal lesson against the accumulated episode
        evidence. Evidence determines the outcome; nothing is assumed."""
        changed: List[Dict[str, Any]] = []
        for item in self.distilled.list():
            if item.validation_status in (ValidationStatus.VALIDATED,
                                          ValidationStatus.REJECTED,
                                          ValidationStatus.DEPRECATED):
                continue
            before = (item.validation_status, item.confidence)
            self._validate_one(item)
            if (item.validation_status, item.confidence) != before:
                changed.append({
                    "id": item.id,
                    "type": item.type.value,
                    "validation_status": item.validation_status.value,
                    "confidence": round(item.confidence, 6),
                    "source_episodes": item.source_episodes,
                    "counterexamples": item.counterexamples,
                })
                self.distilled.put(item)
        return changed

    def _validate_one(self, item: DistilledExperience) -> None:
        support = len(item.source_episodes)
        counter = len(item.counterexamples)

        # Explicit, inspectable confidence formula (evidence counts only).
        base = 0.3
        support_bonus = min(0.4, support * 0.1)
        recurrence_bonus = 0.0
        for sid in item.source_episodes:
            ep = self.episodes.get(sid)
            if ep is None or not ep.failures:
                continue
            for fid in ep.failures:
                f = self.failures.get_failure(fid) if self.failures else None
                if f is not None and f.repeat_count >= 2:
                    recurrence_bonus = min(0.15, recurrence_bonus + 0.05)
        counter_penalty = min(0.5, counter * 0.25)
        confidence = base + support_bonus + recurrence_bonus - counter_penalty
        item.confidence = round(min(1.0, max(0.0, confidence)), 6)

        if counter > 0 and item.confidence < 0.3:
            item.validation_status = ValidationStatus.REJECTED
            reason = "counterexamples contradict the lesson"
        elif counter > 0:
            item.validation_status = ValidationStatus.WEAKENED
            reason = "counterexamples reduce confidence"
        elif support >= self.min_episodes_to_validate \
                and item.confidence >= self.validate_confidence_threshold \
                and not self._model_generated(item):
            item.validation_status = ValidationStatus.VALIDATED
            reason = (f"repeatable across {support} episodes, confidence "
                      f"{item.confidence:.2f}, no counterexamples")
        elif support >= 2:
            item.validation_status = ValidationStatus.VALIDATING
            reason = "repeatable but not enough evidence yet"
        else:
            item.validation_status = ValidationStatus.CANDIDATE
            reason = "insufficient evidence — one episode is never universal"

        item.updated_at = time.time()
        item.revision_history.append({
            "event": "validation", "at": time.time(),
            "validation_status": item.validation_status.value,
            "confidence": item.confidence,
            "reason": reason,
        })

    def _model_generated(self, item: DistilledExperience) -> bool:
        prov = item.provenance or {}
        return str(prov.get("source", "")).lower() in (
            "model", "model_generated", "llm")

    # --- Causal promotion ------------------------------------------------------

    def promote_causality(self, item_id: str) -> DistilledExperience:
        """Promote a CAUSAL_PATTERN to CONFIRMED_CAUSAL only if OBSERVED
        experimental evidence (Slice 3) supports it. Correlation alone never
        promotes."""
        item = self.distilled.get(item_id)
        if item is None:
            raise KeyError(f"Unknown distilled item {item_id}")
        if item.type != DistilledType.CAUSAL_PATTERN:
            return item
        observed = 0
        if self.evidence is not None:
            for ev_id in item.evidence:
                ev = self.evidence.get(ev_id)
                if ev is not None and ev.provenance.mode == EvidenceMode.OBSERVED \
                        and ev.verdict.value == "SUPPORTS":
                    observed += 1
        if observed >= 1:
            item.causality_status = CausalityStatus.CONFIRMED_CAUSAL
        else:
            item.causality_status = CausalityStatus.CAUSAL_HYPOTHESIS
        item.updated_at = time.time()
        item.revision_history.append({
            "event": "causality_promotion", "at": time.time(),
            "causality_status": item.causality_status.value,
            "observed_supporting_evidence": observed,
        })
        self.distilled.put(item)
        return item

    # --- Lifecycle helpers -----------------------------------------------------

    def deprecate_lesson(self, item_id: str, reason: str) -> DistilledExperience:
        """Explicitly deprecate a stale lesson (it remains stored with its
        history — never silently deleted)."""
        item = self.distilled.get(item_id)
        if item is None:
            raise KeyError(f"Unknown distilled item {item_id}")
        item.validation_status = ValidationStatus.DEPRECATED
        item.updated_at = time.time()
        item.revision_history.append({
            "event": "deprecated", "at": time.time(), "reason": reason,
            "status": ValidationStatus.DEPRECATED.value,
        })
        self.distilled.put(item)
        return item

    def add_counterexample(self, item_id: str, episode_id: str,
                           episode_store: EpisodeStore) -> DistilledExperience:
        """A contradictory experience is recorded on the lesson; revalidation
        weakens or rejects it."""
        item = self.distilled.get(item_id)
        if item is None:
            raise KeyError(f"Unknown distilled item {item_id}")
        if episode_store.get(episode_id) is None:
            raise KeyError(f"Unknown episode {episode_id}")
        if episode_id not in item.counterexamples:
            item.counterexamples.append(episode_id)
        item.updated_at = time.time()
        self.distilled.put(item)
        self._validate_one(item)
        self.distilled.put(item)
        return item
