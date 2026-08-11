"""
Unified 7-Domain Developmental Memory Store
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
from zerion.memory.episodic import Episode
from zerion.memory.procedural import ProceduralRule
from zerion.memory.semantic import SemanticConcept, CausalLink, FailureMemoryRecord, MetacognitiveRecord
from zerion.memory.distillation import ExperienceDistiller


class DevelopmentalMemoryStore:
    def __init__(self, db_path: Optional[str] = "data/developmental_memory.db"):
        self.db_path = db_path
        self.distiller = ExperienceDistiller(min_pattern_support=2)
        self._episodes: Dict[str, Episode] = {}
        self._procedural_rules: Dict[str, ProceduralRule] = {}
        self._concepts: Dict[str, SemanticConcept] = {}
        self._causal_links: Dict[str, CausalLink] = {}
        self._failures: Dict[str, FailureMemoryRecord] = {}
        self._metacognitive: Dict[str, MetacognitiveRecord] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("CREATE TABLE IF NOT EXISTS mem_episodes (id TEXT PRIMARY KEY, data_json TEXT, timestamp REAL);")
            conn.execute("CREATE TABLE IF NOT EXISTS mem_procedural (id TEXT PRIMARY KEY, data_json TEXT, updated_at REAL);")
            conn.execute("CREATE TABLE IF NOT EXISTS mem_semantic (id TEXT PRIMARY KEY, data_json TEXT, updated_at REAL);")
            conn.execute("CREATE TABLE IF NOT EXISTS mem_causal (id TEXT PRIMARY KEY, data_json TEXT, updated_at REAL);")
            conn.execute("CREATE TABLE IF NOT EXISTS mem_failures (id TEXT PRIMARY KEY, data_json TEXT, timestamp REAL);")
            conn.execute("CREATE TABLE IF NOT EXISTS mem_metacognitive (id TEXT PRIMARY KEY, data_json TEXT, timestamp REAL);")
            conn.commit()
            conn.close()

    # --- Domain 1: Episodic ---
    def record_episode(self, episode: Episode) -> str:
        self._episodes[episode.id] = episode
        self._persist("mem_episodes", episode.id, episode.to_dict(), episode.timestamp)
        return episode.id

    def list_episodes(self, limit: int = 50) -> List[Episode]:
        return sorted(self._episodes.values(), key=lambda e: e.timestamp, reverse=True)[:limit]

    # --- Domain 2: Procedural ---
    def register_procedural_rule(self, rule: ProceduralRule) -> str:
        self._procedural_rules[rule.id] = rule
        self._persist("mem_procedural", rule.id, rule.to_dict(), rule.updated_at)
        return rule.id

    def find_procedural_rule(self, query: str) -> Optional[ProceduralRule]:
        q_words = set(query.lower().replace("_", " ").split())
        candidates = []
        for r in self._procedural_rules.values():
            # Check name or conditions
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
        return sorted(self._procedural_rules.values(), key=lambda r: r.reliability, reverse=True)

    # --- Domain 3: Semantic ---
    def record_concept(self, concept: SemanticConcept):
        self._concepts[concept.concept_id] = concept
        self._persist("mem_semantic", concept.concept_id, concept.to_dict(), concept.updated_at)

    # --- Domain 4: Causal ---
    def record_causal_link(self, link: CausalLink):
        self._causal_links[link.id] = link
        self._persist("mem_causal", link.id, link.to_dict(), link.updated_at)

    # --- Domain 5: Failure ---
    def record_failure(self, failure: FailureMemoryRecord) -> str:
        self._failures[failure.id] = failure
        self._persist("mem_failures", failure.id, failure.to_dict(), failure.timestamp)
        return failure.id

    def list_failures(self, failure_type: Optional[str] = None) -> List[FailureMemoryRecord]:
        if failure_type:
            return [f for f in self._failures.values() if f.failure_type == failure_type]
        return list(self._failures.values())

    # --- Domain 6 & 7: Metacognitive & Capability ---
    def record_metacognitive(self, meta: MetacognitiveRecord):
        self._metacognitive[meta.id] = meta
        self._persist("mem_metacognitive", meta.id, meta.to_dict(), meta.timestamp)

    # --- Experience Distillation ---
    def trigger_distillation(self) -> List[ProceduralRule]:
        new_rules = self.distiller.distill_episodes(list(self._episodes.values()))
        for r in new_rules:
            self.register_procedural_rule(r)
        return new_rules

    def _persist(self, table: str, item_id: str, data: dict, ts: float):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?)", (item_id, json.dumps(data), ts))
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            # Episodes
            for row in conn.execute("SELECT data_json FROM mem_episodes").fetchall():
                ep = Episode.from_dict(json.loads(row[0]))
                self._episodes[ep.id] = ep
            # Procedural
            for row in conn.execute("SELECT data_json FROM mem_procedural").fetchall():
                r = ProceduralRule.from_dict(json.loads(row[0]))
                self._procedural_rules[r.id] = r
            # Failures
            for row in conn.execute("SELECT data_json FROM mem_failures").fetchall():
                f_data = json.loads(row[0])
                f = FailureMemoryRecord(
                    id=f_data["id"],
                    task_goal=f_data.get("task_goal", ""),
                    failure_type=f_data.get("failure_type", "reasoning_gap"),
                    root_cause=f_data.get("root_cause", ""),
                    preventive_rule=f_data.get("preventive_rule", ""),
                    recurrence_count=f_data.get("recurrence_count", 1),
                    timestamp=f_data.get("timestamp", time.time())
                )
                self._failures[f.id] = f
            conn.close()
        except Exception:
            pass
