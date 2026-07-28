#!/usr/bin/env python3
"""Backwards-compatibility launcher for Stocky.

The implementation moved to the ``stocky_mcp`` package under ``src/`` in
version 2.0. Existing MCP client configurations point at this file directly:

    {"command": "python", "args": ["/path/to/stocky_mcp.py"]}

so it is kept as a thin launcher rather than being deleted.

Prefer the console script for new configurations:

    {"command": "stocky-mcp"}

or, without installing anything:

    {"command": "uvx", "args": ["stocky-mcp"]}

Implementation note: this file sits in the same directory that Python puts on
``sys.path`` when it runs a script, so it shadows the real package by name.
``_load_package`` deals with that explicitly rather than relying on import
order, which is why it looks more defensive than a one-line re-export would.
"""

import sys
from pathlib import Path
from types import ModuleType

_SRC = Path(__file__).resolve().parent / "src"


def _load_server() -> ModuleType:
    """Import the real ``stocky_mcp.server``, working around this shim."""
    # Put a source checkout ahead of this file on the path, so `import
    # stocky_mcp` finds the package directory rather than this module.
    if _SRC.is_dir():
        src = str(_SRC)
        if src in sys.path:
            sys.path.remove(src)
        sys.path.insert(0, src)

    # If this shim has already been imported under the package's name, drop it
    # so the import below resolves to the package instead of back to here.
    shadow = sys.modules.get("stocky_mcp")
    if shadow is not None and not hasattr(shadow, "__path__"):
        del sys.modules["stocky_mcp"]

    import importlib

    return importlib.import_module("stocky_mcp.server")


def main() -> None:
    """Start the Stocky MCP server."""
    _load_server().main()


if __name__ == "__main__":
    main()
