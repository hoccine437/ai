"""
ZERION runtime identity & context layer.

Gemini is ONLY the reasoning engine of the system. This module builds the
system context that makes ZERION the identity of every conversation:

    ZERION IDENTITY
        -> ZERION CONSTITUTION
        -> ZERION COGNITION (mode / field)
        -> ZERION MEMORY (relevance retrieval)
        -> ZERION GOALS
        -> ZERION CAPABILITY REGISTRY
        -> ZERION TOOL / AGENT ROUTER
        -> GEMINI (reasoning engine)

Every section is derived from REAL runtime state (identity store, invariants,
objective store, memory stores, capability registry) — never hard-coded
persona text. The result is size-bounded so each turn receives a small
relevant context, not an architecture dump (``ZERION_CONTEXT_MAX_CHARS``,
default 1400; sections are dropped tail-first when the budget is exceeded,
with the identity rule never truncated).
"""

import os
from typing import Any, Dict, List, Optional

# The identity contract every model invocation must obey. This is the runtime
# identity layer, not a chat nicety: Gemini must never present itself as the
# system's identity, so the instruction is injected before every turn.
IDENTITY_RULE = (
    "You are the reasoning engine operating inside ZERION, an autonomous "
    "developmental cognitive system. You are NOT the assistant and you do "
    "NOT have an identity of your own. The active system identity is ZERION. "
    "Never claim to be Gemini, Google, or any other base model — you are the "
    "reasoning engine ZERION uses. Always speak as ZERION and refer to "
    "yourself as ZERION."
)

ZERION_MISSION = (
    "ZERION's mission is continuous autonomous problem discovery, empirical "
    "reality learning, and measured self-improvement within safe invariants."
)


def _env_max_chars() -> int:
    raw = os.environ.get("ZERION_CONTEXT_MAX_CHARS", "").strip()
    if raw:
        try:
            return max(400, int(raw))
        except ValueError:  # noqa: BLE001 — non-numeric falls back
            pass
    return 1400


class ZerionRuntimeContext:
    """Assembles the ZERION system context from the live runtime.

    ``runtime`` is the CognitiveRuntime; optional engine-owned sources
    (identity, self_model, readiness) may be injected by the engine so the
    context reflects the whole organism, not just the kernel.
    """

    def __init__(self, runtime: Any, *, identity: Optional[Any] = None,
                 self_model: Optional[Any] = None,
                 readiness: Optional[Any] = None):
        self.runtime = runtime
        self.identity = identity
        self.self_model = self_model
        self.readiness = readiness
        self.max_chars = _env_max_chars()

    # -- real state sources (defensive: a partial/fake runtime never crashes) --

    def _system_name(self) -> str:
        try:
            return str(getattr(self.identity, "system_name", None)
                       or "ZERION")
        except Exception:  # noqa: BLE001
            return "ZERION"

    def _system_id(self) -> str:
        try:
            return str(getattr(self.identity, "system_id", "") or "")
        except Exception:  # noqa: BLE001
            return ""

    def _invariants(self) -> List[str]:
        try:
            invariants = getattr(self.identity, "invariants", None)
            if invariants:
                return [f"{getattr(i, 'id', '')} {getattr(i, 'name', '')}"
                        for i in invariants][:10]
        except Exception:  # noqa: BLE001
            pass
        return []

    def _active_goals(self) -> List[str]:
        try:
            objectives = getattr(self.runtime, "objectives", None)
            if objectives is None:
                return []
            goals = objectives.list_active_objectives()
            return [str(getattr(g, "title", ""))[:120] for g in goals][:3]
        except Exception:  # noqa: BLE001
            return []

    def _capabilities(self) -> List[str]:
        caps: List[str] = []
        try:
            registry = getattr(self.runtime, "capability_registry", None)
            if registry is not None:
                for cap in registry.list():
                    name = str(getattr(cap, "name", "") or "")
                    if name:
                        caps.append(name)
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.self_model is not None:
                for cap in self.self_model.what_can_i_do():
                    name = str(cap.get("name", "") or "")
                    if name and name not in caps:
                        caps.append(name)
        except Exception:  # noqa: BLE001
            pass
        return caps[:24]

    def _memory(self, user_text: str) -> List[str]:
        """Relevance-based memory retrieval — searches ALL stored
        knowledge, not just recent episodes."""
        items: List[str] = []
        try:
            reuse = getattr(self.runtime, "experience_reuse", None)
            if reuse is not None:
                for hit in reuse.retrieve(context=user_text[:300], top_k=5):
                    statement = str(hit.get("statement", "") or "")
                    if statement:
                        items.append(f"[lesson] {statement[:200]}")
        except Exception:  # noqa: BLE001
            pass
        try:
            episodes = getattr(self.runtime, "episode_store", None)
            if episodes is not None:
                import re as _re
                q_words = set(_re.findall(r"[a-z0-9_]+", user_text.lower()))
                _STOP = {"the", "is", "am", "are", "do", "you",
                         "my", "to", "a", "an", "in", "on", "it",
                         "that", "this", "of", "for", "was", "has",
                         "have", "can", "with", "from", "not", "but"}
                # Search ALL episodes, not just the last few
                for ep in episodes.list():
                    context = str(getattr(ep, "context", "") or "")
                    if not context:
                        continue
                    # Extract clean fact from "knowledge: X" format
                    fact = context
                    if fact.startswith("knowledge: "):
                        fact = fact[len("knowledge: "):]
                    ep_words = set(_re.findall(r"[a-z0-9_]+", fact.lower()))
                    shared = ep_words & q_words
                    meaningful = shared - _STOP
                    if meaningful and any(len(w) > 2 for w in meaningful):
                        items.append(f"[knowledge] {fact[:200]}")
        except Exception:  # noqa: BLE001
            pass
        return items[:8]

    def _user_learning(self) -> List[str]:
        try:
            store = getattr(self.runtime, "user_learning", None)
            if store is None:
                return []
            signals = store.learned_preferences()
            return [f"- {s.snippet[:120]}" for s in signals[-3:]]
        except Exception:  # noqa: BLE001
            return []

    def _mode(self, field: Optional[str]) -> str:
        # There is no offline mode: Gemini is the only provider.
        mode = "provider: Gemini (only)"
        if field:
            mode += f" · cognitive field: {field}"
        return mode

    def _readiness_line(self) -> str:
        if self.readiness is None:
            return ""
        try:
            r = self.readiness()
            provider = r.get("provider") or "gemini"
            state = r.get("provider_state") or r.get("status") or "UNKNOWN"
            return (f"provider={provider} state={state} "
                    f"input=text-only")
        except Exception:  # noqa: BLE001
            return ""

    # -- assembly ----------------------------------------------------------

    def build_system_prompt(self, user_text: str, *,
                            task: Optional[Any] = None,
                            field: Optional[str] = None,
                            tools: Optional[List[Dict[str, str]]] = None) -> str:
        """Build the bounded ZERION system context for one turn."""
        sections: List[str] = [IDENTITY_RULE]

        system_name = self._system_name()
        system_id = self._system_id()
        identity_line = f"System identity: {system_name}"
        if system_id:
            identity_line += f" ({system_id})"
        sections.append(identity_line)

        mission = ZERION_MISSION
        sections.append(mission)

        invariants = self._invariants()
        if invariants:
            sections.append("Constitution (inviolable invariants): "
                            + "; ".join(invariants))

        sections.append("Current state: " + self._mode(field))

        goals = self._active_goals()
        if goals:
            sections.append("Active goals: " + "; ".join(goals))

        caps = self._capabilities()
        if caps:
            sections.append("Capability registry (what I can actually do): "
                            + ", ".join(caps))

        if tools:
            lines = [f"- {t.get('name', '')}: {t.get('description', '')}"
                     for t in tools]
            sections.append("Available tools (only call tools that exist "
                            "here; never invent tools):\n" + "\n".join(lines))
            sections.append(
                "If the user asks for an ACTION, respond with exactly one "
                "tool call line: [[TOOL:<name>|<argument>]] and nothing "
                "else. Otherwise respond normally as ZERION.")

        memory = self._memory(user_text)
        if memory:
            sections.append("Relevant memory:\n" + "\n".join(memory))

        learning = self._user_learning()
        if learning:
            sections.append("User instructions learned:\n"
                            + "\n".join(learning))

        readiness = self._readiness_line()
        if readiness:
            sections.append("Runtime readiness: " + readiness)

        # Master intelligence: 21 agents + 100 tools
        agents = self._agents_summary()
        if agents:
            sections.append(agents)
        tools = self._tools_summary()
        if tools:
            sections.append(tools)

        return self._bound("\n\n".join(sections))

    def _agents_summary(self) -> str:
        try:
            registry = getattr(self.runtime, "agent_registry", None)
            if registry is None:
                return ""
            count = registry.count()
            names = [a.name for a in registry.list_all()]
            return (f"Agent Registry: {count} specialized agents available. "
                    f"Agents: {', '.join(names)}. "
                    f"Select the best agent for complex tasks.")
        except Exception:
            return ""

    def _tools_summary(self) -> str:
        try:
            registry = getattr(self.runtime, "master_tools", None)
            if registry is None:
                return ""
            count = registry.count()
            cats = {k: len(v) for k, v in registry.by_category().items()}
            cat_str = ', '.join(f'{k}({v})' for k, v in cats.items())
            return (f"Tool Registry: {count} real tools available. "
                    f"Categories: {cat_str}.")
        except Exception:
            return ""

    def _bound(self, text: str) -> str:
        if len(text) <= self.max_chars:
            return text
        marker = "\n[...]"
        budget = max(0, self.max_chars - len(marker))
        return text[:budget].rstrip() + marker
