"""
Evidence Engine and Epistemic Assertion Ledger
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
from zerion.evidence.claim import Claim, EvidenceItem, EpistemicLevel, VerificationMethod
from zerion.evidence.verifier import ClaimVerifier


class EvidenceEngine:
    def __init__(self, db_path: Optional[str] = "data/evidence.db", verifier: Optional[ClaimVerifier] = None):
        self.db_path = db_path
        self.verifier = verifier or ClaimVerifier()
        self._claims: Dict[str, Claim] = {}
        self._evidence: Dict[str, EvidenceItem] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS evidence_items (
                    id TEXT PRIMARY KEY,
                    data_json TEXT,
                    timestamp REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    id TEXT PRIMARY KEY,
                    data_json TEXT,
                    epistemic_level TEXT,
                    confidence REAL,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def add_evidence(self, item: EvidenceItem) -> str:
        self._evidence[item.id] = item
        self._persist_evidence(item)
        return item.id

    def record_claim(self, statement: str, supporting_evidence: Optional[List[EvidenceItem]] = None) -> Claim:
        claim = Claim(statement=statement)
        if supporting_evidence:
            for evi in supporting_evidence:
                self.add_evidence(evi)
                claim.supporting_evidence_ids.append(evi.id)

        level, conf = self.verifier.evaluate_claim(claim, list(self._evidence.values()))
        claim.epistemic_level = level
        claim.confidence = conf
        self._claims[claim.id] = claim
        self._persist_claim(claim)
        return claim

    def attach_evidence_to_claim(self, claim_id: str, evidence: EvidenceItem, contradicts: bool = False):
        self.add_evidence(evidence)
        claim = self._claims.get(claim_id)
        if claim:
            if contradicts:
                if evidence.id not in claim.contradicting_evidence_ids:
                    claim.contradicting_evidence_ids.append(evidence.id)
            else:
                if evidence.id not in claim.supporting_evidence_ids:
                    claim.supporting_evidence_ids.append(evidence.id)
            level, conf = self.verifier.evaluate_claim(claim, list(self._evidence.values()))
            claim.epistemic_level = level
            claim.confidence = conf
            claim.updated_at = time.time()
            self._persist_claim(claim)

    def query_belief(self, statement: str) -> Dict[str, Any]:
        """
        Evaluates a statement against the evidence ledger.
        If evidence is insufficient, explicitly returns 'I don't know'.
        """
        for claim in self._claims.values():
            if claim.statement.lower() == statement.lower() or statement.lower() in claim.statement.lower() or claim.statement.lower() in statement.lower():
                if claim.epistemic_level == EpistemicLevel.UNKNOWN:
                    return {
                        "statement": statement,
                        "status": "UNKNOWN",
                        "answer": "I don't know. The available evidence is insufficient to verify this claim.",
                        "confidence": claim.confidence,
                        "evidence_count": len(claim.supporting_evidence_ids)
                    }
                return {
                    "statement": statement,
                    "status": claim.epistemic_level.value,
                    "answer": f"Claim is {claim.epistemic_level.value} with confidence {claim.confidence * 100:.1f}%.",
                    "confidence": claim.confidence,
                    "supporting_evidence_count": len(claim.supporting_evidence_ids),
                    "contradicting_evidence_count": len(claim.contradicting_evidence_ids)
                }

        # Statement not in ledger
        return {
            "statement": statement,
            "status": "UNKNOWN",
            "answer": "I don't know. No empirical or deductive observations have been recorded for this statement.",
            "confidence": 0.0,
            "evidence_count": 0
        }

    def _persist_evidence(self, item: EvidenceItem):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO evidence_items VALUES (?, ?, ?)",
            (item.id, json.dumps(item.to_dict()), item.timestamp)
        )
        conn.commit()
        conn.close()

    def _persist_claim(self, claim: Claim):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO claims VALUES (?, ?, ?, ?, ?)",
            (claim.id, json.dumps(claim.to_dict()), claim.epistemic_level.value, claim.confidence, claim.updated_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT data_json FROM evidence_items")
            for row in cursor.fetchall():
                evi = EvidenceItem.from_dict(json.loads(row[0]))
                self._evidence[evi.id] = evi

            cursor = conn.execute("SELECT data_json FROM claims")
            for row in cursor.fetchall():
                clm = Claim.from_dict(json.loads(row[0]))
                self._claims[clm.id] = clm
            conn.close()
        except Exception:
            pass
