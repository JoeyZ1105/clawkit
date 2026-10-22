#!/usr/bin/env python3
# /// script
# dependencies = ["httpx"]
# ///
"""
Legacy CLI entry point for backward compatibility.

For package usage, install with `pip install clawkit` and run `clawkit` directly.
This file exists only for `uv run clawkit_legacy_cli.py` compatibility.
"""

if __name__ == "__main__":
    from clawkit.cli import main
    main()
