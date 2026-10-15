"""Check group C - printability and slicing (SPEC section 5: V8, V9, layer quantisation, a real slicer).

    python3 verification/v_printability.py --skin kitty [--variant nominal] [--rays 12000] [--no-slicer]
                                           [--no-render] [--keep-gcode] [--out DIR] [-q]

Writes verification/reports/<skin>/printability.json (printability_<variant>.json for other variants) plus the
overhang maps printability_overhang[_<variant>].png (2-D, one panel per body / Z level) and
printability_overhang3d[_<variant>].png (OpenSCAD), and exits non-zero if any check FAILS (warnings do not fail).
The JSON has per-check status / measured values / criteria, a "summary" and a short "findings" list with proposed
fixes.  Independent of the builder's own checks: it uses only the documented Model API (build, print_pose, params,
sections, skin features), exact manifold3d slices / offsets, trimesh ray casting, the exported STL / 3MF and the
PrusaSlicer CLI.  When the exported STL / 3MF of a skin / variant does not exist, temporary ones are written from
the model (the deliverables under stl/ are never touched).

V8  Topology and wall thickness
    * every body: one component, manifold status NoError, watertight, consistently wound; the exported STL (3 shells)
      and 3MF (1 object, 3 named parts, per-part infill) must match the model;
    * wall thickness by inward ray casting (>= 2000 area-weighted samples per body, default 12000).  Thin samples
      (< 1.2) are labelled with a zone (skid rib, tooth tip, cosmetic feature, funnel seat, stop pad, paw ...) and
      re-checked in the XY slice at their height (ThinMap): a 'wall' (strip >= 2 mm long thinner than 1.2) in a
      structural zone FAILS; a 'corner' (acute-corner tip / short stub) or 'edge_z_only' (the XY section is >= 1.2
      wide there: a stepped edge round seen by a vertical ray) warns; designed 0.8 ribs, frozen escapement tooth
      tips and cosmetic debosses warn;
    * second method: every 0.2 mm layer of every body, slice minus its opening(1.2), pieces classified wall /
      corner with the thinnest width of each wall (bisection on the opening width);
    * SPEC specifics: back plate >= 2.0 and roof >= 2.0 (vertical rays; edge rounds and the keep-out-trimmed roof
      edge warn), fingers >= 4.29 and legs >= 7.0 (chords perpendicular to their axes in the head band), posts D 8.0
      (inscribed diameter in frame slices), no slivers < 1.6 in Fill2D / Roof2D (sections) and in every frame layer of
      the fill / roof band, stop pads (0.6 thick by construction) fully backed by the fill wall, rib pieces 0.8 wide.
V9  Overhang map at the print pose.  Faces steeper than 45 deg (+0.5 deg faceting tolerance) from vertical come
    from the mesh normals, grouped by Z level and turned into exact 2-D regions (slice above minus slice below),
    then classified: bed, chamfer micro-step (<= 0.3 mm stair), listed bridge (roof <= 13.5, umbrella plate
    <= 10.5, bore roofs D 8.7 / bore_d: every point within span/2 of an own-body anchor and every unanchored edge
    run <= span), listed rib-supported float (rib tops exactly 0.40 (+ z_lift) below, nothing closer, every point
    within (pitch - rib_w)/2 + 0.05 = 1.90 of a rib top or own anchor), 45 deg self-supporting faces (cone, V
    flanks, paw lips, bore chamfers), or UNLISTED (fail).  What lies under every region (body and gap) is measured
    with vertical rays.
LAYER  The print-pose assembly is sliced at every 0.2 mm layer mid-height (first layer 0.2): sections of
    different bodies must be >= 0.30 apart in XY in every layer, and wherever one body lies above another there
    must be >= 1 fully empty layer between them (no vertical fusing after quantisation).  Reports the minimum per
    interface, the worst layers, the printed (quantised) Z gaps, the first layer's content and whether a sub-layer
    z_lift (loose variant) survives quantisation.
SLICER  PrusaSlicer CLI (0.2 layers, 0.4 nozzle, PLA, 3 perimeters, 5/5 solid layers, 20 % gyroid, no supports,
    no brim) on the STL and the 3MF: time, filament (g), warnings (attributed by slicing each body alone), support
    presence, first-layer extents vs the plate; every bridge / overhang extrusion attributed to a body with its
    longest run without material in the 3 layers below (bridges: <= listed span) and its distance to that support
    (floats: <= 1.90); and the printed separation of the bodies in the toolpaths (XY gap after line widths >= 0.30,
    >= 1 empty layer between stacked bodies).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import shapely  # noqa: E402
import trimesh  # noqa: E402
from manifold3d import CrossSection, JoinType, Manifold  # noqa: E402

from purrbobble.assemble import mesh_arrays, write_3mf, write_stl  # noqa: E402
from purrbobble.model import build  # noqa: E402

# --------------------------------------------------------------------------------------------- criteria
LAYER_H = 0.2            # SPEC 3.4: 0.2 mm layers, first layer 0.2
NOZZLE = 0.4
WALL_MIN = 1.2           # V8 walls >= 1.2 everywhere
PLATE_MIN = 2.0          # V8 back plate >= 2.0
ROOF_MIN = 2.0           # V8 roof >= 2.0
FINGER_MIN = 4.29        # V8 fingers >= 4.29
LEG_MIN = 7.0            # V8 legs >= 7.0
POST_D = 8.0             # V8 posts D 8.0
SLIVER_T = 1.6           # V8 no slivers < 1.6 in Fill2D / Roof2D
OVERHANG_DEG = 45.0      # V9
ANGLE_TOL_DEG = 0.5      # faceting tolerance on exactly-45-deg surfaces
SPAN = {"roof": 13.5, "umbrella_plate": 10.5, "bore_roof": 8.7}   # V9 listed bridges
RIB_PITCH_MAX = 4.5      # V9 rib-supported floats
RIB_GAP_TOL = 0.02
MICRO_LEDGE = 0.30       # a horizontal ledge that overhangs its own layer below by <= 0.3 = stair-stepped chamfer
XY_GAP_MIN = 0.30        # LAYER: different bodies >= 0.30 apart in every layer
EMPTY_LAYERS_MIN = 1     # LAYER: >= 1 fully empty layer between bodies stacked in Z
SEG = 72                 # circular segments for round offsets
COSMETIC_PREFIX = "cosmetic:"


# ============================================================================================ 2-D helpers
def grow(cs: CrossSection, d: float) -> CrossSection:
    if cs.is_empty() or abs(d) < 1e-12:
        return cs
    return cs.offset(float(d), JoinType.Round, 2.0, SEG)


def opening(cs: CrossSection, t: float) -> CrossSection:
    return grow(grow(cs, -t / 2.0), t / 2.0)


def compose(items) -> CrossSection:
    items = [c for c in items if c is not None and not c.is_empty()]
    if not items:
        return CrossSection()
    out = items[0]
    for c in items[1:]:
        out = out + c
    return out


def keep_pieces(cs: CrossSection, min_area: float = 0.0, min_size: float = 0.0) -> list[CrossSection]:
    out = []
    if cs.is_empty():
        return out
    for q in cs.decompose():
        if q.area() < min_area:
            continue
        if min_size > 0:
            b = q.bounds()
            if math.hypot(b[2] - b[0], b[3] - b[1]) < min_size:
                continue
        out.append(q)
    return out


def shp(cs: CrossSection):
    """CrossSection -> shapely (Multi)Polygon."""
    polys = []
    if cs is None or cs.is_empty():
        return shapely.Polygon()
    for q in cs.decompose():
        rings = [np.asarray(c, float) for c in q.to_polygons()]
        rings = [r for r in rings if len(r) >= 3]
        if not rings:
            continue
        areas = [0.5 * float(np.dot(r[:, 0], np.roll(r[:, 1], -1)) - np.dot(r[:, 1], np.roll(r[:, 0], -1)))
                 for r in rings]
        i0 = int(np.argmax(areas))
        polys.append(shapely.Polygon(rings[i0], [rings[i] for i in range(len(rings)) if i != i0]))
    if not polys:
        return shapely.Polygon()
    return shapely.union_all(polys) if len(polys) > 1 else polys[0]


def rot2(pts, deg, pivot=(0.0, 0.0)):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    p = np.asarray(pts, float) - pivot
    return np.c_[c * p[:, 0] - s * p[:, 1], s * p[:, 0] + c * p[:, 1]] + pivot


def cover_dist(R: CrossSection, S: CrossSection, res: float = 0.05, margin: float = 15.0, **_ignored) -> float:
    """Largest distance from a point of R to the region S (raster EDT, +- res); inf if it exceeds `margin`."""
    from scipy.ndimage import distance_transform_edt
    if R.is_empty():
        return 0.0
    if S.is_empty():
        return math.inf
    gR = shp(R)
    gS = shp(S)
    x0, y0, x1, y1 = gR.bounds
    bx = (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
    res = max(res, math.sqrt((bx[2] - bx[0]) * (bx[3] - bx[1]) / 4.0e6))     # <= 4 M pixels
    xs = np.arange(bx[0], bx[2] + res, res)
    ys = np.arange(bx[1], bx[3] + res, res)
    X, Y = np.meshgrid(xs, ys)
    inR = shapely.contains_xy(gR, X.ravel(), Y.ravel()).reshape(X.shape)
    if not inR.any():
        return 0.0
    inS = shapely.contains_xy(gS, X.ravel(), Y.ravel()).reshape(X.shape)
    if not inS.any():
        return math.inf
    d = float((distance_transform_edt(~inS) * res)[inR].max())
    return math.inf if d >= margin - res else d


def rnd(v, n=3):
    if v is None:
        return None
    if isinstance(v, (list, tuple, np.ndarray)):
        return [rnd(x, n) for x in v]
    v = float(v)
    if math.isinf(v) or math.isnan(v):
        return str(v)
    return round(v, n)


def tm_of(man: Manifold) -> trimesh.Trimesh:
    v, f = mesh_arrays(man)
    return trimesh.Trimesh(v, f, process=False)


# ============================================================================================ zones
class Zoner:
    """Label surface points of a body (print-pose world coordinates) with a functional zone."""

    def __init__(self, M):
        self.M = M
        p = self.p = M.params
        S = self.S = M.sections
        self.P = np.array(p.P, float)

        def prep(cs, d=0.0):
            g = shp(grow(cs, d) if d else cs)
            shapely.prepare(g)
            return g

        sk = M.skin
        # cosmetic feature footprints
        def footprint(feats):
            items = []
            for f in feats or []:
                if f.shape is not None:
                    items.append(f.shape)
                elif f.center is not None and f.radius:
                    items.append(CrossSection.circle(float(f.radius), 48).translate(tuple(map(float, f.center))))
            return compose(items)

        try:
            face_f = sk.face_features(p.C_h, p)
        except Exception:  # pragma: no cover - skin without features
            face_f = []
        paws = sk.paw_style(p)
        paw_f = footprint(list(paws["R"].features) + list(paws["L"].features))
        try:
            plate_f = sk.backdrop_features(p, S["backdrop2d"], S["body2d"], S["swept_faceup2d"])
        except Exception:
            plate_f = []
        decor_f = sk.body_decor_features(p) if hasattr(sk, "body_decor_features") else []
        self.g = {
            "ribs_back": prep(S["ribs_back2d"], 0.05),
            "ribs_roof": prep(S["ribs_roof2d"], 0.05) if not S["ribs_roof2d"].is_empty() else None,
            "ribs_band": prep(S["ribs_band2d"], 0.05) if not S.get("ribs_band2d", CrossSection()).is_empty() else None,
            "ribs_front": prep(S["ribs_front2d"], 0.05) if not S.get("ribs_front2d", CrossSection()).is_empty() else None,
            "ribs_groove": prep(S["groove_rib2d"], 0.05) if not S.get("groove_rib2d", CrossSection()).is_empty() else None,
            "paws": prep(compose([S["paw_plan_R"], S["paw_plan_L"]]), 0.05),
            "decor": prep(S["decor2d"], 0.05) if not S["decor2d"].is_empty() else None,
            "pads": prep(S["stoppads2d"], 0.1) if not S["stoppads2d"].is_empty() else None,
            "plate_edge": prep(S["backdrop2d"] - grow(S["backdrop2d"], -0.8)),
            "plate_feat": prep(footprint(plate_f), 1.5) if plate_f else None,
            "paw_feat": prep(paw_f, 1.5) if not paw_f.is_empty() else None,
            "decor_feat": prep(footprint(decor_f), 1.5) if decor_f else None,
            "face_feat": prep(footprint(face_f), 1.5) if face_f else None,
            "relief": prep(S["wheel_relief2d"], 1.5) if not S.get("wheel_relief2d", CrossSection()).is_empty() else None,
            "fingers": prep(S["fingers2d"], 0.05),
            "legs_free": prep(S["legs2d"] - S["face2d"], 0.05),
            "hub": prep(S["hub2d"], 0.05),
        }

    def _in(self, key, x, y):
        g = self.g.get(key)
        if g is None:
            return np.zeros(len(x), bool)
        return shapely.contains_xy(g, x, y)

    def to_design(self, body, pts):
        """World print-pose points -> the body's design frame."""
        p = self.p
        pts = np.asarray(pts, float).copy()
        if body == "wheel":
            pts[:, :2] = rot2(pts[:, :2], -p.phi_print)
            pts[:, 2] -= p.z_lift
        elif body == "head":
            pts[:, :2] = rot2(pts[:, :2], -p.psi_print, self.P)
            pts[:, 2] -= p.z_lift
        return pts

    def label(self, body, pts_world) -> np.ndarray:
        p = self.p
        q = self.to_design(body, pts_world)
        x, y, z = q[:, 0], q[:, 1], q[:, 2]
        n = len(q)
        lab = np.full(n, "", dtype=object)
        rO = np.hypot(x, y)
        rP = np.hypot(x - self.P[0], y - self.P[1])
        e = 1e-3
        if body == "frame":
            post_zone = p.post_r + p.post_root_fillet + 0.25
            rules = [
                ((z <= p.z_bp + e) & (z >= p.z_bp - 0.7) & self._in("plate_feat", x, y), COSMETIC_PREFIX + "plate_groove"),
                ((z <= p.z_bp + e) & self._in("plate_edge", x, y), "plate_edge"),
                # a sample on a back-plate rib's side wall exactly at its root (z_bp) belongs to the rib
                ((z >= p.z_bp - e) & (z <= p.z_bp + p.rib_h + e) & self._in("ribs_back", x, y), "rib_back"),
                (z <= p.z_bp + e, "plate"),
                (((rO <= post_zone) | (rP <= post_zone)) & (z <= p.post_z1 + e), "post"),
                ((z <= p.z_bp + p.rib_h + e) & self._in("ribs_back", x, y), "rib_back"),
                ((z >= p.z_roof1 - e) & (z <= p.z_roof1 + p.rib_h + e) & self._in("ribs_roof", x, y), "rib_roof"),
                ((z >= p.paw_z1 - 0.7) & self._in("paw_feat", x, y) & self._in("paws", x, y), COSMETIC_PREFIX + "paw_feature"),
                ((z >= p.z_roof1 - e) & self._in("paws", x, y) & (rO <= p.paw_wall_r + 0.05), "paw_lip"),
                ((z >= p.z_roof1 - e) & self._in("paws", x, y), "paw"),
                ((z >= p.z_decor1 - 0.7) & self._in("decor_feat", x, y) & self._in("decor", x, y), COSMETIC_PREFIX + "decor_feature"),
                ((z >= p.z_roof1 - e) & self._in("decor", x, y), "decor"),
                ((z >= 7.6) & (z <= 11.8) & (rO - z - 7.0 >= -0.05) & (rO - z - 7.0 <= 1.3 * math.sqrt(2)), "funnel_seat"),
                ((z <= p.z_roof0 + e) & self._in("pads", x, y), "stop_pad"),
            ]
            default = "fill_roof"
        elif body == "wheel":
            rules = [
                ((rO <= p.bore_r + 1.0) & (z <= p.bore_roof_z + 0.6), "bore_hub"),
                ((z <= p.z_teeth1 + e) & (rO >= p.Rt - 1.2), "tooth_tip"),
                ((z <= p.z_teeth1 + e) & (rO >= p.Rr - 0.05), "tooth"),
                ((z >= p.z_umb_top - p.relief_depth - 0.1) & self._in("relief", x, y), COSMETIC_PREFIX + "relief"),
                ((np.hypot(x - p.r_k, y) <= p.knob_d / 2 + p.knob_root_fillet + 0.1) & (z >= p.z_umb_top - e),
                 "knob" if getattr(p, "wheel_drive", "knob") == "knob" else "finger_well"),
            ]
            default = "umbrella"
        else:
            rules = [
                ((rP <= p.bore_r + 1.0) & (z <= p.bore_roof_z + 0.6), "bore_hub"),
                ((z >= p.z_front1 - 0.7) & self._in("face_feat", x, y), COSMETIC_PREFIX + "face_feature"),
                ((z >= p.z_band1 - e) & (z <= p.z_band1 + p.rib_h + e) & self._in("ribs_band", x, y), "rib_band"),
                ((z >= p.z_roof1 + p.gap_rib - e) & (z <= p.z_front0 + e) & self._in("ribs_front", x, y), "rib_front"),
                ((z >= getattr(p, "z_groove", 0.0) - p.rib_h - p.z_lift - 0.05 - e)
                 & (z <= getattr(p, "z_groove", 0.0) - p.z_lift + e) & self._in("ribs_groove", x, y), "rib_groove"),
                ((z <= p.z_band1 + e) & self._in("fingers", x, y), "finger"),
                ((z <= p.z_band1 + e) & self._in("legs_free", x, y), "leg"),
                ((z <= p.z_band1 + e) & self._in("hub", x, y), "hub"),
                (z <= p.z_band1 + e, "band"),
                (z <= p.z_front0 + e, "face_mid"),
            ]
            default = "face_front"
        for m, name in rules:
            sel = m & (lab == "")
            lab[sel] = name
        lab[lab == ""] = default
        return lab


def zone_policy(zone: str, p) -> tuple[str, float]:
    """(kind, required minimum) for a zone: designed / frozen / cosmetic / structural."""
    if zone in ("rib_back", "rib_roof", "rib_band", "rib_front", "rib_groove"):
        return "designed", p.rib_w - 0.03          # SPEC 3.4 skid ribs 0.8 wide
    if zone == "tooth_tip":
        return "frozen", 0.0                       # SPEC 2.3 frozen escapement (tip land 2 x 1.721 deg)
    if zone.startswith(COSMETIC_PREFIX):
        return "cosmetic", 0.0
    return "structural", WALL_MIN


# ============================================================================================ layers
class Layers:
    """Conservative per-layer sections (union of slices just below and above the layer mid-height)."""

    def __init__(self, bodies: dict, z_top: float, h: float = LAYER_H):
        self.h = h
        self.n = int(math.ceil(z_top / h - 1e-9))
        self.mid = np.array([h * k + h / 2 for k in range(self.n)])
        self.sec = {}
        self._shp = {}
        for name, b in bodies.items():
            lst = []
            lo, hi = b.bounding_box()[2], b.bounding_box()[5]
            for zm in self.mid:
                if zm < lo - 1e-4 or zm > hi + 1e-4:
                    lst.append(CrossSection())
                    continue
                lst.append(compose([b.slice(float(zm - 1e-4)), b.slice(float(zm + 1e-4))]))
            self.sec[name] = lst

    def shp(self, name, k):
        key = (name, k)
        if key not in self._shp:
            g = shp(self.sec[name][k])
            shapely.prepare(g)
            self._shp[key] = g
        return self._shp[key]


# ============================================================================================ V8
def v8_topology(M, bodies: dict, stl_path: Path | None, mf_path: Path | None) -> dict:
    out = {"bodies": {}, "stl": None, "3mf": None}
    ok = True
    for k, b in bodies.items():
        t = tm_of(b)
        d = {"components": len(b.decompose()), "status": str(b.status()), "genus": int(b.genus()),
             "volume_mm3": rnd(b.volume(), 2), "watertight": bool(t.is_watertight),
             "winding_consistent": bool(t.is_winding_consistent), "euler": int(t.euler_number)}
        d["pass"] = (d["components"] == 1 and d["status"].endswith("NoError") and d["watertight"]
                     and d["winding_consistent"] and b.volume() > 0)
        ok &= d["pass"]
        out["bodies"][k] = d
    vols = sorted(float(b.volume()) for b in bodies.values())
    if stl_path is not None and stl_path.exists():
        t = trimesh.load(str(stl_path), force="mesh")
        t.merge_vertices()
        shells = t.split(only_watertight=False)
        sv = sorted(float(abs(s.volume)) for s in shells)
        match = len(sv) == len(vols) and all(abs(a - b) <= 2e-3 * b for a, b in zip(sv, vols))
        bb_model = np.array([[b.bounding_box()[i] for i in range(6)] for b in bodies.values()])
        lo = bb_model[:, :3].min(0)
        hi = bb_model[:, 3:].max(0)
        bb_ok = bool(np.allclose(t.bounds[0], lo, atol=0.01) and np.allclose(t.bounds[1], hi, atol=0.01))
        d = {"path": str(stl_path), "shells": len(shells), "watertight_shells": int(sum(s.is_watertight for s in shells)),
             "shell_volumes": rnd(sv, 1), "model_volumes": rnd(vols, 1), "matches_model": bool(match and bb_ok)}
        d["pass"] = d["shells"] == 3 and d["watertight_shells"] == 3 and d["matches_model"]
        ok &= d["pass"]
        out["stl"] = d
    if mf_path is not None and mf_path.exists():
        d = {"path": str(mf_path)}
        try:
            with zipfile.ZipFile(mf_path) as z:
                model = z.read("3D/3dmodel.model").decode()
                cfg = z.read("Metadata/Slic3r_PE_model.config").decode() if "Metadata/Slic3r_PE_model.config" in z.namelist() else ""
            n_obj = len(re.findall(r"<object ", model))
            vols3 = re.findall(r'<volume firstid="(\d+)" lastid="(\d+)">(.*?)</volume>', cfg, re.S)
            names = [re.search(r'key="name" value="([^"]+)"', v[2]).group(1) for v in vols3]
            infill = {re.search(r'key="name" value="([^"]+)"', v[2]).group(1):
                      (re.search(r'key="fill_density" value="([^"]+)"', v[2]).group(1)
                       if re.search(r'key="fill_density"', v[2]) else None) for v in vols3}
            V = np.array([[float(a), float(b), float(c)] for a, b, c in
                          re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"/>', model)])
            F = np.array([[int(a), int(b), int(c)] for a, b, c in
                          re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"/>', model)])
            parts = {}
            for (a, b, _), nm in zip(vols3, names):
                sub = trimesh.Trimesh(V, F[int(a):int(b) + 1], process=True)
                parts[nm] = {"triangles": int(b) - int(a) + 1, "watertight": bool(sub.is_watertight),
                             "volume_mm3": rnd(abs(sub.volume), 1)}
            d.update({"objects": n_obj, "parts": parts, "infill": infill})
            pv = sorted(v["volume_mm3"] for v in parts.values())
            d["matches_model"] = len(pv) == 3 and all(abs(a - b) <= 2e-3 * b for a, b in zip(pv, vols))
            d["pass"] = (n_obj == 1 and len(parts) == 3 and all(v["watertight"] for v in parts.values())
                         and d["matches_model"])
        except Exception as ex:  # pragma: no cover
            d.update({"error": repr(ex), "pass": False})
        ok &= d["pass"]
        out["3mf"] = d
    out["pass"] = bool(ok)
    return out


def ray_thickness(t: trimesh.Trimesh, n: int, seed: int) -> tuple:
    pts, fi = trimesh.sample.sample_surface(t, n, seed=seed)
    nrm = t.face_normals[fi]
    d = -nrm
    o = pts + d * 1e-4
    loc, ri, _ = t.ray.intersects_location(o, d, multiple_hits=False)
    th = np.full(n, np.inf)
    th[ri] = np.linalg.norm(loc - o[ri], axis=1) + 1e-4
    return pts, nrm, th


class ThinMap:
    """Per-height XY width analysis of one body: pieces of (slice - opening(slice, t)).

    Each piece gets  length  (long side of its minimum rotated rectangle),  w_est  (2 x the largest distance from a
    point of the piece to the section boundary: ~ the wall width for a strip, small for a corner tip) and  kind :
    'wall' when it is a strip at least WALL_LEN long (a real thin wall / fin / knife edge), else 'corner' (the tip of
    an acute plan corner or a short stub)."""

    WALL_LEN = 2.0

    def __init__(self, body: Manifold, t: float = WALL_MIN):
        self.b, self.t, self.c = body, t, {}

    def at(self, z: float, exact: bool = False):
        key = round(z, 4) if exact else round(round(z / 0.02) * 0.02, 3)
        if key not in self.c:
            S = self.b.slice(float(key))
            self.c[key] = (S, thin_pieces(S, self.t))
        return self.c[key]

    def put(self, z: float, S: CrossSection):
        """Register an externally computed section (the conservative layer section) at height z."""
        key = round(z, 4)
        if key not in self.c:
            self.c[key] = (S, thin_pieces(S, self.t))
        return self.c[key]

    def kind_at(self, x: float, y: float, z: float):
        S, pcs = self.at(z)
        pt = shapely.Point(x, y)
        best = None
        for d in pcs:
            dist = d["g"].distance(pt)
            if dist < 0.06 and (best is None or dist < best[0]):
                best = (dist, d)
        return best[1] if best else None


def thin_pieces(S: CrossSection, t: float, min_area: float = 0.02, min_size: float = 0.6) -> list[dict]:
    if S.is_empty():
        return []
    gS = shp(S)
    bnd = gS.boundary
    out = []
    # opening(., 0.03) of the residue drops the hair-line slivers that offsetting leaves along curved outlines
    for q in keep_pieces(opening(S - opening(S, t), 0.03), min_area, min_size):
        g = shp(q)
        shapely.prepare(g)
        try:
            rect = shapely.minimum_rotated_rectangle(g)
            xy = np.asarray(rect.exterior.coords)
            e = np.hypot(*np.diff(xy, axis=0).T)
            length = float(e.max())
        except Exception:
            b = q.bounds()
            length = math.hypot(b[2] - b[0], b[3] - b[1])
        xs, ys = _grid_in(g, max(0.03, math.sqrt(q.area() / 3000.0)))
        if len(xs) == 0:
            rp = g.representative_point()
            xs, ys = np.array([rp.x]), np.array([rp.y])
        w = 2.0 * float(shapely.distance(bnd, shapely.points(np.c_[xs, ys])).max())
        rp = g.representative_point()
        kind = "wall" if length >= ThinMap.WALL_LEN else "corner"
        d = {"cs": q, "g": g, "area": q.area(), "length": length, "w_est": w, "kind": kind, "xy": [rp.x, rp.y]}
        if kind == "wall":
            d["w_min"] = _wall_min_width(S, q, t)
        out.append(d)
    return out


def _wall_min_width(S: CrossSection, q: CrossSection, t: float) -> float:
    """Thinnest width of a thin-wall piece q of section S: the smallest t' whose opening already removes part of q
    (bisection; S is clipped 3 mm around q so the clip edges cannot reach q)."""
    Sl = S ^ grow(q, 3.0)
    lo, hi = 0.0, t
    for _ in range(7):
        mid = 0.5 * (lo + hi)
        gone = (q ^ (Sl - opening(Sl, mid)))
        if not gone.is_empty() and gone.area() > 2e-3:
            hi = mid
        else:
            lo = mid
    return hi


def v8_walls_rays(M, bodies, zoner: Zoner, n_rays: int, thinmaps: dict) -> dict:
    p = M.params
    out = {"method": ("inward ray from area-weighted surface samples (trimesh/embree), thickness = first exit; every "
                      "thin structural sample is re-checked in the XY slice at its height (ThinMap): 'wall' = strip "
                      ">= 2 mm long thinner than 1.2 (fail), 'corner' = acute-corner tip / short stub (warn), "
                      "'edge_z_only' = XY section >= 1.2 wide there (stepped edge round seen by a vertical ray, warn)"),
           "samples_per_body": n_rays, "bodies": {}}
    status = "pass"
    clusters_all = []
    for bi, (k, b) in enumerate(bodies.items()):
        t = tm_of(b)
        pts, nrm, th = ray_thickness(t, n_rays, seed=11 + bi)
        lab = zoner.label(k, pts)
        tmap = thinmaps[k]
        d = {"min": rnd(np.min(th)), "p01": rnd(np.percentile(th, 1)), "median": rnd(np.median(th)),
             "no_hit": int(np.isinf(th).sum()), "frac_below_1.2": rnd(float((th < WALL_MIN).mean()), 4),
             "zones": {}}
        thin = np.nonzero(th < WALL_MIN)[0]
        kinds = {}
        for i in thin:
            kind, need = zone_policy(lab[i], p)
            if kind == "structural":
                q = pts[i] - 0.05 * nrm[i]
                hit = tmap.kind_at(q[0], q[1], q[2])
                kind = "edge_z_only" if hit is None else hit["kind"]
            kinds[i] = kind
        for zone in sorted(set(lab[thin])):
            idx = [i for i in thin if lab[i] == zone]
            kind0, need = zone_policy(zone, p)
            ks = defaultdict(int)
            for i in idx:
                ks[kinds[i]] += 1
            worst = sorted(idx, key=lambda i: th[i])[:5]
            zmin = min(th[i] for i in idx)
            zd = {"policy": kind0, "n_thin": len(idx), "min": rnd(zmin), "kinds": dict(ks),
                  "worst": [{"at": rnd(pts[i], 2), "t": rnd(th[i]), "normal": rnd(nrm[i], 2), "kind": kinds[i]}
                            for i in worst]}
            if kind0 == "designed":
                zd["required"] = rnd(need)
                zd["status"] = "pass" if zmin >= need else "warn"
                if zd["status"] == "warn":
                    zd["note"] = "rays at clipped / rounded rib ends; rib body width checked in V8_ribs"
            elif kind0 in ("frozen", "cosmetic"):
                zd["status"] = "warn"
            else:
                zd["status"] = "fail" if ks.get("wall", 0) else "warn"
            d["zones"][zone] = zd
            if zd["status"] == "fail":
                status = "fail"
            elif zd["status"] == "warn" and status == "pass":
                status = "warn"
        xs = [i for i in thin if kinds[i] in ("wall", "corner")]
        if xs:
            lab_c = _cluster(pts[xs], 1.5)
            for c in sorted(set(lab_c)):
                ii = [xs[j] for j in np.nonzero(lab_c == c)[0]]
                clusters_all.append({"body": k, "zone": lab[ii[0]], "kind": kinds[ii[0]], "n": len(ii),
                                     "min_t": rnd(min(th[i] for i in ii)), "centroid": rnd(pts[ii].mean(0), 2),
                                     "z_range": rnd([pts[ii][:, 2].min(), pts[ii][:, 2].max()], 2),
                                     "area_est_mm2": rnd(len(ii) * t.area / n_rays, 2)})
        out["bodies"][k] = d
    out["structural_thin_clusters"] = sorted(clusters_all, key=lambda c: (c["kind"] != "wall", -c["n"]))
    out["status"] = status
    return out


def _cluster(P: np.ndarray, link: float) -> np.ndarray:
    """Single-linkage clusters (union-find on a KD-tree)."""
    from scipy.spatial import cKDTree
    n = len(P)
    parent = np.arange(n)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for a, b in cKDTree(P).query_pairs(link):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return np.array([find(i) for i in range(n)])


def v8_layer_widths(M, L: Layers, zoner: Zoner, thinmaps: dict) -> dict:
    """Second method: XY width of every 0.2 mm layer section (slice minus its opening by 1.2 / 0.8 / 0.4)."""
    p = M.params
    out = {"method": ("per layer mid-height: pieces of slice - opening(slice, 1.2) (>= 0.02 mm^2), classified 'wall' "
                      "(strip >= 2 mm long) or 'corner' (acute-corner tip / stub); w_est = local width estimate"),
           "bodies": {}}
    status = "pass"
    walls = []
    for k in L.sec:
        tmap = thinmaps[k]
        zones = defaultdict(lambda: {"layers": set(), "area_mm2": 0.0, "walls": 0, "corners": 0, "w_min": math.inf,
                                     "examples": []})
        for i in range(L.n):
            if L.sec[k][i].is_empty():
                continue
            z = float(L.mid[i])
            S, pcs = tmap.put(z, L.sec[k][i])
            for d in pcs:
                zone = zoner.label(k, np.array([[d["xy"][0], d["xy"][1], z]]))[0]
                zz = zones[zone]
                zz["layers"].add(round(z, 2))
                zz["area_mm2"] += d["area"]
                zz["walls" if d["kind"] == "wall" else "corners"] += 1
                if d["kind"] == "wall":
                    zz["w_min"] = min(zz["w_min"], d.get("w_min", d["w_est"]))
                if len(zz["examples"]) < 5 or (d["kind"] == "wall" and len(zz["examples"]) < 8):
                    zz["examples"].append({"z": round(z, 2), "xy": rnd(d["xy"], 2), "area": rnd(d["area"], 3),
                                           "length": rnd(d["length"], 2), "w_min": rnd(d.get("w_min"), 2),
                                           "kind": d["kind"]})
                kind, _ = zone_policy(zone, p)
                if kind == "structural" and d["kind"] == "wall":
                    walls.append({"body": k, "zone": zone, "z": round(z, 2), "xy": rnd(d["xy"], 2),
                                  "area": rnd(d["area"], 3), "length": rnd(d["length"], 2), "w_min": rnd(d["w_min"], 2)})
        bz = {}
        for zone, zz in zones.items():
            kind, need = zone_policy(zone, p)
            if kind == "structural":
                st = "fail" if zz["walls"] else "warn"
            elif kind == "designed":
                st = "pass"
            else:
                st = "warn"
            bz[zone] = {"policy": kind, "n_layers": len(zz["layers"]),
                        "z_range": rnd([min(zz["layers"]), max(zz["layers"])], 2),
                        "area_sum_mm2": rnd(zz["area_mm2"], 2), "wall_pieces": zz["walls"],
                        "corner_pieces": zz["corners"], "thinnest_wall_w_est": rnd(zz["w_min"], 2),
                        "examples": zz["examples"], "status": st}
            if st == "fail":
                status = "fail"
            elif st == "warn" and status == "pass":
                status = "warn"
        out["bodies"][k] = bz
    out["structural_thin_walls"] = sorted(walls, key=lambda d: d["w_min"])[:30]
    out["status"] = status
    return out


def v8_specifics(M, bodies, zoner: Zoner) -> dict:
    p = M.params
    S = M.sections
    res = {}
    frame_t = tm_of(bodies["frame"])

    # ---- back plate >= 2.0: vertical rays upward from a grid on the plate bottom (inside the 0.5 chamfer)
    bd = shp(grow(S["backdrop2d"], -(p.bp_chamfer + 0.1)))
    xs, ys = _grid_in(bd, 0.5)
    o = np.c_[xs, ys, np.full(len(xs), -0.01)]
    th = _vertical_extent(frame_t, o, +1)
    lab = zoner.label("frame", np.c_[xs, ys, np.full(len(xs), p.z_bp)])
    cos = np.array([str(v).startswith(COSMETIC_PREFIX) for v in lab])
    plate_min = float(np.min(th[~cos])) if (~cos).any() else math.inf
    res["back_plate"] = {"criterion": f">= {PLATE_MIN}", "samples": int(len(th)), "min_excl_cosmetic": rnd(plate_min),
                         "min_incl_cosmetic_grooves": rnd(float(np.min(th))),
                         "at_min": rnd(np.r_[xs[np.argmin(th)], ys[np.argmin(th)]], 2),
                         "status": "pass" if plate_min >= PLATE_MIN - 1e-3 else "fail"}
    if np.min(th) < PLATE_MIN - 1e-3 and res["back_plate"]["status"] == "pass":
        res["back_plate"]["status"] = "warn"
        res["back_plate"]["note"] = "only the skin's cosmetic plate deboss (e.g. stitch groove) is thinner"

    # ---- roof >= 2.0: vertical rays upward from the roof underside over the head channels (bridges)
    L0 = p.z_roof0
    R = bodies["frame"].slice(L0 + 2e-3) - bodies["frame"].slice(L0 - 2e-3)
    R = compose(keep_pieces(opening(compose(keep_pieces(R, 1e-4)), 0.05), 0.05))
    g = shp(grow(R, -0.05))           # stay off the outline (micro-ledges of the stacked slabs)
    xs, ys = _grid_in(g, 0.3)
    o = np.c_[xs, ys, np.full(len(xs), L0 - 1e-3)]          # in the air just under the bridge
    th = _vertical_extent(frame_t, o, +1)
    rO = np.hypot(xs, ys)
    body_edge = shp(S["body2d"]).boundary
    d_edge = shapely.distance(body_edge, shapely.points(np.c_[xs, ys])) if len(xs) else np.zeros(0)
    interior = (rO > p.R_hole_roof + 0.5) & (d_edge > p.frame_top_fillet + 0.05)
    imin = float(np.min(th[interior])) if interior.any() else math.inf
    j = int(np.argmin(np.where(interior, th, np.inf))) if interior.any() else 0
    res["roof"] = {"criterion": f">= {ROOF_MIN} (vertical, over the head channels; interior = off the r "
                                f"{p.frame_top_fillet} top-edge round and the keep-out cone)",
                   "samples": int(len(th)), "min_interior": rnd(imin), "at_min_interior": rnd([xs[j], ys[j]], 2) if len(xs) else None,
                   "min_all": rnd(float(np.min(th))) if len(th) else None,
                   "at_min_all": rnd([xs[np.argmin(th)], ys[np.argmin(th)]], 2) if len(th) else None,
                   "area_below_2.0_mm2": rnd(float((th < ROOF_MIN - 1e-3).sum()) * 0.09, 1),
                   "area_below_2.0_interior_mm2": rnd(float(((th < ROOF_MIN - 1e-3) & interior).sum()) * 0.09, 1)}
    if imin >= ROOF_MIN - 1e-3:
        res["roof"]["status"] = "pass" if len(th) and np.min(th) >= ROOF_MIN - 1e-3 else "warn"
        if res["roof"]["status"] == "warn":
            res["roof"]["note"] = ("thinner only within the r 1.0 top-edge round of the body outline and where the 45 deg "
                                   "umbrella keep-out trims the roof's inner edge (r 17.1-17.4 about O): edge geometry")
    else:
        res["roof"]["status"] = "fail"

    # ---- fingers >= 4.29 and legs >= 7.0: chord width perpendicular to their axes in the head band slice
    hb = M.head.slice(0.5 * (p.z_band0 + p.z_band1) + p.z_lift)
    gh = shp(hb)
    fing = []
    for i, (cx, cy) in enumerate(p.pallets):
        u = np.array(p.u[i], float)
        v = np.array([-u[1], u[0]])
        ts = np.linspace(0.0, p.finger_L, 71)
        w = np.array([chord_width(gh, np.array([cx, cy]) + t_ * u, v) for t_ in ts])
        fing.append({"pallet": "LR"[i], "min_width": rnd(float(w.min())), "at_t_from_pallet_centre": rnd(float(ts[np.argmin(w)]), 2),
                     "width_at_pallet_centre": rnd(float(w[0])), "width_at_root": rnd(float(w[-1]))})
    fmin = min(f_["min_width"] for f_ in fing)
    res["fingers"] = {"criterion": f">= {FINGER_MIN} (chord perpendicular to the finger axis, pallet centre -> root)",
                      "per_finger": fing, "min": fmin, "status": "pass" if fmin >= FINGER_MIN - 0.01 else "fail"}
    face = shp(M.sections["face2d"])
    legs = []
    for i in range(2):
        A = np.array(p.leg_A[i], float)
        Bp = np.array(p.leg_Bs[i], float)
        e = (Bp - A) / np.linalg.norm(Bp - A)
        v = np.array([-e[1], e[0]])
        ts = np.linspace(0, 1, 121)
        pts = A + ts[:, None] * (Bp - A)
        free = ~shapely.contains_xy(face, pts[:, 0], pts[:, 1])
        w = np.array([chord_width(gh, c, v) for c in pts])
        sel = free
        j = int(np.argmin(np.where(sel, w, np.inf)))
        legs.append({"leg": "LR"[i], "min_width_free_span": rnd(float(w[j])), "at": rnd(pts[j], 2),
                     "at_frac_from_A": rnd(float(ts[j]), 3), "free_span_len": rnd(float(sel.mean() * np.linalg.norm(Bp - A)), 2),
                     "len_below_7.0": rnd(float(((w < LEG_MIN - 0.01) & sel).mean() * np.linalg.norm(Bp - A)), 2)})
    lmin = min(lg["min_width_free_span"] for lg in legs)
    res["legs"] = {"criterion": f">= {LEG_MIN} (chord perpendicular to A->B where the leg is not under the face)",
                   "per_leg": legs, "min": rnd(lmin), "status": "pass" if lmin >= LEG_MIN - 0.01 else "fail"}
    if res["legs"]["status"] == "fail":
        # in-plane bending from the pallet force: sigma ~ arm / w^2.  Compare the narrowed section with the leg
        # root at the face edge (full width), which the SPEC strength check (11 MPa) is based on.
        worst = []
        for i, lg in enumerate(legs):
            pc = np.array(p.pallets[i], float)
            c = np.array(lg["at"], float)
            A = np.array(p.leg_A[i], float)
            Bp = np.array(p.leg_Bs[i], float)
            ts = np.linspace(0, 1, 121)
            pts = A + ts[:, None] * (Bp - A)
            free = ~shapely.contains_xy(face, pts[:, 0], pts[:, 1])
            root = pts[free][-1]
            s_n = np.linalg.norm(c - pc) / max(lg["min_width_free_span"], 1e-6) ** 2
            s_r = np.linalg.norm(root - pc) / LEG_MIN ** 2
            worst.append(s_n / s_r)
        res["legs"]["bending_stress_ratio_narrowed_vs_root"] = rnd(max(worst), 2)
        res["legs"]["note"] = ("narrowed near the pallet end A by WheelEx2D = SweptInv(disc(O, 14.90)) - the SPEC's own "
                               "HeadBand2D definition; the narrowed section sees less bending than the full-width root")
        if max(worst) < 1.0 and lmin >= 0.75 * LEG_MIN:
            res["legs"]["status"] = "warn"

    # ---- posts D 8.0: inscribed radius about O and P in frame slices clear of root fillet, ridge and chamfer
    zs = [p.post_z0 + p.post_root_fillet + 0.2, p.ridge_z - p.ridge_h - 0.25, p.ridge_z + p.ridge_h + 0.25,
          p.post_z1 - p.post_chamfer - 0.1]
    posts = []
    for nm, c in (("O", (0.0, 0.0)), ("P", tuple(p.P))):
        rr = []
        for z in zs:
            gs = shp(bodies["frame"].slice(float(z)))
            pt = shapely.Point(*c)
            comp = [q for q in getattr(gs, "geoms", [gs]) if q.contains(pt)]
            rr.append(comp[0].exterior.distance(pt) if comp else 0.0)
        posts.append({"post": nm, "z": rnd(zs, 2), "inscribed_d": rnd([2 * r for r in rr])})
    pmin = min(min(pp["inscribed_d"]) for pp in posts)
    res["posts"] = {"criterion": f"D {POST_D} (inscribed, faceting tol 0.01)", "per_post": posts, "min_d": pmin,
                    "status": "pass" if pmin >= POST_D - 0.01 else "fail"}

    # ---- slivers < 1.6 in Fill2D / Roof2D (2-D sections); the stop pads are added after open_1.6 (SPEC) and are
    #      checked separately below
    pads = S["stoppads2d"]
    sl2 = {}
    for nm, cs, excl in (("fill2d", S["fill2d"], grow(pads, 0.7) if not pads.is_empty() else CrossSection()),
                         ("roof2d", S["roof2d"], CrossSection())):
        pcs = [d for d in thin_pieces(cs, SLIVER_T) if (d["cs"] - excl).area() > 0.02]
        sl2[nm] = {"walls": [{"xy": rnd(d["xy"], 2), "length": rnd(d["length"], 2), "w_min": rnd(d["w_min"], 2)}
                             for d in pcs if d["kind"] == "wall"],
                   "corners": len([d for d in pcs if d["kind"] == "corner"])}
    bad = any(v["walls"] for v in sl2.values())
    res["slivers_2d"] = {"criterion": f"no sliver (strip >= 2 mm long) narrower than {SLIVER_T} in Fill2D (pads excluded) "
                                      "/ Roof2D", "sections": sl2, "status": "fail" if bad else "pass"}

    # ---- stop pads (banking stops): thickness and the part not backed by the fill wall
    rows = []
    raw = S["fill2d"] - grow(pads, 0.01) if not pads.is_empty() else S["fill2d"]
    for q in keep_pieces(pads, 0.05):
        lo, hi = 0.0, 3.0
        for _ in range(18):
            mid = 0.5 * (lo + hi)
            if grow(q, -mid).is_empty():
                hi = mid
            else:
                lo = mid
        free = keep_pieces(q - grow(raw, 0.65), 0.005)
        fl = 0.0
        for fp in free:
            try:
                xy = np.asarray(shapely.minimum_rotated_rectangle(shp(fp)).exterior.coords)
                fl = max(fl, float(np.hypot(*np.diff(xy, axis=0).T).max()))
            except Exception:
                pass
        rows.append({"centroid": rnd(_centroid(q), 2), "area_mm2": rnd(q.area(), 2), "max_width": rnd(2 * lo, 3),
                     "unbacked_area_mm2": rnd(sum(x.area() for x in free), 3), "unbacked_fin_length": rnd(fl, 2)})
    worst = max([r["unbacked_fin_length"] for r in rows], default=0.0)
    res["stop_pads"] = {"criterion": ("pads are <= 0.6 thick by construction ([Rot(Leg) (+) 0.55] - Swept(HB)); every part "
                                      "must be backed by the fill wall (no free fin > 0.8 long)"),
                        "pads": rows, "worst_unbacked_fin_length": rnd(worst, 2),
                        "status": "fail" if worst > 0.8 else ("warn" if worst > 0.2 else "pass")}

    # ---- skid ribs: designed 0.8 wide (SPEC 3.4) - every rib piece must reach that width, tips < 0.4 reported
    rr = {}
    for nm in ("ribs_back2d", "ribs_roof2d", "ribs_band2d", "ribs_front2d", "groove_rib2d"):
        if nm not in S:
            continue
        cs = S[nm]
        pcs = keep_pieces(cs, 0.05)
        narrow = [q for q in pcs if grow(q, -(p.rib_w / 2 - 0.03)).is_empty()]
        tips = keep_pieces(cs - opening(cs, NOZZLE), 0.01, 0.3)
        rr[nm] = {"pieces": len(pcs), "pieces_narrower_than_0.74": len(narrow),
                  "tip_area_below_0.4_mm2": rnd(sum(t_.area() for t_ in tips), 3)}
    res["ribs"] = {"criterion": f"rib pieces reach the designed width {p.rib_w}", "sections": rr,
                   "status": "pass" if all(v["pieces_narrower_than_0.74"] == 0 for v in rr.values()) else "fail"}
    return res


def chord_width(g, c, v, L: float = 25.0) -> float:
    """Length of the chord of polygon g through point c along direction v (0 if c is outside)."""
    c = np.asarray(c, float)
    line = shapely.LineString([c - L * v, c + L * v])
    inter = g.intersection(line)
    pt = shapely.Point(*c)
    for part in getattr(inter, "geoms", [inter]):
        if part.length > 0 and part.distance(pt) < 1e-6:
            return float(part.length)
    return 0.0


def v8_slivers_3d(M, L: Layers, zoner: Zoner) -> dict:
    """No sliver < 1.6 in every frame layer of the fill / roof band (z 2.6 - 10.4), stop pads and posts excluded."""
    p = M.params
    excl = compose([grow(M.sections["stoppads2d"], 0.7)] + [CrossSection.circle(p.post_r + p.post_root_fillet + 0.3, 96)
                    .translate(c) for c in ((0.0, 0.0), tuple(p.P))])
    rows = []
    for i, S in enumerate(L.sec["frame"]):
        z = float(L.mid[i])
        if z < p.z_bp + p.rib_h + 0.05 or z > p.z_roof1:
            continue
        for d in thin_pieces(S, SLIVER_T):
            if (d["cs"] - excl).area() < 0.02:
                continue
            zone = zoner.label("frame", np.array([[d["xy"][0], d["xy"][1], z]]))[0]
            rows.append({"z": round(z, 2), "xy": rnd(d["xy"], 2), "area": rnd(d["area"], 3), "zone": zone,
                         "kind": d["kind"], "length": rnd(d["length"], 2), "w": rnd(d.get("w_min", d["w_est"]), 2)})
    by = defaultdict(list)
    for r in rows:
        by[(r["zone"], r["kind"])].append(r)
    summ = {f"{z}/{k}": {"n_pieces": len(v), "z_range": [min(r["z"] for r in v), max(r["z"] for r in v)],
                         "area_sum": rnd(sum(r["area"] for r in v), 2), "min_w": rnd(min(r["w"] for r in v), 2),
                         "worst": sorted(v, key=lambda r: r["w"])[:4]} for (z, k), v in by.items()}
    n_walls = sum(1 for r in rows if r["kind"] == "wall")
    return {"criterion": f"frame layers z {p.z_bp + p.rib_h:.1f}-{p.z_roof1:.1f}: no sliver (strip >= 2 mm long) narrower "
                         f"than {SLIVER_T} (stop pads and posts excluded)",
            "by_zone": summ, "n_wall_pieces": n_walls, "n_corner_pieces": len(rows) - n_walls,
            "status": "fail" if n_walls else ("warn" if rows else "pass")}


def _centroid(q: CrossSection):
    """Area centroid if it lies inside the region, else a point on the surface."""
    g = shp(q)
    c = g.centroid
    if g.is_empty or not g.contains(c):
        c = g.representative_point()
    return [c.x, c.y]


def _grid_in(g, step):
    if g.is_empty:
        return np.zeros(0), np.zeros(0)
    x0, y0, x1, y1 = g.bounds
    xs, ys = np.meshgrid(np.arange(x0 + step / 2, x1, step), np.arange(y0 + step / 2, y1, step))
    xs, ys = xs.ravel(), ys.ravel()
    m = shapely.contains_xy(g, xs, ys)
    return xs[m], ys[m]


def _vertical_extent(t: trimesh.Trimesh, o: np.ndarray, sign: int) -> np.ndarray:
    """Length of material along +/-Z from origins o (first exit), via all hits."""
    if len(o) == 0:
        return np.zeros(0)
    d = np.tile([0.0, 0.0, float(sign)], (len(o), 1))
    loc, ri, _ = t.ray.intersects_location(o, d, multiple_hits=True)
    out = np.full(len(o), np.inf)
    if len(ri):
        dist = np.abs(loc[:, 2] - o[ri, 2])
        hits = defaultdict(list)
        for r, dd in zip(ri, dist):
            hits[r].append(dd)
        for r, lst in hits.items():
            lst = sorted(lst)
            # origin is outside (just below / above the surface): entry, exit, ...
            if len(lst) >= 2:
                out[r] = lst[1] - lst[0]
    return out


# ============================================================================================ V9
def v9_overhangs(M, bodies: dict, L: Layers) -> dict:
    p = M.params
    zl = p.z_lift
    lim = -math.sin(math.radians(OVERHANG_DEG + ANGLE_TOL_DEG))
    tms = {k: tm_of(b) for k, b in bodies.items()}
    allt = trimesh.util.concatenate(list(tms.values()))
    owner = np.concatenate([np.full(len(t.faces), i) for i, t in enumerate(tms.values())])
    names = list(tms)
    out = {"criterion": (f"faces > {OVERHANG_DEG} deg from vertical (+{ANGLE_TOL_DEG} deg tol) must be bed, listed bridge "
                         f"(roof <= {SPAN['roof']}, umbrella plate <= {SPAN['umbrella_plate']}, bores D {SPAN['bore_roof']}),"
                         f" listed rib float (pitch <= {RIB_PITCH_MAX}, gap 0.40) or chamfer micro-step <= {MICRO_LEDGE}"),
           "bodies": {}, "pieces": [], "faces_45deg": []}
    status = "pass"
    allowance_float = (RIB_PITCH_MAX - p.rib_w) / 2.0 + 0.05
    for k, t in tms.items():
        n = t.face_normals
        zc = t.triangles_center[:, 2]
        A = t.area_faces
        zmin = t.bounds[0, 2]
        steep = (n[:, 2] < lim)
        horiz = n[:, 2] < -0.9999
        bed = steep & (zc < zmin + 1e-3) & (zmin < 1e-3)
        oblique = steep & ~horiz
        d = {"steep_area_mm2": rnd(A[steep & ~bed].sum(), 2), "bed_area_mm2": rnd(A[bed].sum(), 2),
             "oblique_steep_area_mm2": rnd(A[oblique].sum(), 3),
             "levels": sorted(set(rnd(np.unique(np.round(zc[steep & horiz & ~bed], 3)), 3)))}
        # 45-deg faces (allowed) summary by connected cluster
        f45 = np.nonzero((n[:, 2] < -0.70) & (n[:, 2] >= lim))[0]
        d["faces_45deg_area_mm2"] = rnd(A[f45].sum(), 2)
        # surface inclination from vertical: n_z = -sin(alpha)
        d["max_oblique_angle_from_vertical_deg"] = (rnd(math.degrees(math.asin(min(1.0, -float(n[oblique, 2].min())))), 2)
                                                    if oblique.any() else None)
        for comp in _face_clusters(t, f45):
            a = float(A[comp].sum())
            if a < 0.5:
                continue
            c = (t.triangles_center[comp] * A[comp, None]).sum(0) / a
            out["faces_45deg"].append({"body": k, "area_mm2": rnd(a, 2), "centroid": rnd(c, 2),
                                       "z_range": rnd([t.triangles[comp][:, :, 2].min(), t.triangles[comp][:, :, 2].max()], 2),
                                       "label": _label45(M, k, c, t.triangles_center[comp]),
                                       "class": "45deg_self_supporting (SPEC 3.4 item 4)"})
        # oblique steep faces (none expected): unlisted
        for comp in _face_clusters(t, np.nonzero(oblique)[0]):
            a = float(A[comp].sum())
            if a < 0.05:
                continue
            c = (t.triangles_center[comp] * A[comp, None]).sum(0) / a
            out["pieces"].append({"body": k, "z": rnd(c[2], 2), "class": "UNLISTED_oblique_overhang", "area_mm2": rnd(a, 2),
                                  "centroid": rnd(c, 2), "status": "fail",
                                  "min_nz": rnd(float(n[comp, 2].min()), 3)})
            status = "fail"
        out["bodies"][k] = d
        # horizontal downward levels -> exact 2-D regions
        for Lz in d["levels"]:
            above = bodies[k].slice(Lz + 2e-3)
            below = bodies[k].slice(Lz - 2e-3)
            R = compose(keep_pieces(above - below, 1e-4))        # drop zero-area slicing noise first
            pieces = keep_pieces(opening(R, 0.02), 0.01)
            for q in pieces:
                rec = _classify_piece(M, k, Lz, q, below, bodies, allt, owner, names, allowance_float)
                out["pieces"].append(rec)
                if rec["status"] == "fail":
                    status = "fail"
                elif rec["status"] == "warn" and status == "pass":
                    status = "warn"
    out["pieces"].sort(key=lambda r: ({"fail": 0, "warn": 1, "pass": 2}[r["status"]], r["body"], r["z"], -r["area_mm2"]))
    out["unlisted_or_failed"] = [r for r in out["pieces"] if r["status"] == "fail"]
    out["status"] = status
    return out


def _face_clusters(t, idx):
    idx = np.asarray(idx)
    if len(idx) == 0:
        return []
    adj = t.face_adjacency[np.all(np.isin(t.face_adjacency, idx), axis=1)]
    return trimesh.graph.connected_components(adj, nodes=idx, min_len=1)


def _label45(M, body, c, pts):
    """Name a 45-deg face cluster; pts = its triangle centres (radii are measured per face, not at the centroid)."""
    p = M.params
    z = c[2]
    if body == "frame":
        rO = float(np.median(np.hypot(pts[:, 0], pts[:, 1])))
        rP = float(np.median(np.hypot(pts[:, 0] - p.P[0], pts[:, 1] - p.P[1])))
        if min(rO, rP) < p.ridge_apex_r + 0.3 and abs(z - p.ridge_z) < p.ridge_h + 0.2:
            return "post V-ridge lower flank"
        if rO > p.paw_lip_r - 0.1 and z > p.z_roof1:
            return "paw lip underside"
        return "frame 45 deg face"
    ax = (0.0, 0.0) if body == "wheel" else tuple(p.P)
    r = float(np.median(np.hypot(pts[:, 0] - ax[0], pts[:, 1] - ax[1])))
    zz = z - p.z_lift
    if r < p.groove_apex_r + 0.7 and zz < p.z_band0 + p.bore_chamfer + 0.1:
        return "bore entry chamfer"
    if r < p.groove_apex_r + 0.3 and abs(zz - p.ridge_z) < 1.0:
        return "bore V-groove upper flank"
    if body == "wheel" and r > p.umb_r0 - 0.5:
        return "umbrella 45 deg cone"
    return f"{body} 45 deg face"


def _classify_piece(M, body, Lz, q, below, bodies, allt, owner, names, allowance_float) -> dict:
    p = M.params
    zl = p.z_lift if body != "frame" else 0.0
    area = q.area()
    b = q.bounds()
    rec = {"body": body, "z": rnd(Lz, 3), "area_mm2": rnd(area, 2), "centroid": rnd(_centroid(q), 2),
           "bbox": rnd(b, 2)}
    _bad_parts = []
    d_own = cover_dist(q, below)
    rec["max_dist_to_own_anchor"] = rnd(d_own, 2)
    # what is under it (vertical rays down from a 0.25 grid, any body)
    g = shp(q)
    xs, ys = _grid_in(g, 0.25)
    if len(xs) == 0:
        c = g.representative_point()
        xs, ys = np.array([c.x]), np.array([c.y])
    o = np.c_[xs, ys, np.full(len(xs), Lz - 1e-4)]
    loc, ri, ti = allt.ray.intersects_location(o, np.tile([0, 0, -1.0], (len(o), 1)), multiple_hits=False)
    gap = np.full(len(o), Lz)      # to the bed if nothing is hit
    hit = np.full(len(o), "bed", dtype=object)
    gap[ri] = Lz - loc[:, 2]
    hit[ri] = [names[owner[t]] for t in ti]
    hist = defaultdict(float)
    for gv, hv in zip(gap, hit):
        hist[f"{hv}@{gv:.2f}"] += 0.0625
    rec["below"] = {k: rnd(v, 1) for k, v in sorted(hist.items(), key=lambda kv: -kv[1])[:6]}
    rec["min_gap_below"] = rnd(float(gap.min()), 3)
    # free (unanchored) edge runs of the region boundary
    runs = _free_runs(g, shp(below))
    rec["free_edge_runs"] = {"n": len(runs), "max_chord": rnd(max([r["chord"] for r in runs], default=0.0), 2),
                             "max_path": rnd(max([r["path"] for r in runs], default=0.0), 2),
                             "closed_unanchored_ring": any(r["closed"] for r in runs)}
    cls, lim = _listed_class(M, body, Lz, q, d_own)
    rec["class"] = cls
    status = "pass"
    notes = []
    if cls == "bed":
        pass
    elif cls == "chamfer_micro_step":
        notes.append(f"overhangs its own layer below by <= {MICRO_LEDGE} (stair-stepped chamfer / mesh hygiene ledge)")
    elif cls.startswith("bridge:"):
        span_lim = lim
        rec["span_limit"] = span_lim
        rec["span_est_2x_anchor_dist"] = rnd(2 * d_own, 2)
        bad = []
        # (fix round 1) a bridge may also rest on another body's rib tops exactly gap_rib below (a rib-supported
        # float, SPEC 3.4 type 1): those points need no anchor within span/2 but a rib top within the float reach
        rib_gap = p.gap_rib + (p.z_lift if body != "frame" else 0.0)
        others_r = rib_tops(bodies, body, Lz - rib_gap)
        reach = (RIB_PITCH_MAX - p.rib_w) / 2.0 + 0.05
        if not others_r.is_empty() and (q ^ others_r).area() > 0.5:
            ribzone = grow(q ^ others_r, reach)
            sup = compose([grow(below, span_lim / 2.0), ribzone])
            far_pts = keep_pieces(q - sup, 0.05)
            d_eff = max([cover_dist(fp_, compose([below, q ^ others_r])) for fp_ in far_pts], default=0.0)
            # (fix round 1) where a bridge runs from an anchor onto a rib-supported float (the crown skirt across the
            # swept leg channel: fill wall at one end, the band's groove rib under the other), the strand through a
            # point is (distance to the anchor) + (distance to the rib-supported zone): that must be <= the span limit
            strand_bad, strand_max = [], 0.0
            if far_pts:
                ga, gr = shp(below), shp(ribzone)
                for fp_ in far_pts:
                    fx, fy = _grid_in(shp(fp_), 0.1)
                    if len(fx) == 0:
                        continue
                    pts_ = shapely.points(fx, fy)
                    tot = shapely.distance(ga, pts_) + shapely.distance(gr, pts_)
                    strand_max = max(strand_max, float(tot.max()))
                    if tot.max() > span_lim + 0.05:
                        strand_bad.append(fp_)
            rec["rib_supported"] = {"rib_top_area_mm2": rnd((q ^ others_r).area(), 2),
                                    "area_beyond_anchor_and_rib_reach_mm2": rnd(sum(x.area() for x in far_pts), 2),
                                    "max_strand_anchor_to_rib_zone": rnd(strand_max, 2)}
            if sum(x.area() for x in strand_bad) > 0.5:
                bad.append(f"{sum(x.area() for x in far_pts):.1f} mm^2 farther than span/2 from an anchor and "
                           f"farther than {reach:.2f} from a rib top (max {d_eff:.2f}); strand anchor -> rib zone "
                           f"{strand_max:.2f} > span {span_lim}")
            far_pts = strand_bad
            runs = _free_runs(g, shp(compose([below, grow(q ^ others_r, reach)])))
            rec["free_edge_runs_rib_supported"] = {"n": len(runs),
                                                   "max_chord": rnd(max([r["chord"] for r in runs], default=0.0), 2)}
        elif 2 * d_own > span_lim + 0.05:
            bad.append(f"points up to {d_own:.2f} from any anchor (> span/2 = {span_lim / 2:.2f})")
        long_runs = [r for r in runs if r["chord"] > span_lim + 0.05 or r["closed"]]
        if long_runs:
            bad.append(f"{len(long_runs)} unanchored edge run(s) longer than the span limit (max chord "
                       f"{max(r['chord'] for r in long_runs):.2f}, path {max(r['path'] for r in long_runs):.2f})")
        if gap.min() < 2 * LAYER_H - 0.03:
            bad.append(f"only {gap.min():.2f} air under the bridge (< 2 layers)")
        # unanchored part: farther than span/2 from an anchor (and from rib tops, if any; and not on a strand from an
        # anchor to the rib-supported zone within the span limit)
        if not others_r.is_empty() and (q ^ others_r).area() > 0.5:
            far = list(far_pts)
        else:
            far = keep_pieces(q - grow(below, span_lim / 2.0), 0.05)
        _bad_parts += far
        rec["area_beyond_half_span_mm2"] = rnd(sum(f.area() for f in far), 2)
        rec["beyond_half_span_regions"] = [{"centroid": rnd(_centroid(f), 2), "area": rnd(f.area(), 2)} for f in far[:6]]
        if bad:
            status = "fail"
            notes += bad
    elif cls.startswith("own_rib_bridge:"):
        # the face front layer bridges between ribs that hang from it (same body, printed first): every point within
        # the float reach of an own anchor below (ribs, face mid layer) or of another body's rib top
        allowance = (RIB_PITCH_MAX - p.rib_w) / 2.0 + 0.05
        rib_gap = p.gap_rib + (p.z_lift if body != "frame" else 0.0)
        support = compose([below, rib_tops(bodies, body, Lz - rib_gap)])
        unsup = keep_pieces(q - grow(support, allowance), 0.05)
        _bad_parts += unsup
        ua = sum(u.area() for u in unsup)
        rec.update({"support_allowance": rnd(allowance, 2), "max_dist_to_support": rnd(cover_dist(q, support), 2),
                    "unsupported_area_mm2": rnd(ua, 2),
                    "unsupported_regions": [{"centroid": rnd(_centroid(u), 2), "area_mm2": rnd(u.area(), 2)}
                                            for u in sorted(unsup, key=lambda c: -c.area())[:8]]})
        if ua > 0.5:
            status = "fail"
            notes.append(f"{ua:.1f} mm^2 farther than {allowance:.2f} from its own ribs / anchors")
    elif cls.startswith("rib_float:"):
        rib_gap = p.gap_rib + (p.z_lift if body != "frame" else 0.0)
        others = rib_tops(bodies, body, Lz - rib_gap)
        too_close = compose([bodies[o].slice(Lz - rib_gap + RIB_GAP_TOL) for o in bodies if o != body])
        ribs = q ^ others
        support = compose([others, below])
        d_sup = cover_dist(q, support)
        unsup = keep_pieces(q - grow(support, allowance_float), 0.05)
        _bad_parts += unsup
        rec["_ribs"] = ribs
        ua = sum(u.area() for u in unsup)
        rec.update({"rib_gap_design": rnd(rib_gap), "area_over_rib_tops_mm2": rnd(ribs.area(), 2),
                    "max_dist_to_support": rnd(d_sup, 2), "support_allowance": rnd(allowance_float, 2),
                    "unsupported_area_mm2": rnd(ua, 2)})
        regs = []
        for u in sorted(unsup, key=lambda c: -c.area())[:8]:
            gu = shp(u)
            ux, uy = _grid_in(gu, 0.25)
            if len(ux):
                oo = np.c_[ux, uy, np.full(len(ux), Lz - 1e-4)]
                lo2, r2, t2 = allt.ray.intersects_location(oo, np.tile([0, 0, -1.0], (len(oo), 1)), multiple_hits=False)
                gg = np.full(len(oo), Lz)
                gg[r2] = Lz - lo2[:, 2]
                hh = np.full(len(oo), "bed", dtype=object)
                hh[r2] = [names[owner[t]] for t in t2]
                drop = {f"{h}@{v:.2f}": 0 for h, v in zip(hh, gg)}
                for h, v in zip(hh, gg):
                    drop[f"{h}@{v:.2f}"] += 1
                drop = {k2: rnd(v2 * 0.0625, 1) for k2, v2 in sorted(drop.items(), key=lambda kv: -kv[1])[:3]}
            else:
                drop = {}
            regs.append({"centroid": rnd(_centroid(u), 2), "area_mm2": rnd(u.area(), 2),
                         "max_dist_to_support": rnd(cover_dist(u, support), 2), "below_mm2": drop})
        rec["unsupported_regions"] = regs
        bad = []
        if ribs.is_empty() or ribs.area() < 0.5:
            bad.append("no rib tops at the designed gap below")
        if not (q ^ too_close).is_empty() and (q ^ too_close).area() > 0.01:
            bad.append(f"other body closer than the rib gap {rib_gap:.2f} below ({(q ^ too_close).area():.2f} mm^2)")
        if ua > 0.5:
            bad.append(f"{ua:.1f} mm^2 farther than {allowance_float:.2f} from any rib top / own anchor "
                       f"(max {d_sup:.2f}; rib pitch <= {RIB_PITCH_MAX} requires <= {allowance_float:.2f})")
        if bad:
            status = "fail"
            notes += bad
    else:
        status = "fail"
        _bad_parts.append(q)
        notes.append("UNLISTED overhang (not bed, listed bridge, rib float or micro-step)")
    rec["status"] = status
    rec["notes"] = notes
    rec["_cs"] = q
    rec["_bad"] = compose(_bad_parts) if _bad_parts else CrossSection()
    return rec


def rib_tops(bodies, body, z):
    """Top faces of the OTHER bodies at height z (material just below z, none just above): the skid-rib tops."""
    return compose([bodies[o].slice(z - 2e-3) - bodies[o].slice(z + 2e-3) for o in bodies if o != body])


def _listed_class(M, body, Lz, q, d_own):
    """Map a horizontal overhang region onto the SPEC 3.4 / V9 list."""
    p = M.params
    zl = p.z_lift if body != "frame" else 0.0
    c = _centroid(q)
    b = q.bounds()
    if Lz < 1e-3:
        return "bed", None
    if d_own <= MICRO_LEDGE + 1e-3:
        return "chamfer_micro_step", None
    if body == "frame" and abs(Lz - p.z_roof0) < 1e-3:
        return "bridge:roof (leg channels)", SPAN["roof"]
    if body == "frame" and getattr(p, "crown_ring", False) and abs(Lz - p.z_skirt) < 1e-3:
        # fix round 1: the crown skirt spans the leg channels like the roof does (anchored on the fill walls each
        # side, same span limit) and floats 0.40 over the head's groove rib where the band passes under it
        return "bridge:crown skirt (leg channels, over the band groove rib)", SPAN["roof"]
    if body == "head" and getattr(p, "crown_ring", False) and abs(Lz - (p.z_roof1 + p.gap_rib + zl)) < 1e-3:
        return "rib_float:front-layer ribs over the crown top", None
    if body == "head" and getattr(p, "crown_ring", False) and abs(Lz - (p.z_front0 + zl)) < 1e-3:
        return "own_rib_bridge:front layer between its own ribs", None
    if body in ("wheel", "head") and abs(Lz - (p.bore_roof_z + zl)) < 1e-3:
        ax = (0.0, 0.0) if body == "wheel" else _posed_axis(M, body)
        rmax = max(math.hypot(x - ax[0], y - ax[1]) for x, y in ((b[0], b[1]), (b[2], b[3]), (b[0], b[3]), (b[2], b[1])))
        if rmax <= (p.bore_r / math.cos(math.pi / 64)) * math.sqrt(2) + 0.1 and math.hypot(c[0] - ax[0], c[1] - ax[1]) < 1.0:
            return "bridge:bore roof", max(SPAN["bore_roof"], p.bore_d)        # loose variant: bore D 8.80
        if body == "wheel" and abs(Lz - (p.z_teeth1 + zl)) < 1e-3:
            return "bridge:umbrella plate (tooth gaps)", SPAN["umbrella_plate"]
    if body == "wheel" and abs(Lz - (p.z_teeth1 + zl)) < 1e-3:
        return "bridge:umbrella plate (tooth gaps)", SPAN["umbrella_plate"]
    if body in ("wheel", "head") and abs(Lz - (p.z_band0 + zl)) < 1e-3:
        return "rib_float:back-plate ribs", None
    if body == "head" and abs(Lz - (p.z_front0 + zl)) < 1e-3:
        return "rib_float:roof-top ribs (I3 front layer)", None
    return "UNLISTED", None


def _posed_axis(M, body):
    return (0.0, 0.0) if body == "wheel" else tuple(M.params.P)


def _free_runs(g, anchor) -> list[dict]:
    """Maximal boundary runs of region g that do not touch the anchor region (sampled every 0.1 mm)."""
    runs = []
    if g.is_empty:
        return runs
    anchor_b = anchor if not anchor.is_empty else None
    rings = []
    for poly in getattr(g, "geoms", [g]):
        rings.append(poly.exterior)
        rings.extend(poly.interiors)
    for ring in rings:
        Lr = ring.length
        if Lr < 0.05:
            continue
        m = max(8, int(Lr / 0.1))
        s = np.linspace(0, Lr, m, endpoint=False)
        pts = shapely.line_interpolate_point(ring, s)
        xy = shapely.get_coordinates(pts)
        if anchor_b is None:
            free = np.ones(m, bool)
        else:
            free = shapely.distance(anchor_b, pts) > MICRO_LEDGE
        if free.all():
            runs.append({"chord": float(np.ptp(xy, axis=0).max()), "path": float(Lr), "closed": True})
            continue
        if not free.any():
            continue
        k0 = int(np.argmin(free))          # start at an anchored sample
        f = np.roll(free, -k0)
        xy2 = np.roll(xy, -k0, axis=0)
        i = 0
        while i < m:
            if f[i]:
                j = i
                while j < m and f[j]:
                    j += 1
                a = xy2[i - 1]
                bb = xy2[j % m]
                seg = xy2[i - 1:j + 1] if j < m else np.vstack([xy2[i - 1:], xy2[:1]])
                path = float(np.sum(np.hypot(*np.diff(seg, axis=0).T)))
                runs.append({"chord": float(math.hypot(*(bb - a))), "path": path, "closed": False,
                             "from": [round(float(a[0]), 2), round(float(a[1]), 2)],
                             "to": [round(float(bb[0]), 2), round(float(bb[1]), 2)]})
                i = j
            else:
                i += 1
    return runs


# ============================================================================================ LAYER CHECK
def layer_check(M, L: Layers) -> dict:
    p = M.params
    names = list(L.sec)
    pairs = [(names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))]
    res = {"layer_h": L.h, "n_layers": L.n, "slice_at": "mid-height +- 1e-4 (union, conservative)", "pairs": {}}
    status = "pass"
    for a, b in pairs:
        key = f"{a}|{b}"
        rows = []
        min_xy, at_xy = math.inf, None
        for k in range(L.n):
            A, B = L.sec[a][k], L.sec[b][k]
            if A.is_empty() or B.is_empty():
                continue
            if not (A ^ B).is_empty() and (A ^ B).area() > 1e-6:
                dxy = 0.0
                where = _centroid(A ^ B)
            else:
                ga, gb = L.shp(a, k), L.shp(b, k)
                dxy = float(ga.distance(gb))
                if dxy < 1.0:
                    ln = shapely.shortest_line(ga, gb)
                    c = np.asarray(ln.coords).mean(0)
                    where = [float(c[0]), float(c[1])]
                else:
                    where = None
            rows.append((dxy, float(L.mid[k]), where))
            if dxy < min_xy:
                min_xy, at_xy = dxy, (float(L.mid[k]), where)
        rows.sort(key=lambda r: r[0])
        # vertical stacking: material of one body in layer k over the other in layer k-j
        min_empty = math.inf
        vrows = []
        for up, dn in ((a, b), (b, a)):
            for k in range(1, L.n):
                U = L.sec[up][k]
                if U.is_empty():
                    continue
                for j in (1, 2, 3, 4):
                    if k - j < 0:
                        break
                    D = L.sec[dn][k - j]
                    if D.is_empty():
                        continue
                    ov = U ^ D
                    if not ov.is_empty() and ov.area() > 1e-3:
                        empty = j - 1
                        # only count the minimum over j for this (k): stop at the first overlap
                        vrows.append({"upper": up, "lower": dn, "upper_layer_z": round(float(L.mid[k]), 2),
                                      "lower_layer_z": round(float(L.mid[k - j]), 2), "empty_layers": empty,
                                      "overlap_mm2": rnd(ov.area(), 2), "at": rnd(_centroid(ov), 2)})
                        min_empty = min(min_empty, empty)
                        break
        vmin = [v for v in vrows if v["empty_layers"] == min_empty] if vrows else []
        st = "pass"
        if min_xy < XY_GAP_MIN - 1e-6:
            st = "fail"
        if vrows and min_empty < EMPTY_LAYERS_MIN:
            st = "fail"
        res["pairs"][key] = {
            "min_xy_gap": rnd(min_xy, 4), "min_xy_at": {"z": rnd(at_xy[0], 2), "xy": rnd(at_xy[1], 2)} if at_xy else None,
            "worst_layers_xy": [{"z": rnd(r[1], 2), "gap": rnd(r[0], 4), "xy": rnd(r[2], 2)} for r in rows[:6]],
            "min_empty_layers_between": (None if not vrows else int(min_empty)),
            "printed_min_z_gap_mm": (None if not vrows else rnd(min_empty * L.h, 2)),
            "stacked_contacts_at_min": _dedupe(vmin)[:8],
            "stacked_interfaces": _stack_summary(vrows),
            "status": st}
        if st == "fail":
            status = "fail"
    # first layers: only the frame, as one island
    first = {k: (not L.sec[k][0].is_empty()) for k in names}
    fl_islands = len(L.sec["frame"][0].decompose()) if not L.sec["frame"][0].is_empty() else 0
    lowest = {k: next((round(float(L.mid[i] - L.h / 2), 2) for i in range(L.n) if not L.sec[k][i].is_empty()), None)
              for k in names}
    res["first_layer"] = {"bodies_present": first, "frame_islands": fl_islands,
                          "lowest_printed_layer_bottom_z": lowest,
                          "status": "pass" if (first.get("frame") and not first.get("wheel") and not first.get("head")
                                               and fl_islands == 1) else "fail"}
    if res["first_layer"]["status"] == "fail":
        status = "fail"
    # designed vs printed (quantised) bottom of the floating bodies
    q = {}
    for k in ("wheel", "head"):
        zb = bodies_bottom(M, k)
        q[k] = {"model_bottom_z": rnd(zb, 3), "printed_bottom_z": lowest[k]}
    res["float_bottom_quantisation"] = q
    if p.z_lift and any(abs((v["printed_bottom_z"] or 0) - v["model_bottom_z"]) > 1e-3 for v in q.values()):
        res["float_bottom_quantisation"]["note"] = (
            f"z_lift {p.z_lift} is below one layer: the slicer prints the floating bodies from the same layer as "
            "nominal, so the printed Z gaps equal the nominal ones (see printed_min_z_gap_mm)")
        res["float_bottom_quantisation"]["status"] = "warn"
        if status == "pass":
            status = "warn"
    res["status"] = status
    return res


def bodies_bottom(M, k):
    b = M.wheel if k == "wheel" else M.head
    return b.bounding_box()[2]


def _dedupe(rows):
    seen, out = set(), []
    for r in rows:
        key = (r["upper"], r["lower"], r["upper_layer_z"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _stack_summary(vrows):
    """Distinct (upper body bottom layer, lower body top layer) interfaces with their printed empty layers."""
    agg = {}
    for v in vrows:
        key = (v["upper"], v["lower"], v["upper_layer_z"], v["empty_layers"])
        if key not in agg or v["overlap_mm2"] > agg[key]["overlap_mm2"]:
            agg[key] = v
    rows = sorted(agg.values(), key=lambda v: (v["empty_layers"], v["upper_layer_z"]))
    return [{"upper": v["upper"], "lower": v["lower"], "upper_layer_z": v["upper_layer_z"],
             "lower_layer_z": v["lower_layer_z"], "empty_layers": v["empty_layers"],
             "printed_gap_mm": round(v["empty_layers"] * LAYER_H, 2), "overlap_mm2": v["overlap_mm2"], "at": v["at"]}
            for v in rows][:12]


# ============================================================================================ SLICER
SLICER_OPTS = ["--layer-height", "0.2", "--first-layer-height", "0.2", "--nozzle-diameter", "0.4",
               "--filament-diameter", "1.75", "--filament-type", "PLA", "--filament-density", "1.24",
               "--temperature", "210", "--first-layer-temperature", "215", "--bed-temperature", "60",
               "--first-layer-bed-temperature", "60", "--perimeters", "3", "--top-solid-layers", "5",
               "--bottom-solid-layers", "5", "--fill-density", "20%", "--fill-pattern", "gyroid", "--skirts", "1",
               "--brim-width", "0", "--elefant-foot-compensation", "0.1", "--no-support-material", "--gcode-comments",
               "--retract-lift", "0.4", "--bridge-fan-speed", "100", "--no-thick-bridges", "--center", "100,100",
               "--loglevel", "2"]


def parse_gcode(path: Path) -> dict:
    num = re.compile(r"([XYZE])([-+]?\d*\.?\d+)")
    X = Y = E = 0.0
    rel = False
    typ = None
    layer_z = None
    width = 0.45
    segs = []
    meta = {}
    with open(path) as fh:
        for line in fh:
            if line.startswith(";"):
                if line.startswith(";TYPE:"):
                    typ = line[6:].strip()
                elif line.startswith(";Z:"):
                    layer_z = float(line[3:])
                elif line.startswith(";WIDTH:"):
                    width = float(line[7:])
                elif line.startswith("; ") and " = " in line:
                    k, v = line[2:].split(" = ", 1)
                    if k in ("estimated printing time (normal mode)", "filament used [g]", "filament used [mm]",
                             "filament used [cm3]", "support_material", "support_material_auto", "fill_density",
                             "layer_height", "first_layer_height", "perimeters", "elefant_foot_compensation"):
                        meta[k] = v.strip()
                continue
            if line.startswith("M83"):
                rel = True
                continue
            if line.startswith("M82"):
                rel = False
                continue
            if line.startswith("G92"):
                m = dict((k, float(v)) for k, v in num.findall(line.split(";")[0]))
                if "E" in m:
                    E = m["E"]
                continue
            if line.startswith("G1 ") or line.startswith("G0 "):
                m = dict((k, float(v)) for k, v in num.findall(line.split(";")[0]))
                nx, ny = m.get("X", X), m.get("Y", Y)
                de = 0.0
                if "E" in m:
                    de = m["E"] if rel else m["E"] - E
                    E = E + m["E"] if rel else m["E"]
                if de > 1e-6 and (nx != X or ny != Y) and layer_z is not None:
                    segs.append((layer_z, typ, X, Y, nx, ny, width))
                X, Y = nx, ny
    return {"segs": segs, "meta": meta}


def slicer_check(M, bodies: dict, stl_path: Path, mf_path: Path | None, workdir: Path, keep: bool) -> dict:
    exe = shutil.which("prusa-slicer") or shutil.which("PrusaSlicer")
    out = {"settings": " ".join(SLICER_OPTS), "runs": {}}
    if exe is None:
        out["status"] = "not-run"
        out["note"] = "prusa-slicer not found on PATH"
        return out
    status = "pass"
    # model -> G-code coordinates: PrusaSlicer centres the object's XY bounding box on (100, 100)
    bb = np.array([b.bounding_box() for b in bodies.values()])
    off = np.array([100.0 - 0.5 * (bb[:, 0].min() + bb[:, 3].max()), 100.0 - 0.5 * (bb[:, 1].min() + bb[:, 4].max())])
    out["xy_offset_model_to_gcode"] = rnd(off, 3)
    info = subprocess.run([exe, "--info", str(stl_path)], capture_output=True, text=True, timeout=300)
    inf = {}
    for line in (info.stdout + info.stderr).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            inf[k.strip()] = v.strip()
    out["stl_info"] = {k: inf[k] for k in ("manifold", "number_of_parts", "volume", "size_x", "size_y", "size_z",
                                           "number_of_facets", "open_edges") if k in inf}
    if inf.get("manifold", "yes") != "yes":
        status = "fail"
    inputs = [("stl", stl_path)] + ([("3mf", mf_path)] if mf_path is not None and mf_path.exists() else [])
    L_cache = {}
    for tag, src in inputs:
        g = workdir / f"slice_{tag}.gcode"
        t0 = time.time()
        r = subprocess.run([exe, "--export-gcode", *SLICER_OPTS, "-o", str(g), str(src)], capture_output=True,
                           text=True, timeout=900)
        log = (r.stdout + "\n" + r.stderr)
        warn = _slicer_warnings(log)
        run = {"input": str(src), "returncode": r.returncode, "time_s": round(time.time() - t0, 1),
               "warnings": warn, "errors": [ln for ln in log.splitlines() if "error" in ln.lower()][:10]}
        if r.returncode != 0 or not g.exists():
            run["status"] = "fail"
            out["runs"][tag] = run
            status = "fail"
            continue
        G = parse_gcode(g)
        segs = G["segs"]
        meta = G["meta"]
        types = defaultdict(float)
        for z, t, x0, y0, x1, y1, w in segs:
            types[t] += math.hypot(x1 - x0, y1 - y0)
        support_len = sum(v for k, v in types.items() if k and "support" in k.lower())
        run.update({"print_time": meta.get("estimated printing time (normal mode)"),
                    "filament_g": float(meta.get("filament used [g]", "nan")),
                    "filament_m": round(float(meta.get("filament used [mm]", "nan")) / 1000.0, 2),
                    "extrusion_length_by_type_mm": {k: round(v, 1) for k, v in sorted(types.items(), key=lambda kv: -kv[1])},
                    "support_extrusion_mm": round(support_len, 2), "support_material_setting": meta.get("support_material")})
        # first layer
        z0 = min(s[0] for s in segs)
        fl = np.array([[x0, y0, x1, y1] for z, t, x0, y0, x1, y1, w in segs if z == z0 and t != "Skirt/Brim"])
        flm = np.r_[fl[:, [0, 2]].min(), fl[:, [1, 3]].min(), fl[:, [0, 2]].max(), fl[:, [1, 3]].max()]
        flm_model = flm - np.r_[off, off]
        plate = bodies["frame"].slice(0.1)
        pb = np.array(plate.bounds())
        ef, hw = 0.1, 0.2      # elephant-foot compensation, half the first-layer line width
        exp = pb + np.r_[ef + hw, ef + hw, -(ef + hw), -(ef + hw)]
        pts = np.r_[fl[:, :2], fl[:, 2:]] - off
        gpl = shp(grow(plate, 0.05))
        inside = shapely.contains_xy(gpl, pts[:, 0], pts[:, 1])
        run["first_layer"] = {"z": z0, "bbox_model_xy": rnd(flm_model, 2), "expected_bbox": rnd(exp, 2),
                              "max_bbox_dev": rnd(float(np.abs(flm_model - exp).max()), 3),
                              "frac_points_inside_plate": rnd(float(inside.mean()), 4)}
        fl_ok = run["first_layer"]["max_bbox_dev"] <= 0.25 and inside.all() and abs(z0 - 0.2) < 1e-6
        # bridges / overhang extrusions: attribute to bodies, longest run without support <= 0.6 below the layer mid
        run["bridges"] = _gcode_bridges(M, bodies, segs, off, L_cache)
        run["toolpath_gaps"] = _gcode_body_gaps(bodies, segs, off)
        bad = [b for b in run["bridges"] if b["status"] == "fail"]
        bad += [k for k, v in run["toolpath_gaps"]["pairs"].items() if v["status"] == "fail"]
        run["status"] = "pass"
        if support_len > 0 or not fl_ok or bad:
            run["status"] = "fail"
        elif warn:
            run["status"] = "warn"
        if not keep:
            try:
                g.unlink()
            except OSError:
                pass
        else:
            run["gcode"] = str(g)
        out["runs"][tag] = run
        if run["status"] == "fail":
            status = "fail"
        elif run["status"] == "warn" and status == "pass":
            status = "warn"
    # attribute the stability warnings: slice every body alone (PrusaSlicer drops it onto the bed)
    attrib = {}
    for k, body in bodies.items():
        pth = workdir / f"alone_{k}.stl"
        write_stl(pth, {k: body})
        r = subprocess.run([exe, "--export-gcode", *SLICER_OPTS, "-o", str(workdir / f"alone_{k}.gcode"), str(pth)],
                           capture_output=True, text=True, timeout=900)
        ws = _slicer_warnings(r.stdout + "\n" + r.stderr)
        attrib[k] = [w.split(" | ")[2] if len(w.split(" | ")) > 2 else w for w in ws] or ["no warning"]
        for ext in (".stl", ".gcode"):
            try:
                (workdir / f"alone_{k}{ext}").unlink()
            except OSError:
                pass
    out["warnings_per_body_alone"] = attrib
    out["status"] = status
    return out


def _slicer_warnings(log: str) -> list[str]:
    """Warning blocks of the PrusaSlicer log ('print warning: ...' up to the next progress line), joined."""
    out = []
    lines = log.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if "warning" in ln.lower():
            block = [ln.strip()]
            j = i + 1
            while j < len(lines) and not re.match(r"^\s*\d+ =>", lines[j]) and "warning" not in lines[j].lower():
                if lines[j].strip():
                    block.append(lines[j].strip())
                j += 1
            out.append(" | ".join(block))
            i = j
        else:
            i += 1
    seen, res = set(), []
    for w in out:
        if w not in seen:
            seen.add(w)
            res.append(w)
    return res


class _EDT:
    """Raster distance field (0.05 mm) to a shapely region, for fast point lookups."""

    def __init__(self, g, bounds, res=0.05):
        from scipy.ndimage import distance_transform_edt
        x0, y0, x1, y1 = bounds
        self.x0, self.y0, self.res = x0, y0, res
        xs = np.arange(x0, x1 + res, res)
        ys = np.arange(y0, y1 + res, res)
        X, Y = np.meshgrid(xs, ys)
        inside = shapely.contains_xy(g, X.ravel(), Y.ravel()).reshape(X.shape) if not g.is_empty else np.zeros(X.shape, bool)
        self.d = distance_transform_edt(~inside) * res if inside.any() else np.full(X.shape, np.inf)

    def __call__(self, P):
        i = np.clip(np.round((P[:, 1] - self.y0) / self.res).astype(int), 0, self.d.shape[0] - 1)
        j = np.clip(np.round((P[:, 0] - self.x0) / self.res).astype(int), 0, self.d.shape[1] - 1)
        return self.d[i, j]


def _gcode_bridges(M, bodies, segs, off, cache) -> list[dict]:
    """Every 'Bridge infill' / 'Overhang perimeter' extrusion, attributed to a body, with
    * max_unsupported_run: longest stretch with no material of any body within 0.6 mm below the layer mid-height
      (the bridge span actually printed), and
    * max_dist_to_support / length beyond the rib reach: XY distance from the toolpath to that support (the
      rib-float criterion: a float is held up by the skid ribs 2 empty layers below)."""
    p = M.params
    bb = np.array([b.bounding_box() for b in bodies.values()])
    bounds = (bb[:, 0].min() - 2, bb[:, 1].min() - 2, bb[:, 3].max() + 2, bb[:, 4].max() + 2)
    reach = (RIB_PITCH_MAX - p.rib_w) / 2.0 + 0.05

    def layer(ztop):
        if ztop not in cache:
            zm = round(ztop - LAYER_H / 2, 4)
            cur = {}
            for k, b in bodies.items():
                g = shp(compose([b.slice(zm - 1e-4), b.slice(zm + 1e-4)]))
                shapely.prepare(g)
                cur[k] = g
            sup = []
            for dz in (0.2, 0.4, 0.6):
                if zm - dz > 0:
                    sup += [shp(b.slice(zm - dz)) for b in bodies.values()]
            sg = shapely.union_all(sup) if sup else shapely.Polygon()
            shapely.prepare(sg)
            cache[ztop] = (cur, sg, _EDT(sg, bounds))
        return cache[ztop]

    agg = {}
    for z, t, x0, y0, x1, y1, _w in segs:
        if t not in ("Bridge infill", "Overhang perimeter"):
            continue
        cur, sg, edt = layer(z)
        a = np.array([x0, y0]) - off
        b = np.array([x1, y1]) - off
        Lseg = float(np.hypot(*(b - a)))
        n = max(2, int(Lseg / 0.05) + 1)
        P = a + (b - a) * np.linspace(0, 1, n)[:, None]
        mid = shapely.Point(*(0.5 * (a + b)))
        body = min(cur, key=lambda k: cur[k].distance(mid))
        dsup = edt(P)
        unsup = dsup > 0.03
        run = best = 0
        for v in unsup:
            run = run + 1 if v else 0
            best = max(best, run)
        best_len = best * Lseg / (n - 1)
        key = (round(z, 2), t, body)
        r = agg.setdefault(key, {"layer_top_z": round(z, 2), "type": t, "body": body, "n": 0, "length_mm": 0.0,
                                 "unsupported_mm": 0.0, "max_unsupported_run": 0.0, "worst_line_model_xy": None,
                                 "max_dist_to_support": 0.0, "beyond_rib_reach_mm": 0.0})
        r["n"] += 1
        r["length_mm"] += Lseg
        r["unsupported_mm"] += Lseg * float(unsup.mean())
        r["max_dist_to_support"] = max(r["max_dist_to_support"], float(dsup.max()))
        r["beyond_rib_reach_mm"] += Lseg * float((dsup > reach).mean())
        if best_len > r["max_unsupported_run"]:
            r["max_unsupported_run"] = best_len
            r["worst_line_model_xy"] = rnd(np.r_[a, b], 2)
    out = []
    for key, r in sorted(agg.items()):
        for k2 in ("length_mm", "unsupported_mm", "beyond_rib_reach_mm"):
            r[k2] = round(r[k2], 1)
        r["max_unsupported_run"] = round(r["max_unsupported_run"], 2)
        r["max_dist_to_support"] = round(r["max_dist_to_support"], 2)
        cls, lim = _gcode_class(M, r)
        r["class"] = cls
        r["limit"] = lim
        if r["max_unsupported_run"] <= 2 * NOZZLE:
            r["status"] = "pass"                       # (internal) bridge resting on material below
        elif cls.startswith("rib_float"):
            r["rib_reach"] = round(reach, 2)
            # floats: judged like V9 - every toolpath point within the rib reach; long runs parallel to the
            # (arc) ribs are reported, not failed
            r["status"] = "fail" if r["beyond_rib_reach_mm"] > 2.0 else ("warn" if r["max_unsupported_run"] > RIB_PITCH_MAX else "pass")
        elif lim is None:
            r["status"] = "fail"
        else:
            r["status"] = "pass" if r["max_unsupported_run"] <= lim + 0.1 else "fail"
        out.append(r)
    return out


def _gcode_body_gaps(bodies, segs, off, step: float = 0.15) -> dict:
    """Printed separation of the bodies in the G-code: every extrusion (except sparse infill and skirt) is sampled,
    attributed to the body whose layer section contains it, and for every pair of bodies
    * XY: min over layers of (centre-line distance - half of both line widths) = the printed air gap;
    * Z: smallest layer offset at which their extrusions overlap in XY (offset 1 = stacked on the next layer, i.e.
      0 empty layers = fused)."""
    from scipy.spatial import cKDTree
    names = list(bodies)
    by_layer = defaultdict(list)
    for z, t, x0, y0, x1, y1, w in segs:
        if t in ("Internal infill", "Skirt/Brim", "Custom", None):
            continue
        by_layer[round(z, 2)].append((x0, y0, x1, y1, w))
    zs = sorted(by_layer)
    pts_layer = {}
    for z in zs:
        a = np.array(by_layer[z])
        P0 = a[:, :2] - off
        P1 = a[:, 2:4] - off
        L = np.hypot(*(P1 - P0).T)
        n = np.maximum(1, np.ceil(L / step).astype(int))
        idx = np.repeat(np.arange(len(a)), n + 1)
        tt = np.concatenate([np.linspace(0, 1, k + 1) for k in n])
        P = P0[idx] + (P1 - P0)[idx] * tt[:, None]
        W = a[idx, 4]
        zm = z - LAYER_H / 2
        owner = np.full(len(P), -1)
        for bi, k in enumerate(names):
            g = shp(compose([bodies[k].slice(zm - 1e-4), bodies[k].slice(zm + 1e-4)]))
            if g.is_empty:
                continue
            g = g.buffer(0.05)
            m = (owner < 0) & shapely.contains_xy(g, P[:, 0], P[:, 1])
            owner[m] = bi
        pts_layer[z] = (P, W, owner)
    out = {"method": "G-code extrusions sampled every 0.15 mm, attributed to bodies by the model layer sections",
           "pairs": {}}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            key = f"{names[i]}|{names[j]}"
            best = (math.inf, None, None)
            zmin_off = math.inf
            zat = None
            for li, z in enumerate(zs):
                P, W, o = pts_layer[z]
                A, B = P[o == i], P[o == j]
                if len(A) and len(B):
                    tB = cKDTree(B)
                    d, k2 = tB.query(A)
                    gap = d - 0.5 * (W[o == i] + W[o == j][k2])
                    m = int(np.argmin(gap))
                    if gap[m] < best[0]:
                        best = (float(gap[m]), z, rnd(0.5 * (A[m] + B[k2[m]]), 2))
                # stacking: this layer's body-i / body-j paths over the other body's paths 1..3 layers below
                for (ua, ub) in ((i, j), (j, i)):
                    U = P[o == ua]
                    if not len(U):
                        continue
                    Wu = W[o == ua]
                    for dk in (1, 2, 3):
                        if li - dk < 0:
                            break
                        P2, W2, o2 = pts_layer[zs[li - dk]]
                        D = P2[o2 == ub]
                        if not len(D):
                            continue
                        d, k2 = cKDTree(D).query(U)
                        if np.any(d < 0.5 * (Wu + W2[o2 == ub][k2]) - 0.05):
                            if dk < zmin_off:
                                zmin_off, zat = dk, (z, zs[li - dk])
                            break
            st = "pass" if best[0] >= XY_GAP_MIN - 0.02 else "fail"
            if zmin_off - 1 < EMPTY_LAYERS_MIN:
                st = "fail"
            out["pairs"][key] = {"min_printed_xy_gap": rnd(best[0], 3), "at_layer_top_z": best[1], "at_xy": best[2],
                                 "min_empty_layers": ">=3" if math.isinf(zmin_off) else int(zmin_off - 1),
                                 "stack_layers": zat, "status": st}
    return out


def _gcode_class(M, r):
    """Listed class for a bridge / overhang layer of the G-code (layer top z = model level + one layer)."""
    p = M.params
    z = r["layer_top_z"]
    b = r["body"]
    zl = p.z_lift if b != "frame" else 0.0

    def at(level):
        # PrusaSlicer slices at the layer mid-height: a body whose bottom is at `level` first appears in the layer
        # k with 0.2 k + 0.1 > level, whose top is 0.2 (k + 1)
        k = math.floor((level - LAYER_H / 2) / LAYER_H + 1e-9) + 1
        return abs(z - LAYER_H * (k + 1)) < 1e-6

    if b == "frame" and at(p.z_roof0):
        return "bridge:roof (leg channels)", SPAN["roof"]
    if b in ("wheel", "head") and at(p.bore_roof_z + zl):
        return "bridge:umbrella plate / bore roof", SPAN["umbrella_plate"] if b == "wheel" else max(SPAN["bore_roof"], p.bore_d)
    if b in ("wheel", "head") and at(p.z_band0 + zl):
        return "rib_float:back-plate ribs (run between rib tops)", RIB_PITCH_MAX
    if b == "head" and at(p.z_front0 + zl):
        return "rib_float:roof-top ribs (I3 front layer)", RIB_PITCH_MAX
    if r["type"] == "Overhang perimeter" and r["max_unsupported_run"] <= 2 * NOZZLE:
        return "overhang perimeter (short, <= 2 nozzle widths)", 2 * NOZZLE
    return "UNLISTED", None


# ============================================================================================ render
def _patch(ax, cs, **kw):
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath
    polys = cs.to_polygons() if isinstance(cs, CrossSection) else cs
    if not polys:
        return
    verts, codes = [], []
    for q in polys:
        q = np.asarray(q)
        if len(q) < 3:
            continue
        verts += list(q) + [q[0]]
        codes += [MPath.MOVETO] + [MPath.LINETO] * (len(q) - 1) + [MPath.CLOSEPOLY]
    if verts:
        ax.add_patch(PathPatch(MPath(verts, codes), **kw))


def render_overhang_map(M, bodies, v9, path: Path):
    """Top-view overhang maps, one panel per (body, Z level): listed bridges blue, rib floats green with the rib
    tops black, chamfer steps grey, 45-deg faces light green; parts beyond span/2 or the rib reach (and unlisted
    overhangs) red, drawn last.  The body outline at that level is drawn for orientation."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    groups = defaultdict(list)
    for r in v9["pieces"]:
        if "_cs" in r and r["class"] not in ("bed",):
            groups[(r["body"], r["z"])].append(r)
    keys = sorted([k for k, v in groups.items() if sum(r["area_mm2"] for r in v) > 5.0], key=lambda k: (k[0] != "frame", k[0], k[1]))
    n = max(1, len(keys))
    cols = min(3, n)
    rows = int(math.ceil(n / cols))
    fig, axs = plt.subplots(rows, cols, figsize=(7.2 * cols, 7.6 * rows), squeeze=False)
    lim45 = -math.sin(math.radians(OVERHANG_DEG + ANGLE_TOL_DEG))
    for ax, key in zip(axs.ravel(), keys):
        k, zz = key
        b = bodies[k]
        _patch(ax, b.slice(zz + 0.05), fc="#f3f3f3", ec="#8a8a8a", lw=0.4)
        if zz > 1.0:
            _patch(ax, compose([bodies[o].slice(zz - 0.05) for o in bodies if o != k]), fc="none", ec="#c084fc", lw=0.3)
        bad = []
        st = "pass"
        for r in groups[key]:
            cls = r["class"]
            fc = ("#9ca3af" if cls == "chamfer_micro_step" else "#22c55e" if cls.startswith("rib_float")
                  else "#3b82f6" if cls.startswith("bridge") else "#ef4444")
            _patch(ax, r["_cs"], fc=fc, ec="k", lw=0.3, alpha=0.5)
            if "_ribs" in r and not r["_ribs"].is_empty():
                _patch(ax, r["_ribs"], fc="#111111", ec="none", alpha=0.85)
            if not r["_bad"].is_empty():
                bad.append(r["_bad"])
            if r["status"] == "fail":
                st = "FAIL"
        for q in bad:
            _patch(ax, q, fc="#ef4444", ec="#7f1d1d", lw=0.8, alpha=0.95)
        ax.set_aspect("equal")
        ax.autoscale()
        ax.grid(True, lw=0.2)
        names = sorted({r["class"] for r in groups[key]})
        ax.set_title(f"{k} z {zz:g}: {', '.join(names)}  [{st}]", fontsize=8)
    for ax in axs.ravel()[len(keys):]:
        ax.axis("off")
    axs.ravel()[0].legend(handles=[Patch(color="#3b82f6", alpha=0.5, label="listed bridge"),
                                   Patch(color="#22c55e", alpha=0.5, label="rib-supported float"),
                                   Patch(color="#111111", label="rib tops under the float"),
                                   Patch(color="#9ca3af", label="chamfer micro-step"),
                                   Patch(color="#ef4444", label="UNSUPPORTED: > span/2 from anchors, > rib reach, unlisted"),
                                   Patch(facecolor="none", edgecolor="#c084fc", label="other bodies just below")],
                          loc="lower left", fontsize=7)
    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(path, dpi=70)
    plt.close(fig)


def render_overhang_3d(M, bodies, v9, path: Path) -> str | None:
    """OpenSCAD render seen from below: bodies translucent, overhang regions as coloured slabs."""
    if shutil.which("openscad") is None or shutil.which("xvfb-run") is None:
        return None
    from manifold3d import OpType
    from verify import save_stl
    cols = {"frame": "[0.80,0.80,0.80,0.25]", "wheel": "[0.5,0.7,1.0,0.25]", "head": "[1.0,0.75,0.8,0.25]"}
    sc = {"bridge": "[0.15,0.35,1.0,0.45]", "float": "[0.1,0.7,0.25,0.35]", "bad": "[0.95,0.05,0.05,1]"}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        lines = []
        slabs = {"bridge": [], "float": [], "bad": []}
        for r in v9["pieces"]:
            if "_cs" not in r or r["class"] in ("bed", "chamfer_micro_step"):
                continue
            zz = r["z"]
            key = "float" if r["class"].startswith("rib_float") else "bridge"
            slabs[key].append(r["_cs"].extrude(0.12).translate((0, 0, zz - 0.13)))
            if not r["_bad"].is_empty():
                slabs["bad"].append(r["_bad"].extrude(0.8).translate((0, 0, zz - 0.82)))
        for nm in ("bad", "bridge", "float"):
            lst = slabs[nm]
            if not lst:
                continue
            m = Manifold.batch_boolean(lst, OpType.Add) if len(lst) > 1 else lst[0]
            fpath = td / f"ov_{nm}.stl"
            save_stl(m, fpath)
            lines.append(f'color({sc[nm]}) import("{fpath}", convexity=10);')
        for k, b in bodies.items():
            fpath = td / f"{k}.stl"
            save_stl(b, fpath)
            lines.append(f'color({cols[k]}) import("{fpath}", convexity=10);')
        scad = td / "scene.scad"
        scad.write_text("\n".join(lines) + "\n")
        cmd = ["xvfb-run", "-a", "openscad", "-o", str(path), "--imgsize=1400,1000", "--colorscheme=Tomorrow",
               "--camera=0,0,0,145,0,200,0", "--viewall", "--autocenter", "--projection=p", str(scad)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        except Exception as ex:  # pragma: no cover
            return f"render failed: {ex!r}"
    return str(path)


def _public(o):
    """Strip private (geometry) keys before JSON export."""
    if isinstance(o, dict):
        return {k: _public(v) for k, v in o.items() if not str(k).startswith("_")}
    if isinstance(o, (list, tuple)):
        return [_public(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return rnd(o, 6)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


# ============================================================================================ findings
def build_findings(rep: dict) -> list[dict]:
    """Short, actionable list of the failing / warning items with a proposed fix (generic per check type)."""
    c = rep["checks"]
    F = []

    def add(sev, check, what, fix, evidence=None):
        F.append({"severity": sev, "check": check, "finding": what, "proposed_fix": fix, "evidence": evidence})

    w = c.get("V8_walls_layers", {})
    walls = w.get("structural_thin_walls", [])
    if walls:
        zones = sorted({x["zone"] for x in walls})
        wmin = min(x["w_min"] for x in walls)
        zr = [min(x["z"] for x in walls), max(x["z"] for x in walls)]
        add("fail", "V8 walls", f"structural thin walls (zones {zones}) down to {wmin} mm at z {zr[0]}-{zr[1]} "
            f"(e.g. {walls[0]['xy']} z {walls[0]['z']})",
            "funnel seat: lower every fill tongue narrower than 3.8 mm inside r 17.5 about O to z 8.2 "
            "(frame -= extrude((Fill2D n disc(O,17.5)) - open_3.8(Fill2D), 8.2, 10.5)) so the 45 deg keep-out cone can "
            "no longer thin it below 1.2", walls[:4])
    sp = c.get("V8_stop_pads", {})
    if sp.get("status") == "fail":
        add("fail", "V8 stop pads", f"stop pads are 0.6 thick and {sp['worst_unbacked_fin_length']} mm of a pad stands "
            "free of the fill wall (thin banking-stop fin, can snap into the escapement)",
            "core2d: clip each pad to the fill it is glued to, pad = pad n (raw_fill (+) 0.6), before the union",
            [x for x in sp.get("pads", []) if x["unbacked_area_mm2"] > 0.01])
    v9 = c.get("V9_overhangs", {})
    for r in v9.get("unlisted_or_failed", []):
        if r["class"].startswith("bridge:roof"):
            fix = ("the roof lobes over the face base are anchored on one side only: give them a rib-supported float "
                   "(0.8 x 0.6 skid ribs on the head-band top z 7.4-8.0, arcs about P at pitch <= 4.5, clipped to "
                   "HeadBand2D n SweptInv(Roof2D) and kept clear of SweptInv(disc(O, 18.6)), roof 0.40 above them) or "
                   "trim Roof2D to (Fill2D (+) 6.5) and re-run V11 captivity")
        elif r["class"].startswith("rib_float:roof"):
            fix = ("extend the roof-top rib field to the roof edge (an outline-following rib 1.0-1.8 inside Body2D, "
                   "protected from the r 1.0 edge round) and add a ~1 mm 45 deg corbel to the I3 slot ceiling along the "
                   "FaceMid wall so no point of the front layer is > 1.9 mm from a rib or wall; changing psi_print "
                   "does not help (unsupported area 26-28 mm^2 for psi -4..8)")
        elif r["class"].startswith("rib_float"):
            fix = "add rib arcs / extend the rib clip so every point of the float is within (pitch - rib_w)/2 of a rib"
        elif r["class"].startswith("bridge"):
            fix = "reduce the span or add anchors"
        else:
            fix = "make it self-supporting (<= 45 deg), a listed bridge or a rib-supported float"
        add("fail", "V9 overhang", f"{r['body']} z {r['z']} {r['class']}: " + "; ".join(r["notes"]), fix,
            {"area_mm2": r["area_mm2"], "centroid": r["centroid"],
             "regions": r.get("beyond_half_span_regions") or r.get("unsupported_regions")})
    sl = c.get("SLICER", {})
    for tag, run in (sl.get("runs") or {}).items():
        bad = [b for b in run.get("bridges", []) if b["status"] == "fail"]
        if bad:
            add("fail", f"SLICER {tag}", "PrusaSlicer toolpaths confirm: " + "; ".join(
                (f"layer {b['layer_top_z']} {b['body']} {b['type']} ({b['class']}): {b['beyond_rib_reach_mm']} mm of "
                 f"path farther than {b.get('rib_reach')} from any rib / anchor (max {b['max_dist_to_support']})")
                if b["class"].startswith("rib_float") else
                (f"layer {b['layer_top_z']} {b['body']} {b['type']} ({b['class']}): longest unsupported strand "
                 f"{b['max_unsupported_run']} mm (limit {b['limit']}) at {b['worst_line_model_xy']}") for b in bad),
                "see the V9 fixes", None)
        if run.get("warnings"):
            add("warn", f"SLICER {tag}", "slicer warnings: " + " / ".join(run["warnings"]),
                "per-body attribution in SLICER.warnings_per_body_alone (floats -> 'Floating object part' / 'Loose "
                "extrusions' are inherent to print-in-place; 'Long bridging extrusions' come from the V9 failures)",
                sl.get("warnings_per_body_alone"))
        for b in run.get("bridges", []):
            if b["status"] == "warn":
                add("warn", f"SLICER {tag}", f"layer {b['layer_top_z']} {b['body']} {b['type']}: strands run up to "
                    f"{b['max_unsupported_run']} mm parallel to the arc ribs (all within {b['max_dist_to_support']} mm of a rib)",
                    "optional: straight parallel skid ribs + a fixed bridge_angle in the 3MF volume config", None)
    lc = c.get("LAYER_quantisation", {})
    if lc.get("float_bottom_quantisation", {}).get("status") == "warn":
        add("warn", "LAYER", lc["float_bottom_quantisation"]["note"],
            "use z_lift = 0.2 (one layer) for the loose variant, or state that it only widens XY gaps", None)
    for k in ("V8_back_plate", "V8_roof", "V8_legs"):
        v = c.get(k, {})
        if v.get("status") == "warn":
            add("warn", k, v.get("note", ""), "spec conflict / edge geometry - no change needed", None)
    return F


# ============================================================================================ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skin", default="kitty")
    ap.add_argument("--variant", default="nominal")
    ap.add_argument("--rays", type=int, default=12000, help="ray samples per body (SPEC >= 2000)")
    ap.add_argument("--no-slicer", action="store_true")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--keep-gcode", action="store_true")
    ap.add_argument("--out", default=None, help="report directory (default verification/reports/<skin>)")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    t_start = time.time()

    def log(msg):
        if not a.quiet:
            print(f"[v_printability {time.time() - t_start:6.1f}s] {msg}", flush=True)

    M = build(skin=a.skin, variant=a.variant)
    p = M.params
    bodies = M.print_pose()
    suffix = "" if a.variant == "nominal" else f"_{a.variant}"
    outdir = Path(a.out) if a.out else REPO / "verification" / "reports" / a.skin
    outdir.mkdir(parents=True, exist_ok=True)
    rep = {"skin": a.skin, "variant": a.variant, "pose": {"phi": p.phi_print, "psi": p.psi_print},
           "z_lift": p.z_lift, "checks": {}}
    log(f"built {a.skin}/{a.variant}, print pose ({p.phi_print}, {p.psi_print})")

    # exported files (or temporary exports of the current model when the deliverable does not exist)
    stl_dir = REPO / "stl" / a.skin
    stl_path = stl_dir / f"purrbobble_{a.skin}_{a.variant}.stl"
    mf_path = stl_dir / f"purrbobble_{a.skin}_{a.variant}.3mf"
    tmpdir = Path(tempfile.mkdtemp(prefix="v_print_"))
    exported = {"stl": str(stl_path) if stl_path.exists() else None, "3mf": str(mf_path) if mf_path.exists() else None}
    if not stl_path.exists():
        stl_path = tmpdir / f"model_{a.skin}_{a.variant}.stl"
        write_stl(stl_path, bodies)
    if not mf_path.exists():
        mf_path = tmpdir / f"model_{a.skin}_{a.variant}.3mf"
        write_3mf(mf_path, bodies, name=f"purrbobble_{a.skin}_{a.variant}")
    rep["files"] = {"exported": exported, "used_stl": str(stl_path), "used_3mf": str(mf_path)}

    zoner = Zoner(M)
    thinmaps = {k: ThinMap(b, WALL_MIN) for k, b in bodies.items()}
    z_top = max(b.bounding_box()[5] for b in bodies.values())
    L = Layers(bodies, z_top)
    log(f"sliced {L.n} layers")

    # ---------------- V8
    topo = v8_topology(M, bodies, Path(exported["stl"]) if exported["stl"] else None,
                       Path(exported["3mf"]) if exported["3mf"] else None)
    rep["checks"]["V8_topology"] = {"status": "pass" if topo["pass"] else "fail", **topo}
    log(f"V8 topology {rep['checks']['V8_topology']['status']}")
    rays = v8_walls_rays(M, bodies, zoner, max(2000, a.rays), thinmaps)
    rep["checks"]["V8_walls_raycast"] = rays
    log(f"V8 ray walls {rays['status']}")
    lw = v8_layer_widths(M, L, zoner, thinmaps)
    rep["checks"]["V8_walls_layers"] = lw
    log(f"V8 layer widths {lw['status']}")
    spc = v8_specifics(M, bodies, zoner)
    for k, v in spc.items():
        rep["checks"][f"V8_{k}"] = v
    sl3 = v8_slivers_3d(M, L, zoner)
    rep["checks"]["V8_slivers_frame_layers"] = sl3
    log("V8 specifics " + ", ".join(f"{k}:{v['status']}" for k, v in spc.items()) + f", slivers3d:{sl3['status']}")

    # ---------------- V9
    v9 = v9_overhangs(M, bodies, L)
    rep["checks"]["V9_overhangs"] = v9
    log(f"V9 overhangs {v9['status']} ({len(v9['unlisted_or_failed'])} failing regions)")
    if not a.no_render:
        try:
            png = outdir / f"printability_overhang{suffix}.png"
            render_overhang_map(M, bodies, v9, png)
            v9["render_2d"] = str(png)
            r3 = render_overhang_3d(M, bodies, v9, outdir / f"printability_overhang3d{suffix}.png")
            v9["render_3d"] = r3
            log("overhang renders written")
        except Exception as ex:  # pragma: no cover
            v9["render_error"] = repr(ex)

    # ---------------- LAYER
    lc = layer_check(M, L)
    rep["checks"]["LAYER_quantisation"] = lc
    log(f"layer check {lc['status']}")

    # ---------------- SLICER
    if a.no_slicer:
        rep["checks"]["SLICER"] = {"status": "not-run", "note": "--no-slicer"}
    else:
        sc = slicer_check(M, bodies, stl_path, mf_path, tmpdir, a.keep_gcode)
        rep["checks"]["SLICER"] = sc
        log(f"slicer {sc['status']}")
    if not a.keep_gcode:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # ---------------- summary
    summ = {k: v.get("status") for k, v in rep["checks"].items()}
    rep["summary"] = summ
    rep["findings"] = build_findings(rep)
    rep["pass"] = all(s in ("pass", "warn", "not-run") for s in summ.values())
    rep["runtime_s"] = round(time.time() - t_start, 1)
    path = outdir / f"printability{suffix}.json"
    path.write_text(json.dumps(_public(rep), indent=1, default=str))
    log(f"report -> {path}")
    for k, s in summ.items():
        log(f"  {k:28s} {s}")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
