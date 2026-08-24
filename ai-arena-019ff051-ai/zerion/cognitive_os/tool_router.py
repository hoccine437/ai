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
    # ONLY intentional fact statements. Normal conversation ("X can Y",
    # "X has Y", "the X is Y", "explain X"...) must NEVER be hijacked into
    # memory writes — it belongs to Gemini.
    r"^(?:(?:please\s+)?(?:remember|memorize|note that|store this|save that)"
    r"[\s:,]+(.+)$"
    r"|(?:my\s+name\s+is\s+)(.+)$"
    r"|(?:i\s+am\s+called\s+)(.+)$"
    r"|(?:call\s+me\s+)(.+)$"
    r"|(?:my\s+name\s+is\s+)(.+?)\s+(?:remember|note|save|store)"
    r"|(?:remember\s+that\s+)(.+)$"
    r"|(?:remember\s+)(?!to\b|that\b|me\b|when\b|how\b|what\b|why\b|where\b|who\b)(.+)$"
    r"|(?:my\s+(?!name\s+is)(.+?)\s+is\s+)(.+)$"
    r"|(?:(\S+)\s+is\s+my\s+(.+)\s*$)"
    r"|(?:i\s+(?:like|love|hate|prefer|enjoy)\s+)(.+)$"
    # Explicit learning commands — "learn X" / "study X" / Arabic تعلّم.
    # Imperative-only (optionally preceded by short imperative lead-ins like
    # "good now learn ...", "just learn ...") so normal chat is never hijacked.
    r"|(?:(?:ok|okay|good|great|nice|well|now|then|please|just|and)\s+){0,4}"
    r"(?:learn\s+)(?!me\b|you\b)(.+)$"
    r"|(?:(?:ok|okay|good|great|nice|well|now|then|please|just|and)\s+){0,4}"
    r"(?:study\s+)(.+)$"
    r"|(?:تعلّم|تعلم)\s*(?:أن|ان|عن)?\s*(.+)$"
    # Arabic / Darija: احفظ / تذكر / سجّل (remember/save), اسمي (my name is)
    r"|(?:احفظ|تذكر|سجّل|سجل)\s*(?:أن|ان|هذا|هذه|ذلك)?\s*[:،,]?\s*(.+)$"
    r"|(?:انا|أنا)?\s*اسمي\s+(.+)$"
    ")", re.IGNORECASE | re.UNICODE)

# FORGET: "forget X", "remove X", "delete X", "clear X"
_MEMORY_FORGET_RE = re.compile(
    r"^(?:forget|remove|delete|clear|erase|wipe)\s+(?:about\s+|what\s+(?:i\s+)?(?:told|said|taught)\s+you\s+(?:about\s+)?)?(.+)$",
    re.IGNORECASE)

# CORRECTION: "actually X is Y", "no X is Y", "correct X to Y", "I meant Y"
_MEMORY_CORRECT_RE = re.compile(
    r"^(?:actually|no(?![a-z])[,.!]?\s*|wrong(?![a-z])[,.!]?\s*|correction[,:]\s*|i\s+meant\s+|it'?s\s+(?:actually\s+)?|change\s+(?:it\s+to|to)\s+|replace\s+.+\s+with\s+)(.+)$",
    re.IGNORECASE)

_MEMORY_RECALL_RE = re.compile(
    # Only genuine recall intents. Questions like "how does X work",
    # "explain X", "where/why/when ..." are CONVERSATION for Gemini — they
    # must never be intercepted as memory lookups.
    r"^(?:what do you remember about|recall|search memory for|"
    r"what did i (?:ask|say|tell you|teach you) about|"
    r"what is my name|whats? my name|what.s my name|do you remember me|"
    r"do you know who i am|do you know my name|tell me my name|"
    r"who am i\??|من أنا|من انا|مين انا|واش اسمي|واش سميتي|شو اسمي|شنو اسمي|ما اسمي|ماذا تعرف عني|هل تذكرني"
    r"|"
    r"what is my (.+)|what.s my (.+)|whats my (.+)|"
    r"do i (?:like|love|hate|prefer|enjoy) (.+)|"
    r"tell me about my (.+)|what do i (?:like|love|hate|prefer|enjoy)|"
    r"what have i (?:taught|told|shared|learned)|what did you learn|"
    r"what do you know about me|what do you remember|tell me what you know"
    r")[\s:?!,]*(.*)$", re.IGNORECASE | re.UNICODE)


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
            "greeting", "report current time period and active objectives "
            "(context data for composing greetings - not a reply)",
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
        # NOTE: greetings are CONVERSATION — they must go through Gemini
        # (architecture rule: no canned/hardcoded conversational replies).
        # The greeting tool stays registered as a real data tool (clock +
        # objectives introspection) but is never auto-selected for chat.
        # Check recall before store — 'what is my name' must not match store
        if _MEMORY_RECALL_RE.match(low):
            return "memory_recall"
        # Contextual recall: "what preference did I ask you to remember?"
        if re.search(r"\bwhat\b.*\b(remember|told|said|ask)\b", low):
            return "memory_recall"
        # "tell me what u learn(ed) about X", "show me what you know about Y"
        if re.search(r"\b(tell|show)\b(?:\s+\w+){0,3}\s+what\b"
                     r".*\b(learn|learned|learnt|know)\b", low):
            return "memory_recall"
        # "what did I ask you to learn?"
        if re.search(r"\bwhat\b.*\b(?:did|do)\s+i\b.*\blearn\b", low):
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
            # Memory tools receive the FULL utterance and parse it inside the
            # handler. (The old first-non-None-group extraction stored only
            # "nickname" for "my nickname is nano808".)
            result = tool.handler(argument or user_text, self)
            return result
        except Exception as exc:  # noqa: BLE001 — honest structured failure
            return ToolResult(
                ok=False, tool=name, output="",
                error=f"{type(exc).__name__}: {str(exc)[:200]}")

    # -- real local tools ---------------------------------------------------

    def _tool_greeting(self, _arg: str, _router) -> ToolResult:
        # Real data only: current time period and live runtime state.
        # NEVER fabricates a conversational reply (that is Gemini's job).
        from datetime import datetime
        hour = datetime.now().hour
        if hour < 6:
            period = "night"
        elif hour < 12:
            period = "morning"
        elif hour < 18:
            period = "afternoon"
        else:
            period = "evening"
        try:
            obj = getattr(_router.runtime, "objectives", None)
            active = len(obj.list_active_objectives()) if obj else 0
        except Exception:  # noqa: BLE001
            active = 0
        return ToolResult(
            ok=True, tool="greeting",
            output=f"time_period={period} local_hour={hour} "
                   f"active_objectives={active}")

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
        # Also include agent and tool counts for full picture
        agent_count = 0
        tool_count = 0
        try:
            reg = getattr(_router.runtime, "agent_registry", None)
            if reg:
                agent_count = reg.count()
        except Exception:  # noqa: BLE001
            pass
        try:
            tr = getattr(_router.runtime, "master_tools", None)
            if tr:
                tool_count = tr.count()
        except Exception:  # noqa: BLE001
            pass
        parts = []
        if caps:
            parts.append("Core capabilities: " + ", ".join(caps))
        if agent_count:
            parts.append(f"Specialized agents: {agent_count}")
        if tool_count:
            parts.append(f"Real tools: {tool_count}")
        if not parts:
            return ToolResult(
                ok=False, tool="capabilities",
                output="",
                error="no capabilities registered")
        return ToolResult(
            ok=True, tool="capabilities",
            output="I have: " + ". ".join(parts) + ".")

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

    _IMPERATIVE_RE = re.compile(
        r"^(?:please\s+)?(?:remember|memorize|note(?:\s+that)?|save|store)"
        r"(?:\s+(?:this|that))?\s*[:,]?\s*(.+)$", re.IGNORECASE)

    def _parse_user_fact(self, text: str) -> str:
        """Parse a raw user utterance into a canonical, storable fact.

        "my nickname is nano808"  -> "nickname: nano808"
        "nano808 is my nickname"  -> "nickname: nano808"
        "call me nano"            -> "name: nano"
        "remember it"             -> resolved from conversation history
        "X is Y"                  -> "x: y"
        "remember it" resolves the REFERENCE — the literal command is never
        stored."""
        low = (text or "").strip()
        if not low:
            return ""
        m = self._IMPERATIVE_RE.match(low)
        if m and m.group(1).strip():
            low = m.group(1).strip().rstrip(".?!").strip()
        # Strip a trailing imperative tail FIRST: "my name is nono888
        # remember it" -> parse "my name is nono888" (the tail must never
        # discard the fact it follows).
        stripped = re.sub(
            r"[\s,.]*\b(?:remember|save|store|memorize)\s+"
            r"(?:it|this|that|them|all)\b[\s.!]*$",
            "", low, flags=re.IGNORECASE).strip()
        if stripped:
            low = stripped
        low_l = low.lower().rstrip(".?! \u060c").strip()
        if low_l in {"it", "this", "that", "them", "those", "the previous",
                     "the last thing", "what i said", "my nickname",
                     "remember it", "save it", "don't forget it",
                     # Arabic/Darija references: ه/ها/هم (it/them), ذلك، هذا
                     "ه", "هـ", "ها", "هم", "هذا", "هذه", "ذلك"} or \
                low_l == "":
            resolved = self._resolve_pronoun(low_l or "it")
            return resolved or ""
        # Arabic / Darija patterns FIRST (matched on the original text so
        # Arabic names keep their exact spelling).
        m = re.match(r"^(?:تعلّم|تعلم)\s*(?:أن|ان|عن)?\s*(.+)$", low)
        if m and m.group(1).strip():
            rest = m.group(1).strip().rstrip(".?!").strip()
            if rest.lower() in {"it", "this", "that", "ه", "ها", "هذا",
                                "هذه", "ذلك"} or not rest:
                resolved = self._resolve_pronoun("it")
                return resolved or ""
            return f"wants to learn: {rest}"
        m = re.match(
            r"^(?:(?:ok|okay|good|great|nice|well|now|then|please|just|and)"
            r"\s+){0,4}(?:learn|study)\s+(?:about\s+)?(.+)$", low,
            re.IGNORECASE)
        if m and m.group(1).strip():
            rest = m.group(1).strip().rstrip(".?!").strip()
            if rest.lower() in {"it", "this", "that", "them", "those",
                                "the previous", "what i said"} or not rest:
                resolved = self._resolve_pronoun("it")
                return resolved or ""
            return f"wants to learn: {rest}"
        m = re.match(r"^(?:انا|أنا)?\s*اسمي\s+(.+)$", low)
        if m and m.group(1).strip():
            return f"name: {m.group(1).strip().rstrip('.?!')}"
        m = re.match(
            r"^(?:احفظ|تذكر|سجّل|سجل)\s*(?:أن|ان)?\s*[:،,]?\s*(.+)$", low)
        if m and m.group(1).strip():
            rest = m.group(1).strip().rstrip(".?!").strip()
            return self._parse_user_fact(rest) or rest
        # Case-preserving semantic patterns (matched on the ORIGINAL text so
        # values like "NEXUS" or "nano808" keep their casing).
        m = re.match(r"^(?:my\s+name\s+is|i\s+am\s+called|call\s+me)\s+(.+)$",
                     low, re.IGNORECASE)
        if m:
            return f"name: {m.group(1).strip()}"
        m = re.match(r"^my\s+(.+?)\s+is\s+(.+)$", low, re.IGNORECASE)
        if m:
            return f"{m.group(1).strip()}: {m.group(2).strip()}"
        m = re.match(r"^(.+?)\s+is\s+my\s+(.+)$", low, re.IGNORECASE)
        if m:
            return f"{m.group(2).strip()}: {m.group(1).strip()}"
        m = re.match(r"^i\s+(like|love|hate|prefer|enjoy)\s+(.+)$", low,
                     re.IGNORECASE)
        if m:
            return f"{m.group(1).strip()}: {m.group(2).strip()}"
        m = re.match(r"^(.+?)\s+is\s+(.+)$", low, re.IGNORECASE)
        if m and m.group(1).strip().lower() not in (
                "what", "who", "it", "this", "that"):
            return f"{m.group(1).strip()}: {m.group(2).strip()}"
        return low

    def _tool_memory_store(self, arg: str, _router) -> ToolResult:
        fact = self._parse_user_fact(arg or "")
        if not fact:
            return ToolResult(ok=False, tool="memory_store", output="",
                              error="nothing to remember — the reference "
                                    "could not be resolved to a concrete fact")
        # Sanity guard: never store bare interjections / filler words
        # ("huh", "what", "ok"...) as knowledge.
        _INTERJECTIONS = {"huh", "what", "wat", "ok", "okay", "yes", "no",
                          "why", "lol", "hm", "hmm", "hmmm", "wow", "hey",
                          "hi", "hello", "thanks", "thank you", "please"}
        if " " not in fact.strip() and \
                fact.strip(".?!").strip().lower() in _INTERJECTIONS:
            return ToolResult(
                ok=False, tool="memory_store", output="",
                error=f"refusing to store \"{fact}\" — not a memorable fact")
        episode_store = getattr(self.runtime, "episode_store", None)
        if episode_store is None:
            return ToolResult(ok=False, tool="memory_store", output="",
                              error="episode store unavailable — cannot "
                                    "persist memory")
        # Resolve pronouns/reference: "remember it" -> the fact just stated.
        # (_parse_user_fact already did this; kept as a safety net.)
        pronouns = {"it", "this", "that", "them", "those", "remember it"}
        if fact.lower().strip() in pronouns:
            resolved = self._resolve_pronoun(fact.lower().strip())
            if resolved:
                fact = resolved
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
        # Dedupe: storing an identical fact twice must not pile up copies.
        fact_norm = " ".join(fact.lower().split())
        for ep in episode_store.list()[-200:]:
            ctx = str(getattr(ep, "context", "") or "")
            if ctx.startswith("knowledge: "):
                existing = " ".join(
                    ctx[len("knowledge: "):].strip().lower().split())
                if existing == fact_norm:
                    return ToolResult(
                        ok=True, tool="memory_store",
                        output=f"Already known: {fact}")
        stored = episode_store.put(episode)
        return ToolResult(
            ok=True, tool="memory_store",
            output=f"Learned: {fact}")

    def _resolve_pronoun(self, pronoun: str):
        """Resolve a pronoun/reference ("it", "that", ...) to the most recent
        concrete fact from the conversation. Returns a canonical fact string
        or None when nothing resolvable exists — never the literal command."""
        episode_store = getattr(self.runtime, "episode_store", None)
        if episode_store is None:
            return None
        recent = episode_store.list()[-10:]
        for ep in reversed(recent):
            ctx = str(getattr(ep, "context", "") or "")
            if ctx.startswith("knowledge: "):
                fact = ctx[len("knowledge: "):].strip()
                if fact and not fact.lower().startswith(
                        ("remember", "save", "store")):
                    return fact
                continue
            if "user message:" in ctx.lower():
                user_msg = ctx.split("user message:", 1)[-1].strip()
                parsed = self._parse_user_fact(user_msg)
                if parsed and parsed.lower() not in (
                        "it", "this", "that", "them", "those"):
                    return parsed
        return None

    def _lookup_key(self, key: str):
        """Look up a stored 'key: value' memory by key (e.g. 'nickname').
        Returns the value or None."""
        episode_store = getattr(self.runtime, "episode_store", None)
        if episode_store is None:
            return None
        norm = key.strip().lower().rstrip("?!. ")
        variants = {norm}
        # Loose morphological matches: plural/singular and common derivations
        # ("preferences" -> "prefer", "nickname" stays "nickname").
        for suf in ("s", "es", "ion", "ions", "ence", "ences", "ing", "ed"):
            if norm.endswith(suf) and len(norm) - len(suf) >= 4:
                variants.add(norm[: len(norm) - len(suf)])
        for ep in reversed(episode_store.list()[-100:]):
            ctx = str(getattr(ep, "context", "") or "")
            if not ctx.startswith("knowledge: "):
                continue
            fact = ctx[len("knowledge: "):].strip()
            if ":" not in fact:
                continue
            k, _, v = fact.partition(":")
            k_norm = k.strip().lower()
            if any(k_norm == v2 or k_norm.startswith(v2)
                   for v2 in variants if len(v2) >= 4):
                return v.strip()
        return None

    def _tool_memory_recall(self, arg: str, _router) -> ToolResult:
        raw = (arg or "").strip()
        query = raw.rstrip("?!.,;:")
        qlow = query.lower().strip()

        # Personal identity recall: "who am i" / "do you know who i am" /
        # Arabic "واش اسمي", "من انا", "ما اسمي" ... -> look up the name key.
        if re.search(
                r"(?:\bwho am i\b|\bdo you (?:know|remember)\s+(?:who i am"
                r"|my name|me)\b|\btell me my name\b"
                r"|من أنا|من انا|مين انا|مين أنا|واش اسمي|واش سميتي"
                r"|شو اسمي|شنو اسمي|ما اسمي|هل تذكرني)", qlow):
            val = self._lookup_key("name")
            if val:
                return ToolResult(
                    ok=True, tool="memory_recall",
                    output=f"You told me your name is {val}.")
            return ToolResult(
                ok=True, tool="memory_recall",
                output=("I don't know your name yet — tell me and "
                        "I'll remember it."))

        # Personal key lookup: "what is my nickname" -> "Your nickname is X."
        key_m = re.match(
            r"^(?:what\s+(?:is|are|was)|what's|whats)\s+(?:my|the)\s+(.+?)$",
            qlow)
        if not key_m:
            # Contextual phrasings: "what preference did I ask you to
            # remember?", "what did I tell you about my game?"
            ctx_m = re.search(
                r"what\s+(?:\w+\s+){0,3}?my\s+([\w\- ]*?)\b.*"
                r"(remember|tell|said|ask)", qlow)
            if not ctx_m:
                # "what <noun> did I (ask/tell you) ..." -> treat <noun> as key
                noun_m = re.match(r"^what\s+([\w\-]+)\s+did\b.*"
                                  r"(remember|tell|said|ask)", qlow)
                if noun_m:
                    ctx_m = noun_m
            if ctx_m:
                key_m = ctx_m
        if key_m:
            key = key_m.group(1).strip()
            val = self._lookup_key(key)
            if val:
                return ToolResult(
                    ok=True, tool="memory_recall",
                    output=f"You asked me to remember your {key}: {val}.")
            return ToolResult(
                ok=True, tool="memory_recall",
                output=(f"I don't have your {key} stored yet — "
                        f"tell me and I'll remember it."))

        if not query:
            # Empty query (e.g. "what do you remember?") — list knowledge.
            query = "knowledge"
        hits: List[str] = []
        fallback_hits: List[str] = []
        try:
            reuse = getattr(self.runtime, "experience_reuse", None)
            if reuse is not None:
                for hit in reuse.retrieve(context=query, top_k=5):
                    statement = str(hit.get("statement", "") or "")
                    if statement:
                        fallback_hits.append(statement[:300])
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
                    is_knowledge = fact.startswith("knowledge: ")
                    if is_knowledge:
                        fact = fact[len("knowledge: "):]
                    ep_words = set(re.findall(r"[a-z0-9_]+", fact.lower()))
                    shared = ep_words & q_words
                    _STOP = {"the", "is", "am", "are", "do", "you",
                             "my", "to", "a", "an", "in", "on", "it",
                             "that", "this", "of", "for", "was", "has",
                             "have", "can", "with", "from", "not", "but"}
                    meaningful = shared - _STOP
                    if not meaningful:
                        continue
                    if is_knowledge:
                        # Clean user facts always come first.
                        hits.append(fact[:300])
                    else:
                        # Raw conversation/lesson logs are a last resort —
                        # never dump them over real knowledge.
                        fallback_hits.append(fact[:300])
        except Exception:  # noqa: BLE001
            pass
        if not hits:
            hits = fallback_hits
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
                prov = r.get("provider") or {}
                if isinstance(prov, dict):
                    configured = prov.get("configured")
                    health = prov.get("health", "UNKNOWN")
                else:
                    configured, health = None, str(prov)
                state_txt = (f"provider=gemini health={health}"
                             + ("" if configured is None else
                                f" configured={configured}"))
                rt = r.get("runtime") or {}
                started = rt.get("started") if isinstance(rt, dict) else None
                out = (f"Runtime status: {state_txt}; running={started}. "
                       f"Input: text only (microphone removed). "
                       f"Gemini is the only provider.")
                return ToolResult(ok=True, tool="status", output=out)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, tool="status", output="",
                                  error=f"readiness probe failed: {exc}")
        return ToolResult(ok=True, tool="status",
                          output="Runtime status: provider=gemini (only provider); "
                                 "text input only.")

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
