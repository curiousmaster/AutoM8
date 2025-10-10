# =====================================================================
# File: autom8_pkg/utils/logger.py
# Simple leveled logger for TUI and debugging
# =====================================================================
from __future__ import annotations
import sys

LEVELS = {0: "ERROR", 1: "WARN", 2: "INFO", 3: "DEBUG"}


class Logger:
    def __init__(self, level: int = 2):
        self.level = max(0, min(3, level))

    def _log(self, lvl: int, msg: str):
        if self.level >= lvl:
            print(f"[{LEVELS.get(lvl, lvl)}] {msg}", file=sys.stderr)

    def error(self, msg: str):
        self._log(0, msg)

    def warn(self, msg: str):
        self._log(1, msg)

    def info(self, msg: str):
        self._log(2, msg)

    def debug(self, msg: str):
        self._log(3, msg)

