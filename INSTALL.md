# Autom8 Installation Guide

This document describes how to install and configure **Autom8**, a curses-based Ansible control interface.

---

## Prerequisites

* Ubuntu 22.04 or later
* Python 3.8 or later
* Internet connection (for installing collections)
* Sudo privileges (for installing system-wide)

---

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/defensify/autom8.git
cd autom8
```

---

### 2. Full Automated Setup

Run:

```bash
make setup
```

This command will:

1. Install system packages (`python3`, `pip`, `venv`, `git`, `make`)
2. Create a local virtual environment:

   ```
   ~/.venv
   ```
3. Install dependencies:

   * `ansible`
   * `ansible-lint`
   * `pyyaml`
4. Install Cisco Galaxy collections:

   ```
   cisco.ios
   cisco.nxos
   cisco.asa
   cisco.aci
   ```
5. Install the Autom8 binary into:

   ```
   /usr/local/sbin/autom8
   ```

---

### 3. Verify Installation

Run:

```bash
autom8 --help
```

or manually verify Ansible and collections:

```bash
source ~/.venv/bin/activate
ansible --version
ansible-galaxy collection list | grep cisco
```

Expected output:

```
cisco.ios     8.x.x
cisco.nxos    9.x.x
cisco.asa     5.x.x
cisco.aci     2.x.x
```

---

### 4. Manual Steps (Optional)

If you only want to install dependencies without Autom8:

```bash
make deps
make collections
```

---

### 5. Uninstall

```bash
sudo make uninstall
```

This removes `/usr/local/sbin/autom8` but preserves the virtual environment.

To remove everything (including the venv):

```bash
make clean
```

---

## Environment Details

* Virtual environment: `~/.venv`
* Python binary: `~/.venv/bin/python`
* Installed tools:

  * Ansible
  * ansible-lint
  * PyYAML
  * Cisco Galaxy collections

---

## Logs

Installation logs are written to:

```
/var/log/autom8-install.log
```

Example entries:

```
[2025-10-08 21:58:45] Installed Python + Ansible deps in venv (by stefan)
[2025-10-08 21:59:02] Installed Autom8 binary to /usr/local/sbin (by root)
[2025-10-08 21:59:18] Installed Cisco Ansible Galaxy collections: cisco.ios cisco.nxos cisco.asa cisco.aci (by stefan)
```

---

## Troubleshooting

| Issue                      | Solution                                     |
| -------------------------- | -------------------------------------------- |
| `autom8` command not found | Ensure `/usr/local/sbin` is in your PATH     |
| `ansible` not found        | Run `source ~/.venv/bin/activate`            |
| Missing Cisco collections  | Run `make collections` again                 |
| Permission denied          | Use `sudo make setup` or `sudo make install` |

---

## Completion

You can now start Autom8 with:

```bash
autom8
```

and enjoy a full curses-based control interface for Ansible.
