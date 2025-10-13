# =====================================================================
# File: autom8_pkg/ui/tree.py
# Foldable tree view with tri-state checkboxes (curses)
# - Level-agnostic, any depth
# - '>' cursor marker + highlighted row
# - No arrow icons (as requested)
# =====================================================================

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Iterable
import curses
from .helpers import safe_addstr, box_title


# check state: 0=unchecked, 1=partial, 2=checked
@dataclass
class TreeNode:
    name: str
    kind: str  # "group" | "host"
    children: List["TreeNode"] = field(default_factory=list)
    parent: Optional["TreeNode"] = None
    expanded: bool = False
    checked: int = 0  # 0/1/2

    @staticmethod
    def from_dict(d: dict, parent: Optional["TreeNode"] = None) -> "TreeNode":
        node = TreeNode(name=d["name"], kind=d["kind"], parent=parent)
        node.expanded = d.get("expanded", False)
        for ch in d.get("children", []):
            child = TreeNode.from_dict(ch, parent=node)
            node.children.append(child)
        node._recompute_from_children()
        return node

    # ---- selection logic ----
    def _set_checked_recursive(self, value: int):
        self.checked = 2 if value else 0
        for c in self.children:
            c._set_checked_recursive(value)
        if self.parent:
            self.parent._recompute_from_children()

    def toggle_check(self):
        if self.kind == "host":
            self.checked = 0 if self.checked == 2 else 2
            if self.parent:
                self.parent._recompute_from_children()
        else:
            want = 0 if self.checked == 2 else 2
            self._set_checked_recursive(1 if want == 2 else 0)

    def _recompute_from_children(self):
        if not self.children:
            return
        states = {c.checked for c in self.children}
        if states == {2}:
            self.checked = 2
        elif states == {0}:
            self.checked = 0
        else:
            self.checked = 1
        if self.parent:
            self.parent._recompute_from_children()

    # ---- expand/collapse ----
    def toggle_expand(self):
        if self.kind == "group" and self.children:
            self.expanded = not self.expanded

    # ---- utilities ----
    def iter_visible(self) -> Iterable["TreeNode"]:
        yield self
        if self.kind == "group" and self.expanded:
            for c in self.children:
                yield from c.iter_visible()

    def depth(self) -> int:
        d = 0
        p = self.parent
        while p:
            d += 1
            p = p.parent
        return d

    # For disambiguating duplicate hostnames (site:&host)
    def top_level_group(self) -> Optional[str]:
        if self.parent is None:
            return None
        last = self
        p = self.parent
        while p and p.parent is not None:
            last = p
            p = p.parent
        return last.name if last is not self else None

    def collect_hosts(self) -> List[str]:
        if self.kind == "host":
            return [self.name] if self.checked == 2 else []
        out: List[str] = []
        for c in self.children:
            out.extend(c.collect_hosts())
        return out


class TreePane:
    """
    Scrollable tree with tri-state checkboxes.
    Keys:
      ./. move, PgUp/PgDn page, Home/End jump
      . collapse (or go parent), . expand
      SPACE toggle checkbox, ENTER expand/collapse
    """
    def __init__(self, win, title: str = "Inventory"):
        self.win = win
        self.title = title
        self.root: Optional[TreeNode] = None
        self._flat: List[TreeNode] = []  # visible nodes
        self.index = 0
        self.top = 0

    # ---------- data ----------
    def _expand_to_depth(self, node: TreeNode, depth: int):
        """Expand node and its subtree up to 'depth' (root at depth>=1)."""
        if depth <= 0 or node.kind != "group":
            return
        node.expanded = True
        for ch in node.children:
            self._expand_to_depth(ch, depth - 1)

    def set_tree(self, root_dict: dict, expand_levels: int = 3):
        self.root = TreeNode.from_dict(root_dict)
        if self.root:
            self._expand_to_depth(self.root, max(0, int(expand_levels)))
        self._rebuild_flat()
        self.index = 0
        self.top = 0

    def _rebuild_flat(self):
        self._flat = list(self.root.iter_visible()) if self.root else []

    # ---------- scrolling ----------
    def _visible_rows(self) -> int:
        h, _ = self.win.getmaxyx()
        return max(1, h - 2)

    def _ensure_cursor_visible(self):
        vis = self._visible_rows()
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + vis:
            self.top = self.index - vis + 1

    def move(self, delta: int):
        if not self._flat:
            return
        self.index = max(0, min(len(self._flat) - 1, self.index + delta))
        self._ensure_cursor_visible()

    def page_up(self):
        self.move(-self._visible_rows())

    def page_down(self):
        self.move(+self._visible_rows())

    def to_home(self):
        self.index = 0
        self._ensure_cursor_visible()

    def to_end(self):
        if self._flat:
            self.index = len(self._flat) - 1
            self._ensure_cursor_visible()

    # ---------- actions ----------
    def current(self) -> Optional[TreeNode]:
        if 0 <= self.index < len(self._flat):
            return self._flat[self.index]
        return None

    def toggle_check_current(self):
        n = self.current()
        if not n:
            return
        n.toggle_check()
        self._rebuild_flat()

    def expand_current(self):
        n = self.current()
        if not n:
            return
        if n.kind == "group":
            before = n.expanded
            n.expanded = True
            if not before:
                self._rebuild_flat()

    def collapse_current_or_go_parent(self):
        n = self.current()
        if not n:
            return
        if n.kind == "group" and n.expanded:
            n.expanded = False
            self._rebuild_flat()
        elif n.parent:
            p = n.parent
            try:
                idx = self._flat.index(p)
                self.index = idx
                self._ensure_cursor_visible()
            except ValueError:
                pass

    def toggle_expand_current(self):
        n = self.current()
        if not n:
            return
        if n.kind == "group" and n.children:
            n.toggle_expand()
            self._rebuild_flat()

    def get_selected_hosts(self) -> List[str]:
        return sorted(set(self.root.collect_hosts())) if self.root else []

    def get_selected_limit_patterns(self) -> List[str]:
        """
        Return a list of ansible --limit patterns with disambiguation:
        - If a hostname appears once => "hostname"
        - If the same hostname is selected under multiple sites => "SITE:&hostname" for each
        """
        if not self.root:
            return []
        selected: List[tuple[str, Optional[str]]] = []
        for node in self._flat:
            if node.kind == "host" and node.checked == 2:
                selected.append((node.name, node.top_level_group()))

        from collections import defaultdict
        counts = defaultdict(int)
        for h, _s in selected:
            counts[h] += 1

        out: List[str] = []
        for h, s in selected:
            if counts[h] > 1 and s:
                out.append(f"{s}:&{h}")
            else:
                out.append(h)
        # dedupe preserving order
        seen = set()
        uniq: List[str] = []
        for item in out:
            if item not in seen:
                seen.add(item)
                uniq.append(item)
        return uniq

    # ---------- render ----------
    def render(self):
        self.win.erase()
        self.win.box()
        box_title(self.win, self.title)

        if not self._flat:
            self.win.noutrefresh()
            return

        vis = self._visible_rows()
        start = max(0, min(self.top, max(0, len(self._flat) - vis)))
        end = min(len(self._flat), start + vis)

        h, w = self.win.getmaxyx()
        max_text_w = max(1, w - 4)  # borders + marker + space

        for row, node in enumerate(self._flat[start:end], start=1):
            is_cursor = (start + row - 1) == self.index
            attr = curses.A_REVERSE | curses.A_BOLD if is_cursor else 0

            cb = "[x]" if node.checked == 2 else "[-]" if node.checked == 1 else "[ ]"
            indent = "  " * node.depth()
            line = f"{indent}{cb} {node.name}"
            if len(line) > max_text_w:
                line = line[:max_text_w - 1] + "."

            # first column marker
            safe_addstr(self.win, row, 1, ">" if is_cursor else " ")
            # content
            safe_addstr(self.win, row, 3, line, attr)

        self.win.noutrefresh()

