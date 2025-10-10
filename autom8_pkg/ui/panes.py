# =====================================================================
# File: autom8_pkg/ui/panes.py
# Panes for: Sites, Groups, Playbooks, Selection, Output, Footer
# =====================================================================
from __future__ import annotations
import curses
from typing import List, Optional, Tuple
from .helpers import safe_addstr, box_title

# ------------------------------ List Panes ------------------------------
class ListPane:
    """Generic scrollable list pane with focus highlight."""
    def __init__(self, win, title: str):
        self.win = win
        self.title = title
        self.items: List[str] = []
        self.index = 0
        self.focused = False

    def set_items(self, items: List[str]):
        self.items = items
        self.index = 0

    def move(self, delta: int):
        if not self.items:
            return
        self.index = (self.index + delta) % len(self.items)

    def current(self) -> Optional[str]:
        if not self.items:
            return None
        return self.items[self.index]

    def render(self):
        self.win.erase()
        self.win.box()
        box_title(self.win, self.title)
        h, w = self.win.getmaxyx()
        max_rows = h - 2
        start = 0
        if self.index >= max_rows:
            start = self.index - max_rows + 1
        visible = self.items[start:start + max_rows]
        for i, text in enumerate(visible, start=0):
            y = 1 + i
            marker = ">" if (start + i) == self.index and self.focused else " "
            attr = curses.A_BOLD if (start + i) == self.index and self.focused else 0
            safe_addstr(self.win, y, 1, f"{marker} {text}", attr)
        self.win.noutrefresh()


class CheckListPane(ListPane):
    """
    Scrollable list with checkboxes.
    Special handling for 'all': selecting it clears others; if nothing is selected, treat as 'all'.
    (Used for Sites pane.)
    """
    def __init__(self, win, title: str):
        super().__init__(win, title)
        self.selected: set[str] = set()

    def set_items(self, items: List[str]):
        super().set_items(items)
        self.selected = {s for s in self.selected if s in set(items)}

    def set_selected(self, items: List[str]):
        self.selected = set(items) & set(self.items)

    def get_selected(self) -> List[str]:
        return sorted(self.selected)

    def toggle_current(self):
        cur = self.current()
        if cur is None:
            return
        if cur == "all":
            if "all" in self.selected:
                self.selected.remove("all")
            else:
                self.selected = {"all"}
        else:
            if "all" in self.selected:
                self.selected.remove("all")
            if cur in self.selected:
                self.selected.remove(cur)
            else:
                self.selected.add(cur)

    def render(self):
        self.win.erase()
        self.win.box()
        box_title(self.win, self.title)
        h, w = self.win.getmaxyx()
        max_rows = h - 2
        start = 0
        if self.index >= max_rows:
            start = self.index - max_rows + 1
        visible = self.items[start:start + max_rows]
        for i, text in enumerate(visible, start=0):
            y = 1 + i
            checked = "[x]" if (text in self.selected or (not self.selected and text == "all")) else "[ ]"
            marker = ">" if (start + i) == self.index and self.focused else " "
            attr = curses.A_BOLD if (start + i) == self.index and self.focused else 0
            safe_addstr(self.win, y, 1, f"{marker} {checked} {text}", attr)
        self.win.noutrefresh()


# ------------------------------ Modal: PasswordModal ------------------------
class PasswordModalPane:
    """
    Centered password input modal (masked). Returns the entered string or None if cancelled.
    Controls: type to enter, BACKSPACE to erase, ENTER to confirm, ESC/q to cancel.
    """
    def __init__(self, stdscr, title: str = "Vault Password", prompt: str = "Enter vault password:"):
        import curses, curses.panel
        from .helpers import safe_addstr, box_title

        self.curses = curses
        self.panel_mod = curses.panel
        self.safe_addstr = safe_addstr
        self.box_title = box_title

        self.stdscr = stdscr
        self.title = title
        self.prompt = prompt
        self.buffer: list[str] = []
        self.index = 0

        h, w = stdscr.getmaxyx()
        width = min(max(50, len(prompt) + 10), int(w * 0.9))
        height = 7
        y = max(0, (h - height)//2)
        x = max(0, (w - width)//2)

        self.win = curses.newwin(height, width, y, x)
        self.win.keypad(True)
        self.panel = curses.panel.new_panel(self.win)
        self.panel.top()

    def run(self) -> str | None:
        self.curses.curs_set(1)
        try:
            while True:
                self.render()
                self.panel_mod.update_panels()
                self.curses.doupdate()

                ch = self.win.getch()
                if ch in (27, ord('q')):   # ESC or q
                    return None
                elif ch in (self.curses.KEY_ENTER, 10, 13):
                    return "".join(self.buffer)
                elif ch in (self.curses.KEY_BACKSPACE, 127, 8):
                    if self.buffer:
                        self.buffer.pop()
                elif 32 <= ch <= 126:      # printable ASCII
                    self.buffer.append(chr(ch))
                # ignore others
        finally:
            self.curses.curs_set(0)

    def render(self):
        self.win.erase()
        self.win.box()
        self.box_title(self.win, self.title)
        self.safe_addstr(self.win, 2, 2, self.prompt)
        masked = "*" * len(self.buffer)
        self.safe_addstr(self.win, 3, 2, masked)
        self.safe_addstr(self.win, 5, 2, "ENTER=confirm  ESC=cancel", self.curses.A_DIM)
        self.win.noutrefresh()

# ------------------------------ Modal: Multi-check ---------------------------
class MultiCheckModalPane:
    """
    Centered modal with checkboxes and an 'All' toggle at the top.
    Now fully scrollable for long lists.
    Controls:
      ./k  ./j   = move
      PgUp/PgDn  = page scroll
      Home/End   = jump to first/last
      SPACE      = toggle
      ENTER      = confirm
      ESC/q      = cancel
    """
    def __init__(self, stdscr, title: str, options: list[str], preselected: list[str] | None = None):
        import curses, curses.panel
        from .helpers import safe_addstr, box_title

        self.curses = curses
        self.panel_mod = curses.panel
        self.safe_addstr = safe_addstr
        self.box_title = box_title

        self.stdscr = stdscr
        self.title = title
        self.options = list(options)           # host list
        self.all_label = "All"
        self.items = [self.all_label] + self.options
        self.selected: set[str] = set(preselected or [])
        self.index = 0                         # cursor index into items (0..len-1)
        self.top = 0                           # top visible index for scrolling window

        # Size modal relative to screen; cap height so content becomes scrollable
        h, w = stdscr.getmaxyx()
        self.height = min(max(10, int(h * 0.7)), h)
        self.width  = min(max(50, int(w * 0.8)), w)
        y = max(0, (h - self.height)//2)
        x = max(0, (w - self.width)//2)

        self.win = curses.newwin(self.height, self.width, y, x)
        self.win.keypad(True)
        self.panel = curses.panel.new_panel(self.win)
        self.panel.top()

    # ---------- selection helpers ----------
    def toggle(self, label: str):
        if label == self.all_label:
            if self.is_all_selected():
                self.selected.clear()
            else:
                self.selected = set(self.options)
        else:
            if label in self.selected:
                self.selected.remove(label)
            else:
                self.selected.add(label)

    def is_all_selected(self) -> bool:
        return len(self.selected) == len(self.options) and len(self.options) > 0

    # ---------- scrolling helpers ----------
    def _visible_rows(self) -> int:
        # inner area between borders; one line reserved for footer help
        return max(1, self.height - 3)

    def _ensure_cursor_visible(self):
        visible = self._visible_rows()
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + visible:
            self.top = self.index - visible + 1

    def _page_up(self):
        self.index = max(0, self.index - self._visible_rows())
        self._ensure_cursor_visible()

    def _page_down(self):
        self.index = min(len(self.items) - 1, self.index + self._visible_rows())
        self._ensure_cursor_visible()

    def _to_home(self):
        self.index = 0
        self._ensure_cursor_visible()

    def _to_end(self):
        self.index = len(self.items) - 1 if self.items else 0
        self._ensure_cursor_visible()

    # ---------- main loop ----------
    def run(self) -> list[str] | None:
        self.curses.curs_set(0)
        while True:
            self.render()
            self.panel_mod.update_panels()
            self.curses.doupdate()

            ch = self.win.getch()
            if ch in (27, ord('q')):  # ESC / q
                return None
            elif ch in (self.curses.KEY_ENTER, 10, 13):  # ENTER
                return list(self.options) if self.is_all_selected() else sorted(self.selected)
            elif ch in (self.curses.KEY_UP, ord('k')):
                if self.index > 0:
                    self.index -= 1
                    self._ensure_cursor_visible()
            elif ch in (self.curses.KEY_DOWN, ord('j')):
                if self.index < len(self.items) - 1:
                    self.index += 1
                    self._ensure_cursor_visible()
            elif ch == self.curses.KEY_PPAGE:   # Page Up
                self._page_up()
            elif ch == self.curses.KEY_NPAGE:   # Page Down
                self._page_down()
            elif ch in (self.curses.KEY_HOME,):
                self._to_home()
            elif ch in (self.curses.KEY_END,):
                self._to_end()
            elif ch == ord(' '):  # SPACE to toggle
                self.toggle(self.items[self.index])

    # ---------- rendering ----------
    def render(self):
        self.win.erase()
        self.win.box()
        # Title with "more..." indicator when scrollable
        extra = ""
        total = len(self.items)
        visible = self._visible_rows()
        if total > visible:
            # show down/up arrows when there.s more content off-screen
            up_more = "." if self.top > 0 else ""
            down_more = "." if self.top + visible < total else ""
            extra = f"  {up_more}{' ' if up_more and down_more else ''}{down_more}"
        self.box_title(self.win, f"{self.title}{extra}")

        # Draw visible window
        start = self.top
        end = min(total, start + visible)
        row = 1
        for i in range(start, end):
            label = self.items[i]
            if label == self.all_label:
                checked = "[x]" if self.is_all_selected() else "[ ]"
            else:
                checked = "[x]" if label in self.selected else "[ ]"
            marker = ">" if i == self.index else " "
            attr = self.curses.A_BOLD if i == self.index else 0
            self.safe_addstr(self.win, row, 2, f"{marker} {checked} {label}", attr)
            row += 1

        # Footer help
        help_text = "SPACE=toggle  PgUp/PgDn/Home/End scroll  ENTER=confirm  ESC=cancel"
        self.safe_addstr(self.win, self.height - 1, 2, help_text[: self.width - 4], self.curses.A_DIM)
        self.win.noutrefresh()


# ------------------------------ Output & Footer ------------------------------
class SelectionPane:
    """Right-most summary pane."""
    def __init__(self, win):
        self.win = win
        self.site = "all"
        self.group = "(none)"
        self.playbook = "(none)"
        self.vault = False
        self.hosts: List[str] = []

    def set_site(self, s: str): self.site = s
    def set_group(self, g: str): self.group = g
    def set_playbook(self, p: str): self.playbook = p
    def set_vault(self, v: bool): self.vault = v
    def set_hosts(self, hosts: List[str]): self.hosts = hosts

    def render(self):
        self.win.erase()
        self.win.box()
        box_title(self.win, "Selection")
        safe_addstr(self.win, 1, 2, f"Site:    {self.site}")
        safe_addstr(self.win, 2, 2, f"Target:  {self.group}")
        safe_addstr(self.win, 3, 2, f"Playbook:{' ' + self.playbook}")
        safe_addstr(self.win, 4, 2, f"Vault:   {'ON' if self.vault else 'OFF'}")
        safe_addstr(self.win, 6, 2, f"Hosts ({len(self.hosts)}):")
        if not self.hosts:
            safe_addstr(self.win, 7, 4, ".")
        else:
            for i, h in enumerate(self.hosts[: (self.win.getmaxyx()[0] - 9)]):
                safe_addstr(self.win, 7 + i, 4, h)
        self.win.noutrefresh()


class OutputPane:
    def __init__(self, win, max_lines: int = 5000):
        self.win = win
        self.lines: List[str] = []
        self.max_lines = max_lines
        self.scroll = 0  # 0 = follow tail; >0 = user scrolled up

        # Precompiled regex to strip ANSI escape sequences
        import re
        self._ansi_re = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

    def clear(self):
        self.lines.clear()
        self.scroll = 0

    def _clean_text(self, s: str) -> str:
        # Remove ANSI color/formatting sequences
        s = self._ansi_re.sub("", s)
        # Normalize carriage-returns (progress-style lines)
        # Keep the last segment after a CR to emulate overwrite behavior
        if "\r" in s:
            parts = s.split("\r")
            s = parts[-1]
        return s

    def append_bytes(self, chunk: bytes):
        text = chunk.decode(errors="ignore")
        text = self._clean_text(text)
        for part in text.splitlines():
            self.lines.append(part)
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]

    # -------- scrolling ----------
    def _max_visible(self) -> int:
        h, _ = self.win.getmaxyx()
        return max(0, h - 2)

    def _max_scroll(self) -> int:
        max_vis = self._max_visible()
        return max(0, len(self.lines) - max_vis)

    def scroll_lines(self, n: int):
        self.scroll = max(0, min(self.scroll + n, self._max_scroll()))

    def page_up(self):
        self.scroll_lines(self._max_visible())

    def page_down(self):
        self.scroll_lines(-self._max_visible())

    def to_top(self):
        self.scroll = self._max_scroll()

    def to_bottom(self):
        self.scroll = 0

    def render(self):
        self.win.erase()
        self.win.box()
        box_title(self.win, "Output / Status")
        h, w = self.win.getmaxyx()
        visible = max(0, h - 2)
        start = max(0, len(self.lines) - visible - self.scroll)
        for i, line in enumerate(self.lines[start:start+visible], start=1):
            safe_addstr(self.win, i, 1, line)
        if self.scroll > 0:
            hint = f". {self.scroll} lines (PgDn to follow)"
            safe_addstr(self.win, 0, max(2, w - len(hint) - 2), hint, curses.A_DIM)
        self.win.noutrefresh()


class FooterPane:
    def __init__(self, win):
        self.win = win
        self.text_template = (
                " [?] Preview     |     [v] vault:{vault}     |     [r] run     |     [h] help     |     [q] quit"
        )

        self.vault_on = False

    def set_vault(self, on: bool):
        self.vault_on = on

    def render(self):
        self.win.erase()
        text = self.text_template.format(vault=("ON" if self.vault_on else "OFF"))
        safe_addstr(self.win, 0, 1, text, curses.A_DIM)
        self.win.noutrefresh()

class TextModalPane:
    """
    Centered read-only text modal with dynamic word-wrapping.
    Closes with ENTER or ESC/q. Supports ./. and PgUp/PgDn scrolling.
    """
    def __init__(self, stdscr, title: str, lines: List[str]):
        import curses, curses.panel
        from .helpers import safe_addstr, box_title

        self.curses = curses
        self.panel_mod = curses.panel
        self.safe_addstr = safe_addstr
        self.box_title = box_title

        self.stdscr = stdscr
        self.title = title
        # Keep the original (unwrapped) lines; we wrap per window width at render time
        self._raw_lines = list(lines)

        self.index = 0  # top wrapped line index for scrolling

        h, w = stdscr.getmaxyx()
        # Modal size: up to 90% of screen, but at least 14x50
        self.height = min(max(14, int(h * 0.8)), h)
        self.width  = min(max(50, int(w * 0.9)), w)
        y = max(0, (h - self.height)//2)
        x = max(0, (w - self.width)//2)

        self.win = curses.newwin(self.height, self.width, y, x)
        self.win.keypad(True)
        self.panel = curses.panel.new_panel(self.win)
        self.panel.top()

        # cache of wrapped lines for current width
        self._wrapped_lines: List[str] = []
        self._wrap_width = 0  # recompute on first render

    def _compute_wrapped(self):
        """Wrap raw lines to the current usable width, preserving leading indentation."""
        import textwrap
        usable = max(1, self.width - 4)  # borders + padding
        if usable == self._wrap_width and self._wrapped_lines:
            return
        self._wrap_width = usable
        wrapped: List[str] = []
        for line in self._raw_lines:
            # detect leading indentation to preserve alignment on wraps
            leading_spaces = len(line) - len(line.lstrip(' '))
            indent = ' ' * leading_spaces
            # Let textwrap do soft wrapping; preserve/keep existing spaces
            filled = textwrap.fill(
                line,
                width=usable,
                initial_indent='',
                subsequent_indent=indent,
                replace_whitespace=False,
                drop_whitespace=False,
                break_long_words=True,
                break_on_hyphens=True,
            )
            wrapped.extend(filled.splitlines() or [''])
        self._wrapped_lines = wrapped
        # Ensure index is valid after rewrap
        self.index = min(self.index, max(0, len(self._wrapped_lines) - 1))

    def run(self):
        self.curses.curs_set(0)
        while True:
            self.render()
            self.panel_mod.update_panels()
            self.curses.doupdate()
            ch = self.win.getch()
            if ch in (self.curses.KEY_ENTER, 10, 13, 27, ord('q')):
                return
            elif ch in (self.curses.KEY_UP, ord('k')):
                self.index = max(0, self.index - 1)
            elif ch in (self.curses.KEY_DOWN, ord('j')):
                self.index = min(max(0, len(self._wrapped_lines) - 1), self.index + 1)
            elif ch == self.curses.KEY_PPAGE:
                self.index = max(0, self.index - (self.height - 3))
            elif ch == self.curses.KEY_NPAGE:
                self.index = min(max(0, len(self._wrapped_lines) - 1), self.index + (self.height - 3))

    def render(self):
        # Recompute wraps if size changed (defensive; current code uses fixed size)
        h, w = self.win.getmaxyx()
        if (h, w) != (self.height, self.width):
            self.height, self.width = h, w
            self._wrapped_lines = []  # force recompute
        self._compute_wrapped()

        self.win.erase()
        self.win.box()
        self.box_title(self.win, self.title)

        usable_rows = self.height - 2
        start = self.index
        view = self._wrapped_lines[start:start + usable_rows]
        for i, line in enumerate(view, start=1):
            self.safe_addstr(self.win, i, 2, line[: self.width - 4])

        # footer hint
        hint = "ENTER/ESC to close"
        self.safe_addstr(self.win, self.height - 1, 2, hint, self.curses.A_DIM)

        # scroll indicator (optional)
        if len(self._wrapped_lines) > usable_rows and start + usable_rows < len(self._wrapped_lines):
            more = f". {len(self._wrapped_lines) - (start + usable_rows)} more"
            self.safe_addstr(self.win, 0, max(2, self.width - len(more) - 2), more, self.curses.A_DIM)

        self.win.noutrefresh()

