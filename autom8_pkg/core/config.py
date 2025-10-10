# =====================================================================
# File: autom8_pkg/core/config.py
# App configuration loading and defaults
# =====================================================================
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_COLOR_SCHEME = {
    "accent": "green",
    "accent2": "blue",
    "text": "white",
    "muted": "cyan",
}


@dataclass
class AppConfig:
    project_root: Path
    inventory_root: Path
    playbooks_root: Path
    color_scheme: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_COLOR_SCHEME))
    splash_seconds: int = 10
    splash_skippable: bool = True
    default_site: Optional[str] = None
    default_targets: List[str] = field(default_factory=list)
    default_playbook: Optional[str] = None
    ask_vault: bool = False
    debug_level: int = 0


def load_config(
    project_root: Path,
    inventory_override: Optional[str] = None,
    playbook_override: Optional[str] = None,
    site: Optional[str] = None,
    targets: Optional[str] = None,
    ask_vault: bool = False,
    splash_seconds: int = 10,
    debug_level: int = 0,
) -> AppConfig:
    inv_root = Path(inventory_override) if inventory_override else project_root / "inventory"
    pb_root = project_root / "playbooks"

    default_targets: List[str] = []
    if targets:
        default_targets = [h.strip() for h in targets.split(",") if h.strip()]

    return AppConfig(
        project_root=project_root,
        inventory_root=inv_root,
        playbooks_root=pb_root,
        default_site=site,
        default_targets=default_targets,
        default_playbook=playbook_override,
        ask_vault=ask_vault,
        splash_seconds=splash_seconds,
        debug_level=debug_level,
    )

