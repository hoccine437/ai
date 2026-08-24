"""
Cognitive Strategy Registry and Persistence Ledger
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional
from zerion.cognitive_genesis.strategy import CognitiveStrategy


class StrategyRegistry:
    def __init__(self, db_path: Optional[str] = "data/strategies.db"):
        self.db_path = db_path
        self._strategies: Dict[str, CognitiveStrategy] = {}
        self._init_db()
        self._bootstrap_native_strategies()
        self.load()

    def _bootstrap_native_strategies(self):
        core_strats = [
            CognitiveStrategy(
                name="IntervalBisectionDebugging",
                domain="software_engineering",
                preconditions=["Ordered state space", "Monotonic error boundary"],
                procedure_steps=["1. Identify mid-point", "2. Test predicate", "3. Discard partition"],
                expected_benefit="O(log N) fault localization",
                confidence=0.96,
                provenance="native_core"
            ),
            CognitiveStrategy(
                name="CausalCounterfactualProbe",
                domain="epistemic_discovery",
                preconditions=["Identified causal hypothesis", "Controllable variable"],
                procedure_steps=["1. Set control state", "2. Observe effect", "3. Apply intervention", "4. Compare delta"],
                expected_benefit="Direct empirical falsification",
                confidence=0.94,
                provenance="native_core"
            ),
            CognitiveStrategy(
                name="AdversarialInvariantDefense",
                domain="security_and_verification",
                preconditions=["Candidate conclusion asserted", "Core safety invariants defined"],
                procedure_steps=["1. Search edge cases", "2. Test boundary mutations", "3. Check invariant violations"],
                expected_benefit="Guaranteed invariant integrity",
                confidence=0.99,
                provenance="native_core"
            )
        ]
        for s in core_strats:
            if s.strategy_id not in self._strategies:
                self._strategies[s.strategy_id] = s

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS strategies (
                    strategy_id TEXT PRIMARY KEY,
                    name TEXT,
                    domain TEXT,
                    data_json TEXT,
                    is_active INTEGER,
                    reliability REAL,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def register_strategy(self, strategy: CognitiveStrategy) -> str:
        self._strategies[strategy.strategy_id] = strategy
        self._persist_strategy(strategy)
        return strategy.strategy_id

    def get_strategy(self, strategy_id: str) -> Optional[CognitiveStrategy]:
        return self._strategies.get(strategy_id)

    def find_strategy_for_domain(self, domain: str) -> List[CognitiveStrategy]:
        d_lower = domain.lower()
        matches = [s for s in self._strategies.values() if s.is_active and (s.domain.lower() in d_lower or d_lower in s.domain.lower() or s.domain == "general")]
        return sorted(matches, key=lambda s: s.reliability, reverse=True)

    def list_strategies(self, active_only: bool = True) -> List[CognitiveStrategy]:
        strats = list(self._strategies.values())
        if active_only:
            strats = [s for s in strats if s.is_active]
        return sorted(strats, key=lambda s: s.reliability, reverse=True)

    def _persist_strategy(self, strategy: CognitiveStrategy):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO strategies VALUES (?, ?, ?, ?, ?, ?, ?)",
            (strategy.strategy_id, strategy.name, strategy.domain, json.dumps(strategy.to_dict()), 1 if strategy.is_active else 0, strategy.reliability, strategy.updated_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT data_json FROM strategies")
            for row in cursor.fetchall():
                strat = CognitiveStrategy.from_dict(json.loads(row[0]))
                self._strategies[strat.strategy_id] = strat
            conn.close()
        except Exception:
            pass
