#!/usr/bin/env python3
# ======================================================================
# File: autom8.py
# Name: Autom8 . Ansible TUI Wrapper
# ======================================================================
# SYNOPSIS
#   Autom8 is a curses-based terminal UI for selecting Inventories, Sites,
#   Target Types, relevant Playbooks, and Hosts, then running ansible-playbook.
#
# WHAT'S NEW (2025-10-09)
#   - . Detect + list multiple inventories from inventory/*.yml
#   - . Top horizontal "Inventories" tabs (./. to switch, ENTER to apply)
#   - . "ALL (merged)" option: UI merges all files; runner uses multiple -i
#   - . Site filtering still uses host var `site` (default "other")
#   - . Live ansible output fixed via PTY (unbuffered, colored)
#   - . Modal redraw fix (no black hole after closing)
#   - . Panes order: Site . Target Types . Playbooks . Selected Hosts . Output
#   - . CLI site pre-filter (case-insensitive, multi-word): `autom8 selu` / `autom8 Sweden North`
#   - . Loads ALL inventory files, then filters display by site (post-merge)
#   - . -h/--help via argparse, --no-splash toggle
#
# USAGE
#   pip install pyyaml
#   python3 autom8.py [--no-splash] [SITE ...]
#   (Run from repo root so inventory/*.yml and playbooks/*.yml exist)
#
# KEYS
#   Global:
#     TAB / SHIFT+TAB       : switch pane (SHIFT+TAB can be code 353)
#     q / ESC               : quit
#     v                     : toggle vault prompt (ON/OFF)
#     r or F5               : run ansible-playbook
#     x                     : clear Output/Status pane
#     c                     : clear selected hosts
#
#   Inventories (top tabs):
#     . / .                 : move between inventories (including ALL)
#     ENTER                 : apply selected inventory (reloads data)
#
#   Sites:
#     . / ., j / k          : navigate
#     ENTER                 : apply site filter
#
#   Target Types (groups):
#     . / ., j / k          : navigate
#     ENTER                 : open Host Selection modal
#
#   Playbooks:
#     . / ., j / k          : select playbook
#
#   Selection:
#     (read-only summary)
#
#   Output:
#     . / ., j / k, PgUp/PgDn, Home/End  : scroll
#
# CONFIG (env vars)
#   ATUI_INV_GLOB         default: inventory/*.yml
#   ATUI_INVENTORY        (legacy) single file path; if set, added to list
#   ATUI_PLAYBOOKS        default: playbooks/*.yml
#   AUTOM8_SPLASH         1 to show splash (default 1), 0 to disable
#   AUTOM8_SPLASH_SECS    splash duration seconds (default 3)
#   AUTOM8_LOGO_IDX       choose splash logo index (0..N-1), else random
#
# INVENTORY ASSUMPTIONS
#   - YAML inventory; hosts may live under groups via children.
#   - A host may define "site" var. If missing, defaults to "other".
#   - A group (incl. `all`) may define vars.site which inherits to children/hosts
#
# PLAYBOOK METADATA (optional, for better relevance filtering)
#   ---
#   metadata:
#     device_types:
#       - switch
#       - ios
#
# AUTHOR
#   Stefan Benediktsson (c) 2025
# ======================================================================

# ======================================================================
# Imports
# ======================================================================
import curses
import curses.panel
import os
import sys
import glob
import yaml
import subprocess
import threading
import queue
import time
import random
import tempfile
import pty
import fcntl
import termios
import argparse
from typing import Dict, List, Tuple, Set, Optional

# ======================================================================
# Configuration
# ======================================================================
INV_GLOB = os.environ.get("ATUI_INV_GLOB", "inventory/*.yml")
INV_LEGACY = os.environ.get("ATUI_INVENTORY")  # optional, legacy single file
PB_GLOB = os.environ.get("ATUI_PLAYBOOKS", "playbooks/*.yml")
SPLASH_ENABLED = os.environ.get("AUTOM8_SPLASH", "1") not in ("0", "false", "False", "")
try:
    SPLASH_SECS = float(os.environ.get("AUTOM8_SPLASH_SECS", "3"))
except ValueError:
    SPLASH_SECS = 3.0

# ======================================================================
# ASCII Art Logos
# ======================================================================
ASCII_LOGOS = [
r"""
   _____          __            _____     ______
  /  _  \  __ ___/  |_  ____   /     \   /  __  \
 /  /_\  \|  |  \   __\/  _ \ /  \ /  \  >      <
/    |    \  |  /|  | (  <_> )    Y    \/   --   \
\____|__  /____/ |__|  \____/\____|__  /\______  /
        \/                           \/        \/

 A u t o M 8   .   A n s i b l e  M a d e  E a s y
""",
]

try:
    _logo_idx = int(os.environ.get("AUTOM8_LOGO_IDX", "-1"))
except ValueError:
    _logo_idx = -1
ASCII_LOGO = ASCII_LOGOS[_logo_idx] if 0 <= _logo_idx < len(ASCII_LOGOS) else random.choice(ASCII_LOGOS)

# ======================================================================
# Utility (safe addstr)
# ======================================================================
def safe_addstr(win, y: int, x: int, s: str, maxw: int, attr: int = 0):
    if y < 0 or x < 0:
        return
    try:
        win.addnstr(y, x, s, maxw, attr)
    except curses.error:
        pass

# ======================================================================
# Inventory loader/merger
# ======================================================================

def _collect_hosts_from_group(group_dict) -> Set[str]:
    hosts = set()
    if not isinstance(group_dict, dict):
        return hosts
    if 'hosts' in group_dict and isinstance(group_dict['hosts'], dict):
        hosts.update(group_dict['hosts'].keys())
    if 'children' in group_dict and isinstance(group_dict['children'], dict):
        for _, child_group in group_dict['children'].items():
            hosts.update(_collect_hosts_from_group(child_group))
    return hosts


def _collect_sites_from_group(group_dict, host_sites: Dict[str, str], inherited_site: str = "other"):
    """Recursively collect host.site mappings, honoring group-level vars.site inheritance.
    - If a group has vars.site, it overrides the inherited site for that subtree.
    - A host-level 'site' key (under hosts.<name> dict) overrides group vars.
    - Falls back to 'other' when nothing is set.
    """
    if not isinstance(group_dict, dict):
        return

    site_here = inherited_site
    vars_d = group_dict.get("vars", {})
    if isinstance(vars_d, dict) and "site" in vars_d:
        s = str(vars_d.get("site", "")).strip()
        if s:
            site_here = s

    # Collect hosts under this group
    hosts_d = group_dict.get("hosts", {})
    if isinstance(hosts_d, dict):
        for h, attrs in hosts_d.items():
            host_site = site_here
            if isinstance(attrs, dict) and "site" in attrs:
                s2 = str(attrs.get("site", "")).strip()
                if s2:
                    host_site = s2
            if h not in host_sites or host_sites[h] == "other":
                host_sites[h] = host_site or "other"

    # Recurse into children groups
    children = group_dict.get("children", {})
    if isinstance(children, dict):
        for child in children.values():
            _collect_sites_from_group(child, host_sites, site_here)


def parse_inventory_dict(data: dict) -> Tuple[List[str], Dict[str, List[str]], Dict[str, str]]:
    """
    Returns (group_names, group_to_hosts, host_to_site) for a single parsed YAML dict.
    - Collects hosts under both `all.children.*` and any top-level groups.
    - Computes host.site by honoring group vars.site inheritance and host overrides.
    """
    host_sites: Dict[str, str] = {}

    # Gather sites with inheritance starting from 'all' and also from any top-level groups
    root = data.get("all", {}) if isinstance(data, dict) else {}
    _collect_sites_from_group(root, host_sites, inherited_site="other")

    # Also look at any additional top-level groups outside 'all'
    if isinstance(data, dict):
        for gname, gdict in data.items():
            if gname == "all" or not isinstance(gdict, dict):
                continue
            _collect_sites_from_group(gdict, host_sites, inherited_site="other")

    groups: List[str] = []
    mapping: Dict[str, List[str]] = {}

    # groups under all.children.*
    children = root.get('children', {}) if isinstance(root.get('children', {}), dict) else {}
    for gname, gdict in children.items():
        hosts = sorted(list(_collect_hosts_from_group(gdict)))
        groups.append(gname)
        mapping[gname] = hosts

    # top-level fallbacks (if any)
    if isinstance(data, dict):
        for gname, gdict in data.items():
            if gname == 'all' or not isinstance(gdict, dict):
                continue
            if gname not in mapping:
                mapping[gname] = sorted(list(_collect_hosts_from_group(gdict)))
                groups.append(gname)

    return sorted(groups), mapping, host_sites


def load_inventory_file(path: str) -> Tuple[List[str], Dict[str, List[str]], Dict[str, str]]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Inventory not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return parse_inventory_dict(data)


def merge_inventories(parts: List[Tuple[List[str], Dict[str, List[str]], Dict[str, str]]]
                      ) -> Tuple[List[str], Dict[str, List[str]], Dict[str, str]]:
    merged_groups: Set[str] = set()
    merged_map: Dict[str, Set[str]] = {}
    merged_sites: Dict[str, str] = {}

    for groups, gmap, hsites in parts:
        merged_groups.update(groups)
        for g, hosts in gmap.items():
            merged_map.setdefault(g, set()).update(hosts)
        # prefer first seen non-"other" site per host
        for h, s in hsites.items():
            if h not in merged_sites or merged_sites[h] == "other":
                merged_sites[h] = s

    final_map: Dict[str, List[str]] = {g: sorted(list(hs)) for g, hs in merged_map.items()}
    return sorted(list(merged_groups)), final_map, merged_sites

# ======================================================================
# Playbooks
# ======================================================================
DEVICE_KEYWORDS = [
    "switch", "router", "firewall", "asa", "nxos", "ios", "iosxe", "iosxr", "pan", "forti"
]


def load_playbooks(pb_glob: str) -> List[dict]:
    """
    Returns list of dicts: { 'file': path, 'name': base, 'types': [devicetype1, ...] }
    types are read from YAML 'metadata.device_types' if present in the header,
    else inferred from filename keywords.
    """
    files = sorted(glob.glob(pb_glob))
    results = []
    for f in files:
        types = []
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                head_lines = []
                for _ in range(80):
                    line = fh.readline()
                    if not line:
                        break
                    head_lines.append(line)
                head = ''.join(head_lines)
                y = yaml.safe_load(head)
                if isinstance(y, dict):
                    md = y.get("metadata", {})
                    if isinstance(md, dict):
                        dt = md.get("device_types", [])
                        if isinstance(dt, list):
                            types = [str(x).lower() for x in dt]
        except Exception:
            pass

        if not types:
            fname = os.path.basename(f).lower()
            types = [kw for kw in DEVICE_KEYWORDS if kw in fname]

        results.append({'file': f, 'name': os.path.basename(f), 'types': types})
    return results

# ======================================================================
# Basic UI panes
# ======================================================================
class ListPane:
    def __init__(self, win, title: str, items: List[str]):
        self.win = win
        self.title = title
        self.items = items
        self.idx = 0
        self.scroll = 0
        self.focus = False

    def set_items(self, items: List[str]):
        self.items = items
        self.idx = 0
        self.scroll = 0

    def current(self) -> str:
        return self.items[self.idx] if 0 <= self.idx < len(self.items) else ""

    def handle_key(self, ch):
        n = len(self.items)
        if n == 0:
            return
        if ch in (curses.KEY_UP, ord('k')):
            self.idx = (self.idx - 1) % n
        elif ch in (curses.KEY_DOWN, ord('j')):
            self.idx = (self.idx + 1) % n

    def draw(self):
        h, w = self.win.getmaxyx()
        self.win.erase()
        self.win.box()
        title = f" {self.title} "
        title_attr = curses.A_REVERSE if self.focus else curses.A_BOLD
        safe_addstr(self.win, 0, max(1, (w - len(title)) // 2), title, w - 2, title_attr)
        view_h = h - 2
        if self.idx < self.scroll:
            self.scroll = self.idx
        elif self.idx >= self.scroll + view_h:
            self.scroll = self.idx - view_h + 1
        for i in range(view_h):
            j = self.scroll + i
            if j >= len(self.items):
                break
            line = self.items[j]
            attr = curses.A_REVERSE if (self.focus and j == self.idx) else curses.A_NORMAL
            safe_addstr(self.win, 1 + i, 1, line, w - 2, attr)
        self.win.noutrefresh()

class OutputPane:
    def __init__(self, win, title="Output / Status"):
        self.win = win
        self.title = title
        self.lines: List[str] = []
        self.scroll = 0
        self.focus = False

    def append(self, text: str):
        for line in text.splitlines():
            self.lines.append(line)
        self.draw()

    def clear(self):
        self.lines = []
        self.scroll = 0
        self.draw()

    def handle_key(self, ch):
        h, w = self.win.getmaxyx()
        view_h = max(1, h - 2)
        max_scroll = max(0, len(self.lines) - view_h)
        if ch in (curses.KEY_UP, ord('k')):
            self.scroll = max(0, self.scroll - 1)
        elif ch in (curses.KEY_DOWN, ord('j')):
            self.scroll = min(max_scroll, self.scroll + 1)
        elif ch == curses.KEY_NPAGE:  # PgDn
            self.scroll = min(max_scroll, self.scroll + view_h)
        elif ch == curses.KEY_PPAGE:  # PgUp
            self.scroll = max(0, self.scroll - view_h)
        elif ch == curses.KEY_HOME:
            self.scroll = 0
        elif ch == curses.KEY_END:
            self.scroll = max_scroll

    def draw(self):
        h, w = self.win.getmaxyx()
        self.win.erase()
        self.win.box()
        title = f" {self.title} "
        title_attr = curses.A_REVERSE if self.focus else curses.A_BOLD
        safe_addstr(self.win, 0, max(1, (w - len(title)) // 2), title, w - 2, title_attr)
        view_h = max(1, h - 2)
        max_scroll = max(0, len(self.lines) - view_h)
        self.scroll = max(0, min(self.scroll, max_scroll))
        start = self.scroll
        visible = self.lines[start:start + view_h]
        for i, line in enumerate(visible):
            safe_addstr(self.win, 1 + i, 1, line, max(1, w - 3))
        # scrollbar
        if len(self.lines) > view_h:
            sb_h = max(1, int(view_h * view_h / len(self.lines)))
            sb_top = int((view_h - sb_h) * (start / max(1, len(self.lines) - view_h)))
            for i in range(sb_h):
                try:
                    self.win.addch(1 + sb_top + i, w - 2, '|')
                except curses.error:
                    pass
        self.win.noutrefresh()

class SelectionPane:
    def __init__(self, win, title="Selection"):
        self.win = win
        self.title = title
        self.focus = False
        self.data = {
            "inventory": ".",
            "site": ".",
            "target": ".",
            "playbook": ".",
            "hosts": [],
            "vault": False
        }

    def update(self, inventory=None, site=None, target=None, playbook=None, hosts=None, vault=None):
        if inventory is not None:
            self.data["inventory"] = inventory
        if site is not None:
            self.data["site"] = site
        if target is not None:
            self.data["target"] = target
        if playbook is not None:
            self.data["playbook"] = playbook
        if hosts is not None:
            self.data["hosts"] = hosts
        if vault is not None:
            self.data["vault"] = vault

    def draw(self):
        h, w = self.win.getmaxyx()
        self.win.erase()
        self.win.box()
        title = f" {self.title} "
        title_attr = curses.A_REVERSE if self.focus else curses.A_BOLD
        safe_addstr(self.win, 0, max(1, (w - len(title)) // 2), title, w - 2, title_attr)

        lines = [
            f"Inventory: {self.data['inventory']}",
            f"Site:      {self.data['site']}",
            f"Target:    {self.data['target']}",
            f"Playbook:  {self.data['playbook']}",
            f"Vault:     {'ON' if self.data['vault'] else 'OFF'}",
            "",
            f"Hosts ({len(self.data['hosts'])}):"
        ]
        host_list = sorted(self.data["hosts"])
        lines.extend(host_list if host_list else ["  ."])

        for i, line in enumerate(lines[:h - 2]):
            safe_addstr(self.win, 1 + i, 1, line, w - 2)

        self.win.noutrefresh()

# ======================================================================
# Modals
# ======================================================================
class HostModal:
    def __init__(self, stdscr, title: str, hosts: List[str], preselected: Set[str] = None):
        self.stdscr = stdscr
        self.title = title
        self.hosts = hosts
        self.selected: Set[str] = set(preselected or set())
        self.idx = 0
        self.scroll = 0

    def show(self) -> Set[str]:
        maxy, maxx = self.stdscr.getmaxyx()
        height = min(maxy - 4, 20)
        width = min(maxx - 4, 80)
        y = (maxy - height) // 2
        x = (maxx - width) // 2
        win = curses.newwin(height, width, y, x)
        win.keypad(True)

        while True:
            win.erase()
            win.box()
            title = f" {self.title} (SPACE=toggle, ENTER=save, ESC=cancel) "
            safe_addstr(win, 0, max(1, (width - len(title)) // 2), title, width - 2, curses.A_BOLD)

            view_h = height - 2
            if self.idx < self.scroll:
                self.scroll = self.idx
            elif self.idx >= self.scroll + view_h:
                self.scroll = self.idx - view_h + 1

            for i in range(view_h):
                j = self.scroll + i
                if j >= len(self.hosts):
                    break
                hname = self.hosts[j]
                checked = "[x]" if hname in self.selected else "[ ]"
                marker = ">" if j == self.idx else " "
                line = f"{marker} {checked} {hname}"
                attr = curses.A_REVERSE if j == self.idx else curses.A_NORMAL
                safe_addstr(win, 1 + i, 1, line, width - 2, attr)

            win.noutrefresh()
            curses.doupdate()

            ch = win.getch()
            if ch in (curses.KEY_UP, ord('k')):
                self.idx = (self.idx - 1) % max(1, len(self.hosts))
            elif ch in (curses.KEY_DOWN, ord('j')):
                self.idx = (self.idx + 1) % max(1, len(self.hosts))
            elif ch == ord(' '):
                if 0 <= self.idx < len(self.hosts):
                    h = self.hosts[self.idx]
                    if h in self.selected:
                        self.selected.remove(h)
                    else:
                        self.selected.add(h)
            elif ch in (10, 13, curses.KEY_ENTER):
                # Properly clean overlay
                curses.curs_set(0)
                curses.panel.update_panels()
                # Full screen repaint to avoid .black hole.
                self.stdscr.clear()
                self.stdscr.refresh()
                return set(self.selected)
            elif ch == 27:  # ESC
                curses.curs_set(0)
                curses.panel.update_panels()
                self.stdscr.clear()
                self.stdscr.refresh()
                return set(preselected or set())

class PasswordModal:
    def __init__(self, stdscr, title="Vault Password"):
        self.stdscr = stdscr
        self.title = title
        self.password = ""

    def show(self) -> str:
        maxy, maxx = self.stdscr.getmaxyx()
        height, width = 7, 50
        y = (maxy - height) // 2
        x = (maxx - width) // 2
        win = curses.newwin(height, width, y, x)
        win.keypad(True)
        curses.curs_set(1)

        while True:
            win.erase()
            win.box()
            safe_addstr(win, 0, max(1, (width - len(self.title)) // 2),
                        f" {self.title} (ENTER=OK, ESC=cancel) ", width - 2, curses.A_BOLD)
            safe_addstr(win, 3, 2, "Password: " + "*" * len(self.password), width - 4)
            win.noutrefresh()
            curses.doupdate()

            ch = win.getch()
            if ch in (10, 13, curses.KEY_ENTER):
                curses.curs_set(0)
                curses.panel.update_panels()
                self.stdscr.clear()
                self.stdscr.refresh()
                return self.password
            elif ch == 27:  # ESC
                curses.curs_set(0)
                curses.panel.update_panels()
                self.stdscr.clear()
                self.stdscr.refresh()
                return ""
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                self.password = self.password[:-1]
            elif 32 <= ch <= 126:
                self.password += chr(ch)

# ======================================================================
# Inventories top tabs pane
# ======================================================================
class InventoriesPane:
    """
    A horizontal tabs bar listing:
      [ ALL ] [ SEDEF.yml ] [ SELU.yml ] ...
    Keys: ./. to move, ENTER to apply.
    """
    def __init__(self, win, title: str, items: List[str]):
        self.win = win
        self.title = title
        self.items = items  # display names (e.g., 'ALL (merged)', 'SEDEF.yml')
        self.idx = 0
        self.focus = True

    def set_items(self, items: List[str]):
        self.items = items
        self.idx = 0

    def current(self) -> str:
        return self.items[self.idx] if 0 <= self.idx < len(self.items) else ""

    def handle_key(self, ch):
        if not self.items:
            return
        if ch in (curses.KEY_LEFT,):
            self.idx = (self.idx - 1) % len(self.items)
        elif ch in (curses.KEY_RIGHT,):
            self.idx = (self.idx + 1) % len(self.items)

    def draw(self):
        h, w = self.win.getmaxyx()
        self.win.erase()
        self.win.box()
        title = f" {self.title} (./. to select, ENTER to load) "
        title_attr = curses.A_REVERSE if self.focus else curses.A_BOLD
        safe_addstr(self.win, 0, max(1, (w - len(title)) // 2), title, w - 2, title_attr)

        # render centered tabs
        if not self.items:
            self.win.noutrefresh()
            return

        tab_texts = []
        for i, name in enumerate(self.items):
            if i == self.idx and self.focus:
                tab_texts.append(f"[{name}]")
            else:
                tab_texts.append(f" {name} ")
        text = "  ".join(tab_texts)
        safe_addstr(self.win, 1, max(1, (w - len(text)) // 2), text, w - 2)

        self.win.noutrefresh()

# ======================================================================
# Runner (PTY for live output)
# ======================================================================
class Runner(threading.Thread):
    def __init__(self, cmd: List[str], outq: queue.Queue, env: Optional[dict] = None):
        super().__init__(daemon=True)
        self.cmd = cmd
        self.outq = outq
        self.env = env or os.environ.copy()

    def run(self):
        try:
            self.outq.put(("info", "$ " + " ".join(self.cmd)))

            # allocate PTY so ansible plays nice with line buffering + colors
            master_fd, slave_fd = pty.openpty()

            # Set raw-ish mode for smoother reading
            try:
                attrs = termios.tcgetattr(master_fd)
                attrs[3] = attrs[3] & ~(termios.ECHO | termios.ICANON)
                termios.tcsetattr(master_fd, termios.TCSANOW, attrs)
            except Exception:
                pass

            proc = subprocess.Popen(
                self.cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=self.env,
                text=False,  # PTY gives us bytes; we decode per line
                bufsize=0,
                close_fds=True
            )
            os.close(slave_fd)

            # read loop
            with os.fdopen(master_fd, 'rb', buffering=0) as m:
                buf = b""
                while True:
                    chunk = m.read(1)
                    if not chunk:
                        break
                    if chunk == b' ':
                        try:
                            line = buf.decode(errors='replace')
                        except Exception:
                            line = repr(buf)
                        self.outq.put(("out", line))
                        buf = b""
                    else:
                        buf += chunk

            rc = proc.wait()
            # flush tail if any
            if buf:
                try:
                    self.outq.put(("out", buf.decode(errors='replace')))
                except Exception:
                    self.outq.put(("out", repr(buf)))
            self.outq.put(("info", f"[Process exited with code {rc}]"))
        except FileNotFoundError:
            self.outq.put(("err", "ansible-playbook not found in PATH"))
        except Exception as e:
            self.outq.put(("err", f"Exception: {e!r}"))

# ======================================================================
# Splash
# ======================================================================
def show_splash(stdscr):
    if not SPLASH_ENABLED:
        return
    stdscr.clear()
    stdscr.refresh()
    lines = ASCII_LOGO.splitlines()
    height = len(lines) + 4
    width = max(len(l) for l in lines) + 4
    maxy, maxx = stdscr.getmaxyx()
    y = max(0, (maxy - height) // 2)
    x = max(0, (maxx - width) // 2)
    win = curses.newwin(height, width, y, x)
    win.box()
    for i, l in enumerate(lines):
        safe_addstr(win, 2 + i, 2, l, width - 4)
    safe_addstr(win, height - 2, 2, "Press any key to skip...", width - 4, curses.A_DIM)
    win.refresh()
    stdscr.nodelay(True)
    start = time.time()
    while True:
        if stdscr.getch() != -1:
            break
        if time.time() - start >= SPLASH_SECS:
            break
        time.sleep(0.10)
    stdscr.nodelay(False)
    stdscr.clear()
    stdscr.refresh()

# ======================================================================
# App
# ======================================================================
class App:
    def __init__(self, stdscr, site_arg: Optional[str] = None):
        self.stdscr = stdscr
        curses.curs_set(0)
        self.stdscr.nodelay(False)
        self.stdscr.keypad(True)

        # Splash
        show_splash(self.stdscr)

        # --- Inventories discovery ---
        self.inventory_files: List[str] = sorted(glob.glob(INV_GLOB))
        if INV_LEGACY and os.path.exists(INV_LEGACY) and INV_LEGACY not in self.inventory_files:
            self.inventory_files.append(INV_LEGACY)

        if not self.inventory_files:
            raise FileNotFoundError(f"No inventories found with pattern {INV_GLOB} (or ATUI_INVENTORY).")

        # build inventory display names (always show all files)
        self.inv_display: List[str] = ["ALL (merged)"] + [os.path.basename(p) for p in self.inventory_files]
        self.inv_selected_idx = 0  # 0 means ALL
        self.inv_display_to_path: Dict[str, Optional[str]] = {"ALL (merged)": None}
        for p in self.inventory_files:
            self.inv_display_to_path[os.path.basename(p)] = p

        # Playbooks
        self.playbooks_meta = load_playbooks(PB_GLOB)

        # CLI site filter handling
        self.cli_site_raw: Optional[str] = site_arg if site_arg else None
        self.cli_site: Optional[str] = self.cli_site_raw.strip() if self.cli_site_raw else None
        self.cli_site_norm: Optional[str] = self.cli_site.lower() if self.cli_site else None

        # Load combined data initially (ALL merged), then apply CLI site filter after merge
        groups_all, gmap_all, hsites_all = self._load_current_inventory_data(raw=True)
        total_hosts_all = len(hsites_all)
        if self.cli_site_norm:
            groups_f, gmap_f, hsites_f = self._apply_cli_site_filter(groups_all, gmap_all, hsites_all)
            self._cli_info_msg = f"[INFO] Filtered {len(hsites_f)} of {total_hosts_all} hosts for site {self.cli_site}"
            groups, gmap, hsites = groups_f, gmap_f, hsites_f
        else:
            self._cli_info_msg = None
            groups, gmap, hsites = groups_all, gmap_all, hsites_all
        self.groups, self.group_hosts, self.host_sites = groups, gmap, hsites

        # Sites
        if self.cli_site:
            self.sites = [self.cli_site]
        else:
            sites = sorted(set(self.host_sites.values())) if self.host_sites else []
            self.sites = ["all"] + (sites if sites else ["other"])

        # State
        self.selected_hosts: Set[str] = set()
        self.ask_vault = False

        # Filtered views
        self.filtered_groups = list(self.groups)
        self.filtered_playbooks = list(self.playbooks_meta)
        self._last_group_for_filter = None  # to re-filter playbooks on change

        # Layout
        maxy, maxx = self.stdscr.getmaxyx()
        # Top bar for inventories
        top_bar_h = 3
        remaining_h = maxy - top_bar_h
        top_h = remaining_h - 10 if remaining_h > 24 else remaining_h - 8
        bot_h = max(6, remaining_h - top_h)

        col_w = max(20, maxx // 4)
        # Inventories bar full width
        self.win_inv = curses.newwin(top_bar_h, maxx, 0, 0)
        # Four top panes:
        self.win_sites = curses.newwin(top_h, col_w, top_bar_h, 0)
        self.win_groups = curses.newwin(top_h, col_w, top_bar_h, col_w)
        self.win_pb = curses.newwin(top_h, col_w, top_bar_h, col_w * 2)
        self.win_sel = curses.newwin(top_h, maxx - col_w * 3, top_bar_h, col_w * 3)
        # Bottom output
        self.win_out = curses.newwin(bot_h, maxx, top_bar_h + top_h, 0)

        self.pane_inv = InventoriesPane(self.win_inv, "Inventories", self.inv_display)
        self.pane_sites = ListPane(self.win_sites, (
            f"Sites (locked: {self.cli_site})" if self.cli_site else "Sites"
        ), self.sites)
        self.pane_groups = ListPane(self.win_groups, "Target Types (Groups)", self.filtered_groups)
        self.pane_pb = ListPane(self.win_pb, "Playbooks", [pb['name'] for pb in self.filtered_playbooks])
        self.pane_sel = SelectionPane(self.win_sel, "Selection")
        self.pane_out = OutputPane(self.win_out, "Output / Status")

        # One-time CLI filter info message
        self._cli_info_printed = False
        if self._cli_info_msg and not self._cli_info_printed:
            self.pane_out.append(self._cli_info_msg)
            self._cli_info_printed = True

        # Navigation order: Inventories . Sites . Groups . Playbooks . Selection . Output
        self.panes = [self.pane_inv, self.pane_sites, self.pane_groups, self.pane_pb, self.pane_sel, self.pane_out]
        self.focus_idx = 0
        self.panes[self.focus_idx].focus = True

        # Async runner
        self.outq: queue.Queue = queue.Queue()
        self.runner: Optional[Runner] = None

        # Pre-select CLI site filter on start (no-op if only one item)
        if self.cli_site:
            self.pane_sites.idx = 0
            self.apply_site_filter()
            self.pane_out.append(f"Site pre-filter active: {self.cli_site}")

    # ------------------ Helpers for CLI site filtering ------------------ #
    def _apply_cli_site_filter(self, groups: List[str], gmap: Dict[str, List[str]], hsites: Dict[str, str]) -> Tuple[List[str], Dict[str, List[str]], Dict[str, str]]:
        """Return (groups,gmap,hsites) filtered to only hosts matching self.cli_site_norm (case-insensitive)."""
        if not self.cli_site_norm:
            return groups, gmap, hsites
        filtered_hsites = {h: s for h, s in hsites.items() if str(s).lower() == self.cli_site_norm}
        new_gmap: Dict[str, List[str]] = {}
        new_groups: List[str] = []
        for g, hosts in gmap.items():
            sel = [h for h in hosts if h in filtered_hsites]
            if sel:
                new_gmap[g] = sel
                new_groups.append(g)
        return sorted(new_groups), new_gmap, filtered_hsites

    # ------------------ Inventory data loader ------------------ #
    def _load_current_inventory_data(self, raw: bool = False) -> Tuple[List[str], Dict[str, List[str]], Dict[str, str]]:
        """
        If inv_selected_idx == 0 . ALL (merged) across self.inventory_files
        Else . single selected inventory file
        If raw=True, never apply CLI site filtering (caller will post-filter).
        Otherwise, apply CLI site filter within this method for correctness on tab change.
        """
        if self.inv_selected_idx == 0:
            parts = []
            for p in self.inventory_files:
                try:
                    parts.append(load_inventory_file(p))
                except Exception:
                    # Non-fatal: ignore broken inventories
                    pass
            if not parts:
                raise RuntimeError("Failed to load any inventories for ALL (merged).")
            groups, gmap, hsites = merge_inventories(parts)
        else:
            disp = self.inv_display[self.inv_selected_idx]
            path = self.inv_display_to_path.get(disp)
            if not path:
                raise FileNotFoundError(f"Selected inventory path not found for {disp}")
            groups, gmap, hsites = load_inventory_file(path)

        if raw:
            return groups, gmap, hsites
        # Apply CLI site filter if set
        if self.cli_site_norm:
            return self._apply_cli_site_filter(groups, gmap, hsites)
        return groups, gmap, hsites

    # ------------------ Filters ------------------ #
    def apply_site_filter(self):
        site = self.pane_sites.current()
        if site == "all":
            groups = list(self.groups)
        else:
            allowed_hosts = {h for h, s in self.host_sites.items() if s == site}
            groups = []
            for g, hosts in self.group_hosts.items():
                if any(h in allowed_hosts for h in hosts):
                    groups.append(g)
            # trim selected hosts to this site
            self.selected_hosts = {h for h in self.selected_hosts if h in allowed_hosts}

        groups.sort()
        self.filtered_groups = groups
        self.pane_groups.set_items(self.filtered_groups)
        self._last_group_for_filter = None  # force re-filter on next loop

        # update selection pane
        self.pane_sel.update(site=site, hosts=sorted(self.selected_hosts))

    def apply_playbook_filter(self):
        group = self.pane_groups.current()
        if not group:
            self.filtered_playbooks = list(self.playbooks_meta)
        else:
            g = group.lower()
            filtered = []
            for pb in self.playbooks_meta:
                types = pb.get('types', [])
                if not types:
                    filtered.append(pb)  # generic playbook -> keep
                elif g in types or any(g in t for t in types):
                    filtered.append(pb)
                else:
                    if g in pb['name'].lower():
                        filtered.append(pb)
            self.filtered_playbooks = filtered if filtered else list(self.playbooks_meta)
        self.pane_pb.set_items([pb['name'] for pb in self.filtered_playbooks])

    # ------------------ Status & nav helpers ------------------ #
    def draw_status(self):
        maxy, maxx = self.stdscr.getmaxyx()
        status = (
            f"[TAB] switch  [ENTER] Inventories=load / Sites=filter / Groups=hosts  "
            f"[r/F5] run  [v] vault:{'ON' if self.ask_vault else 'OFF'}  [c] clear hosts  [x] clear output  [q] quit"
        )
        safe_addstr(self.stdscr, maxy - 1, 0, " " * (maxx - 1), maxx - 1)
        safe_addstr(self.stdscr, maxy - 1, 1, status, maxx - 2, curses.A_REVERSE)

    def cycle_focus(self, backward=False):
        self.panes[self.focus_idx].focus = False
        self.focus_idx = (self.focus_idx - 1 if backward else self.focus_idx + 1) % len(self.panes)
        self.panes[self.focus_idx].focus = True

    def open_host_modal(self):
        group = self.pane_groups.current()
        if not group:
            return
        site = self.pane_sites.current()
        hosts = list(self.group_hosts.get(group, []))
        if site != "all":
            hosts = [h for h in hosts if self.host_sites.get(h, "other") == site]
        hosts = sorted(hosts)
        modal = HostModal(self.stdscr, f"Select hosts in '{group}'", hosts,
                          preselected=self.selected_hosts & set(hosts))
        new_sel = modal.show()

        # ensure full redraw after closing modal
        self.stdscr.touchwin()
        self.stdscr.refresh()

        # merge selections
        self.selected_hosts = (self.selected_hosts - set(hosts)) | new_sel

        # update selection pane
        self.pane_sel.update(target=group, hosts=sorted(self.selected_hosts))

    def _build_inventory_cli_args(self) -> List[str]:
        """
        For runner: when ALL (merged) is selected, pass multiple -i <file> flags.
        Otherwise a single -i.
        """
        if self.inv_selected_idx == 0:
            args: List[str] = []
            for path in self.inventory_files:
                args.extend(["-i", path])
            return args
        else:
            disp = self.inv_display[self.inv_selected_idx]
            path = self.inv_display_to_path.get(disp)
            return ["-i", path] if path else []

    def run_ansible(self):
        if not self.filtered_playbooks:
            self.pane_out.append("No playbooks available.")
            return
        pb_idx = self.pane_pb.idx
        if pb_idx < 0 or pb_idx >= len(self.filtered_playbooks):
            self.pane_out.append("No playbook selected.")
            return
        if not self.selected_hosts:
            self.pane_out.append("No hosts selected. Use ENTER on a group to pick hosts.")
            return

        # choose the actual file path for the displayed playbook name
        selected_name = self.pane_pb.current()
        pb_file = None
        for pb in self.filtered_playbooks:
            if pb['name'] == selected_name:
                pb_file = pb['file']
                break
        if not pb_file:
            self.pane_out.append("Failed to locate playbook file.")
            return

        limit = ",".join(sorted(list(self.selected_hosts)))

        cmd = ["ansible-playbook"] + self._build_inventory_cli_args() + ["-l", limit, pb_file]

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.setdefault("ANSIBLE_FORCE_COLOR", "1")
        # Leave default callback; PTY ensures streaming

        vault_file = None
        if self.ask_vault:
            modal = PasswordModal(self.stdscr, "Enter Vault Password")
            password = modal.show()
            # redraw main screen after closing modal
            self.stdscr.touchwin()
            self.stdscr.refresh()

            if password.strip():
                vault_file = tempfile.NamedTemporaryFile(delete=False, mode="w", encoding="utf-8")
                vault_file.write(password)
                vault_file.close()
                cmd.extend(["--vault-password-file", vault_file.name])
            else:
                self.pane_out.append("Vault password prompt canceled.")
                return

        if self.runner and self.runner.is_alive():
            self.pane_out.append("A run is already in progress.")
            return

        self.pane_out.clear()
        self.pane_out.append("Running: " + " ".join(cmd))
        self.runner = Runner(cmd, self.outq, env=env)
        self.runner.start()

        # cleanup vault file when done
        def _cleanup():
            try:
                self.runner.join()
            except Exception:
                pass
            if vault_file and os.path.exists(vault_file.name):
                try:
                    os.remove(vault_file.name)
                except OSError:
                    pass
        threading.Thread(target=_cleanup, daemon=True).start()

    def pump_runner_output(self, nonblock=True):
        try:
            while True:
                kind, msg = self.outq.get_nowait() if nonblock else self.outq.get()
                if kind in ("out", "info"):
                    self.pane_out.append(msg)
                elif kind == "err":
                    self.pane_out.append(f"[ERROR] {msg}")
        except queue.Empty:
            pass

    # ------------------ Main loop ------------------ #
    def _reload_inventories_apply(self):
        # Re-load current selection.s data
        try:
            groups, gmap, hsites = self._load_current_inventory_data(raw=False)
        except Exception as e:
            self.pane_out.append(f"[ERROR] Failed loading inventory: {e}")
            return

        # Apply to state
        self.groups, self.group_hosts, self.host_sites = groups, gmap, hsites

        # rebuild sites (keep locked if CLI site is used)
        if self.cli_site:
            self.sites = [self.cli_site]
        else:
            sites = sorted(set(self.host_sites.values())) if self.host_sites else []
            self.sites = ["all"] + (sites if sites else ["other"])
        self.pane_sites.set_items(self.sites)

        # clear selections that might not exist anymore
        self.selected_hosts.clear()

        # reset groups/playbooks
        self.filtered_groups = list(self.groups)
        self.pane_groups.set_items(self.filtered_groups)
        self._last_group_for_filter = None
        self.apply_playbook_filter()  # reset playbooks list

        # refresh selection summary
        inv_name = self.inv_display[self.inv_selected_idx]
        self.pane_sel.update(inventory=inv_name, site=self.pane_sites.current(),
                             target=self.pane_groups.current(), playbook=self.pane_pb.current(),
                             hosts=sorted(self.selected_hosts))

    def mainloop(self):
        SHIFT_TAB = getattr(curses, 'KEY_BTAB', 353)

        # Initial selection inventory name
        self.pane_sel.update(inventory=self.inv_display[self.inv_selected_idx])

        while True:
            # auto-apply playbook filter when group selection changes
            current_group = self.pane_groups.current()
            if current_group != self._last_group_for_filter:
                self.apply_playbook_filter()
                self._last_group_for_filter = current_group

            # keep selection pane synchronized every frame
            self.pane_sel.update(
                inventory=self.inv_display[self.inv_selected_idx],
                site=self.pane_sites.current(),
                target=self.pane_groups.current(),
                playbook=self.pane_pb.current(),
                hosts=sorted(self.selected_hosts),
                vault=self.ask_vault
            )

            # draw panes
            for p in self.panes:
                p.draw()
            self.draw_status()
            curses.doupdate()

            # pump ansible output
            self.pump_runner_output(nonblock=True)

            ch = self.stdscr.getch()
            if ch == -1:
                continue

            # navigation keys
            if ch == 9:  # TAB
                self.cycle_focus(False)
                continue
            elif ch == SHIFT_TAB:
                self.cycle_focus(True)
                continue

            # global keys
            if ch in (ord('q'), 27):  # q / ESC
                break
            elif ch == ord('v'):
                self.ask_vault = not self.ask_vault
                continue
            elif ch == ord('c'):
                self.selected_hosts.clear()
                continue
            elif ch == ord('x'):  # clear output
                self.pane_out.clear()
                continue
            elif ch in (ord('r'), curses.KEY_F5):
                self.run_ansible()
                continue

            # per-pane actions
            focused = self.panes[self.focus_idx]

            # Inventories top tabs
            if focused is self.pane_inv:
                if ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
                    focused.handle_key(ch)
                    continue
                if ch in (10, 13, curses.KEY_ENTER):
                    self.inv_selected_idx = self.pane_inv.idx  # apply
                    self._reload_inventories_apply()
                    # hard repaint to avoid artifacts
                    self.stdscr.clear()
                    self.stdscr.refresh()
                    continue

            # Sites ENTER applies filter
            if focused is self.pane_sites and ch in (10, 13, curses.KEY_ENTER):
                self.apply_site_filter()
                continue
            # Groups ENTER opens host modal
            elif focused is self.pane_groups and ch in (10, 13, curses.KEY_ENTER):
                self.open_host_modal()
                continue

            # per-pane navigation / scrolling
            if hasattr(focused, "handle_key"):
                focused.handle_key(ch)

# ======================================================================
# Entrypoint
# ======================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        prog="autom8",
        description="Autom8 . Ansible TUI Wrapper for selecting inventories, sites, and playbooks."
    )
    parser.add_argument(
        "site",
        nargs="*",
        help="Optional site filter (case-insensitive, all trailing words are joined as one filter)."
    )
    parser.add_argument(
        "--no-splash",
        action="store_true",
        help="Disable splash screen at startup."
    )
    return parser.parse_args()


def _wrap(stdscr, site_arg: Optional[str] = None):
    try:
        app = App(stdscr, site_arg=site_arg)
        app.mainloop()
    except Exception as e:
        curses.endwin()
        print(f"Fatal error: {e}", file=sys.stderr)
        raise


def main():
    args = parse_args()

    # Disable splash if requested
    global SPLASH_ENABLED
    if args.no_splash:
        SPLASH_ENABLED = False

    # Join all site words into one filter string
    site_arg = " ".join(args.site).strip()
    if site_arg == "":
        site_arg = None

    # Quick sanity: playbooks exist?
    if not glob.glob(PB_GLOB):
        print(f"No playbooks found at {PB_GLOB}", file=sys.stderr)
        sys.exit(1)

    curses.wrapper(_wrap, site_arg=site_arg)


if __name__ == "__main__":
    main()

