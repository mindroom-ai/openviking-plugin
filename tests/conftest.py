"""Test configuration — bootstrap the plugin package for relative imports."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent


def _ensure_package() -> None:
    """Make sure 'openviking' is importable as a package during tests."""
    pkg_name = "openviking"
    if pkg_name in sys.modules:
        return

    # Create a package module pointing at the plugin directory
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(PLUGIN_DIR)]
    pkg.__package__ = pkg_name
    pkg.__file__ = str(PLUGIN_DIR / "__init__.py")
    sys.modules[pkg_name] = pkg

    # Import sub-modules so relative imports resolve
    for mod_name in ("config", "client", "hooks", "tools"):
        mod_path = PLUGIN_DIR / f"{mod_name}.py"
        if mod_path.exists():
            spec = importlib.util.spec_from_file_location(
                f"{pkg_name}.{mod_name}",
                mod_path,
                submodule_search_locations=[],
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                mod.__package__ = pkg_name
                sys.modules[f"{pkg_name}.{mod_name}"] = mod
                spec.loader.exec_module(mod)


_ensure_package()
