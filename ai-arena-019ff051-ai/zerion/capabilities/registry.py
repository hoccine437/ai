"""
Dynamic Capability Registry and Lifecycle Manager
"""

import json
from pathlib import Path
import sqlite3
import time
from typing import Dict, List, Optional
from zerion.capabilities.birth import BornCapability
from zerion.self_model.capabilities import CapabilityRecord


class DynamicCapabilityRegistry:
    def __init__(self, db_path: Optional[str] = "data/capabilities.db"):
        self.db_path = db_path
        self._born_capabilities: Dict[str, BornCapability] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS born_capabilities (
                    name TEXT PRIMARY KEY,
                    category TEXT,
                    spec TEXT,
                    code TEXT,
                    benchmark_score REAL,
                    is_validated INTEGER,
                    created_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def register_born_capability(self, born: BornCapability) -> bool:
        if not born.is_validated:
            return False
        self._born_capabilities[born.name] = born
        if self.db_path:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT OR REPLACE INTO born_capabilities VALUES (?, ?, ?, ?, ?, ?, ?)",
                (born.name, born.category, born.specification, born.implementation_code, born.benchmark_score, 1 if born.is_validated else 0, born.created_at)
            )
            conn.commit()
            conn.close()
        return True

    def get_born_capability(self, name: str) -> Optional[BornCapability]:
        return self._born_capabilities.get(name)

    def list_born_capabilities(self) -> List[BornCapability]:
        return list(self._born_capabilities.values())

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT name, category, spec, code, benchmark_score, is_validated, created_at FROM born_capabilities")
            for row in cursor.fetchall():
                born = BornCapability(
                    name=row[0],
                    category=row[1],
                    specification=row[2],
                    implementation_code=row[3],
                    unit_tests_code="",
                    benchmark_score=row[4],
                    is_validated=bool(row[5]),
                    created_at=row[6]
                )
                self._born_capabilities[born.name] = born
            conn.close()
        except Exception:
            pass
