"""
ZERION-X — CLI launcher (compatibility entry).

Historical console scripts (`zerion`, `genesis`, `zerion-ui`) land here.
The CLI no longer builds its own engine or web server — that would create a
competing runtime. It delegates everything to the MASTER ENTRYPOINT
`main2.py`, the central orchestrator, preserving the historical flags.
"""
from __future__ import annotations


def main(argv=None):
    """Forward to the one bootstrap path in main2.run()."""
    import sys
    import main2

    # Map legacy flags onto main2's parser (they are a superset; unknown
    # legacy flags like --ui are accepted and ignored for compatibility).
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = [a for a in argv if a not in ("--ui", "-u")]
    return main2.run(argv)


if __name__ == "__main__":
    main()
