"""Export light-weight GLB meshes of each skin for the web viewer.

    python3 tools/export_web.py [--skins kitty,bee,robot] [--out web/models] [--faces 60000]

Writes <out>/<skin>_<body>.glb for body in frame/wheel/head, in the DESIGN frame (phi = 0, psi = 0),
plus <out>/models.json with the pivots the viewer animates about: the wheel turns about O = (0, 0)
and the head swings about P = (0, D), both about the +Z axis (Z = print direction, face toward +Z).
Meshes are decimated with fast-simplification; they are for viewing only, never for printing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from purrbobble import build  # noqa: E402
from verify import to_trimesh  # noqa: E402

BODIES = ("frame", "wheel", "head")


def decimate(tm: trimesh.Trimesh, max_faces: int) -> trimesh.Trimesh:
    if len(tm.faces) <= max_faces:
        return tm
    out = tm.simplify_quadric_decimation(face_count=max_faces)
    out.merge_vertices()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skins", default="kitty,bee,robot")
    ap.add_argument("--out", default=str(ROOT / "web" / "models"))
    ap.add_argument("--faces", type=int, default=60000, help="max faces for the frame (wheel/head get half)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    meta = {}
    for skin in a.skins.split(","):
        M = build(skin, "nominal")
        p = M.params
        entry = {"O": [0.0, 0.0], "P": [float(M.P[0]), float(M.P[1])], "psi_b": float(p.psi_b),
                 "teeth": int(p.N), "print_pose": [float(p.phi_print), float(p.psi_print)], "files": {}}
        for name in BODIES:
            tm = to_trimesh(getattr(M, name))
            tm.merge_vertices()
            budget = a.faces if name == "frame" else a.faces // 2
            dm = decimate(tm, budget)
            # split vertices along sharp edges so smooth normals keep creases crisp in the viewer
            sm = trimesh.graph.smooth_shade(dm, angle=np.radians(30))
            path = out / f"{skin}_{name}.glb"
            path.write_bytes(trimesh.exchange.gltf.export_glb(trimesh.Scene(sm), include_normals=True))
            entry["files"][name] = path.name
            print(f"{skin:6s} {name:5s} {len(tm.faces):7d} -> {len(dm.faces):6d} faces  {path.stat().st_size/1e6:.2f} MB")
        lo, hi = np.min([getattr(M, b).bounding_box()[:3] for b in BODIES], 0), \
            np.max([getattr(M, b).bounding_box()[3:] for b in BODIES], 0)
        entry["bbox"] = [lo.round(2).tolist(), hi.round(2).tolist()]
        meta[skin] = entry
    (out / "models.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
