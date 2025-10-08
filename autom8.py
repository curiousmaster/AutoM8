#!/usr/bin/env python3
#======================================================================
# File: autom8.py
# Name: Autom8 . Ansible TUI Wrapper
#
#======================================================================
# SYNOPSIS
#   Autom8 is a curses-based terminal UI for selecting Sites, Target Types,
#   relevant Playbooks, and Hosts, then running ansible-playbook.
#
# DESCRIPTION
#   - Parses inventory/hosts.yml (YAML) for groups and hosts
#   - Derives Sites from host var `site` (defaults to "other")
#   - Filters Target Types (groups) by selected Site
#   - Filters Playbooks by relevance to selected Target Type using:
#       * playbook metadata.device_types, or
#       * filename keywords fallback
#   - Selection pane shows Site / Target / Playbook / Vault / Hosts
#   - Curses-native vault password modal (writes temp --vault-password-file)
#   - Displays full subprocess output in the Output/Status pane
#   - Output pane supports scrolling, shows a scrollbar, and can be cleared
#   - Focus highlighting: active pane title uses reverse video
#   - Panes order: Site | Target Types | Playbooks | Selection | Output/Status
#
# USAGE
#   pip install pyyaml
#   python3 autom8.py
#     (Run from repo root so inventory/hosts.yml and playbooks/*.yml exist)
#
# KEYS
#   TAB / SHIFT+TAB  : switch pane (SHIFT+TAB also 353 on some terms)
#   ./. or j/k       : navigate lists (or scroll output when focused there)
#   PgUp/PgDn        : page scroll (in output pane)
#   ENTER on Sites   : apply site filter
#   ENTER on Groups  : open host selection modal
#   SPACE (in modal) : toggle host selection
#   v                : toggle vault mode (ON/OFF)
#   r or F5          : run ansible-playbook
#   c                : clear selected hosts
#   x                : clear Output/Status pane
#   q / ESC          : quit
#
# CONFIG (env vars)
#   ATUI_INVENTORY       default: inventory/hosts.yml
#   ATUI_PLAYBOOKS       default: playbooks/*.yml
#   AUTOM8_SPLASH        1 to show splash (default 1), 0 to disable
#   AUTOM8_SPLASH_SECS   splash duration seconds (default 3)
#   AUTOM8_LOGO_IDX      choose splash logo index (0..N-1), else random
#
# INVENTORY ASSUMPTIONS
#   - YAML format. Hosts can be nested under groups via children.
#   - Example host with site:
#       all:
#         children:
#           switches:
#             hosts:
#               sw1:
#                 site: eu
#               sw2:
#                 site: us
#
# PLAYBOOK METADATA (optional for better filtering)
#   ---
#   metadata:
#     device_types:
#       - switch
#       - nxos
#   # ... tasks etc.
#
# AUTHOR
#   Stefan Benediktsson (c) 2025
#======================================================================

#======================================================================
# Imports
#======================================================================
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
from typing import Dict, List, Tuple, Set

#======================================================================
# Configuration
#======================================================================
INV_PATH = os.environ.get("ATUI_INVENTORY", "inventory/hosts.yml")
PB_GLOB = os.environ.get("ATUI_PLAYBOOKS", "playbooks/*.yml")
SPLASH_ENABLED = os.environ.get("AUTOM8_SPLASH", "1") not in ("0", "false", "False", "")
try:
    SPLASH_SECS = float(os.environ.get("AUTOM8_SPLASH_SECS", "3"))
except ValueError:
    SPLASH_SECS = 3.0

#======================================================================
# ASCII Art Logos (Autom8) . include your current logo as default
#======================================================================
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

#======================================================================
# Utility (safe addstr)
#======================================================================
def safe_addstr(win, y: int, x: int, s: str, maxw: int, attr: int = 0):
    """
    Wrap curses.addnstr with bounds checking and a max width.
    Avoids errors when terminal is small or string is wide.
    """
    if y < 0 or x < 0:
        return
    try:
        win.addnstr(y, x, s, maxw, attr)
    except curses.error:
        # Some terminals throw even on clipped, just ignore
        pass

#======================================================================
# Inventory & Playbook helpers
#======================================================================
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

def load_inventory(inv_path: str) -> Tuple[List[str], Dict[str, List[str]], Dict[str, str]]:
    """
    Returns (group_names, group_to_hosts, host_to_site)
    - host_to_site default "other" when not set
    """
    if not os.path.exists(inv_path):
        raise FileNotFoundError(f"Inventory not found: {inv_path}")
    with open(inv_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    host_sites: Dict[str, str] = {}

    def collect_sites(gdict):
        if not isinstance(gdict, dict):
            return
        if "hosts" in gdict and isinstance(gdict["hosts"], dict):
            for h, attrs in gdict["hosts"].items():
                site = "other"
                if isinstance(attrs, dict) and "site" in attrs:
                    site = str(attrs["site"]).strip() or "other"
                host_sites[h] = site
        if "children" in gdict and isinstance(gdict["children"], dict):
            for c in gdict["children"].values():
                collect_sites(c)

    collect_sites(data.get("all", {}))

    groups: List[str] = []
    mapping: Dict[str, List[str]] = {}

    root = data.get('all', {})
    children = root.get('children', {}) if isinstance(root.get('children', {}), dict) else {}
    for gname, gdict in children.items():
        hosts = sorted(list(_collect_hosts_from_group(gdict)))
        groups.append(gname)
        mapping[gname] = hosts

    # top-level groups fallback (in case groups aren't only under "all.children")
    for gname, gdict in data.items():
        if gname == 'all' or not isinstance(gdict, dict):
            continue
        if gname not in mapping:
            mapping[gname] = sorted(list(_collect_hosts_from_group(gdict)))
            groups.append(gname)

    return sorted(groups), mapping, host_sites

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
        # Try reading a small header for metadata
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

#======================================================================
# Basic UI elements
#======================================================================
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
        self.scroll = 0   # number of lines down from top (top=0)
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
        elif ch == curses.KEY_NPAGE:  # Page Down
            self.scroll = min(max_scroll, self.scroll + view_h)
        elif ch == curses.KEY_PPAGE:  # Page Up
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

        # content
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

#======================================================================
# Selection Summary Pane
#======================================================================
class SelectionPane:
    def __init__(self, win, title="Selection"):
        self.win = win
        self.title = title
        self.focus = False
        self.data = {
            "site": ".",
            "target": ".",
            "playbook": ".",
            "hosts": [],
            "vault": False
        }

    def update(self, site=None, target=None, playbook=None, hosts=None, vault=None):
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
            f"Site:      {self.data['site']}",
            f"Target:    {self.data['target']}",
            f"Playbook:  {self.data['playbook']}",
            f"Vault:     {'ON' if self.data['vault'] else 'OFF'}",
            "",
            f"Hosts ({len(self.data['hosts'])}):"
        ]
        host_list = sorted(self.data["hosts"])
        if host_list:
            lines.extend(host_list)
        else:
            lines.append("  .")

        for i, line in enumerate(lines[:h - 2]):
            safe_addstr(self.win, 1 + i, 1, line, w - 2)

        self.win.noutrefresh()

#======================================================================
# Modals: Host Selection & Password
#======================================================================
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
                curses.panel.update_panels()
                return set(self.selected)
            elif ch == 27:  # ESC
                curses.panel.update_panels()
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
                return self.password
            elif ch == 27:  # ESC
                curses.curs_set(0)
                curses.panel.update_panels()
                return ""
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                self.password = self.password[:-1]
            elif 32 <= ch <= 126:
                self.password += chr(ch)

#======================================================================
# Runner (async subprocess)
#======================================================================
class Runner(threading.Thread):
    def __init__(self, cmd: List[str], outq: queue.Queue):
        super().__init__(daemon=True)
        self.cmd = cmd
        self.outq = outq

    def run(self):
        try:
            self.outq.put(("info", "$ " + " ".join(self.cmd)))
            proc = subprocess.Popen(
                self.cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                bufsize=1
            )
            for line in iter(proc.stdout.readline, ''):
                self.outq.put(("out", line.rstrip("\n")))
            rc = proc.wait()
            self.outq.put(("info", f"[Process exited with code {rc}]"))
        except FileNotFoundError:
            self.outq.put(("err", "ansible-playbook not found in PATH"))
        except Exception as e:
            self.outq.put(("err", f"Exception: {e!r}"))

#======================================================================
# Splash
#======================================================================
def show_splash(stdscr):
    if not SPLASH_ENABLED:
        return

    stdscr.clear()
    stdscr.refresh()

    lines = ASCII_LOGO.strip("\n").splitlines()
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

#======================================================================
# App
#======================================================================
class App:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0)
        self.stdscr.nodelay(False)
        self.stdscr.keypad(True)

        # Splash first
        show_splash(self.stdscr)

        # Data
        self.playbooks_meta = load_playbooks(PB_GLOB)        # list of dicts
        self.groups, self.group_hosts, self.host_sites = load_inventory(INV_PATH)

        # Sites
        sites = sorted(set(self.host_sites.values())) if self.host_sites else []
        self.sites = ["all"] + (sites if sites else ["other"])

        # State
        self.selected_hosts: Set[str] = set()
        self.ask_vault = False

        # Filtered views
        self.filtered_groups = list(self.groups)
        self.filtered_playbooks = list(self.playbooks_meta)
        self._last_group_for_filter = None  # to re-filter playbooks on change

        # Layout: Site | Target Types | Playbooks | Selection (top) + Output (bottom)
        maxy, maxx = self.stdscr.getmaxyx()
        top_h = maxy - 10 if maxy > 24 else maxy - 8
        bot_h = maxy - top_h
        col_w = max(20, maxx // 4)

        self.win_sites = curses.newwin(top_h, col_w, 0, 0)
        self.win_groups = curses.newwin(top_h, col_w, 0, col_w)
        self.win_pb = curses.newwin(top_h, col_w, 0, col_w * 2)
        self.win_sel = curses.newwin(top_h, maxx - col_w * 3, 0, col_w * 3)
        self.win_out = curses.newwin(bot_h, maxx, top_h, 0)

        self.pane_sites = ListPane(self.win_sites, "Sites", self.sites)
        self.pane_groups = ListPane(self.win_groups, "Target Types (Groups)", self.filtered_groups)
        self.pane_pb = ListPane(self.win_pb, "Playbooks", [pb['name'] for pb in self.filtered_playbooks])
        self.pane_sel = SelectionPane(self.win_sel, "Selection")
        self.pane_out = OutputPane(self.win_out, "Output / Status")

        self.panes = [self.pane_sites, self.pane_groups, self.pane_pb, self.pane_sel, self.pane_out]
        self.focus_idx = 0
        self.panes[self.focus_idx].focus = True

        # Async runner
        self.outq: queue.Queue = queue.Queue()
        self.runner: Runner | None = None

    #------------------ Filters ------------------#
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
                    # filename fallback heuristic
                    if g in pb['name'].lower():
                        filtered.append(pb)
            self.filtered_playbooks = filtered if filtered else list(self.playbooks_meta)
        self.pane_pb.set_items([pb['name'] for pb in self.filtered_playbooks])

    #------------------ Helpers ------------------#
    def draw_status(self):
        maxy, maxx = self.stdscr.getmaxyx()
        status = f"[TAB] switch  [ENTER] Sites=filter / Groups=hosts  [r/F5] run  [v] vault:{'ON' if self.ask_vault else 'OFF'}  [c] clear hosts  [x] clear output  [q] quit"
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
        cmd = ["ansible-playbook", "-i", INV_PATH, "-l", limit, pb_file]

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
        self.runner = Runner(cmd, self.outq)
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

    #------------------ Main loop ------------------#
    def mainloop(self):
        # Include Output pane in navigation (already included in self.panes)
        # Also support SHIFT+TAB as KEY_BTAB or code 353
        SHIFT_TAB = getattr(curses, 'KEY_BTAB', 353)

        while True:
            # auto-apply playbook filter when group selection changes
            current_group = self.pane_groups.current()
            if current_group != self._last_group_for_filter:
                self.apply_playbook_filter()
                self._last_group_for_filter = current_group

            # keep selection pane synchronized every frame
            self.pane_sel.update(
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

            # enter actions by pane
            focused = self.panes[self.focus_idx]
            if focused is self.pane_sites and ch in (10, 13, curses.KEY_ENTER):
                self.apply_site_filter()
                continue
            elif focused is self.pane_groups and ch in (10, 13, curses.KEY_ENTER):
                self.open_host_modal()
                continue

            # per-pane navigation / scrolling
            if hasattr(focused, "handle_key"):
                focused.handle_key(ch)

#======================================================================
# Entrypoint
#======================================================================
def _wrap(stdscr):
    try:
        app = App(stdscr)
        app.mainloop()
    except Exception as e:
        # Ensure terminal is reset on crash
        curses.endwin()
        print(f"Fatal error: {e}", file=sys.stderr)
        raise

def main():
    if not os.path.exists(INV_PATH):
        print(f"Missing inventory: {INV_PATH}", file=sys.stderr)
        sys.exit(1)
    if not glob.glob(PB_GLOB):
        print(f"No playbooks found at {PB_GLOB}", file=sys.stderr)
        sys.exit(1)
    curses.wrapper(_wrap)

if __name__ == "__main__":
    main()
