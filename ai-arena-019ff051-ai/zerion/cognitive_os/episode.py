"""
Slice 4 — ExperienceEpisode.

A structured record of one runtime episode (never a plain transcript): context,
goal/event/question/hypothesis/experiment/observation references, actions,
outcomes, failures, success, lessons, capabilities used, resources and
provenance. Episodes are the raw material for distillation; they are stored
separately from procedural / failure / validated knowledge.
"""

import hashlib
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid


class EpisodeStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class EpisodeMode(str, Enum):
    OBSERVED = "OBSERVED"          # real runtime episode
    SIMULATED = "SIMULATED"        # simulation only — never real-world evidence
    TEST = "TEST"                  # deterministic test fixture


class EpisodeValidationError(ValueError):
    """Raised for structurally invalid episodes."""


class EpisodeStoreIntegrityError(RuntimeError):
    """Raised when persisted episodes are corrupt and strict loading is enabled."""


_MAX_TEXT_LENGTH = 4000
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_text(value: Any) -> str:
    return _CTRL_RE.sub("", str(value)).strip()


def _clean_str_list(values: Any) -> List[str]:
    if not values:
        return []
    return [_clean_text(v) for v in values if _clean_text(v)]


def episode_fingerprint(context: str, actions: List[str], outcome: str) -> str:
    """Deterministic dedup key. Identical episodes (same context + actions +
    outcome) are duplicates and are rejected — but a success and a failure with
    the same actions are different episodes and both must be kept."""
    norm = re.sub(r"\s+", " ", context.lower()).strip()
    key = f"{norm}|{sorted(actions)}|{outcome.lower().strip()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


@dataclass
class ExperienceEpisode:
    episode_id: str = field(default_factory=lambda: f"ep_{uuid.uuid4().hex[:10]}")
    context: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    goal_ids: List[str] = field(default_factory=list)
    event_ids: List[str] = field(default_factory=list)
    question_ids: List[str] = field(default_factory=list)
    hypothesis_ids: List[str] = field(default_factory=list)
    experiment_ids: List[str] = field(default_factory=list)
    observation_ids: List[str] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)   # {action, at, detail?}
    outcomes: List[Dict[str, Any]] = field(default_factory=list)  # {outcome, at, detail?}
    failures: List[str] = field(default_factory=list)             # failure_ids
    success: bool = False
    lessons: List[str] = field(default_factory=list)
    capabilities_used: List[str] = field(default_factory=list)
    resources: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
    status: EpisodeStatus = EpisodeStatus.IN_PROGRESS
    mode: EpisodeMode = EpisodeMode.TEST
    fingerprint: str = ""
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self):
        self.context = _clean_text(self.context)
        if not self.context:
            raise EpisodeValidationError("Episode context must not be empty")
        if len(self.context) > _MAX_TEXT_LENGTH:
            raise EpisodeValidationError("Episode context exceeds max length")
        if isinstance(self.status, str):
            self.status = EpisodeStatus(self.status)
        if isinstance(self.mode, str):
            self.mode = EpisodeMode(self.mode)
        if (self.completed_at is not None
                and self.completed_at + 1e-6 < self.started_at):
            raise EpisodeValidationError(
                "Episode completed_at must not precede started_at")
        self.goal_ids = _clean_str_list(self.goal_ids)
        self.event_ids = _clean_str_list(self.event_ids)
        self.question_ids = _clean_str_list(self.question_ids)
        self.hypothesis_ids = _clean_str_list(self.hypothesis_ids)
        self.experiment_ids = _clean_str_list(self.experiment_ids)
        self.observation_ids = _clean_str_list(self.observation_ids)
        self.failures = _clean_str_list(self.failures)
        self.lessons = _clean_str_list(self.lessons)
        self.capabilities_used = _clean_str_list(self.capabilities_used)
        if not self.fingerprint:
            action_keys = [str(a.get("action", "")) for a in self.actions]
            outcome_keys = [str(o.get("outcome", "")) for o in self.outcomes]
            outcome = ";".join(outcome_keys) or ("success" if self.success else "unknown")
            self.fingerprint = episode_fingerprint(self.context, action_keys, outcome)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "context": self.context,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "goal_ids": self.goal_ids,
            "event_ids": self.event_ids,
            "question_ids": self.question_ids,
            "hypothesis_ids": self.hypothesis_ids,
            "experiment_ids": self.experiment_ids,
            "observation_ids": self.observation_ids,
            "actions": self.actions,
            "outcomes": self.outcomes,
            "failures": self.failures,
            "success": self.success,
            "lessons": self.lessons,
            "capabilities_used": self.capabilities_used,
            "resources": self.resources,
            "provenance": self.provenance,
            "status": self.status.value,
            "mode": self.mode.value,
            "fingerprint": self.fingerprint,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperienceEpisode":
        status = data.get("status", EpisodeStatus.IN_PROGRESS.value)
        try:
            status = EpisodeStatus(status)
        except ValueError:
            status = EpisodeStatus.IN_PROGRESS
        mode = data.get("mode", EpisodeMode.TEST.value)
        try:
            mode = EpisodeMode(mode)
        except ValueError:
            mode = EpisodeMode.TEST
        return cls(
            episode_id=data.get("episode_id", f"ep_{uuid.uuid4().hex[:10]}"),
            context=data.get("context", ""),
            started_at=float(data.get("started_at", time.time())),
            completed_at=data.get("completed_at"),
            goal_ids=list(data.get("goal_ids", [])),
            event_ids=list(data.get("event_ids", [])),
            question_ids=list(data.get("question_ids", [])),
            hypothesis_ids=list(data.get("hypothesis_ids", [])),
            experiment_ids=list(data.get("experiment_ids", [])),
            observation_ids=list(data.get("observation_ids", [])),
            actions=list(data.get("actions", [])),
            outcomes=list(data.get("outcomes", [])),
            failures=list(data.get("failures", [])),
            success=bool(data.get("success", False)),
            lessons=list(data.get("lessons", [])),
            capabilities_used=list(data.get("capabilities_used", [])),
            resources=dict(data.get("resources", {})),
            provenance=dict(data.get("provenance", {})),
            status=status,
            mode=mode,
            fingerprint=data.get("fingerprint", ""),
            updated_at=float(data.get("updated_at", time.time())),
        )


class EpisodeStore:
    """SQLite WAL-backed store for ExperienceEpisodes (corruption-safe, same
    pattern as the Slice 1-3 stores). DB ``experience_episodes.db`` — avoids the
    legacy ``cognitive_episodes.db`` (zerion/intelligence_forge)."""

    def __init__(self, db_path: Optional[str] = "data/experience_episodes.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._episodes: Dict[str, ExperienceEpisode] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    status TEXT,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def put(self, episode: ExperienceEpisode) -> ExperienceEpisode:
        self._episodes[episode.episode_id] = episode
        if not self.db_path:
            return episode
        payload = json.dumps(episode.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO episodes VALUES (?, ?, ?, ?, ?)",
                (episode.episode_id, payload, self._checksum(payload),
                 episode.status.value, episode.updated_at)
            )
            conn.commit()
        finally:
            conn.close()
        return episode

    def get(self, episode_id: str) -> Optional[ExperienceEpisode]:
        return self._episodes.get(episode_id)

    def get_by_fingerprint(self, fingerprint: str) -> Optional[ExperienceEpisode]:
        for e in self._episodes.values():
            if e.fingerprint == fingerprint:
                return e
        return None

    def list(self, status: Optional[EpisodeStatus] = None) -> List[ExperienceEpisode]:
        eps = list(self._episodes.values())
        if status is not None:
            eps = [e for e in eps if e.status == status]
        return sorted(eps, key=lambda e: e.started_at)

    def count(self) -> int:
        return len(self._episodes)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT payload, checksum FROM episodes").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise EpisodeStoreIntegrityError(
                    f"Failed to load persisted episodes from {self.db_path}: {e}"
                ) from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise EpisodeStoreIntegrityError(
                        "Episode row checksum mismatch (corrupt or partial write)")
                data = json.loads(payload)
                ep = ExperienceEpisode.from_dict(data)
                self._episodes[ep.episode_id] = ep
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise EpisodeStoreIntegrityError(
                        f"Failed to load persisted episodes from {self.db_path}: {e}"
                    ) from e
