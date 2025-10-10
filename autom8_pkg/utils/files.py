# =====================================================================
# File: autom8_pkg/utils/files.py
# Filesystem helpers (symlink-safe project root discovery)
# =====================================================================
from __future__ import annotations
from pathlib import Path


def find_project_root(explicit: str | None = None) -> Path:
    """Locate project root (supports running from symlinks or any cwd)."""
    if explicit:
        return Path(explicit).resolve()

    here = Path.cwd().resolve()
    for p in [here, *here.parents]:
        if (p / 'playbooks').exists() or (p / 'inventory').exists() or (p / 'autom8_pkg').exists():
            return p

    # Fallback to this file’s ancestor
    return Path(__file__).resolve().parents[2]


def ensure_relative_to(path: Path, base: Path) -> str:
    """Return path relative to base if possible."""
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except Exception:
        return str(path)

