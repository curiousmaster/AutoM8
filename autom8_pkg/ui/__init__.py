# =====================================================================
# File: core/args.py
# Description: Command-line argument parsing for Autom8
# =====================================================================

"""
Defines and parses CLI arguments for Autom8, including:
  - Site filters (multi-site, case-insensitive)
  - Splash toggle (--no-splash)
"""

import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="Autom8 . Ansible TUI Wrapper")
    parser.add_argument("site", nargs="*", help="Optional site filters (case-insensitive, multi-word supported)")
    parser.add_argument("--no-splash", action="store_true", help="Disable splash screen")
    return parser.parse_args()

