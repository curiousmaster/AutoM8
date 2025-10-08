#======================================================================
# File: Makefile
# Project: Autom8 . Ansible TUI Wrapper
#======================================================================
# Description:
#   This Makefile automates full setup and installation of Autom8,
#   using a user-local Python virtual environment (~/.venv).
#   It installs Ansible, ansible-lint, and recommended Ansible Galaxy
#   collections for multi-vendor networking, infrastructure, cloud,
#   and security automation.
#======================================================================

PYTHON       := python3
INSTALL_DIR  := /usr/local/sbin
SCRIPT_NAME  := autom8
SOURCE_FILE  := autom8.py
VENV_DIR     := $(HOME)/.venv
VENV_PYTHON  := $(VENV_DIR)/bin/python
VENV_PIP     := $(VENV_DIR)/bin/pip
VENV_ANSIBLE := $(VENV_DIR)/bin/ansible
VENV_GALAXY  := $(VENV_DIR)/bin/ansible-galaxy
LOGFILE      := /var/log/autom8-install.log

#======================================================================
# Ansible Galaxy Collections (core + extended)
#======================================================================
# These collections cover Cisco, multi-vendor networking, infrastructure,
# cloud, security, and monitoring integrations.
# They will be installed automatically with: make collections
#======================================================================

GALAXY_COLLECTIONS := \
	# --- Cisco ecosystem --- \
	cisco.ios \
	cisco.nxos \
	cisco.asa \
	cisco.aci \
	cisco.meraki \
	cisco.iosxr \
	cisco.dnac \
	cisco.intersight \
	\
	# --- Multi-vendor networking --- \
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
	\
	# --- Infrastructure and system management --- \
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
	\
	# --- Cloud and virtualization --- \
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
	\
	# --- Security and compliance --- \
	community.crypto \
	community.hashi_vault \
	community.general.hardened \
	ansible.lockdown \
	splunk.es \
	graylog.graylog \
	theforeman.foreman \
	servicenow.servicenow \
	\
	# --- Monitoring, logging, and DevOps --- \
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
	\
	# --- Utilities and shared helpers --- \
	ansible.netcommon \
	ansible.net_tools \
	community.time

#----------------------------------------------------------------------
# Default target
#----------------------------------------------------------------------
all: install

#----------------------------------------------------------------------
# Log helper
#----------------------------------------------------------------------
define log_action
	@echo "[$$(date '+%Y-%m-%d %H:%M:%S')] $1 (by $$(whoami))" | sudo tee -a $(LOGFILE) > /dev/null
endef

#----------------------------------------------------------------------
# Install required system packages (Debian/Ubuntu)
#----------------------------------------------------------------------
system-packages:
	@echo ">>> Installing system dependencies (python3, pip, git, venv)..."
	@sudo apt-get update -qq
	@sudo apt-get install -y python3 python3-pip python3-venv git make
	$(call log_action,"Installed system dependencies")

#----------------------------------------------------------------------
# Create virtual environment in ~/.venv
#----------------------------------------------------------------------
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

#----------------------------------------------------------------------
# Install Python + Ansible dependencies inside venv
#----------------------------------------------------------------------
deps: env
	@echo ">>> Installing Python + Ansible dependencies into $(VENV_DIR)..."
	@$(VENV_PIP) install --upgrade pip
	@$(VENV_PIP) install pyyaml ansible ansible-lint
	$(call log_action,"Installed Python + Ansible deps in venv")

#----------------------------------------------------------------------
# Install Ansible Galaxy collections
#----------------------------------------------------------------------
collections: deps
	@echo ">>> Installing Ansible Galaxy collections..."
	@for coll in $(GALAXY_COLLECTIONS); do \
		echo ">>> Installing $$coll..."; \
		$(VENV_GALAXY) collection install $$coll --force || true; \
	done
	$(call log_action,"Installed Ansible Galaxy collections: $(GALAXY_COLLECTIONS)")

#----------------------------------------------------------------------
# Full setup (system packages + venv + dependencies + collections + install)
#----------------------------------------------------------------------
setup: system-packages deps collections install
	@echo ">>> Full Autom8 setup complete."
	$(call log_action,"Completed full Autom8 setup (with Ansible collections)")

#----------------------------------------------------------------------
# Install Autom8 system-wide
#----------------------------------------------------------------------
install: $(SOURCE_FILE)
	@echo ">>> Installing Autom8 to $(INSTALL_DIR)/$(SCRIPT_NAME)..."
	@sudo install -m 755 $(SOURCE_FILE) $(INSTALL_DIR)/$(SCRIPT_NAME)
	@sudo sed -i '1c\#\!$(VENV_PYTHON)' $(INSTALL_DIR)/$(SCRIPT_NAME)
	$(call log_action,"Installed Autom8 binary to $(INSTALL_DIR)")
	@echo ">>> Installation complete."
	@echo ">>> Run it with: $(SCRIPT_NAME)"

#----------------------------------------------------------------------
# Uninstall Autom8
#----------------------------------------------------------------------
uninstall:
	@echo ">>> Removing Autom8..."
	@sudo rm -f $(INSTALL_DIR)/$(SCRIPT_NAME)
	$(call log_action,"Uninstalled Autom8 from $(INSTALL_DIR)")
	@echo ">>> Done."

#----------------------------------------------------------------------
# Clean environment
#----------------------------------------------------------------------
clean:
	@echo ">>> Cleaning cache and virtual environment..."
	rm -rf __pycache__ *.pyc *.pyo
	rm -rf $(VENV_DIR)
	find . -type f -name '*.log' -delete
	@echo ">>> Done."
	$(call log_action,"Cleaned environment and removed venv")

#----------------------------------------------------------------------
# Help target
#----------------------------------------------------------------------
help:
	@echo ""
	@echo "Autom8 . Makefile Commands"
	@echo "=========================="
	@echo "make setup        - Full setup (system, venv, deps, collections, install)"
	@echo "make env          - Create Python venv under ~/.venv"
	@echo "make deps         - Install Python/Ansible deps into venv"
	@echo "make collections  - Install Ansible Galaxy collections"
	@echo "make install      - Install Autom8 binary to /usr/local/sbin"
	@echo "make uninstall    - Remove Autom8 binary"
	@echo "make clean        - Remove cache and venv"
	@echo ""
	@echo "Virtual Environment: $(VENV_DIR)"
	@echo "Log file: $(LOGFILE)"
	@echo ""
#======================================================================

