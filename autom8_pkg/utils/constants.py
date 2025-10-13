# =====================================================================
# File: autom8_pkg/utils/constants.py
# Key bindings
# =====================================================================
from __future__ import annotations
import curses

KEY_RUN          = ord('r')
KEY_QUIT         = ord('q')
KEY_REFRESH      = curses.KEY_F5
KEY_TAB          = 9
KEY_ENTER        = 10
KEY_SPACE        = ord(' ')
KEY_TOGGLE_VAULT = ord('v')
KEY_CLEAR_HOSTS  = ord('c')
KEY_CLEAR_OUTPUT = ord('x')
KEY_PGUP         = curses.KEY_PPAGE
KEY_PGDN         = curses.KEY_NPAGE
KEY_HOME         = ord('g')
KEY_END          = ord('G')
KEY_SHOW_CMD     = ord('?')
KEY_HELP         = ord('h')

# New for tree navigation
KEY_LEFT         = curses.KEY_LEFT
KEY_RIGHT        = curses.KEY_RIGHT

