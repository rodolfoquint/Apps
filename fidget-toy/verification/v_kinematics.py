"""Check group B - 3-D kinematics, clearances, print pose and captivity (SPEC section 5: V5, V6, V7, V11).

    python3 verification/v_kinematics.py --skin kitty [--variant nominal] [-q]

Writes verification/reports/<skin>/kinematics.json (kinematics_<variant>.json for other variants) and exits
non-zero if any check FAILS (warnings do not fail).  Independent of the builder's own checks: it only uses the
documented Model API (build, posed / head_at / wheel_at, params, 2-D sections) plus exact manifold3d booleans /
min_gap, trimesh ray casting, and the exported STL for V7.

V5  3-D collision sweep.
    * frame x head : psi -psi_b..+psi_b, step <= 0.25 deg (101 poses).  Overlap volume must be 0; the stop pads
      are the only frame parts allowed to (nearly) touch and only at |psi| = psi_b.  Banking check: a little
      beyond psi_b the head must hit the pads and nothing else.
    * frame x wheel: phi 0..45 step 0.5 (one pitch) U 0..358 step 2 (knob / paws).  Overlap 0.
    * head x wheel : every C-space-free pose of the 2-D pallet C-space (SPEC 2.4 (a): c(phi, psi) =
      min_i SDF_star(Rot(-phi)(P + Rot(psi)(p_i - P))) - rp >= 0) on phi 0..44.5 step 0.5 x psi 101 poses, plus
      phi 0..358 step 2 with three free psi each (knob / face).  Overlap 0, and a 3-D shadow test:
      gap_3d >= min(c_pins, pallet<->plate Z gap) - 0.02 (only the pallet tips may be the nearest wheel contact).
    * Z-play corners (adversarial, warning only): head and wheel at opposite ends of their measured axial play.
V6  Minimum clearances per interface (exact manifold3d min_gap on Z-band / XY crops; journals also as a radial
    range from slices; Z gaps from a vertical ray census on <= 0.05 mm^2 samples).  Criteria from SPEC V6 / 3.2,
    journals / ridge / rib values follow the variant's parameters (loose: 0.40 / 0.40 / 0.45).
V7  Print pose on the EXPORTED combined STL (stl/<skin>/purrbobble_<skin>_<variant>.stl): three watertight shells,
    identical to the model's print pose, pairwise disjoint, global min gap >= 0.35, pallet<->tooth >= 1.3,
    floating bodies clear of the first layers.
V11 Captivity: each moving body displaced 1.0 mm in +-X, +-Y, +-Z and tilted +-3 deg about X / Y (pivots: journal
    centre at ridge height and the body's centre of mass) at 20 poses must interfere with the frame; repeated with
    the V-ridges deleted from the posts.  Free play by bisection (with / without ridges), the stop that limits a
    ridge-less lift (head: roof, wheel: paw lips, <= 1.0 mm), and a lift-ladder escape search (lift beyond the
    stop with lateral offsets and tilts must always interfere).

Sculpt skins (the skin has a sculpt() method; purrbobble/sculpt.py builds the three bodies from the owner's mesh
around the unchanged mechanism core): no roof, I3 slot, face layers, paw lips or knob.  Their checks are replaced by
the equivalent checks of what is built: head body above the band <-> frame (XY slices + 3-D, swept), cap <-> static
yarn ring, the umbrella rim / skid rings / cap <-> frame, the frame covers over the band and the static ring over the
skid rings as the designed Z gaps and lift stops (gated on ``sculpt``; classic skins are unchanged).  Their bodies are
~10x denser meshes: the head x wheel sweep keeps one head pose in memory at a time, V7 measures the print-pose gaps
with a 1 mm search, and zero-volume fragments in the exported STL fail V7.shells without stopping the other V7 checks.
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
import trimesh  # noqa: E402
from manifold3d import Manifold  # noqa: E402

from purrbobble import geom2d as g2  # noqa: E402
from purrbobble.model import build  # noqa: E402

# --------------------------------------------------------------------------------------------- constants
OV_EPS = 1e-6          # mm^3: overlap volume treated as zero (boolean round-off)
TOUCH = 1e-3           # mm: min_gap below this = contact
SPEC = {               # SPEC section 5 V6 / V7 (absolute values; variant-dependent ones are derived below)
    "journal_tol": 0.02,
    "ridge_tol": 0.02,
    "head_fill_min": 0.50,
    "head_fill_psi_max": 12.2,
    "facemid_roof_min": 0.50,
    "wheel_frame_xy_min": 0.45,
    "wheel_frame_z_min": 0.40,
    "face_ball": (1.4, 2.0),
    "knob_paw_min": 0.9,
    "rib_tol": 0.02,
    "field_min": 0.95,
    "print_gap_min": 0.35,
    "print_gap_tol": 0.002,      # float / faceting on the 0.35 designed journal + ridge gaps
    "pallet_tooth_min": 1.3,
    "shadow_tol": 0.02,          # SPEC V3 tolerance, reused for the 3-D shadow test
    "captive_disp": 1.0,
    "captive_tilt": 3.0,
    "ridgeless_lift_max": 1.0,
    "lift_tol": 0.02,
}


# --------------------------------------------------------------------------------------------- helpers
def zb(z0: float, z1: float, xy: float = 200.0) -> Manifold:
    """Slab z0..z1 (crop region)."""
    return Manifold.cube((2 * xy, 2 * xy, z1 - z0)).translate((-xy, -xy, z0))


def cyl(c, r: float, z0: float, z1: float, n: int = 256) -> Manifold:
    return Manifold.cylinder(z1 - z0, r, r, n).translate((float(c[0]), float(c[1]), z0))


def ann(c, r0: float, r1: float, z0: float, z1: float, n: int = 256) -> Manifold:
    return cyl(c, r1, z0, z1, n) - cyl(c, r0, z0 - 1, z1 + 1, n)


def crop(m: Manifold, *regions) -> Manifold:
    out = m
    for r in regions:
        out = out ^ r
    return out


def ov(a: Manifold, b: Manifold) -> float:
    return float((a ^ b).volume())


def gap(a: Manifold, b: Manifold, search: float = 3.0) -> float:
    if a.is_empty() or b.is_empty():
        return float("inf")
    return float(a.min_gap(b, search))


def xy_gap(a: Manifold, b: Manifold, levels, cap: float = 2.0) -> float:
    """Smallest in-plane (XY) distance between two bodies over horizontal slices at `levels` (capped)."""
    best = cap
    for z in levels:
        sa, sb = a.slice(z), b.slice(z)
        if sa.is_empty() or sb.is_empty():
            continue
        ga, gb = g2.to_shapely(sa), g2.to_shapely(sb)
        if ga.intersects(gb):
            return 0.0
        best = min(best, float(ga.distance(gb)))
    return best


def slice_sh(m: Manifold, z: float):
    """Horizontal slice as a shapely geometry (None if empty)."""
    s = m.slice(float(z))
    return None if s.is_empty() else g2.to_shapely(s)


def xy_gap_rot(fixed, moving, c, a_deg: float, cap: float = 2.0) -> float:
    """xy_gap on pre-computed slices (lists of shapely geometries per level, None = empty): the moving body's slices
    rotated a_deg about c (= the slices of the rotated body; much cheaper than re-slicing it at every pose)."""
    from shapely import affinity
    best = cap
    for ga, gb in zip(fixed, moving):
        if ga is None or gb is None:
            continue
        gb = affinity.rotate(gb, float(a_deg), origin=(float(c[0]), float(c[1])))
        if ga.intersects(gb):
            return 0.0
        best = min(best, float(ga.distance(gb)))
    return best


def blocked(frame: Manifold, body: Manifold) -> tuple[bool, float, float]:
    v = ov(frame, body)
    if v > OV_EPS:
        return True, v, 0.0
    g = float(frame.min_gap(body, 0.05))
    return g < TOUCH, v, g


def rot_xy(v, a_deg):
    c, s = np.cos(np.radians(a_deg)), np.sin(np.radians(a_deg))
    return np.stack([c * v[..., 0] - s * v[..., 1], s * v[..., 0] + c * v[..., 1]], -1)


def tilt(m: Manifold, pivot, rx: float = 0.0, ry: float = 0.0) -> Manifold:
    px, py, pz = (float(x) for x in pivot)
    return m.translate((-px, -py, -pz)).rotate((rx, ry, 0.0)).translate((px, py, pz))


def to_tm(m: Manifold) -> trimesh.Trimesh:
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    return trimesh.Trimesh(v, np.asarray(mesh.tri_verts, dtype=np.int64), process=False)


def status_of(ok: bool, warn: bool = False) -> str:
    return "pass" if ok and not warn else ("warn" if ok else "fail")


def r4(x):
    if x is None:
        return None
    if isinstance(x, float) and not math.isfinite(x):
        return str(x)
    return round(float(x), 4)


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
        self.log(f"{cid:28s} {status.upper():5s} {name}: {measured}")
        return rec


# --------------------------------------------------------------------------------------------- C-space
def pallet_cspace(M, phis, psis):
    """SPEC 2.4 (a) pallet clearance c(phi, psi) from the exported 2-D sections (Star2D, pallet centres, rp)."""
    p, S = M.params, M.sections
    star = g2.to_shapely(S["star2d"])
    bnd = star.boundary
    P = np.array(p.P)
    PH, PS = np.meshgrid(phis, psis, indexing="ij")
    cs = []
    for pc in p.pallets:
        q = P + rot_xy(np.broadcast_to(np.array(pc) - P, PS.shape + (2,)), PS)
        qw = rot_xy(q, -PH)
        d = shapely.distance(bnd, shapely.points(qw[..., 0], qw[..., 1]))
        inside = shapely.contains_xy(star, qw[..., 0], qw[..., 1])
        cs.append(np.where(inside, -d, d) - p.rp)
    return np.minimum(*cs)


def free_intervals(row_free, psis):
    idx = np.nonzero(row_free)[0]
    out = []
    if len(idx) == 0:
        return out
    s = prev = idx[0]
    for k in idx[1:]:
        if k != prev + 1:
            out.append((float(psis[s]), float(psis[prev])))
            s = k
        prev = k
    out.append((float(psis[s]), float(psis[prev])))
    return out


def cspace_reach_with_play(M, psi_b: float, play: float = 0.7, n_dir: int = 12) -> dict:
    """Largest free psi (full HeadBand2D vs Star2D, 2-D) when the head pivot is displaced relative to the wheel
    axis by ``play`` (= both journals' radial play) in n_dir directions; phi step 1 deg, psi step 0.1 deg."""
    from shapely import affinity
    p, S = M.params, M.sections
    star = g2.to_shapely(S["star2d"])
    hb = g2.to_shapely(S["headband2d"])
    best = {"psi": 0.0}
    for k in range(n_dir):
        a = 2 * math.pi * k / n_dir
        d = (play * math.cos(a), play * math.sin(a))
        for phi in np.arange(0.0, 45.0, 1.0):
            W = affinity.rotate(star, phi, origin=(0, 0))
            shapely.prepare(W)
            for sgn in (+1, -1):
                for psi in np.arange(psi_b, best["psi"], -0.1):
                    H = affinity.translate(affinity.rotate(hb, sgn * psi, origin=p.P), *d)
                    if not W.intersects(H):
                        if psi > best["psi"]:
                            best = {"psi": round(float(psi), 2), "phi": float(phi), "sign": sgn,
                                    "shift_dir_deg": round(math.degrees(a), 1)}
                        break
    return best


# --------------------------------------------------------------------------------------------- Z-gap census
def z_census(bodies: dict, axes: dict, rng_seed: int = 0, density: float = 20.0, min_nz: float = 0.3,
             r_axis: float = 6.0, area_below: float | None = None) -> list[dict]:
    """Vertical ray census: from every upward-facing face (normal z > min_nz) of each body, sample points
    (``density`` per mm^2), cast a +Z ray against all bodies and keep the rays whose FIRST hit is a different
    body.  Returns clusters keyed by (lower body, lower face class, lower z level, upper body, upper face class,
    zone); zone = 'journal_<name>' within r_axis of an axis in ``axes`` (posts, ridges, bore roofs), else
    'field'.  area_below: also report each cluster's area with a gap below this value."""
    names = list(bodies)
    tms = [to_tm(bodies[n]) for n in names]
    offs = np.cumsum([0] + [len(t.faces) for t in tms])
    scene = trimesh.util.concatenate(tms)
    owner = np.searchsorted(offs, np.arange(len(scene.faces)), side="right") - 1
    rng = np.random.default_rng(rng_seed)
    clusters = {}
    for bi, t in enumerate(tms):
        nz = t.face_normals[:, 2]
        up = np.nonzero(nz > min_nz)[0]
        if len(up) == 0:
            continue
        area = t.area_faces[up]
        n = int(max(1000, area.sum() * density))
        fi = rng.choice(up, size=n, p=area / area.sum())
        tri = t.triangles[fi]
        r1 = np.sqrt(rng.random(n))
        r2 = rng.random(n)
        pts = (1 - r1)[:, None] * tri[:, 0] + (r1 * (1 - r2))[:, None] * tri[:, 1] + (r1 * r2)[:, None] * tri[:, 2]
        flat_lo = nz[fi] > 0.999
        org = pts + np.array([0.0, 0.0, 1e-4])
        dirs = np.tile([0.0, 0.0, 1.0], (n, 1))
        loc, ri, ti = scene.ray.intersects_location(org, dirs, multiple_hits=False)
        hit_owner = owner[ti]
        sel = hit_owner != bi
        ri, ti, loc, hit_owner = ri[sel], ti[sel], loc[sel], hit_owner[sel]
        g = loc[:, 2] - pts[ri, 2]
        flat_hi = scene.face_normals[ti, 2] < -0.999
        zl = np.where(flat_lo[ri], np.round(pts[ri, 2], 2), np.nan)
        zone = np.full(len(ri), "field", dtype=object)
        for an, ac in axes.items():
            near = np.hypot(pts[ri, 0] - ac[0], pts[ri, 1] - ac[1]) < r_axis
            zone[near] = f"journal_{an}"
        for k in range(len(ri)):
            key = (names[bi], "flat" if flat_lo[ri[k]] else "slanted",
                   float(zl[k]) if flat_lo[ri[k]] else None, names[hit_owner[k]],
                   "flat" if flat_hi[k] else "slanted", zone[k])
            c = clusters.get(key)
            if c is None:
                c = clusters[key] = {"g": [], "xy": []}
            c["g"].append(g[k])
            c["xy"].append(pts[ri[k], :2])
    out = []
    for (lo_b, lo_cls, lo_z, hi_b, hi_cls, zn), c in clusters.items():
        g = np.array(c["g"])
        xy = np.array(c["xy"])
        k = int(g.argmin())
        out.append({"lower": lo_b, "lower_face": lo_cls, "lower_z": lo_z, "upper": hi_b, "upper_face": hi_cls,
                    "zone": zn, "n": int(len(g)), "area_mm2": round(len(g) / density, 1), "gap_min": round(float(g.min()), 4),
                    "gap_p05": round(float(np.percentile(g, 5)), 4), "gap_max": round(float(g.max()), 4),
                    "at_min_xy": [round(float(v), 2) for v in xy[k]]})
        if area_below is not None:
            out[-1]["area_below_mm2"] = round(float((g < area_below).sum()) / density, 1)
    out.sort(key=lambda d: (d["lower"], d["lower_z"] if d["lower_z"] is not None else 99, d["upper"]))
    return out


def census_select(cl, lower, lower_z, upper, upper_face="flat", gap_lt=None, zone="field", gap_ge=None,
                  z_tol=0.011):
    """Clusters for a (lower body at z level) -> (upper body, upper face class) pair; returns (min, max, n)."""
    g_min, g_max, n = math.inf, -math.inf, 0
    for c in cl:
        if zone is not None and not c["zone"].startswith(zone):
            continue
        if c["lower"] != lower or c["upper"] not in (upper if isinstance(upper, tuple) else (upper,)):
            continue
        if lower_z is not None and (c["lower_z"] is None or abs(c["lower_z"] - lower_z) > z_tol):
            continue
        if upper_face is not None and c["upper_face"] != upper_face:
            continue
        if gap_lt is not None and c["gap_min"] >= gap_lt:
            continue
        if gap_ge is not None and c["gap_min"] < gap_ge:
            continue
        g_min, g_max, n = min(g_min, c["gap_min"]), max(g_max, c["gap_max"]), n + c["n"]
    return g_min, g_max, n


# --------------------------------------------------------------------------------------------- journals (slices)
def _contours_near(cs, c, rmax):
    out = []
    for poly in cs.to_polygons():
        a = np.asarray(poly, float)
        d = np.hypot(a[:, 0] - c[0], a[:, 1] - c[1])
        if d.max() < rmax:
            out.append(a)
    return out


def _edge_min_dist(a, c):
    b = np.roll(a, -1, axis=0)
    ab = b - a
    t = np.clip(((c - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-30), 0, 1)
    q = a + t[:, None] * ab
    return float(np.hypot(q[:, 0] - c[0], q[:, 1] - c[1]).min())


def journal_range(frame: Manifold, body: Manifold, c, z: float):
    """Radial journal gap range at height z from slices: [min, max] over the faceted post / bore polygons."""
    c = np.array(c, float)
    post = _contours_near(frame.slice(z), c, 4.6)
    hole = _contours_near(body.slice(z), c, 6.0)
    if not post or not hole:
        return None
    pa = max(post, key=lambda a: np.hypot(a[:, 0] - c[0], a[:, 1] - c[1]).max())
    ha = min(hole, key=lambda a: np.hypot(a[:, 0] - c[0], a[:, 1] - c[1]).max())
    post_rmax = float(np.hypot(pa[:, 0] - c[0], pa[:, 1] - c[1]).max())
    post_rmin = _edge_min_dist(pa, c)
    hole_rmax = float(np.hypot(ha[:, 0] - c[0], ha[:, 1] - c[1]).max())
    hole_rmin = _edge_min_dist(ha, c)
    return hole_rmin - post_rmax, hole_rmax - post_rmin


# --------------------------------------------------------------------------------------------- main checks
def run(skin: str, variant: str, quiet: bool = False) -> dict:
    R = Report(quiet)
    M = build(skin, variant)
    p, S = M.params, M.sections
    F, W, H = M.frame, M.wheel, M.head
    P = tuple(p.P)
    O = (0.0, 0.0)
    lift = p.z_lift
    psi_b = p.psi_b
    # sculpt skin: no roof / I3 slot / face layers / paw lips / knob (see the module docstring)
    sculpt = hasattr(M.skin, "sculpt")
    sk = M.skin
    if sculpt:
        from purrbobble.sculpt import seams
        sm = seams(sk, p)
        gz, gzf = sm["gap_z"], sm["gap_z_floors"]   # static ring over the skid rings, covers / head floors
    else:
        sm, gz, gzf = None, None, None
    R.log(f"built {skin}/{variant}: P = {P}, z_lift {lift}" + (", sculpt" if sculpt else ""))

    journal = (p.bore_d - p.post_d) / 2.0
    rib_gap = p.z_band0 - (p.z_bp + p.rib_h) + lift
    field_min = SPEC["field_min"] + lift
    psis = np.linspace(-psi_b, psi_b, int(math.ceil(2 * psi_b / 0.25)) + 1)
    info = {"skin": skin, "variant": variant, "P": P, "psi_b": psi_b, "z_lift": lift,
            "design_journal": journal, "design_ridge_normal": p.ridge_gap_n, "design_rib_gap": rib_gap,
            "psi_poses": len(psis), "psi_step": float(psis[1] - psis[0])}
    if sculpt:
        info["sculpt"] = {"gap_z": sk.gap_z, "gap_z_seams": gz, "gap_z_floors": gzf, "gap_xy": sm["gap_xy"],
                          "cap_r": sk.cap_r, "cap_gap": sm["cap_gap"], "leg_low_top": sk.leg_low_top}

    # ---------------------------------------------------------------- crop regions
    zh0, zh1 = p.z_band0 + lift, p.z_band1 + lift              # head band layer
    band = zb(zh0 + 0.05, zh1 - 0.05)
    posts_zone = cyl(O, 6.0, -1, 20) + cyl(P, 6.0, -1, 20)
    pad_zone = g2.grow(S["stoppads2d"], 0.3, 0.01).extrude(12.0).translate((0, 0, 0.5))
    F_band = F ^ band
    F_band_np = F_band - posts_zone - pad_zone                   # fill / cavity walls without posts and pads
    # V6.head_fill is an XY criterion: measure it on slices through the band layer (the 3-D distance would also
    # report designed Z gaps inside the band, e.g. the crown skirt 0.40 over the band groove)
    band_levels = [round(float(z), 3) for z in np.linspace(zh0 + 0.1, zh1 - 0.1, 9)]
    F_pads = F_band ^ pad_zone
    pad_pieces = sorted(F_pads.decompose(), key=lambda m: m.bounding_box()[0])
    if sculpt:
        # the head body rises continuously from its floors (z 3.0 .. 14) to the sculpt surface: XY on slices over
        # its whole height above the band (levels at .075 mod 0.2: >= 0.02 off the floors .037, cut flats .023,
        # covers .014 / .184, static ring .114; post tops cut out; the band layer itself is V6.head_fill), and 3-D
        # over the whole head from just above the band bottom (designed Z gaps: band tops -> covers, floors ->
        # frame flats; posts and pads cut out)
        up_levels = [round(float(z), 4) for z in np.arange(zh1 + 0.075, H.bounding_box()[5], 0.2)]
        F_upx = F - (cyl(O, 6.0, -1, p.post_z1 + 0.05) + cyl(P, 6.0, -1, p.post_z1 + 0.05))
        up_f = [slice_sh(F_upx, z) for z in up_levels]
        up_h = [slice_sh(H, z) for z in up_levels]
        F_up = F - posts_zone - pad_zone
        H_up = zb(zh0 + 0.05, 60)          # (3-D: the band and the floors below its top too: lowered legs <-> covers;
        #                                    search 0.6: > every designed Z gap, ~4x faster than 1.0 on these meshes)
    else:
        F_mid = F ^ zb(p.z_roof0 + 0.05, p.z_roof1 - 0.05)       # roof (+ fill) band seen by the face-mid layer
        F_front = F ^ zb(p.z_front0 + lift + 0.05, p.z_knob_top + 1)
    F_noposts = F - (cyl(O, 5.5, -1, p.bore_roof_z + 1) + cyl(P, 5.5, -1, p.bore_roof_z + 1))

    # =============================================================== V5 frame x head
    R.log("V5 frame x head sweep")
    rows = []
    for psi in psis:
        h = M.head_at(psi)
        hb = h ^ band
        r = {"psi": float(psi), "overlap": ov(F, h), "gap_all": gap(F, h, 1.0),
             "gap_nonpad": xy_gap(F_band_np, hb, band_levels), "gap_pads": gap(F_pads, hb, 3.0)}
        if sculpt:
            r.update(gap_up_xy=xy_gap_rot(up_f, up_h, P, psi), gap_up_3d=gap(F_up, h ^ H_up, 0.6))
        else:
            r.update(gap_mid=gap(F_mid, h ^ zb(p.z_roof0 + 0.05, p.z_roof1 - 0.05), 2.0),
                     gap_front=gap(F_front, h ^ zb(p.z_front0 + lift + 0.05, p.z_feat + lift + 1), 5.0))
        rows.append(r)
    ovmax = max(r["overlap"] for r in rows)
    interior = [r for r in rows if abs(abs(r["psi"]) - psi_b) > 1e-6]
    touch_int = [r["psi"] for r in interior if min(r["gap_all"], r["gap_pads"]) < TOUCH]
    R.add("V5.frame_head", "frame x head overlap over the head swing", status_of(ovmax <= OV_EPS and not touch_int),
          {"max_overlap_mm3": r4(ovmax), "poses": len(rows), "touching_interior_poses": touch_int,
           "min_gap_interior": r4(min(min(r["gap_all"], r["gap_pads"]) for r in interior))},
          "overlap 0 at every psi in [-psi_b, psi_b] (step <= 0.25); contact only at |psi| = psi_b (pads)")

    ends = [r for r in rows if abs(abs(r["psi"]) - psi_b) <= 1e-6]
    pad_end = {}
    for r in ends:
        h = M.head_at(r["psi"]) ^ band
        pad_end[f"{r['psi']:+.2f}"] = [r4(gap(q, h, 3.0)) for q in pad_pieces]
    beyond = {}
    beyond_ok = True
    for s in (+1, -1):
        psi_x = s * (psi_b + 0.25)
        h = M.head_at(psi_x)
        v_pad = ov(F_pads, h ^ band)
        v_other = ov(F - pad_zone, h)
        beyond[f"{psi_x:+.2f}"] = {"overlap_pads_mm3": r4(v_pad), "overlap_elsewhere_mm3": r4(v_other)}
        beyond_ok &= v_pad > OV_EPS and v_other <= OV_EPS
    ends_touch = all(sorted(v)[1] <= 0.01 for v in pad_end.values()) if len(pad_pieces) == 4 else False
    R.add("V5.banking_pads", "stop pads: both legs touch at +-psi_b, pads are the first and only stop beyond it",
          status_of(ends_touch and beyond_ok),
          {"n_pads": len(pad_pieces), "pad_gaps_at_ends": pad_end, "beyond_limit": beyond,
           "pad_max_inscribed_width": [r4(g2.max_inscribed_width(q)) for q in g2.pieces(S["stoppads2d"])],
           "pad_area_mm2": [r4(q.area()) for q in g2.pieces(S["stoppads2d"])]},
          "at +-psi_b two pads (one per leg) within 0.01; at psi_b + 0.25 overlap with pads > 0 and nowhere else")

    # =============================================================== V5 frame x wheel
    R.log("V5 frame x wheel sweep")
    phis_w = sorted(set([round(x, 3) for x in np.arange(0, 45.0001, 0.5)] + [float(x) for x in range(0, 360, 2)]))
    wrows = []
    for phi in phis_w:
        w = M.wheel_at(phi)
        wrows.append({"phi": phi, "overlap": ov(F, w), "gap": gap(F, w, 1.0), "gap_noposts": gap(F_noposts, w, 1.0)})
    wovmax = max(r["overlap"] for r in wrows)
    R.add("V5.frame_wheel", "frame x wheel overlap, phi 0..45 step 0.5 and 0..358 step 2",
          status_of(wovmax <= OV_EPS),
          {"max_overlap_mm3": r4(wovmax), "poses": len(wrows), "min_gap": r4(min(r["gap"] for r in wrows)),
           "min_gap_excl_journal": r4(min(r["gap_noposts"] for r in wrows))},
          "overlap 0 at every phi")

    # =============================================================== V5 head x wheel (C-space free)
    R.log("V5 head x wheel at C-space-free poses")
    phis_c = np.round(np.arange(0, 45, 0.5), 6)
    C = pallet_cspace(M, phis_c, psis)
    free = C >= 0
    per_phi = {f"{phis_c[i]:.1f}": free_intervals(free[i], psis) for i in range(0, len(phis_c), 6)}
    max_free_psi = float(np.abs(np.where(free, np.broadcast_to(psis, free.shape), 0)).max())
    # pallet top <-> umbrella plate Z gap caps the 3-D gap (head band top vs plate)
    z_pal_plate = (p.z_teeth1 - p.z_pallet_top)
    heads = {}
    wheels = {}

    def head_at(j, psi):
        if j not in heads:
            heads[j] = M.head_at(psi)
        return heads[j]

    def wheel_at(phi):
        k = round(float(phi), 4)
        if k not in wheels:
            wheels[k] = M.wheel_at(phi)
        return wheels[k]

    def hw_rows(poses, search):
        """(phi, psi, c, overlap, gap) per (phi, i, j) pose, in the given order.  Sculpt: its bodies are ~10x denser
        (~0.5 M triangles per head pose; 101 cached head poses plus the wheel poses do not fit in memory), so one
        head pose at a time (poses visited grouped by psi) and the wheel rotated per pose, nothing cached"""
        out = [None] * len(poses)
        order = sorted(range(len(poses)), key=lambda k: poses[k][2]) if sculpt else range(len(poses))
        hj = h = None
        for k in order:
            phi, i, j = poses[k]
            if sculpt:
                if j != hj:
                    hj, h = j, M.head_at(float(psis[j]))
                w = M.wheel_at(phi)
            else:
                h, w = head_at(j, float(psis[j])), wheel_at(phi)
            out[k] = (phi, float(psis[j]), float(C[i, j]), ov(h, w), gap(h, w, search))
        return out

    hw = np.array(hw_rows([(float(phis_c[i]), int(i), int(j)) for i, j in np.argwhere(free)], z_pal_plate + 0.1))
    # the 0..358 sweep (knob / face / relief), three free psi per phi
    poses360 = []
    for phi in range(0, 360, 2):
        i = int(round((phi % 45) / 0.5))
        js = np.nonzero(free[i])[0]
        if len(js) == 0:
            continue
        for j in sorted({int(js[0]), int(js[np.argmax(C[i, js])]), int(js[-1])}):
            poses360.append((float(phi), i, j))
    hw360 = np.array(hw_rows(poses360, 3.0))
    hw_ovmax = float(max(hw[:, 3].max(), hw360[:, 3].max()))
    R.add("V5.head_wheel_free", "head x wheel overlap at every C-space-free (phi, psi)",
          status_of(hw_ovmax <= OV_EPS),
          {"free_poses_pitch": int(len(hw)), "poses_0_358": int(len(hw360)), "max_overlap_mm3": r4(hw_ovmax),
           "min_gap_3d": r4(min(hw[:, 4].min(), hw360[:, 4].min()))},
          "overlap 0 wherever the 2-D pallet clearance c(phi, psi) >= 0")
    deficit = hw[:, 4] - np.minimum(hw[:, 2], z_pal_plate)
    k = int(deficit.argmin())
    R.add("V5.shadow_3d", "3-D shadow test: only the pallet tips are the nearest head<->wheel contact",
          status_of(deficit.min() >= -SPEC["shadow_tol"]),
          {"worst_deficit": r4(deficit.min()), "at": {"phi": hw[k, 0], "psi": r4(hw[k, 1]), "c_pins": r4(hw[k, 2]),
                                                       "gap_3d": r4(hw[k, 4])}},
          f"gap_3d >= min(c_pins, {z_pal_plate:.2f}) - {SPEC['shadow_tol']} at every free pose")
    reach_play = cspace_reach_with_play(M, psi_b)
    R.add("V5.cspace_banking_reach", "(info) can the head reach the banking stops while the wheel is engaged?",
          "pass",
          {"max_free_abs_psi_deg_centred": r4(max_free_psi), "psi_b": psi_b,
           "max_free_psi_with_relative_journal_play_0.7": reach_play, "free_fraction": r4(free.mean()),
           "free_psi_intervals_by_phi": per_phi,
           "c_max": r4(C.max()), "c_max_at": {"phi": float(phis_c[np.unravel_index(C.argmax(), C.shape)[0]]),
                                              "psi": r4(psis[np.unravel_index(C.argmax(), C.shape)[1]])}},
          "informational (no pass criterion): with centred journals the pallets meet a tooth before the stop pads, "
          "so a resting head leans on a tooth, not on a pad (SPEC 1 / 2.4(b) assume hard banking); journal play "
          "can make the pads reachable")

    # =============================================================== V6 journals / ridges / post tops
    R.log("V6 journals, ridges")
    z_lo = (p.z_band0 + p.bore_chamfer + lift + 0.05, p.ridge_z - (p.groove_apex_r - p.bore_r) - 0.05)
    z_hi = (p.ridge_z + (p.groove_apex_r - p.bore_r) + 0.1, p.post_z1 - p.post_chamfer - 0.1)
    jr = {}
    for nm, c, mov in (("head", P, M.head_at(0.0)), ("wheel", O, W)):
        gs, rngs = [], []
        for zz in (z_lo, z_hi):
            gs.append(gap(crop(F, cyl(c, p.post_r + 0.6, *zz)), crop(mov, cyl(c, p.bore_r + 1.2, *zz)), 2.0))
            rg = journal_range(F, mov, c, 0.5 * (zz[0] + zz[1]))
            if rg:
                rngs.append(rg)
        lo = min(min(gs), min(r[0] for r in rngs))
        hi = max(r[1] for r in rngs)
        ok = abs(lo - journal) <= SPEC["journal_tol"] and abs(hi - journal) <= SPEC["journal_tol"]
        R.add(f"V6.journal_{nm}", f"{nm} journal radial gap (post vs bore)", status_of(ok),
              {"min_gap_exact": r4(min(gs)), "faceted_range": [r4(lo), r4(hi)]},
              f"{journal:.2f} +- {SPEC['journal_tol']} (min and max over the faceted polygons)")
        zr = (p.ridge_z - p.ridge_h + 0.1, p.ridge_z + p.ridge_h - 0.1)
        g_r = gap(crop(F, cyl(c, p.ridge_apex_r + 0.3, *zr)), crop(mov, cyl(c, p.groove_apex_r + 1.0, *zr)), 2.0)
        R.add(f"V6.ridge_{nm}", f"{nm} V-ridge <-> V-groove normal gap", status_of(g_r >= p.ridge_gap_n - SPEC["ridge_tol"]),
              r4(g_r), f">= {p.ridge_gap_n - SPEC['ridge_tol']:.2f} (designed {p.ridge_gap_n})")
        jr[nm] = g_r
        g_t = gap(crop(F, cyl(c, p.post_r - p.post_chamfer - 0.1, p.post_z1 - 0.3, p.post_z1 + 0.05)),
                  crop(mov, cyl(c, p.post_r - p.post_chamfer - 0.1, p.post_z1 + 0.05, p.bore_roof_z + lift + 0.6)), 2.0)
        want = p.bore_roof_z + lift - p.post_z1
        R.add(f"V6.post_top_{nm}", f"{nm} post top <-> bore roof (Z)", status_of(abs(g_t - want) <= 0.02),
              r4(g_t), f"{want:.2f} +- 0.02 (SPEC 3.2)")

    # =============================================================== V6 head interfaces (psi sweep)
    gnp = [r["gap_nonpad"] for r in rows if abs(r["psi"]) <= SPEC["head_fill_psi_max"] + 1e-9]
    gnp_all = [r["gap_nonpad"] for r in rows]
    hf_min = p.swept_gap - 0.05
    R.add("V6.head_fill", "head band <-> frame fill / cavity walls (XY, posts and stop pads excluded)",
          status_of(min(gnp) >= SPEC["head_fill_min"] and min(gnp_all) >= SPEC["head_fill_min"]),
          {"min_|psi|<=12.2": r4(min(gnp)), "min_all_psi": r4(min(gnp_all)), "designed": p.swept_gap},
          f">= {SPEC['head_fill_min']} for |psi| <= {SPEC['head_fill_psi_max']} (SPEC V6); "
          f"variant swept gap {p.swept_gap:.2f} (>= {hf_min:.2f})")
    pad_curve = {f"{r['psi']:+.2f}": r4(r["gap_pads"]) for r in rows if abs(r["psi"]) >= 10.9}
    g122 = min(r["gap_pads"] for r in rows if abs(abs(r["psi"]) - 12.2) < 0.13)
    slope = []
    for s in (+1, -1):
        sel = sorted([r for r in rows if s * r["psi"] >= psi_b - 1.0], key=lambda r: abs(r["psi"]))
        if len(sel) >= 2:
            slope.append((sel[0]["gap_pads"] - sel[-1]["gap_pads"]) / abs(sel[0]["psi"] - sel[-1]["psi"]))
    R.add("V6.head_stop_pads", "head legs <-> stop pads (approach towards the banking limit)",
          "warn" if g122 < SPEC["head_fill_min"] else "pass",
          {"gap_at_|psi|=12.2": r4(g122), "approach_mm_per_deg": [r4(x) for x in slope],
           "gap_vs_psi_(|psi|>=10.9)": pad_curve},
          "SPEC V6 'head<->fill >= 0.50 for |psi| <= 12.2' cannot hold at the pads: SPEC 2.5 builds them to touch "
          "the leg flank exactly at psi_b. Reported, not failed; contact only at |psi| = psi_b is checked in V5")
    if sculpt:
        # (no face mid layer, roof or front layer: the head body above the band against the whole frame instead)
        gm = [r["gap_up_xy"] for r in rows]
        R.add("V6.facemid_roof", "head body above the band <-> frame (XY slices over the head's whole height, swept)",
              status_of(min(gm) >= SPEC["head_fill_min"]),
              {"min": r4(min(gm)), "at_psi": r4(rows[int(np.argmin(gm))]["psi"]), "levels": len(up_levels),
               "z_range": [up_levels[0], up_levels[-1]], "designed": r4(max(sk.gap_xy, p.gap_xy) + p.sweep_allowance)},
              f">= {SPEC['head_fill_min']} (SPEC V6 head<->fill; sculpt: replaces face mid <-> roof, every 0.2 mm "
              f"from the band top up, all psi)")
        gf = [r["gap_up_3d"] for r in rows]
        R.add("V6.face_front_frame", "head (band and body, from z_band0 + 0.05 up) <-> frame, 3-D (band tops under "
                                     "the covers, floors over the frame's cut flats; posts and stop pads excluded), "
                                     "swept",
              status_of(min(gf) >= sk.gap_z - SPEC["rib_tol"]),
              {"min_capped_at_0.6": r4(min(gf)), "at_psi": r4(rows[int(np.argmin(gf))]["psi"]),
               "designed_z": [r4(gz), r4(gzf)]},
              f">= {sk.gap_z - SPEC['rib_tol']:.4f} (nothing closer than the designed Z gaps: seams {gz:.4f}, head "
              f"floors {gzf:.4f}; sculpt: replaces face front layer <-> paws / decor)")
    else:
        gm = [r["gap_mid"] for r in rows]
        R.add("V6.facemid_roof", "face mid layer <-> roof edge (XY, swept)",
              status_of(min(gm) >= SPEC["facemid_roof_min"]),
              {"min": r4(min(gm)), "at_psi": r4(rows[int(np.argmin(gm))]["psi"])},
              f">= {SPEC['facemid_roof_min']}")
        gf = [r["gap_front"] for r in rows]
        R.add("V6.face_front_frame", "face front layer (z >= 11.4) <-> paws / decor / anything on the roof (XY)",
              status_of(min(gf) >= SPEC["head_fill_min"]), {"min_capped_at_5": r4(min(gf))},
              ">= 0.50 (SPEC 3.2: decor >= 2 mm outside Swept(FaceUp))")

    # =============================================================== V6 wheel <-> frame
    R.log("V6 wheel interfaces")
    zw0 = p.z_band0 + lift
    W_teeth = W ^ zb(zw0 + 0.05, p.z_teeth1 + lift - 0.25)
    F_teeth = (F ^ zb(zw0 + 0.05, p.z_teeth1 + lift - 0.25)) - posts_zone
    W_cone = W ^ zb(p.z_teeth1 + lift + 0.05, p.umb_rim_z0 + lift - 0.05)
    F_cone = (F ^ zb(p.z_teeth1 - 0.5, p.umb_rim_z1 + 0.5)) - posts_zone
    W_rim = W ^ zb(p.umb_rim_z0 + lift - 0.05, p.umb_rim_z1 + lift + 0.05)
    kp = []
    if sculpt:
        # no paws / lips / knob / roof: the umbrella rim turns inside the wheel envelope's wall, and above the
        # umbrella top the skid rings and the cap turn under / inside the static yarn ring.  XY on slices there
        # (levels at .05 mod 0.1, off the wheel tops .0 and the ring undersides .014), and 3-D above the rim top,
        # where only the designed Z gaps (umbrella top / skid rings -> static ring) may be below the XY minimum
        F_rim = F ^ zb(p.umb_rim_z0 + lift - 0.5, p.umb_rim_z1 + lift + 0.5)
        w_levels = [round(float(z), 4) for z in np.arange(p.z_umb_top + lift - 0.05, W.bounding_box()[5], 0.1)]
        wt_f = [slice_sh(F, z) for z in w_levels]
        wt_w = [slice_sh(W, z) for z in w_levels]
        W_abv = W ^ zb(p.umb_rim_z1 + lift, 60)
        F_abv = F ^ ann(O, sk.cap_r - 1.0, p.R_u + 3.0, p.umb_rim_z1 + lift - 0.5, 60)
        sub = {"teeth_fill": [], "cone_funnel_seat": [], "rim_frame_wall": [], "above_umbrella_top_xy": []}
        sub3 = []
        for phi in np.arange(0, 360, 30.0):
            sub["teeth_fill"].append(gap(F_teeth, W_teeth.rotate((0, 0, phi)), 2.0))
            sub["cone_funnel_seat"].append(gap(F_cone, W_cone.rotate((0, 0, phi)), 2.0))
            sub["rim_frame_wall"].append(gap(F_rim, W_rim.rotate((0, 0, phi)), 2.0))
            sub["above_umbrella_top_xy"].append(xy_gap_rot(wt_f, wt_w, O, phi))
            sub3.append(gap(F_abv, W_abv.rotate((0, 0, phi)), 1.0))
        for phi in np.arange(0, 45, 0.5):
            sub["teeth_fill"].append(gap(F_teeth, W_teeth.rotate((0, 0, phi)), 2.0))
        subm = {k: r4(min(v)) for k, v in sub.items()}
        subm["above_rim_top_3d_(Z criterion)"] = r4(min(sub3))
        gxy = max(sk.gap_xy, p.gap_xy)
        R.add("V6.wheel_frame_xy", "wheel <-> frame, XY / normal interfaces (journal excluded): teeth, cone, umbrella "
                                   "rim, skid rings and cap under / inside the static yarn ring",
              status_of(min(min(v) for v in sub.values()) >= SPEC["wheel_frame_xy_min"]
                        and min(sub3) >= SPEC["wheel_frame_z_min"]), subm,
              f">= {SPEC['wheel_frame_xy_min']} each XY (designed: teeth 0.50, cone 0.50 normal, rim {gxy:.2f}, "
              f"cap <-> ring {sm['cap_gap']:.2f} radial; XY slices z {w_levels[0]}..{w_levels[-1]} every 0.1); 3-D above "
              f"the rim top >= {SPEC['wheel_frame_z_min']} (the designed Z gaps umbrella top / skid rings -> ring, "
              f"{gz:.4f})")
        # spinning cap (r cap_r, the finger dish's body) <-> static yarn ring around it: replaces knob <-> paw lip
        cap = W ^ zb(p.z_umb_top + lift + p.rib_h + 0.02, 60)
        F_ring = F ^ ann(O, sk.cap_r - 1.0, sk.cap_r + sm["cap_gap"] + 2.0, p.z_umb_top + lift, 60)
        for phi in range(0, 360, 2):
            kp.append(gap(F_ring, cap.rotate((0, 0, float(phi))), 1.0))
        journal_ = (p.bore_d - p.post_d) / 2.0
        k_play = min(gap(F_ring, cap.translate((journal_ * c_, journal_ * s_, 0.0)), 1.0)
                     for c_, s_ in ((1, 0), (0, 1), (-1, 0), (0, -1)))
        kp_lo = max(SPEC["wheel_frame_xy_min"], sm["cap_gap"] - SPEC["rib_tol"])
        R.add("V6.knob_paw", "spinning cap <-> static yarn ring (radial, constant), phi 0..358 step 2",
              status_of(min(kp) >= kp_lo),
              {"min": r4(min(kp)), "at_phi": int(2 * np.argmin(kp)), "max_of_min": r4(max(kp)),
               "with_full_journal_play_(info)": r4(k_play), "designed": r4(sm["cap_gap"])},
              f">= {kp_lo:.2f} (designed cap_gap {sm['cap_gap']:.2f} - {SPEC['rib_tol']}, not below the wheel <-> frame XY "
              f"minimum {SPEC['wheel_frame_xy_min']}; sculpt: replaces knob <-> paw lip, SPEC {SPEC['knob_paw_min']})")
    else:
        F_rim = F ^ zb(p.paw_z0, p.z_umb_top + 1.0)
        W_top = crop(W, zb(p.umb_rim_z1 + lift, p.z_umb_top + lift + 0.05), ann(O, p.R_u - 2.0, p.R_u + 0.5, -1, 30))
        F_paws = F ^ zb(p.z_umb_top - 0.3, p.z_knob_top + 1)
        knob = W ^ cyl((p.r_k, 0.0), p.knob_d / 2 + p.knob_root_fillet + 0.2, p.z_umb_top + lift + 0.02,
                       p.z_knob_top + 1)
        W_ext = W ^ zb(p.z_roof1, 40)
        F_ext = F ^ zb(p.z_roof1 - 0.5, 40)
        sub = {"teeth_fill": [], "cone_funnel_seat": [], "rim_paw_wall": [], "balltop_paw_lip_normal": [],
               "wheel_vs_frame_above_roof": []}
        for phi in np.arange(0, 360, 30.0):
            sub["teeth_fill"].append(gap(F_teeth, W_teeth.rotate((0, 0, phi)), 2.0))
            sub["cone_funnel_seat"].append(gap(F_cone, W_cone.rotate((0, 0, phi)), 2.0))
            sub["rim_paw_wall"].append(gap(F_rim, W_rim.rotate((0, 0, phi)), 2.0))
            sub["balltop_paw_lip_normal"].append(gap(F_paws, W_top.rotate((0, 0, phi)), 2.0))
            sub["wheel_vs_frame_above_roof"].append(gap(F_ext, W_ext.rotate((0, 0, phi)), 2.0))
        for phi in np.arange(0, 45, 0.5):
            sub["teeth_fill"].append(gap(F_teeth, W_teeth.rotate((0, 0, phi)), 2.0))
        subm = {k: r4(min(v)) for k, v in sub.items()}
        R.add("V6.wheel_frame_xy", "wheel <-> frame, XY / normal interfaces (journal excluded)",
              status_of(min(subm.values()) >= SPEC["wheel_frame_xy_min"]), subm,
              f">= {SPEC['wheel_frame_xy_min']} each (designed: teeth 0.50, cone 0.50 normal, rim 0.60, "
              f"knob 1.00; ball fillet <-> 45 deg lip is 0.71 normal / 1.00 vertical)")
        if knob.is_empty() or knob.volume() < 1e-3:
            # recessed finger well (params.wheel_drive == "well"): nothing of the wheel stands above the ball top, so
            # there is no knob <-> paw interface; the well rim is part of the ball top, checked by
            # balltop_paw_lip_normal above (annulus r 16 .. 18.5 includes the well's outer rim at r 16.85)
            above = W ^ zb(p.z_umb_top + lift + 0.01, 60)
            R.add("V6.knob_paw", "knob <-> paw lip (finger well: no protruding knob)",
                  status_of(above.is_empty() or above.volume() < 1e-3),
                  {"wheel_volume_above_ball_top_mm3": r4(0.0 if above.is_empty() else above.volume()),
                   "drive": getattr(p, "wheel_drive", "knob"),
                   "balltop_paw_lip_normal": subm["balltop_paw_lip_normal"]},
                  f"no wheel material above the ball top (finger well); well rim <-> paw lip >= "
                  f"{SPEC['knob_paw_min']} via balltop_paw_lip_normal")
        else:
            for phi in range(0, 360, 2):
                kp.append(gap(F_paws, knob.rotate((0, 0, float(phi))), 3.0))
            R.add("V6.knob_paw", "knob <-> paw lip, phi 0..358 step 2", status_of(min(kp) >= SPEC["knob_paw_min"]),
                  {"min": r4(min(kp)), "at_phi": int(2 * np.argmin(kp)), "max_of_min": r4(max(kp))},
                  f">= {SPEC['knob_paw_min']} (designed 1.00)")

    # face <-> ball rim (FaceMid / FaceUp vs umbrella), all psi, a few phi
    if sculpt:
        # the head body never swings over the yarn ball (ball_keep_r about O): the whole wheel (umbrella, skid rings,
        # cap) against the head above the band.  The chin faces the STATIC yarn ring (frame), so the classic upper
        # bound (an exposed head <-> ball slit < 2 mm) has no head <-> wheel counterpart: that slit is a head <->
        # frame boundary (V6.facemid_roof here, V12 pinch in v_safety)
        # (search 6.0: the true distance, ~4 mm, is reported instead of the 3.0 cap)
        W_ball = W
        fb_search = 6.0
    else:
        W_ball = (W ^ zb(p.z_teeth1 + lift - 0.1, p.z_umb_top + lift + 0.1)) - cyl((p.r_k, 0), 6.5, -1, 30)
        fb_search = 3.0
    H_face = H ^ zb(p.z_band1 + lift + 0.05, p.z_feat + lift + 1)
    fb = []
    for psi in psis:
        hf = H_face.translate((-P[0], -P[1], 0)).rotate((0, 0, float(psi))).translate((P[0], P[1], 0))
        fb.append(min(gap(hf, W_ball.rotate((0, 0, float(ph))), fb_search) for ph in (0.0, 22.5)))
    lo_fb, hi_fb = SPEC["face_ball"]
    if sculpt:
        R.add("V6.face_ball", "head above the band <-> wheel (umbrella / skid rings / cap) over the swing",
              status_of(min(fb) >= lo_fb),
              {"min_capped_at_6": r4(min(fb)), "max_of_min": r4(max(fb)), "at_psi_min": r4(psis[int(np.argmin(fb))]),
               "ball_keep_r": sk.ball_keep_r, "R_u": p.R_u},
              f">= {lo_fb} at every psi (sculpt: the upper bound {hi_fb} is n/a - the chin faces the static yarn ring, "
              f"not the wheel)")
    else:
        R.add("V6.face_ball", "face (FaceMid/FaceUp) <-> ball rim (XY) over the swing",
              status_of(min(fb) >= lo_fb and max(fb) <= hi_fb),
              {"min": r4(min(fb)), "max_of_min": r4(max(fb)), "at_psi_min": r4(psis[int(np.argmin(fb))])},
              f"in [{lo_fb}, {hi_fb}] at every psi (designed 1.53-1.71)")

    # =============================================================== V6 Z gaps (ray census)
    R.log("V6 vertical Z-gap census")
    pp = (p.phi_print, p.psi_print)
    census_poses = {"design_0_0": (0.0, 0.0), "print": pp}
    census = {}
    axes = {"O": O, "P": P}
    zkw = {"area_below": field_min} if sculpt else {}             # (sculpt: float areas without a field, info)
    for k, (phi, psi) in census_poses.items():
        census[k] = z_census(M.posed(phi, psi), axes, **zkw)
    for s in (+1, -1):
        b = M.posed(0.0, s * psi_b)
        census[f"head_{s * psi_b:+.2f}"] = z_census({"frame": b["frame"], "head": b["head"]}, axes, **zkw)
    z_rib_b, z_rib_r = p.z_bp + p.rib_h, p.z_roof1 + p.rib_h
    # (lower body, lower z, upper body, gap_lt) for every rib float and (..., gap_ge) for its field.  With the
    # crown ring (fix round 1) the roof-top ribs moved onto the head: band-top ribs under the crown roof and
    # front-layer ribs hanging over the crown top, both gliding rib_gap from the frame.
    rib_sel = {"back_ribs_to_head": ("frame", z_rib_b, "head", 1.0, None),
               "back_ribs_to_wheel": ("frame", z_rib_b, "wheel", 1.0, None)}
    fld_sel = {"back_plate_to_head": ("frame", p.z_bp, "head", None, None),
               "back_plate_to_wheel": ("frame", p.z_bp, "wheel", None, None)}
    rib_design = p.z_band0 - (p.z_bp + p.rib_h)      # 0.40: the crown ribs keep it in every variant (they are
    #                                                  shortened by z_lift), while the back-rib gap grows by z_lift
    rib_want = {"back_ribs_to_head": rib_gap, "back_ribs_to_wheel": rib_gap}
    fld_want = {"back_plate_to_head": field_min, "back_plate_to_wheel": field_min}
    z_tol = 0.011
    if sculpt:
        # no crown ring / roof / front layer.  The thin designed Z gaps are the back ribs, the frame flats cut at
        # z_band0 - gap_z_floors under the head body's lowest floor (2.39 nominal), the
        # skid rings under the static yarn ring, and the band tops under the frame covers (full-height legs under
        # the chest, lowered legs): the head's and the wheel's lift stops.  The umbrella top under the static ring
        # is the skid rings' field.  (The head floors over the frame's other cut flats sit gap_z + z_lift above
        # them but vary per pose: V6.any_flat_z_gap / V6.face_front_frame.)  The seams over the lifted head band
        # and wheel grow by z_lift with it (gz = gap_z + z_lift); the head floors keep floor_rest more (gzf).
        z_tol = 0.004
        rib_sel.update(frame_cut_flats_to_head=("frame", round(p.z_band0 + lift - gzf, 2), "head", 1.0, None),
                       skid_rings_to_static_ring=("wheel", p.z_umb_top + lift + p.rib_h, "frame", 1.0, None),
                       band_top_to_chest_cover=("head", p.z_band1 + lift, "frame", 0.7, None),
                       lowered_legs_to_cover=("head", sk.leg_low_top + lift, "frame", 0.7, None),
                       collar_top_to_frame=("head", p.z_roof0 + lift, "frame", 0.7, None))
        rib_want.update(frame_cut_flats_to_head=gzf, skid_rings_to_static_ring=gz, band_top_to_chest_cover=gz,
                        lowered_legs_to_cover=gz, collar_top_to_frame=gz)
        # (the band's full-height top may run only under the head body, the collar or the wheel, with every leg
        # that leaves the head lowered under a cover: then there is no chest-cover interface to measure)
        rib_optional = {"band_top_to_chest_cover"}
        fld_sel["umbrella_top_to_static_ring"] = ("wheel", p.z_umb_top + lift, "frame", None, None)
        fld_want["umbrella_top_to_static_ring"] = field_min
    elif p.crown_ring:
        rib_sel["band_ribs_to_crown_roof"] = ("head", None, "frame", 0.7, None)      # band ribs (and band groove)
        rib_sel["crown_top_to_front_ribs"] = ("frame", p.z_roof1, "head", 0.7, None)
        fld_sel["band_top_to_crown_roof"] = ("head", p.z_band1 + lift, "frame", None, 0.7)
        # (no field entry over the crown top: the front layer is 3.3+ mm above it and its hanging ribs share the
        # census cluster with it; the 0.40 rib gap there is checked in V6.rib_z)
        rib_want.update(band_ribs_to_crown_roof=rib_design, crown_top_to_front_ribs=rib_design + lift)
        # crown fields: the roof / front layer print as rib floats (arcs + spokes, spans <= ~4.2 mm); the field
        # only has to clear the rib gap plus the sag of such a span: >= rib gap + 0.35.  (z_lift shrinks the
        # band-top field: 1.0 nominal, 0.8 loose.)
        fld_want.update(band_top_to_crown_roof=rib_design + 0.35)
    else:
        rib_sel["roof_ribs_to_face_front"] = ("frame", z_rib_r, "head", 1.0, None)
        fld_sel["roof_to_face_front"] = ("frame", p.z_roof1, "head", None, None)
    rib = {k: [] for k in rib_sel}
    fld = {k: [] for k in fld_sel}
    other_min = []
    for k, cl in census.items():
        for key, (lo, lo_z, up, lt, ge) in rib_sel.items():
            g0, _, n = census_select(cl, lo, lo_z, up, "flat", gap_lt=lt, gap_ge=ge, z_tol=z_tol)
            if n:
                rib[key].append(g0)
        for key, (lo, lo_z, up, lt, ge) in fld_sel.items():
            g0, _, n = census_select(cl, lo, lo_z, up, "flat", gap_lt=lt, gap_ge=ge, z_tol=z_tol)
            if n:
                fld[key].append(g0)
        for c in cl:   # every flat-over-flat gap between two different bodies
            if c["lower_face"] == "flat" and c["upper_face"] == "flat":
                other_min.append((c["gap_min"], k, c["lower"], c["lower_z"], c["upper"], c["at_min_xy"], c["zone"]))
    if not p.crown_ring and not sculpt:
        rib_want["roof_ribs_to_face_front"] = rib_gap
        fld_want["roof_to_face_front"] = field_min
    rib_m = {k: [r4(min(v)), r4(max(v))] if v else None for k, v in rib.items()}
    rib_opt = rib_optional if sculpt else set()
    rib_ok = all((not v and k in rib_opt) or
                 (v and abs(min(v) - rib_want[k]) <= SPEC["rib_tol"] and abs(max(v) - rib_want[k]) <= SPEC["rib_tol"])
                 for k, v in rib.items())
    fmt = ".4f" if sculpt else ".2f"
    R.add("V6.rib_z", "skid-rib float Z gaps (back ribs under head / wheel; " + (
              "sculpt: cut flats under the head body, skid rings under the static ring, band tops under the covers)"
              if sculpt else "crown: band-top ribs under the roof and front-layer ribs over the crown top)"),
          status_of(rib_ok), rib_m, "per interface " + ", ".join(f"{k} {v:{fmt}}" for k, v in rib_want.items())
          + f" (+- {SPEC['rib_tol']}, min/max over the rib tops, all census poses)")
    fld_m = {k: r4(min(v)) if v else None for k, v in fld.items()}
    fdet = {}
    if sculpt:
        # (info for V9: the floats the sculpt prints straight over a flat at gap_z, with no >= field_min field
        # beside a rib: band tops under the covers, head floors over the frame's cut flats; design pose)
        flo = {"band_tops_under_covers": 0.0, "head_floors_over_frame_flats": 0.0}
        zl_ok = {round(p.z_band1 + lift, 2), round(sk.leg_low_top + lift, 2)}
        for c in census["design_0_0"]:
            if c["zone"] != "field" or c["lower_face"] != "flat" or c["upper_face"] != "flat":
                continue
            if c["lower"] == "head" and c["upper"] == "frame" and c["lower_z"] in zl_ok:
                flo["band_tops_under_covers"] += c["area_below_mm2"]
            elif c["lower"] == "frame" and c["upper"] == "head" and c["lower_z"] not in (p.z_bp, round(z_rib_b, 2)):
                flo["head_floors_over_frame_flats"] += c["area_below_mm2"]
        fdet = {"(info)_float_area_with_gap_below_field_min_mm2": {k: round(v, 1) for k, v in flo.items()}}
    R.add("V6.field_z", "float field Z gaps (back plate / " + ("umbrella top under the static ring" if sculpt else
                                                                 "crown roof / crown top") + " under the floats)",
          status_of(all(fld_m[k] is not None and fld_m[k] >= fld_want[k] - 1e-3 for k in fld_m)), dict(fld_m, **fdet),
          "per interface >= " + ", ".join(f"{k} {v:.2f}" for k, v in fld_want.items()))
    other_min.sort(key=lambda t: t[0])
    R.add("V6.any_flat_z_gap", "smallest flat-over-flat Z gap between different bodies anywhere (census poses)",
          status_of(other_min[0][0] >= min(rib_want.values()) - SPEC["rib_tol"]),
          {"min": r4(other_min[0][0]), "where": {"pose": other_min[0][1], "lower": other_min[0][2],
                                                  "lower_z": other_min[0][3], "upper": other_min[0][4],
                                                  "xy": other_min[0][5], "zone": other_min[0][6]},
           "n_clusters_below_0.6": len([t for t in other_min if t[0] < 0.6])},
          f">= {min(rib_want.values()) - SPEC['rib_tol']:.2f} (nothing tighter than the designed rib floats)")
    cl = census["design_0_0"]
    g_legs = census_select(cl, "head", p.z_band1 + lift, "frame", "flat", z_tol=z_tol)[0]
    g_pal = census_select(cl, "head", p.z_pallet_top + lift, "wheel", "flat", z_tol=z_tol)[0]
    g_ridge = min(census_select(cl, "wheel", None, "frame", None, zone="journal_O")[0],
                  census_select(cl, "head", None, "frame", None, zone="journal_P")[0])
    if sculpt:
        # no roof (the band top glides under the frame covers), no paw lips (the static yarn ring floats over the
        # skid rings), no roof top under the cone (the wheel envelope's ledges are): any frame upward face under the
        # slanted cone, and a missing interface fails instead of passing on inf
        g_cone = census_select(cl, "frame", None, "wheel", "slanted")[0]
        g_lip = census_select(cl, "wheel", p.z_umb_top + lift + p.rib_h, "frame", "flat", z_tol=z_tol)[0]
        want_legs = gz
        # the head's top seam at the design pose: the hub collar under the frame (gz; the band top beside it lies
        # under the collar's cut, gz + the collar's 1.0, reported as info)
        g_collar = census_select(cl, "head", p.z_roof0 + lift, "frame", "flat", z_tol=z_tol)[0]
        R.add("V6.designed_z_gaps", "other designed Z gaps from the ray census at phi 0 / psi 0 (sculpt: collar, "
                                    "covers, static ring)",
              status_of(abs(g_collar - want_legs) <= 0.02 and abs(g_pal - z_pal_plate) <= 0.02
                        and math.isfinite(g_cone) and g_cone >= SPEC["wheel_frame_z_min"] and abs(g_lip - gz) <= 0.02),
              {"head_collar_top_to_frame": r4(g_collar), "head_band_top_to_frame_(info)": r4(g_legs),
               "pallet_top_to_umbrella_plate": r4(g_pal),
               "frame_ledge_to_umbrella_cone_vertical": r4(g_cone), "skid_rings_to_static_ring_vertical": r4(g_lip),
               "ridge_axial_play_vertical_(info)": r4(g_ridge)},
              f"collar<->frame {want_legs:.4f}, pallet<->plate {z_pal_plate:.2f} and skid rings<->static ring "
              f"{gz:.4f} (+-0.02); frame<->cone vertical >= {SPEC['wheel_frame_z_min']} (present)")
    else:
        g_cone = census_select(cl, "frame", p.z_roof1, "wheel", "slanted")[0]
        g_lip = census_select(cl, "wheel", None, "frame", None)[0]          # ball rim / knob -> paw lips (field)
        want_legs = p.z_roof0 - p.z_band1 - lift
        want_lip = 1.0 - lift - 0.02
        # (a missing roof <-> cone interface returns inf: it must fail, not pass)
        R.add("V6.designed_z_gaps", "other designed Z gaps (SPEC 3.2) from the ray census at phi 0 / psi 0",
              status_of(abs(g_legs - want_legs) <= 0.02 and abs(g_pal - z_pal_plate) <= 0.02
                        and math.isfinite(g_cone) and g_cone >= SPEC["wheel_frame_z_min"] and g_lip >= want_lip),
              {"head_band_top_to_roof_underside": r4(g_legs), "pallet_top_to_umbrella_plate": r4(g_pal),
               "roof_top_to_umbrella_cone_vertical": r4(g_cone), "ball_rim_to_paw_lip_vertical": r4(g_lip),
               "ridge_axial_play_vertical_(info)": r4(g_ridge)},
              f"legs<->roof {want_legs:.2f} and pallet<->plate {z_pal_plate:.2f} (+-0.02); roof<->cone vertical >= "
              f"{SPEC['wheel_frame_z_min']}; ball<->paw lip vertical >= {want_lip:.2f} (SPEC 3.2 >= 1.00, minus "
              f"z_lift)")
    info["census"] = census

    # =============================================================== V7 print pose (exported STL)
    R.log("V7 print pose on the exported STL")
    v7(R, M, skin, variant)

    # =============================================================== V11 captivity
    R.log("V11 captivity")
    v11(R, M, psis, C, phis_c)

    # =============================================================== V5 adversarial: axial play corners
    R.log("V5x axial play corners")
    zplay(R, M, hw)

    st = [c["status"] for c in R.checks]
    rep = {"skin": skin, "variant": variant, "time_s": round(time.time() - R.t0, 1),
           "n_pass": st.count("pass"), "n_warn": st.count("warn"), "n_fail": st.count("fail"),
           "pass": "fail" not in st, "checks": R.checks, "info": info,
           "sweeps": {"frame_head": [{k: r4(v) for k, v in r.items()} for r in rows],
                      "frame_wheel_min_gap_by_phi": {f"{r['phi']:g}": r4(r["gap"]) for r in wrows[::4]},
                      "face_ball_by_psi": {f"{psi:+.2f}": r4(g) for psi, g in zip(psis[::5], fb[::5])},
                      "knob_paw_by_phi": {str(2 * i): r4(g) for i, g in enumerate(kp) if i % 10 == 0}}}
    return rep


# --------------------------------------------------------------------------------------------- V7
def _identify(shells, model_bodies):
    """Match STL shells to model bodies by volume (closest)."""
    out = {}
    for k, b in model_bodies.items():
        vb = b.volume()
        j = int(np.argmin([abs(s.volume() - vb) for s in shells]))
        out[k] = shells[j]
    return out


def v7(R: Report, M, skin: str, variant: str):
    p = M.params
    stl = REPO / "stl" / skin / f"purrbobble_{skin}_{variant}.stl"
    if not stl.exists():
        R.add("V7.stl", "exported print-pose STL", "not-run", None, f"{stl} missing")
        return
    tm = trimesh.load(str(stl), force="mesh")
    tm.merge_vertices()
    parts = tm.split(only_watertight=False)
    shells_tm = sorted(parts, key=lambda t: -t.volume)
    wt = [bool(s.is_watertight) for s in shells_tm]
    wc = [bool(s.is_winding_consistent) for s in shells_tm]
    shells = []
    err = None
    for s in shells_tm:
        try:
            m = Manifold(_m3d_mesh(s))
            shells.append(m)
        except Exception as e:  # noqa: BLE001
            err = str(e)
    ok_shells = len(shells_tm) == 3 and all(wt) and all(wc) and err is None and all(
        len(s.decompose()) == 1 for s in shells)
    det = {"file": str(stl.relative_to(REPO)), "shells": len(shells_tm), "watertight": wt, "winding_consistent": wc,
           "to_manifold_error": err, "volumes": [r4(s.volume) for s in shells_tm]}
    frag_only = False
    if hasattr(M.skin, "sculpt") and not ok_shells and len(shells_tm) > 3:
        # sculpt: shells beyond the three bodies are reported with their location (V7.shells stays failed); when
        # they are only zero-volume fragments (triangles collapsed by the float32 STL coordinates split off the
        # dense bodies) and the three largest shells are valid bodies, the other V7 checks still run on those three
        extra = shells_tm[3:]
        det["extra_shells"] = {"n": len(extra), "faces": int(sum(len(s.faces) for s in extra)),
                               "max_abs_volume_mm3": r4(max(abs(float(s.volume)) for s in extra)),
                               "bbox_centres": [[r4(v) for v in s.bounds.mean(axis=0)] for s in extra[:8]]}
        try:
            main = [Manifold(_m3d_mesh(s)) for s in shells_tm[:3]]
            frag_only = (all(wt[:3]) and all(wc[:3]) and all(len(m.decompose()) == 1 for m in main)
                         and all(abs(float(s.volume)) < 1e-3 for s in extra))
        except Exception:  # noqa: BLE001
            main = []
        det["remaining_V7_checks_on_the_3_body_shells"] = frag_only
        if frag_only:
            shells = main
    R.add("V7.shells", "exported STL = three watertight, consistently wound, single-component shells",
          status_of(ok_shells), det, "3 shells, each watertight + valid manifold")
    if not ok_shells and not frag_only:
        return
    model = M.print_pose()
    B = _identify(shells, model)
    diff = {k: r4((B[k] - model[k]).volume() + (model[k] - B[k]).volume()) for k in model}
    R.add("V7.stl_matches_model", "exported STL equals the model at the print pose (symmetric difference)",
          status_of(all(v is not None and v < 0.05 for v in diff.values())),
          {"sym_diff_mm3": diff, "pose": [p.phi_print, p.psi_print]}, "< 0.05 mm^3 per body (STL is current)")
    names = list(B)
    pair = {}
    gmin = math.inf
    disjoint = True
    # (sculpt: its bodies face each other across 0.41 / 0.5 mm seams over their whole interface, and a 5 mm search
    # takes ~10 min on frame | head; 1 mm finds the same minimum, and gaps above 1 mm then read 1.0)
    srch = 1.0 if hasattr(M.skin, "sculpt") else 5.0
    for i in range(3):
        for j in range(i + 1, 3):
            a, b = B[names[i]], B[names[j]]
            v = ov(a, b)
            g = 0.0 if v > OV_EPS else gap(a, b, srch)
            pair[f"{names[i]}|{names[j]}"] = {"overlap_mm3": r4(v), "min_gap": r4(g)}
            disjoint &= v <= OV_EPS
            gmin = min(gmin, g)
    R.add("V7.disjoint_min_gap", "print pose: pairwise disjoint, global minimum gap",
          status_of(disjoint and gmin >= SPEC["print_gap_min"] - SPEC["print_gap_tol"]),
          dict({"global_min_gap": r4(gmin), "pairs": pair}, **({"gap_search_mm": srch} if srch != 5.0 else {})),
          f"overlap 0; gap >= {SPEC['print_gap_min']} (tol {SPEC['print_gap_tol']} for the exactly-0.35 journals)")
    z0, z1 = p.z_band0 + p.z_lift + 0.05, p.z_band1 + p.z_lift - 0.05
    g_pt = gap(B["head"] ^ zb(z0, z1), B["wheel"] ^ zb(z0, z1), 5.0)
    R.add("V7.pallet_tooth", "print pose: pallet / head band <-> tooth gap (3-D band layer)",
          status_of(g_pt >= SPEC["pallet_tooth_min"]), r4(g_pt), f">= {SPEC['pallet_tooth_min']}")
    tmf = REPO / "stl" / skin / f"purrbobble_{skin}_{variant}.3mf"
    if tmf.exists():
        v7_3mf(R, tmf, model)
    zmins = {k: r4(B[k].bounding_box()[2]) for k in ("head", "wheel")}
    R.add("V7.first_layer", "print pose: floating bodies start above the rib tops (no moving gap in the first layers)",
          status_of(all(v >= p.z_bp + p.rib_h + 0.38 for v in zmins.values())), zmins,
          f"min z >= {p.z_bp + p.rib_h + 0.38:.2f}")


def v7_3mf(R: Report, path: Path, model: dict):
    """The 3MF (one object, named volumes by triangle range, PrusaSlicer per-volume config) must contain the same
    three bodies as the model at the print pose, with frame 20 % gyroid and head / wheel 100 % infill."""
    import re
    import zipfile
    import manifold3d as m3d
    z = zipfile.ZipFile(path)
    txt = z.read("3D/3dmodel.model").decode()
    cfg = z.read("Metadata/Slic3r_PE_model.config").decode() if "Metadata/Slic3r_PE_model.config" in z.namelist() else ""
    V = np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', txt), dtype=np.float64)
    T = np.array(re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"', txt), dtype=np.int64)
    n_obj = len(re.findall(r"<object ", txt))
    has_tf = "transform=" in txt
    vols = re.findall(r'<volume firstid="(\d+)" lastid="(\d+)">(.*?)</volume>', cfg, flags=re.S)
    parts, settings, diffs, errs = {}, {}, {}, []
    for a, b, body in vols:
        name = re.search(r'key="name" value="([^"]+)"', body)
        name = name.group(1) if name else f"vol{a}"
        settings[name] = dict(re.findall(r'key="(fill_density|fill_pattern)" value="([^"]+)"', body))
        tri = T[int(a): int(b) + 1]
        used, inv = np.unique(tri.ravel(), return_inverse=True)
        try:
            m = m3d.Manifold(m3d.Mesh(vert_properties=V[used].astype(np.float32),
                                      tri_verts=inv.reshape(-1, 3).astype(np.uint32)))
            if m.status() != m3d.Error.NoError:
                raise ValueError(str(m.status()))
            parts[name] = m
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name}: {e}")
    for k, mb in model.items():
        if k in parts:
            diffs[k] = r4((parts[k] - mb).volume() + (mb - parts[k]).volume())
    want = {"frame": {"fill_density": "20%", "fill_pattern": "gyroid"}, "wheel": {"fill_density": "100%"},
            "head": {"fill_density": "100%"}}
    ok_set = all(all(settings.get(k, {}).get(kk) == vv for kk, vv in w.items()) for k, w in want.items())
    ok = (n_obj == 1 and not has_tf and not errs and set(parts) == set(model)
          and all(v is not None and v < 0.05 for v in diffs.values()) and ok_set)
    R.add("V7.3mf", "3MF = one object, three named parts equal to the print-pose bodies, per-part infill set",
          status_of(ok), {"file": str(path.relative_to(REPO)), "objects": n_obj, "transforms": has_tf,
                          "parts": sorted(parts), "sym_diff_mm3": diffs, "settings": settings, "errors": errs},
          "1 object / 3 valid parts, sym. difference < 0.05 mm^3 each, frame 20 % gyroid, wheel + head 100 %")


def _m3d_mesh(t: trimesh.Trimesh):
    import manifold3d as m3d
    return m3d.Mesh(vert_properties=np.asarray(t.vertices, dtype=np.float32),
                    tri_verts=np.asarray(t.faces, dtype=np.uint32))


# --------------------------------------------------------------------------------------------- V11
def ridgeless_frame(M) -> tuple[Manifold, float]:
    """Frame with both post V-ridges deleted (post core kept at r - 1 um over the ridge band)."""
    p = M.params
    zr0, zr1 = p.ridge_z - p.ridge_h - 0.1, p.ridge_z + p.ridge_h + 0.1
    F = M.frame
    out = F
    for c in ((0.0, 0.0), p.P):
        tube = cyl(c, p.ridge_apex_r + 0.4, zr0, zr1) - cyl(c, p.post_r - 0.001, zr0 - 0.1, zr1 + 0.1, 512)
        out = out - tube
    return out, float(F.volume() - out.volume())


def play(frame: Manifold, fn, hi: float, tol: float) -> float:
    if not blocked(frame, fn(hi))[0]:
        return math.inf
    lo = 0.0
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if blocked(frame, fn(mid))[0]:
            hi = mid
        else:
            lo = mid
    return lo


DIRS = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}
TILTS = {"rx+": (1, 0), "rx-": (-1, 0), "ry+": (0, 1), "ry-": (0, -1)}


def _com(m: Manifold):
    t = to_tm(m)
    return t.center_mass


def v11(R: Report, M, psis, C, phis_c):
    p = M.params
    sculpt = hasattr(M.skin, "sculpt")
    F = M.frame
    Fnr, removed = ridgeless_frame(M)
    exp_ridge = 2 * 0.5 * (2 * p.ridge_h) * p.ridge_h * 2 * math.pi * (p.post_r + p.ridge_h / 3)
    R.log(f"ridge-less frame: removed {removed:.2f} mm^3 (two ridges ~{exp_ridge:.2f})")
    poses = [((18.0 * k + 3.0) % 360.0, float(x)) for k, x in enumerate(np.linspace(-p.psi_b, p.psi_b, 20))]
    zc = p.ridge_z + p.z_lift
    com_h = _com(M.head)
    com_w = _com(M.wheel)
    d, t = SPEC["captive_disp"], SPEC["captive_tilt"]
    for fname, frame in (("with_ridges", F), ("ridges_deleted", Fnr)):
        fails, marginal = [], []
        n = 0
        for phi, psi in poses:
            for bname in ("head", "wheel"):
                if bname == "head":
                    body = M.head_at(psi)
                    piv_j = (p.P[0], p.P[1], zc)
                    c = com_h
                    a, s_ = math.radians(psi), (com_h[0] - p.P[0], com_h[1] - p.P[1])
                    piv_c = (p.P[0] + s_[0] * math.cos(a) - s_[1] * math.sin(a),
                             p.P[1] + s_[0] * math.sin(a) + s_[1] * math.cos(a), c[2])
                else:
                    body = M.wheel_at(phi)
                    piv_j = (0.0, 0.0, zc)
                    a = math.radians(phi)
                    piv_c = (com_w[0] * math.cos(a) - com_w[1] * math.sin(a),
                             com_w[0] * math.sin(a) + com_w[1] * math.cos(a), com_w[2])
                tests = {k: body.translate(tuple(d * np.array(v, float))) for k, v in DIRS.items()}
                for k, (sx, sy) in TILTS.items():
                    tests[f"{k}@journal"] = tilt(body, piv_j, sx * t, sy * t)
                    tests[f"{k}@com"] = tilt(body, piv_c, sx * t, sy * t)
                for k, b in tests.items():
                    n += 1
                    ok, v, g = blocked(frame, b)
                    if not ok:
                        g = float(frame.min_gap(b, 1.0))
                        (marginal if g <= SPEC["lift_tol"] else fails).append(
                            {"body": bname, "phi": phi, "psi": round(psi, 3), "move": k, "gap_left": r4(g)})
        R.add(f"V11.displace_{fname}", f"captivity, {fname.replace('_', ' ')}: 1.0 mm +-X/Y/Z and +-3 deg tilts "
              f"(journal + COM pivots) at 20 poses", status_of(not fails, warn=bool(marginal)),
              {"tests": n, "not_blocked": len(fails), "examples": fails[:6], "marginal_not_blocked": len(marginal),
               "marginal_examples": marginal[:6]},
              f"every displaced / tilted body interferes with the frame (marginal = still free by <= "
              f"{SPEC['lift_tol']} mm after the 1.0 mm move: a stop designed at exactly 1.0, reported as warn)")

    # free play by bisection (two poses), with and without ridges
    R.log("V11 play by bisection")
    play_tab = {}
    for fname, frame in (("with_ridges", F), ("ridges_deleted", Fnr)):
        for bname, (phi, psi) in (("head", (0.0, p.psi_print)), ("head", (0.0, -p.psi_b)),
                                  ("wheel", (p.phi_print, 0.0)), ("wheel", (200.0, 0.0))):
            body = M.head_at(psi) if bname == "head" else M.wheel_at(phi)
            piv = (p.P[0], p.P[1], zc) if bname == "head" else (0.0, 0.0, zc)
            row = {}
            for k, v in DIRS.items():
                row[k] = r4(play(frame, lambda s, v=v: body.translate(tuple(s * np.array(v, float))), 3.0, 0.002))
            for k, (sx, sy) in TILTS.items():
                row[k + "_deg"] = r4(play(frame, lambda a, sx=sx, sy=sy: tilt(body, piv, sx * a, sy * a), 10.0, 0.01))
            play_tab[f"{fname}|{bname}|phi{phi:g}|psi{psi:+.2f}"] = row
    zplay_ridge = {b: min(v["+Z"] for k, v in play_tab.items() if k.startswith("with_ridges|" + b)) for b in ("head", "wheel")}
    max_xy = max(max(v[k] for k in ("+X", "-X", "+Y", "-Y")) for v in play_tab.values())
    R.add("V11.play", "free play before contact with the frame (bisection)",
          status_of(max_xy <= p.bore_r - p.post_r + 0.02 and max(zplay_ridge.values()) < SPEC["captive_disp"]),
          play_tab, "XY play = journal; +Z play with ridges = ridge axial play (< 1.0); tilt play < 3 deg")
    lift_nr = {b: max(v["+Z"] for k, v in play_tab.items() if k.startswith("ridges_deleted|" + b)) for b in ("head", "wheel")}
    lift_scan = {"wheel": {}, "head": {}}
    for phi in np.arange(0.0, 45.0, 3.0):
        b = M.wheel_at(float(phi))
        lift_scan["wheel"][f"{phi:g}"] = r4(play(Fnr, lambda s, b=b: b.translate((0, 0, s)), 2.0, 0.0005))
    for psi in np.linspace(-p.psi_b, p.psi_b, 7):
        b = M.head_at(float(psi))
        lift_scan["head"][f"{psi:+.2f}"] = r4(play(Fnr, lambda s, b=b: b.translate((0, 0, s)), 2.0, 0.0005))
    for bname in lift_nr:
        lift_nr[bname] = max(lift_nr[bname], max(lift_scan[bname].values()))

    # which feature stops the ridge-less lift?
    stops = {}
    all_pcs = {}
    for bname in ("head", "wheel"):
        body = M.head_at(p.psi_print) if bname == "head" else M.wheel_at(p.phi_print)
        dz = lift_nr[bname] + 0.03
        x = Fnr ^ body.translate((0, 0, dz))
        pcs = []
        for q in x.decompose():
            bb = q.bounding_box()
            cx, cy = 0.5 * (bb[0] + bb[3]), 0.5 * (bb[1] + bb[4])
            pcs.append({"vol": r4(q.volume()), "z": [r4(bb[2]), r4(bb[5])], "r_from_O": r4(math.hypot(cx, cy)),
                        "xy": [r4(cx), r4(cy)]})
            if sculpt:   # (the static ring's contacts are whole annuli about O: their bbox centre is O itself)
                v = np.asarray(q.to_mesh().vert_properties, dtype=np.float64)[:, :2]
                pcs[-1]["r_min_from_O"] = r4(np.hypot(v[:, 0], v[:, 1]).min())
        pcs.sort(key=lambda d: -d["vol"])
        all_pcs[bname] = pcs
        stops[bname] = {"max_lift_play": lift_nr[bname], "lift_play_scan": lift_scan[bname],
                        "contacts_at_play+0.03": pcs[:6]}
    if sculpt:
        # head stopped by the frame covers over its band (the chest over the full-height legs, the cover over the
        # lowered legs: z ~ cover underside), the wheel by the static yarn ring over its skid rings (z > umbrella
        # top, outside the cap's radial gap); every contact piece must be one of these
        sk = M.skin
        from purrbobble.sculpt import seams
        sm_ = seams(sk, p)
        z_cov = (sm_["band_top_seam_z"], sm_["lowered_env_top"], sm_["collar_top_seam_z"])
        head_roof = bool(all_pcs["head"]) and all(min(abs(c["z"][0] - z) for z in z_cov) < 0.1 for c in all_pcs["head"])
        wheel_paw = bool(all_pcs["wheel"]) and all(c["z"][0] >= p.z_umb_top + p.z_lift and c["r_min_from_O"] >=
                                                   sk.cap_r + sm_["cap_gap"] - 0.05 for c in all_pcs["wheel"])
        stops.update(n_contacts={k: len(v) for k, v in all_pcs.items()}, cover_underside_z=[r4(z) for z in z_cov])
        name = "ridge-less lift stop: head by the frame covers over its band, wheel by the static yarn ring"
    else:
        # head must be stopped by the roof (z ~ roof underside) and the wheel by the paw lips (r >= paw_lip_r,
        # z > ball top)
        head_roof = any(abs(c["z"][0] - M.params.z_roof0) < 0.1 for c in stops["head"]["contacts_at_play+0.03"])
        wheel_paw = all(c["r_from_O"] is not None and c["r_from_O"] >= p.paw_lip_r - 1.0 and c["z"][0] >= p.z_umb_top
                        for c in stops["wheel"]["contacts_at_play+0.03"]) and stops["wheel"]["contacts_at_play+0.03"]
        name = "ridge-less lift stop: head by the roof (I3 slot / bridges), wheel by the paw lips"
    lim = SPEC["ridgeless_lift_max"] + SPEC["lift_tol"]
    R.add("V11.second_capture", name,
          status_of(lift_nr["head"] <= lim and lift_nr["wheel"] <= lim and head_roof and bool(wheel_paw),
                    warn=max(lift_nr.values()) > SPEC["ridgeless_lift_max"] - 0.01),
          stops, f"lift <= {SPEC['ridgeless_lift_max']} (+{SPEC['lift_tol']}) and the contact is at the intended stop; "
                 "warn when the play sits at the 1.0 limit itself")

    # lift-ladder escape search (ridges deleted): beyond the stop, every lateral offset / tilt must still interfere
    R.log("V11 lift ladder")
    ladder_free = []
    n = 0
    for bname in ("head", "wheel"):
        for (phi, psi) in ((p.phi_print, p.psi_print), (33.0, -p.psi_b)):
            body = M.head_at(psi) if bname == "head" else M.wheel_at(phi)
            ax = p.P if bname == "head" else (0.0, 0.0)
            for dz in (lift_nr[bname] + 0.1, 1.5, 2.5, 4.0):
                for dx in (-0.3, 0.0, 0.3):
                    for dy in (-0.3, 0.0, 0.3):
                        for rx in (-1.5, 0.0, 1.5):
                            for ry in (-1.5, 0.0, 1.5):
                                b = tilt(body, (ax[0], ax[1], zc), rx, ry).translate((dx, dy, dz))
                                n += 1
                                if ov(Fnr, b) <= OV_EPS:
                                    ladder_free.append({"body": bname, "phi": phi, "psi": psi, "dz": round(dz, 3),
                                                        "dx": dx, "dy": dy, "rx": rx, "ry": ry})
    R.add("V11.lift_ladder", "ridge-less escape search: lift beyond the stop x lateral offsets x tilts",
          status_of(not ladder_free), {"configs": n, "free_configs": len(ladder_free), "examples": ladder_free[:6]},
          "no configuration with lift > stop is free of the frame")


# --------------------------------------------------------------------------------------------- V5x
def zplay(R: Report, M, hw):
    """Adversarial: head and wheel at opposite ends of their axial play (measured against the frame)."""
    p = M.params
    F = M.frame
    hb = M.head_at(p.psi_print)
    wb = M.wheel_at(p.phi_print)
    up_h = play(F, lambda s: hb.translate((0, 0, s)), 3.0, 0.002)
    dn_h = play(F, lambda s: hb.translate((0, 0, -s)), 3.0, 0.002)
    up_w = play(F, lambda s: wb.translate((0, 0, s)), 3.0, 0.002)
    dn_w = play(F, lambda s: wb.translate((0, 0, -s)), 3.0, 0.002)
    rng = np.random.default_rng(1)
    idx = rng.choice(len(hw), size=min(300, len(hw)), replace=False)
    res = {}
    for name, dzh, dzw in (("head_up_wheel_down", up_h, -dn_w), ("head_down_wheel_up", -dn_h, up_w)):
        vmax, worst, n_ov = 0.0, None, 0
        for k in idx:
            phi, psi = hw[k, 0], hw[k, 1]
            v = ov(M.head_at(psi).translate((0, 0, dzh)), M.wheel_at(phi).translate((0, 0, dzw)))
            if v > OV_EPS:
                n_ov += 1
            if v > vmax:
                vmax, worst = v, (float(phi), float(psi))
        loc = None
        if worst:
            x = M.head_at(worst[1]).translate((0, 0, dzh)) ^ M.wheel_at(worst[0]).translate((0, 0, dzw))
            bb = x.bounding_box()
            loc = {"z": [r4(bb[2]), r4(bb[5])], "xy_centre": [r4(0.5 * (bb[0] + bb[3])), r4(0.5 * (bb[1] + bb[4]))]}
        res[name] = {"dz_head": r4(dzh), "dz_wheel": r4(dzw), "poses": int(len(idx)), "poses_with_overlap": n_ov,
                     "max_overlap_mm3": r4(vmax), "worst_pose": worst, "overlap_region": loc}
    rel = up_h + dn_w
    gap_pp = p.z_teeth1 - p.z_pallet_top
    R.add("V5x.axial_play_corners", "head x wheel with the two bodies at opposite ends of their axial play",
          "warn" if any(v["poses_with_overlap"] for v in res.values()) else "pass",
          {"axial_play_head_up/down": [r4(up_h), r4(dn_h)], "axial_play_wheel_up/down": [r4(up_w), r4(dn_w)],
           "relative_head_up_wheel_down": r4(rel), "pallet_plate_gap": gap_pp, **res},
          "adversarial (not a SPEC criterion): overlap here means the pallet tops can rub the umbrella plate when "
          "the knob is pressed in while the head sits high")


# --------------------------------------------------------------------------------------------- CLI
def _json_default(o):
    if hasattr(o, "item"):
        return o.item()
    if isinstance(o, (set, tuple)):
        return list(o)
    if isinstance(o, float) and not math.isfinite(o):
        return str(o)
    return str(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skin", default="kitty")
    ap.add_argument("--variant", default="nominal")
    ap.add_argument("--out", default=None, help="report path (default verification/reports/<skin>/kinematics*.json)")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    rep = run(a.skin, a.variant, a.quiet)
    out = Path(a.out) if a.out else (REPO / "verification" / "reports" / a.skin /
                                     ("kinematics.json" if a.variant == "nominal" else f"kinematics_{a.variant}.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1, default=_json_default))
    print(json.dumps({"skin": a.skin, "variant": a.variant, "pass": rep["pass"], "n_pass": rep["n_pass"],
                      "n_warn": rep["n_warn"], "n_fail": rep["n_fail"], "time_s": rep["time_s"],
                      "failed": [c["id"] for c in rep["checks"] if c["status"] == "fail"],
                      "warned": [c["id"] for c in rep["checks"] if c["status"] == "warn"],
                      "report": str(out)}, indent=1))
    sys.exit(0 if rep["pass"] else 1)


if __name__ == "__main__":
    main()
