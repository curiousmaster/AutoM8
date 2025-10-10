# =====================================================================
# File: autom8_pkg/utils/constants.py
# Constants and key bindings
# =====================================================================
from __future__ import annotations
import curses

KEY_RUN          = ord('r')
KEY_QUIT         = ord('q')
KEY_SELECT       = ord('s')
KEY_PICK_PB      = ord('p')
KEY_REFRESH      = curses.KEY_F5
KEY_TAB          = 9
KEY_ENTER        = 10
KEY_SPACE        = ord(' ')
KEY_TOGGLE_VAULT = ord('v')
KEY_CLEAR_HOSTS  = ord('c')
KEY_CLEAR_OUTPUT = ord('x')
KEY_SHOW_CMD     = ord('?')
KEY_HELP         = ord('h')

# Scrolling
KEY_PGUP = curses.KEY_PPAGE
KEY_PGDN = curses.KEY_NPAGE
KEY_HOME = ord('g')   # go to top (like less)
KEY_END  = ord('G')   # go to bottom

