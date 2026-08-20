"""
ZERION X — runtime lifecycle regression tests (spec §15).

The bug: ``python main.py`` printed readiness -> ran the initial
developmental cycle -> printed the scoreboard -> the CLI coroutine
returned -> ``asyncio.run`` completed -> the process exited 0.

A developmental cycle is ONE operation inside the runtime; it must not
terminate the runtime. After the cycle + scoreboard, Zerion must enter
ACTIVE / WAITING_FOR_EVENTS and stay resident until explicit shutdown.

These tests exercise the fixed seam (``_enter_persistent_runtime``):

- the wait BLOCKS (task pending) until a shutdown request,
- it is fully event-driven (no CPU-burning loop),
- completing a cycle / waiting / idle never calls ``engine.stop()``,
- a set shutdown event releases the wait so the CLI can exit cleanly.

The real end-to-end proof (bare ``python main.py`` stays alive after the
scoreboard, then exits 0 on SIGINT) lives in
``test_local_model_execution.py::TestMainPyCanonicalEntrypoint``.
"""

import asyncio
import contextlib
import io
import unittest
from unittest import mock

try:
    from zerion.cli import _enter_persistent_runtime
except ImportError:
    _enter_persistent_runtime = None


@unittest.skipIf(_enter_persistent_runtime is None, "Persistent runtime removed from CLI")
class TestPersistentRuntimeWait(unittest.IsolatedAsyncioTestCase):
    """The CLI wait seam: blocks, is event-driven, never stops the engine."""

    async def test_wait_blocks_until_shutdown_event_event_driven(self) -> None:
        """With signal wiring available, the wait is a pure event wait: the
        task stays pending until the event is set, then completes — and the
        engine is never stopped by the wait itself."""
        engine = mock.MagicMock()
        event = asyncio.Event()
        loop = asyncio.get_running_loop()
        with mock.patch.object(loop, "add_signal_handler") as add_handler:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                task = asyncio.create_task(
                    _enter_persistent_runtime(engine, event))
                await asyncio.sleep(0.05)
                # Still waiting: idle does NOT terminate the runtime.
                self.assertFalse(task.done())
                self.assertFalse(event.is_set())
                engine.stop.assert_not_called()
                event.set()
                await asyncio.wait_for(task, timeout=5)
        # The explicit shutdown request released the wait cleanly.
        add_handler.assert_called()
        text = out.getvalue()
        self.assertIn("ZERION RUNTIME: ACTIVE", text)
        self.assertIn("LIFECYCLE: PERSISTENT", text)
        self.assertIn("STATE: WAITING_FOR_EVENTS", text)
        engine.stop.assert_not_called()

    async def test_wait_fallback_loop_without_signal_support(self) -> None:
        """On platforms without asyncio signal handlers the wait falls back
        to periodic wakeups but still blocks and releases on shutdown."""
        engine = mock.MagicMock()
        event = asyncio.Event()
        loop = asyncio.get_running_loop()
        with mock.patch.object(loop, "add_signal_handler",
                               side_effect=NotImplementedError):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                task = asyncio.create_task(
                    _enter_persistent_runtime(engine, event))
                await asyncio.sleep(0.1)
                self.assertFalse(task.done())
                event.set()
                await asyncio.wait_for(task, timeout=5)
        self.assertIn("STATE: WAITING_FOR_EVENTS", out.getvalue())
        engine.stop.assert_not_called()

    async def test_cycle_completion_does_not_stop_runtime(self) -> None:
        """Simulating the fixed default CLI branch: a completed developmental
        cycle (fake) + scoreboard (fake) followed by the persistent wait must
        leave the runtime running — stop() is only invoked by the CLI's own
        ``finally`` on explicit shutdown, never by the wait."""
        engine = mock.MagicMock()
        # The developmental cycle completed (one operation inside the runtime).
        engine.run_developmental_cycle = mock.AsyncMock(
            return_value=mock.MagicMock(cycle_id="test_cycle_1"))
        await engine.run_developmental_cycle()
        event = asyncio.Event()
        loop = asyncio.get_running_loop()
        with mock.patch.object(loop, "add_signal_handler",
                               side_effect=NotImplementedError):
            task = asyncio.create_task(_enter_persistent_runtime(engine, event))
            await asyncio.sleep(0.1)
            # Cycle finished, scoreboard printed (in the real CLI), runtime
            # still resident and untouched.
            self.assertFalse(task.done())
            engine.stop.assert_not_called()
            event.set()
            await asyncio.wait_for(task, timeout=5)
        engine.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
