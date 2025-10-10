# =====================================================================
# File: autom8_pkg/utils/misc.py
# Miscellaneous utilities
# =====================================================================
from __future__ import annotations
import shutil


def which(cmd: str) -> str | None:
    """Return the full path of a command if found in PATH."""
    return shutil.which(cmd)

