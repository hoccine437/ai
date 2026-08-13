#!/usr/bin/env python3
"""
ZERION-X — GENESIS & Ω Intelligence Foundry Main Entrypoint
"""

import os
from pathlib import Path


def load_dotenv():
    """Loads environment variables from .env file if present (zero external dependencies)."""
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
    from zerion.cli import main
    main()
