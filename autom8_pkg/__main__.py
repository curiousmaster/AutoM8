# =====================================================================
# File: autom8_pkg/__main__.py
# Entrypoint for AutoM8 package (python -m autom8_pkg)
# =====================================================================
from .core.app import main

if __name__ == "__main__":
    raise SystemExit(main())

