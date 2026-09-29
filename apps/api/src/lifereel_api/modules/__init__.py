"""Compatibility namespace for independently owned domain source roots."""

from pathlib import Path

import lifereel_api

__path__.extend(
    str(Path(root) / "modules") for root in lifereel_api.__path__
    if (Path(root) / "modules").is_dir() and str(Path(root) / "modules") not in __path__
)
