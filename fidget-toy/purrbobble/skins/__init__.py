"""Skin registry.  ``get_skin(name)`` returns a Skin instance (see skins/base.py for the interface)."""
from __future__ import annotations

import importlib
import importlib.util

from .base import Feature, PawStyle, Skin

# name -> "module:Class" (modules are imported lazily so a broken skin cannot break the others)
REGISTRY = {
    "kitty": "purrbobble.skins.kitty:KittySkin",
    "bee": "purrbobble.skins.bee:BeeSkin",
    "robot": "purrbobble.skins.robot:RobotSkin",
}


def available() -> list[str]:
    out = []
    for name, target in REGISTRY.items():
        mod = target.split(":")[0]
        try:
            if importlib.util.find_spec(mod) is not None:
                out.append(name)
        except ModuleNotFoundError:
            pass
    return out


def get_skin(name: str = "kitty") -> Skin:
    if isinstance(name, Skin):
        return name
    if name not in REGISTRY:
        raise KeyError(f"unknown skin {name!r}; registered: {sorted(REGISTRY)}")
    mod, cls = REGISTRY[name].split(":")
    return getattr(importlib.import_module(mod), cls)()


__all__ = ["Feature", "PawStyle", "Skin", "get_skin", "available", "REGISTRY"]
