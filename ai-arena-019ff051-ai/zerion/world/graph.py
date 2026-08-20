"""
Entity-Relation-State World Graph with Epistemic Annotations
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set
from zerion.world.epistemic import EpistemicStatus, EpistemicValue
from zerion.world.causal import CausalHypothesis


@dataclass
class WorldNode:
    id: str
    node_type: str  # "entity", "state", "resource", "constraint", "dependency"
    name: str
    attributes: Dict[str, EpistemicValue] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def set_attribute(self, key: str, value: Any, status: EpistemicStatus, confidence: float = 1.0, source: str = "environment"):
        self.attributes[key] = EpistemicValue(value=value, status=status, confidence=confidence, source=source)
        self.updated_at = time.time()

    def get_attribute(self, key: str) -> Optional[EpistemicValue]:
        return self.attributes.get(key)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "node_type": self.node_type,
            "name": self.name,
            "attributes": {k: v.to_dict() for k, v in self.attributes.items()},
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorldNode":
        attrs = {
            k: EpistemicValue.from_dict(v) for k, v in data.get("attributes", {}).items()
        }
        return cls(
            id=data["id"],
            node_type=data.get("node_type", "entity"),
            name=data.get("name", data["id"]),
            attributes=attrs,
            updated_at=data.get("updated_at", time.time())
        )


@dataclass
class WorldEdge:
    source_id: str
    target_id: str
    relation: str  # "depends_on", "causes", "constrains", "contains", "produces"
    epistemic: EpistemicValue = field(default_factory=lambda: EpistemicValue(value=1.0, status=EpistemicStatus.OBSERVED))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
            "epistemic": self.epistemic.to_dict(),
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorldEdge":
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            relation=data["relation"],
            epistemic=EpistemicValue.from_dict(data.get("epistemic", {})),
            metadata=data.get("metadata", {})
        )


class WorldModel:
    def __init__(self, db_path: Optional[str] = "data/world_model.db"):
        self.db_path = db_path
        self._nodes: Dict[str, WorldNode] = {}
        self._edges: List[WorldEdge] = []
        self._causal_hypotheses: Dict[str, CausalHypothesis] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS world_nodes (
                    id TEXT PRIMARY KEY,
                    node_type TEXT,
                    name TEXT,
                    data_json TEXT,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS world_edges (
                    source_id TEXT,
                    target_id TEXT,
                    relation TEXT,
                    data_json TEXT,
                    PRIMARY KEY(source_id, target_id, relation)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS causal_hypotheses (
                    id TEXT PRIMARY KEY,
                    data_json TEXT,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()

    def upsert_node(self, node: WorldNode):
        self._nodes[node.id] = node
        self._persist_node(node)

    def get_node(self, node_id: str) -> Optional[WorldNode]:
        return self._nodes.get(node_id)

    def add_edge(self, edge: WorldEdge):
        self._edges = [e for e in self._edges if not (e.source_id == edge.source_id and e.target_id == edge.target_id and e.relation == edge.relation)]
        self._edges.append(edge)
        self._persist_edge(edge)

    def add_causal_hypothesis(self, hypothesis: CausalHypothesis) -> str:
        self._causal_hypotheses[hypothesis.id] = hypothesis
        self._persist_causal(hypothesis)
        return hypothesis.id

    def get_causal_hypothesis(self, hyp_id: str) -> Optional[CausalHypothesis]:
        return self._causal_hypotheses.get(hyp_id)

    def list_nodes(self, node_type: Optional[str] = None) -> List[WorldNode]:
        if node_type:
            return [n for n in self._nodes.values() if n.node_type == node_type]
        return list(self._nodes.values())

    def get_edges_for(self, node_id: str, direction: str = "out") -> List[WorldEdge]:
        if direction == "out":
            return [e for e in self._edges if e.source_id == node_id]
        elif direction == "in":
            return [e for e in self._edges if e.target_id == node_id]
        return [e for e in self._edges if e.source_id == node_id or e.target_id == node_id]

    def _persist_node(self, node: WorldNode):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO world_nodes VALUES (?, ?, ?, ?, ?)",
            (node.id, node.node_type, node.name, json.dumps(node.to_dict()), node.updated_at)
        )
        conn.commit()
        conn.close()

    def _persist_edge(self, edge: WorldEdge):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO world_edges VALUES (?, ?, ?, ?)",
            (edge.source_id, edge.target_id, edge.relation, json.dumps(edge.to_dict()))
        )
        conn.commit()
        conn.close()

    def _persist_causal(self, hyp: CausalHypothesis):
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO causal_hypotheses VALUES (?, ?, ?)",
            (hyp.id, json.dumps(hyp.to_dict()), hyp.updated_at)
        )
        conn.commit()
        conn.close()

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT data_json FROM world_nodes")
            for row in cursor.fetchall():
                node = WorldNode.from_dict(json.loads(row[0]))
                self._nodes[node.id] = node

            cursor = conn.execute("SELECT data_json FROM world_edges")
            for row in cursor.fetchall():
                edge = WorldEdge.from_dict(json.loads(row[0]))
                self._edges.append(edge)

            cursor = conn.execute("SELECT data_json FROM causal_hypotheses")
            for row in cursor.fetchall():
                hyp = CausalHypothesis.from_dict(json.loads(row[0]))
                self._causal_hypotheses[hyp.id] = hyp

            conn.close()
        except Exception:
            pass
