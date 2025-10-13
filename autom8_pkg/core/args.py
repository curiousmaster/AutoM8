# =====================================================================
# File: autom8_pkg/core/args.py
# Command-line argument parsing
# =====================================================================
from __future__ import annotations
import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autom8",
        description="AutoM8 - Ansible Made Easy",
    )
    p.add_argument("--inventory", "-i", help="Inventory file or directory", default=None)
    p.add_argument("--playbook", "-p", help="Playbook path under ./playbooks", default=None)
    p.add_argument("--site", help="Preselect site (inventory var 'site')", default=None)
    p.add_argument("--targets", help="Comma-separated hosts to preselect", default=None)
    p.add_argument("-E", "--expand-levels", type=int, default=3, help="Initial tree expand levels (0=root only, default: 3)")
    p.add_argument("--no-splash", action="store_true", help="Skip splash screen")
    p.add_argument("--vault", action="store_true", help="Ask for Ansible vault password")
    p.add_argument("--debug", "-d", action="count", default=0, help="Increase verbosity")
    p.add_argument("--cwd", default=None, help="Override working directory")
    p.add_argument("--env", default=None, help="Environment file (.env)")
    return p


def parse_args(argv=None):
    return build_parser().parse_args(argv)

