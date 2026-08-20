"""
User learning — principle 8: Zerion learns from the user through legitimate
interaction, never by fabricating preferences.

Every observed turn produces a ``UserSignal``. Only EXPLICIT markers in the
user's own words (prefer/always/never/don't/remember/stop) are classified as
learning signals — plain conversation is recorded as NEUTRAL interaction
evidence. No sensitive personal data is inferred: the stored text is a short,
bounded snippet of what the user actually said.

Signals persist to ``<data_dir>/user_learning.json`` so what Zerion learns
from the user survives restarts.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Explicit markers, checked case-insensitively. Deliberately small and
# conservative: only clear user statements become learning signals.
_PREFERENCE_MARKERS = ("prefer", "i like", "i want you to", "always use",
                       "never use", "never do", "don't", "do not",
                       "stop doing", "remember")
_INSTRUCTION_MARKERS = ("remember", "always", "from now on", "please use")


@dataclass
class UserSignal:
    kind: str  # preference | correction | instruction | neutral
    snippet: str
    marker: Optional[str]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "snippet": self.snippet,
                "marker": self.marker, "timestamp": self.timestamp}


class UserLearningStore:
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = Path(data_dir) if data_dir else None
        self._signals: List[UserSignal] = []
        self._load()

    # -- observation -------------------------------------------------------

    def observe_turn(self, user_text: str, response: Optional[str] = None,
                     kind_hint: Optional[str] = None) -> UserSignal:
        """Record one real user turn as a learning signal.

        Classification is evidence-based: explicit markers in the user's text
        (or an explicit caller-provided hint) decide the kind. Plain turns are
        NEUTRAL interaction evidence — never invented preferences."""
        text = (user_text or "").strip()
        snippet = text[:160]
        marker = self._detect_marker(text)
        kind = "neutral"
        if kind_hint in ("preference", "correction", "instruction"):
            kind = kind_hint
        elif marker is not None:
            low = text.lower()
            if any(m in low for m in _INSTRUCTION_MARKERS):
                kind = "instruction"  # explicit instruction outranks preference
            elif any(word in low for word in
                     ("don't", "do not", "stop doing", "never")):
                kind = "correction"
            else:
                kind = "preference"
        signal = UserSignal(kind=kind, snippet=snippet, marker=marker)
        self._signals.append(signal)
        if kind != "neutral":
            self._persist()
        return signal

    @staticmethod
    def _detect_marker(text: str) -> Optional[str]:
        low = text.lower()
        for marker in _PREFERENCE_MARKERS:
            if marker in low:
                return marker
        return None

    # -- accessors ---------------------------------------------------------

    def learned_preferences(self) -> List[UserSignal]:
        return [s for s in self._signals if s.kind != "neutral"]

    def corrections(self) -> List[UserSignal]:
        return [s for s in self._signals if s.kind == "correction"]

    def all_signals(self) -> List[UserSignal]:
        return list(self._signals)

    def count(self) -> int:
        return len(self._signals)

    # -- persistence -------------------------------------------------------

    def _path(self) -> Optional[Path]:
        if self.data_dir is None:
            return None
        return self.data_dir / "user_learning.json"

    def _load(self) -> None:
        path = self._path()
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for entry in data.get("signals", []):
                self._signals.append(UserSignal(
                    kind=entry.get("kind", "neutral"),
                    snippet=entry.get("snippet", ""),
                    marker=entry.get("marker"),
                    timestamp=entry.get("timestamp", 0.0)))
        except (OSError, ValueError):
            self._signals = []  # corrupt store -> empty, never crash runtime

    def _persist(self) -> None:
        path = self._path()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(
                {"signals": [s.to_dict() for s in self._signals]},
                indent=2), encoding="utf-8")
        except OSError:
            pass  # persistence is best-effort; runtime never dies for it
