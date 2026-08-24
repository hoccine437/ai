"""
Cognitive Genome Manager - Persistence, Lineage, and Mutation Guardrails
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
from zerion.cognitive_genome.genome import CognitiveGenome, GenomeMutationProposal
from zerion.cognitive_genome.phenotype import CognitivePhenotype, PhenotypeFactory


class GenomeManager:
    """
    Manages durable persistence of the Cognitive Genome, lineage branching,
    and rollback-safe mutation promotion.
    """
    def __init__(self, db_path: Optional[str] = "data/cognitive_genome.db"):
        self.db_path = db_path
        self._current_genome: CognitiveGenome = CognitiveGenome()
        self._lineage_history: List[CognitiveGenome] = [self._current_genome]
        self._dynamic_phenotypes: Dict[str, CognitivePhenotype] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS genome_versions (
                    version INTEGER PRIMARY KEY,
                    genome_id TEXT,
                    lineage_id TEXT,
                    digest TEXT,
                    data_json TEXT,
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dynamic_phenotypes (
                    name TEXT PRIMARY KEY,
                    domain TEXT,
                    data_json TEXT,
                    created_at REAL
                )
            """)
            conn.commit()
            conn.close()

    @property
    def current_genome(self) -> CognitiveGenome:
        return self._current_genome

    def get_phenotype(self, task_domain_or_name: str) -> CognitivePhenotype:
        """Retrieves or derives a specialized phenotype from the current genome."""
        if task_domain_or_name in self._dynamic_phenotypes:
            return self._dynamic_phenotypes[task_domain_or_name]
        return PhenotypeFactory.derive_phenotype(self._current_genome, task_domain_or_name)

    def register_dynamic_phenotype(self, phenotype: CognitivePhenotype):
        phenotype.is_dynamic = True
        self._dynamic_phenotypes[phenotype.name] = phenotype
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO dynamic_phenotypes VALUES (?, ?, ?, ?)",
                (phenotype.name, phenotype.domain, json.dumps(phenotype.to_dict()), phenotype.created_at)
            )
            conn.commit()
            conn.close()

    def propose_and_apply_mutation(self, proposal: GenomeMutationProposal) -> bool:
        """Executes full mutation safety pipeline."""
        candidate = self._current_genome.clone()
        success = candidate.apply_mutation(proposal)
        if not success:
            return False

        # Invariant check
        valid, err = candidate.validate_bounds()
        if not valid:
            return False

        self._lineage_history.append(self._current_genome)
        self._current_genome = candidate
        self._persist_genome(candidate)
        return True

    def rollback(self) -> Optional[CognitiveGenome]:
        """Rolls back to previous genome version in case of benchmark regression."""
        if len(self._lineage_history) > 1:
            self._current_genome = self._lineage_history.pop()
            self._persist_genome(self._current_genome)
            return self._current_genome
        return None

    def _persist_genome(self, genome: CognitiveGenome):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO genome_versions VALUES (?, ?, ?, ?, ?, ?)",
            (genome.version, genome.genome_id, genome.lineage_id, genome.get_digest(), json.dumps(genome.to_dict()), genome.updated_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT data_json FROM genome_versions ORDER BY version DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                self._current_genome = CognitiveGenome.from_dict(json.loads(row[0]))
                self._lineage_history = [self._current_genome]

            p_cursor = conn.execute("SELECT data_json FROM dynamic_phenotypes")
            for p_row in p_cursor.fetchall():
                p_dict = json.loads(p_row[0])
                phenotype = CognitivePhenotype(
                    name=p_dict["name"],
                    domain=p_dict["domain"],
                    reasoning_depth=p_dict["reasoning_depth"],
                    parallel_width=p_dict["parallel_width"],
                    verification_ratio=p_dict["verification_ratio"],
                    adversarial_check_rate=p_dict["adversarial_check_rate"],
                    experiment_rate=p_dict["experiment_rate"],
                    exploration_ratio=p_dict["exploration_ratio"],
                    tool_policy=p_dict["tool_policy"],
                    memory_policy=p_dict["memory_policy"],
                    risk_tolerance=p_dict["risk_tolerance"],
                    max_latency_ms=p_dict["max_latency_ms"],
                    is_dynamic=True,
                    created_at=p_dict.get("created_at", time.time())
                )
                self._dynamic_phenotypes[phenotype.name] = phenotype
            conn.close()
        except Exception:
            pass
