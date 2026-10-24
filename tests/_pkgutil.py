"""Load foodwithlove modules as a package without importing Home Assistant."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = "custom_components.foodwithlove"
PKG_DIR = ROOT / "custom_components" / "foodwithlove"


def ensure_package() -> None:
    if "custom_components" not in sys.modules:
        parent = types.ModuleType("custom_components")
        parent.__path__ = [str(ROOT / "custom_components")]
        sys.modules["custom_components"] = parent
    if PKG not in sys.modules:
        pkg = types.ModuleType(PKG)
        pkg.__path__ = [str(PKG_DIR)]
        sys.modules[PKG] = pkg


def load(name: str, filename: str):
    """Load ``custom_components.foodwithlove.<name>`` from ``filename``."""
    ensure_package()
    full = f"{PKG}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    path = PKG_DIR / filename
    spec = importlib.util.spec_from_file_location(full, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[full] = mod
    spec.loader.exec_module(mod)
    return mod
