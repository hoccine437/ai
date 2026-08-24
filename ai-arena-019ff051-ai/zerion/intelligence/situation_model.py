"""
SituationModel — Understands what is actually happening.

Instead of blindly processing user input, the SituationModel:
1. Parses the literal request
2. Identifies the underlying objective
3. Detects constraints and hidden dependencies
4. Determines if the stated problem IS the real problem
5. Builds a structured Situation object

This is the foundation of Zerion's intelligence — solving the right problem.
"""

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class IntentType(Enum):
    GREETING = "greeting"
    QUESTION = "question"
    PROBLEM_SOLVING = "problem_solving"
    CREATION = "creation"
    MODIFICATION = "modification"
    KNOWLEDGE_STORAGE = "knowledge_storage"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    KNOWLEDGE_FORGET = "knowledge_forget"
    KNOWLEDGE_CORRECTION = "knowledge_correction"
    STATUS_CHECK = "status_check"
    CAPABILITIES = "capabilities"
    IDENTITY = "identity"
    FEEDBACK = "feedback"
    CLARIFICATION = "clarification"
    COMMAND = "command"
    CONVERSATION = "conversation"


class ProblemType(Enum):
    FACTUAL = "factual"           # Direct answer exists
    DIAGNOSTIC = "diagnostic"     # Need to find root cause
    PROCEDURAL = "procedural"     # Need to execute steps
    CREATIVE = "creative"         # Need to generate something new
    ANALYTICAL = "analytical"     # Need to analyze data/situation
    STRATEGIC = "strategic"       # Need to plan approach
    EXPLORATORY = "exploratory"   # Need to investigate/learn
    REACTIVE = "reactive"         # Something went wrong, respond


class Complexity(Enum):
    TRIVIAL = 1    # Simple lookup or greeting
    SIMPLE = 2     # Single-step reasoning
    MODERATE = 3   # Multi-step, some uncertainty
    COMPLEX = 4    # Multiple competing factors
    HARD = 5       # Novel, uncertain, requires deep reasoning


class Urgency(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Situation:
    """Structured representation of the current situation."""
    # What the user literally said
    raw_input: str = ""

    # Classified intent
    intent: IntentType = IntentType.CONVERSATION

    # Type of problem
    problem_type: ProblemType = ProblemType.FACTUAL

    # Complexity assessment
    complexity: Complexity = Complexity.SIMPLE

    # Urgency assessment
    urgency: Urgency = Urgency.NORMAL

    # What the user ACTUALLY wants (reframed objective)
    underlying_objective: str = ""

    # What the user stated vs what they need
    stated_problem: str = ""
    real_problem: str = ""

    # Detected constraints
    constraints: List[str] = field(default_factory=list)

    # Key entities mentioned
    entities: List[str] = field(default_factory=list)

    # Topic keywords (meaningful, filtered)
    topic_tokens: Set[str] = field(default_factory=set)

    # What information is likely missing
    likely_missing: List[str] = field(default_factory=list)

    # Is this a follow-up to a previous conversation?
    is_followup: bool = False

    # Does this reference something from before?
    references_prior: bool = False

    # Detected language
    language: str = "en"

    # Timestamp
    timestamp: float = field(default_factory=time.time)

    # Raw context (previous messages, etc.)
    conversation_history: List[Dict[str, str]] = field(default_factory=list)

    def to_prompt_context(self) -> str:
        """Format situation as context for the LLM."""
        parts = [
            f"INTENT: {self.intent.value}",
            f"PROBLEM_TYPE: {self.problem_type.value}",
            f"COMPLEXITY: {self.complexity.name} ({self.complexity.value})",
            f"OBJECTIVE: {self.underlying_objective or self.raw_input[:200]}",
        ]
        if self.constraints:
            parts.append(f"CONSTRAINTS: {'; '.join(self.constraints[:5])}")
        if self.likely_missing:
            parts.append(f"LIKELY_MISSING: {'; '.join(self.likely_missing[:3])}")
        if self.is_followup:
            parts.append("FOLLOWUP: yes — use conversation context")
        return "\n".join(parts)


# ── Intent classification patterns ───────────────────────────────────────────

_INTENT_PATTERNS: List[Tuple[IntentType, List[str], float]] = [
    # Greetings
    (IntentType.GREETING, [
        r"\b(hello|hi|hey|greetings|good\s*(morning|afternoon|evening)|"
        r"marhaba|salam|bonjour|ahlan)\b",
    ], 0.9),

    # Knowledge storage
    (IntentType.KNOWLEDGE_STORAGE, [
        r"\b(learn|remember|save|store|note|记住|APPREND| AppConfig)\b",
        r"\b(learn\s*this|remember\s*this|keep\s*this|don.t\s*forget)\b",
        r"\b(traduire|APPREND|HAFADH)\b",
    ], 0.85),

    # Knowledge retrieval
    (IntentType.KNOWLEDGE_RETRIEVAL, [
        r"\b(what\s+did\s+you\s+learn|what\s+do\s+you\s+know|recall|"
        r"what\s+is\s+my|tell\s+me\s+about|remind\s+me|شْنو\s*تعلمت)\b",
    ], 0.85),

    # Knowledge forget
    (IntentType.KNOWLEDGE_FORGET, [
        r"\b(forget|remove|delete|clear|erase|نسّى|ANSAX)\b",
    ], 0.8),

    # Knowledge correction
    (IntentType.KNOWLEDGE_CORRECTION, [
        r"\b(actually|no[,!]|wrong|incorrect|纠正|not\s+quite|correction)\b",
        r"\b(but\s+I\s+said|I\s+meant|that\s+was\s+wrong)\b",
    ], 0.85),

    # Problem solving
    (IntentType.PROBLEM_SOLVING, [
        r"\b(fix|solve|debug|error|broken|problem|issue|bug|crash|fail|"
        r"doesn.t\s+work|not\s+working|حل|صلح|مشكلة)\b",
    ], 0.8),

    # Status check
    (IntentType.STATUS_CHECK, [
        r"\b(status|are\s+you\s+(ready|ok|working|online|alive)|"
        r"what.s\s+your\s+status|شْنوة\s*راهدوم|واش\s*راه\s*يخدم)\b",
    ], 0.8),

    # Capabilities
    (IntentType.CAPABILITIES, [
        r"\b(what\s+can\s+you\s+do|capabilities|skills|abilities|tools|"
        r"powers|شنو\s*تقدر|واش\s*عندك\s*من\s*قدرات)\b",
    ], 0.8),

    # Identity
    (IntentType.IDENTITY, [
        r"\b(who\s+are\s+you|what\s+are\s+you|your\s+name|tell\s+me\s+"
        r"about\s+yourself|شْنْو\s*نتي)\b",
    ], 0.8),

    # Creation
    (IntentType.CREATION, [
        r"\b(create|build|write|make|generate|design|compose|write\s+me|"
        r"build\s+me|dir|DIIR|3ML)\b",
    ], 0.7),

    # Modification
    (IntentType.MODIFICATION, [
        r"\b(change|modify|update|adjust|edit|replace|upgrade|improve|"
        r"modify|GaDDel|JADDEL)\b",
    ], 0.7),

    # Feedback
    (IntentType.FEEDBACK, [
        r"\b(good|great|bad|terrible|thanks|thank\s+you|perfect|"
        r"excellent|horrible|merci|shukran)\b",
    ], 0.7),

    # Clarification (follow-up questions)
    (IntentType.CLARIFICATION, [
        r"\b(explain|more|detail|elaborate|what\s+do\s+you\s+mean|"
        r"which\s+one|the\s+first|the\s+second|ها|الأولى|الثانية)\b",
    ], 0.7),
]

# ── Problem type patterns ────────────────────────────────────────────────────

_PROBLEM_TYPE_PATTERNS: List[Tuple[ProblemType, List[str]]] = [
    (ProblemType.DIAGNOSTIC, [
        r"\b(why|cause|reason|diagnose|root\s+cause|what.*wrong|"
        r"what.*happened|علاقش|شْنو\s*سْباب)\b",
    ]),
    (ProblemType.PROCEDURAL, [
        r"\b(how\s+to|how\s+do\s+I|steps|procedure|process|workflow|"
        r"kifach|comment)\b",
    ]),
    (ProblemType.ANALYTICAL, [
        r"\b(analyze|compare|evaluate|assess|measure|benchmark|"
        r"measure|scan|inspect)\b",
    ]),
    (ProblemType.STRATEGIC, [
        r"\b(plan|strategy|approach|best\s+way|should\s+I|"
        r"recommend|suggest|propose)\b",
    ]),
    (ProblemType.EXPLORATORY, [
        r"\b(explore|investigate|research|discover|find\s+out|"
        r"search|look\s+into)\b",
    ]),
    (ProblemType.CREATIVE, [
        r"\b(imagine|creative|brainstorm|idea|inspire|novel|"
        r"innovative|original)\b",
    ]),
]

# ── Constraint patterns ──────────────────────────────────────────────────────

_CONSTRAINT_PATTERNS: List[Tuple[str, List[str]]] = [
    ("resource_limit", [r"\b(\d+\s*(gb|mb|ram|memory|storage))\b"]),
    ("time_limit", [r"\b(quick|fast|asap|urgent|now|immediately)\b"]),
    ("no_internet", [r"\b(offline|no\s+internet|no\s+network)\b"]),
    ("mobile_device", [r"\b(phone|mobile|android|termux|small\s+screen)\b"]),
    ("privacy", [r"\b(private|privacy|local|no\s+cloud)\b"]),
]

# ── Stop words for tokenization ──────────────────────────────────────────────

_STOP_WORDS = frozenset({
    "the", "is", "am", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can",
    "a", "an", "the", "this", "that", "these", "those",
    "i", "you", "he", "she", "it", "we", "they",
    "my", "your", "his", "her", "its", "our", "their",
    "me", "him", "us", "them",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after",
    "and", "but", "or", "so", "yet", "nor",
    "not", "no", "yes", "ok", "okay",
    "what", "which", "who", "whom", "where", "when", "why", "how",
    "if", "then", "else", "because", "since",
    "please", "just", "also", "very", "really", "quite",
    "about", "up", "out", "off", "over", "under", "again",
})


def _tokenize(text: str) -> Set[str]:
    """Lowercase word tokenization, filtering stop words."""
    words = re.findall(r"[a-z0-9_]{2,}", text.lower())
    return {w for w in words if w not in _STOP_WORDS}


# ── Language detection ────────────────────────────────────────────────────────

_ARABIC_RANGE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_FRENCH_MARKERS = frozenset({"bonjour", "merci", "comment", "pourquoi", "c'est",
                              "je", "tu", "nous", "vous", "ils", "elles",
                              "est-ce", "peux-tu", "s'il", "voila"})


def _detect_language(text: str) -> str:
    """Detect the dominant language of the input."""
    lower = text.lower()
    if _ARABIC_RANGE.search(text):
        return "ar"
    if any(w in lower for w in _FRENCH_MARKERS):
        return "fr"
    return "en"


# ── SituationModel ───────────────────────────────────────────────────────────

class SituationModel:
    """Builds a structured understanding of the current situation.
    
    This is Zerion's "ears and eyes" — it takes raw input and produces
    a rich, structured Situation that the rest of the intelligence
    pipeline can reason about.
    """

    def __init__(self):
        self._conversation_turns: List[Dict[str, str]] = []
        self._last_intent: Optional[IntentType] = None
        self._last_entities: List[str] = []

    def analyze(
        self,
        user_input: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        memory_context: Optional[str] = None,
        system_state: Optional[Dict[str, Any]] = None,
    ) -> Situation:
        """Analyze raw user input and build a structured Situation."""
        situation = Situation(raw_input=user_input)

        # 1. Language detection
        situation.language = _detect_language(user_input)

        # 2. Intent classification
        situation.intent = self._classify_intent(user_input)

        # 3. Topic extraction
        situation.topic_tokens = _tokenize(user_input)

        # 4. Problem type classification
        situation.problem_type = self._classify_problem_type(user_input)

        # 5. Complexity assessment
        situation.complexity = self._assess_complexity(user_input, situation)

        # 6. Urgency assessment
        situation.urgency = self._assess_urgency(user_input)

        # 7. Entity extraction
        situation.entities = self._extract_entities(user_input)

        # 8. Constraint detection
        situation.constraints = self._detect_constraints(user_input)

        # 9. Problem reframing
        situation.stated_problem = user_input.strip()
        situation.real_problem, situation.underlying_objective = (
            self._reframe_problem(user_input, situation)
        )

        # 10. Missing information detection
        situation.likely_missing = self._detect_missing_info(user_input, situation)

        # 11. Follow-up detection
        situation.conversation_history = conversation_history or []
        situation.is_followup = self._is_followup(user_input, situation)
        situation.references_prior = self._references_prior(user_input)

        # 12. Update conversation tracking
        self._conversation_turns.append({"role": "user", "content": user_input})
        if len(self._conversation_turns) > 20:
            self._conversation_turns = self._conversation_turns[-20:]
        self._last_intent = situation.intent
        self._last_entities = situation.entities

        return situation

    def _classify_intent(self, text: str) -> IntentType:
        """Classify user intent using pattern matching."""
        lower = text.lower().strip()

        best_intent = IntentType.CONVERSATION
        best_score = 0.0

        for intent, patterns, base_score in _INTENT_PATTERNS:
            for pattern in patterns:
                if re.search(pattern, lower, re.IGNORECASE):
                    if base_score > best_score:
                        best_score = base_score
                        best_intent = intent
                    break

        return best_intent

    def _classify_problem_type(self, text: str) -> ProblemType:
        """Classify the type of problem."""
        lower = text.lower()

        # Question markers → FACTUAL
        if re.search(r"\?$", text.strip()) or re.search(r"\b(what|who|when|where|which)\b", lower):
            return ProblemType.FACTUAL

        # Check diagnostic patterns
        for ptype, patterns in _PROBLEM_TYPE_PATTERNS:
            for pattern in patterns:
                if re.search(pattern, lower, re.IGNORECASE):
                    return ptype

        return ProblemType.FACTUAL

    def _assess_complexity(self, text: str, situation: Situation) -> Complexity:
        """Assess the complexity of the request."""
        score = 0

        # Length-based
        if len(text) > 200:
            score += 1
        if len(text) > 500:
            score += 1

        # Multi-step indicators
        multi_step_words = ["then", "after", "also", "and then", "first", "next",
                            "finally", "step", "حل", "جرب", "dire"]
        if any(w in text.lower() for w in multi_step_words):
            score += 1

        # Problem-solving indicators
        if situation.problem_type in (ProblemType.DIAGNOSTIC, ProblemType.STRATEGIC):
            score += 1

        # Multiple constraints
        if len(situation.constraints) >= 2:
            score += 1

        # References to multiple topics
        if len(situation.topic_tokens) > 10:
            score += 1

        # Map score to complexity
        if score <= 1:
            return Complexity.TRIVIAL if score == 0 else Complexity.SIMPLE
        elif score <= 2:
            return Complexity.MODERATE
        elif score <= 3:
            return Complexity.COMPLEX
        else:
            return Complexity.HARD

    def _assess_urgency(self, text: str) -> Urgency:
        """Assess how urgent the request is."""
        lower = text.lower()
        if any(w in lower for w in ["urgent", "asap", "immediately", "now", "hurry"]):
            return Urgency.HIGH
        if any(w in lower for w in ["broken", "crash", "error", "fail", "dead"]):
            return Urgency.HIGH
        if any(w in lower for w in ["quick", "fast", "simple", "just"]):
            return Urgency.NORMAL
        return Urgency.NORMAL

    def _extract_entities(self, text: str) -> List[str]:
        """Extract named entities from the text."""
        entities = []
        # Capitalized words (English)
        for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", text):
            word = match.group(1)
            if word.lower() not in _STOP_WORDS and len(word) > 2:
                entities.append(word)
        # Quoted strings
        for match in re.finditer(r'["\']([^"\']+)["\']', text):
            entities.append(match.group(1))
        # Technical terms (contain dots, underscores, or mixed case)
        for match in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_.]{2,})\b", text):
            word = match.group(1)
            if "." in word or "_" in word or any(c.isupper() for c in word[1:]):
                entities.append(word)
        return list(dict.fromkeys(entities))[:10]  # deduplicate, limit

    def _detect_constraints(self, text: str) -> List[str]:
        """Detect constraints mentioned in the input."""
        constraints = []
        lower = text.lower()
        for name, patterns in _CONSTRAINT_PATTERNS:
            for pattern in patterns:
                if re.search(pattern, lower):
                    constraints.append(name)
                    break
        return constraints

    def _reframe_problem(self, text: str, situation: Situation) -> Tuple[str, str]:
        """Reframe the problem: identify stated vs real problem.
        
        Returns (real_problem, underlying_objective).
        """
        lower = text.lower().strip()
        intent = situation.intent

        # For simple intents, the stated problem IS the real problem
        if intent in (IntentType.GREETING, IntentType.IDENTITY,
                      IntentType.CAPABILITIES, IntentType.STATUS_CHECK):
            return text.strip(), text.strip()

        # For problem-solving, try to extract the real issue
        if intent == IntentType.PROBLEM_SOLVING:
            # Strip command prefixes
            cleaned = re.sub(
                r"^(fix|solve|debug|repair|resolve|help\s+me\s+with)\s+",
                "", lower
            ).strip()
            return cleaned, f"Resolve: {cleaned}"

        # For knowledge operations
        if intent == IntentType.KNOWLEDGE_STORAGE:
            # Extract the actual knowledge to store
            learn_match = re.search(
                r"(?:learn|remember|save|store|note)\s*(?:this|that|:)?\s*(.+)",
                lower
            )
            if learn_match:
                knowledge = learn_match.group(1).strip()
                return knowledge, f"Store knowledge: {knowledge}"

        if intent == IntentType.KNOWLEDGE_RETRIEVAL:
            # What is the user asking about?
            recall_match = re.search(
                r"(?:what|tell|remind|recall)\s.*?(?:about|regarding|concerning)?\s*(.+)",
                lower
            )
            if recall_match:
                topic = recall_match.group(1).strip()
                return topic, f"Retrieve: {topic}"

        # For questions
        if intent == IntentType.QUESTION:
            return text.strip(), f"Answer: {text.strip()}"

        # Default: stated = real
        return text.strip(), text.strip()

    def _detect_missing_info(self, text: str, situation: Situation) -> List[str]:
        """Detect what information is likely missing for a complete response."""
        missing = []
        lower = text.lower()

        if situation.problem_type == ProblemType.DIAGNOSTIC:
            if not any(w in lower for w in ["error", "traceback", "log", "output"]):
                missing.append("error details or logs")
            if not any(w in lower for w in ["when", "time", "started", "after"]):
                missing.append("when the problem started")
            if not any(w in lower for w in ["step", "before", "did", "tried"]):
                missing.append("steps to reproduce")

        if situation.problem_type == ProblemType.PROCEDURAL:
            if not any(w in lower for w in ["where", "which", "file", "path"]):
                missing.append("specific location or target")

        if situation.intent == IntentType.CREATION:
            if not any(w in lower for w in ["like", "format", "style", "example"]):
                missing.append("desired format or style")

        return missing

    def _is_followup(self, text: str, situation: Situation) -> bool:
        """Detect if this is a follow-up to a previous message."""
        lower = text.lower().strip()

        # Very short messages are likely follow-ups
        if len(lower.split()) <= 3:
            return True

        # Pronouns without clear antecedent
        if re.match(r"^(it|this|that|them|those|ها|الأولى|الثانية)\b", lower):
            return True

        # Implicit references
        followup_markers = [
            "and", "also", "the", "one", "first", "second",
            "also", "do", "now", "go", "yes", "no",
            "صلحها", "جرب", "ديرها",
        ]
        if lower.strip() in followup_markers:
            return True

        return False

    def _references_prior(self, text: str) -> bool:
        """Detect if the text references prior conversation."""
        prior_markers = [
            "earlier", "before", "previously", "last time", "you said",
            "we discussed", "the one you", "that thing",
            "اللي قلت", "اللي درتي", "اللي شفت",
        ]
        lower = text.lower()
        return any(m in lower for m in prior_markers)

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get recent conversation turns."""
        return list(self._conversation_turns)
