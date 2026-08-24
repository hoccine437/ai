#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════
 ZERION — MASTER RUNTIME / CENTRAL ORCHESTRATOR (main2.py)
═══════════════════════════════════════════════════════════════════════

main2.py is the MASTER ENTRYPOINT and CENTRAL NERVOUS SYSTEM of Zerion.

    python main2.py

initializes and controls the complete Zerion runtime:

    config → provider → memory → context/agents/tools → cognition
           → runtime → UI/API

ARCHITECTURAL INVARIANT (single chain of authority):

    main2.py → ZerionRuntime → all subsystems → UI/API

There is exactly ONE runtime, ONE provider (Gemini primary), ONE memory,
ONE AgentRegistry, ONE ToolRegistry, and ONE source of runtime truth
(the RuntimeState owned here).

This module is IMPORT-SAFE: importing it never starts the application.
Bootstrap pattern:

    create_runtime()      — construct the runtime object (no side effects)
    initialize_runtime()  — build + connect every subsystem in dependency order
    start_runtime()       — start engine + UI/API server
    stop_runtime()        — graceful shutdown
    run()                 — CLI orchestration (only under `python main2.py`)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Lightweight, side-effect-free imports only at module level.
from zerion.runtime.state import RuntimeState, refresh_runtime_state


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION (stage 1 of the dependency graph)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class RuntimeConfig:
    """All startup configuration. Owned exclusively by the central runtime."""
    host: str = "0.0.0.0"
    port: int = 8080
    data_dir: str = "data"
    dev_cycles: int = 1            # autonomous flywheel cycle(s) before serving (legacy contract)


def load_environment() -> None:
    """Load .env files (cwd, project root, home). Never overrides real env."""
    from zerion.engine import load_dotenv_files
    load_dotenv_files()


# ═══════════════════════════════════════════════════════════════════════
# THE CENTRAL RUNTIME OBJECT
# ═══════════════════════════════════════════════════════════════════════

class ZerionRuntime:
    """The one authoritative Zerion runtime.

    Owns: configuration, RuntimeState, the AscendantEngine (which owns the
    provider, SmartMemory, CognitiveRuntime, AgentRegistry, ToolRegistry,
    voice, cognition), and the UI server (a pure client of this runtime).
    """

    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.state = RuntimeState(data_dir=config.data_dir)
        self.engine = None            # AscendantEngine (created in initialize)
        self.ui = None                # ui.ZerionUI (created in start)
        self._server_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._initialized = False
        self._started = False

    # ── diagnostics ──────────────────────────────────────────────────────
    def diagnostics(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "started": self._started,
            "config": {
                "host": self.config.host,
                "port": self.config.port,
                "data_dir": self.config.data_dir,
                "dev_cycles": self.config.dev_cycles,
            },
            "state": self.state.to_dict(),
        }


def create_runtime(config: Optional[RuntimeConfig] = None) -> ZerionRuntime:
    """Stage 1 — create the central runtime object. Import-safe, no I/O."""
    return ZerionRuntime(config or RuntimeConfig())


# ═══════════════════════════════════════════════════════════════════════
# INITIALIZATION — explicit dependency graph, no circular init
# ═══════════════════════════════════════════════════════════════════════
#
#   config ─→ provider(Gemini primary) ─→ memory(SmartMemory, ONE instance)
#          ─→ context/cognition(CognitiveRuntime) ─→ agents(ONE registry)
#          ─→ tools(ONE registry) ─→ voice/learning/UI-bridge subsystems
#          ─→ runtime state ─→ UI/API
#
# All of this is assembled inside ONE AscendantEngine construction — there is
# no second engine, no second memory, no competing registries anywhere.

async def initialize_runtime(rt: ZerionRuntime) -> ZerionRuntime:
    """Stage 2 — build and connect every subsystem in dependency order."""
    if rt._initialized:
        return rt
    t0 = time.time()

    # 1. CONFIG: environment (.env) + policy flags
    load_environment()

    # 2. RUNTIME CORE: the single engine that owns provider, memory,
    #    cognition, agents, tools, voice, learning. Heavy imports stay local
    #    so importing main2 remains cheap and side-effect free.
    from zerion.engine import AscendantEngine

    engine_kwargs: Dict[str, Any] = {"data_dir": rt.config.data_dir}
    rt.engine = AscendantEngine(**engine_kwargs)

    # The engine records its true boot time for the authoritative state.
    rt.engine._startup_time = t0

    # 3. MEASURE: fill RuntimeState from live subsystem references
    refresh_runtime_state(rt.state, rt.engine)
    rt.state.runtime_health = "BOOTING"

    rt._initialized = True

    print("╔" + "═" * 68 + "╗")
    print("║ ZERION — CENTRAL RUNTIME INITIALIZED (main2.py)".ljust(69) + "║")
    print("╠" + "═" * 68 + "╣")
    print(f"║ Provider : {rt.state.provider} ({rt.state.provider_state})".ljust(69) + "║")
    print(f"║ Model     : {rt.state.model}".ljust(69) + "║")
    print(f"║ Memory    : {rt.state.memory_state} (episodes={rt.state.episodes}, rules={rt.state.distilled_rules})".ljust(69) + "║")
    print(f"║ Agents    : {rt.state.agent_count} registered (single AgentRegistry)".ljust(69) + "║")
    print(f"║ Tools     : {rt.state.tool_count} registered (single ToolRegistry)".ljust(69) + "║")
    print(f"║ Voice     : text-input only (microphone removed); tts={rt.state.voice_enabled}".ljust(69) + "║")
    print(f"║ Data dir  : {Path(rt.config.data_dir).resolve()}".ljust(69) + "║")
    print("╚" + "═" * 68 + "╝")
    return rt


# ═══════════════════════════════════════════════════════════════════════
# STARTUP — engine first, then UI as a read-only client
# ═══════════════════════════════════════════════════════════════════════

async def start_runtime(rt: ZerionRuntime) -> ZerionRuntime:
    """Stage 3 — start the engine, then the UI/API server."""
    if not rt._initialized:
        raise RuntimeError("Call initialize_runtime(runtime) before start_runtime().")
    if rt._started:
        return rt

    await rt.engine.start()

    # Optional developmental cycles BEFORE serving (explicit, user-requested).
    for i in range(max(0, rt.config.dev_cycles)):
        trace = await rt.engine.run_developmental_cycle()
        print(f"[ZERION] Developmental cycle {i + 1}: "
              f"{trace.strategy_selected} ({trace.duration_ms:.1f}ms)")

    # 4. UI/API — a CLIENT of this runtime. It receives THIS runtime object;
    #    it never creates an engine, memory, provider or registry of its own.
    from ui import ZerionUI
    rt.ui = ZerionUI(runtime=rt, host=rt.config.host, port=rt.config.port)
    await rt.ui.start()

    refresh_runtime_state(rt.state, rt.engine)
    rt.state.runtime_health = "OK" if rt.state.memory_state.startswith("READY") else "DEGRADED"
    rt._started = True

    print(f"[ZERION] Web interface : http://{rt.config.host}:{rt.config.port}")
    print(f"[ZERION] Status API    : http://{rt.config.host}:{rt.config.port}/api/status")
    print(f"[ZERION] Runtime health: {rt.state.runtime_health}")
    return rt


async def stop_runtime(rt: ZerionRuntime) -> None:
    """Graceful shutdown: UI first, then engine persistence, then state."""
    if rt.ui is not None:
        try:
            await rt.ui.stop()
        except Exception:
            pass
    if rt.engine is not None:
        try:
            await rt.engine.stop()
        except Exception:
            pass
    rt.state.runtime_health = "STOPPED"
    rt._started = False
    print("[ZERION] Runtime stopped cleanly.")


# ═══════════════════════════════════════════════════════════════════════
# CONVERSATION / SERVE LOOP — one authoritative pipeline lives in the
# engine's CognitiveRuntime; the loop below only keeps the process alive.
# ═══════════════════════════════════════════════════════════════════════

async def serve_forever(rt: ZerionRuntime) -> None:
    rt._stop_event = asyncio.Event()
    stop_requested = {"flag": False}

    def _handle_signal(*_args):  # noqa: ANN001 — loop calls it with no args
        stop_requested["flag"] = True
        rt._stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            signal.signal(sig, _handle_signal)

    print("[ZERION] Central runtime online — press Ctrl+C to shut down.")
    while not rt._stop_event.is_set():
        try:
            await asyncio.wait_for(rt._stop_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            pass
    await stop_runtime(rt)


# ═══════════════════════════════════════════════════════════════════════
# CLI ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main2.py",
        description="ZERION — Master entrypoint & central orchestrator.")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8080)),
                   help="Port for the web server (default: 8080)")
    p.add_argument("--host", type=str, default="0.0.0.0",
                   help="Bind host (default: 0.0.0.0)")
    p.add_argument("--data-dir", type=str, default="data",
                   help="Directory for durable persistence")
    p.add_argument("--cycle", action="store_true",
                   help="Execute 1 autonomous developmental cycle before serving")
    p.add_argument("--cycles", type=int, default=1,
                   help="Execute N autonomous developmental cycles before serving (default: 1)")
    return p


async def run_async(args: argparse.Namespace) -> int:
    config = RuntimeConfig(
        host=args.host,
        port=args.port,
        data_dir=args.data_dir,
        # Legacy startup contract: at least ONE real flywheel cycle runs
        # before the server accepts traffic.
        dev_cycles=max(1, args.cycles),
    )
    rt = create_runtime(config)
    try:
        await initialize_runtime(rt)
        await start_runtime(rt)
        await serve_forever(rt)
        return 0
    except KeyboardInterrupt:
        await stop_runtime(rt)
        return 0
    except Exception as e:
        # Startup errors are reported honestly and stop the process.
        print(f"[ZERION] FATAL STARTUP ERROR: {type(e).__name__}: {e}",
              file=sys.stderr)
        try:
            await stop_runtime(rt)
        except Exception:
            pass
        return 1


def run(argv: Optional[List[str]] = None) -> int:
    """Entry point used by `python main2.py` and compatibility wrappers."""
    args = build_arg_parser().parse_args(argv)
    return asyncio.run(run_async(args))


if __name__ == "__main__":
    sys.exit(run())
