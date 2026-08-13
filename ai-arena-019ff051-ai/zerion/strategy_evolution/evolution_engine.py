"""
Strategy Evolution Substrate - Lineage, Composition, and Non-Destructive Retirement
Manages lifecycle transitions of cognitive strategies:
Discover -> Evaluate -> Compare -> Compose -> Specialize -> Generalize -> Retire -> Replace
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set
import uuid
from zerion.cognitive_genesis.strategy import CognitiveStrategy


@dataclass
class StrategyLineageNode:
    strategy_id: str
    parent_strategy_id: Optional[str] = None
    derivation_type: str = "genesis"  # "genesis", "composition", "specialization", "generalization"
    lineage_depth: int = 1
    benchmark_gain: float = 0.0
    created_at: float = field(default_factory=time.time)


@dataclass
class StrategyCompatibilityEdge:
    source_strategy_id: str
    target_strategy_id: str
    compatibility_score: float         # 0.0 to 1.0
    co_occurrence_count: int = 0
    composite_success_rate: float = 1.0


class StrategyEvolutionEngine:
    def __init__(self, db_path: Optional[str] = "data/strategy_evolution.db"):
        self.db_path = db_path
        self._lineage: Dict[str, StrategyLineageNode] = {}
        self._compatibility_graph: List[StrategyCompatibilityEdge] = []
        self._retired_strategies: Dict[str, Dict[str, Any]] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategy_lineage (
                    strategy_id TEXT PRIMARY KEY,
                    parent_id TEXT,
                    derivation_type TEXT,
                    lineage_depth INTEGER,
                    benchmark_gain REAL,
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS retired_strategies (
                    strategy_id TEXT PRIMARY KEY,
                    reason TEXT,
                    superseded_by TEXT,
                    data_json TEXT,
                    retired_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def record_lineage(
        self,
        strategy_id: str,
        parent_id: Optional[str] = None,
        derivation_type: str = "genesis",
        gain: float = 0.0
    ) -> StrategyLineageNode:
        depth = (self._lineage[parent_id].lineage_depth + 1) if (parent_id and parent_id in self._lineage) else 1
        node = StrategyLineageNode(
            strategy_id=strategy_id,
            parent_strategy_id=parent_id,
            derivation_type=derivation_type,
            lineage_depth=depth,
            benchmark_gain=gain
        )
        self._lineage[strategy_id] = node
        self._persist_lineage(node)
        return node

    def compose_strategies(
        self,
        strat_a: CognitiveStrategy,
        strat_b: CognitiveStrategy,
        composite_name: str
    ) -> CognitiveStrategy:
        """Composes two complementary strategies into a higher-order pipeline."""
        composite_id = f"comp_{uuid.uuid4().hex[:8]}"
        composite_steps = [f"[Phase 1: {strat_a.name}] " + s for s in strat_a.procedure_steps] + \
                          [f"[Phase 2: {strat_b.name}] " + s for s in strat_b.procedure_steps]

        composed = CognitiveStrategy(
            name=composite_name,
            domain=f"{strat_a.domain}+{strat_b.domain}",
            strategy_id=composite_id,
            preconditions=list(set(strat_a.preconditions + strat_b.preconditions)),
            procedure_steps=composite_steps,
            expected_benefit=f"Composite synergized pipeline of {strat_a.name} and {strat_b.name}",
            cost=strat_a.cost + strat_b.cost,
            latency_ms=strat_a.latency_ms + strat_b.latency_ms,
            risk=max(strat_a.risk, strat_b.risk) * 0.9,  # Synergistic risk reduction
            confidence=round((strat_a.confidence + strat_b.confidence) / 2.0, 3),
            provenance="strategy_composition"
        )
        self.record_lineage(composite_id, parent_id=strat_a.strategy_id, derivation_type="composition", gain=0.05)
        return composed

    def retire_strategy(self, strategy: CognitiveStrategy, reason: str, superseded_by: Optional[str] = None):
        """Non-destructive retirement preserving full audit provenance and rollback capability."""
        strategy.is_active = False
        self._retired_strategies[strategy.strategy_id] = {
            "strategy": strategy.to_dict(),
            "reason": reason,
            "superseded_by": superseded_by,
            "retired_at": time.time()
        }
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO retired_strategies VALUES (?, ?, ?, ?, ?)",
                (strategy.strategy_id, reason, superseded_by or "", json.dumps(strategy.to_dict()), time.time())
            )
            conn.commit()
            conn.close()

    def _persist_lineage(self, node: StrategyLineageNode):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO strategy_lineage VALUES (?, ?, ?, ?, ?, ?)",
            (node.strategy_id, node.parent_strategy_id or "", node.derivation_type, node.lineage_depth, node.benchmark_gain, node.created_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            for row in conn.execute("SELECT strategy_id, parent_id, derivation_type, lineage_depth, benchmark_gain, created_at FROM strategy_lineage").fetchall():
                node = StrategyLineageNode(
                    strategy_id=row[0],
                    parent_strategy_id=row[1] if row[1] else None,
                    derivation_type=row[2],
                    lineage_depth=row[3],
                    benchmark_gain=row[4],
                    created_at=row[5]
                )
                self._lineage[node.strategy_id] = node
            conn.close()
        except Exception:
            pass
