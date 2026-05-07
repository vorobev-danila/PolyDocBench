"""Helpers for accessing the legacy renderer package during migration."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_legacy_render_path() -> Path:
    """Add the historical ``render/`` directory to ``sys.path`` if needed."""

    project_root = Path(__file__).resolve().parent.parent
    legacy_root = project_root / "render"
    legacy_root_str = str(legacy_root)
    if legacy_root_str not in sys.path:
        sys.path.insert(0, legacy_root_str)
    return legacy_root

