#!/usr/bin/env python3
"""Backward-compatible thin wrapper for `uv run clawkit.py`.

For package usage, use `import clawkit` after installation.
"""

from pathlib import Path
import importlib.util

__version__ = "3.2.0"


def _load_legacy():
    legacy_path = Path(__file__).parent / "clawkit" / "_legacy.py"
    spec = importlib.util.spec_from_file_location("_clawkit_legacy", legacy_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


_legacy = _load_legacy()

# Backward-compatible API exports
extract = _legacy.extract
batch_extract = _legacy.batch_extract
download_media = _legacy.download_media
format_result = _legacy.format_result
format_markdown = _legacy.format_markdown
format_brief = _legacy.format_brief
Author = _legacy.Author
Stats = _legacy.Stats
MediaItem = _legacy.MediaItem
Comment = _legacy.Comment
ExtractResult = _legacy.ExtractResult


if __name__ == "__main__":
    _legacy.main()
