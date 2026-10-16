"""Check group D - child safety, pinch points, renders and character design (SPEC section 5: V10, V12, V14).

    python3 verification/v_safety.py --skin kitty [--variant nominal] [--probe 2.0] [--no-render] [--fast] [-q]

Writes verification/reports/<skin>/safety.json (safety_<variant>.json for other variants), diagnostic plots
verification/reports/<skin>/safety_<variant>_*.png, and (unless --no-render) the V14 renders
renders/<skin>/v14_<skin>_<variant>_*.png.  Exits non-zero if any check FAILS (warnings do not fail).
Independent of the builder's own checks: only the documented Model API (build, posed / head_at / wheel_at,
params, 2-D sections) plus exact manifold3d slicing / booleans, shapely and scipy are used.

V10  Small parts.
     * Every body: smallest enclosing-cylinder diameter over all orientations (min over axis directions of the
       minimum enclosing circle of the projection, 2000 directions + local refinement) and the small-parts
       cylinder test (D 31.7, depth 25.4 / 57.1).  Wheel >= 35.5, head >= 38, no body fits.
     * Every breakable protrusion, found from the geometry (not from the skin's own description):
         - vertical: knob (wheel), every frame part standing >= 3 mm above the body top (paws ...), posts;
         - in-plane: lobes of the head plan narrower than 20 mm (ears, antennae ...) and of the frame body plan
           narrower than 12 mm (tail, feet ...), minus anything hidden inside the frame body (head legs);
         - the 2 mm back-plate panel that carries the head post and lies under the head (warn level).
       The root section is measured by slicing the real solid (horizontal slices for vertical protrusions,
       vertical planes along the protrusion axis for in-plane ones).  Root >= 8 x 5 and the beam-theory bending
       stress for 50 N applied at the tip in the worst lateral direction < 10 MPa at every station.  The size of
       the fragment if the protrusion snapped at its root is reported (does it fit the small-parts cylinder?).
V12  Pinch audit.  Every moving boundary point (head and wheel slices every 0.5 mm in Z, 0.3 mm along the
     outline) is tracked over the motion against the other bodies in the SAME Z slice (exact nearest distance,
     only material in front of the moving surface counts).  Accessibility: a probe of radius --probe (2.0 mm,
     i.e. a 4 mm fingertip / nail edge) is flooded down from above the toy and in from the sides on 0.25 mm
     rasters of every Z slice (2.5-D flood); a moving point counts as exposed if the probe can touch it at any
     pose.  Rule (SPEC V12): each exposed gap is constant (variation <= 0.1), or stays < 2.0, or stays >= 12;
     nothing may vary across the 2-12 mm band.  Motions: head psi -psi_b..+psi_b (wheel knob near / away from
     the chin) and wheel phi 0..360 (head at -psi_b, 0, +psi_b).
     Edge radii / sharp points: (a) convex plan corners of the exposed outer outlines (2-D opening test,
     exterior r >= 1.5, any edge r >= 1.0); (b) sharp points: the fraction of a 1.0 mm ball around a surface point
     that is inside the solid (flat 0.50, square edge 0.25, square corner 0.125, knife edges / needles less),
     evaluated at every convex mesh vertex of the exposed outer surface (de-duplicated on a 0.5 mm grid);
     < 0.15 is a sharp point, 0.15-0.20 a warning.
V14  Renders (OpenSCAD on exported meshes): front, back, three-quarter at psi = -12.4 / 0 / +12.4 with the wheel at
     three angles, sections at x = 0 and z = 5.2.
Design review (warn level, numbers measured on the solids): face-feature heights and line widths (raised >= 0.6,
grooves / lines >= 0.8 wide, debosses >= 0.4 deep = 2 layers), eye size and placement versus the face,
head / ball size ratio, ear proportions, colour-swap side effects, giggle amplitude at the ear tips.

Sculpt skins (purrbobble/sculpt.py: frame and head cut from a sculpted mesh; no roof, knob, face layers, paws or
decor in the bodies, although the sections still hold them) are judged on what is built instead:
    * V10: the protrusion above the umbrella is the sculpted cap (dish drive); the frame's towers are the parts that
      stand >= 3 mm above where they merge into the organic body (prominence, no body-top plane); the head's lobes
      are hidden only where the frame lies over them (legs under the chest), lobes < 3 mm long are outline bumps
      (listed, not analysed), and a lobe's sections leave out slivers of other parts of the body that the plane
      also cuts (< 1 mm2 and < 5 %; the all-pieces stress is kept in the record); the back-plate panel keeps the
      holes of the body's plan (the cushion encloses it) and only the panel under the head is checked; plus
      V10.static_ring, the yarn ball's static ring over the umbrella (thickness >= 2.0, warn level);
    * V12: corners must persist 0.5 above or below (vertical edges); a single-slice corner where a seam crosses the
      sloping surface is left to the sharp-point test; pinch fixes are sculpt-specific;
    * design review: no face / paw / decor planes (the scans run on the back plate and the umbrella top only); eyes,
      nose, ears and the colour swap are 'n/a' (the owner's single-colour sculpt); head vs ball uses the head's blob
      and the visible 36 mm yarn ball; V14 renders tint the head to set it off from the frame.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import shapely  # noqa: E402
from manifold3d import CrossSection, JoinType, Manifold  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from scipy import ndimage  # noqa: E402
from scipy.optimize import minimize  # noqa: E402
from scipy.spatial import ConvexHull, cKDTree  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402

from purrbobble import geom2d as g2  # noqa: E402
from purrbobble.model import build  # noqa: E402

# --------------------------------------------------------------------------------------------- criteria
SPEC = {
    "cyl_d": 31.7,              # small-parts cylinder (16 CFR 1501 / EN 71-1)
    "cyl_depth_short": 25.4,
    "cyl_depth_long": 57.1,
    "wheel_min_width": 35.5,
    "head_min_width": 38.0,
    "root_long": 8.0,           # protrusion root >= 8 x 5
    "root_short": 5.0,
    "load_N": 50.0,             # lateral test load
    "stress_max": 10.0,         # MPa
    "pinch_const": 0.1,         # gap variation <= 0.1 counts as constant
    "pinch_lo": 2.0,            # < 2.0 always: slit
    "pinch_hi": 12.0,           # >= 12 always: too wide to trap
    "edge_r_ext": 1.5,          # exterior plan corners
    "edge_r_min": 1.0,          # every edge
    "sharp_fail": 0.15,         # ball volume fraction
    "sharp_warn": 0.20,
    "feat_raise_min": 0.6,
    "feat_line_min": 0.8,
    "feat_deboss_min": 0.4,
}
LAYER = 0.2
NOZZLE = 0.4


# --------------------------------------------------------------------------------------------- helpers
def r4(x):
    if x is None:
        return None
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return round(x, 4) if math.isfinite(x) else str(x)
    return x


def rl(v, n=3):
    return [round(float(a), n) for a in v]


class Report:
    def __init__(self, quiet: bool):
        self.checks = []
        self.quiet = quiet
        self.t0 = time.time()

    def log(self, msg: str):
        if not self.quiet:
            print(f"[{time.time() - self.t0:6.1f}s] {msg}", flush=True)

    def add(self, cid: str, name: str, status: str, measured, criterion: str, **details):
        rec = {"id": cid, "name": name, "status": status, "measured": measured, "criterion": criterion}
        rec.update(details)
        self.checks.append(rec)
        self.log(f"{cid:30s} {status.upper():5s} {name}: {measured}")
        return rec


def status(ok: bool, warn: bool = False) -> str:
    return "fail" if not ok else ("warn" if warn else "pass")


def cs_contours(cs: CrossSection) -> list[np.ndarray]:
    return [np.asarray(c, dtype=float) for c in cs.to_polygons() if len(c) >= 3]


def signed_area(a: np.ndarray) -> float:
    x, y = a[:, 0], a[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))


def to_shp(cs: CrossSection):
    """CrossSection -> shapely (Multi)Polygon (robust to empty pieces)."""
    polys = []
    for q in cs.decompose():
        rings = [np.asarray(c, float) for c in q.to_polygons() if len(c) >= 3]
        if not rings:
            continue
        areas = [signed_area(r) for r in rings]
        i0 = int(np.argmax(areas))
        if areas[i0] <= 0:
            continue
        holes = [rings[i] for i in range(len(rings)) if i != i0 and areas[i] < 0]
        pg = Polygon(rings[i0], holes)
        if not pg.is_valid:
            pg = pg.buffer(0)
        polys.append(pg)
    if not polys:
        return Polygon()
    return shapely.union_all(polys)


def rot2(pts: np.ndarray, deg: float, pivot=(0.0, 0.0)) -> np.ndarray:
    if not deg:
        return np.array(pts, dtype=float, copy=True)
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    q = np.asarray(pts, float) - pivot
    return np.stack([c * q[:, 0] - s * q[:, 1], s * q[:, 0] + c * q[:, 1]], axis=1) + pivot


def disc(c, r, n=96) -> CrossSection:
    return CrossSection.circle(r, n).translate((float(c[0]), float(c[1])))


def mesh_np(m: Manifold):
    mm = m.to_mesh()
    return np.asarray(mm.vert_properties, dtype=float)[:, :3], np.asarray(mm.tri_verts, dtype=np.int64)


# --------------------------------------------------------------------------------------------- section props
def poly_props(cs: CrossSection) -> dict | None:
    """Area, centroid and second moments of a CrossSection (Green's theorem over all contours)."""
    A = Sx = Sy = Ixx = Iyy = Ixy = 0.0
    pts_all = []
    for c in cs_contours(cs):
        x, y = c[:, 0], c[:, 1]
        x1, y1 = np.roll(x, -1), np.roll(y, -1)
        cr = x * y1 - x1 * y
        A += cr.sum() / 2
        Sx += ((x + x1) * cr).sum() / 6
        Sy += ((y + y1) * cr).sum() / 6
        Iyy += ((x * x + x * x1 + x1 * x1) * cr).sum() / 12     # integral x^2
        Ixx += ((y * y + y * y1 + y1 * y1) * cr).sum() / 12     # integral y^2
        Ixy += ((x * y1 + 2 * x * y + 2 * x1 * y1 + x1 * y) * cr).sum() / 24
        pts_all.append(c)
    if A <= 1e-9:
        return None
    cx, cy = Sx / A, Sy / A
    return {"A": A, "c": (cx, cy), "Ixx": Ixx - A * cy * cy, "Iyy": Iyy - A * cx * cx, "Ixy": Ixy - A * cx * cy,
            "pts": np.vstack(pts_all)}


def max_bending_stress(props: dict, M: float, n_dir: int = 72) -> tuple[float, float]:
    """Worst normal stress (MPa for N, mm) over moment-vector directions in the section plane (unsymmetric
    bending formula).  Returns (sigma_max, worst moment-vector angle deg)."""
    Ixx, Iyy, Ixy = props["Ixx"], props["Iyy"], props["Ixy"]
    det = Ixx * Iyy - Ixy * Ixy
    q = props["pts"] - np.asarray(props["c"])
    best, best_a = 0.0, 0.0
    for a in np.linspace(0, 180, n_dir, endpoint=False):
        Mx, My = M * math.cos(math.radians(a)), M * math.sin(math.radians(a))
        # sigma = [(Mx Iyy + My Ixy) y - (My Ixx + Mx Ixy) x] / det    (moment vector (Mx, My))
        s = np.abs(((Mx * Iyy + My * Ixy) * q[:, 1] - (My * Ixx + Mx * Ixy) * q[:, 0]) / det).max()
        if s > best:
            best, best_a = float(s), float(a)
    return best, best_a


def caliper_dims(pts: np.ndarray) -> tuple[float, float]:
    """(min width, width perpendicular to it) of a 2-D point set (rotating calipers on the hull)."""
    if len(pts) < 3:
        return 0.0, 0.0
    try:
        h = pts[ConvexHull(pts).vertices]
    except Exception:
        return 0.0, 0.0
    best = (math.inf, 0.0)
    for i in range(len(h)):
        e = h[(i + 1) % len(h)] - h[i]
        L = np.linalg.norm(e)
        if L < 1e-9:
            continue
        e = e / L
        n = np.array([-e[1], e[0]])
        w = np.ptp(h @ n)
        if w < best[0]:
            best = (float(w), float(np.ptp(h @ e)))
    return best


# --------------------------------------------------------------------------------------------- V10 bodies
def _circ2(a, b):
    c = (a + b) / 2
    return c, float(np.linalg.norm(a - c))


def _circ3(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        # collinear: the circle on the two farthest points
        pts = [a, b, c]
        best = max(((pts[i], pts[j]) for i in range(3) for j in range(i + 1, 3)),
                   key=lambda t: np.linalg.norm(t[0] - t[1]))
        return _circ2(*best)
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    o = np.array([ux, uy])
    return o, float(np.linalg.norm(a - o))


def mec(pts: np.ndarray, seed: int = 0) -> float:
    """Diameter of the minimum enclosing circle (Welzl, iterative, on the convex hull)."""
    try:
        pts = pts[ConvexHull(pts).vertices]
    except Exception:
        pass
    rng = np.random.default_rng(seed)
    P = pts[rng.permutation(len(pts))]
    eps = 1e-9
    c, r = P[0], 0.0
    for i in range(1, len(P)):
        if np.linalg.norm(P[i] - c) > r + eps:
            c, r = P[i], 0.0
            for j in range(i):
                if np.linalg.norm(P[j] - c) > r + eps:
                    c, r = _circ2(P[i], P[j])
                    for k in range(j):
                        if np.linalg.norm(P[k] - c) > r + eps:
                            c, r = _circ3(P[i], P[j], P[k])
    return 2 * r


def _basis(a: np.ndarray):
    a = a / np.linalg.norm(a)
    t = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(a, t)
    u /= np.linalg.norm(u)
    return a, u, np.cross(a, u)


def cylinder_fit(m: Manifold, n_dir: int = 2000) -> dict:
    """min over axis directions a of MEC(projection onto the plane normal to a); length along a."""
    hv, _ = mesh_np(m.hull())

    def f(a):
        a, u, v = _basis(np.asarray(a, float))
        q = np.stack([hv @ u, hv @ v], axis=1)
        return mec(q), float(np.ptp(hv @ a))

    i = np.arange(n_dir) + 0.5
    zc = 1 - i / n_dir                                 # hemisphere (a and -a are the same axis)
    th = math.pi * (1 + 5 ** 0.5) * i
    dirs = np.stack([np.sqrt(1 - zc * zc) * np.cos(th), np.sqrt(1 - zc * zc) * np.sin(th), zc], axis=1)
    dirs = np.vstack([dirs, np.eye(3)])
    vals = np.array([f(a)[0] for a in dirs])
    order = np.argsort(vals)[:4]
    best = (vals[order[0]], dirs[order[0]])

    def sph(t):
        return np.array([math.sin(t[0]) * math.cos(t[1]), math.sin(t[0]) * math.sin(t[1]), math.cos(t[0])])

    for k in order:
        a = dirs[k]
        t0 = [math.acos(np.clip(a[2], -1, 1)), math.atan2(a[1], a[0])]
        res = minimize(lambda t: f(sph(t))[0], t0, method="Nelder-Mead",
                       options={"xatol": 1e-4, "fatol": 1e-5, "maxiter": 200})
        if res.fun < best[0]:
            best = (float(res.fun), sph(res.x))
    d_min, a_best = best
    _, L = f(a_best)
    # also: is there ANY axis with MEC <= 31.7?  (then report the shortest such length)
    fits_any = [(v, f(a)[1]) for v, a in zip(vals, dirs) if v <= SPEC["cyl_d"]] + [(d_min, L)]
    Lmin_fit = min((x[1] for x in fits_any if x[0] <= SPEC["cyl_d"]), default=None)
    return {"min_enclosing_d": round(float(d_min), 3), "axis": rl(a_best, 4), "length_along_axis": round(float(L), 3),
            "fits_short_cylinder": bool(d_min <= SPEC["cyl_d"] and (Lmin_fit or 1e9) <= SPEC["cyl_depth_short"]),
            "fits_long_cylinder": bool(d_min <= SPEC["cyl_d"] and (Lmin_fit or 1e9) <= SPEC["cyl_depth_long"])}


def silhouette(m: Manifold) -> CrossSection:
    """Plan silhouette (projection along Z) with every hole filled."""
    outer = [c for c in cs_contours(m.project()) if signed_area(c) > 0]
    return CrossSection([[tuple(p) for p in c] for c in outer]) if outer else CrossSection()


def plan_dims(m: Manifold) -> tuple[float, float]:
    pts = np.vstack(cs_contours(m.project()))
    return caliper_dims(pts)


def fragment_fit(m: Manifold) -> dict:
    """Would this piece (a snapped-off protrusion) fit the small-parts cylinder?"""
    if m.is_empty() or m.volume() < 1e-3:
        return {"volume_mm3": 0.0}
    cf = cylinder_fit(m, n_dir=600)
    return {"volume_mm3": round(float(m.volume()), 1), "min_enclosing_d": float(cf["min_enclosing_d"]),
            "length_along_axis": cf["length_along_axis"],
            "fits_small_parts_cylinder": bool(cf["fits_short_cylinder"] or cf["fits_long_cylinder"])}


# --------------------------------------------------------------------------------------------- V10 protrusions
def _stress_record(name, kind, body_name, stations, root_dims, L, F, fragment, notes=""):
    smax = max((st["sigma_MPa"] for st in stations), default=0.0)
    worst = max(stations, key=lambda st: st["sigma_MPa"]) if stations else None
    d_long, d_short = max(root_dims), min(root_dims)
    ok_root = d_long >= SPEC["root_long"] - 1e-6 and d_short >= SPEC["root_short"] - 1e-6
    ok_s = smax < SPEC["stress_max"]
    return {"name": name, "kind": kind, "body": body_name, "root_dims_mm": [round(d_long, 2), round(d_short, 2)],
            "root_ok": bool(ok_root), "length_mm": round(L, 2), "load_N": F, "sigma_max_MPa": round(smax, 2),
            "stress_ok": bool(ok_s), "worst_station": worst, "fragment_if_snapped": fragment,
            "stations": stations, "notes": notes}


def vertical_protrusion(name, body_name, body: Manifold, region: CrossSection, z0: float, z_top: float,
                        F: float, notes: str = "", layer_note: str = "interlayer (Z) tension") -> dict:
    """Protrusion standing up in +Z: horizontal sections z0 .. z_top - 1, tip load F (horizontal) at z_top."""
    stations = []
    zs = np.arange(z0, z_top - 0.99, 0.25)
    root_dims = (0.0, 0.0)
    for k, z in enumerate(zs):
        sec = body.slice(float(z))
        sec = sec ^ region
        pr = poly_props(sec)
        if pr is None:
            continue
        Mz = F * (z_top - z)
        sg, ang = max_bending_stress(pr, Mz)
        dims = caliper_dims(pr["pts"])
        if k == 0:
            root_dims = dims
        stations.append({"z": round(float(z), 2), "area_mm2": round(pr["A"], 2), "dims_mm": rl(dims, 2),
                         "moment_Nmm": round(Mz, 1), "sigma_MPa": round(sg, 3)})
    frag = fragment_fit(body ^ region.extrude(z_top - z0 + 2.0).translate((0, 0, z0)))
    return _stress_record(name, "vertical", body_name, stations, root_dims, z_top - z0, F, frag,
                          notes + f"; stress direction: {layer_note}")


def _plane_section(body: Manifold, c, n) -> CrossSection:
    """Section of `body` by the vertical plane through c (xy) with horizontal normal n.  Returned in (u, v)
    coordinates, u along e = (-n_y, n_x) from c, v = z ... as CrossSection (x' = -z, y' = u)."""
    th = math.degrees(math.atan2(n[1], n[0]))
    m = body.translate((-float(c[0]), -float(c[1]), 0.0)).rotate((0.0, 0.0, -th)).rotate((0.0, -90.0, 0.0))
    return m.slice(0.0)


def inplane_protrusions(body_name: str, body: Manifold, plan: CrossSection, t_open: float, F: float,
                        hidden: CrossSection | None = None, min_area: float = 4.0, label: str = "",
                        min_len: float = 0.0, drop_slivers: bool = False) -> list[dict]:
    """Lobes of `plan` narrower than t_open.  Lobes mostly inside `hidden` and lobes protruding less than min_len
    from the opened outline (bumps of an organic outline: nothing to grip) are listed but not analysed.
    drop_slivers: sliver pieces of a station's section (< 1 mm2, < 5 %) are left out (sculpt skins)."""
    core = g2.opening(plan, t_open, 0.02)
    prot = g2.difference(plan, g2.grow(core, 0.05, 0.02))
    core_shp = to_shp(core)
    out = []
    for q in prot.decompose():
        if q.area() < min_area:
            continue
        piece = to_shp(q)
        cen = piece.centroid
        if hidden is not None:
            fr = (to_shp(q ^ hidden).area if not (q ^ hidden).is_empty() else 0.0) / q.area()
            if fr > 0.5:
                out.append({"name": f"{label}lobe@({cen.x:.1f},{cen.y:.1f})", "kind": "in-plane", "body": body_name,
                            "hidden": True, "hidden_fraction": round(fr, 2),
                            "notes": "inside the frame body footprint (not graspable)"})
                continue
        # root chord = part of the piece boundary on the opened core's boundary
        ring = np.asarray(piece.exterior.coords) if piece.geom_type == "Polygon" else \
            np.asarray(max(piece.geoms, key=lambda g: g.area).exterior.coords)
        seg = ring[1:] - ring[:-1]
        nseg = np.maximum(1, np.ceil(np.linalg.norm(seg, axis=1) / 0.1)).astype(int)
        bpts = np.vstack([ring[i] + np.outer(np.linspace(0, 1, k, endpoint=False), seg[i]) for i, k in enumerate(nseg)])
        d = shapely.distance(shapely.points(bpts), core_shp)
        rootp = bpts[d < 0.25]
        if len(rootp) < 2:
            continue
        try:
            hpts = rootp[ConvexHull(rootp).vertices]
        except Exception:
            hpts = rootp
        D = np.linalg.norm(hpts[:, None] - hpts[None], axis=2)
        i, j = np.unravel_index(np.argmax(D), D.shape)
        a, b = hpts[i], hpts[j]
        m = (a + b) / 2
        e = (b - a) / max(np.linalg.norm(b - a), 1e-9)
        n = np.array([-e[1], e[0]])
        if np.dot(np.array([cen.x, cen.y]) - m, n) < 0:
            n = -n
        e = np.array([-n[1], n[0]])
        proj = (bpts - m) @ n
        L = float(proj.max())
        if L < 1.0:
            continue
        if L < min_len:
            out.append({"name": f"{label}lobe@({cen.x:.1f},{cen.y:.1f})", "kind": "in-plane", "body": body_name,
                        "too_short": True, "length_mm": round(L, 2), "area_mm2": round(q.area(), 2),
                        "notes": f"protrudes only {L:.2f} mm from the opened outline (< {min_len}): a bump of the "
                                 "sculpted outline, too short to grip (not analysed)"})
            continue
        tip = bpts[np.argmax(proj)]
        stations = []
        root_dims = (0.0, 0.0)
        big = piece.buffer(0.3)
        for k, s_ in enumerate(np.linspace(0.0, 0.8 * L, 9)):
            c = m + s_ * n
            line = LineString([c - 200 * e, c + 200 * e]).intersection(big)
            if line.is_empty:
                continue
            us = (np.asarray(shapely.get_coordinates(line)) - c) @ e
            u0, u1 = float(us.min()), float(us.max())
            clip = CrossSection.square((400.0, u1 - u0 + 0.6)).translate((-200.0, u0 - 0.3))
            sec = _plane_section(body, c, n) ^ clip
            extra = {}
            if drop_slivers:
                # (sculpt) the plane also cuts slivers of other parts of the body (the thin edge of the head's low
                # floors under a lobe): tiny pieces far from the lobe's own section that carry nothing but would set
                # the extreme-fibre distance.  Pieces < 1 mm2 and < 5 % of the section are dropped (never the
                # largest); the all-pieces stress is kept for reference
                pcs = sec.decompose()
                tot = sum(q.area() for q in pcs)
                keep = [q for q in pcs if q.area() >= 1.0 or q.area() >= 0.05 * tot or q.area() == max(
                    x.area() for x in pcs)]
                if len(keep) < len(pcs):
                    pr_all = poly_props(sec)
                    extra = {"sigma_all_pieces_MPa": round(max_bending_stress(pr_all, F * (L - s_))[0], 3),
                             "slivers_dropped_mm2": sorted(round(q.area(), 3) for q in pcs
                                                           if not any(q is k_ for k_ in keep))}
                    sec = CrossSection.compose(keep)
            pr = poly_props(sec)
            if pr is None:
                continue
            Mz = F * (L - s_)
            sg, ang = max_bending_stress(pr, Mz)
            dims = caliper_dims(pr["pts"])
            if k == 0:
                root_dims = dims
            stations.append({"s": round(float(s_), 2), "area_mm2": round(pr["A"], 2), "dims_mm": rl(dims, 2),
                             "moment_Nmm": round(Mz, 1), "sigma_MPa": round(sg, 3), **extra})
        # fragment if snapped at the root: body beyond the root plane, inside the piece footprint (+1 mm)
        bb_ = shapely.geometry.polygon.orient(big.buffer(1.0), 1.0)
        cut = CrossSection([[tuple(p_) for p_ in np.asarray(bb_.exterior.coords)[:-1]]])
        frag_m = body ^ cut.extrude(60.0).translate((0, 0, -20.0))
        th = math.degrees(math.atan2(n[1], n[0]))
        frag_m = frag_m.translate((-m[0], -m[1], 0)).rotate((0, 0, -th)).trim_by_plane((1, 0, 0), 0.0)
        frag = fragment_fit(frag_m)
        out.append(_stress_record(f"{label}lobe@({cen.x:.1f},{cen.y:.1f})", "in-plane", body_name, stations,
                                  root_dims, L, F, frag,
                                  notes=f"root chord {np.linalg.norm(b - a):.2f} mm from ({a[0]:.2f},{a[1]:.2f}) to "
                                        f"({b[0]:.2f},{b[1]:.2f}), tip ({tip[0]:.2f},{tip[1]:.2f}); bending stress "
                                        "lies in the layer plane (in-layer, strong direction)"))
    return out


def thin_panels(frame: Manifold, z_thin: float, F: float, head: Manifold | None = None,
                fill_holes: bool = True) -> list[dict]:
    """Regions of the frame that are only the back plate (+ skid ribs): cantilever plate estimate for a load F
    normal to the plate at the point farthest from the supporting body.  Islands standing on the plate (e.g. a
    post) are load points, not supports.
    fill_holes=False (sculpt skins): the thick part's plan keeps its holes.  The sculpt's cushion closes around the
    head, so the plate-only region under it is a hole of that plan; filling it (classic) leaves no panel at all."""
    plate = silhouette(frame)
    up = frame.trim_by_plane((0, 0, 1), z_thin)
    thick_all = silhouette(up) if fill_holes else up.project()
    comps = sorted(thick_all.decompose(), key=lambda q: -q.area())
    if not fill_holes:
        comps = [q for q in comps if q.area() >= 0.5]       # (zero-area slivers of the organic surface)
    if not comps:
        return []
    support = comps[0]
    islands = comps[1:]
    thin = g2.difference(plate, support)
    sup_shp = to_shp(support)
    out = []
    for q in thin.decompose():
        if q.area() < 50.0:
            continue
        shp = to_shp(q)
        # sample the panel, find the farthest point from the support
        x0, y0, x1, y1 = shp.bounds
        gx, gy = np.meshgrid(np.arange(x0, x1, 0.5), np.arange(y0, y1, 0.5))
        pts = np.stack([gx.ravel(), gy.ravel()], axis=1)
        inside = shapely.contains_xy(shp, pts[:, 0], pts[:, 1])
        pts = pts[inside]
        if len(pts) == 0:
            continue
        d = shapely.distance(shapely.points(pts), sup_shp)
        k = int(np.argmax(d))
        L, tip = float(d[k]), pts[k]
        if L < 3.0:
            continue
        nearest = np.asarray(shapely.get_coordinates(shapely.shortest_line(Point(tip), sup_shp)))[-1]
        dirv = (tip - nearest) / max(np.linalg.norm(tip - nearest), 1e-9)
        perp = np.array([-dirv[1], dirv[0]])
        width = float(np.ptp(pts @ perp))
        # plate thickness near the tip (2 mm inboard, clear of the bottom chamfer): highest z with material
        probe_pt = Point(tip - 2.0 * dirv)
        t = 0.0
        for z in np.arange(1.0, 6.0, 0.05):
            if not to_shp(frame.slice(float(z))).contains(probe_pt):
                break
            t = float(z) + 0.025
        w_eff = min(2.0 * L, width)
        sigma = 6.0 * F * L / (w_eff * t * t) if t > 0 else math.inf
        covered = None
        if head is not None:
            covered = round(float(to_shp(q ^ silhouette(head)).area / q.area()), 3) if not (q ^ silhouette(head)).is_empty() else 0.0
        rec = {"area_mm2": round(q.area(), 1), "far_point": rl(tip, 2), "cantilever_L_mm": round(L, 2),
               "support_point": rl(nearest, 2), "width_mm": round(width, 2), "w_eff_mm": round(w_eff, 2),
               "thickness_mm": round(t, 2), "load_N": F, "sigma_MPa": round(sigma, 1),
               "fraction_under_head": covered, "islands_on_panel": []}
        for isl in islands:
            ish = to_shp(isl)
            if ish.within(shp.buffer(0.5)) or ish.intersects(shp.buffer(0.5)):
                c = ish.centroid
                gap = float(ish.distance(sup_shp))
                r0 = math.sqrt(isl.area() / math.pi)
                rm = r0 + gap / 2
                # half-ring cantilever strip (support on the body side only): sigma = 6 F a / (pi r_m t^2)
                s_isl = 6.0 * F * gap / (math.pi * rm * t * t) if t > 0 else math.inf
                rec["islands_on_panel"].append({"centre": rl((c.x, c.y), 2), "r_equiv": round(r0, 2),
                                                "gap_to_support_mm": round(gap, 2),
                                                "sigma_axial_pull_MPa": round(s_isl, 1)})
        out.append(rec)
    return out


def summit_parts(body: Manifold, z_lo: float, dz: float = 0.25) -> list[dict]:
    """Parts of an organic body that stand up on their own (sculpt skins: there is no flat body-top plane).
    Walking down from the top in dz steps, the body above z splits into 3-D components; where two of them merge,
    the one with the lower summit ends: it stands on the body from that level (its root) up to its summit
    (topographic prominence).  Returns every ended part, plus the parts still separate at z_lo (root z_lo); the
    main body (highest summit) is not a part."""
    zt = body.bounding_box()[5]
    tracks, parts, prev = [], [], []          # prev: (track index, component above the previous level)
    for z in np.arange(z_lo, zt, dz)[::-1]:
        comps = [q for q in body.trim_by_plane((0, 0, 1), float(z)).decompose() if q.volume() > 1e-3]
        bbs = [np.asarray(q.bounding_box()) for q in comps]
        owner = {}
        for ti, U in prev:                    # the lower component that contains each upper one
            ub = np.asarray(U.bounding_box())
            cand = [j for j, b in enumerate(bbs) if np.all(b[:3] <= ub[:3] + 1e-4) and np.all(b[3:] >= ub[3:] - 1e-4)]
            if len(cand) > 1:
                cand = [max(cand, key=lambda j: (comps[j] ^ U).volume())]
            if cand:
                owner.setdefault(cand[0], []).append((ti, U))
        cur = []
        for j, q in enumerate(comps):
            ups = sorted(owner.get(j, []), key=lambda t: -tracks[t[0]])
            if not ups:
                tracks.append(float(bbs[j][5]))
                cur.append((len(tracks) - 1, q))
                continue
            for ti, U in ups[1:]:
                parts.append({"root_z": float(z + dz), "summit_z": tracks[ti], "comp": U})
            cur.append((ups[0][0], q))
        prev = cur
    if prev:
        main = max(prev, key=lambda t: tracks[t[0]])[0]
        parts += [{"root_z": float(z_lo), "summit_z": tracks[ti], "comp": U, "separate_at_z_lo": True}
                  for ti, U in prev if ti != main]
    for d in parts:
        d["h"] = d["summit_z"] - d["root_z"]
    return parts


def ring_thickness(frame: Manifold, r_in: float, r_out: float, z0: float, F: float, r_load: float) -> dict:
    """Thickness of the frame over an annulus about O (sculpt skins: the yarn ball's static ring over the wheel's
    umbrella): vertical columns every 5 deg x 1 mm in radius; per column the first solid run above z0 (its
    underside clears the umbrella / skid rings, its top is the sculpt).  Also a pull-out estimate: F up on the wheel
    bears on the ring's underside at r_load (the inner skid ring) and bends the ring as a strip clamped at r_out:
    sigma = 6 m / t_min^2, m = F (r_out - r_load) / (2 pi r_out) per mm of the clamped edge (hoop action ignored)."""
    th = np.radians(np.arange(0.0, 360.0, 5.0))
    rr, tt = np.meshgrid(np.arange(r_in + 0.25, r_out, 1.0), th)
    pts = np.stack([(rr * np.cos(tt)).ravel(), (rr * np.sin(tt)).ravel()], axis=1)
    zs = np.arange(z0 + 0.025, frame.bounding_box()[5], 0.05)
    occ = np.zeros((len(zs), len(pts)), bool)
    for i, z in enumerate(zs):
        occ[i] = shapely.contains_xy(to_shp(frame.slice(float(z))), pts[:, 0], pts[:, 1])
    t = np.full(len(pts), np.nan)
    zr = np.full((len(pts), 2), np.nan)
    for j in range(len(pts)):
        col = occ[:, j]
        if not col.any():
            continue
        i0 = i1 = int(np.argmax(col))
        while i1 + 1 < len(col) and col[i1 + 1]:
            i1 += 1
        t[j] = (i1 - i0 + 1) * 0.05
        zr[j] = (zs[i0] - 0.025, zs[i1] + 0.025)
    n_open = int(np.isnan(t).sum())
    if n_open == len(t):
        return {"n_columns": len(t), "n_open": n_open, "t_min_mm": None}
    k = int(np.nanargmin(t))
    m = F * (r_out - r_load) / (2.0 * math.pi * r_out)
    worst = sorted(range(len(t)), key=lambda j: t[j] if np.isfinite(t[j]) else 1e9)[:8]
    return {"annulus_r": [round(r_in, 2), round(r_out, 2)], "z_from": round(z0, 3), "n_columns": len(t),
            "n_open": n_open, "t_min_mm": round(float(t[k]), 2), "at": rl(pts[k], 2),
            "z_range_at_min": rl(zr[k], 2), "t_median_mm": round(float(np.nanmedian(t)), 2),
            "n_below_2.0": int(np.sum(t < 2.0 - 1e-6)),
            "pull_out_sigma_MPa": round(6.0 * m / float(t[k]) ** 2, 2), "pull_out_load_N": F,
            "pull_out_r_load": round(r_load, 2),
            "thinnest": [{"at": rl(pts[j], 2), "t": round(float(t[j]), 2), "z": rl(zr[j], 2)} for j in worst]}


# --------------------------------------------------------------------------------------------- V12 machinery
def resample_contour(c: np.ndarray, step: float) -> tuple[np.ndarray, np.ndarray]:
    """Points every `step` along a closed contour and the outward normal (right-hand normal of the contour
    direction; CrossSection outer contours are CCW and holes CW, so it points out of the material)."""
    cc = np.vstack([c, c[:1]])
    seg = cc[1:] - cc[:-1]
    ln = np.linalg.norm(seg, axis=1)
    keep = ln > 1e-9
    cc = np.vstack([cc[:-1][keep], cc[:-1][keep][:1]])
    seg = cc[1:] - cc[:-1]
    ln = np.linalg.norm(seg, axis=1)
    s = np.concatenate([[0], np.cumsum(ln)])
    total = s[-1]
    if total < step:
        return np.zeros((0, 2)), np.zeros((0, 2))
    t = np.arange(0.0, total, step) + 0.5 * (total % step)
    idx = np.clip(np.searchsorted(s, t, side="right") - 1, 0, len(seg) - 1)
    frac = (t - s[idx]) / ln[idx]
    pts = cc[idx] + seg[idx] * frac[:, None]
    tang = seg[idx] / ln[idx, None]
    nrm = np.stack([tang[:, 1], -tang[:, 0]], axis=1)
    return pts, nrm


class BodyRaster:
    """Boolean occupancy raster of a CrossSection in its own (body) frame."""

    def __init__(self, cs: CrossSection, h: float = 0.1, pad: float = 1.0):
        self.h = h
        if cs.is_empty():
            self.empty = True
            return
        self.empty = False
        x0, y0, x1, y1 = cs.bounds()
        self.x0, self.y0 = x0 - pad, y0 - pad
        self.nx = int(math.ceil((x1 - x0 + 2 * pad) / h)) + 1
        self.ny = int(math.ceil((y1 - y0 + 2 * pad) / h)) + 1
        acc = np.zeros((self.ny, self.nx), dtype=bool)
        for c in cs_contours(cs):
            img = Image.new("1", (self.nx, self.ny), 0)
            pts = [((x - self.x0) / h, (y - self.y0) / h) for x, y in c]
            ImageDraw.Draw(img).polygon(pts, fill=1, outline=1)
            acc ^= np.asarray(img, dtype=bool)
        self.a = acc

    def lookup(self, xy: np.ndarray) -> np.ndarray:
        if self.empty:
            return np.zeros(len(xy), dtype=bool)
        ix = np.rint((xy[:, 0] - self.x0) / self.h).astype(np.int64)
        iy = np.rint((xy[:, 1] - self.y0) / self.h).astype(np.int64)
        ok = (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)
        out = np.zeros(len(xy), dtype=bool)
        out[ok] = self.a[iy[ok], ix[ok]]
        return out


class ZLevel:
    def __init__(self, z: float, bodies: dict, edge_step: float, moving: tuple):
        self.z = z
        self.cs, self.ras, self.kd, self.kdp, self.edges = {}, {}, {}, {}, {}
        for k, b in bodies.items():
            cs = b.slice(z)
            self.cs[k] = cs
            self.ras[k] = BodyRaster(cs)
            dense = [resample_contour(c, 0.05)[0] for c in cs_contours(cs)]
            dense = [d for d in dense if len(d)]
            if dense:
                P = np.vstack(dense)
                self.kd[k], self.kdp[k] = cKDTree(P), P
            if k in moving:
                pts, nrm = [], []
                for c in cs_contours(cs):
                    if abs(signed_area(c)) < 0.05:
                        continue
                    p_, n_ = resample_contour(c, edge_step)
                    pts.append(p_)
                    nrm.append(n_)
                if pts:
                    P, N = np.vstack(pts), np.vstack(nrm)
                    # make sure the normals point out of the material
                    inside = self.ras[k].lookup(P + 0.15 * N)
                    N[inside] *= -1.0
                    self.edges[k] = (P, N)


class World:
    def __init__(self, M, zs, edge_step: float, h: float, r_probe: float):
        self.M = M
        self.p = M.params
        self.P = np.asarray(M.P, float)
        self.zs = list(zs)
        self.h = h
        self.r = r_probe
        bodies = M.bodies
        self.levels = [ZLevel(z, bodies, edge_step, ("head", "wheel")) for z in self.zs]
        bb = np.array([b.bounding_box() for b in bodies.values()])
        m = r_probe + 3.0
        # grid anchored to world multiples of h, so the same geometry is sampled the same way whatever the skin's
        # outline (a bounding-box origin shifted the cells by up to h and flipped marginal probe contacts, run 5)
        self.gx0 = math.floor((bb[:, 0].min() - m) / h) * h
        self.gy0 = math.floor((bb[:, 1].min() - m) / h) * h
        # a probe centre cell "touches" a cell within r + h sqrt(2): the raster error of both cells (the old
        # r + h missed contacts in bands narrower than a cell, e.g. the crown face beside the head's neck)
        self.touch = r_probe + h * math.sqrt(2.0)
        gx1, gy1 = bb[:, 3].max() + m, bb[:, 4].max() + m
        self.nx = int(math.ceil((gx1 - self.gx0) / h)) + 1
        self.ny = int(math.ceil((gy1 - self.gy0) / h)) + 1
        X, Y = np.meshgrid(self.gx0 + h * np.arange(self.nx), self.gy0 + h * np.arange(self.ny))
        self.G = np.stack([X.ravel(), Y.ravel()], axis=1)
        self.frame_occ = [lv.ras["frame"].lookup(self.G).reshape(self.ny, self.nx) for lv in self.levels]
        self.border = np.zeros((self.ny, self.nx), dtype=bool)
        self.border[0, :] = self.border[-1, :] = self.border[:, 0] = self.border[:, -1] = True

    def to_body(self, body: str, xy: np.ndarray, phi: float, psi: float) -> np.ndarray:
        if body == "wheel":
            return rot2(xy, -phi)
        if body == "head":
            return rot2(xy, -psi, self.P)
        return xy

    def to_world(self, body: str, xy: np.ndarray, phi: float, psi: float) -> np.ndarray:
        if body == "wheel":
            return rot2(xy, phi)
        if body == "head":
            return rot2(xy, psi, self.P)
        return xy

    def occ(self, body: str, k: int, phi: float, psi: float, G=None) -> np.ndarray:
        if body == "frame":
            return self.frame_occ[k]
        if G is None:
            G = self.to_body(body, self.G, phi, psi)
        return self.levels[k].ras[body].lookup(G).reshape(self.ny, self.nx)

    def accessible(self, phi: float, psi: float) -> list[np.ndarray]:
        """Probe-centre accessibility masks for every Z level.  The probe is a SPHERE of radius r: its centre
        may sit at level k only if every level j within +-r is clear by sqrt(r^2 - dz^2) (per-level distance
        transforms).  Flood: lateral within a level from the raster border, and straight down from the level
        above (top-down; everything above the toy is accessible)."""
        Gw = rot2(self.G, -phi)
        Gh = rot2(self.G, -psi, self.P)
        nlev = len(self.levels)
        edt = []
        for k in range(nlev):
            lv = self.levels[k]
            occ = self.frame_occ[k] | lv.ras["wheel"].lookup(Gw).reshape(self.ny, self.nx) | \
                lv.ras["head"].lookup(Gh).reshape(self.ny, self.nx)
            edt.append(ndimage.distance_transform_edt(~occ) * self.h if occ.any()
                       else np.full(occ.shape, 1e9))
        dzs = np.asarray(self.zs)
        acc_prev = np.ones((self.ny, self.nx), dtype=bool)
        out = [None] * nlev
        st = ndimage.generate_binary_structure(2, 2)
        for k in range(nlev - 1, -1, -1):
            free = np.ones((self.ny, self.nx), dtype=bool)
            for j in range(nlev):
                dz = abs(dzs[j] - dzs[k])
                if dz >= self.r:
                    continue
                free &= edt[j] >= math.sqrt(self.r ** 2 - dz ** 2) - 1e-9
            if dzs[k] - self.r < dzs[0] - 0.25:      # sphere reaches below the lowest level: the bed / plate
                free &= edt[0] >= self.r
            lab, n = ndimage.label(free, structure=st)
            seeds = np.unique(lab[(free & acc_prev) | (free & self.border)])
            seeds = seeds[seeds > 0]
            acc = np.isin(lab, seeds)
            out[k] = acc
            acc_prev = acc
        return out

    def lookup_acc(self, acc: np.ndarray, xy: np.ndarray) -> np.ndarray:
        ix = np.rint((xy[:, 0] - self.gx0) / self.h).astype(np.int64)
        iy = np.rint((xy[:, 1] - self.gy0) / self.h).astype(np.int64)
        ok = (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)
        out = np.zeros(len(xy), dtype=bool)
        out[ok] = acc[iy[ok], ix[ok]]
        return out

    def gaps(self, lv: ZLevel, mover: str, phi: float, psi: float, cap: float = 30.0):
        """Gap (nearest neighbour material in front of the surface) and neighbour id for every edge point."""
        P, N = lv.edges[mover]
        Pw = self.to_world(mover, P, phi, psi)
        Nw = self.to_world(mover, N, phi, psi) - self.to_world(mover, np.zeros((1, 2)), phi, psi)
        best = np.full(len(P), cap)
        who = np.full(len(P), -1, dtype=np.int64)
        for j, nb in enumerate(("frame", "wheel", "head")):
            if nb == mover or nb not in lv.kd:
                continue
            Pb = self.to_body(nb, Pw, phi, psi)
            Nb = self.to_body(nb, Pw + Nw, phi, psi) - Pb
            d, idx = lv.kd[nb].query(Pb, k=16, distance_upper_bound=cap)
            valid = np.isfinite(d)
            idx = np.where(valid, idx, 0)
            vec = lv.kdp[nb][idx] - Pb[:, None, :]
            front = (vec * Nb[:, None, :]).sum(-1) >= -0.02
            dd = np.where(valid & front, d, np.inf).min(axis=1)
            upd = dd < best
            best[upd] = dd[upd]
            who[upd] = j
        return best, who, Pw, Nw


def _edt(occ: np.ndarray, h: float) -> np.ndarray:
    if not occ.any():
        return np.full(occ.shape, 1e3, dtype=np.float32)
    return (ndimage.distance_transform_edt(~occ) * h).astype(np.float32)


def _edt_vec(occ: np.ndarray, h: float):
    """Distance to the nearest occupied cell and the unit vector towards it (cell units)."""
    if not occ.any():
        return np.full(occ.shape, 1e3, np.float32), None
    d, ind = ndimage.distance_transform_edt(~occ, return_indices=True)
    iy, ix = np.indices(occ.shape)
    v = np.stack([ind[1] - ix, ind[0] - iy]).astype(np.float32)
    n = np.maximum(np.hypot(v[0], v[1]), 1e-6)
    return (d * h).astype(np.float32), v / n


BETWEEN_COS = -0.3      # a cell is IN a gap if the nearest mover point and the nearest neighbour point lie on
                        # opposite sides of it (angle > 107 deg); otherwise the "gap" would be measured through a wall


def pinch_audit(W: World, series: list[dict], R: Report, roi: float = 12.5) -> dict:
    """Eulerian pinch audit.  For every world cell x of every Z level and every pose t of a motion series:
    gap g(x, t) = d(x, mover) + d(x, other bodies) (same Z level), evaluated where x is air and lies BETWEEN the
    mover and the neighbour (nearest points on opposite sides).  x is exposed if a probe sphere (radius W.r,
    flooded from outside) can touch it at some pose.  Raster screening (0.25 mm EDT) followed by an exact
    re-evaluation (dense boundary samples, KD-trees) of every candidate cell."""
    out = {}
    others = {"head": ("frame", "wheel"), "wheel": ("frame", "head")}
    for ser in series:
        t0 = time.time()
        mv = ser["mover"]
        poses = ser["poses"]
        fphi, fpsi = ser["fixed"]                       # pose of the non-moving bodies
        levels = [k for k, lv in enumerate(W.levels) if not lv.cs[mv].is_empty()]
        G_other = {b: W.to_body(b, W.G, fphi, fpsi) for b in others[mv] if b != "frame"}
        occ_n, edt_n, vec_n = {}, {}, {}
        for k in levels:
            o = np.zeros((W.ny, W.nx), dtype=bool)
            for b in others[mv]:
                o |= W.occ(b, k, fphi, fpsi, G_other.get(b))
            occ_n[k] = o
            edt_n[k], vec_n[k] = _edt_vec(o, W.h)
        shp = (W.ny, W.nx)
        acc_ = {k: dict(gmin=np.full(shp, np.inf, np.float32), gmax=np.full(shp, -np.inf, np.float32),
                        exp=np.zeros(shp, bool)) for k in levels}
        touch = {k: [] for k in levels}          # per pose: cells a probe can touch (packed bits)
        for t, (phi, psi) in enumerate(poses):
            acc = W.accessible(phi, psi)
            for k in levels:
                tm = (_edt(acc[k], W.h) <= W.touch) if acc[k].any() else np.zeros((W.ny, W.nx), bool)
                touch[k].append(np.packbits(tm.ravel()))
            Gm = W.to_body(mv, W.G, phi, psi)
            for k in levels:
                if vec_n[k] is None:
                    continue
                om = W.occ(mv, k, phi, psi, Gm)
                dm, vm = _edt_vec(om, W.h)
                if vm is None:
                    continue
                between = (vm[0] * vec_n[k][0] + vm[1] * vec_n[k][1]) < BETWEEN_COS
                ok = ~om & ~occ_n[k] & between & (dm < roi) & (edt_n[k] < roi)
                g = dm + edt_n[k]
                a = acc_[k]
                np.minimum(a["gmin"], np.where(ok, g, np.inf), out=a["gmin"])
                np.maximum(a["gmax"], np.where(ok, g, -np.inf), out=a["gmax"])
                # cells a probe sphere centred in the accessible set can touch (within r of an accessible centre)
                if acc[k].any():
                    a["exp"] |= ok & (_edt(acc[k], W.h) <= W.touch)
        # screening (raster error <= ~0.4 on the sum of two distances)
        cand = {}
        for k in levels:
            a = acc_[k]
            m = a["exp"] & np.isfinite(a["gmin"]) & (a["gmax"] >= SPEC["pinch_lo"] - 0.4) & \
                (a["gmin"] < SPEC["pinch_hi"] + 0.4) & (a["gmax"] - a["gmin"] > SPEC["pinch_const"] - 0.5)
            if m.any():
                cand[k] = np.nonzero(m.ravel())[0]
        # exact re-evaluation
        res = []
        for k, idx in cand.items():
            lv = W.levels[k]
            X = W.G[idx]
            dn = np.full(len(X), np.inf)
            pn = np.zeros((len(X), 2))
            nbi = np.full(len(X), -1, np.int64)
            inside_n = np.zeros(len(X), bool)
            for j, b in enumerate(others[mv]):
                Xb = W.to_body(b, X, fphi, fpsi)
                inside_n |= lv.ras[b].lookup(Xb)
                if b in lv.kd:
                    d, i = lv.kd[b].query(Xb)
                    upd = d < dn
                    dn[upd] = d[upd]
                    nbi[upd] = j
                    pn[upd] = W.to_world(b, lv.kdp[b][i[upd]], fphi, fpsi)
            un = (pn - X) / np.maximum(np.linalg.norm(pn - X, axis=1, keepdims=True), 1e-9)
            gmin = np.full(len(X), np.inf)
            gmax = np.full(len(X), -np.inf)
            amin = np.zeros(len(X), np.int64)
            amax = np.zeros(len(X), np.int64)
            for t, (phi, psi) in enumerate(poses):
                Xm = W.to_body(mv, X, phi, psi)
                cov = lv.ras[mv].lookup(Xm)
                if mv not in lv.kd:
                    continue
                dm, im = lv.kd[mv].query(Xm)
                pm = W.to_world(mv, lv.kdp[mv][im], phi, psi)
                um = (pm - X) / np.maximum(np.linalg.norm(pm - X, axis=1, keepdims=True), 1e-9)
                between = (um * un).sum(1) < BETWEEN_COS
                # line of sight: the segment x -> nearest mover point must not pass through another body
                cand_i = np.nonzero(~cov & ~inside_n & between & (dm < roi) & (dn < roi))[0]
                los = np.zeros(len(X), bool)
                if len(cand_i):
                    blocked = np.zeros(len(cand_i), bool)
                    for f_ in np.linspace(0.1, 0.9, 9):
                        Y = X[cand_i] + f_ * (pm[cand_i] - X[cand_i])
                        for b in others[mv]:
                            blocked |= lv.ras[b].lookup(W.to_body(b, Y, fphi, fpsi))
                        # (fix round 1) and x -> nearest neighbour point must not pass through the mover itself:
                        # otherwise the "gap" is measured through the mover's own wall (e.g. a cell inside the
                        # wheel's finger well 'sees' the paw lip through the ball rim)
                        Yn = X[cand_i] + f_ * (pn[cand_i] - X[cand_i])
                        blocked |= lv.ras[mv].lookup(W.to_body(mv, Yn, phi, psi))
                    los[cand_i] = ~blocked
                # (fix round 1) both jaws must be touchable by the probe at this pose: a surface the fingertip
                # cannot reach (e.g. a wall deep inside a 3 mm slot) cannot squeeze it
                tmask = np.unpackbits(touch[k][t])[:W.ny * W.nx].astype(bool).reshape(W.ny, W.nx)
                both = W.lookup_acc(tmask, pn) & W.lookup_acc(tmask, pm)
                valid = los & both
                g = np.where(valid, dm + dn, np.nan)
                lo = g < gmin
                gmin[lo], amin[lo] = g[lo], t
                hi = g > gmax
                gmax[hi], amax[hi] = g[hi], t
            var = gmax - gmin
            bad = np.isfinite(gmin) & (var > SPEC["pinch_const"]) & ~(gmax < SPEC["pinch_lo"]) & \
                ~(gmin >= SPEC["pinch_hi"])
            for i in np.nonzero(bad)[0]:
                res.append({"k": k, "z": lv.z, "x": X[i], "gmin": float(gmin[i]), "gmax": float(gmax[i]),
                            "tmin": int(amin[i]), "tmax": int(amax[i]), "nb": others[mv][nbi[i]]})
        n_exp = int(sum(acc_[k]["exp"].sum() for k in levels))
        n_cand = int(sum(len(v) for v in cand.values()))
        R.log(f"  pinch series {ser['name']}: {len(poses)} poses, {len(levels)} levels, exposed gap cells {n_exp}, "
              f"candidates {n_cand}, violating cells {len(res)}, {time.time() - t0:.1f}s")
        out[ser["name"]] = {"violations": res, "exposed_gap_cells": n_exp, "candidates": n_cand}
    return out


PROBE_OPEN = 4.0    # a gap that opens to >= 4 mm admits a fingertip edge (probe diameter)
CLOSE_MIN = 2.0     # a finger-size gap that closes by less than this is not counted as a squeeze (warn only)
MIN_CELLS = 4       # clusters smaller than this (0.25 mm cells x 0.5 mm levels) are reported together as isolated


def cluster_pinch(W: World, series: list[dict], audit: dict) -> list[dict]:
    clusters = []
    for ser in series:
        res = audit[ser["name"]]["violations"]
        for nb in ("frame", "wheel", "head"):
            sub = [r for r in res if r["nb"] == nb]
            if not sub:
                continue
            X = np.array([[r["x"][0], r["x"][1], r["z"]] for r in sub])
            tree = cKDTree(X)
            parent = list(range(len(sub)))

            def find(a):
                while parent[a] != a:
                    parent[a] = parent[parent[a]]
                    a = parent[a]
                return a
            for a, b in tree.query_pairs(0.6):
                parent[find(a)] = find(b)
            groups = {}
            for i in range(len(sub)):
                groups.setdefault(find(i), []).append(i)
            for g in groups.values():
                vs = [sub[i] for i in g]
                xy = np.array([v["x"] for v in vs])
                opens = [v for v in vs if v["gmax"] >= PROBE_OPEN]
                shear = [v for v in opens if v["gmin"] < SPEC["pinch_lo"]]
                squeeze = [v for v in opens if v["gmax"] - v["gmin"] >= CLOSE_MIN and v["gmin"] < SPEC["pinch_hi"]]
                if shear:
                    sev, kind = "high", "finger-size opening (>= 4 mm) closes below 2 mm (shear / crush)"
                    pool = shear
                elif squeeze:
                    sev, kind = "medium", ("finger-size opening closes by >= 2 mm to a gap inside the 2-12 mm band "
                                           "(squeeze)")
                    pool = squeeze
                else:
                    sev, kind = "low", ("literal V12 violation only: the gap never opens to a 4 mm fingertip or "
                                        "changes by < 2 mm")
                    pool = vs
                worst = min(pool, key=lambda v: (v["gmin"], -v["gmax"]))
                clusters.append({
                    "series": ser["name"], "mover": ser["mover"], "neighbour": nb, "n_cells": len(vs),
                    "n_cells_shear": len(shear), "n_cells_squeeze": len(squeeze), "severity": sev, "kind": kind,
                    "z_range": [float(min(v["z"] for v in vs)), float(max(v["z"] for v in vs))],
                    "xy_centroid": rl(xy.mean(0), 2), "xy_bbox": rl(np.r_[xy.min(0), xy.max(0)], 2),
                    "worst_cell": rl(worst["x"], 2), "worst_z": float(worst["z"]),
                    "gap_min_at_worst_cell": round(worst["gmin"], 3),
                    "gap_max_at_worst_cell": round(worst["gmax"], 3),
                    "gap_min": round(min(v["gmin"] for v in vs), 3),
                    "gap_max": round(max(v["gmax"] for v in vs), 3),
                    "pose_at_gap_min": rl(ser["poses"][worst["tmin"]], 2),
                    "pose_at_gap_max": rl(ser["poses"][worst["tmax"]], 2),
                    "_worst": worst})
    rank = {"high": 0, "medium": 1, "low": 2}
    clusters.sort(key=lambda c: (rank[c["severity"]], c["gap_min"], -c["n_cells"]))
    return clusters


def plot_cluster(W: World, ser: dict, c: dict, path: Path, title: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    w = c["_worst"]
    lv = W.levels[w["k"]]
    fig, axs = plt.subplots(1, 2, figsize=(13, 6.5))
    cols = {"frame": "#d04040", "wheel": "#3070c0", "head": "#d09000"}
    fphi, fpsi = ser["fixed"]
    for ax, (lab, t) in zip(axs, (("widest", w["tmax"]), ("narrowest", w["tmin"]))):
        phi, psi = ser["poses"][t]
        for b in ("frame", "wheel", "head"):
            bp, bs = (phi, psi) if b == ser["mover"] else (fphi, fpsi)
            for poly in cs_contours(lv.cs[b]):
                a = W.to_world(b, poly, bp, bs)
                a = np.vstack([a, a[:1]])
                ax.plot(a[:, 0], a[:, 1], color=cols[b], lw=1.0)
        x = w["x"]
        ax.plot(x[0], x[1], "k*", ms=12)
        ax.add_patch(plt.Circle(x, W.r, fill=False, ls="--", color="gray"))
        ax.set_xlim(x[0] - 14, x[0] + 14)
        ax.set_ylim(x[1] - 14, x[1] + 14)
        ax.set_aspect("equal")
        ax.grid(alpha=0.3)
        ax.set_title(f"{lab}: phi {phi:.1f}, psi {psi:.2f}, z {lv.z:.2f}")
    fig.suptitle(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=70)
    plt.close(fig)


# --------------------------------------------------------------------------------------------- V14 renders
V14_VIEWS = {"front": (12, 0, 6), "back": (155, 0, 190), "three_quarter": (40, 0, 28)}


def render_colors(M) -> dict:
    """Body colours for the V14 renders and the pinch close-ups.  (sculpt: the skin paints frame and head the same
    cream, so the swinging head and the seams V14 is meant to show would read as shading only: the head gets a
    contrasting tint in these renders)"""
    cols = M.skin.colors
    if hasattr(M.skin, "sculpt"):
        cols = dict(cols, head="#e8b98c")
    return cols


def v14_renders(M, out_dir: Path, tag: str, R: Report) -> list[dict]:
    from render import render_views
    cols = render_colors(M)
    p = M.params
    pb = round(p.psi_b, 2)
    poses = [(0.0, -pb), (120.0, 0.0), (240.0, pb)]
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "_v14tmp"
    made = []
    for phi, psi in poses:
        B = M.posed(phi, psi)
        parts = {k: (B[k], cols.get(k, "#cccccc")) for k in ("frame", "wheel", "head")}
        for vname, cam in V14_VIEWS.items():
            pngs = render_views(parts, tmp / "r", views=(cam,), size=(1000, 1000))
            dst = out_dir / f"v14_{tag}_{vname}_psi{psi:+.1f}_phi{phi:.0f}.png"
            pngs[0].replace(dst)
            made.append({"view": vname, "phi": phi, "psi": psi, "file": str(dst)})
    # sections at the print pose
    B = M.print_pose()
    parts = {k: (B[k], cols.get(k, "#cccccc")) for k in ("frame", "wheel", "head")}
    cut = {k: (b.trim_by_plane((-1.0, 0.0, 0.0), 0.0), c) for k, (b, c) in parts.items()}
    cut = {k: v for k, v in cut.items() if not v[0].is_empty()}
    pngs = render_views(cut, tmp / "r", views=((90, 0, 90),), size=(1200, 700))
    dst = out_dir / f"v14_{tag}_section_x0_print_pose.png"
    pngs[0].replace(dst)
    made.append({"view": "section x=0 (seen from +X, keep x<0)", "phi": p.phi_print, "psi": p.psi_print,
                 "file": str(dst)})
    cutz = {k: (b.trim_by_plane((0.0, 0.0, -1.0), -5.2), c) for k, (b, c) in parts.items()}
    cutz = {k: v for k, v in cutz.items() if not v[0].is_empty()}
    pngs = render_views(cutz, tmp / "r", views=((0, 0, 0),), size=(1000, 1100))
    dst = out_dir / f"v14_{tag}_section_z5.2_print_pose.png"
    pngs[0].replace(dst)
    made.append({"view": "section z=5.2 (seen from +Z, keep z<5.2)", "phi": p.phi_print, "psi": p.psi_print,
                 "file": str(dst)})
    try:
        for f in tmp.glob("*"):
            f.unlink()
        tmp.rmdir()
    except OSError:
        pass
    R.log(f"  V14: {len(made)} renders in {out_dir}")
    return made


# --------------------------------------------------------------------------------------------- V12 edges / points
def convex_corner_report(cs: CrossSection, r_req: float, exposed_fn=None, min_depth: float = 0.08) -> list[dict]:
    """Convex plan corners sharper than r_req: material removed by an opening with a disc of radius r_req.
    Each removed piece deeper than `min_depth` (max distance from the opened outline) is a corner; its local
    radius is estimated by bisection on the opening radius (largest r whose opening leaves it < min_depth)."""
    if cs.is_empty():
        return []
    opened = g2.opening(cs, 2 * r_req, 0.005)
    removed = g2.difference(cs, g2.grow(opened, 0.01, 0.005))
    out = []
    op_shp = to_shp(opened)
    for q in removed.decompose():
        if q.area() < 1e-3:
            continue
        sq = to_shp(q)
        pts = np.asarray(shapely.get_coordinates(sq.exterior if sq.geom_type == "Polygon" else sq))
        if len(pts) == 0:
            continue
        d = shapely.distance(shapely.points(pts), op_shp)
        depth = float(d.max())
        if depth < min_depth:
            continue
        tip = pts[int(np.argmax(d))]
        if exposed_fn is not None and not exposed_fn(tip):
            continue
        bx = sq.bounds
        if math.hypot(bx[2] - bx[0], bx[3] - bx[1]) > 4.0 * r_req:
            # a long strip removed whole: a wall narrower than 2 r_req (wall thickness is group B / V8), not a corner
            continue
        # local radius: for a corner of interior angle a and radius rc the opening with radius R > rc removes
        # depth (R - rc)(1/sin(a/2) - 1); bisection on R to find where depth -> ~0 gives rc
        lo, hi = 0.0, r_req
        local = to_shp(cs).intersection(Point(tip).buffer(r_req * 3 + 1.0))
        lcs = CrossSection([[tuple(p) for p in np.asarray(shapely.geometry.polygon.orient(g, 1.0).exterior.coords)[:-1]]
                            for g in (local.geoms if local.geom_type == "MultiPolygon" else [local])
                            if g.geom_type == "Polygon" and g.area > 1e-6])
        for _ in range(10):
            mid = 0.5 * (lo + hi)
            op = to_shp(g2.opening(lcs, 2 * mid, 0.005)) if mid > 1e-3 else to_shp(lcs)
            dd = float(Point(tip).distance(op)) if not op.is_empty else 99.0
            if dd < 0.03:
                lo = mid
            else:
                hi = mid
        out.append({"at": rl(tip, 2), "depth_mm": round(depth, 3), "area_mm2": round(q.area(), 3),
                    "est_corner_r_mm": round(lo, 2)})
    return out


def ball_fraction(body: Manifold, pts: np.ndarray, rho: float = 1.0, tile: float = 8.0) -> np.ndarray:
    """Fraction of a ball of radius rho around each point that lies inside `body` (exact booleans on tiles)."""
    sph = Manifold.sphere(rho, 32)
    vol_s = sph.volume()
    out = np.zeros(len(pts))
    keys = np.floor(pts / tile).astype(int)
    cache = {}
    for i, (pt, key) in enumerate(zip(pts, map(tuple, keys))):
        if key not in cache:
            lo = np.array(key) * tile - (rho + 0.2)
            cube = Manifold.cube((tile + 2 * rho + 0.4,) * 3).translate(tuple(lo))
            cache[key] = body ^ cube
        out[i] = (cache[key] ^ sph.translate(tuple(pt))).volume() / vol_s
    return out


def sharp_candidates(body: Manifold, min_dihedral: float = 55.0) -> tuple[np.ndarray, np.ndarray, dict]:
    """Mesh vertices on convex edges that are acute (dihedral > 100 deg) or at corners where >= 2 sharp convex
    edges (dihedral > min_dihedral) meet at > 30 deg.  Returns (points, vertex normals, stats)."""
    import trimesh
    v, f = mesh_np(body)
    tm = trimesh.Trimesh(v, f, process=False)
    ang = np.degrees(tm.face_adjacency_angles)
    cvx = tm.face_adjacency_convex
    E = tm.face_adjacency_edges
    sharp = cvx & (ang > min_dihedral)
    acute = cvx & (ang > 100.0)
    cand = set(np.unique(E[acute]).tolist())
    # corners: per vertex, directions of incident sharp edges
    se = E[sharp]
    dirs = v[se[:, 1]] - v[se[:, 0]]
    dirs /= np.maximum(np.linalg.norm(dirs, axis=1, keepdims=True), 1e-12)
    inc = {}
    for (a, b), d in zip(se, dirs):
        inc.setdefault(a, []).append(d)
        inc.setdefault(b, []).append(d)
    for vi, ds in inc.items():
        if len(ds) < 2:
            continue
        D = np.abs(np.array(ds) @ np.array(ds).T)
        if D.min() < math.cos(math.radians(30.0)):
            cand.add(vi)
    idx = np.array(sorted(cand), dtype=np.int64)
    vn = tm.vertex_normals
    if len(idx) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3)), {"sharp_edges": int(sharp.sum()), "acute_edges": int(acute.sum())}
    P = v[idx]
    N = vn[idx]
    # de-duplicate on a 0.5 mm grid
    _, keep = np.unique(np.floor(P / 0.5).astype(np.int64), axis=0, return_index=True)
    return P[keep], N[keep], {"sharp_edges": int(sharp.sum()), "acute_edges": int(acute.sum()),
                              "candidates": int(len(keep))}


# --------------------------------------------------------------------------------------------- design review
def _inscribed_w(geom) -> float:
    try:
        ln = shapely.maximum_inscribed_circle(geom, 0.005)
        return 2.0 * float(ln.length)
    except Exception:
        return float("nan")


def _depth_scan(body: Manifold, pt, z_top: float, step: float = 0.05, zmax_depth: float = 2.0) -> float:
    """Depth of a pocket at pt below z_top: lowest z (from z_top down) at which pt is still air."""
    z = z_top - step / 2
    last = z_top
    while z > z_top - zmax_depth:
        if to_shp(body.slice(float(z))).contains(Point(pt)):
            break
        last = z
        z -= step
    return round(z_top - last + step / 2, 3)


def _height_scan(body: Manifold, pt, z_base: float, step: float = 0.05, hmax: float = 3.0) -> float:
    z = z_base + step / 2
    last = z_base
    while z < z_base + hmax:
        if not to_shp(body.slice(float(z))).contains(Point(pt)):
            break
        last = z
        z += step
    return round(last - z_base + step / 2, 3)


def surface_features(body: Manifold, z_surf: float, label: str, region=None, deep: float = 1.2) -> list[dict]:
    """Debossed pockets (holes in the slice just below z_surf that do not reach z_surf - deep) and raised
    features (pieces of the slice just above z_surf) on a flat top surface at z_surf."""
    out = []
    below = to_shp(body.slice(z_surf - 0.04))
    deeper = to_shp(body.slice(z_surf - deep))
    raised = to_shp(body.slice(z_surf + 0.04))
    polys = list(below.geoms) if below.geom_type == "MultiPolygon" else [below]
    for poly in polys:
        if poly.is_empty:
            continue
        for ring in poly.interiors:
            hole = Polygon(ring)
            if hole.area < 0.05 or (region is not None and not region.contains(hole.representative_point())):
                continue
            rp = hole.representative_point()
            if not deeper.contains(rp):           # through-hole / gap between parts, not a deboss
                continue
            w = _inscribed_w(hole)
            out.append({"surface": label, "type": "deboss", "z_surface": round(z_surf, 2),
                        "centroid": rl((hole.centroid.x, hole.centroid.y), 2), "area_mm2": round(hole.area, 2),
                        "width_mm": round(w, 3), "stroke_width_mm": round(min(w, 2 * hole.area / hole.length), 3),
                        "depth_mm": _depth_scan(body, (rp.x, rp.y), z_surf)})
    rp_list = list(raised.geoms) if raised.geom_type == "MultiPolygon" else [raised]
    if any(not g.is_empty for g in rp_list):
        base = below
        for g in rp_list:
            if g.is_empty or g.area < 0.05:
                continue
            if region is not None and not region.contains(g.representative_point()):
                continue
            # only pieces that stand on the surface (smaller than the surface they sit on)
            if g.area > 0.5 * base.area:
                continue
            w = _inscribed_w(g)
            rp = g.representative_point()
            c = g.centroid
            # height measured at the inscribed-circle centre (the highest region for domes)
            mic = shapely.maximum_inscribed_circle(g, 0.005)
            cpt = np.asarray(mic.coords)[0]
            hgt = _height_scan(body, cpt, z_surf, hmax=1.6)
            if hgt > 1.2:                         # structural (paws, knob ...), not a relief feature
                continue
            out.append({"surface": label, "type": "raised", "z_surface": round(z_surf, 2),
                        "centroid": rl((c.x, c.y), 2), "area_mm2": round(g.area, 2), "width_mm": round(w, 3),
                        "stroke_width_mm": round(min(w, 2 * g.area / g.length), 3),
                        "bbox_mm": rl(np.r_[g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1]], 2),
                        "height_mm": hgt})
    return out


# --------------------------------------------------------------------------------------------- driver
def _json_default(o):
    if hasattr(o, "item"):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    if isinstance(o, float) and not math.isfinite(o):
        return str(o)
    return str(o)


def run_v10(R: Report, M) -> dict:
    p = M.params
    F = SPEC["load_N"]
    out = {"bodies": {}, "protrusions": [], "panels": []}
    # ---- whole bodies
    fits = []
    for k, b in M.bodies.items():
        cf = cylinder_fit(b, n_dir=1200)
        w2 = plan_dims(b)
        cf["plan_min_caliper_width"] = round(w2[0], 3)
        cf["plan_perp_width"] = round(w2[1], 3)
        out["bodies"][k] = cf
        fits.append(cf["fits_short_cylinder"] or cf["fits_long_cylinder"])
        if k in ("wheel", "head"):
            lim = SPEC["wheel_min_width"] if k == "wheel" else SPEC["head_min_width"]
            R.add(f"V10.{k}_min_width", f"{k}: smallest enclosing cylinder over all orientations",
                  status(cf["min_enclosing_d"] >= lim), cf["min_enclosing_d"], f">= {lim} (and > {SPEC['cyl_d']})",
                  plan_min_caliper_width=cf["plan_min_caliper_width"], axis=cf["axis"])
    R.add("V10.no_body_fits", "no body fits the small-parts cylinder (D 31.7 x 25.4 / 57.1)", status(not any(fits)),
          {k: v["min_enclosing_d"] for k, v in out["bodies"].items()}, "min enclosing D > 31.7 for every body")
    # ---- protrusions
    prot = []
    sculpt = hasattr(M.skin, "sculpt")
    if sculpt:
        # (sculpt, wheel_drive 'dish': no knob; the spinning part above the umbrella is the sculpted cap, the yarn
        # ball's centre r cap_r with the finger dish in it - the whole cap is the protrusion; the skid rings at
        # r >= cap_r + cap_gap + 1.2 - rib_w / 2 stay outside the region)
        prot.append(vertical_protrusion("cap", "wheel", M.wheel, disc((0.0, 0.0), M.skin.cap_r + 0.3),
                                        p.z_umb_top + p.z_lift + 0.02, M.wheel.bounding_box()[5], F,
                                        notes="sculpted spinning cap (dish drive), 50 N horizontal at its top, "
                                              "wheel frame"))
    elif M.wheel.bounding_box()[5] > p.z_umb_top + p.z_lift + 1.0:          # a protruding knob (not a finger well)
        prot.append(vertical_protrusion("knob", "wheel", M.wheel,
                                        disc((p.r_k, 0.0), p.knob_d / 2 + p.knob_root_fillet + 0.6),
                                        p.z_umb_top + p.z_lift + 0.02, M.wheel.bounding_box()[5], F,
                                        notes="50 N horizontal at the knob top, wheel frame"))
    low_reliefs = []
    if sculpt:
        # (sculpt: no body-top plane - z_roof1 is the classic roof, the sculpt frame above it is one piece.  The parts
        # standing up on the organic body are found by their prominence: a part of the frame above z that merges
        # into the main body only below z; >= 3 mm tall above that root it is a tower (paws ...).  Walked down to
        # just above the posts' tops)
        z_lo = max(p.post_z1, p.z_band1) + p.z_lift + 0.25
        for d in summit_parts(M.frame, z_lo):
            q, z0, ztop = d["comp"], d["root_z"], d["summit_z"]
            bb = q.bounding_box()
            c = ((bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2)
            if d["h"] >= 3.0:
                # its own footprint (grown 0.5), minus the rest of the body above the root: the root section is the
                # part's alone
                rest = M.frame.trim_by_plane((0, 0, 1), z0) - q
                reg = g2.difference(g2.grow(q.project(), 0.5, 0.02), rest.project()) if not rest.is_empty() \
                    else g2.grow(q.project(), 0.5, 0.02)
                prot.append(vertical_protrusion(f"frame tower@({c[0]:.1f},{c[1]:.1f})", "frame", M.frame, reg,
                                                z0 + 0.02, ztop, F,
                                                notes=f"part standing on the sculpted body from its root z {z0:.2f} "
                                                      f"(where it merges into the body) to z {ztop:.2f}, 50 N at "
                                                      "its top"))
            elif d["h"] >= 1.0:
                low_reliefs.append({"centre": rl(c, 1), "root_z": round(z0, 2), "height_mm": round(d["h"], 2),
                                    "volume_mm3": round(q.volume(), 1)})
    else:
        z0 = p.z_roof1 + 0.05
        up = M.frame.trim_by_plane((0, 0, 1), z0)
        for q in up.decompose():
            bb = q.bounding_box()
            h = bb[5] - z0
            c = ((bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2)
            if h >= 3.0:
                reg = g2.grow(q.project(), 0.5, 0.02)
                prot.append(vertical_protrusion(f"frame tower@({c[0]:.1f},{c[1]:.1f})", "frame", M.frame, reg, z0,
                                                bb[5], F,
                                                notes="part standing on the body top (paw ...), 50 N at its top"))
            else:
                low_reliefs.append({"centre": rl(c, 1), "height_mm": round(h, 2), "volume_mm3": round(q.volume(), 1)})
    for c, nm in ((p.O, "post O"), (p.P, "post P")):
        prot.append(vertical_protrusion(nm, "frame", M.frame, disc(c, p.post_r + p.post_root_fillet + 0.3),
                                        p.z_bp + 0.02, p.post_z1, F,
                                        notes="hidden; 50 N side yank on the moving body applied at the post top"))
    if sculpt:
        # (sculpt: the classic Body2D is not what covers the head - the sculpted head is the exposed top.  Hidden =
        # where the frame lies over the head's band / legs: the frame's plan above the band's bottom outside the
        # head's blob (the legs under the chest); lobes shorter than 3 mm are bumps of the sculpted outline)
        hid = g2.difference(M.frame.trim_by_plane((0, 0, 1), p.z_band0 + p.z_lift).project(),
                            g2.grow(M.skin.head_blob(), 0.5, 0.01))
        prot += inplane_protrusions("head", M.head, silhouette(M.head), 20.0, F, hidden=hid, label="head ",
                                    min_len=3.0, drop_slivers=True)
    else:
        prot += inplane_protrusions("head", M.head, silhouette(M.head), 20.0, F, hidden=M.sections["body2d"],
                                    label="head ")
    prot += inplane_protrusions("frame", M.frame, silhouette(M.frame.trim_by_plane((0, 0, 1), p.z_bp + 0.7)),
                                12.0, F, label="frame ", drop_slivers=sculpt)
    out["protrusions"] = prot
    out["low_reliefs_on_body_top"] = low_reliefs
    for r in prot:
        if r.get("hidden") or r.get("too_short"):
            continue
        ok = r["root_ok"] and r["stress_ok"]
        frag = r["fragment_if_snapped"]
        R.add(f"V10.protrusion.{r['name'].replace(' ', '_')}", f"protrusion {r['name']} ({r['kind']}, {r['body']})",
              status(ok), {"root_mm": r["root_dims_mm"], "sigma_max_MPa": r["sigma_max_MPa"]},
              f"root >= {SPEC['root_long']} x {SPEC['root_short']}, sigma < {SPEC['stress_max']} MPa at 50 N",
              length_mm=r["length_mm"], worst_station=r["worst_station"],
              fragment_fits_small_parts=frag.get("fits_small_parts_cylinder"), notes=r["notes"])
    # ---- thin back-plate panels
    panels = thin_panels(M.frame, p.z_bp + p.rib_h + 0.15, F, head=M.head, fill_holes=not sculpt)
    if sculpt:
        # (sculpt: the plan keeps its holes, so the wheel's pocket (post O at its centre) is a plate-only region too.
        # It is not the panel this check is about - classic builds fill it as a hole of the body - and its far point
        # falls on post O, so its cantilever numbers mean nothing: listed, not checked)
        out["panels_not_checked"] = [dict(pn, reason="not under the head (the wheel's pocket around post O)")
                                     for pn in panels if (pn["fraction_under_head"] or 0.0) < 0.5]
        panels = [pn for pn in panels if (pn["fraction_under_head"] or 0.0) >= 0.5]
    out["panels"] = panels
    for i, pn in enumerate(panels):
        warn = pn["sigma_MPa"] >= SPEC["stress_max"]
        if sculpt:
            t_ = pn["thickness_mm"]
            s3 = pn["sigma_MPa"] * (t_ / (t_ + 1.0)) ** 2 if t_ > 0 else float("nan")
            crit = ("plate cantilever under 50 N normal at the far point < 10 MPa (warn level: the panel lies under "
                    "the head, which bears on the back ribs and post P; the cushion encloses the panel, so the "
                    "cantilever from its nearest support is an upper bound)")
            fix = (f"the {t_:.1f} mm plate under the head carries post P and is the thinnest load-bearing frame "
                   f"part.  A plate 1.0 thicker (z_bp + 1.0, every mechanism level up 1.0 under the sculpt) -> sigma "
                   f"x (t / (t + 1))^2 = {s3:.0f} MPa; or accept and add an inspection note.")
        else:
            crit = ("plate cantilever under 50 N normal at the far edge < 10 MPa (warn level: the panel lies under the "
                    "head; load reaches it through the head's back ribs)")
            fix = ("the 2.0 mm plate behind the head is the weakest structural element (est. crack at "
                   "~100 N on the top edge; the head post P stands on it).  Raise every Z level by 1.0 "
                   "(plate 3.0): sigma x (2/3)^2 -> ~17 MPa, depth 19.3 mm; or accept and add an "
                   "inspection note.")
        R.add(f"V10.back_panel_{i}", "back-plate-only panel (cantilever from the body; carries the head post)",
              "warn" if warn else "pass", {"sigma_MPa": pn["sigma_MPa"], "L_mm": pn["cantilever_L_mm"],
                                           "t_mm": pn["thickness_mm"]},
              crit, panel=pn, proposed_fix=fix)
    if sculpt:
        # ---- (sculpt) the yarn ball's static ring over the wheel's umbrella: the frame's thinnest designed overhang
        # (>= 2.0 by design) and the wheel's capture upwards
        sk = M.skin
        ring_r = [float(r) for r in np.arange(sk.cap_r + sk.cap_gap + 1.2, p.R_u - 1.0 + 1e-6, sk.ring_pitch)]
        rg = ring_thickness(M.frame, sk.cap_r + sk.cap_gap, p.R_u + p.gap_xy, p.z_umb_top + p.z_lift + 0.05, F,
                            r_load=min(ring_r) if ring_r else sk.cap_r + sk.cap_gap)
        out["static_ring"] = rg
        ok = rg["t_min_mm"] is not None and rg["n_open"] == 0 and rg["t_min_mm"] >= 2.0 - 1e-6
        R.add("V10.static_ring", "static yarn-ball ring over the wheel's umbrella: thickness (sculpt)",
              status(True, not ok),
              {"t_min_mm": rg["t_min_mm"], "at": rg.get("at"), "open_columns": rg["n_open"],
               "pull_out_sigma_MPa": rg.get("pull_out_sigma_MPa")},
              "frame over the annulus cap_r + cap_gap .. R_u + gap_xy is closed and >= 2.0 thick (warn level: the "
              "design value); it is what keeps the wheel in", ring=rg)
    return out


def make_series(M, fast: bool) -> list[dict]:
    p = M.params
    pb = p.psi_b
    nh = 21 if fast else 41
    dphi = 10.0 if fast else 5.0
    series = []
    for phi in (90.0, 270.0):
        series.append({"name": f"head_phi{phi:.0f}", "mover": "head", "fixed": (phi, 0.0),
                       "poses": [(phi, float(s)) for s in np.linspace(-pb, pb, nh)]})
    for psi in (-pb, 0.0, pb):
        series.append({"name": f"wheel_psi{psi:+.2f}", "mover": "wheel", "fixed": (0.0, psi),
                       "poses": [(float(f), psi) for f in np.arange(0.0, 360.0, dphi)]})
    return series


def group_clusters(clusters: list[dict]) -> list[dict]:
    """Group clusters of the same mover / neighbour / severity whose worst cells lie within 6 mm, counting the
    left / right mirror twin (x -> -x) as the same feature."""
    groups = []
    for c in clusters:
        a = np.array(c["worst_cell"])
        for g in groups:
            h = g[0]
            if h["mover"] != c["mover"] or h["neighbour"] != c["neighbour"] or h["severity"] != c["severity"]:
                continue
            b = np.array(h["worst_cell"])
            d = min(np.linalg.norm(a - b), np.linalg.norm(a - b * np.array([-1.0, 1.0])))
            if d < 6.0 and abs(h["worst_z"] - c["worst_z"]) <= 3.0:
                g.append(c)
                break
        else:
            groups.append([c])
    return groups


def pinch_closeups(M, W: World, ser: dict, c: dict, path: Path) -> str | None:
    """Two cropped renders (widest / narrowest pose) around the worst cell of a pinch cluster."""
    try:
        from render import render_views
    except Exception:
        return None
    w = c["_worst"]
    x = np.asarray(w["x"])
    th = math.degrees(math.atan2(x[1] - 15.0, x[0]))
    box = Manifold.cube((34.0, 34.0, 30.0)).translate((float(x[0]) - 17.0, float(x[1]) - 17.0, -1.0))
    cols = render_colors(M)
    imgs = []
    fphi, fpsi = ser["fixed"]
    for t in (w["tmax"], w["tmin"]):
        phi, psi = ser["poses"][t]
        if ser["mover"] == "head":
            B = M.posed(fphi, psi)
        else:
            B = M.posed(phi, fpsi)
        parts = {k: (B[k] ^ box, cols.get(k, "#cccccc")) for k in B if not (B[k] ^ box).is_empty()}
        pngs = render_views(parts, path.parent / "_closeup_tmp" / f"c{t}", views=((50, 0, th + 90.0),), size=(700, 600))
        imgs.append(pngs[0])
    ims = [Image.open(i).convert("RGB") for i in imgs]
    out = Image.new("RGB", (sum(i.width for i in ims), max(i.height for i in ims)), "white")
    xo = 0
    for i in ims:
        out.paste(i, (xo, 0))
        xo += i.width
    ImageDraw.Draw(out).text((10, 10), "left: widest   right: narrowest", fill=(0, 0, 0))
    out.save(path)
    for i in imgs:
        try:
            Path(i).unlink()
        except OSError:
            pass
    try:
        (path.parent / "_closeup_tmp").rmdir()
    except OSError:
        pass
    return str(path)


def run_v12(R: Report, M, W: World, fast: bool, rep_dir: Path, tag: str, render: bool = True) -> dict:
    out = {}
    for old_png in rep_dir.glob(f"safety_{tag}_pinch_*.png"):
        try:
            old_png.unlink()
        except OSError:
            pass
    series = make_series(M, fast)
    sd = {s["name"]: s for s in series}
    audit = pinch_audit(W, series, R)
    clusters = cluster_pinch(W, series, audit)
    groups_all = group_clusters(clusters)
    groups = [g for g in groups_all if sum(x["n_cells"] for x in g) >= MIN_CELLS]
    isolated = [x for g in groups_all if sum(y["n_cells"] for y in g) < MIN_CELLS for x in g]
    out["series"] = {s["name"]: {"mover": s["mover"], "fixed_pose": s["fixed"], "n_poses": len(s["poses"]),
                                 **{k: v for k, v in audit[s["name"]].items() if k != "violations"}}
                     for s in series}
    out["clusters"] = [{k: v for k, v in c.items() if k != "_worst"} for c in clusters]
    for gi, g in enumerate(groups):
        c = min(g, key=lambda x: ({"high": 0, "medium": 1, "low": 2}[x["severity"]], x["gap_min"]))
        png = rep_dir / f"safety_{tag}_pinch_{gi:02d}.png"
        plot_cluster(W, sd[c["series"]], c, png,
                     f"{c['mover']} vs {c['neighbour']} - {c['kind']}\nworst cell {c['worst_cell']} z {c['worst_z']}: "
                     f"gap {c['gap_min_at_worst_cell']} .. {c['gap_max_at_worst_cell']} mm")
        st = "fail" if c["severity"] in ("high", "medium") else "warn"
        closeup = None
        if c["severity"] == "high" and render:
            closeup = pinch_closeups(M, W, sd[c["series"]], c, rep_dir / f"safety_{tag}_pinch_{gi:02d}_3d.png")
        R.add(f"V12.pinch_{gi:02d}", f"{c['mover']} vs {c['neighbour']} at ({c['worst_cell'][0]:.1f}, "
              f"{c['worst_cell'][1]:.1f}), z {c['z_range'][0]}-{c['z_range'][1]}", st,
              {"gap_min": c["gap_min_at_worst_cell"], "gap_max": c["gap_max_at_worst_cell"], "severity": c["severity"]},
              "exposed gap constant (<= 0.1 variation), always < 2.0, or always >= 12 (SPEC V12)",
              kind=c["kind"], series=sorted({x["series"] for x in g}), cells=int(sum(x["n_cells"] for x in g)),
              cells_shear=int(sum(x["n_cells_shear"] for x in g)), xy_bbox=c["xy_bbox"],
              pose_at_gap_min=c["pose_at_gap_min"], pose_at_gap_max=c["pose_at_gap_max"], plot=str(png),
              closeup_3d=closeup, proposed_fix=(SCULPT_FIXES if hasattr(M.skin, "sculpt") else FIXES).get(
                  (c["mover"], c["neighbour"]), ""),
              locations=[{"worst_cell": x["worst_cell"], "z_range": x["z_range"], "series": x["series"],
                          "gap": [x["gap_min_at_worst_cell"], x["gap_max_at_worst_cell"]]} for x in g])
    if isolated:
        R.add("V12.pinch_isolated", f"isolated violating cells (clusters < {MIN_CELLS} cells; usually the fringe of a "
              "listed pinch or a nearly constant far gap)", "warn", len(isolated),
              "reported for completeness, not counted as separate pinch points",
              cells=[{"mover": x["mover"], "neighbour": x["neighbour"], "worst_cell": x["worst_cell"],
                      "z": x["worst_z"], "gap": [x["gap_min_at_worst_cell"], x["gap_max_at_worst_cell"]],
                      "severity": x["severity"]} for x in isolated])
    if not groups:
        R.add("V12.pinch", "pinch audit", "pass", 0, "no exposed gap varies across the 2-12 mm band")
    out["n_groups"] = len(groups)
    return out


def exposure_masks(W: World, poses) -> list[list[np.ndarray]]:
    """Per pose, per level: cells a probe sphere can touch (within r of an accessible probe centre)."""
    res = []
    for phi, psi in poses:
        acc = W.accessible(phi, psi)
        res.append([(_edt(a, W.h) <= W.touch) if a.any() else np.zeros_like(a) for a in acc])
    return res


def touched(W: World, masks, poses, body: str, P3: np.ndarray) -> np.ndarray:
    zs = np.asarray(W.zs)
    k = np.clip(np.rint((P3[:, 2] - zs[0]) / (zs[1] - zs[0])).astype(int), 0, len(zs) - 1)
    hit = np.zeros(len(P3), bool)
    for (phi, psi), mk in zip(poses, masks):
        xy = W.to_world(body, P3[:, :2], phi, psi)
        for kk in np.unique(k):
            sel = k == kk
            hit[sel] |= W.lookup_acc(mk[kk], xy[sel])
    return hit


def _dedupe_xy(items: list[dict], tol: float = 1.0) -> list[dict]:
    """Keep the first item per xy location (merging Z levels); records the z range."""
    out = []
    for it in items:
        for o in out:
            if o["body"] == it["body"] and np.linalg.norm(np.array(o["at"][:2]) - np.array(it["at"][:2])) < tol:
                o["z_levels"] = sorted(set(o.get("z_levels", [o.get("z")]) + [it.get("z")]))
                break
        else:
            out.append(dict(it))
    return out


def run_edges(R: Report, M, W: World) -> dict:
    p = M.params
    pb = p.psi_b
    poses = [(0.0, 0.0), (0.0, -pb), (0.0, pb), (90.0, 0.0), (180.0, 0.0), (270.0, 0.0)]
    masks = exposure_masks(W, poses)
    out = {"corners": {}, "sharp": {}}
    # (a) plan corners of exposed outlines, every 1.0 mm in Z
    worst_r = {}
    sculpt = hasattr(M.skin, "sculpt")
    if sculpt:
        out["corners_sloped"] = {}
    for b, body in M.bodies.items():
        bb = body.bounding_box()
        found, sloped = [], []
        for z in np.arange(math.floor(bb[2]) + 0.5, bb[5], 1.0):
            k = int(np.argmin(np.abs(np.asarray(W.zs) - z)))

            def exp_fn(tip, b=b, z=z):
                return bool(touched(W, masks, poses, b, np.array([[tip[0], tip[1], z]]))[0])
            cs_z = convex_corner_report(body.slice(float(z)), SPEC["edge_r_ext"], exp_fn)
            if sculpt and cs_z:
                # (sculpt: the seams are vertical cuts through the sloping sculpt surface, so a slice also shows a
                # sharp 2-D corner where it crosses a SLOPED edge (seam wall x sculpt surface) - its 3-D sharpness is
                # the dihedral, which the ball test (b) measures.  A vertical edge persists: keep a corner only if the
                # slice 0.5 above or below has one within 0.3 mm)
                nb = [np.array(c["at"]) for dz in (-0.5, 0.5) if bb[2] < z + dz < bb[5]
                      for c in convex_corner_report(body.slice(float(z + dz)), SPEC["edge_r_ext"])]
                for c in cs_z:
                    c["z"] = float(z)
                    if any(np.linalg.norm(np.array(c["at"]) - a) <= 0.3 for a in nb):
                        found.append(c)
                    else:
                        sloped.append(c)
                continue
            for c in cs_z:
                c["z"] = float(z)
                found.append(c)
        out["corners"][b] = found
        if sculpt:
            out["corners_sloped"][b] = sloped
        worst_r[b] = min((c["est_corner_r_mm"] for c in found), default=None)
    allc = [(b, c) for b, lst in out["corners"].items() for c in lst]
    sharp_c = [(b, c) for b, c in allc if c["est_corner_r_mm"] < SPEC["edge_r_min"] - 0.05]
    soft_c = [(b, c) for b, c in allc if SPEC["edge_r_min"] - 0.05 <= c["est_corner_r_mm"] < SPEC["edge_r_ext"] - 0.1]
    if sculpt:
        n_sl = {b: len(v) for b, v in out["corners_sloped"].items()}
        fix_c = ("round the listed near-vertical convex corners (the seams the head's swept envelope, the stop pads "
                 "and the neck cut leave in the sculpt; r >= 1.0, exterior 1.5).  Removing material only increases "
                 "clearances.") if (sharp_c or soft_c) else ""
        extra = {"sloped_edge_corners_not_counted": n_sl,
                 "sloped_note": "single-slice corners where a vertical seam meets the sloping sculpt surface: their "
                                "sharpness is the 3-D dihedral, judged by V12.sharp_points"}
    else:
        fix_c = ("round the listed convex plan corners: FaceMid2D = open(FaceUp - RoofSweepInv, 2.0) "
                 "(r 1.0; today 1.0 -> r 0.5 at the I3 slot mouth) and round the exposed fill-finger tips at "
                 "the cavity mouth (Fill2D open 2.0 / r 1.0 convex rounding outside the stop pads).  Removing "
                 "material only increases clearances.")
        extra = {}
    R.add("V12.corners", "exposed convex plan corners (vertical edges) r >= 1.0 (exterior >= 1.5)",
          "fail" if sharp_c else ("warn" if soft_c else "pass"),
          {"below_1.0": len(sharp_c), "1.0_to_1.5": len(soft_c), "min_r_by_body": worst_r},
          "no exposed convex corner sharper than r 1.0; r 1.0-1.5 is a warning",
          proposed_fix=fix_c,
          worst=_dedupe_xy([{"body": b, **c} for b, c in sorted(allc, key=lambda t: t[1]["est_corner_r_mm"])])[:12],
          **extra)
    # (b) sharp points: ball fraction at convex mesh corners / acute edges on the touchable surface
    allpts = []
    for b, body in M.bodies.items():
        P3, N3, st = sharp_candidates(body)
        if len(P3) == 0:
            out["sharp"][b] = {"stats": st, "points": []}
            continue
        probe = P3 + N3 * (W.r + 0.1)
        exp = touched(W, masks, poses, b, probe) | touched(W, masks, poses, b, P3)
        Pe = P3[exp]
        fr = ball_fraction(body, Pe) if len(Pe) else np.zeros(0)
        pts = [{"at": rl(q, 2), "ball_fraction": round(float(f), 3)} for q, f in zip(Pe, fr)]
        pts.sort(key=lambda d: d["ball_fraction"])
        st.update({"exposed_candidates": int(exp.sum())})
        out["sharp"][b] = {"stats": st, "points": pts[:25]}
        allpts += [(b, d) for d in pts]
    bad = [(b, d) for b, d in allpts if d["ball_fraction"] < SPEC["sharp_fail"]]
    meh = [(b, d) for b, d in allpts if SPEC["sharp_fail"] <= d["ball_fraction"] < SPEC["sharp_warn"]]
    R.add("V12.sharp_points", "sharp points / knife edges on the touchable surface (1 mm ball volume fraction)",
          "fail" if bad else ("warn" if meh else "pass"),
          {"below_0.15": len(bad), "0.15_to_0.20": len(meh),
           "min_fraction": round(min((d["ball_fraction"] for _, d in allpts), default=0.5), 3)},
          "fraction >= 0.20 (square edge 0.25, square corner 0.125); < 0.15 fails",
          worst=[{"body": b, **d} for b, d in sorted(allpts, key=lambda t: t[1]["ball_fraction"])[:12]])
    return out


def run_design(R: Report, M) -> dict:
    p = M.params
    S = M.sections
    out = {}
    feats = []
    sculpt = hasattr(M.skin, "sculpt")
    if sculpt:
        # (sculpt: no flat feature planes - the face front layer z_front1, the paw tops paw_z1 and the decor top
        # z_decor1 are classic levels; slicing the organic surface there finds bumps and crevices of the sculpt, not
        # features.  The skin has no face features; the sculpt carries its own relief)
        out["surfaces_not_scanned"] = {"face top": p.z_front1 + p.z_lift, "paw tops": p.paw_z1,
                                       "decor top": p.z_decor1,
                                       "reason": "sculpt skin: no flat feature planes; the sculpted relief is the "
                                                 "owner's mesh (face_features() is empty)"}
    else:
        feats += surface_features(M.head, p.z_front1 + p.z_lift, "face top")
        feats += surface_features(M.frame, p.paw_z1, "paw tops")
        feats += surface_features(M.frame, p.z_decor1, "decor top")
    feats += [f for f in surface_features(M.frame, p.z_bp, "back plate") if f["type"] == "deboss"]
    wf = surface_features(M.wheel, p.z_umb_top + p.z_lift, "ball top", deep=0.9)
    wg = [f for f in wf if f["type"] == "deboss"]
    if wg:
        feats.append({"surface": "ball top", "type": "deboss", "n_grooves": len(wg),
                      "width_mm": round(float(np.median([f["width_mm"] for f in wg])), 3),
                      "stroke_width_mm": round(float(np.median([f["stroke_width_mm"] for f in wg])), 3),
                      "depth_mm": round(float(np.median([f["depth_mm"] for f in wg])), 3),
                      "area_mm2": round(float(sum(f["area_mm2"] for f in wg)), 1), "centroid": [0.0, 0.0]})
    out["features"] = feats
    raised = [f for f in feats if f["type"] == "raised"]
    low_h = [f for f in raised if f["height_mm"] < SPEC["feat_raise_min"] - 0.06]
    R.add("DR.raised_height", "raised features >= 0.6 high (3 layers)", status(True, bool(low_h)),
          [{"at": f["centroid"], "h": f["height_mm"]} for f in raised],
          ">= 0.6 (0.05 measurement step)", low=low_h)
    thin = [f for f in feats if f.get("stroke_width_mm", 9) < SPEC["feat_line_min"] - 0.02]
    R.add("DR.line_width", "grooves / lines >= 0.8 wide (2 nozzle widths) so they survive slicing and read",
          status(True, bool(thin)),
          [{"surface": f["surface"], "at": f["centroid"], "w": f.get("stroke_width_mm")} for f in thin],
          ">= 0.8 mm stroke width", n_thin=len(thin))
    shallow = [f for f in feats if f["type"] == "deboss" and f["depth_mm"] < SPEC["feat_deboss_min"] - 0.02]
    R.add("DR.deboss_depth", "debossed features >= 0.4 deep (2 layers at 0.2)", status(True, bool(shallow)),
          [{"surface": f["surface"], "at": f["centroid"], "d": f["depth_mm"]} for f in shallow],
          ">= 0.4 mm", n_shallow=len(shallow))
    if sculpt:
        return _design_sculpt(R, M, out)
    # ---- face proportions (generic: from Face2D / FaceUp2D and the raised features)
    face = to_shp(S["faceup2d"])
    fb = face.bounds
    face_w, face_h = fb[2] - fb[0], fb[3] - fb[1]
    eyes = sorted([f for f in raised if f["surface"] == "face top"], key=lambda f: -f["area_mm2"])[:2]
    out["face"] = {"faceup_w": round(face_w, 2), "faceup_h_incl_ears": round(face_h, 2)}
    if len(eyes) == 2:
        ed = float(np.mean([max(f["bbox_mm"]) for f in eyes]))
        ex = abs(eyes[0]["centroid"][0] - eyes[1]["centroid"][0])
        ey = float(np.mean([f["centroid"][1] for f in eyes]))
        # head-circle centre estimate: centre of the largest inscribed circle of FaceUp2D
        mic = np.asarray(shapely.maximum_inscribed_circle(face, 0.01).coords)
        hc, hr = mic[0], float(np.linalg.norm(mic[1] - mic[0]))
        width_at_eyes = float(np.ptp(np.asarray(shapely.get_coordinates(
            face.intersection(LineString([(fb[0] - 1, ey), (fb[2] + 1, ey)]))))[:, 0]))
        d = {"eye_d": round(ed, 2), "eye_spacing_cc": round(ex, 2), "face_width_at_eyes": round(width_at_eyes, 2),
             "eye_d_over_face_w": round(ed / width_at_eyes, 3), "spacing_over_face_w": round(ex / width_at_eyes, 3),
             "head_circle_centre": rl(hc, 2), "head_circle_r": round(hr, 2),
             "eye_line_below_head_centre_over_r": round((hc[1] - ey) / hr, 3)}
        out["face"].update(d)
        small = d["eye_d_over_face_w"] < 0.25
        high = d["eye_line_below_head_centre_over_r"] < 0.15
        R.add("DR.eyes", "kawaii eye size / placement", status(True, small or high), d,
              "eye D >= 0.25 x face width; eye line >= 0.15 R below the head-circle centre (big, low, wide-set eyes)",
              suggestion="eyes D 8.5 domes 0.8 tall at C_h + (+-7.2, -2.8) with D 2.6 highlight dimples at (+1.5, +1.5); "
                         "this keeps every edge >= 3 mm inside FaceUp2D" if (small or high) else "")
    nose = [f for f in raised if f["surface"] == "face top" and f not in eyes]
    if nose:
        n = nose[0]
        nw = max(n["bbox_mm"])
        R.add("DR.nose", "nose readable at arm's length", status(True, nw < 3.0),
              {"nose_bbox_mm": n["bbox_mm"], "nose_w_over_face_w": round(nw / face_w, 3)},
              "nose width >= 3.0 mm (about 0.1 x face width)",
              suggestion="rounded-triangle nose 4.0 x 2.8, raised 0.6, at C_h + (0, -4.6)" if nw < 3.0 else "")
    # ---- head vs ball, ears, giggle
    ball_d = 2 * p.R_u
    hb = {"face_disc_w": round(face_w, 2), "ball_d": ball_d, "ratio": round(face_w / ball_d, 3)}
    R.add("DR.head_vs_ball", "head reads as the biggest shape (kawaii: big head, small body)",
          status(True, face_w < ball_d), hb, "face width >= ball diameter",
          suggestion="grow the face disc to r 17.5 with C_h = P + (0, 12.0) (chin stays put; I_h rises ~30 %, still "
                     "inside 4-8e-6 - re-run V13/V4), or tint the ball a softer colour so the face dominates"
          if face_w < ball_d else "")
    head_sil = to_shp(silhouette(M.head))
    hsb = head_sil.bounds
    crown = face.intersection(LineString([(0.0, fb[1]), (0.0, fb[3] + 5)]))
    crown_y = float(np.asarray(shapely.get_coordinates(crown))[:, 1].max()) if not crown.is_empty else fb[3]
    ear_rise = hsb[3] - crown_y
    Py = p.P[1]
    tip_r = float(np.max(np.hypot(np.asarray(shapely.get_coordinates(head_sil))[:, 0],
                                  np.asarray(shapely.get_coordinates(head_sil))[:, 1] - Py)))
    giggle = {"ear_rise_above_crown_mm": round(ear_rise, 2), "ear_rise_over_head_r": round(ear_rise / 16.0, 3),
              "farthest_point_from_P_mm": round(tip_r, 2),
              "tip_travel_each_way_mm": round(tip_r * math.radians(p.psi_b), 2),
              "tip_travel_p2p_mm": round(2 * tip_r * math.radians(p.psi_b), 2)}
    out["ears_giggle"] = giggle
    R.add("DR.ears", "ears tall enough to read as cat ears", status(True, ear_rise < 6.0), giggle,
          "ear tips >= 6 mm above the crown (about 0.35-0.5 x head radius)",
          suggestion="ear tip at C_h + 24.5 (sin 30, cos 30) with base at +-12 / +-50 deg and rounding (+)2.0 (-)0.8; "
                     "re-check I_h (+~4 %) and the ear root (still >= 8 x 5)" if ear_rise < 6.0 else "")
    R.add("DR.giggle", "head shiver amplitude visible as a giggle", status(True, giggle["tip_travel_p2p_mm"] < 8.0),
          {"ear_tip_travel_p2p_mm": giggle["tip_travel_p2p_mm"]}, ">= 8 mm peak-to-peak at the ear tips")
    # ---- colour swap (SPEC 6: swap at z 15.6, back at 16.2)
    # (fix round 1: the face front layer was raised to z_front1 17.7; the swap follows it: 0.2 above the face top
    # until 0.2 above the feature tops)
    zc0, zc1 = p.z_front1 + p.z_lift + 0.2, p.z_feat + p.z_lift + 0.2
    sw = {}
    for k, b in M.bodies.items():
        a = b.trim_by_plane((0, 0, 1), zc0).trim_by_plane((0, 0, -1), -zc1)
        sw[k] = round(float(a.project().area()) if not a.is_empty() else 0.0, 1)
    mouth_like = [f for f in feats if f["surface"] == "face top" and f["type"] == "deboss"]
    R.add("DR.colour_swap", f"optional colour swap z {zc0:.1f}-{zc1:.1f} colours exactly the face features",
          status(True, sw.get("frame", 0) > 1.0 or bool(mouth_like)), {"coloured_top_area_mm2": sw},
          "only the eyes / nose / mouth change colour",
          note="the swap also colours the paw tops (frame) and a band of the knob; debossed features (mouth, blush, "
               "inner ears) stay face-coloured",
          suggestion="make the mouth a raised 0.6 x 0.9 line, and drop the paw top to z 15.4 (or start the swap at "
                     "z 16.05 with 0.7 tall eyes / nose) so the swap catches only the face")
    return out


def _design_sculpt(R: Report, M, out: dict) -> dict:
    """Design review, face / proportions part, for a sculpt skin: the face is the owner's fixed sculpt (no FaceUp2D
    front layer, no face features, one colour), so only what the bodies show is measured: the head's plan (its
    blob: ears and bow included) against the visible yarn ball, and the giggle at the head's farthest point."""
    p = M.params
    sk = M.skin
    na = "n/a: sculpted face - "
    R.add("DR.eyes", "kawaii eye size / placement", "n/a", None, "eye D >= 0.25 x face width (classic face features)",
          note=na + "the eyes are relief of the owner's sculpt, not separate features (face_features() is empty); the "
                    "classic rule measures raised pieces on the z_front1 face layer, which is not built")
    R.add("DR.nose", "nose readable at arm's length", "n/a", None, "nose width >= 3.0 mm (classic face features)",
          note=na + "no separate nose feature (see DR.eyes)")
    R.add("DR.ears", "ears tall enough to read as cat ears", "n/a", None,
          "ear tips >= 6 mm above the crown (classic FaceUp2D crown, head radius 16)",
          note=na + "the crown is taken from the classic FaceUp2D outline, which is not built; the sculpted head's "
                    "plan top is its bow, not an ear tip")
    head_sil = to_shp(silhouette(M.head))
    hbb = to_shp(sk.head_blob()).bounds
    face_w = hbb[2] - hbb[0]
    # the visible yarn ball: the sculpt is scaled so that its ball (r 15.8 in the source) is r 18 (skin.scale); the
    # wheel's own umbrella (R_u 15) hides under it
    ball_d = 2.0 * getattr(sk, "ball_r", 15.8 * sk.scale)
    hb = {"head_blob_w": round(face_w, 2), "ball_d": round(ball_d, 2), "ratio": round(face_w / ball_d, 3)}
    out["face"] = {"head_blob_w": round(face_w, 2), "head_blob_h": round(hbb[3] - hbb[1], 2)}
    R.add("DR.head_vs_ball", "head reads as the biggest shape (kawaii: big head, small body)",
          status(True, face_w < ball_d), hb, "sculpted head width (plan, ears and bow included) >= ball diameter")
    Py = p.P[1]
    xy = np.asarray(shapely.get_coordinates(head_sil))
    tip_r = float(np.max(np.hypot(xy[:, 0], xy[:, 1] - Py)))
    giggle = {"farthest_point_from_P_mm": round(tip_r, 2),
              "tip_travel_each_way_mm": round(tip_r * math.radians(p.psi_b), 2),
              "tip_travel_p2p_mm": round(2 * tip_r * math.radians(p.psi_b), 2)}
    out["ears_giggle"] = giggle
    R.add("DR.giggle", "head shiver amplitude visible as a giggle", status(True, giggle["tip_travel_p2p_mm"] < 8.0),
          {"ear_tip_travel_p2p_mm": giggle["tip_travel_p2p_mm"]}, ">= 8 mm peak-to-peak at the ear tips")
    R.add("DR.colour_swap", "optional colour swap colours exactly the face features", "n/a", None,
          "only the eyes / nose / mouth change colour",
          note="n/a: single-colour sculpt, no swap layer (no face features, no head feature parts / frame colour "
               "masks)")
    return out


FIXES = {
    ("head", "frame"): "Cheek / roof-lobe jaw: where the roof lobes enter the head's I3 slot the slot back wall closes on "
                       "the lobe end (gap 0.55 at one bank, several mm at the other) and the slot mouth is reachable "
                       "from the side.  Make the lobe end inside the slot a circular arc about P (Body2D clipped to "
                       "r <= R_b about P in both lobe sectors, R_b ~17.5) so RoofSweepInv's back wall becomes the "
                       "concentric arc R_b + 0.55 (constant gap), let the face outline cross the body outline at ~90 "
                       "deg (locally radial to P) and round the slot-mouth corners r >= 1.0.  A cheek-only change "
                       "(Face2D U sector(P, 18.5)) was prototyped and does NOT remove the jaw.",
    ("wheel", "frame"): "Knob vs paw-lip span ends: the knob (r 6-16, z 13.3-18.3) enters each paw span with a "
                        "vertical end face -> guillotine from >= 12 mm to 1.0 mm.  Cleanest fix: replace the "
                        "protruding knob by a recessed finger well (spherical dish D 11 x 2.0 deep at r_k 11; nothing "
                        "of the wheel above z 13.3) - removes this pinch, the knob-chin squeeze and the knob "
                        "small-part risk; re-run V4 for the fingertip torque.  Mitigation if the knob stays: lead-in "
                        "cams at the span ends (lip inner radius 17 -> 22 over the last 15 deg, paw top chamfered 45 "
                        "deg down to z 13.4) and a documented V12 waiver for the user-driven knob.",
    ("wheel", "head"): "Knob vs chin: the knob passes under the chin with 2.9-4.0 mm left (3-D min 2.86).  Fixed by "
                       "the recessed finger well (see knob vs paw); otherwise needs a V12 waiver (driven by the "
                       "user's own finger, <= ~4 N tangential at 40 N mm).",
    ("head", "wheel"): "Cheek / chin vs ball rim + knob crescent: the face's lower edge diverges from the rim, so "
                       "the gap at fixed points varies 2.5-5.6 mm as the head banks.  Keep the chin-to-rim gap "
                       "< 2.0 along the whole crescent (FaceUp = Face - (BallEx (+) 0.5) only where the face is "
                       "within 4 mm of the rim, i.e. a rim-concentric chin) and remove the knob (finger well).",
}


# (sculpt skins: none of the classic features of FIXES - roof lobes, I3 slot, knob, paw lips, FaceUp chin - exist)
SCULPT_FIXES = {
    ("head", "frame"): "The sculpted head's edge is the sculpt's organic outline, not an arc about P: as it swings, "
                       "the gap between it and the static sculpt beside it (chin corners against the chest and the "
                       "yarn ball's flank, the back of the head against the recess its sweep cuts in the cushion) "
                       "opens to ~r x 2 psi_b on the trailing side and closes on the leading side.  Where a fingertip "
                       "reaches it, make that part of the head's edge a circular arc about P over the whole swing "
                       "(its distance from any fixed point is then constant, and the recess wall cut by its sweep "
                       "becomes the concentric arc + gap_xy), e.g. trim the chin corners to an arc about P; or keep "
                       "the gap out of the probe's reach (recess < ~2 mm deep) or < 2.0 at every pose.",
    ("wheel", "frame"): "Cap vs static ring: the seam r cap_r / cap_r + cap_gap cuts a sculpted surface that is not "
                        "axisymmetric, so at a fixed height the cap's section comes and goes as it turns and the gap "
                        "at a point varies around 1-2 mm (never a fingertip opening).  A level rim (the cap's and "
                        "the ring's top flattened to a common height for ~1 mm on both sides of the seam) makes it "
                        "constant 0.5.",
}


def summarize(checks: list[dict]) -> list[str]:
    out = []
    for c in checks:
        if c["status"] == "pass":
            continue
        line = f"[{c['status'].upper()}] {c['id']}: {c['name']} -> {c['measured']}"
        out.append(line)
    return out


def run(skin: str, variant: str, probe: float, fast: bool, render: bool, quiet: bool) -> dict:
    R = Report(quiet)
    M = build(skin, variant)
    p = M.params
    R.log(f"built {skin}/{variant}")
    tag = f"{skin}_{variant}"
    rep_dir = REPO / "verification" / "reports" / skin
    rep_dir.mkdir(parents=True, exist_ok=True)
    out = {"skin": skin, "variant": variant, "probe_radius_mm": probe, "fast": fast,
           "criteria": SPEC, "P": M.P}
    out["V10"] = run_v10(R, M)
    R.log("V10 done")
    zmax = max(b.bounding_box()[5] for b in M.bodies.values())
    zs = np.arange(0.25, zmax + 0.51, 0.5)
    W = World(M, zs, 0.3, 0.25, probe)
    out["V12"] = run_v12(R, M, W, fast, rep_dir, tag, render)
    R.log("V12 pinch done")
    out["V12"]["edges"] = run_edges(R, M, W)
    R.log("V12 edges done")
    out["design_review"] = run_design(R, M)
    if render:
        out["V14"] = v14_renders(M, REPO / "renders" / skin, tag, R)
        R.add("V14.renders", "front / back / three-quarter at psi -12.4, 0, +12.4 (wheel 0, 120, 240) + sections",
              status(len(out["V14"]) == 11), len(out["V14"]), "11 PNGs written", files=[r["file"] for r in out["V14"]])
    out["checks"] = R.checks
    out["summary"] = summarize(R.checks)
    out["n_pass"] = sum(c["status"] == "pass" for c in R.checks)
    out["n_warn"] = sum(c["status"] == "warn" for c in R.checks)
    out["n_fail"] = sum(c["status"] == "fail" for c in R.checks)
    if any(c["status"] == "n/a" for c in R.checks):          # (sculpt skins: checks of classic-only features)
        out["n_na"] = sum(c["status"] == "n/a" for c in R.checks)
    out["pass"] = out["n_fail"] == 0
    out["time_s"] = round(time.time() - R.t0, 1)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skin", default="kitty")
    ap.add_argument("--variant", default="nominal")
    ap.add_argument("--probe", type=float, default=2.0, help="accessibility probe sphere radius (mm)")
    ap.add_argument("--fast", action="store_true", help="half the pinch-audit poses")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    rep = run(a.skin, a.variant, a.probe, a.fast, not a.no_render, a.quiet)
    out = Path(a.out) if a.out else (REPO / "verification" / "reports" / a.skin /
                                     ("safety.json" if a.variant == "nominal" else f"safety_{a.variant}.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1, default=_json_default))
    print(json.dumps({"skin": a.skin, "variant": a.variant, "pass": rep["pass"], "n_pass": rep["n_pass"],
                      "n_warn": rep["n_warn"], "n_fail": rep["n_fail"], "time_s": rep["time_s"],
                      "failed": [c["id"] for c in rep["checks"] if c["status"] == "fail"],
                      "warned": [c["id"] for c in rep["checks"] if c["status"] == "warn"],
                      **({"n_a": [c["id"] for c in rep["checks"] if c["status"] == "n/a"]} if rep.get("n_na") else {}),
                      "report": str(out)}, indent=1))
    sys.exit(0 if rep["pass"] else 1)


if __name__ == "__main__":
    main()
