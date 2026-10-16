"""Export light-weight meshes of each skin for the web viewer.

    python3 tools/export_web.py [--skins kitty,bee,robot] [--out web/models] [--faces 50000]

Writes <out>/<skin>_<body>.json for body in frame/wheel/head, in the DESIGN frame (phi = 0, psi = 0): positions
quantised to int16 over the body's bounding box and triangle indices, both base64 (artifact pages serve JSON but
not GLB); normals are computed in the browser, and vertices are split along sharp edges so creases stay crisp.
plus <out>/models.json with the pivots the viewer animates about: the wheel turns about O = (0, 0)
and the head swings about P = (0, D), both about the +Z axis (Z = print direction, face toward +Z).
Skins not exported in this run keep their models.json entry; an exported skin's region files that its colour
regions no longer produce (e.g. the classic kitty's plate and face details) are removed.
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
    import fast_simplification
    v, f = fast_simplification.simplify(np.asarray(tm.vertices, np.float32), np.asarray(tm.faces, np.int32),
                                        target_reduction=1.0 - max_faces / len(tm.faces))
    out = trimesh.Trimesh(v, f, process=True)
    out.merge_vertices()
    return out


def pack(tm: trimesh.Trimesh) -> dict:
    import base64
    v = np.asarray(tm.vertices, np.float64)
    lo, hi = v.min(0), v.max(0)
    scale = np.maximum(hi - lo, 1e-6) / 65534.0
    q = np.round((v - lo) / scale - 32767).astype(np.int16)
    f = np.asarray(tm.faces)
    idx = f.astype(np.uint16 if len(v) < 65536 else np.uint32)
    return {"offset": (lo + 32767 * scale).round(6).tolist(), "scale": scale.tolist(), "n_vert": int(len(v)),
            "index_type": "u16" if idx.dtype == np.uint16 else "u32",
            "positions": base64.b64encode(q.tobytes()).decode(), "indices": base64.b64encode(idx.tobytes()).decode()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skins", default="kitty,bee,robot")
    ap.add_argument("--out", default=str(ROOT / "web" / "models"))
    ap.add_argument("--faces", type=int, default=50000, help="max faces for the frame (wheel/head get half)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        meta = json.loads((out / "models.json").read_text())       # entries of the skins not exported now stay
    except (OSError, ValueError):
        meta = {}
    for skin in a.skins.split(","):
        M = build(skin, "nominal")
        p = M.params
        entry = {"O": [0.0, 0.0], "P": [float(M.P[0]), float(M.P[1])], "psi_b": float(p.psi_b),
                 "teeth": int(p.N), "print_pose": [float(p.phi_print), float(p.psi_print)], "files": {}}
        from purrbobble.assemble import colour_parts, palette_of
        pal = palette_of(M.skin)
        # one mesh per colour region (design frame: phi = psi = 0); "body" says which pivot it moves with
        for name, (m, ckey) in colour_parts(M, phi=0.0, psi=0.0).items():
            if M.info.get("sculpt"):
                # the sculpt bodies' slivers (integration booleans) stall the quadric decimation far above the
                # budget, with mm-size spikes (head: 510k -> 322k faces, max error 2.6 mm): merge within 0.01 mm
                # first (manifold's own simplify; the budget is then met within ~0.1 mm)
                m = m.simplify(0.01)
            tm = to_trimesh(m)
            tm.merge_vertices()
            body = name.split("_")[0]
            budget = a.faces if name in ("frame_body", "frame_plate") else a.faces // 2
            dm = decimate(tm, budget)
            # split vertices along sharp edges so smooth normals keep creases crisp in the viewer
            sm = trimesh.graph.smooth_shade(dm, angle=np.radians(30))
            path = out / f"{skin}_{name}.json"
            path.write_text(json.dumps(pack(sm)))
            entry["files"][name] = {"file": path.name, "body": body, "color": pal[ckey]}
            print(f"{skin:6s} {name:13s} {len(tm.faces):7d} -> {len(dm.faces):6d} faces  {path.stat().st_size/1e6:.2f} MB")
        lo, hi = np.min([getattr(M, b).bounding_box()[:3] for b in BODIES], 0), \
            np.max([getattr(M, b).bounding_box()[3:] for b in BODIES], 0)
        entry["bbox"] = [lo.round(2).tolist(), hi.round(2).tolist()]
        meta[skin] = entry
        # region files of this skin from an earlier export that are not in the entry now (<skin>_<region>.json;
        # the region test keeps e.g. kitty_classic_*.json when exporting kitty)
        keep = {e["file"] for e in entry["files"].values()}
        for f in out.glob(f"{skin}_*.json"):
            region = f.stem[len(skin) + 1:]
            if f.name not in keep and (region == "wheel" or region.startswith(("frame_", "head_"))):
                f.unlink()
                print(f"{skin:6s} removed stale {f.name}")
    (out / "models.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
