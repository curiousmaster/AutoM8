# Autom8 . Ansible TUI Wrapper

```
   _____          __            _____     ______
  /  _  \  __ ___/  |_  ____   /     \   /  __  \
 /  /_\  \|  |  \   __\/  _ \ /  \ /  \  >      <
/    |    \  |  /|  | (  <_> )    Y    \/   --   \
\____|__  /____/ |__|  \____/\____|__  /\______  /
        \/                           \/        \/

 A u t o M 8   .   A n s i b l e  M a d e  E a s y
```

Autom8 is a text-based user interface (TUI) wrapper for **Ansible**, designed to simplify execution of playbooks and management of inventories through an interactive curses interface.

It automatically parses your `inventory/hosts.yml` and `playbooks/*.yml` files, lets you select **Sites**, **Target Types**, and **Playbooks**, and runs Ansible directly . with live output and secure vault handling.

---

## Features

* Full curses-based text interface
* Smart inventory parsing (`inventory/hosts.yml`)
* Automatic playbook discovery (`playbooks/*.yml`)
* Site and Target filtering
* Secure vault password modal
* Scrollable live output with scrollbar
* Integrated Ansible + Cisco Galaxy setup
* Lightweight, single-file Python application

---

## Requirements

* Ubuntu or Debian (tested)
* Python 3.8 or later
* Ansible 2.16 or later
* `pip`, `git`, and `make`

Cisco Ansible Galaxy collections are installed automatically:

```
cisco.ios
cisco.nxos
cisco.asa
cisco.aci
```

---

## Installation

Clone the repository and run the setup:

```bash
git clone https://github.com/defensify/autom8.git
cd autom8
make setup
```

This will:

1. Install required system packages (`python3`, `pip`, `venv`, `git`)
2. Create a virtual environment at `~/.venv`
3. Install Ansible, ansible-lint, and PyYAML inside the venv
4. Install Cisco Galaxy collections
5. Install the Autom8 script to `/usr/local/sbin/autom8`

---

## Usage

Once installed, start Autom8:

```bash
autom8
```

### Navigation

| Key     | Action                     |
| ------- | -------------------------- |
| TAB     | Move focus between panes   |
| . / .   | Move selection             |
| ENTER   | Open host selection modal  |
| r / F5  | Run selected playbook      |
| v       | Toggle vault password mode |
| x       | Clear output pane          |
| q / ESC | Quit                       |

---

## Directory Structure

```
autom8/
... autom8.py
... Makefile
... README.md
... INSTALL.md
... inventory/
.   ... hosts.yml
... playbooks/
    ... deploy_firewall.yml
    ... backup_switch.yml
    ... verify_config.yml
```

---

## Logging

All setup and installation actions are logged to:

```
/var/log/autom8-install.log
```

Example entries:

```
[2025-10-08 22:32:10] Installed Python + Ansible deps in venv (by root)
[2025-10-08 22:32:45] Installed Cisco Ansible Galaxy collections: cisco.ios cisco.nxos cisco.asa cisco.aci (by root)
```

---

## Contributing

Contributions and improvements are welcome.
Please keep code formatting consistent and follow the 80-character width rule for readability.

---
