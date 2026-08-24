"""Conversational context manager for ZERION CLI.

Tracks conversation history, resolves ambiguous references ("الأولى",
"صلحها", "same", "that"), and builds context-aware prompts so the
cognitive runtime understands follow-up messages naturally.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Conversation History Entry ──────────────────────────────────────────────

@dataclass
class ConversationTurn:
    """One turn in the conversation."""
    role: str                          # "user" or "zerion"
    text: str                          # the actual message
    timestamp: float = field(default_factory=time.time)
    tool_used: Optional[str] = None    # if ZERION used a tool
    tool_result_ok: Optional[bool] = None
    items: List[str] = field(default_factory=list)  # numbered items mentioned
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Reference Resolution ───────────────────────────────────────────────────

# Ordinal words in Arabic, English, and French
_ORDINALS = {
    # Arabic
    "الأولى": 1, "الثانية": 2, "الثالثة": 3, "الرابعة": 4, "الخامسة": 5,
    "السادسة": 6, "السابعة": 7, "الثامنة": 8, "التاسعة": 9, "العاشرة": 10,
    "أولى": 1, "ثانية": 2, "ثالثة": 3,
    # English
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
    # French
    "première": 1, "premier": 1, "deuxième": 2, "deuxieme": 2,
    "troisième": 3, "troisieme": 3,
}

_ACTION_WORDS = {
    "fix": True, "solve": True, "repair": True, "debug": True, "try": True,
    "test": True, "run": True, "execute": True, "build": True, "check": True,
    "diagnose": True, "inspect": True, "analyze": True, "review": True,
    # Arabic
    "صلح": True, "جرب": True, "شوف": True, "حل": True, "-dir": True,
    "نفّذ": True, "شغّل": True, " kiểm tra": True,
}

_DEMONSTRATIVES = {
    "الأولى", "الثانية", "الثالثة", "الرابعة", "الخامسة",
    "first", "second", "third", "fourth", "fifth",
    "première", "premier", "deuxième", "troisième",
}

_AMBIGUOUS = {
    "صلحها", "fix it", "solve it", "repair it", "جربها", "try it",
    "شوفها", "check it", "run it", "execute it",
    "same", "ا same", "نفس الشيء", "نفسها",
}


class ConversationContext:
    """Manages conversational state for the ZERION CLI.

    Tracks turns, resolves ambiguous references, and builds
    context-aware prompts for the cognitive runtime.
    """

    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self.history: List[ConversationTurn] = []
        self._last_numbered_items: List[str] = []
        self._last_topic: Optional[str] = None

    def add_user_turn(self, text: str,
                      items: Optional[List[str]] = None) -> ConversationTurn:
        turn = ConversationTurn(role="user", text=text, items=items or [])
        self.history.append(turn)
        if items:
            self._last_numbered_items = items
        self._trim()
        return turn

    def add_zerion_turn(self, text: str, tool_used: Optional[str] = None,
                        tool_result_ok: Optional[bool] = None,
                        metadata: Optional[Dict[str, Any]] = None) -> ConversationTurn:
        turn = ConversationTurn(
            role="zerion", text=text,
            tool_used=tool_used, tool_result_ok=tool_result_ok,
            metadata=metadata or {},
        )
        self.history.append(turn)
        # Extract numbered items from ZERION's response
        items = self._extract_numbered_items(text)
        if items:
            self._last_numbered_items = items
        # Track topic
        if text:
            self._last_topic = text[:100]
        self._trim()
        return turn

    def resolve_references(self, user_text: str) -> Tuple[str, Optional[str]]:
        """Resolve ambiguous references in the user's message.

        Returns (resolved_text, context_note) where context_note is a
        brief explanation of what was resolved (shown to the user).
        """
        low = user_text.strip().lower()
        resolved = user_text
        note = None

        # Check for ordinal references: "الأولى", "first", etc.
        for word, idx in _ORDINALS.items():
            if word in low:
                if self._last_numbered_items and idx <= len(self._last_numbered_items):
                    item = self._last_numbered_items[idx - 1]
                    resolved = f"{user_text} (refers to: {item})"
                    note = f"Referenced item {idx}: {item}"
                break

        # Check for action references: "صلحها", "fix it", etc.
        for phrase in _AMBIGUOUS:
            if phrase in low and len(low.split()) <= 4:
                # This is a short follow-up action — append context
                if self._last_numbered_items:
                    items_str = "; ".join(self._last_numbered_items[:3])
                    resolved = f"{user_text} (context from last response: {items_str})"
                    note = f"Using context from previous response"
                elif self._last_topic:
                    resolved = f"{user_text} (previous topic: {self._last_topic})"
                    note = f"Using context from previous topic"
                break

        return resolved, note

    def build_context_prefix(self) -> str:
        """Build a lightweight context prefix for the model.

        Only includes the last 5 turns to stay within the model's
        context window. Plain conversational format (Gemini).
        """
        recent = self.history[-10:]  # last 10 entries (5 user + 5 zerion)
        if not recent:
            return ""

        lines = []
        for turn in recent:
            role = "User" if turn.role == "user" else "ZERION"
            # Truncate long messages
            text = turn.text[:200]
            if len(turn.text) > 200:
                text += "..."
            lines.append(f"{role}: {text}")

        context = "\n".join(lines)
        return (
            "\n[CONVERSATION CONTEXT — recent messages for reference]\n"
            f"{context}\n"
            "[END CONTEXT]\n\n"
        )

    def get_summary(self) -> str:
        """One-line summary of conversation state."""
        n = len(self.history)
        user_turns = sum(1 for t in self.history if t.role == "user")
        tools = [t.tool_used for t in self.history if t.tool_used]
        tool_str = f", tools used: {', '.join(set(tools))}" if tools else ""
        return f"Conversation: {user_turns} messages, {n} turns total{tool_str}"

    def is_reference(self, text: str) -> bool:
        """Check if the text is likely a reference to previous context."""
        low = text.strip().lower()
        words = set(low.split())
        # Short messages with ordinal/demonstrative words
        if len(words) <= 3:
            if words & set(_DEMONSTRATIVES):
                return True
            if any(p in low for p in _AMBIGUOUS):
                return True
        return False

    def _extract_numbered_items(self, text: str) -> List[str]:
        """Extract numbered list items from text."""
        items = []
        for match in re.finditer(r'(?:^|\n)\s*(?:\d+[\.\)]\s*|[-•]\s*)(.+)', text):
            item = match.group(1).strip()
            if item and len(item) > 3:
                items.append(item[:100])
        return items

    def _trim(self):
        if len(self.history) > self.max_turns:
            self.history = self.history[-self.max_turns:]
