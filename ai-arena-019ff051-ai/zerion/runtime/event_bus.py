"""
Async Event Bus with SQLite Event Persistence and Replay

Slice 1 additions (backward compatible):
- publish() validates events (unknown type, malformed payload, out-of-range priority,
  duplicate event id) and raises ValueError instead of silently accepting them.
- Each published event receives a monotonically increasing ``sequence`` so ordering is
  deterministic and inspectable.
- ``dispatch_immediately=True`` bypasses the worker queue and synchronously delivers the
  event to handlers (deterministic, used by the Cognitive Foundation runtime).
- ``drain_now()`` synchronously drains the priority queue for deterministic testing.
- ``pending_count`` exposes queued-but-undelivered events; ``dispatch_errors`` records
  handler failures without crashing the bus.
"""

import asyncio
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
from zerion.runtime.events import Event, EventType
from zerion.runtime.queue import PriorityEventQueue

EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventValidationError(ValueError):
    """Raised when an event is malformed (unknown type, bad payload, bad priority, duplicate id)."""


class AsyncEventBus:
    def __init__(self, db_path: Optional[str] = None, max_queue_capacity: int = 5000):
        self.db_path = db_path
        self.queue = PriorityEventQueue(max_capacity=max_queue_capacity)
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._wildcard_handlers: List[EventHandler] = []
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._db_conn: Optional[sqlite3.Connection] = None
        self._next_sequence: int = 1
        self._published_ids: Set[str] = set()
        self.dispatch_errors: List[Dict[str, Any]] = []
        self._init_db()
        self._resume_sequence_from_db()

    def _init_db(self):
        if self.db_path:
            p = Path(self.db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._db_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._db_conn.execute("PRAGMA journal_mode=WAL;")
            self._db_conn.execute("""
                CREATE TABLE IF NOT EXISTS events_log (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    correlation_id TEXT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    sequence INTEGER NOT NULL DEFAULT 0
                )
            """)
            # Migrate pre-existing databases created before the `sequence` column.
            columns = [r[1] for r in self._db_conn.execute("PRAGMA table_info(events_log)").fetchall()]
            if columns and "sequence" not in columns:
                self._db_conn.execute("ALTER TABLE events_log ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0")
            self._db_conn.commit()

    def subscribe(self, event_type: EventType, handler: EventHandler):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler):
        if handler not in self._wildcard_handlers:
            self._wildcard_handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler):
        if event_type in self._handlers and handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    def _validate_event(self, event: Event):
        if not isinstance(event, Event):
            raise EventValidationError(f"publish() requires an Event instance, got {type(event).__name__}")
        if not isinstance(event.event_type, EventType):
            raise EventValidationError(f"Unknown event type: {event.event_type!r}")
        if not isinstance(event.payload, dict):
            raise EventValidationError(f"Event payload must be a dict, got {type(event.payload).__name__}")
        if not isinstance(event.priority, int) or not (0 <= event.priority <= 100):
            raise EventValidationError(f"Event priority must be an int in [0, 100], got {event.priority!r}")
        if event.event_id in self._published_ids:
            raise EventValidationError(f"Duplicate event id rejected: {event.event_id}")

    def _resume_sequence_from_db(self):
        if not self._db_conn:
            return
        try:
            row = self._db_conn.execute("SELECT COALESCE(MAX(sequence), 0) FROM events_log").fetchone()
            self._next_sequence = int(row[0]) + 1 if row else 1
        except Exception:
            self._next_sequence = 1

    async def publish(self, event: Event, dispatch_immediately: bool = False) -> bool:
        """
        Validates and publishes an event.

        With ``dispatch_immediately=True`` the event is delivered to handlers synchronously
        (deterministic, no queueing). Otherwise it is queued for the worker / ``drain_now``.
        """
        self._validate_event(event)
        if event.sequence is None:
            event.sequence = self._next_sequence
        self._next_sequence += 1
        self._published_ids.add(event.event_id)

        # Persist to disk if persistence is enabled (before dispatch so a crash never
        # loses an accepted event).
        if self._db_conn:
            try:
                self._db_conn.execute(
                    "INSERT OR REPLACE INTO events_log VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.event_type.value,
                        json.dumps(event.payload),
                        event.correlation_id,
                        event.timestamp,
                        event.source,
                        event.priority,
                        event.sequence
                    )
                )
                self._db_conn.commit()
            except Exception as e:
                raise EventValidationError(f"Event persistence failed: {e}") from e

        if dispatch_immediately:
            await self._dispatch(event)
            return True
        return await self.queue.put(event)

    async def start(self):
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._process_queue())

    async def stop(self):
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        if self._db_conn:
            self._db_conn.close()
            self._db_conn = None

    @property
    def pending_count(self) -> int:
        """Number of events queued but not yet delivered."""
        return self.queue.size

    async def drain_now(self, max_events: Optional[int] = None) -> List[Event]:
        """
        Synchronously drains the priority queue in deterministic order (priority desc,
        FIFO within equal priority) and dispatches each event to handlers.

        Returns the events that were dispatched. Intended for deterministic testing and
        for recovering queued events at shutdown.
        """
        dispatched: List[Event] = []
        while self.queue.size > 0 and (max_events is None or len(dispatched) < max_events):
            event = await self.queue.get()
            await self._dispatch(event)
            self.queue.task_done()
            dispatched.append(event)
        return dispatched

    async def _process_queue(self):
        while self._running:
            try:
                event = await self.queue.get()
                await self._dispatch(event)
                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                await asyncio.sleep(0.01)

    async def _dispatch(self, event: Event):
        handlers = list(self._handlers.get(event.event_type, [])) + list(self._wildcard_handlers)
        for handler in handlers:
            try:
                res = handler(event)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as err:
                self.queue.route_to_dlq(event, reason=f"Handler {handler.__name__ if hasattr(handler, '__name__') else 'anonymous'} failed: {err}")
                self.dispatch_errors.append({
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "handler": getattr(handler, "__name__", "anonymous"),
                    "error": str(err)
                })
    async def replay_events(self, limit: int = 100, since_timestamp: Optional[str] = None) -> List[Event]:
        """Replay stored events from database for crash recovery or auditing."""
        if not self._db_conn:
            return []
        query = "SELECT event_id, event_type, payload, correlation_id, timestamp, source, priority, sequence FROM events_log"
        params: List[Any] = []
        if since_timestamp:
            query += " WHERE timestamp >= ?"
            params.append(since_timestamp)
        query += " ORDER BY timestamp ASC LIMIT ?"
        params.append(limit)

        cursor = self._db_conn.execute(query, params)
        replayed: List[Event] = []
        for row in cursor.fetchall():
            try:
                ev_type = EventType(row[1])
            except ValueError:
                ev_type = EventType.OBSERVATION_RECORDED
            ev = Event(
                event_id=row[0],
                event_type=ev_type,
                payload=json.loads(row[2]),
                correlation_id=row[3],
                timestamp=row[4],
                source=row[5],
                priority=row[6],
                sequence=row[7] if len(row) > 7 else None
            )
            replayed.append(ev)
        return replayed
