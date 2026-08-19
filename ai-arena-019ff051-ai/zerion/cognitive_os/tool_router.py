"""
ZERION tool / capability router.

The local model never fabricates tools: this router is the ONLY source of
truth for what is executable. Every tool is derived from REAL runtime state
(memory stores, objective store, capability registry, identity store) and
runs through the constitution gate (``check_invariants``) before execution.

Two entry points, both bounded:

1. FAST FIELD — deterministic intent detection (``detect``) for the common
   local commands (who are you / what can you do / remember / recall /
   status / goals / time). No model tokens are spent on these.
2. DEEP FIELD — the model may emit exactly one tool-call line
   (``[[TOOL:<name>|<argument>]]``); the router validates the name against
   the registry and executes it, then the runtime asks the model for the
   final response with the real tool result. Unknown tool names are reported
   honestly — never silently executed, never advertised as available.
"""

import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from zerion.identity.invariants import check_invariants

# Model tool-call contract: one line, validated against the real registry.
_TOOL_CALL_RE = re.compile(
    r"\[\[\s*TOOL\s*:\s*([A-Za-z0-9_\-]+)\s*(?:\|\s*(.*?))?\s*\]\]",
    re.IGNORECASE | re.DOTALL)

_MEMORY_STORE_RE = re.compile(
    r"^(?:(?:please\s+)?(?:remember|memorize|note that|store this|save that)"
    r"[\s:,]+(.+)$"
    r"|(?:my\s+(?:name\s+is|name\s*=)\s+)(.+)$"
    r"|(?:call\s+me\s+)(.+)$"
    r"|(?:i\s+am\s+)(\S+)\s+(?:re\w*|mem\w*|note|save|store|pls|plz).*$"
    r"|(?:my\s+name\s+is\s+)(.+?)\s+(?:remember|note|save|store)"
    r"|(?:remember\s+that\s+)(.+)$"
    r"|(?:remember\s+)(?!to\b)(.+)$"
    r"|(?:my\s+name\s+is\s+)(.+?)\s*,?\s*$)"
    r"|(?:(\w+)\s+is\s+my\s+(\w+)\s*$)"
    r"|(?:my\s+(?!name\s+is)(.+?)\s+is\s+)(.+)$"
    r"|(?:i\s+(?:like|love|hate|prefer|enjoy|want|need)\s+)(.+)$"
    r"|(?:the\s+(.+?)\s+is\s+)(.+)$"
    r"|(?:(\w+)\s+is\s+)(?!my\b)(.+)$"
    r"|(?:(\w+)\s+uses\s+)(.+)$"
    r"|(?:(\w+)\s+does\s+)(.+)$"
    r"|(?:(\w+)\s+can\s+)(.+)$"
    r"|(?:(\w+)\s+controls\s+)(.+)$"
    r"|(?:(\w+)\s+runs\s+)(.+)$"
    r"|(?:(\w+)\s+means\s+)(.+)$"
    r"|(?:(\w+)\s+has\s+)(.+)$"
    r"|(?:(\w+)\s+stands\s+for\s+)(.+)$"
    r"|(?:(\w+)\s+called\s+)(.+)$"
    r"|(?:\w+\s+\w+\s+is\s+)(?!my\b)(.+)$"
    r"|(?:\S+\s+is\s+a\s+)(.+)$"
    r"|(?:\S+\s+is\s+an\s+)(.+)$"
    r"|(?:\w+\s+\w+\s+are\s+)(?!you)(.+)$"
    r"|(?:\w+\s+\w+\s+have\s+)(.+)$"
    r"|(?:\w+\s+\w+\s+use\s+)(.+)$"
    r"|(?:\w+\s+\w+\s+means\s+)(.+)$"
    r"|(?:\w+\s+\w+\s+means\s+that\s+)(.+)$"
    r"|(?:\w+\s+\w+\s+supports\s+)(.+)$"
    r"|(?:\w+\s+\w+\s+implements\s+)(.+)$"
    r"|(?:\w+\s+\w+\s+follows\s+)(.+)$"
    r"|(?:\S+\s+\+\+\s+is\s+)(?!my\b)(.+)$"
    r"|(?:(\S+)\s+is\s+my\s+(.+)\s*$)"
    r"|(?:I\s+learned\s+that\s+)(.+)$"
    r"|(?:learn\s+)(.+)$"
    r"|(?:study\s+)(.+)$"
    r"|(?:understand\s+)(.+)$"
    r"|(?:classify\s+by\s+)(.+)$"
    r"|(?:the\s+user\s+thinks\s+)(.+)$"
    r"|(?:\w+\s+\w+\s+use\s+)(.+)$"
    r"|(?:\w+\s+supports\s+)(.+)$"
    r"|(?:\w+\s+are\s+)(?!you)(.+)$"
    r"|(?:\w+\s+means\s+that\s+)(.+)$"
    r"|(?:\w+\s+have\s+)(.+)$"
    r"|(?:\w+\s+use\s+)(.+)$"
    r"|(?:\w+\s+implement\s+)(.+)$"
    r"|(?:\w+\s+follow\s+)(.+)$", re.IGNORECASE)

# FORGET: "forget X", "remove X", "delete X", "clear X"
_MEMORY_FORGET_RE = re.compile(
    r"^(?:forget|remove|delete|clear|erase|wipe)\s+(?:about\s+|what\s+(?:i\s+)?(?:told|said|taught)\s+you\s+(?:about\s+)?)?(.+)$",
    re.IGNORECASE)

# CORRECTION: "actually X is Y", "no X is Y", "correct X to Y", "I meant Y"
_MEMORY_CORRECT_RE = re.compile(
    r"^(?:actually|no[,.]?\s*|wrong[,.]?\s*|correction[,:]\s*|i\s+meant\s+|it'?s\s+(?:actually\s+)?|change\s+(?:it\s+to|to)\s+|replace\s+.+\s+with\s+)(.+)$",
    re.IGNORECASE)

_MEMORY_RECALL_RE = re.compile(
    r"^(?:what do you remember about|recall|what do you know about|"
    r"what did i (?:ask|say|tell you) about|search memory for|"
    r"what is my name|whats? my name|do you remember me|"
    r"what did i tell you about|what did i teach you|what did i learn you|do you know who i am|"
    r"do you know my name|tell me my name|"
    r"do you remember my name|what.s my name|what is my (\w+)|what.s my (\w+)|do i (?:like|love|hate|prefer|enjoy|want|need) (\w+)|tell me about my (.+)|what do i (?:like|love|hate|prefer|enjoy|want|need)|"
    r"what does (\w+) (?:do|mean|stand for)\??|"
    r"what (\w+) is (\w+)\??|"
    r"how (?:do you |to |can you )?(.+?)\??|"
    r"where (?:does|do|is|are|can) (.+?)\??|"
    r"when (?:does|do|is|are|was|were) (.+?)\??|"
    r"why (?:does|do|is|are|was|were) (.+?)\??|"
    r"explain (.+)|"
    r"describe (.+)|"
    r"teach me (.+)|"
    r"what have i (?:taught|told|shared|learned)|what did you learn|what do you know|what have you learned|tell me what you know|"
    r"how does (\w+) work\??|"
    r"how do (\w+) work\??|"
    r"can you (?:explain|teach|tell me about) (.+?)\??|"
    r"what (.+?) does (\w+) use\??"
    r")[\s:,]*(.*)$", re.IGNORECASE)


class ToolResult:
    """Structured outcome of one real tool execution."""

    def __init__(self, *, ok: bool, output: str,
                 tool: str, error: Optional[str] = None,
                 detail: Optional[Dict[str, Any]] = None):
        self.ok = ok
        self.output = output
        self.tool = tool
        self.error = error
        self.detail = detail or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "output": self.output, "tool": self.tool,
                "error": self.error, "detail": self.detail}


class ZerionTool:
    def __init__(self, name: str, description: str,
                 handler: Callable[[str, "ZerionToolRouter"], ToolResult]):
        self.name = name
        self.description = description
        self.handler = handler


class ZerionToolRouter:
    """Real, registry-backed tool execution for the live conversation loop."""

    def __init__(self, runtime: Any, *, identity: Optional[Any] = None,
                 self_model: Optional[Any] = None,
                 readiness: Optional[Callable[[], Dict[str, Any]]] = None):
        self.runtime = runtime
        self.identity = identity
        self.self_model = self_model
        self.readiness = readiness
        self._tools: Dict[str, ZerionTool] = {}
        self._register_defaults()

    # -- registry ----------------------------------------------------------

    def _register(self, tool: ZerionTool) -> None:
        self._tools[tool.name] = tool

    def _register_defaults(self) -> None:
        self._register(ZerionTool(
            "greeting", "friendly greeting when the user says hello/hi",
            self._tool_greeting))
        self._register(ZerionTool(
            "identity", "report who ZERION is (identity, mission, state)",
            self._tool_identity))
        self._register(ZerionTool(
            "capabilities", "list the capabilities ZERION can actually execute",
            self._tool_capabilities))
        self._register(ZerionTool(
            "memory_store", "store a fact or instruction the user asked ZERION to remember",
            self._tool_memory_store))
        self._register(ZerionTool(
            "memory_recall", "retrieve stored memory relevant to a topic",
            self._tool_memory_recall))
        self._register(ZerionTool(
            "memory_forget", "forget or remove a previously stored memory",
            self._tool_memory_forget))
        self._register(ZerionTool(
            "memory_correct", "correct previously stored information",
            self._tool_memory_correct))
        self._register(ZerionTool(
            "status", "report real runtime readiness (model/STT/TTS)",
            self._tool_status))
        self._register(ZerionTool(
            "goals", "list active long-term objectives",
            self._tool_goals))
        self._register(ZerionTool(
            "time", "report the current date and time",
            self._tool_time))

    def names(self) -> List[str]:
        return sorted(self._tools)

    def describe_pairs(self) -> List[Dict[str, str]]:
        """(name, description) pairs for the identity context — the ONLY
        tool list the model ever sees (never invented)."""
        return [{"name": t.name, "description": t.description}
                for t in sorted(self._tools.values(),
                                key=lambda t: t.name)]

    def describe(self, max_chars: int = 700) -> str:
        lines = [f"- {t.name}: {t.description}"
                 for t in self._tools.values()]
        text = "\n".join(lines)
        if len(text) > max_chars:
            return text[:max_chars].rstrip() + "\n[...]"
        return text

    # -- FAST FIELD: deterministic intent detection -------------------------

    def detect(self, user_text: str) -> Optional[str]:
        """Map common user requests to a real tool WITHOUT spending model
        tokens. Returns the tool name or None (defer to the model)."""
        low = (user_text or "").strip().lower()
        if not low:
            return None
        # Word-boundary greeting detection: 'hi' must not match inside 'this'
        _greet_words = {"hello", "hi", "hey", "greetings", "howdy", "sup", "yo"}
        words = set(low.split())
        if words & _greet_words and len(words) <= 2:
            return "greeting"
        # Check recall before store — 'what is my name' must not match store
        if _MEMORY_RECALL_RE.match(low):
            return "memory_recall"
        # Specific tool checks BEFORE broad store patterns — prevents
        # 'what can you do?' from matching the broad 'X can Y' store pattern
        if any(q in low for q in ("who are you", "who are u", "what are you",
                                  "your name", "introduce yourself")):
            return "identity"
        if any(q in low for q in ("what can you do", "what can u do",
                                  "what u can do", "what u can you do",
                                  "what are your capabilities",
                                  "what capabilities do you have",
                                  "list your capabilities")):
            return "capabilities"
        if any(q in low for q in ("status", "readiness", "health check",
                                  "are you ready", "system status")):
            return "status"
        if any(q in low for q in ("your goals", "active objectives",
                                  "what are you working on",
                                  "current objectives")):
            return "goals"
        if any(q in low for q in ("what time", "current time", "the time is",
                                  "what is the date")):
            return "time"
        # Store patterns last — they are broad and should not intercept
        # specific tool requests or questions meant for the model.
        # Guard: skip store for questions starting with question words
        _qwords = {"what", "how", "where", "why", "who", "which"}
        if low.split()[0] in _qwords:
            return None
        # Check forget before store
        if _MEMORY_FORGET_RE.match(low):
            return "memory_forget"
        # Check correction before store
        if _MEMORY_CORRECT_RE.match(low):
            return "memory_correct"
        if _MEMORY_STORE_RE.match(low):
            return "memory_store"
        return None

    # -- DEEP FIELD: model-requested tool call ------------------------------

    def parse_model_tool_call(self, text: str) -> Optional[Tuple[str, str]]:
        """Extract exactly one ``[[TOOL:name|arg]]`` call from model output.
        Returns None when no call is present (plain text = normal response)."""
        m = _TOOL_CALL_RE.search(text or "")
        if m is None:
            return None
        name = m.group(1).strip().lower()
        arg = (m.group(2) or "").strip()
        if name not in self._tools:
            return None  # unknown tools are never executed
        return name, arg

    # -- execution ----------------------------------------------------------

    async def execute(self, name: str, user_text: str,
                      argument: str = "") -> ToolResult:
        """Execute a real tool behind the constitution gate. Every execution
        is validated against the invariants first; a denial is returned, never
        silently bypassed."""
        name = (name or "").strip().lower()
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                ok=False, tool=name or "unknown",
                output="",
                error=f"tool '{name}' is not registered — never advertised, "
                      f"never executed")
        # Constitution gate: INV-001..INV-010 enforcement seam for tools.
        allowed, reason = check_invariants(
            f"tool_{name}", {"user_request": (user_text or "")[:200]})
        if not allowed:
            return ToolResult(
                ok=False, tool=name, output="",
                error=f"constitution gate denied tool '{name}': {reason}")
        try:
            # Memory tools extract their fact/query from the verb phrase so
            # "remember X" stores X (not "remember X").
            if not argument and name in ("memory_store", "memory_recall",
                                          "memory_forget", "memory_correct"):
                low = (user_text or "").strip()
                if name == "memory_store":
                    m = _MEMORY_STORE_RE.match(low)
                elif name == "memory_forget":
                    m = _MEMORY_FORGET_RE.match(low)
                elif name == "memory_correct":
                    m = _MEMORY_CORRECT_RE.match(low)
                else:
                    m = _MEMORY_RECALL_RE.match(low)
                if m is not None:
                    # Find the first non-None capture group — patterns
                    # beyond group 1 still need their captured value.
                    argument = next(
                        (g for g in m.groups() if g is not None), ""
                    ).strip()
                    # If extracted argument is just punctuation or too short,
                    # use the raw user text instead — the handler will
                    # clean it up.
                    if len(argument) < 3:
                        argument = ""
            result = tool.handler(argument or user_text, self)
            return result
        except Exception as exc:  # noqa: BLE001 — honest structured failure
            return ToolResult(
                ok=False, tool=name, output="",
                error=f"{type(exc).__name__}: {str(exc)[:200]}")

    # -- real local tools ---------------------------------------------------

    def _tool_greeting(self, _arg: str, _router) -> ToolResult:
        return ToolResult(
            ok=True, tool="greeting",
            output="Hello! I am ZERION, your autonomous cognitive assistant. "
                   "I run entirely on your local device with no cloud connection. "
                   "How can I help you today?")

    def _tool_identity(self, _arg: str, _router) -> ToolResult:
        try:
            name = str(getattr(self.identity, "system_name", None) or "ZERION")
        except Exception:  # noqa: BLE001
            name = "ZERION"
        try:
            sys_id = str(getattr(self.identity, "system_id", "") or "")
        except Exception:  # noqa: BLE001
            sys_id = ""
        inv = 0
        try:
            inv = len(getattr(self.identity, "invariants", None) or [])
        except Exception:  # noqa: BLE001
            inv = 0
        out = (f"I am {name}, an autonomous developmental cognitive system. "
               f"My mission is continuous autonomous problem discovery, "
               f"empirical reality learning, and measured self-improvement "
               f"within safe invariants ({inv} constitutional invariants "
               f"active).")
        if sys_id:
            out += f" System id: {sys_id}."
        return ToolResult(ok=True, tool="identity", output=out)

    def _tool_capabilities(self, _arg: str, _router) -> ToolResult:
        caps = self._capability_names()
        if not caps:
            return ToolResult(
                ok=False, tool="capabilities",
                output="",
                error="capability registry is empty — no capability can be "
                      "claimed or executed")
        return ToolResult(
            ok=True, tool="capabilities",
            output="I can execute these capabilities from my real registry: "
                   + ", ".join(caps) + ".")

    def _capability_names(self) -> List[str]:
        caps: List[str] = []
        try:
            registry = getattr(self.runtime, "capability_registry", None)
            if registry is not None:
                for cap in registry.list():
                    name = str(getattr(cap, "name", "") or "")
                    if name and name not in caps:
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
        return caps

    def _tool_memory_store(self, arg: str, _router) -> ToolResult:
        fact = (arg or "").strip()
        if not fact:
            return ToolResult(ok=False, tool="memory_store", output="",
                              error="nothing to remember (empty argument)")
        episode_store = getattr(self.runtime, "episode_store", None)
        if episode_store is None:
            return ToolResult(ok=False, tool="memory_store", output="",
                              error="episode store unavailable — cannot "
                                    "persist memory")
        from zerion.cognitive_os.episode import (
            EpisodeMode,
            EpisodeStatus,
            ExperienceEpisode,
        )
        # Store the fact cleanly as knowledge — the fact IS the knowledge,
        # not a sentence about the user asking to store it.
        episode = ExperienceEpisode(
            context=f"knowledge: {fact[:500]}",
            mode=EpisodeMode.OBSERVED,
            status=EpisodeStatus.COMPLETED,
            success=True,
            actions=[{"action": "memory_store", "detail": fact[:500]}],
            outcomes=[{"outcome": "knowledge_stored",
                       "detail": fact[:500]}],
            capabilities_used=["memory_store"],
        )
        stored = episode_store.put(episode)
        return ToolResult(
            ok=True, tool="memory_store",
            output=f"Learned: {fact}")

    def _tool_memory_recall(self, arg: str, _router) -> ToolResult:
        query = (arg or "").strip().rstrip("?!.,;:")
        if not query:
            # Empty query (e.g. "what is my name?") — search for
            # personal/user-identity memories broadly.
            query = "name user remember"
        hits: List[str] = []
        try:
            reuse = getattr(self.runtime, "experience_reuse", None)
            if reuse is not None:
                for hit in reuse.retrieve(context=query, top_k=5):
                    statement = str(hit.get("statement", "") or "")
                    if statement:
                        hits.append(statement[:300])
        except Exception:  # noqa: BLE001
            pass
        try:
            episode_store = getattr(self.runtime, "episode_store", None)
            if episode_store is not None:
                q_words = set(re.findall(r"[a-z0-9_]+", query.lower()))
                for ep in episode_store.list()[-50:]:
                    context = str(getattr(ep, "context", "") or "")
                    # Extract the knowledge from "knowledge: X" format
                    fact = context
                    if fact.startswith("knowledge: "):
                        fact = fact[len("knowledge: "):]
                    ep_words = set(re.findall(r"[a-z0-9_]+", fact.lower()))
                    shared = ep_words & q_words
                    _STOP = {"the", "is", "am", "are", "do", "you",
                             "my", "to", "a", "an", "in", "on", "it",
                             "that", "this", "of", "for", "was", "has",
                             "have", "can", "with", "from", "not", "but"}
                    meaningful = shared - _STOP
                    if meaningful:
                        hits.append(fact[:300])
        except Exception:  # noqa: BLE001
            pass
        seen = []
        for h in hits:
            if h not in seen:
                seen.append(h)
        if not seen:
            return ToolResult(
                ok=True, tool="memory_recall",
                output=(f"I have no stored memory matching \"{query}\". "
                        f"I can store things you ask me to remember."))
        # Return the facts directly — the model will extract the answer
        return ToolResult(
            ok=True, tool="memory_recall",
            output="\n".join(seen))

    def _tool_memory_forget(self, arg: str, _router) -> ToolResult:
        query = (arg or "").strip()
        if not query:
            return ToolResult(ok=False, tool="memory_forget", output="",
                              error="nothing to forget (empty argument)")
        episode_store = getattr(self.runtime, "episode_store", None)
        if episode_store is None:
            return ToolResult(ok=False, tool="memory_forget", output="",
                              error="episode store unavailable")
        q_words = set(re.findall(r"[a-z0-9_]+", query.lower()))
        removed = 0
        for ep in list(episode_store.list()):
            context = str(getattr(ep, "context", "") or "")
            fact = context
            if fact.startswith("knowledge: "):
                fact = fact[len("knowledge: "):]
            ep_words = set(re.findall(r"[a-z0-9_]+", fact.lower()))
            shared = ep_words & q_words
            _STOP = {"the", "is", "am", "are", "do", "you",
                     "my", "to", "a", "an", "in", "on", "it"}
            if shared - _STOP:
                episode_store._episodes.pop(ep.episode_id, None)
                # Also remove from SQLite
                try:
                    import sqlite3 as _sqlite3
                    conn = _sqlite3.connect(episode_store.db_path)
                    conn.execute("DELETE FROM episodes WHERE episode_id=?",
                                 (ep.episode_id,))
                    conn.commit()
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                removed += 1
        if removed == 0:
            return ToolResult(
                ok=True, tool="memory_forget",
                output=f"I don't have any stored memory about \"{query}\".")
        return ToolResult(
            ok=True, tool="memory_forget",
            output=f"Forgot {removed} item(s) about \"{query}\".")

    def _tool_memory_correct(self, arg: str, _router) -> ToolResult:
        correction = (arg or "").strip()
        if not correction:
            return ToolResult(ok=False, tool="memory_correct", output="",
                              error="nothing to correct (empty argument)")
        episode_store = getattr(self.runtime, "episode_store", None)
        if episode_store is None:
            return ToolResult(ok=False, tool="memory_correct", output="",
                              error="episode store unavailable")
        from zerion.cognitive_os.episode import (
            EpisodeMode,
            EpisodeStatus,
            ExperienceEpisode,
        )
        # Try to find and remove superseded old facts about the same topic.
        # Extract topic words from the correction to find related old episodes.
        _STOP = {"the", "is", "am", "are", "do", "you",
                 "my", "to", "a", "an", "in", "on", "it",
                 "that", "this", "of", "for", "was", "has",
                 "have", "can", "with", "from", "not", "but",
                 "actually", "no", "wrong", "correct", "meant",
                 "its", "its", "change", "replace", "with"}
        correction_words = set(
            re.findall(r"[a-z0-9_]+", correction.lower())) - _STOP
        removed = 0
        for ep in list(episode_store.list()):
            context = str(getattr(ep, "context", "") or "")
            fact = context
            if fact.startswith("knowledge: "):
                fact = fact[len("knowledge: "):]
            fact_words = set(re.findall(r"[a-z0-9_]+", fact.lower()))
            shared = fact_words & correction_words
            meaningful = shared - _STOP
            # If the old fact shares key topic words with the correction,
            # it is likely superseded — remove it.
            if meaningful and any(len(w) > 2 for w in meaningful):
                episode_store._episodes.pop(ep.episode_id, None)
                try:
                    import sqlite3 as _sqlite3
                    conn = _sqlite3.connect(episode_store.db_path)
                    conn.execute("DELETE FROM episodes WHERE episode_id=?",
                                 (ep.episode_id,))
                    conn.commit()
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
                removed += 1
        # Store the correction as new knowledge
        episode = ExperienceEpisode(
            context=f"knowledge: {correction[:500]}",
            mode=EpisodeMode.OBSERVED,
            status=EpisodeStatus.COMPLETED,
            success=True,
            actions=[{"action": "memory_correct", "detail": correction[:500]}],
            outcomes=[{"outcome": "corrected", "detail": correction[:500]}],
            capabilities_used=["memory_correct"],
        )
        episode_store.put(episode)
        if removed:
            return ToolResult(
                ok=True, tool="memory_correct",
                output=f"Updated: {correction} (replaced {removed} old version(s))")
        return ToolResult(
            ok=True, tool="memory_correct",
            output=f"Updated: {correction}")

    def _tool_status(self, _arg: str, _router) -> ToolResult:
        if self.readiness is not None:
            try:
                r = self.readiness()
                models = r.get("models") or {}
                stt = r.get("stt") or {}
                tts = r.get("tts") or {}
                mic = r.get("microphone") or {}
                out = (f"Runtime status: model={models.get('status', 'UNKNOWN')} "
                       f"({models.get('probe', {}).get('inference', 'NOT_VERIFIED')}), "
                       f"stt={stt.get('display_status') or stt.get('status', 'UNKNOWN')}, "
                       f"tts={tts.get('status', 'UNKNOWN')}, "
                       f"mic={mic.get('status', 'UNKNOWN')}.")
                return ToolResult(ok=True, tool="status", output=out)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, tool="status", output="",
                                  error=f"readiness probe failed: {exc}")
        models = self._model_line()
        return ToolResult(ok=True, tool="status",
                          output=f"Local model state: {models or 'no model'}.")

    def _model_line(self) -> str:
        try:
            discovery = getattr(self.runtime, "local_models", None)
            if discovery is None:
                return ""
            available = discovery.available()
            if not available:
                return "no local model loaded"
            return ", ".join(sorted(
                str(getattr(m, "model_id", "") or "") for m in available[:3]))
        except Exception:  # noqa: BLE001
            return ""

    def _tool_goals(self, _arg: str, _router) -> ToolResult:
        try:
            objectives = getattr(self.runtime, "objectives", None)
            if objectives is None:
                return ToolResult(ok=False, tool="goals", output="",
                                  error="objective store unavailable")
            goals = objectives.list_active_objectives()
            if not goals:
                return ToolResult(ok=True, tool="goals",
                                  output="No active objectives right now.")
            lines = [f"- {getattr(g, 'title', '')}" for g in goals[:8]]
            return ToolResult(ok=True, tool="goals",
                              output="Active objectives:\n" + "\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, tool="goals", output="",
                              error=f"goal lookup failed: {exc}")

    def _tool_time(self, _arg: str, _router) -> ToolResult:
        now = datetime.now()
        return ToolResult(
            ok=True, tool="time",
            output=now.strftime("It is %A, %B %d, %Y at %H:%M (%Z).")
            if now.tzinfo else
            now.strftime("It is %A, %B %d, %Y at %H:%M."))
