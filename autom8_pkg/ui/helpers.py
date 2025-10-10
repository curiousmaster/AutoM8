# =====================================================================
# File: autom8_pkg/ui/helpers.py
# Drawing helpers for curses UI
# =====================================================================
from __future__ import annotations
import curses


def safe_addstr(win, y: int, x: int, text: str, attr=0):
    """Safely write text to curses window without overflow errors."""
    h, w = win.getmaxyx()
    if 0 <= y < h:
        if x < 0:
            text = text[-x:]
            x = 0
        if x < w:
            win.addstr(y, x, text[: max(0, w - x - 1)], attr)


def hr(win, y: int, ch: str = "─"):
    """Draw a horizontal line using Unicode or ASCII fallback."""
    h, w = win.getmaxyx()
    line = ch * (w - 1)
    safe_addstr(win, y, 0, line)


def box_title(win, title: str):
    """Draw a title on the top border of a window box."""
    h, w = win.getmaxyx()
    if w < 4:
        return
    t = f" {title} "
    safe_addstr(win, 0, 2, t, curses.A_BOLD)

