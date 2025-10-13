# =====================================================================
# File: autom8_pkg/core/inventory.py
# Inventory discovery + tree loader (ansible-inventory first, YAML fallback)
# Level-agnostic (any depth), safe for mixed formats
# =====================================================================

from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional, Set
import json
import re
import subprocess

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

# -------------------- Generic discovery helpers --------------------

YAML_SITE_RE = re.compile(r"^\s*site\s*:\s*([A-Za-z0-9_\-]+)\s*$")
KEY_RE = re.compile(r"^([A-Za-z0-9_.\-]+):\s*$")
SKIP_GROUPS: Set[str] = {"all", "ungrouped", "children", "vars", "hosts", "_meta"}


def discover_inventory(inventory_root: Path) -> List[Path]:
    """Find inventory files under a root directory or return the single file."""
    if inventory_root.is_file():
        return [inventory_root]
    files: List[Path] = []
    if inventory_root.exists():
        for ext in ("*.yml", "*.yaml", "hosts", "hosts.yml"):
            files += list(inventory_root.rglob(ext))
    return sorted(set(files))


# -------------------- Prefer ansible-inventory --list --------------------

def _ansible_inventory_json(inventory_root: Path) -> Optional[dict]:
    try:
        out = subprocess.check_output(
            ["ansible-inventory", "-i", str(inventory_root), "--list"],
            stderr=subprocess.STDOUT,
        )
        return json.loads(out.decode("utf-8", errors="ignore"))
    except Exception:
        return None


def _dict_tree_from_ansible_list(data: dict) -> Optional[dict]:
    """
    Convert `ansible-inventory --list` JSON (flat group map) into a nested tree.
    children is a LIST of group names; hosts may be LIST or DICT.
    """
    if not isinstance(data, dict):
        return None

    groups = {k: v for k, v in data.items() if isinstance(v, dict) and k != "_meta"}
    if not groups:
        return None

    def _hosts_from(node: dict) -> List[str]:
        h = node.get("hosts", {})
        if isinstance(h, dict):
            return [str(x) for x in h.keys()]
        if isinstance(h, list):
            return [str(x) for x in h]
        return []

    def _children_from(node: dict) -> List[str]:
        c = node.get("children", [])
        if isinstance(c, dict):
            return [str(x) for x in c.keys()]
        if isinstance(c, list):
            return [str(x) for x in c]
        return []

    def build_group(name: str, seen: Optional[Set[str]] = None) -> dict:
        if seen is None:
            seen = set()
        if name in seen:
            # avoid cycles
            return {"name": name, "kind": "group", "children": []}
        seen = set(seen) | {name}

        node = groups.get(name, {})
        children_nodes: List[dict] = []

        # child groups first
        for child_name in _children_from(node):
            children_nodes.append(build_group(child_name, seen))

        # then hosts
        for host in _hosts_from(node):
            children_nodes.append({"name": host, "kind": "host", "children": []})

        return {"name": name, "kind": "group", "children": children_nodes}

    root_name = "all" if "all" in groups else next(iter(groups.keys()))
    return build_group(root_name)


# -------------------- YAML fallback (tolerant merge) --------------------

def _yaml_merge_groups(dst: dict, src: dict):
    """
    Deep-merge group dicts. Accepts canonical:
      { children: {...}, hosts: {...}, vars: {...} }
    and tolerant form where arbitrary keys (not hosts/children/vars)
    are treated as implicit child groups.
    """
    if not isinstance(src, dict):
        return

    # vars (shallow)
    if "vars" in src and isinstance(src["vars"], dict):
        dst.setdefault("vars", {}).update(src["vars"])

    # hosts
    if "hosts" in src and isinstance(src["hosts"], dict):
        dst.setdefault("hosts", {})
        dst["hosts"].update(src["hosts"])

    # children
    if "children" in src and isinstance(src["children"], dict):
        dst.setdefault("children", {})
        for cname, cnode in src["children"].items():
            dst["children"].setdefault(cname, {})
            _yaml_merge_groups(dst["children"][cname], cnode if isinstance(cnode, dict) else {})

    # implicit children: any other mapping keys
    for k, v in src.items():
        if k in ("vars", "hosts", "children"):
            continue
        if isinstance(v, dict):
            dst.setdefault("children", {})
            dst["children"].setdefault(k, {})
            _yaml_merge_groups(dst["children"][k], v)


def _load_yaml_merged(inventory_root: Path) -> Optional[dict]:
    files = discover_inventory(inventory_root)
    if not files:
        return None

    root = {"children": {}, "hosts": {}}
    any_data = False

    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            if yaml is None:
                continue
            data = yaml.safe_load(content) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        g = data.get("all")
        if not isinstance(g, dict):
            g = data  # accept file with a single group mapping
        _yaml_merge_groups(root, g)
        any_data = True

    if not any_data:
        return None

    def build_group(name: str, node: dict) -> dict:
        children_out: List[dict] = []
        c = node.get("children", {})
        if isinstance(c, dict):
            for gname, gnode in c.items():
                if not isinstance(gnode, dict):
                    gnode = {}
                children_out.append(build_group(gname, gnode))
        h = node.get("hosts", {})
        if isinstance(h, dict):
            for hname in h.keys():
                children_out.append({"name": str(hname), "kind": "host", "children": []})
        return {"name": name, "kind": "group", "children": children_out}

    return build_group("all", root)


# -------------------- Public API --------------------

def load_tree_data(inventory_root: Path) -> dict:
    """
    Return a nested tree dict of the inventory:
      { "name": "all", "kind": "group", "children": [ ... ] }
    Prefer ansible-inventory --list; fallback to YAML merge.
    """
    data = _ansible_inventory_json(inventory_root)
    if data is not None:
        tree = _dict_tree_from_ansible_list(data)
        if tree is not None:
            return tree
    tree = _load_yaml_merged(inventory_root)
    return tree or {"name": "all", "kind": "group", "children": []}

