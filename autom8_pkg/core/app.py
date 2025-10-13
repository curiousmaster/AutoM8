# =====================================================================
# File: autom8_pkg/core/app.py
# App with single dynamic Tree pane (foldable, tri-state checkboxes)
# Keeps: vault modal, command preview (wrapped), scrollable output, help modal
# =====================================================================

from __future__ import annotations
import curses
from pathlib import Path
from typing import List, Optional

from .args import parse_args
from .config import load_config
from .inventory import load_tree_data
from .playbooks import discover_playbooks, friendly_name
from .runner import LiveRunner, build_ansible_cmd
from .splash import run_splash

from ..ui.tree import TreePane
from ..ui.panes import (
    ListPane, SelectionPane, OutputPane, FooterPane,
    PasswordModalPane, TextModalPane
)
from ..utils.constants import (
    KEY_QUIT, KEY_RUN, KEY_REFRESH, KEY_TAB, KEY_SPACE,
    KEY_TOGGLE_VAULT, KEY_CLEAR_HOSTS, KEY_CLEAR_OUTPUT,
    KEY_PGUP, KEY_PGDN, KEY_HOME, KEY_END, KEY_SHOW_CMD, KEY_HELP,
    KEY_LEFT, KEY_RIGHT
)
from ..utils.files import find_project_root
from ..utils.logger import Logger


def _is_enter(ch: int) -> bool:
    return ch in (10, 13, getattr(curses, "KEY_ENTER", -1))


class AppState:
    def __init__(self):
        self.playbook_rel: Optional[str] = None
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

        self.p_tree: TreePane | None = None
        self.p_playbooks: ListPane | None = None
        self.p_select: SelectionPane | None = None
        self.p_output: OutputPane | None = None
        self.p_footer: FooterPane | None = None

        self.playbooks: List[Path] = []
        self.focus = 0  # 0=tree, 1=playbooks

    # ------------------------------ Layout ------------------------------
    def layout(self):
        h, w = self.stdscr.getmaxyx()
        top_h = max(10, int(h * 0.6))
        bottom_h = h - top_h - 1
        col_w = max(20, w // 4)

        if not self.p_tree:
            win_tree   = self.stdscr.derwin(top_h, col_w * 2, 0, 0);                 win_tree.keypad(True)
            win_pbs    = self.stdscr.derwin(top_h, col_w, 0, col_w * 2);             win_pbs.keypad(True)
            win_sel    = self.stdscr.derwin(top_h, w - (col_w * 3), 0, col_w * 3);   win_sel.keypad(True)
            win_output = self.stdscr.derwin(bottom_h, w, top_h, 0);                  win_output.keypad(True)
            win_footer = self.stdscr.derwin(1, w, h - 1, 0);                         win_footer.keypad(True)

            self.p_tree = TreePane(win_tree, "Inventory")
            self.p_playbooks = ListPane(win_pbs, "Playbooks")
            self.p_select = SelectionPane(win_sel)
            self.p_output = OutputPane(win_output)
            self.p_footer = FooterPane(win_footer)
        else:
            self.p_tree.win.resize(top_h, col_w * 2)
            self.p_playbooks.win.resize(top_h, col_w)
            self.p_select.win.resize(top_h, w - (col_w * 3))
            self.p_output.win.resize(bottom_h, w)
            self.p_footer.win.resize(1, w)

    # ------------------------------ Data ------------------------------
    def discover(self):
        # Build dynamic tree from inventory
        tree = load_tree_data(self.cfg.inventory_root)
        self.p_tree.set_tree(tree, expand_levels=self.cfg.expand_levels)

        # Playbooks
        self.playbooks = discover_playbooks(self.cfg.playbooks_root)
        pnames = [friendly_name(p, self.cfg.playbooks_root) for p in self.playbooks]
        self.p_playbooks.set_items(pnames)

    # ------------------------------ Render ------------------------------
    def render_all(self):
        self.layout()
        self.p_playbooks.focused = (self.focus == 1)

        # Selection pane summary
        hosts = self.p_tree.get_selected_hosts()
        self.p_select.set_site("(tree)")
        self.p_select.set_group("(tree)")
        self.p_select.set_playbook(self.state.playbook_rel or "(none)")
        self.p_select.set_vault(self.state.vault)
        self.p_select.set_hosts(hosts)

        # Draw panes
        self.p_tree.render()
        self.p_playbooks.render()
        self.p_select.render()
        self.p_output.render()
        self.p_footer.set_vault(self.state.vault)
        self.p_footer.render()
        curses.doupdate()

    # ------------------------------ Helpers ------------------------------
    def _build_command_preview(self) -> List[str]:
        playbook_abs = str((self.cfg.project_root / self.state.playbook_rel).resolve()) if self.state.playbook_rel else "(none)"
        inventory = str(self.cfg.inventory_root)
        hosts = self.p_tree.get_selected_limit_patterns()  # disambiguated

        parts = ["ansible-playbook", "-i", inventory, playbook_abs]
        if hosts:
            parts += ["--limit", ",".join(hosts)]
        if self.state.vault:
            parts += ["--vault-password-file", "******"]

        lines = [
            "COMMAND PREVIEW",
            "",
            f"Inventory : {inventory}",
            f"Playbook  : {self.state.playbook_rel or '(none)'}",
            f"Hosts     : {', '.join(hosts) if hosts else '(none)'}",
            f"Vault     : {'ON' if self.state.vault else 'OFF'}",
            "",
            "Full command:",
            "  " + " ".join(parts),
            "",
            "Note: Vault password file path is masked.",
        ]
        return lines

    # ------------------------------ Run ------------------------------
    def run(self):
        if self.state.running or not self.state.playbook_rel:
            return

        run_hosts = self.p_tree.get_selected_limit_patterns()
        if not run_hosts:
            return

        # Vault password modal if needed
        vault_pw_file = None
        if self.state.vault and not self.state.vault_password:
            pw = PasswordModalPane(self.stdscr, "Vault Password", "Enter vault password:").run()
            if pw is None:
                return
            self.state.vault_password = pw

        if self.state.vault and self.state.vault_password is not None:
            import tempfile, os
            tf = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
            tf.write(self.state.vault_password + "\n")
            tf.flush(); tf.close()
            os.chmod(tf.name, 0o600)
            vault_pw_file = tf.name

        playbook_abs = str((self.cfg.project_root / self.state.playbook_rel).resolve())
        inventory = str(self.cfg.inventory_root)

        cmd = build_ansible_cmd(
            playbook_path=playbook_abs,
            inventory=inventory,
            hosts=run_hosts,
            ask_vault=False,
            vault_password_file=vault_pw_file,
        )

        self.state.running = True
        try:
            # Output pane shows only live stdout
            self.p_output.clear()
            self.p_output.render()
            curses.doupdate()

            with LiveRunner(cmd, cwd=str(self.cfg.project_root)) as r:
                for chunk in r.stream():
                    follow = (self.p_output.scroll == 0)
                    self.p_output.append_bytes(chunk)
                    if follow:
                        self.p_output.to_bottom()
                    self.p_output.render()
                    curses.doupdate()
            _ = r.wait()
        finally:
            self.state.running = False
            if vault_pw_file:
                import os
                try:
                    os.remove(vault_pw_file)
                except Exception:
                    pass

    # ------------------------------ Loop ------------------------------
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
                self.focus = (self.focus + 1) % 2
                self.render_all()

            # --- Tree navigation ---
            elif self.focus == 0 and ch == curses.KEY_UP:
                self.p_tree.move(-1); self.render_all()
            elif self.focus == 0 and ch == curses.KEY_DOWN:
                self.p_tree.move(+1); self.render_all()
            elif self.focus == 0 and ch == KEY_PGUP:
                self.p_tree.page_up(); self.render_all()
            elif self.focus == 0 and ch == KEY_PGDN:
                self.p_tree.page_down(); self.render_all()
            elif self.focus == 0 and ch == KEY_HOME:
                self.p_tree.to_home(); self.render_all()
            elif self.focus == 0 and ch == KEY_END:
                self.p_tree.to_end(); self.render_all()
            elif self.focus == 0 and ch == KEY_LEFT:
                self.p_tree.collapse_current_or_go_parent(); self.render_all()
            elif self.focus == 0 and ch == KEY_RIGHT:
                self.p_tree.expand_current(); self.render_all()
            elif self.focus == 0 and ch in (KEY_SPACE,):
                self.p_tree.toggle_check_current(); self.render_all()
            elif self.focus == 0 and _is_enter(ch):
                self.p_tree.toggle_expand_current(); self.render_all()

            # --- Playbooks column ---
            elif self.focus == 1 and ch == curses.KEY_UP:
                self.p_playbooks.move(-1); self.render_all()
            elif self.focus == 1 and ch == curses.KEY_DOWN:
                self.p_playbooks.move(+1); self.render_all()
            elif self.focus == 1 and _is_enter(ch):
                name = self.p_playbooks.current()
                if name:
                    for p in self.playbooks:
                        if friendly_name(p, self.cfg.playbooks_root) == name:
                            self.state.playbook_rel = str(
                                p.resolve().relative_to(self.cfg.project_root.resolve())
                            )
                            break
                self.render_all()

            # --- Global toggles / utils ---
            elif ch == KEY_TOGGLE_VAULT:
                self.state.vault = not self.state.vault
                self.render_all()
            elif ch == KEY_CLEAR_HOSTS:
                if self.p_tree.root:
                    self.p_tree.root._set_checked_recursive(0)
                    self.p_tree._rebuild_flat()
                self.render_all()
            elif ch == KEY_CLEAR_OUTPUT:
                self.p_output.clear(); self.render_all()

            # Output scrolling (always active)
            elif ch == KEY_PGUP:
                self.p_output.page_up(); self.p_output.render(); curses.doupdate()
            elif ch == KEY_PGDN:
                self.p_output.page_down(); self.p_output.render(); curses.doupdate()
            elif ch == KEY_HOME:
                self.p_output.to_top(); self.p_output.render(); curses.doupdate()
            elif ch == KEY_END:
                self.p_output.to_bottom(); self.p_output.render(); curses.doupdate()

            elif ch == KEY_SHOW_CMD:
                TextModalPane(self.stdscr, "Command Preview", self._build_command_preview()).run()
                self.render_all()
            elif ch == KEY_HELP:
                TextModalPane(self.stdscr, "Help", self._build_help_lines()).run()
                self.render_all()
            else:
                pass

    # ------------------------------ Help ------------------------------
    def _build_help_lines(self) -> List[str]:
        return [
            "AUTO M8 . HELP (Tree selection)",
            "",
            "Tree (Inventory):",
            "  ./.            Move",
            "  PgUp/PgDn      Page up/down",
            "  Home/End (g/G) Jump to top/bottom",
            "  .               Collapse (or go to parent)",
            "  .               Expand",
            "  SPACE           Toggle checkbox",
            "  ENTER           Expand/Collapse",
            "",
            "Playbooks:",
            "  ENTER           Select playbook",
            "",
            "Run / Output:",
            f"  r / F5          Run playbook (Vault {'ON' if self.state.vault else 'OFF'})",
            "  v               Toggle Vault",
            "  x               Clear Output",
            "",
            "Misc:",
            "  ?               Command preview",
            "  h               Help (this)",
            "  q / ESC         Quit",
        ]


# ============================== Entrypoints ==============================
def run_curses(stdscr, cfg, log: Logger):
    stdscr.keypad(True)
    app = App(stdscr, cfg, log)
    app.layout()
    app.discover()
    app.render_all()
    app.loop()


def main(argv=None):
    args = parse_args(argv)
    project_root = find_project_root(args.cwd)
    cfg = load_config(
        project_root=project_root,
        inventory_override=args.inventory,
        playbook_override=args.playbook,
        site=None,
        targets=None,
        ask_vault=args.vault,
        splash_seconds=10,
        debug_level=args.debug or 0,
        expand_levels=args.expand_levels,   # NEW
    )
    logger = Logger(level=2 + min(1, args.debug)) if args.debug else Logger(level=2)

    if not args.no_splash:
        try:
            run_splash(seconds=cfg.splash_seconds)
        except Exception:
            pass

    return curses.wrapper(run_curses, cfg, logger)

