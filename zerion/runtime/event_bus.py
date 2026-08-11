"""
Async Event Bus with SQLite Event Persistence and Replay
"""

import asyncio
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
from zerion.runtime.events import Event, EventType
from zerion.runtime.queue import PriorityEventQueue

EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class AsyncEventBus:
    def __init__(self, db_path: Optional[str] = None, max_queue_capacity: int = 5000):
        self.db_path = db_path
        self.queue = PriorityEventQueue(max_capacity=max_queue_capacity)
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._wildcard_handlers: List[EventHandler] = []
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._db_conn: Optional[sqlite3.Connection] = None
        self._init_db()

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
                    priority INTEGER NOT NULL
                )
            """)
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

    async def publish(self, event: Event) -> bool:
        # Persist to disk if persistence is enabled
        if self._db_conn:
            try:
                self._db_conn.execute(
                    "INSERT OR REPLACE INTO events_log VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.event_id,
                        event.event_type.value if isinstance(event.event_type, EventType) else str(event.event_type),
                        json.dumps(event.payload),
                        event.correlation_id,
                        event.timestamp,
                        event.source,
                        event.priority
                    )
                )
                self._db_conn.commit()
            except Exception as e:
                # Log persistence failure without crashing
                pass

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

    async def replay_events(self, limit: int = 100, since_timestamp: Optional[str] = None) -> List[Event]:
        """Replay stored events from database for crash recovery or auditing."""
        if not self._db_conn:
            return []
        query = "SELECT event_id, event_type, payload, correlation_id, timestamp, source, priority FROM events_log"
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
                priority=row[6]
            )
            replayed.append(ev)
        return replayed
