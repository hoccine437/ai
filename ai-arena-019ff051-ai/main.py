#!/usr/bin/env python3
"""
ZERION — LEGACY ENTRY COMPATIBILITY WRAPPER.

main.py no longer starts its own runtime. The MASTER ENTRYPOINT of Zerion is
`main2.py` (the central orchestrator); this wrapper only forwards to it so
existing launchers (`sh start.sh`, `python main.py ...`, package.json scripts)
keep working. There is exactly ONE bootstrap path: main2.py.
"""

import os
import sys


def load_dotenv():
    """Kept for launcher compatibility — main2 performs the canonical load."""
    from pathlib import Path

    for env_file in [Path(".env"), Path(__file__).parent / ".env", Path.home() / ".env"]:
        if env_file.exists():
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip("'").strip('"')
                            if key and not os.environ.get(key):
                                os.environ[key] = val
            except Exception:
                pass


if __name__ == "__main__":
    load_dotenv()
    # Microphone has been REMOVED from Zerion entirely — nothing to disable.
    from main2 import run
    sys.exit(run())
