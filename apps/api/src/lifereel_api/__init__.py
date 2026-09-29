"""Shared backend namespace and source-checkout package discovery.

Domain implementations live under services/. Release wheels merge these source
roots into one versioned namespace so existing imports and migrations stay stable.
Applications register only their owned routes; distributed calls never fall back.
"""

from pathlib import Path

__version__ = "0.1.0"
_root = Path(__file__).resolve().parents[4]
if (_root / "services").is_dir() and (_root / "apps/api/pyproject.toml").is_file():
    __path__.extend(str(p) for p in sorted((_root / "services").glob("*/src/lifereel_api")))
