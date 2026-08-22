"""
ZERION UI — COMPATIBILITY SHIM.

The authoritative UI module is `ui.py` at the project root. This shim keeps
historical import paths (`zerion.ui.server`) working WITHOUT being a competing
entry point: every server lifecycle goes through the single central runtime
bootstrap in `main2.py`. The old module-level `main()` / `__main__` entry —
which built its own engine (a second runtime) — has been removed.
"""

from __future__ import annotations

import asyncio

# Single source of truth for the UI:
from ui import ZerionUI as GenesisWebServer  # noqa: F401 — re-exported shim

__all__ = ["GenesisWebServer", "run_server"]


async def run_server(port: int = 8080, data_dir: str = "data") -> None:
    """Legacy programmatic entry — delegates to the ONE bootstrap in main2."""
    import main2

    config = main2.RuntimeConfig(port=port, data_dir=data_dir)
    rt = main2.create_runtime(config)
    await main2.initialize_runtime(rt)
    await main2.start_runtime(rt)
    try:
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        await main2.stop_runtime(rt)
