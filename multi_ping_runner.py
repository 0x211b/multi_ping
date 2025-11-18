#!/usr/bin/env python3
"""Standalone entry point for the multi_ping monitor."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    src_dir = root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from multi_ping.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
