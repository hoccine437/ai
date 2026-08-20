"""
ZERION-X — Web UI Launcher

Launches the ZERION web interface on port 8080 (or custom port).
No terminal chat. No voice mode. No offline mode. Gemini 3.1 Flash only.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any


async def run_cli():
    parser = argparse.ArgumentParser(description="ZERION-X — Autonomous Cognitive System")
    parser.add_argument("--ui", action="store_true", default=True,
                        help="Start the ZERION web interface (default)")
    parser.add_argument("--port", type=int, default=8080,
                        help="Port for the web server (default: 8080)")
    parser.add_argument("--data-dir", type=str, default="data",
                        help="Directory for durable persistence")
    parser.add_argument("--cycle", action="store_true",
                        help="Execute 1 autonomous developmental cycle")
    parser.add_argument("--cycles", type=int, default=1,
                        help="Execute N autonomous developmental cycles")

    args = parser.parse_args()

    # Import engine
    from zerion.engine import AscendantEngine
    from zerion.runtime.evidence import collect_runtime_evidence

    engine = AscendantEngine(data_dir=args.data_dir)
    await engine.start()

    # Show startup info
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        print("[ZERION] Gemini API detected — using cloud inference.")
    else:
        print("[ZERION] WARNING: No GEMINI_API_KEY set. Set it for cloud inference.")
        print("[ZERION]   export GEMINI_API_KEY='your-key-here'")

    try:
        # Always run developmental cycles first
        n = max(1, args.cycles)
        if args.cycle or n > 1:
            print(f"[ZERION] Running {n} developmental cycle(s)...")
            for i in range(n):
                trace = await engine.run_developmental_cycle()
                print(f"  Cycle {i+1}: {trace.strategy_selected} ({trace.duration_ms:.1f}ms)")

        # Start the web server
        from zerion.ui.server import GenesisWebServer
        server = GenesisWebServer(engine=engine, host="0.0.0.0", port=args.port)
        await server.start()
        print(f"[ZERION] Web interface: http://0.0.0.0:{args.port}")
        print(f"[ZERION] Model: gemini-3.1-flash")
        print(f"[ZERION] Tools: 100 | Agents: 21")

        # Keep running
        try:
            while True:
                await asyncio.sleep(3600)
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await server.stop()

    finally:
        await engine.stop()


def main():
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
