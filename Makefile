#======================================================================
# File: Makefile
# Project: AutoM8 · Ansible TUI Wrapper
# System layout:
#   Code:    /usr/local/lib/autom8/autom8_pkg
#   Wrapper: /usr/local/sbin/autom8
#======================================================================

PYTHON        := python3
PREFIX        ?= /usr/local
BIN_DIR       := $(PREFIX)/sbin
PKG_ROOT      := $(PREFIX)/lib/autom8
WRAPPER_NAME  := autom8

VENV_DIR      := $(HOME)/.venv
VENV_PYTHON   := $(VENV_DIR)/bin/python
VENV_PIP      := $(VENV_DIR)/bin/pip
VENV_GALAXY   := $(VENV_DIR)/bin/ansible-galaxy

LOGFILE       := /var/log/autom8-install.log

GALAXY_COLLECTIONS := \
  cisco.ios \
  cisco.nxos \
  cisco.asa \
  cisco.aci \
  cisco.meraki \
  cisco.iosxr \
  cisco.dnac \
  cisco.intersight \
  arista.eos \
  junipernetworks.junos \
  fortinet.fortios \
  paloaltonetworks.panos \
  f5networks.f5_modules \
  checkpoint.checkpoint \
  vyos.vyos \
  dellemc.os10 \
  lenovo.lenovoos10 \
  hpe.procurve \
  hpe.ilo \
  ansible.posix \
  ansible.utils \
  community.general \
  community.docker \
  community.kubernetes \
  community.vmware \
  community.windows \
  community.mysql \
  community.postgresql \
  community.network \
  amazon.aws \
  google.cloud \
  azure.azcollection \
  oracle.oci \
  openstack.cloud \
  hetzner.hcloud \
  linode.cloud \
  digitalocean.cloud \
  vmware.vmware_rest \
  kubernetes.core \
  community.crypto \
  community.hashi_vault \
  community.general.hardened \
  ansible.lockdown \
  splunk.es \
  graylog.graylog \
  theforeman.foreman \
  servicenow.servicenow \
  community.grafana \
  community.zabbix \
  community.prometheus \
  community.influxdb \
  community.elastic \
  community.git \
  community.jenkins \
  community.terraform \
  community.nagios \
  community.slack \
  ansible.netcommon \
  ansible.net_tools \
  community.time

# ---------------- Default target ----------------
all: install-system

# ---------------- Log helper ----------------
define log_action
	@echo "[$$(date '+%Y-%m-%d %H:%M:%S')] $1 (by $$(whoami))" | sudo tee -a $(LOGFILE) > /dev/null
endef

# ---------------- System deps (Debian/Ubuntu) ----------------
system-packages:
	@echo ">>> Installing system dependencies (python3, pip, venv, rsync, git)..."
	@sudo apt-get update -qq
	@sudo apt-get install -y python3 python3-pip python3-venv rsync git make
	$(call log_action,"Installed system dependencies")

# ---------------- Virtual environment ----------------
env:
	@echo ">>> Creating user-local venv in $(VENV_DIR)..."
	@mkdir -p $(VENV_DIR)
	@if [ ! -x "$(VENV_PYTHON)" ]; then \
		$(PYTHON) -m venv $(VENV_DIR); \
		echo ">>> Virtual environment created."; \
	else \
		echo ">>> Virtual environment already exists."; \
	fi
	$(call log_action,"Created/verified venv at $(VENV_DIR)")

# ---------------- Python/Ansible deps ----------------
deps: env
	@echo ">>> Installing Python + Ansible dependencies into $(VENV_DIR)..."
	@$(VENV_PIP) install --upgrade pip
	@$(VENV_PIP) install pyyaml ansible ansible-lint paramiko ansible-pylibssh
	$(call log_action,"Installed Python + Ansible deps in venv")

# ---------------- Ansible Galaxy collections ----------------
collections: deps
	@echo ">>> Installing Ansible Galaxy collections..."
	@for coll in $(GALAXY_COLLECTIONS); do \
		echo ">>> Installing $$coll..."; \
		$(VENV_GALAXY) collection install $$coll --force || true; \
	done
	$(call log_action,"Installed Ansible Galaxy collections")

# ---------------- System install (/usr/local/lib/autom8 + wrapper) ----------------
install-system: deps
	@echo ">>> Installing AutoM8 package to $(PKG_ROOT)/autom8_pkg ..."
	@sudo mkdir -p $(PKG_ROOT)
	@sudo rsync -a --delete autom8_pkg/ $(PKG_ROOT)/autom8_pkg/
	@sudo mkdir -p $(BIN_DIR)
	@echo ">>> Installing wrapper to $(BIN_DIR)/$(WRAPPER_NAME)..."
	@printf '%s\n' \
'#!/usr/bin/env bash' \
'VENV_PY="$(VENV_PYTHON)"' \
'PKG_ROOT="$(PKG_ROOT)"' \
'export PYTHONPATH="${PKG_ROOT}:${PYTHONPATH}"' \
'exec "$$VENV_PY" -m autom8_pkg "$$@"' \
	| sudo tee $(BIN_DIR)/$(WRAPPER_NAME) >/dev/null
	@sudo chmod 755 $(BIN_DIR)/$(WRAPPER_NAME)
	@sudo chown root:root $(BIN_DIR)/$(WRAPPER_NAME)
	$(call log_action,"Installed AutoM8 under $(PKG_ROOT) with wrapper $(BIN_DIR)/$(WRAPPER_NAME)")
	@echo ">>> Done. Run: $(WRAPPER_NAME)"

# ---------------- Update system copy (code sync only) ----------------
update-system:
	@echo ">>> Updating AutoM8 package at $(PKG_ROOT)..."
	@sudo rsync -a --delete autom8_pkg/ $(PKG_ROOT)/autom8_pkg/
	$(call log_action,"Updated AutoM8 under $(PKG_ROOT)")

# ---------------- Uninstall system copy ----------------
uninstall-system:
	@echo ">>> Removing AutoM8 system install..."
	@sudo rm -f $(BIN_DIR)/$(WRAPPER_NAME)
	@sudo rm -rf $(PKG_ROOT)
	$(call log_action,"Removed AutoM8 from $(BIN_DIR) and $(PKG_ROOT)")
	@echo ">>> Done."

# ---------------- Dev helpers (run from repo) ----------------
run:
	@$(VENV_PYTHON) -m autom8_pkg

dev:
	@$(VENV_PYTHON) -m autom8_pkg -d

# ---------------- Clean ----------------
clean:
	@echo ">>> Cleaning cache..."
	rm -rf __pycache__ **/__pycache__ *.pyc *.pyo
	find . -type f -name '*.log' -delete
	@echo ">>> Done."
	$(call log_action,"Cleaned caches")

clean-all: clean
	@echo ">>> Removing venv at $(VENV_DIR)..."
	rm -rf $(VENV_DIR)
	$(call log_action,"Removed venv")

# ---------------- Help ----------------
help:
	@echo ""
	@echo "AutoM8 · Makefile Commands"
	@echo "=========================="
	@echo "make system-packages - Install OS deps (python, pip, venv, rsync, git)"
	@echo "make env             - Create Python venv under ~/.venv"
	@echo "make deps            - Install Python/Ansible deps into venv"
	@echo "make collections     - Install Ansible Galaxy collections"
	@echo "make install-system  - Install package to /usr/local/lib/autom8 + wrapper"
	@echo "make update-system   - Update code at /usr/local/lib/autom8"
	@echo "make uninstall-system- Remove wrapper and package dir"
	@echo "make run             - Run from repo via venv"
	@echo "make dev             - Run from repo with debug"
	@echo "make clean           - Remove caches"
	@echo "make clean-all       - Remove caches and venv"
	@echo ""
	@echo "Prefix:     $(PREFIX)"
	@echo "BIN_DIR:    $(BIN_DIR)"
	@echo "PKG_ROOT:   $(PKG_ROOT)"
	@echo "VENV_DIR:   $(VENV_DIR)"
	@echo "Log file:   $(LOGFILE)"
	@echo ""

