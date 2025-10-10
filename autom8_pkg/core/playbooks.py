# =====================================================================
# File: autom8_pkg/core/playbooks.py
# Playbook discovery utilities
# =====================================================================
from __future__ import annotations
from pathlib import Path
from typing import List


def discover_playbooks(root: Path) -> List[Path]:
    files: List[Path] = []
    if root.exists():
        for ext in ("*.yml", "*.yaml"):
            files += list(root.rglob(ext))
    return sorted(files)


def friendly_name(p: Path, base: Path) -> str:
    try:
        return str(p.relative_to(base))
    except Exception:
        return str(p)

