# =====================================================================
# File: autom8_pkg/core/inventory.py
# Robust inventory parsing with YAML (recursive children -> hosts)
# =====================================================================
from __future__ import annotations
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import re

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

YAML_SITE_RE  = re.compile(r"^\s*site\s*:\s*([A-Za-z0-9_\-]+)\s*$")
KEY_RE        = re.compile(r"^([A-Za-z0-9_.\-]+):\s*$")
SKIP_GROUPS: Set[str] = {"all", "ungrouped", "children", "vars", "hosts"}

# ------------------- discovery / site -------------------

def discover_inventory(inventory_root: Path) -> List[Path]:
    if inventory_root.is_file():
        return [inventory_root]
    files: List[Path] = []
    if inventory_root.exists():
        for ext in ("*.yml", "*.yaml", "hosts", "hosts.yml"):
            files += list(inventory_root.rglob(ext))
    return sorted(set(files))

def extract_sites(inv_file: Path) -> Optional[str]:
    try:
        with inv_file.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = YAML_SITE_RE.match(line.strip())
                if m:
                    return m.group(1)
    except OSError:
        return None
    return None

def inventory_by_site(inventory_files: List[Path]) -> Dict[str, List[Path]]:
    mapping: Dict[str, List[Path]] = {}
    for f in inventory_files:
        s = extract_sites(f) or "other"
        mapping.setdefault(s, []).append(f)
    return mapping

# ------------------- YAML-based parsing (fixed) -------------------

def _collect_groups_recursive(name: str, node: dict, groups: Dict[str, dict]):
    """Register this group and recursively register all children."""
    if not isinstance(node, dict):
        return
    # Register group itself
    groups.setdefault(name, {})
    # Merge shallow maps
    for k, v in node.items():
        if k not in groups[name]:
            groups[name][k] = v
        else:
            if isinstance(groups[name][k], dict) and isinstance(v, dict):
                groups[name][k].update(v)
            else:
                groups[name][k] = v
    # Recurse into children
    ch = node.get("children", {})
    if isinstance(ch, dict):
        for child_name, child_node in ch.items():
            if isinstance(child_name, str) and isinstance(child_node, dict):
                _collect_groups_recursive(child_name, child_node, groups)

def _groups_from_yaml(data: dict) -> Dict[str, dict]:
    """
    Return a mapping of group_name -> node for ALL groups found anywhere,
    including under all.children.* (recursively).
    """
    groups: Dict[str, dict] = {}
    if not isinstance(data, dict):
        return groups
    # 1) Top-level keys (e.g., 'all', direct groups)
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, dict):
            _collect_groups_recursive(k, v, groups)
    return groups

def _resolve_hosts(group_name: str, groups: Dict[str, dict], seen: Optional[Set[str]] = None) -> Set[str]:
    """Return the full set of hosts for a group, recursing into its children."""
    if seen is None:
        seen = set()
    if group_name in seen:
        return set()
    seen.add(group_name)
    node = groups.get(group_name, {})
    hosts: Set[str] = set()
    # direct hosts
    hmap = node.get("hosts", {})
    if isinstance(hmap, dict):
        for hk in hmap.keys():
            if isinstance(hk, str):
                hosts.add(hk)
    # children
    cmap = node.get("children", {})
    if isinstance(cmap, dict):
        for child in cmap.keys():
            if isinstance(child, str):
                hosts |= _resolve_hosts(child, groups, seen)
    return hosts

def _collect_from_yaml(data: dict) -> Tuple[Dict[str, List[str]], List[str]]:
    """
    Returns (hostmap, grouplist)
      hostmap: group -> [hosts...]
      grouplist: all visible groups (even if they have 0 hosts)
    """
    groups = _groups_from_yaml(data)
    # Visible groups = everything except structural names
    visible = [g for g in groups.keys() if g not in SKIP_GROUPS]
    hostmap: Dict[str, List[str]] = {}
    for g in visible:
        hostmap[g] = sorted(_resolve_hosts(g, groups))
    return hostmap, sorted(visible)

# ------------------- Fallback tolerant text scanner -------------------

def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))

def _is_key(line: str) -> Optional[str]:
    m = KEY_RE.match(line.strip())
    return m.group(1) if m else None

def _collect_from_text(text: str) -> Tuple[Dict[str, List[str]], List[str]]:
    """
    Fallback: detect groups under 'children:' and '<group>: hosts:' blocks.
    Returns (hostmap, grouplist)
    """
    hostmap: Dict[str, List[str]] = {}
    headers: Set[str] = set()

    stack: List[tuple[int, str]] = []
    current_group: Optional[str] = None
    in_hosts_for: Optional[str] = None

    for raw in text.splitlines():
        if not raw.strip():
            continue
        ind = _indent(raw)
        while stack and stack[-1][0] >= ind:
            popped_indent, popped_key = stack.pop()
            if in_hosts_for and popped_key == "hosts":
                in_hosts_for = None
            if current_group and popped_key == current_group:
                current_group = None

        key = _is_key(raw)
        if key is not None:
            parent = stack[-1][1] if stack else None
            # visible header?
            if key not in SKIP_GROUPS and (parent == "children" or parent is None and key != "all"):
                headers.add(key)
                current_group = key
            stack.append((ind, key))
            if key == "hosts" and current_group:
                in_hosts_for = current_group
                hostmap.setdefault(in_hosts_for, [])
            continue

        if in_hosts_for:
            hkey = _is_key(raw)
            if hkey:
                hostmap.setdefault(in_hosts_for, []).append(hkey)

    for g in list(hostmap.keys()):
        hostmap[g] = sorted(set(hostmap[g]))

    return hostmap, sorted(headers)

# ------------------- Public API -------------------

def hosts_by_group(files: List[Path]) -> Dict[str, List[str]]:
    acc: Dict[str, List[str]] = {}
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if yaml is not None:
            try:
                data = yaml.safe_load(content) or {}
                m, _ = _collect_from_yaml(data)
            except Exception:
                m, _ = _collect_from_text(content)
        else:
            m, _ = _collect_from_text(content)
        for g, lst in m.items():
            acc.setdefault(g, []).extend(lst)
    for g in list(acc.keys()):
        acc[g] = sorted(set(acc[g]))
    return acc

def list_groups(files: List[Path]) -> List[str]:
    """Return ALL target types we can see, even if they have zero hosts."""
    groups_seen: Set[str] = set()
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if yaml is not None:
            try:
                data = yaml.safe_load(content) or {}
                _, headers = _collect_from_yaml(data)
            except Exception:
                _, headers = _collect_from_text(content)
        else:
            _, headers = _collect_from_text(content)
        groups_seen.update(headers)
    return sorted(groups_seen)

def any_hosts_in_files(files: List[Path]) -> bool:
    hb = hosts_by_group(files)
    return any(hb.get(g) for g in hb)

