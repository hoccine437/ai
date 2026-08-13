"""
Slice 8 — Continuous monitoring & controlled self-improvement loop.

A background cadence that runs the Slice 7 machinery on REAL runtime timing
instead of explicit calls:

  OBSERVE (telemetry) -> DETECT BOTTLENECK -> COLLECT EVIDENCE ->
  (persistent bottleneck) -> PROPOSE -> GATE (analyze/test/benchmark/approve) ->
  PROMOTE -> MONITOR REGRESSION -> ROLLBACK IF NEEDED

The loop never invents data: it scans the persisted telemetry/bottleneck/
proposal stores exactly like the explicit runtime calls do. A bottleneck is
only marked persistent after it has been sighted across configurable
consecutive monitor cycles. Regression detection only looks at APPROVED
proposals through the Slice 7 gate, and auto-rollback restores the
snapshot-taken-before-promotion (the safe, known-good state).

Auto-proposing is opt-in: when enabled, a caller-supplied proposal_factory
turns a persistent bottleneck into an ImprovementProposal that must still
survive the full gate. Never auto-generates code.

Sighting/cycle history is persisted with the SQLite-WAL + SHA-256 checksum
pattern (Slices 1-7), so cadence and persistence survive restarts.
"""

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
from typing import Any, Callable, Dict, List, Optional

from zerion.runtime.events import Event, EventType

from zerion.cognitive_os.bottlenecks import BottleneckReport
from zerion.cognitive_os.improvement import ImprovementProposal, ProposalStatus


class MonitorIntegrityError(RuntimeError):
    pass


@dataclass
class MonitorConfig:
    """Cadence + thresholds for the background monitor loop.

    persistent_cycles: how many consecutive cycles the same (type, component)
        must be sighted before it is considered a PERSISTENT bottleneck.
    auto_rollback: when a post-promotion regression is detected, roll back to
        the snapshot taken before promotion (restores known-good state).
        Default ON because rollback is the bounded, safe action.
    auto_propose: when a bottleneck is persistent, create an improvement
        proposal via the caller-supplied proposal_factory. Default OFF —
        proposals are never fabricated; they require a real design step.
    """
    interval_s: float = 30.0
    persistent_cycles: int = 3
    auto_rollback: bool = True
    auto_propose: bool = False


@dataclass
class MonitorCycle:
    """Result of one monitor scan cycle (persisted)."""
    cycle_id: str = field(default_factory=lambda: f"cyc_{uuid.uuid4().hex[:10]}")
    seq: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    bottlenecks_new: List[str] = field(default_factory=list)
    unresolved_bottlenecks: List[Dict[str, Any]] = field(default_factory=list)
    persistent_bottlenecks: List[Dict[str, Any]] = field(default_factory=list)
    proposals_created: List[str] = field(default_factory=list)
    regressions: List[str] = field(default_factory=list)
    rolled_back: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "seq": self.seq,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "bottlenecks_new": list(self.bottlenecks_new),
            "unresolved_bottlenecks": list(self.unresolved_bottlenecks),
            "persistent_bottlenecks": list(self.persistent_bottlenecks),
            "proposals_created": list(self.proposals_created),
            "regressions": list(self.regressions),
            "rolled_back": list(self.rolled_back),
            "errors": list(self.errors),
        }


class MonitorStore:
    """SQLite-WAL + SHA-256 persistence for monitor cycles + sightings."""

    def __init__(self, db_path: Optional[str] = "data/monitor.db",
                 strict_load: bool = True):
        self.db_path = db_path
        self.strict_load = strict_load
        self.load_errors: List[str] = []
        self._cycles: Dict[str, MonitorCycle] = {}
        self._init_db()
        self.load()

    def _init_db(self):
        if not self.db_path:
            return
        p = Path(self.db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cycles (
                cycle_id TEXT PRIMARY KEY,
                seq INTEGER UNIQUE,
                payload TEXT NOT NULL,
                checksum TEXT NOT NULL,
                started_at REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sightings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bottleneck_type TEXT,
                component TEXT,
                cycle_seq INTEGER,
                seen_at REAL
            )
        """)
        conn.commit()
        conn.close()

    @staticmethod
    def _checksum(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def max_cycle_seq(self) -> int:
        if not self.db_path or not Path(self.db_path).exists():
            return 0
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT MAX(seq) FROM cycles").fetchone()
            return int(row[0] or 0)
        finally:
            conn.close()

    def put_cycle(self, cycle: MonitorCycle) -> MonitorCycle:
        """Persist a cycle, assigning its monotonic seq on first write."""
        if cycle.seq == 0:
            cycle.seq = self.max_cycle_seq() + 1
        self._cycles[cycle.cycle_id] = cycle
        if not self.db_path:
            return cycle
        payload = json.dumps(cycle.to_dict(), sort_keys=True, separators=(",", ":"))
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cycles VALUES (?, ?, ?, ?, ?)",
                (cycle.cycle_id, cycle.seq, payload,
                 self._checksum(payload), cycle.started_at))
            conn.commit()
        finally:
            conn.close()
        return cycle

    def record_sighting(self, bottleneck_type: str, component: str,
                        cycle_seq: int) -> None:
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO sightings (bottleneck_type, component, cycle_seq, seen_at) "
                "VALUES (?, ?, ?, ?)",
                (bottleneck_type, component, cycle_seq, time.time()))
            conn.commit()
        finally:
            conn.close()

    def list_persistent(self, threshold: int) -> List[Dict[str, Any]]:
        """(type, component) pairs sighted in >= threshold of the most recent
        `threshold` consecutive cycles. Requires real repeated evidence — a
        bottleneck seen once is never persistent."""
        if threshold < 2 or not self.db_path or not Path(self.db_path).exists():
            return []
        max_seq = self.max_cycle_seq()
        if max_seq < threshold:
            return []
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT bottleneck_type, component, "
                "COUNT(DISTINCT cycle_seq) AS sightings "
                "FROM sightings "
                "WHERE cycle_seq > ? "
                "GROUP BY bottleneck_type, component "
                "HAVING sightings >= ? "
                "ORDER BY bottleneck_type, component",
                (max_seq - threshold, threshold)).fetchall()
            return [{"type": t, "component": c, "sightings": int(n)}
                    for t, c, n in rows]
        finally:
            conn.close()

    def list_cycles(self, limit: int = 50) -> List[MonitorCycle]:
        cycles = sorted(self._cycles.values(), key=lambda c: c.seq)
        return cycles[-limit:]

    def count(self) -> int:
        return len(self._cycles)

    def load(self):
        if not self.db_path or not Path(self.db_path).exists():
            return
        try:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute("SELECT payload, checksum FROM cycles").fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.load_errors.append(f"{type(e).__name__}: {e}")
            if self.strict_load:
                raise MonitorIntegrityError(
                    f"Failed to load monitor cycles from {self.db_path}: {e}") from e
            return
        for payload, stored_checksum in rows:
            try:
                if self._checksum(payload) != stored_checksum:
                    raise MonitorIntegrityError(
                        "monitor cycle checksum mismatch (corrupt write)")
                data = json.loads(payload)
                self._cycles[data["cycle_id"]] = MonitorCycle(
                    cycle_id=data["cycle_id"], seq=data.get("seq", 0),
                    started_at=data.get("started_at", time.time()),
                    finished_at=data.get("finished_at"),
                    bottlenecks_new=list(data.get("bottlenecks_new", [])),
                    unresolved_bottlenecks=list(data.get("unresolved_bottlenecks", [])),
                    persistent_bottlenecks=list(data.get("persistent_bottlenecks", [])),
                    proposals_created=list(data.get("proposals_created", [])),
                    regressions=list(data.get("regressions", [])),
                    rolled_back=list(data.get("rolled_back", [])),
                    errors=list(data.get("errors", [])),
                )
            except Exception as e:  # noqa: BLE001
                self.load_errors.append(f"{type(e).__name__}: {e}")
                if self.strict_load:
                    raise MonitorIntegrityError(
                        f"Failed to load monitor cycles from {self.db_path}: {e}") from e


# A factory receives a persistent-bottleneck dict
# {"type", "component", "sightings"} and returns an ImprovementProposal that
# must still pass the full Slice 7 gate. Returning None means "no proposal".
ProposalFactory = Callable[[Dict[str, Any]], Optional[ImprovementProposal]]


class MonitorScheduler:
    """Background cadence loop over the real runtime's Slice 7 machinery.

    Depends on the runtime only through the methods it actually calls
    (detect_bottlenecks, monitor_proposal_regression, rollback_modification,
    proposal_store, event_bus) — no import cycle, no duplicate systems.
    """

    def __init__(self, runtime: Any,
                 config: Optional[MonitorConfig] = None,
                 store: Optional[MonitorStore] = None,
                 proposal_factory: Optional[ProposalFactory] = None):
        self.runtime = runtime
        self.config = config or MonitorConfig()
        self.store = store or MonitorStore(db_path=None)
        self.proposal_factory = proposal_factory
        self._task: Optional[Any] = None
        self._running = False
        self.last_cycle: Optional[MonitorCycle] = None
        self.last_error: str = ""

    # -- one cycle ----------------------------------------------------------

    async def run_once(self) -> MonitorCycle:
        """One full scan: detect bottlenecks, sight unresolved bottlenecks,
        flag persistent ones, optionally propose, monitor APPROVED proposals
        for regression, and auto-rollback when configured."""
        cycle = MonitorCycle(started_at=time.time())
        self.store.put_cycle(cycle)  # assigns cycle.seq
        errors: List[str] = []
        try:
            # 1. OBSERVE + DETECT: real telemetry -> bottleneck reports.
            reports = await self.runtime.detect_bottlenecks()
            cycle.bottlenecks_new = [r.id for r in reports]

            # 2. Sight every currently-unresolved bottleneck (deduped by the
            #    detector's store). Persistence is real evidence across cycles.
            unresolved = []
            for report in self.runtime.bottleneck_store.list():
                self.store.record_sighting(
                    report.type, report.affected_component, cycle.seq)
                unresolved.append({
                    "type": report.type,
                    "component": report.affected_component,
                    "severity": report.severity,
                    "confidence": report.confidence,
                    "report_id": report.id,
                })
            cycle.unresolved_bottlenecks = unresolved

            # 3. Persistent bottlenecks (evidence across consecutive cycles).
            for pb in self.store.list_persistent(self.config.persistent_cycles):
                cycle.persistent_bottlenecks.append(pb)
                if self.config.auto_propose and self.proposal_factory is not None:
                    try:
                        proposal = self.proposal_factory(pb)
                        if proposal is not None:
                            self.runtime.proposal_store.put(proposal)
                            cycle.proposals_created.append(proposal.proposal_id)
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"propose: {type(e).__name__}: {e}")

            # 4. Post-promotion regression monitoring (real telemetry only).
            for proposal in self.runtime.proposal_store.list(
                    status=ProposalStatus.APPROVED):
                try:
                    if self.runtime.monitor_proposal_regression(proposal):
                        cycle.regressions.append(proposal.proposal_id)
                        await self.runtime.event_bus.publish(Event(
                            event_type=EventType.REGRESSION_DETECTED,
                            payload={"proposal_id": proposal.proposal_id,
                                     "target_component": proposal.target_component,
                                     "modification_type":
                                         proposal.modification_type.value},
                            source="monitor",
                            priority=80,
                        ), dispatch_immediately=True)
                        if self.config.auto_rollback:
                            rb = await self.runtime.rollback_modification(
                                proposal,
                                reason="monitor: post-promotion regression")
                            cycle.rolled_back.append({
                                "proposal_id": proposal.proposal_id,
                                "ok": rb.ok,
                                "restored_version": rb.restored_version,
                                "message": rb.message,
                            })
                except Exception as e:  # noqa: BLE001
                    errors.append(
                        f"regression({proposal.proposal_id}): "
                        f"{type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"cycle: {type(e).__name__}: {e}")

        cycle.finished_at = time.time()
        cycle.errors = errors
        self.store.put_cycle(cycle)  # update payload with final results
        self.last_cycle = cycle
        await self.runtime.event_bus.publish(Event(
            event_type=EventType.MONITOR_CYCLE_COMPLETED,
            payload=cycle.to_dict(),
            source="monitor",
            priority=50,
        ), dispatch_immediately=True)
        return cycle

    # -- background loop ----------------------------------------------------

    async def start(self) -> None:
        """Start the background loop. Idempotent."""
        if self._running:
            return
        self._running = True
        self._task = self._loop_task()

    def _loop_task(self):
        async def _loop():
            while self._running:
                try:
                    await self.run_once()
                except Exception as e:  # noqa: BLE001 — never kill the loop
                    self.last_error = f"{type(e).__name__}: {e}"
                await asyncio.sleep(self.config.interval_s)
        return asyncio.ensure_future(_loop())

    async def stop(self) -> None:
        """Stop the background loop. Idempotent."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except Exception:  # noqa: BLE001 — CancelledError and friends
                pass
            self._task = None

    @property
    def running(self) -> bool:
        return self._running
