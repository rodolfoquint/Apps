"""Verification helpers for print-in-place mechanisms.

Built on manifold3d (exact booleans, exact min_gap) and trimesh (I/O, analysis).
Every check returns plain data so scripts can assert on it and write reports.

    from verify import load, min_gap, overlap_volume, overhang_report, small_parts_report
"""
from __future__ import annotations

import math
from pathlib import Path

import manifold3d as m3d
import numpy as np
import trimesh

# Small-parts test cylinder (16 CFR 1501 / EN 71-1): 31.7 mm dia, 25.4-57.1 mm deep.
SMALL_PARTS_DIA = 31.7
SMALL_PARTS_DEPTH = 57.1


# ---------------------------------------------------------------- conversion
def to_manifold(mesh: trimesh.Trimesh) -> m3d.Manifold:
    mm = m3d.Mesh(
        vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
        tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
    )
    man = m3d.Manifold(mm)
    if man.status() != m3d.Error.NoError:
        raise ValueError(f"mesh is not a valid manifold: {man.status()}")
    return man


def to_trimesh(man: m3d.Manifold) -> trimesh.Trimesh:
    mesh = man.to_mesh()
    verts = np.asarray(mesh.vert_properties)[:, :3]
    return trimesh.Trimesh(vertices=verts, faces=np.asarray(mesh.tri_verts), process=False)


def load(path: str | Path) -> m3d.Manifold:
    tm = trimesh.load(str(path), force="mesh")
    tm.merge_vertices()
    return to_manifold(tm)


def save_stl(man: m3d.Manifold, path: str | Path) -> None:
    to_trimesh(man).export(str(path))


# ---------------------------------------------------------------- clearances
def min_gap(a: m3d.Manifold, b: m3d.Manifold, search: float = 3.0) -> float:
    """Exact minimum distance between two solids (capped at `search`).

    Returns 0.0 if they touch or overlap - use overlap_volume to tell which.
    """
    return float(a.min_gap(b, search))


def overlap_volume(a: m3d.Manifold, b: m3d.Manifold) -> float:
    return float((a ^ b).volume())


def pairwise_report(parts: dict[str, m3d.Manifold], search: float = 3.0,
                    pairs: list[tuple[str, str]] | None = None) -> list[dict]:
    names = list(parts)
    if pairs is None:
        pairs = [(names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))]
    out = []
    for a, b in pairs:
        ov = overlap_volume(parts[a], parts[b])
        gap = 0.0 if ov > 1e-6 else min_gap(parts[a], parts[b], search)
        out.append({"a": a, "b": b, "gap": gap, "overlap_mm3": ov})
    return out


def sweep(pose_fn, ts, pairs: list[tuple[str, str]], search: float = 3.0) -> dict:
    """Kinematic collision sweep.

    pose_fn(t) -> dict[name, Manifold] with every part placed at motion
    parameter t. For each pair, records min gap and overlap over all t.
    """
    worst = {f"{a}|{b}": {"min_gap": math.inf, "at": None, "max_overlap_mm3": 0.0, "overlap_at": None}
             for a, b in pairs}
    trace = []
    for t in ts:
        parts = pose_fn(t)
        row = {"t": float(t)}
        for r in pairwise_report(parts, search, pairs):
            k = f"{r['a']}|{r['b']}"
            row[k] = r["gap"] if r["overlap_mm3"] <= 1e-6 else -r["overlap_mm3"]
            w = worst[k]
            if r["overlap_mm3"] > w["max_overlap_mm3"]:
                w["max_overlap_mm3"], w["overlap_at"] = r["overlap_mm3"], float(t)
            if r["gap"] < w["min_gap"]:
                w["min_gap"], w["at"] = r["gap"], float(t)
        trace.append(row)
    return {"worst": worst, "trace": trace}


# ---------------------------------------------------------------- printability
def overhang_report(man: m3d.Manifold, max_angle_deg: float = 45.0, bed_tol: float = 0.25,
                    min_report_area: float = 1.0) -> dict:
    """Area of downward-facing surface steeper than `max_angle_deg` from vertical.

    Faces touching the bed (z within bed_tol of the part minimum) are excluded.
    Returns total area and clusters (connected regions) with centroid and area.
    """
    tm = to_trimesh(man)
    zmin = tm.bounds[0, 2]
    n = tm.face_normals
    # angle between face normal and straight down; overhang if normal points down
    # more steeply than (90 - max_angle) from horizontal.
    limit = -math.cos(math.radians(max_angle_deg))  # nz below this = overhang beyond max_angle
    face_z = tm.triangles_center[:, 2]
    mask = (n[:, 2] < limit) & (face_z > zmin + bed_tol)
    areas = tm.area_faces
    total = float(areas[mask].sum())
    clusters = []
    if mask.any():
        idx = np.nonzero(mask)[0]
        sub_adj = trimesh.graph.connected_components(
            tm.face_adjacency[np.all(np.isin(tm.face_adjacency, idx), axis=1)], nodes=idx)
        for comp in sub_adj:
            a = float(areas[comp].sum())
            if a >= min_report_area:
                c = (tm.triangles_center[comp] * areas[comp, None]).sum(0) / a
                clusters.append({"area_mm2": round(a, 2), "centroid": [round(float(v), 2) for v in c],
                                 "min_nz": round(float(n[comp, 2].min()), 3)})
        clusters.sort(key=lambda d: -d["area_mm2"])
    return {"overhang_area_mm2": round(total, 2), "clusters": clusters}


def bodies(man: m3d.Manifold) -> list[m3d.Manifold]:
    return list(man.decompose())


def small_parts_report(man: m3d.Manifold) -> list[dict]:
    """Flag every separate body that could fit the small-parts cylinder.

    Conservative: uses the oriented bounding box; a body is flagged when its
    two smaller OBB extents fit the 31.7 mm diameter (diagonal check) and its
    largest extent is under the 57.1 mm depth.
    """
    out = []
    for i, b in enumerate(bodies(man)):
        tm = to_trimesh(b)
        ext = np.sort(tm.bounding_box_oriented.primitive.extents)
        fits = math.hypot(ext[0], ext[1]) <= SMALL_PARTS_DIA and ext[2] <= SMALL_PARTS_DEPTH
        out.append({"body": i, "volume_mm3": round(float(b.volume()), 1),
                    "obb_extents": [round(float(e), 2) for e in ext], "small_part_risk": bool(fits)})
    return out


def thin_wall_probe(man: m3d.Manifold, min_wall: float = 0.8, samples: int = 20000, seed: int = 0) -> dict:
    """Estimate local wall thickness by casting rays inward from surface samples.

    Reports the fraction of sampled surface whose inward ray exits the solid
    within `min_wall` mm (i.e. walls thinner than one ~2-perimeter wall).
    """
    tm = to_trimesh(man)
    pts, fidx = trimesh.sample.sample_surface(tm, samples, seed=seed)
    dirs = -tm.face_normals[fidx]
    origins = pts + dirs * 1e-3
    loc, ray_idx, _ = tm.ray.intersects_location(origins, dirs, multiple_hits=False)
    thick = np.full(samples, np.inf)
    d = np.linalg.norm(loc - origins[ray_idx], axis=1)
    thick[ray_idx] = d
    thin = thick < min_wall
    worst = []
    if thin.any():
        order = np.argsort(thick)[: min(10, int(thin.sum()))]
        worst = [{"at": [round(float(v), 2) for v in pts[i]], "thickness": round(float(thick[i]), 3)} for i in order]
    return {"thin_fraction": round(float(thin.mean()), 4), "min_wall": min_wall, "worst": worst}


def summary(man: m3d.Manifold) -> dict:
    tm = to_trimesh(man)
    lo, hi = tm.bounds
    return {"volume_mm3": round(float(man.volume()), 1), "bodies": len(bodies(man)),
            "bbox_mm": [round(float(v), 2) for v in (hi - lo)], "watertight": bool(tm.is_watertight),
            "genus": int(man.genus())}
