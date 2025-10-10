# =====================================================================
# File: autom8_pkg/core/splash.py
# Curses splash screen (10s), skippable by any key
# =====================================================================
from __future__ import annotations
import curses
import time

LOGO = [
"   _____          __            _____     _______",
"  /  _  \\  __ ___/  |_  ____   /     \\   /  ___  \\",
" /  /_\\  \\|  |  \\   __\\/  _ \\ /  \\ /  \\  >       <",
"/    |    \\  |  /|  | (  <_> )    Y    \\/   ---   \\",
"\\____|__  /____/ |__|  \\____/\\____|__  /\\_______  /",
"        \\/                           \\/         \\/",
"",
" A u t o M 8   .   A n s i b l e  M a d e  E a s y",
"",
]

TAGLINE = "AutoM8  ·  Ansible Made Easy"
SKIPTXT = "Press any key to skip..."

def center(win, y: int, text: str, attr=0):
    h, w = win.getmaxyx()
    x = max(0, (w - len(text)) // 2)
    if 0 <= y < h:
        win.addstr(y, max(0, x), text[: max(0, w - x - 1)], attr)

def run_splash(stdscr, seconds: int = 10):
    curses.curs_set(0)
    stdscr.nodelay(True)
    start, end = time.time(), time.time() + max(1, seconds)
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        # draw box
        stdscr.box()
        y0 = max(2, h // 2 - 5)
        for i, line in enumerate(LOGO):
            center(stdscr, y0 + i, line, curses.A_BOLD)
        center(stdscr, y0 + len(LOGO) + 2, TAGLINE, curses.A_DIM)
        center(stdscr, h - 3, SKIPTXT, curses.A_DIM)

        stdscr.refresh()
        ch = stdscr.getch()
        if ch != -1 or time.time() >= end:
            break
        time.sleep(0.05)

def splash(seconds: int = 10):
    curses.wrapper(run_splash, seconds)
