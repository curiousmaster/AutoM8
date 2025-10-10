# =====================================================================
# File: autom8_pkg/core/app.py
# Groups list triggers a checkbox modal to pick hosts (with 'All' on top)
# =====================================================================
from __future__ import annotations
import curses
from pathlib import Path
from typing import List, Optional

from .args import parse_args
from .config import load_config
from .inventory import discover_inventory, inventory_by_site, hosts_by_group, list_groups
from .playbooks import discover_playbooks, friendly_name
from .runner import LiveRunner, build_ansible_cmd
from .splash import run_splash
from ..ui.panes import CheckListPane, ListPane, SelectionPane, OutputPane, FooterPane, MultiCheckModalPane, PasswordModalPane, TextModalPane
from ..utils.constants import (
    KEY_QUIT, KEY_RUN, KEY_REFRESH, KEY_TAB, KEY_ENTER, KEY_SPACE,
    KEY_TOGGLE_VAULT, KEY_CLEAR_HOSTS, KEY_CLEAR_OUTPUT,
    KEY_PGUP, KEY_PGDN, KEY_HOME, KEY_END, KEY_SHOW_CMD, KEY_HELP
)
from ..utils.files import find_project_root
from ..utils.logger import Logger


def _is_enter(ch: int) -> bool:
    import curses
    return ch in (10, 13, getattr(curses, "KEY_ENTER", -1))

class AppState:
    def __init__(self):
        self.selected_sites: set[str] = set()   # empty => 'all'
        self.group: str = "(none)"
        self.playbook_rel: Optional[str] = None
        self.hosts: List[str] = []
        self.vault: bool = False
        self.vault_password: Optional[str] = None
        self.running: bool = False
        self.last_rc: Optional[int] = None

class App:
    def __init__(self, stdscr, cfg, log: Logger):
        self.stdscr = stdscr
        self.cfg = cfg
        self.log = log
        self.state = AppState()

        self.inventory_files: List[Path] = []
        self.site_map: dict[str, List[Path]] = {}
        self.group_map: dict[str, List[str]] = {}
        self.playbooks: List[Path] = []

        self.p_sites: CheckListPane | None = None
        self.p_groups: ListPane | None = None
        self.p_playbooks: ListPane | None = None
        self.p_select: SelectionPane | None = None
        self.p_output: OutputPane | None = None
        self.p_footer: FooterPane | None = None

        self.focus = 0  # 0=sites,1=groups,2=playbooks

    # ------------------------------ Layout ------------------------------
    def layout(self):
        h, w = self.stdscr.getmaxyx()
        top_h = max(10, int(h * 0.6))
        bottom_h = h - top_h - 1
        col_w = max(20, w // 4)

        if not self.p_sites:
            win_sites = self.stdscr.derwin(top_h, col_w, 0, 0)
            win_sites.keypad(True)

            win_groups = self.stdscr.derwin(top_h, col_w, 0, col_w)
            win_groups.keypad(True)

            win_play  = self.stdscr.derwin(top_h, col_w, 0, col_w * 2)
            win_play.keypad(True)

            win_sel   = self.stdscr.derwin(top_h, w - (col_w * 3), 0, col_w * 3)
            win_sel.keypad(True)

            win_output = self.stdscr.derwin(bottom_h, w, top_h, 0)
            win_output.keypad(True)

            win_footer = self.stdscr.derwin(1, w, h - 1, 0)
            win_footer.keypad(True)

            self.p_sites = CheckListPane(win_sites, "Sites")
            self.p_groups = ListPane(win_groups, "Target Types (Groups)")
            self.p_playbooks = ListPane(win_play, "Playbooks")
            self.p_select = SelectionPane(win_sel)
            self.p_output = OutputPane(win_output)
            self.p_footer = FooterPane(win_footer)
        else:
            self.p_sites.win.resize(top_h, col_w)
            self.p_groups.win.resize(top_h, col_w)
            self.p_playbooks.win.resize(top_h, col_w)
            self.p_select.win.resize(top_h, w - (col_w * 3))
            self.p_output.win.resize(bottom_h, w)
            self.p_footer.win.resize(1, w)

    # ------------------------------ Data ------------------------------
    def discover(self):
        self.inventory_files = discover_inventory(self.cfg.inventory_root)
        self.site_map = inventory_by_site(self.inventory_files)
        self.playbooks = discover_playbooks(self.cfg.playbooks_root)
    
        # Build Sites list:
        # - Always include 'all'
        # - Include named sites found
        # - Include 'other' ONLY if those files actually contain hosts
        sites = ["all"]
        named = sorted([s for s in self.site_map.keys() if s not in ("all", "other")])
        sites += named
    
        from .inventory import any_hosts_in_files  # local import to avoid cycles
        if "other" in self.site_map and any_hosts_in_files(self.site_map["other"]):
            sites.append("other")
    
        self.p_sites.set_items(sites)
    
        # Apply default selection (if provided), otherwise none => 'all'
        if self.cfg.default_site and self.cfg.default_site in sites:
            self.state.selected_sites = {self.cfg.default_site}
            self.p_sites.set_selected(list(self.state.selected_sites))
        else:
            self.state.selected_sites = set()
            self.p_sites.set_selected([])
    
        self.rebuild_groups()
    
        pnames = [friendly_name(p, self.cfg.playbooks_root) for p in self.playbooks]
        self.p_playbooks.set_items(pnames)

    def selected_site_names(self) -> list[str]:
        """
        Return the currently selected site names.
        Empty selection means 'all'.
        """
        return sorted(self.state.selected_sites) if self.state.selected_sites else ["all"]

    def rebuild_groups(self):
        if not self.state.selected_sites or "all" in self.state.selected_sites:
            files = self.inventory_files
        else:
            files = []
            for s in self.state.selected_sites:
                files.extend(self.site_map.get(s, []))
        self.group_map = hosts_by_group(files)
        self.p_groups.set_items(sorted(self.group_map.keys()))

    # ------------------------------ Render ------------------------------
    def render_all(self):
        self.layout()
        self.p_sites.focused = (self.focus == 0)
        self.p_groups.focused = (self.focus == 1)
        self.p_playbooks.focused = (self.focus == 2)

        site_label = ",".join(self.selected_site_names())
        self.p_select.set_site(site_label)
        self.p_select.set_group(self.state.group)
        self.p_select.set_playbook(self.state.playbook_rel or "(none)")
        self.p_select.set_vault(self.state.vault)
        self.p_select.set_hosts(self.state.hosts)

        self.p_sites.render()
        self.p_groups.render()
        self.p_playbooks.render()
        self.p_select.render()
        self.p_output.render()
        self.p_footer.set_vault(self.state.vault)
        self.p_footer.render()
        curses.doupdate()

    # ------------------------------ Actions ------------------------------
    def toggle_vault(self):
        self.state.vault = not self.state.vault

    def clear_hosts(self):
        self.state.hosts = []

    def clear_output(self):
        self.p_output.clear()

    # ------------------------------ Run ------------------------------
    def run(self):
        if self.state.running:
            return
        if not self.state.playbook_rel:
            # Do not write to output; simply refuse to run silently.
            return
    
        # If vault is ON, ensure we have a password; ask via modal if not.
        vault_pw_file = None
        if self.state.vault and not self.state.vault_password:
            pw = PasswordModalPane(self.stdscr, "Vault Password", "Enter vault password:").run()
            if pw is None:
                # User cancelled; do not write anything to Output pane.
                return
            self.state.vault_password = pw
    
        # If no explicit hosts selected but a group is chosen, default to all hosts in that group.
        run_hosts = list(self.state.hosts)
        if not run_hosts and self.state.group and self.state.group in self.group_map:
            run_hosts = list(self.group_map.get(self.state.group, []))
        if not run_hosts:
            # No hosts to run against; do not write to Output pane.
            return
    
        # Prepare vault password file if needed.
        if self.state.vault and self.state.vault_password is not None:
            import tempfile, os
            tf = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
            tf.write(self.state.vault_password + "\n")
            tf.flush(); tf.close()
            os.chmod(tf.name, 0o600)
            vault_pw_file = tf.name
    
        self.state.running = True
        try:
            # Clear previous text; from now on, only raw stdout goes in.
            self.p_output.clear()
            self.p_output.render()
            curses.doupdate()
    
            playbook_abs = str((self.cfg.project_root / self.state.playbook_rel).resolve())
            inventory = str(self.cfg.inventory_root)
    
            cmd = build_ansible_cmd(
                playbook_path=playbook_abs,
                inventory=inventory,
                hosts=run_hosts,
                ask_vault=False,                    # prefer file
                vault_password_file=vault_pw_file,  # may be None
            )
    
            # Stream live stdout/stderr (ANSI cleaned by OutputPane)
            with LiveRunner(cmd, cwd=str(self.cfg.project_root)) as r:
                for chunk in r.stream():
                    follow = (self.p_output.scroll == 0)  # only autoscroll if at bottom
                    self.p_output.append_bytes(chunk)
                    if follow:
                        self.p_output.to_bottom()
                    self.p_output.render()
                    curses.doupdate()
            _ = r.wait()  # Do not print "Finished with code ..." to output
        finally:
            self.state.running = False
            if vault_pw_file:
                import os
                try:
                    os.remove(vault_pw_file)
                except Exception:
                    pass
    
    
    def add_status(self, msg: str):
        self.p_output.append_bytes((msg + "\n").encode())

    # ------------------------------ Loop (add scroll keys) ------------------------------
    def loop(self):
        curses.curs_set(0)
        self.render_all()
        while True:
            ch = self.stdscr.getch()
            if ch in (KEY_QUIT, 27):
                break
            elif ch in (KEY_REFRESH, KEY_RUN, curses.KEY_F5):
                self.run()
            elif ch == KEY_TAB:
                self.focus = (self.focus + 1) % 3
                self.render_all()
            elif ch == curses.KEY_UP:
                (self.p_sites, self.p_groups, self.p_playbooks)[self.focus].move(-1)
                self.render_all()
            elif ch == curses.KEY_DOWN:
                (self.p_sites, self.p_groups, self.p_playbooks)[self.focus].move(+1)
                self.render_all()
            elif self.focus == 0 and (ch in (KEY_SPACE,) or _is_enter(ch)):
                self.p_sites.toggle_current()
                self.state.selected_sites = set(self.p_sites.get_selected())
                self.rebuild_groups()
                self.render_all()
            elif self.focus == 1 and _is_enter(ch):
                g = self.p_groups.current()
                if g:
                    hosts = self.group_map.get(g, [])
                    modal = MultiCheckModalPane(self.stdscr, f"Select Hosts . {g}", hosts,
                                                preselected=(self.state.hosts if self.state.group == g else []))
                    res = modal.run()
                    if res is not None:
                        self.state.group = g
                        self.state.hosts = res
                self.render_all()
            elif self.focus == 2 and _is_enter(ch):
                name = self.p_playbooks.current()
                if name:
                    for p in self.playbooks:
                        if friendly_name(p, self.cfg.playbooks_root) == name:
                            self.state.playbook_rel = str(p.resolve().relative_to(self.cfg.project_root.resolve()))
                            break
                self.render_all()
            elif ch == KEY_TOGGLE_VAULT:
                self.state.vault = not self.state.vault
                self.render_all()
            elif ch == KEY_CLEAR_HOSTS:
                self.state.hosts = []
                self.render_all()
            elif ch == KEY_CLEAR_OUTPUT:
                self.p_output.clear()
                self.render_all()
            # ---- Output scrolling (global) ----
            elif ch == KEY_PGUP:
                self.p_output.page_up(); self.p_output.render(); curses.doupdate()
            elif ch == KEY_PGDN:
                self.p_output.page_down(); self.p_output.render(); curses.doupdate()
            elif ch == KEY_HOME:
                self.p_output.to_top(); self.p_output.render(); curses.doupdate()
            elif ch == KEY_END:
                self.p_output.to_bottom(); self.p_output.render(); curses.doupdate()
            elif ch == KEY_SHOW_CMD:
                lines = self._build_command_preview()
                TextModalPane(self.stdscr, "Command Preview", lines).run()
                self.render_all()
            elif ch == KEY_HELP:
                TextModalPane(self.stdscr, "Help", self._build_help_lines()).run()
                self.render_all()
            else:
                pass


    def _build_help_lines(self) -> list[str]:
        vault_state = "ON" if self.state.vault else "OFF"
        return [
            "",
            "-----------------------------------------------------------------------------",
            "Navigation",
            "-----------------------------------------------------------------------------",
            "  TAB            |  Switch focus between columns (Sites / Groups / Playbooks)",
            "  ArrowUp/Down   |  Move selection in the focused column",
            "  PgUp / PgDn    |  Scroll Output pane",
            "  g / G          |  Output pane: top / bottom",
            "-----------------------------------------------------------------------------",
            "Sites column",
            "-----------------------------------------------------------------------------",
            "  SPACE / ENTER  |  Toggle checkbox for the highlighted Site",
            "-----------------------------------------------------------------------------",
            "Running",
            "-----------------------------------------------------------------------------",
            f"  r / F5         |  Run playbook (Vault: {vault_state})",
            "  v              |  Toggle Vault ON/OFF",
            "  ?              |  Show Command Preview (word-wrapped; vault path masked)",
            "-----------------------------------------------------------------------------",
            "Misc",
            "-----------------------------------------------------------------------------",
            "  x              |  Clear Output pane",
            "  c              |  Clear selected Hosts",
            "  h              |  Show this Help",
            "  q / ESC        |  Quit",
        ]
    

    def _build_command_preview(self) -> list[str]:
        playbook_abs = str((self.cfg.project_root / self.state.playbook_rel).resolve()) if self.state.playbook_rel else "(none)"
        inventory = str(self.cfg.inventory_root)
    
        # Determine hosts we.d run against (same logic as run())
        run_hosts = list(self.state.hosts)
        if not run_hosts and self.state.group and self.state.group in self.group_map:
            run_hosts = list(self.group_map.get(self.state.group, []))
    
        # Build a human-readable command (mask vault file)
        parts = ["ansible-playbook", "-i", inventory, playbook_abs]
        if run_hosts:
            parts += ["--limit", ",".join(run_hosts)]
        if self.state.vault:
            parts += ["--vault-password-file", "******"]
    
        lines = [
            "COMMAND PREVIEW",
            "",
            f"Inventory : {inventory}",
            f"Playbook  : {self.state.playbook_rel or '(none)'}",
            f"Hosts     : {', '.join(run_hosts) if run_hosts else '(none)'}",
            f"Vault     : {'ON' if self.state.vault else 'OFF'}",
            "",
            "Full command:",
            "  " + " ".join(parts),
            "",
            "Note: Vault password file path is masked.",
        ]
        return lines
    
# ============================== App entrypoints ==============================

def run_curses(stdscr, cfg, log: Logger):
    # Make sure the root screen understands keypad keys (ENTER, PgUp/PgDn, etc.)
    stdscr.keypad(True)

    app = App(stdscr, cfg, log)
    # Create panes first, then discover/populate
    app.layout()
    app.discover()
    app.render_all()
    app.loop()


def main(argv=None):
    # Parse CLI
    args = parse_args(argv)

    # Resolve project root and load config
    project_root = find_project_root(args.cwd)
    cfg = load_config(
        project_root=project_root,
        inventory_override=args.inventory,
        playbook_override=args.playbook,
        site=args.site,
        targets=args.targets,
        ask_vault=args.vault,
        splash_seconds=10,
        debug_level=args.debug or 0,
    )
    logger = Logger(level=2 + min(1, args.debug)) if args.debug else Logger(level=2)

    # Optional splash
    if not args.no_splash:
        try:
            run_splash(seconds=cfg.splash_seconds)
        except Exception:
            # Never fail the app because the splash couldn't render
            pass

    # Enter curses
    import curses
    return curses.wrapper(run_curses, cfg, logger)

