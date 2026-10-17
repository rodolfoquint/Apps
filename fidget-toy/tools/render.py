"""Headless colored renders of multi-part models via OpenSCAD preview mode.

    from render import render_views
    render_views({"body": (manifold_or_stl_path, "#ffb3c7"), ...}, "out/prefix", views=("iso", "front"))

Writes <prefix>_<view>.png for each view. Needs xvfb-run + openscad on PATH.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import manifold3d as m3d

from verify import save_stl

# OpenSCAD --camera=rotx,roty,rotz,transx,transy,transz,dist (gimbal form)
VIEWS = {
    "iso": (60, 0, 35),
    "iso_back": (60, 0, 215),
    "front": (90, 0, 0),
    "back": (90, 0, 180),
    "side": (90, 0, 90),
    "top": (0, 0, 0),
    "bottom": (180, 0, 0),
}


def _hex(c: str) -> str:
    c = c.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return f"[{r:.3f},{g:.3f},{b:.3f}]"


def render_views(parts: dict[str, tuple], prefix: str | Path, views=("iso", "front", "top"),
                 size=(900, 700), dist: float | None = None) -> list[Path]:
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    out = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        lines = []
        for name, (geom, color) in parts.items():
            if isinstance(geom, m3d.Manifold):
                p = td / f"{name}.stl"
                save_stl(geom, p)
            else:
                p = Path(geom).resolve()
            lines.append(f'color({_hex(color)}) import("{p}", convexity=10);')
        scad = td / "scene.scad"
        scad.write_text("\n".join(lines) + "\n")
        for v in views:
            rx, ry, rz = VIEWS[v] if isinstance(v, str) else v
            name = v if isinstance(v, str) else f"r{rx}_{ry}_{rz}"
            png = prefix.parent / f"{prefix.name}_{name}.png"
            cam = f"0,0,0,{rx},{ry},{rz},{dist if dist else 0}"
            cmd = ["xvfb-run", "-a", "openscad", "-o", str(png), f"--imgsize={size[0]},{size[1]}",
                   "--colorscheme=Tomorrow", f"--camera={cam}", "--viewall", "--autocenter",
                   "--projection=p", str(scad)]
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            out.append(png)
    return out
