"""
Question Graph (DAG) with Priority Traversal and Dependency Resolution
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Dict, List, Optional, Set
from zerion.questions.question import Question, QuestionStatus
from zerion.questions.scorer import QuestionScorer


class QuestionGraph:
    def __init__(self, db_path: Optional[str] = "data/questions.db", scorer: Optional[QuestionScorer] = None):
        self.db_path = db_path
        self.scorer = scorer or QuestionScorer()
        self._questions: Dict[str, Question] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    data_json TEXT,
                    priority REAL,
                    status TEXT,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def add_question(self, question: Question) -> str:
        self.scorer.score(question)
        self._questions[question.id] = question
        self._persist_question(question)
        return question.id

    def get_question(self, q_id: str) -> Optional[Question]:
        return self._questions.get(q_id)

    def list_questions(self, status: Optional[QuestionStatus] = None) -> List[Question]:
        qs = list(self._questions.values())
        if status:
            qs = [q for q in qs if q.status == status]
        return sorted(qs, key=lambda q: q.priority, reverse=True)

    def get_ready_questions(self) -> List[Question]:
        """
        Returns questions whose dependencies have all been ANSWERED or FALSIFIED.
        """
        ready = []
        for q in self._questions.values():
            if q.status not in (QuestionStatus.PROPOSED, QuestionStatus.ACTIVE):
                continue
            deps_met = True
            for dep_id in q.dependencies:
                dep_q = self._questions.get(dep_id)
                if not dep_q or dep_q.status not in (QuestionStatus.ANSWERED, QuestionStatus.FALSIFIED):
                    deps_met = False
                    break
            if deps_met:
                ready.append(q)
        return sorted(ready, key=lambda q: q.priority, reverse=True)

    def answer_question(self, q_id: str, answer: str, evidence_ids: Optional[List[str]] = None):
        q = self._questions.get(q_id)
        if q:
            q.status = QuestionStatus.ANSWERED
            q.answer = answer
            if evidence_ids:
                q.evidence_ids.extend(evidence_ids)
            q.updated_at = time.time()
            self._persist_question(q)

    def _persist_question(self, q: Question):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO questions VALUES (?, ?, ?, ?, ?)",
            (q.id, json.dumps(q.to_dict()), q.priority, q.status.value, q.updated_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT data_json FROM questions")
            for row in cursor.fetchall():
                q = Question.from_dict(json.loads(row[0]))
                self._questions[q.id] = q
            conn.close()
        except Exception:
            pass
