"""
SmartMemory — ONE unified intelligent memory for Zerion.

Replaces the old 8-layer memory architecture with a single intelligent system
that manages 7 simple JSON storage files:

  userdata.json      — user identity, name, personal facts
  preferences.json   — user preferences and settings
  goals.json         — goals, intentions, plans
  experiences.json   — episodic experiences, episodes, outcomes
  knowledge.json     — learned facts, rules, procedures, concepts
  rewards.json       — rewards, achievements, outcomes
  system_state.json  — runtime state, metrics, configuration

There is ONE memory intelligence. The files are only storage organization.
"""

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from zerion.memory.episodic import Episode
from zerion.memory.procedural import ProceduralRule
from zerion.memory.semantic import (
    CausalLink,
    FailureMemoryRecord,
    MetacognitiveRecord,
    SemanticConcept,
)
from zerion.memory.distillation import ExperienceDistiller

# ── Memory item structure ────────────────────────────────────────────────────

_MEMORY_DOMAINS = ("userdata", "preferences", "goals", "experiences",
                   "knowledge", "rewards", "system_state")

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
    "further", "once", "here", "there", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such",
    "than", "too", "only",
})


def _tokenize(text: str) -> List[str]:
    """Lowercase word tokenization, filtering short/stop words."""
    words = re.findall(r"[a-z0-9_]{2,}", text.lower())
    return [w for w in words if w not in _STOP_WORDS]


def _content_hash(content: str) -> str:
    """Stable hash for deduplication (ignores whitespace/case)."""
    normalized = re.sub(r"\s+", " ", content.strip().lower())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── Domain classification heuristics ─────────────────────────────────────────

# Keyword → domain mapping (checked in order; first match wins)
_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "userdata": [
        "name", "user name", "my name", "i am", "i'm", "live", "address",
        "birthday", "born", "age", "phone", "email", "location", "country",
        "city", "job", "occupation", "work as", "i work", "family",
    ],
    "preferences": [
        "prefer", "like", "dislike", "hate", "love", "favorite", "favourite",
        "always", "never", "style", "way", "short answer", "concise",
        "verbose", "detailed", "simple", "complex", "format", "language",
        "arabic", "english", "french", "theme", "dark mode", "light mode",
        "font", "size", "color", "quiet", "loud",
    ],
    "goals": [
        "goal", "objective", "aim", "target", "want to", "trying to",
        "planning to", "need to", "should", "must", "deadline", "finish",
        "complete", "achieve", "build", "create", "learn", "master",
        "improve", "develop", "deploy", "launch",
    ],
    "rewards": [
        "reward", "achievement", "unlocked", "earned", "score",
        "milestone", "completed", "success", "won", "level up",
        "progress", "streak",
    ],
    "knowledge": [
        "learned", "discovered", "found out", "realized", "know that",
        "fact", "theorem", "rule", "principle", "method", "technique",
        "algorithm", "pattern", "how to", "solution", "fix", "workaround",
        "best practice", "important",
    ],
    "system_state": [
        "status", "running", "stopped", "error", "warning", "crash",
        "timeout", "memory usage", "cpu", "disk", "network", "online",
        "offline", "connected", "disconnected", "version", "config",
        "setting", "uptime", "latency",
    ],
}


def _classify_domain(text: str) -> str:
    """Classify text into a memory domain using keyword heuristics.
    
    Returns one of: userdata, preferences, goals, experiences,
    knowledge, rewards, system_state.
    """
    lower = text.lower()
    scores: Dict[str, float] = {d: 0.0 for d in _MEMORY_DOMAINS}

    for domain, keywords in _DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                scores[domain] += 1.0

    # Strong signal: "my name is" → userdata immediately
    if re.search(r"\bmy\s+name\s+(is|was|be)\b", lower):
        return "userdata"

    # "I prefer/like/dislike" → preferences
    if re.search(r"\b(i\s+)?(prefer|like|dislike|hate|love)\b", lower):
        return "preferences"

    # "my goal / I want to / I need to" → goals
    if re.search(r"\b(goal|want\s+to|need\s+to|trying\s+to|planning\s+to)\b", lower):
        return "goals"

    # "I learned / I discovered / I realized" → knowledge
    if re.search(r"\b(learned|discovered|realized|found\s+out)\b", lower):
        return "knowledge"

    # If we have clear keyword hits, pick the highest
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best

    # Default: knowledge (most general)
    return "knowledge"


def _assess_importance(text: str, domain: str) -> str:
    """Assess memory importance: 'critical', 'high', 'medium', 'low'."""
    lower = text.lower()

    # Critical: system errors, security issues
    if domain == "system_state" and any(w in lower for w in (
        "crash", "error", "critical", "security", "breach", "data loss"
    )):
        return "critical"

    # High: user identity, explicit preferences, goals
    if domain in ("userdata", "goals"):
        return "high"
    if domain == "preferences" and any(w in lower for w in (
        "always", "never", "must", "important"
    )):
        return "high"

    # Medium: knowledge, experiences
    if domain in ("knowledge", "experiences", "rewards"):
        return "medium"

    # Low: everything else
    return "low"


def _assess_confidence(text: str, source: str = "user") -> float:
    """Assess confidence: explicit user statement > inferred > assumed."""
    lower = text.lower()

    # Explicit statements get high confidence
    if source == "user":
        if re.search(r"\b(is|are|was|name\s+is)\b", lower):
            return 0.95
        if re.search(r"\b(i\s+)?(prefer|like|want|need)\b", lower):
            return 0.90
        return 0.85

    # System observations
    if source == "system":
        return 0.80

    # Inferred
    if source == "inferred":
        return 0.60

    return 0.50


# ── SmartMemory ──────────────────────────────────────────────────────────────

class SmartMemory:
    """ONE intelligent memory system for Zerion.
    
    Manages 7 JSON storage files. Automatically classifies, deduplicates,
    updates, and retrieves memories. One system, one intelligence.
    """

    def __init__(self, data_dir: str = "data", *, migrate_from_db: bool = True, db_path: Optional[str] = None):
        # Backward compat: db_path is ignored (old SQLite storage replaced by JSON)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._storage_files: Dict[str, Path] = {}
        for domain in _MEMORY_DOMAINS:
            self._storage_files[domain] = self.data_dir / f"{domain}.json"

        # In-memory cache: domain → list of memory items
        self._memories: Dict[str, List[Dict[str, Any]]] = {d: [] for d in _MEMORY_DOMAINS}
        # Quick lookup by content hash
        self._hash_index: Dict[str, str] = {}  # hash → domain

        # Load all storage files
        self._load_all()

        # Migration from old SQLite if needed
        if migrate_from_db:
            self._migrate_from_old_db()

        # Backward-compat: legacy episodic/procedural/failure stores
        # populated from the experiences/knowledge domains
        self._episodes: Dict[str, Episode] = {}
        self._procedural_rules: Dict[str, ProceduralRule] = {}
        self._failures: Dict[str, FailureMemoryRecord] = {}
        self._concepts: Dict[str, SemanticConcept] = {}
        self._causal_links: Dict[str, CausalLink] = {}
        self._metacognitive: Dict[str, MetacognitiveRecord] = {}
        self._distiller = ExperienceDistiller(min_pattern_support=2)
        self._rebuild_legacy_caches()

    # ── PUBLIC API ────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        *,
        domain: Optional[str] = None,
        importance: Optional[str] = None,
        confidence: Optional[float] = None,
        source: str = "user",
        tags: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store a memory. Auto-classifies domain if not specified.
        
        Returns the memory item stored (with id, domain, timestamp).
        Detects duplicates and updates existing memories when appropriate.
        """
        # 1. Classify
        if domain is None:
            domain = _classify_domain(content)
        if domain not in _MEMORY_DOMAINS:
            domain = "knowledge"

        # 2. Check for duplicates / updates
        content_hash = _content_hash(content)
        existing = self._find_similar(content, domain)

        if existing:
            # Update existing memory (boost confidence, refresh timestamp)
            return self._update_memory(existing, content, domain, content_hash,
                                        importance, confidence, source, tags, context)

        # 3. Check cross-domain duplicates
        cross = self._find_cross_domain_duplicate(content, domain)
        if cross:
            return self._update_memory(cross, content, domain, content_hash,
                                        importance, confidence, source, tags, context)

        # 4. Create new memory
        if importance is None:
            importance = _assess_importance(content, domain)
        if confidence is None:
            confidence = _assess_confidence(content, source)

        item = {
            "id": f"mem_{uuid.uuid4().hex[:12]}",
            "content": content.strip(),
            "domain": domain,
            "importance": importance,
            "confidence": round(confidence, 3),
            "source": source,
            "created_at": time.time(),
            "updated_at": time.time(),
            "access_count": 0,
            "tags": tags or [],
            "context": context or {},
            "history": [],
            "hash": content_hash,
        }

        self._memories[domain].append(item)
        self._hash_index[content_hash] = domain
        self._persist_domain(domain)
        return item

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        domains: Optional[List[str]] = None,
        min_confidence: float = 0.0,
        min_importance: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve memories relevant to a query.
        
        Returns the top_k most relevant memories across specified domains,
        ranked by relevance × confidence × importance.
        """
        query_tokens = set(_tokenize(query))
        importance_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        search_domains = domains or list(_MEMORY_DOMAINS)

        candidates: List[Tuple[float, Dict[str, Any]]] = []

        for domain in search_domains:
            if domain not in self._memories:
                continue
            for item in self._memories[domain]:
                if item["confidence"] < min_confidence:
                    continue
                if min_importance:
                    if importance_order.get(item["importance"], 0) < importance_order.get(min_importance, 0):
                        continue

                # Compute relevance score
                content_tokens = set(_tokenize(item["content"]))
                tag_tokens = set(t.lower() for t in item.get("tags", []))
                all_tokens = content_tokens | tag_tokens

                if query_tokens:
                    overlap = len(query_tokens & all_tokens)
                    total = len(query_tokens | all_tokens)
                    relevance = overlap / total if total > 0 else 0.0
                    # Boost by confidence and importance
                    imp_boost = importance_order.get(item["importance"], 1) / 4.0
                    score = relevance * 0.5 + item["confidence"] * 0.3 + imp_boost * 0.2
                else:
                    score = item["confidence"] * 0.5 + (
                        importance_order.get(item["importance"], 1) / 4.0) * 0.5

                if score > 0.05:
                    candidates.append((score, item))

        # Sort by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)

        # Update access counts
        results = []
        for score, item in candidates[:top_k]:
            item["access_count"] = item.get("access_count", 0) + 1
            results.append(item)

        # Persist access count updates periodically
        if results:
            self._persist_domain(results[0]["domain"])

        return results

    def get_context(self, query: str, *, max_tokens: int = 500) -> str:
        """Build a compact memory context string for LLM reasoning.
        
        Returns only the memories relevant to the current query,
        formatted as concise text to minimize token usage.
        """
        memories = self.retrieve(query, top_k=5, min_confidence=0.3)
        if not memories:
            return ""

        lines = ["[Memory context]"]
        for m in memories:
            domain_label = m["domain"].replace("_", " ").title()
            lines.append(f"  {domain_label}: {m['content'][:200]}")

        context = "\n".join(lines)
        # Truncate to token budget (rough: 1 token ≈ 4 chars)
        max_chars = max_tokens * 4
        if len(context) > max_chars:
            context = context[:max_chars] + "\n  [...truncated]"
        return context

    def update(self, memory_id: str, **fields) -> Optional[Dict[str, Any]]:
        """Update specific fields of an existing memory by ID."""
        for domain in _MEMORY_DOMAINS:
            for item in self._memories[domain]:
                if item["id"] == memory_id:
                    for key, value in fields.items():
                        if key in ("content", "importance", "confidence",
                                   "tags", "context", "source"):
                            item[key] = value
                    item["updated_at"] = time.time()
                    self._persist_domain(domain)
                    return item
        return None

    def forget(self, query: str, *, domain: Optional[str] = None) -> int:
        """Remove memories matching a query. Returns count removed."""
        query_tokens = set(_tokenize(query))
        removed = 0
        search_domains = [domain] if domain else list(_MEMORY_DOMAINS)

        for d in search_domains:
            before = len(self._memories[d])
            self._memories[d] = [
                item for item in self._memories[d]
                if not self._matches_query(item, query_tokens)
            ]
            removed += before - len(self._memories[d])
            if before != len(self._memories[d]):
                self._persist_domain(d)

        return removed

    def search(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """Alias for retrieve — search memories."""
        return self.retrieve(query, **kwargs)

    def count(self, domain: Optional[str] = None) -> int:
        """Count memories, optionally in a specific domain."""
        if domain:
            return len(self._memories.get(domain, []))
        return sum(len(v) for v in self._memories.values())

    def domains_summary(self) -> Dict[str, int]:
        """Return count of memories per domain."""
        return {d: len(items) for d, items in self._memories.items()}

    def list_all(self, domain: Optional[str] = None,
                 limit: int = 50) -> List[Dict[str, Any]]:
        """List memories, optionally filtered by domain."""
        if domain:
            items = self._memories.get(domain, [])
        else:
            items = [item for items in self._memories.values() for item in items]
        # Sort by updated_at descending
        items = sorted(items, key=lambda x: x.get("updated_at", 0), reverse=True)
        return items[:limit]

    # ── BACKWARD COMPAT: Episodes ─────────────────────────────────────────

    def record_episode(self, episode: Episode) -> str:
        """Store an episode (backward compat with old DevelopmentalMemoryStore)."""
        item = self.remember(
            f"Episode: {episode.goal} — {episode.outcome_status}",
            domain="experiences",
            source="system",
            importance="medium",
            context={
                "episode_id": episode.id,
                "goal": episode.goal,
                "status": episode.outcome_status,
                "reward": episode.reward,
                "actions": episode.actions_taken,
                "duration_ms": episode.duration_ms,
            },
            tags=["episode", episode.outcome_status.lower()],
        )
        self._episodes[episode.id] = episode
        return episode.id

    def list_episodes(self, limit: int = 50) -> List[Episode]:
        """List recent episodes (backward compat)."""
        return sorted(self._episodes.values(),
                      key=lambda e: e.timestamp, reverse=True)[:limit]

    # ── BACKWARD COMPAT: Procedural Rules ─────────────────────────────────

    def register_procedural_rule(self, rule: ProceduralRule) -> str:
        """Store a procedural rule (backward compat)."""
        self.remember(
            f"Rule: {rule.name} — {rule.action_procedure}",
            domain="knowledge",
            source="system",
            importance="high",
            confidence=rule.reliability,
            context={
                "rule_id": rule.id,
                "name": rule.name,
                "trigger_conditions": rule.trigger_conditions,
                "action_procedure": rule.action_procedure,
                "reliability": rule.reliability,
            },
            tags=["procedural_rule", "automated"],
        )
        self._procedural_rules[rule.id] = rule
        return rule.id

    def find_procedural_rule(self, query: str) -> Optional[ProceduralRule]:
        """Find a procedural rule matching a query (backward compat)."""
        q_words = set(query.lower().replace("_", " ").split())
        candidates = []
        for r in self._procedural_rules.values():
            rule_text = (r.name + " " + " ".join(r.trigger_conditions)).lower().replace("_", " ")
            rule_words = set(rule_text.split())
            overlap = len(q_words.intersection(rule_words))
            if overlap >= 2 or any(c.lower() in query.lower() for c in r.trigger_conditions):
                candidates.append((overlap, r))
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1].reliability), reverse=True)
            return candidates[0][1]
        return None

    def list_procedural_rules(self) -> List[ProceduralRule]:
        """List all procedural rules (backward compat)."""
        return sorted(self._procedural_rules.values(),
                      key=lambda r: r.reliability, reverse=True)

    # ── BACKWARD COMPAT: Failures ─────────────────────────────────────────

    def record_failure(self, failure: FailureMemoryRecord) -> str:
        """Store a failure record (backward compat)."""
        self.remember(
            f"Failure: {failure.task_goal} — {failure.failure_type}: {failure.root_cause}",
            domain="knowledge",
            source="system",
            importance="high",
            context={
                "failure_id": failure.id,
                "task_goal": failure.task_goal,
                "failure_type": failure.failure_type,
                "root_cause": failure.root_cause,
                "preventive_rule": failure.preventive_rule,
            },
            tags=["failure", failure.failure_type],
        )
        self._failures[failure.id] = failure
        return failure.id

    def list_failures(self, failure_type: Optional[str] = None) -> List[FailureMemoryRecord]:
        """List failure records (backward compat)."""
        if failure_type:
            return [f for f in self._failures.values() if f.failure_type == failure_type]
        return list(self._failures.values())

    # ── BACKWARD COMPAT: Semantic / Causal / Metacognitive ────────────────

    def record_concept(self, concept: SemanticConcept):
        """Store a semantic concept (backward compat)."""
        self.remember(
            f"Concept: {concept.name} — {concept.definition}",
            domain="knowledge",
            source="system",
            importance="medium",
            confidence=concept.confidence,
            context={"concept_id": concept.concept_id, "properties": concept.properties},
            tags=["concept", concept.name],
        )
        self._concepts[concept.concept_id] = concept

    def record_causal_link(self, link: CausalLink):
        """Store a causal link (backward compat)."""
        self.remember(
            f"Causal: {link.cause} → {link.effect} (p={link.p_effect_given_cause:.2f})",
            domain="knowledge",
            source="system",
            importance="medium",
            context={"link_id": link.id, "cause": link.cause, "effect": link.effect},
            tags=["causal_link"],
        )
        self._causal_links[link.id] = link

    def record_metacognitive(self, meta: MetacognitiveRecord):
        """Store a metacognitive record (backward compat)."""
        self.remember(
            f"Meta: {meta.strategy_name} on {meta.problem_domain} "
            f"(gain={meta.effective_gain:.2f}, efficiency={meta.cost_efficiency:.2f})",
            domain="system_state",
            source="system",
            importance="medium",
            context={
                "meta_id": meta.id,
                "strategy": meta.strategy_name,
                "domain": meta.problem_domain,
            },
            tags=["metacognitive"],
        )
        self._metacognitive[meta.id] = meta

    # ── BACKWARD COMPAT: Distillation ─────────────────────────────────────

    def trigger_distillation(self) -> List[ProceduralRule]:
        """Distill episodes into procedural rules (backward compat)."""
        new_rules = self._distiller.distill_episodes(list(self._episodes.values()))
        for r in new_rules:
            self.register_procedural_rule(r)
        return new_rules

    # ── INTERNAL: Classification & Dedup ──────────────────────────────────

    def _find_similar(self, content: str, domain: str) -> Optional[Dict[str, Any]]:
        """Find a semantically similar memory in the same domain."""
        new_tokens = set(_tokenize(content))
        for item in self._memories[domain]:
            existing_tokens = set(_tokenize(item["content"]))
            similarity = _jaccard(new_tokens, existing_tokens)
            if similarity > 0.6:
                return item
        return None

    def _find_cross_domain_duplicate(self, content: str,
                                      exclude_domain: str) -> Optional[Dict[str, Any]]:
        """Check if the same info exists in a different domain."""
        new_tokens = set(_tokenize(content))
        for domain in _MEMORY_DOMAINS:
            if domain == exclude_domain:
                continue
            for item in self._memories[domain]:
                existing_tokens = set(_tokenize(item["content"]))
                similarity = _jaccard(new_tokens, existing_tokens)
                if similarity > 0.8:
                    return item
        return None

    def _update_memory(
        self,
        existing: Dict[str, Any],
        new_content: str,
        domain: str,
        content_hash: str,
        importance: Optional[str],
        confidence: Optional[float],
        source: str,
        tags: Optional[List[str]],
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Update an existing memory with new information."""
        # Preserve history
        if "history" not in existing:
            existing["history"] = []
        existing["history"].append({
            "content": existing["content"],
            "confidence": existing["confidence"],
            "updated_at": existing["updated_at"],
        })

        # Update content
        existing["content"] = new_content.strip()
        existing["hash"] = content_hash
        existing["updated_at"] = time.time()
        existing["access_count"] = existing.get("access_count", 0)

        # Boost confidence for repeated confirmation
        if confidence is not None:
            old_conf = existing.get("confidence", 0.5)
            existing["confidence"] = round(min(1.0, (old_conf + confidence) / 2 + 0.05), 3)

        # Update importance if higher
        if importance:
            imp_order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            if imp_order.get(importance, 0) > imp_order.get(existing.get("importance", "low"), 0):
                existing["importance"] = importance

        # Merge tags
        if tags:
            existing_tags = set(existing.get("tags", []))
            existing_tags.update(tags)
            existing["tags"] = list(existing_tags)

        # Merge context
        if context:
            if "context" not in existing:
                existing["context"] = {}
            existing["context"].update(context)

        self._persist_domain(domain)
        return existing

    def _matches_query(self, item: Dict[str, Any], query_tokens: set) -> bool:
        """Check if a memory item matches a forget query."""
        content_tokens = set(_tokenize(item["content"]))
        tag_tokens = set(t.lower() for t in item.get("tags", []))
        meaningful = (content_tokens | tag_tokens) - _STOP_WORDS
        return len(query_tokens & meaningful) >= 1

    # ── INTERNAL: Persistence ─────────────────────────────────────────────

    def _persist_domain(self, domain: str):
        """Write a domain's memories to its JSON file."""
        filepath = self._storage_files[domain]
        items = self._memories[domain]
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(items, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _load_all(self):
        """Load all storage files into memory."""
        for domain in _MEMORY_DOMAINS:
            filepath = self._storage_files[domain]
            if filepath.exists():
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        items = json.load(f)
                    if isinstance(items, list):
                        self._memories[domain] = items
                        for item in items:
                            h = item.get("hash")
                            if h:
                                self._hash_index[h] = domain
                except Exception:
                    pass

    # ── INTERNAL: Migration ───────────────────────────────────────────────

    def _migrate_from_old_db(self):
        """Migrate data from old memory.db SQLite to unified JSON storage."""
        old_db = self.data_dir / "memory.db"
        if not old_db.exists():
            return

        # Check if already migrated (skip if userdata has data)
        if self._memories["userdata"] or self._memories["knowledge"]:
            return

        try:
            conn = sqlite3.connect(str(old_db))
            migrated = 0

            # Migrate episodes → experiences
            for row in conn.execute("SELECT data_json FROM mem_episodes").fetchall():
                try:
                    ep_data = json.loads(row[0])
                    ep = Episode.from_dict(ep_data)
                    self._episodes[ep.id] = ep
                    self._memories["experiences"].append({
                        "id": f"mem_{uuid.uuid4().hex[:12]}",
                        "content": f"Episode: {ep.goal} — {ep.outcome_status} "
                                   f"(reward={ep.reward:.2f})",
                        "domain": "experiences",
                        "importance": "medium",
                        "confidence": 0.80,
                        "source": "system",
                        "created_at": ep.timestamp,
                        "updated_at": ep.timestamp,
                        "access_count": 0,
                        "tags": ["episode", ep.outcome_status.lower(), "migrated"],
                        "context": {"episode_id": ep.id, "goal": ep.goal,
                                    "reward": ep.reward, "status": ep.outcome_status},
                        "history": [],
                        "hash": _content_hash(f"{ep.goal} {ep.outcome_status}"),
                    })
                    migrated += 1
                except Exception:
                    pass

            # Migrate procedural rules → knowledge
            for row in conn.execute("SELECT data_json FROM mem_procedural").fetchall():
                try:
                    r_data = json.loads(row[0])
                    rule = ProceduralRule.from_dict(r_data)
                    self._procedural_rules[rule.id] = rule
                    self._memories["knowledge"].append({
                        "id": f"mem_{uuid.uuid4().hex[:12]}",
                        "content": f"Rule: {rule.name} — {rule.action_procedure}",
                        "domain": "knowledge",
                        "importance": "high",
                        "confidence": rule.reliability,
                        "source": "system",
                        "created_at": rule.created_at,
                        "updated_at": rule.updated_at,
                        "access_count": 0,
                        "tags": ["procedural_rule", "migrated"],
                        "context": {"rule_id": rule.id, "name": rule.name,
                                    "reliability": rule.reliability},
                        "history": [],
                        "hash": _content_hash(rule.name),
                    })
                    migrated += 1
                except Exception:
                    pass

            # Migrate semantic concepts → knowledge
            for row in conn.execute("SELECT data_json FROM mem_semantic").fetchall():
                try:
                    c_data = json.loads(row[0])
                    concept = SemanticConcept(
                        concept_id=c_data["concept_id"],
                        name=c_data["name"],
                        definition=c_data.get("definition", ""),
                        properties=c_data.get("properties", {}),
                        related_concepts=c_data.get("related_concepts", []),
                        confidence=c_data.get("confidence", 1.0),
                        updated_at=c_data.get("updated_at", time.time()),
                    )
                    self._concepts[concept.concept_id] = concept
                    self._memories["knowledge"].append({
                        "id": f"mem_{uuid.uuid4().hex[:12]}",
                        "content": f"Concept: {concept.name} — {concept.definition}",
                        "domain": "knowledge",
                        "importance": "medium",
                        "confidence": concept.confidence,
                        "source": "system",
                        "created_at": concept.updated_at,
                        "updated_at": concept.updated_at,
                        "access_count": 0,
                        "tags": ["concept", "migrated"],
                        "context": {"concept_id": concept.concept_id},
                        "history": [],
                        "hash": _content_hash(concept.name),
                    })
                    migrated += 1
                except Exception:
                    pass

            # Migrate causal links → knowledge
            for row in conn.execute("SELECT data_json FROM mem_causal").fetchall():
                try:
                    cl_data = json.loads(row[0])
                    link = CausalLink(
                        id=cl_data["id"],
                        cause=cl_data.get("cause", ""),
                        effect=cl_data.get("effect", ""),
                        intervention_tested=cl_data.get("intervention_tested", False),
                        p_effect_given_cause=cl_data.get("p_effect_given_cause", 0.9),
                        p_effect_without_cause=cl_data.get("p_effect_without_cause", 0.1),
                        updated_at=cl_data.get("updated_at", time.time()),
                    )
                    self._causal_links[link.id] = link
                    self._memories["knowledge"].append({
                        "id": f"mem_{uuid.uuid4().hex[:12]}",
                        "content": f"Causal: {link.cause} → {link.effect}",
                        "domain": "knowledge",
                        "importance": "medium",
                        "confidence": 0.80,
                        "source": "system",
                        "created_at": link.updated_at,
                        "updated_at": link.updated_at,
                        "access_count": 0,
                        "tags": ["causal_link", "migrated"],
                        "context": {"link_id": link.id},
                        "history": [],
                        "hash": _content_hash(f"{link.cause} {link.effect}"),
                    })
                    migrated += 1
                except Exception:
                    pass

            # Migrate failures → knowledge
            for row in conn.execute("SELECT data_json FROM mem_failures").fetchall():
                try:
                    f_data = json.loads(row[0])
                    fail = FailureMemoryRecord(
                        id=f_data["id"],
                        task_goal=f_data.get("task_goal", ""),
                        failure_type=f_data.get("failure_type", "reasoning_gap"),
                        root_cause=f_data.get("root_cause", ""),
                        preventive_rule=f_data.get("preventive_rule", ""),
                        recurrence_count=f_data.get("recurrence_count", 1),
                        timestamp=f_data.get("timestamp", time.time()),
                    )
                    self._failures[fail.id] = fail
                    self._memories["knowledge"].append({
                        "id": f"mem_{uuid.uuid4().hex[:12]}",
                        "content": f"Failure: {fail.task_goal} — {fail.failure_type}: "
                                   f"{fail.root_cause}",
                        "domain": "knowledge",
                        "importance": "high",
                        "confidence": 0.85,
                        "source": "system",
                        "created_at": fail.timestamp,
                        "updated_at": fail.timestamp,
                        "access_count": 0,
                        "tags": ["failure", fail.failure_type, "migrated"],
                        "context": {"failure_id": fail.id,
                                    "preventive_rule": fail.preventive_rule},
                        "history": [],
                        "hash": _content_hash(f"{fail.id} {fail.root_cause}"),
                    })
                    migrated += 1
                except Exception:
                    pass

            # Migrate metacognitive → system_state
            for row in conn.execute("SELECT data_json FROM mem_metacognitive").fetchall():
                try:
                    m_data = json.loads(row[0])
                    meta = MetacognitiveRecord(
                        id=m_data["id"],
                        strategy_name=m_data.get("strategy_name", ""),
                        problem_domain=m_data.get("problem_domain", ""),
                        compute_tier_used=m_data.get("compute_tier_used", "NORMAL"),
                        effective_gain=m_data.get("effective_gain", 0.8),
                        cost_efficiency=m_data.get("cost_efficiency", 0.9),
                        timestamp=m_data.get("timestamp", time.time()),
                    )
                    self._metacognitive[meta.id] = meta
                    self._memories["system_state"].append({
                        "id": f"mem_{uuid.uuid4().hex[:12]}",
                        "content": f"Strategy: {meta.strategy_name} on "
                                   f"{meta.problem_domain} "
                                   f"(gain={meta.effective_gain:.2f})",
                        "domain": "system_state",
                        "importance": "medium",
                        "confidence": 0.80,
                        "source": "system",
                        "created_at": meta.timestamp,
                        "updated_at": meta.timestamp,
                        "access_count": 0,
                        "tags": ["metacognitive", "migrated"],
                        "context": {"meta_id": meta.id},
                        "history": [],
                        "hash": _content_hash(meta.strategy_name),
                    })
                    migrated += 1
                except Exception:
                    pass

            conn.close()

            if migrated > 0:
                # Persist all migrated data
                for domain in _MEMORY_DOMAINS:
                    if self._memories[domain]:
                        self._persist_domain(domain)

        except Exception:
            pass

    # ── INTERNAL: Rebuild legacy caches ───────────────────────────────────

    def _rebuild_legacy_caches(self):
        """Rebuild Episode/ProceduralRule/etc caches from unified storage."""
        # Rebuild episodes from experiences domain
        for item in self._memories.get("experiences", []):
            ctx = item.get("context", {})
            ep_id = ctx.get("episode_id")
            if ep_id and ep_id not in self._episodes:
                self._episodes[ep_id] = Episode(
                    id=ep_id,
                    goal=ctx.get("goal", ""),
                    outcome_status=ctx.get("status", "SUCCESS"),
                    reward=ctx.get("reward", 0.0),
                    actions_taken=ctx.get("actions", []),
                    duration_ms=ctx.get("duration_ms", 0.0),
                    timestamp=item.get("created_at", time.time()),
                )

        # Rebuild procedural rules from knowledge domain
        for item in self._memories.get("knowledge", []):
            ctx = item.get("context", {})
            rule_id = ctx.get("rule_id")
            if rule_id and rule_id not in self._procedural_rules:
                self._procedural_rules[rule_id] = ProceduralRule(
                    id=rule_id,
                    name=ctx.get("name", ""),
                    trigger_conditions=ctx.get("trigger_conditions", []),
                    action_procedure=ctx.get("action_procedure",
                                             item.get("content", "")),
                )

        # Rebuild failures from knowledge domain
        for item in self._memories.get("knowledge", []):
            tags = item.get("tags", [])
            if "failure" in tags:
                ctx = item.get("context", {})
                fail_id = ctx.get("failure_id")
                if fail_id and fail_id not in self._failures:
                    content = item.get("content", "")
                    # Parse "Failure: goal — type: cause"
                    parts = content.replace("Failure: ", "", 1).split(" — ", 1)
                    goal = parts[0] if parts else ""
                    detail = parts[1] if len(parts) > 1 else ""
                    type_cause = detail.split(": ", 1)
                    ftype = type_cause[0] if type_cause else "reasoning_gap"
                    cause = type_cause[1] if len(type_cause) > 1 else ""
                    self._failures[fail_id] = FailureMemoryRecord(
                        id=fail_id,
                        task_goal=goal,
                        failure_type=ftype,
                        root_cause=cause,
                        preventive_rule=ctx.get("preventive_rule", ""),
                        timestamp=item.get("created_at", time.time()),
                    )

# Backward-compatibility alias
DevelopmentalMemoryStore = SmartMemory

