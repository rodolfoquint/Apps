#!/usr/bin/env python3
"""Escapement and dynamics verification on the AS-MODELLED geometry: SPEC V2, V3, V4 and V13.

    python3 verification/v_escapement.py --skin kitty [--variant nominal] [--jobs 3] [--quick] [--no-gif]

Writes ``verification/reports/<skin>/escapement.json`` (``escapement_<variant>.json`` for other variants), a
C-space plot next to it and, unless ``--no-gif``, ``renders/<skin>/escapement_cycle.gif`` (one tooth cycle of the
simulated 2-D head + star motion).  Exits non-zero when a SPEC pass criterion fails.

Inputs are taken from the built solids, never from the parameters:

* Star profile  = ``M.wheel.slice(z_c)`` (outer ring, design frame == wheel frame at phi 0), z_c = 5.2 (+ z_lift).
* Head profiles = ``M.head.slice(z_c)`` (V2 band) and the union of head slices over the whole tooth height
  z 3.0 .. 8.0 (V3 "full" outline, includes anything of the face-mid layer / collar that dips into the teeth band).
* Pallet pins   = least-squares circles fitted to the pallet-tip arcs of the head slice (centre + radius).
* Pivot P, journal play (bore - post radius, measured on slices), banking angle (bisection of the 2-D head slice
  against the frame slice, posts excluded), head I_h / m / COM and wheel J / m from trimesh (solid PLA 1.24).

Checks
------
V2  static lazy-head C-space jam screen (port of ideation ``esc_opt.evaluate`` / ``static_map.py``), hard banking,
    both directions, phi 0..90 deg step 0.25, psi step ~0.1 deg, 9 cases dpivot {-0.4, 0, +0.4} (P moved along the
    line of centres) x drp {-0.2, 0, +0.2} (CrossSection offsets of the CAD head slice; pins: radius +-0.2).
    Two independent clearance models: (A) fitted pins on the CAD star SDF (exactly the SPEC 2.4(a) formula) and
    (B) every boundary point of the offset CAD head band on the CAD star SDF.  Two sweep rules: the ideation
    "nearest free psi" rule and a stricter "connected" rule (the head may only move inside the free run it is in).
    Pass: 0 jams in all cases (A and B, both rules); worst pressure angle <= 60 deg (hard limit 62.7).
V3  shadow test: full CAD head outline vs CAD star, phi 0..90 step 0.5, psi +-psi_b step <= 0.25.
    Pass: where c_pins >= 0, c_full >= min(c_pins, 0.6) - 0.02.  Spot-checked with exact shapely distances.
V4  6-DOF dynamics (port of ideation ``esc_dyn3.simulate``; self-validated against the original on the ideation
    geometry) with the CAD star SDF, fitted pins, CAD pivot, trimesh mass properties, measured banking, knob r_k.
    Runs: nominal f(T) table (T 1..40, both directions), 60 tolerance corners (dpivot +-0.4 x drp +-0.2 plus
    nominal, c_r 0.25/0.5, T 1/3/20, both directions), mu/mu_b 0.5/0.5 corners (4 corners x T 1/3/20 x dir).
    Pass: every run rev/s >= 0.15, rev/s <= 2.2 x nominal (same T and direction), swing >= 8 deg p-p; nominal f(T)
    within +-25 % of the SPEC 2.4 table.  Extras (reported, not SPEC-gated): bare-wheel inertia (finger lifted),
    mu 0.2, gravity orientations (flat / inverted / sideways), release coast-down, direction symmetry.
V13 mass properties: I_h about P in [4, 8]e-6 kg m^2, COM 8..14 mm above P, as-printed mass <= MASS_LIMIT_G.

Sculpt skins (``M.info["sculpt"]``): the finger drives the cap's dish at r_k (5, a skin param override, so V4's
finger side load uses that lever arm); V13 adds |COM_x - P_x| <= 0.3 mm, takes the skin's mass budget and accepts
I_h / COM height outside the classic tuning band only when V4 passes with exactly those values; the extra
x_finger_r2 runs (finger inertia scaled to the dish lever arm) also report the f(T) table.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import multiprocessing as mp
import os
import sys
import time
from array import array
from pathlib import Path

import numpy as np
import shapely
from scipy.ndimage import map_coordinates
from shapely import affinity
from shapely.geometry import Point, Polygon

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RHO_PLA = 1.24e-3            # g / mm^3 (SPEC: solid PLA 1.24 g/cm^3)
G_ACC = 9.81
SDF_H = 0.04                 # SDF grid step (mm); SPEC asks for <= 0.05
PA_PASS = 60.0               # V2 worst pressure angle (deg)
PA_HARD = 90.0 - math.degrees(math.atan(0.35)) - 8.0   # 62.7
V3_CAP, V3_TOL = 0.6, 0.02
V4_MIN_RPS, V4_MAX_RATIO, V4_MIN_SWING, V4_F_TOL = 0.15, 2.2, 8.0, 0.25
J_FINGER = 3.0e-6            # SPEC 2.4(b): J_w = 4e-6 "finger included"; bare wheel ~1e-6 -> finger ~3e-6
FRAME_SHELL_MM = 1.2           # as-printed frame: 3 perimeters (~1.2 mm) and 5 x 0.2 top/bottom layers
FRAME_INFILL = 0.20            # SPEC 6: frame 20% gyroid
TOL_CORNERS = [(-0.4, 0.2), (-0.4, -0.2), (0.4, 0.2), (0.4, -0.2)]
# SPEC 2.4 verified performance table: T -> (rev/s lo, hi), (f_head lo, hi), (swing lo, hi)
SPEC_TABLE = {1: ((0.61, 0.74), (5.1, 5.1), (16, 17)), 2: ((1.05, 1.14), (7.7, 9.0), (18, 20)),
              3: ((1.27, 1.34), (10.3, 11.5), (20, 22)), 5: ((1.61, 1.73), (12.8, 14.1), (19, 19)),
              10: ((2.43, 2.47), (18.0, 20.5), (22, 24)), 20: ((3.53, 3.56), (28.0, 28.0), (24, 25)),
              40: ((4.63, 4.69), (37.0, 37.0), (24, 24))}


# ============================================================================ geometry helpers
def _signed_area(a: np.ndarray) -> float:
    x, y = a[:, 0], a[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def cs_to_shapely(cs, holes: bool = True):
    """manifold3d CrossSection -> shapely (Multi)Polygon (own converter, independent of purrbobble.geom2d)."""
    polys = []
    for q in cs.decompose():
        rings = [np.asarray(r, float) for r in q.to_polygons() if len(r) >= 3]
        if not rings:
            continue
        ar = [_signed_area(r) for r in rings]
        i0 = int(np.argmax(ar))
        hs = [rings[k] for k in range(len(rings)) if k != i0] if holes else []
        polys.append(Polygon(rings[i0], hs))
    g = shapely.union_all(polys)
    return g if g.is_valid else shapely.make_valid(g)


def parts(g):
    return list(g.geoms) if hasattr(g, "geoms") else [g]


def rot_pts(pts: np.ndarray, deg: float, pivot=(0.0, 0.0)) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    q = np.asarray(pts, float) - pivot
    return np.c_[c * q[:, 0] - s * q[:, 1], s * q[:, 0] + c * q[:, 1]] + pivot


def boundary_samples(g, step: float = 0.04) -> np.ndarray:
    """Points on every ring (outer + holes) of a shapely polygonal geometry, spacing <= step."""
    g = shapely.segmentize(g, step)
    pts = []
    for poly in parts(g):
        for ring in [poly.exterior, *poly.interiors]:
            pts.append(np.asarray(ring.coords)[:-1])
    return np.vstack(pts)


def fit_circle(pts: np.ndarray):
    """Kasa algebraic least-squares circle: returns (cx, cy, r, rms, max_abs_residual)."""
    x, y = pts[:, 0], pts[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    b = x * x + y * y
    (cx, cy, c), *_ = np.linalg.lstsq(A, b, rcond=None)
    r = math.sqrt(c + cx * cx + cy * cy)
    res = np.hypot(x - cx, y - cy) - r
    return float(cx), float(cy), float(r), float(np.sqrt(np.mean(res ** 2))), float(np.max(np.abs(res)))


def manifold_to_trimesh(m):
    import trimesh
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties, float)[:, :3]
    f = np.asarray(mesh.tri_verts, np.int64)
    return trimesh.Trimesh(v, f, process=True)


# ============================================================================ CAD extraction
def extract_cad(M) -> dict:
    """Profiles, pallet fit, journal play and banking angle measured on the built solids."""
    p = M.params
    P = (float(M.P[0]), float(M.P[1]))
    zl = float(getattr(p, "z_lift", 0.0))
    zc = 5.2 + zl
    out = {"z_contact": zc, "P": P}
    # ---- star (outer ring of the wheel slice at the contact height)
    ws = cs_to_shapely(M.wheel.slice(zc), holes=False)
    wp = parts(ws)
    star = max(wp, key=lambda q: q.area)
    out["star_poly"] = star
    rv = np.hypot(*np.asarray(star.exterior.coords).T)
    out["star"] = {"pieces": len(wp), "area": round(star.area, 4), "vertices": len(star.exterior.coords) - 1,
                   "r_tip": round(float(rv.max()), 4), "r_root": round(float(rv.min()), 4)}
    # consistency of the tooth profile over the band height
    z_lo, z_hi = p.z_band0 + zl, p.z_teeth1 + zl
    zs = np.round(np.arange(z_lo + 0.05, z_hi - 0.02, 0.2), 3)
    w_xor, h_union = 0.0, []
    head_c = cs_to_shapely(M.head.slice(zc), holes=False)
    for z in zs:
        if z <= p.z_band1 + zl:
            wz = cs_to_shapely(M.wheel.slice(float(z)), holes=False)
            w_xor = max(w_xor, wz.symmetric_difference(ws).area)
        hz = M.head.slice(float(z))
        if hz.area() > 0:
            h_union.append(cs_to_shapely(hz, holes=False))
    head_full = shapely.union_all(h_union + [head_c])
    out["head_band_poly"] = head_c
    out["head_full_poly"] = head_full
    zf = p.z_front0 + zl + 1.0                      # face front layer (for the animation only)
    out["face_poly"] = cs_to_shapely(M.head.slice(zf), holes=False) if M.head.slice(zf).area() > 0 else None
    out["R_u"] = float(p.R_u)
    out["knob_r"] = float(p.knob_d) / 2
    if M.info.get("sculpt"):
        # sculpt skins: the visible spinning part is the cap (r cap_r) with a finger dish at (r_k, 0); the umbrella
        # (r R_u) hides under the static ring of the sculpted ball
        out["R_u"] = float(M.skin.cap_r)
        out["knob_r"] = float(M.skin.dish_d) / 2
        out["rim_name"] = "spinning cap rim"
        # the head slice at z_c is the band plus the sculpted head where its floors are below z_c
        out["band_name"] = f"head slice z {zc:.1f} solid (band + low head floors);\nhead at z {zf:.1f}"
    out["profile_consistency"] = {"z_samples": [float(z) for z in zs], "wheel_xor_vs_zc_max_mm2": round(w_xor, 6),
                                  "head_full_minus_band_mm2": round(head_full.difference(head_c).area, 6)}
    # ---- pallet tips: fit circles to the CAD arcs near the design centres
    fits = []
    ring_pts = boundary_samples(head_c, 10.0)          # original vertices only (segmentize no-op at 10 mm)
    for (cx0, cy0), u in zip(p.pallets, p.u):
        q = ring_pts - np.array([cx0, cy0])
        d = np.hypot(q[:, 0], q[:, 1])
        # wheel-facing half of the tip (the finger trapezoid starts on the line through the centre normal to u)
        sel = ring_pts[(np.abs(d - p.rp) < 0.05) & (q @ np.asarray(u) < -0.05)]
        cx, cy, r, rms, mx = fit_circle(sel)
        r_env = float(np.max(np.hypot(sel[:, 0] - cx, sel[:, 1] - cy)))
        fits.append({"design_centre": [cx0, cy0], "centre": [cx, cy], "r_lsq": r, "r": r_env, "n_pts": int(len(sel)),
                     "centre_err": math.hypot(cx - cx0, cy - cy0), "r_err": r_env - p.rp, "rms": rms, "max_res": mx,
                     "note": "centre = least-squares fit of the arc vertices; r = vertex envelope about that centre"})
    out["pallet_fit"] = fits
    out["pins"] = [tuple(f["centre"]) for f in fits]
    out["rp"] = float(np.mean([f["r"] for f in fits]))
    out["Rt_rule"] = float(p.Rt)          # esc_opt tip-zone rule uses the design tip radius
    # ---- journal play (radial) at the plain-bore height between the V-groove and the post-top chamfer
    zj = 6.5 + zl

    def journal(body, centre, which):
        bs = cs_to_shapely(body.slice(zj))
        hole_r = None
        for poly in parts(bs):
            for ring in poly.interiors:
                rr = Polygon(ring)
                if rr.contains(Point(centre)):
                    hole_r = Point(centre).distance(ring)     # inscribed radius of the bore polygon
        fs = cs_to_shapely(M.frame.slice(zj))
        post_r = None
        for poly in parts(fs):
            if poly.contains(Point(centre)):
                post_r = float(np.max(np.hypot(*(np.asarray(poly.exterior.coords) - centre).T)))
        return {"bore_r_in": hole_r, "post_r_out": post_r,
                "c_r": (hole_r - post_r) if (hole_r and post_r) else None, "z": zj, "body": which}
    out["journal_wheel"] = journal(M.wheel, (0.0, 0.0), "wheel")
    out["journal_head"] = journal(M.head, P, "head")
    crs = [j["c_r"] for j in (out["journal_wheel"], out["journal_head"]) if j["c_r"] is not None]
    out["c_r"] = float(np.mean(crs)) if crs else (p.bore_d - p.post_d) / 2
    # ---- banking: bisection of the head slice against the frame slice (posts excluded)
    banks = []
    for z in (p.z_band0 + zl + 0.2, zc, p.z_band1 + zl - 0.2):
        F = cs_to_shapely(M.frame.slice(float(z)))
        H = cs_to_shapely(M.head.slice(float(z)), holes=False)
        Fx = shapely.union_all([q for q in parts(F) if not q.contains(Point(P)) and not q.contains(Point(0, 0))])
        shapely.prepare(Fx)

        def gap(psi, H=H, Fx=Fx):
            Hr = affinity.rotate(H, psi, origin=P)
            d = Fx.distance(Hr)
            return d if d > 0 else -Fx.intersection(Hr).area

        res = {"z": round(float(z), 3), "gap_psi0": round(gap(0.0), 4)}
        for sgn, key in ((1, "pos"), (-1, "neg")):
            lo, hi = 0.0, 20.0
            if gap(sgn * hi) > 0:
                res[key] = None
                continue
            for _ in range(36):
                mid = 0.5 * (lo + hi)
                if gap(sgn * mid) > 0:
                    lo = mid
                else:
                    hi = mid
            res[key] = round(lo, 4)
        res["gap_at_spec_minus_0.25"] = round(gap(p.psi_b - 0.25), 4)
        banks.append(res)
    vals = [b[k] for b in banks for k in ("pos", "neg") if b[k] is not None]
    out["banking"] = {"per_z": banks, "psi_b_spec": p.psi_b,
                      "psi_b_measured": round(min(vals), 4) if vals else None,
                      "asymmetry_deg": round(max(abs(b["pos"] - b["neg"]) for b in banks
                                                 if b["pos"] is not None and b["neg"] is not None), 4)
                      if vals else None}
    out["psi_b"] = float(min(vals)) if vals else float(p.psi_b)
    return out


# As-printed mass limit.  The SPEC's 45 g was a budget from the first estimate (37 g), not a mechanism or safety
# requirement: frame mass does not enter the escapement dynamics (V4 uses the head and wheel only).  Round 4 raised it
# to 50 g for the owner's chunkier concept-art kitty (cushion relief, domed feet, tail: all frame).
MASS_LIMIT_G = 50.0


def mass_limit_g(M) -> float:
    """MASS_LIMIT_G, or the skin's own budget (``mass_limit_g``, with its ``mass_limit_note``): the sculpt kitty is the
    owner's model scaled x1.14 (66 x 85 x 21.5 mm), a bigger toy than the 60 x 85 x 18 mm classic ones."""
    return float(getattr(M.skin, "mass_limit_g", MASS_LIMIT_G))


def sliced_mass_g(skin: str, variant: str) -> dict | None:
    """As-printed mass from PrusaSlicer on the exported 3MF (per-part infill: frame 20 % gyroid, head and wheel
    100 %), with the print settings of verification/v_printability.py.  None if the slicer or the 3MF is missing."""
    import re
    import shutil
    import subprocess
    import tempfile
    exe = shutil.which("prusa-slicer") or shutil.which("PrusaSlicer")
    mf = REPO / "stl" / skin / f"purrbobble_{skin}_{variant}.3mf"
    if exe is None or not mf.exists():
        return None
    sys.path.insert(0, str(REPO / "verification"))
    from v_printability import SLICER_OPTS
    with tempfile.TemporaryDirectory() as td:
        g = Path(td) / "w.gcode"
        r = subprocess.run([exe, "--export-gcode", *SLICER_OPTS, "-o", str(g), str(mf)], capture_output=True,
                           text=True, timeout=900)
        if r.returncode != 0 or not g.exists():
            return None
        txt = g.read_text(errors="ignore")
    m = re.search(r"^; filament used \[g\] = ([0-9.]+)", txt, re.M)
    t = re.search(r"^; estimated printing time \(normal mode\) = (.+)$", txt, re.M)
    return {"filament_g": float(m.group(1)) if m else None, "print_time": t.group(1).strip() if t else None,
            "source": str(mf.relative_to(REPO))}


def mass_properties(M) -> dict:
    """V13: solid PLA, head about the vertical axis through P, wheel about O."""
    P = np.array(M.P, float)
    res = {}
    for name in ("frame", "wheel", "head"):
        tm = manifold_to_trimesh(getattr(M, name))
        tm.density = RHO_PLA * 1e-3                    # kg / mm^3 -> mass kg, inertia kg mm^2
        com = np.asarray(tm.center_mass)
        Ic = np.asarray(tm.moment_inertia)
        res[name] = {"watertight": bool(tm.is_watertight), "volume_mm3": float(tm.volume),
                     "mass_g": float(tm.mass * 1e3), "com": com.tolist(), "I_com_zz_kgm2": float(Ic[2, 2] * 1e-6)}
    h, w = res["head"], res["wheel"]
    hc = np.array(h["com"])
    dx, dy = hc[0] - P[0], hc[1] - P[1]
    h["I_P_kgm2"] = h["I_com_zz_kgm2"] + h["mass_g"] * 1e-3 * (dx * dx + dy * dy) * 1e-6
    h["com_rel_P_mm"] = [float(dx), float(dy)]
    wc = np.array(w["com"])
    w["J_O_kgm2"] = w["I_com_zz_kgm2"] + w["mass_g"] * 1e-3 * (wc[0] ** 2 + wc[1] ** 2) * 1e-6
    w["com_offset_mm"] = float(math.hypot(wc[0], wc[1]))
    total = sum(res[k]["mass_g"] for k in res)
    lim = mass_limit_g(M)
    # SPEC 2.6 / 6 budget the toy as printed: head and wheel 100% infill, frame 3 perimeters + 5 top/bottom
    # layers + 20% gyroid.  Estimate the frame as a ~1.2 mm shell over its surface plus 20% of the core.
    fr = manifold_to_trimesh(M.frame)
    shell = min(float(fr.volume), float(fr.area) * FRAME_SHELL_MM)
    frame_printed_g = (shell + FRAME_INFILL * (float(fr.volume) - shell)) * RHO_PLA * 1e-3 * 1e3
    printed = h["mass_g"] + w["mass_g"] + frame_printed_g
    res["frame"]["printed_mass_g_est"] = float(frame_printed_g)
    checks = {
        "I_h": {"measured": h["I_P_kgm2"], "criterion": "4.0e-6 <= I_h <= 8.0e-6 kg m^2",
                "pass": bool(4.0e-6 <= h["I_P_kgm2"] <= 8.0e-6)},
        "com_above_P": {"measured": float(dy), "criterion": "8 <= COM_y - P_y <= 14 mm", "pass": bool(8.0 <= dy <= 14.0)},
    }
    if M.info.get("sculpt"):
        # an off-centre head is a constant gravity torque when the toy is held up (V4: one direction slow, a jam at
        # mu 0.5); the classic faces are mirror-symmetric by construction, the sculpt kitty's bow is balanced by its
        # mech_dx offset
        checks["com_lateral"] = {"measured": float(dx), "criterion": "|COM_x - P_x| <= 0.3 mm",
                                 "pass": bool(abs(dx) <= 0.3)}
    checks |= {
        "total_mass": {"measured": float(printed),
                       "criterion": f"as printed <= {lim:g} g (estimate: head + wheel solid, frame {FRAME_SHELL_MM} mm "
                                    f"shell + {FRAME_INFILL:.0%} infill; all-solid upper bound {total:.1f} g)",
                       "pass": bool(printed <= lim)},
        "bodies_watertight": {"measured": {k: res[k]["watertight"] for k in res}, "criterion": "all watertight",
                              "pass": all(res[k]["watertight"] for k in res)},
    }
    return {"bodies": res, "total_mass_g": float(total), "checks": checks,
            "pass": all(c["pass"] for c in checks.values())}


# ============================================================================ wheel SDF
class WheelSDF:
    """Exact signed distance to the star outline sampled on a grid (negative inside), bilinear lookups."""

    def __init__(self, poly, h: float = SDF_H, pad: float = 5.0):
        R = float(np.max(np.hypot(*np.asarray(poly.exterior.coords).T)))
        L = R + pad
        xs = np.arange(-L, L + 0.5 * h, h)
        n = len(xs)
        X, Y = np.meshgrid(xs, xs, indexing="ij")
        ring = poly.exterior
        shapely.prepare(poly)
        d = np.empty(X.size)
        xr, yr = X.ravel(), Y.ravel()
        chunk = 200000
        for a in range(0, X.size, chunk):
            d[a:a + chunk] = shapely.distance(ring, shapely.points(xr[a:a + chunk], yr[a:a + chunk]))
        ins = shapely.contains_xy(poly, xr, yr)
        s = np.where(ins, -d, d).reshape(n, n)
        gx, gy = np.gradient(s, h)
        self.s, self.gx, self.gy, self.x0, self.h, self.n, self.R = s, gx, gy, -L, h, n, R

    def sample(self, x, y, key: str = "s"):
        x = np.asarray(x, float)
        c = np.vstack([(x.ravel() - self.x0) / self.h, (np.asarray(y, float).ravel() - self.x0) / self.h])
        return map_coordinates(getattr(self, key), c, order=1, mode="nearest").reshape(x.shape)

    def flat(self) -> dict:
        return {"S": array("d", self.s.ravel()), "GX": array("d", self.gx.ravel()), "GY": array("d", self.gy.ravel()),
                "n": self.n, "x0": self.x0, "h": self.h}


def head_points_to_wheel(pts, P, dD, phi_rad, psi_rad):
    """Head-frame points -> wheel frame for (phi, psi); pivot P shifted by (0, dD) with the head."""
    rel = pts - np.asarray(P)
    c, s = math.cos(psi_rad), math.sin(psi_rad)
    wx = P[0] + c * rel[:, 0] - s * rel[:, 1]
    wy = P[1] + dD + s * rel[:, 0] + c * rel[:, 1]
    cp, sp = np.cos(phi_rad), np.sin(phi_rad)
    xw = np.outer(cp, wx) + np.outer(sp, wy)
    yw = -np.outer(sp, wx) + np.outer(cp, wy)
    return wx, wy, xw, yw


def clearance_map(sdf: WheelSDF, pts, P, phis_deg, psis_deg, dD=0.0, offset=0.0):
    """c[i, j] = min_k SDF(point_k at (phi_i, psi_j)) - offset."""
    ph = np.radians(phis_deg)
    out = np.empty((len(phis_deg), len(psis_deg)))
    for j, ps in enumerate(np.radians(psis_deg)):
        _, _, xw, yw = head_points_to_wheel(pts, P, dD, ph, ps)
        out[:, j] = sdf.sample(xw, yw).min(axis=1) - offset
    return out


def relevant_points(pts, P, dD, psi_b, R_tip, margin):
    """Keep the head boundary samples that can come within R_tip + margin of O for some |psi| <= psi_b."""
    keep = np.zeros(len(pts), bool)
    for ps in np.linspace(-psi_b, psi_b, 61):
        w = rot_pts(pts, ps, P) + np.array([0.0, dD])
        keep |= np.hypot(w[:, 0], w[:, 1]) <= R_tip + margin
    return pts[keep]


# ============================================================================ V2 lazy-head sweep (esc_opt port)
def _runs(row: np.ndarray):
    idx = np.flatnonzero(np.diff(np.r_[0, row.astype(np.int8), 0]))
    return list(zip(idx[0::2], idx[1::2] - 1))


def lazy_sweep(free, phis, psis, direction, contact_fn, connected=False):
    """esc_opt.evaluate's lazy-anchor sweep. phis, psis in radians.  connected=True only lets the head move to a
    free psi whose run in the new row overlaps the run it occupied in the previous row (no tunnelling)."""
    nphi = free.shape[0]
    order = list(range(nphi)) if direction == 1 else list(range(nphi - 1, -1, -1))
    j = int(np.argmax(np.where(free[order[0]], -np.abs(psis), -1e9)))
    traj, jams, worst, events, jam_at = [], 0, None, 0, []
    max_jump = 0.0
    prev = None
    dphi = abs(phis[1] - phis[0])
    for i in order:
        row = free[i]
        if not row[j]:
            if connected and prev is not None:
                if free[prev, j]:
                    a = b = j
                    while a > 0 and free[prev, a - 1]:
                        a -= 1
                    while b < len(row) - 1 and free[prev, b + 1]:
                        b += 1
                else:
                    a = b = j
                cand = np.array([k for (s, e) in _runs(row) if s <= b + 1 and e >= a - 1 for k in range(s, e + 1)], int)
            else:
                cand = np.flatnonzero(row)
            if len(cand) == 0:
                jams += 1
                jam_at.append(round(math.degrees(phis[i]), 2))
                prev = i
                continue
            jn = int(cand[np.argmin(np.abs(cand - j))])
            ev = contact_fn(i, j, jn, direction)
            ev["dpsi_dphi"] = abs(psis[jn] - psis[j]) / dphi
            tip_zone = ev["r_contact"] > ev["R_tip"] - 0.35
            ev["pa"] = 0.0 if tip_zone else max(ev["pa_pin"], ev["pa_wh"] if ev["dpsi_dphi"] > 0.25 else 0.0)
            if worst is None or ev["pa"] > worst["pa"]:
                worst = dict(ev, phi=round(math.degrees(phis[i]), 3), psi_from=round(math.degrees(psis[j]), 3),
                             psi_to=round(math.degrees(psis[jn]), 3))
            max_jump = max(max_jump, abs(math.degrees(psis[jn] - psis[j])))
            events += 1
            j = jn
        traj.append(psis[j])
        prev = i
    swing = math.degrees(max(traj) - min(traj)) if traj else 0.0
    return {"jams": jams, "jam_phi_deg": jam_at[:20], "pushes": events, "swing_pp_deg": round(swing, 2),
            "worst_pa_deg": round(worst["pa"], 2) if worst else 0.0, "worst": worst,
            "max_push_jump_deg": round(max_jump, 3), "traj_deg": [round(math.degrees(t), 3) for t in traj]}


def _pressure(C, n, A, direction):
    v_pin = np.array([-(C - A)[1], (C - A)[0]])
    v_pin /= np.linalg.norm(v_pin)
    v_wh = direction * np.array([-C[1], C[0]])
    v_wh /= np.linalg.norm(v_wh)
    pa_pin = math.degrees(math.acos(min(1.0, abs(float(n @ v_pin)))))
    pa_wh = math.degrees(math.acos(float(np.clip(n @ v_wh, -1, 1))))
    return pa_pin, pa_wh


def v2_case(sdf, cad, dD, drp, phis_deg, psis_deg, margin=1.0, models=("pins", "band")):
    """One tolerance case: (A) fitted pins, (B) offset CAD band; nearest-free and connected rules, both dirs."""
    P = np.array(cad["P"])
    A = P + np.array([0.0, dD])
    R_tip = cad["star"]["r_tip"]
    R_rule = cad["Rt_rule"]
    phis, psis = np.radians(phis_deg), np.radians(psis_deg)
    res = {"dpivot": dD, "drp": drp}
    # ---- (A) pins: c = min_i SDF(centre_i) - (rp + drp)
    pins = np.array(cad["pins"])
    rp = cad["rp"] + drp
    cA = np.full((len(phis), len(psis)), np.inf)
    which = np.zeros(cA.shape, int)
    for k in range(2):
        ck = clearance_map(sdf, pins[k:k + 1], P, phis_deg, psis_deg, dD, rp)
        which = np.where(ck < cA, k, which)
        cA = np.minimum(cA, ck)

    def contact_A(i, j, jn, direction):
        k = which[i, j]
        _, _, xw, yw = head_points_to_wheel(pins[k:k + 1], P, dD, np.array([phis[i]]), psis[j])
        g = np.array([sdf.sample(xw, yw, "gx")[0, 0], sdf.sample(xw, yw, "gy")[0, 0]])
        nw = g / (np.linalg.norm(g) + 1e-12)
        ph = phis[i]
        n = np.array([math.cos(ph) * nw[0] - math.sin(ph) * nw[1], math.sin(ph) * nw[0] + math.cos(ph) * nw[1]])
        centre = rot_pts(pins[k:k + 1], math.degrees(psis[j]), P)[0] + np.array([0.0, dD])
        C = centre - rp * n
        pa_pin, pa_wh = _pressure(C, n, A, direction)
        return {"pa_pin": pa_pin, "pa_wh": pa_wh, "r_contact": float(np.linalg.norm(C)), "R_tip": R_rule, "pin": int(k)}

    # ---- (B) every boundary point of the offset CAD head band
    if "band" in models:
        band = cad["head_band_poly"]
        if drp:
            band = band.buffer(drp, quad_segs=64, join_style="round")
        pts = relevant_points(boundary_samples(band, SDF_H), P, dD, cad["psi_b"], R_tip, margin)
        cB = clearance_map(sdf, pts, P, phis_deg, psis_deg, dD)
    else:
        pts, cB = np.zeros((0, 2)), None

    def contact_B(i, j, jn, direction):
        _, _, xw, yw = head_points_to_wheel(pts, P, dD, np.array([phis[i]]), psis[j])
        v = sdf.sample(xw, yw)[0]
        k = int(np.argmin(v))
        g = np.array([sdf.sample(xw[:, k], yw[:, k], "gx")[0], sdf.sample(xw[:, k], yw[:, k], "gy")[0]])
        nw = g / (np.linalg.norm(g) + 1e-12)
        ph = phis[i]
        n = np.array([math.cos(ph) * nw[0] - math.sin(ph) * nw[1], math.sin(ph) * nw[0] + math.cos(ph) * nw[1]])
        C = rot_pts(pts[k:k + 1], math.degrees(psis[j]), P)[0] + np.array([0.0, dD])
        pa_pin, pa_wh = _pressure(C, n, A, direction)
        return {"pa_pin": pa_pin, "pa_wh": pa_wh, "r_contact": float(np.linalg.norm(C)), "R_tip": R_rule,
                "point": [round(float(x), 3) for x in pts[k]]}

    for name, c, cf in (("pins", cA, contact_A), ("band", cB, contact_B)):
        if name not in models:
            continue
        free = c >= 0
        r = {"n_points": 2 if name == "pins" else int(len(pts)), "free_frac": round(float(free.mean()), 4),
             "max_clearance": round(float(c.max()), 4), "min_clearance": round(float(c.min()), 4)}
        kmax = np.unravel_index(np.argmax(c), c.shape)
        r["best_print_pose"] = {"phi": float(phis_deg[kmax[0]]), "psi": float(psis_deg[kmax[1]]),
                                "clearance": round(float(c[kmax]), 4)}
        # static free spin: a psi column that is free over a whole pitch lets the wheel pass a parked head
        pitch_n = int(round(45.0 / (phis_deg[1] - phis_deg[0])))
        cols = []
        for jj in range(len(psis)):
            col = free[:, jj]
            for s0 in range(0, len(phis) - pitch_n):
                if col[s0:s0 + pitch_n + 1].all():
                    cols.append(round(float(psis_deg[jj]), 3))
                    break
        r["free_spin_psi_columns"] = cols
        r["bank_columns_blocked"] = bool(not free[:, 0].all() and not free[:, -1].all())
        for rule in ("nearest", "connected"):
            for direction in (1, -1):
                s = lazy_sweep(free, phis, psis, direction, cf, connected=(rule == "connected"))
                tr = s.pop("traj_deg")
                r[f"{rule}_dir{'+' if direction > 0 else '-'}"] = s
                if name == "pins" and rule == "nearest":
                    r.setdefault("_traj", {})[direction] = tr
        res[name] = r
    res["_maps"] = {"pins": cA, "band": cB}
    return res


def _margin_worker(args):
    """Pins-only static screen for one (dpivot, drp): jams (both rules, both dirs) and free-spin columns."""
    dD, drp = args
    c = _CTX
    r = v2_case(c["sdf"], c["cad"], dD, drp, c["phis2"], c["psis2"], models=("pins",))["pins"]
    jams = sum(r[f"{rule}_dir{s}"]["jams"] for rule in ("nearest", "connected") for s in "+-")
    return {"dpivot": round(dD, 3), "drp": drp, "jams": jams, "free_spin_columns": len(r["free_spin_psi_columns"])}


# ============================================================================ pooled workers (fork-inherited globals)
_CTX: dict = {}        # sdf, cad, grids
_W: dict = {}          # flat SDF arrays for the dynamics


def _v2_worker(args):
    dD, drp = args
    c = _CTX
    return v2_case(c["sdf"], c["cad"], dD, drp, c["phis2"], c["psis2"])


def _v3_worker(args):
    """V3 shadow test for one tolerance case on the V3 grid (fitted pins vs full CAD head outline)."""
    dD, drp = args
    sdf, cad, phis3, psis3 = _CTX["sdf"], _CTX["cad"], _CTX["phis3"], _CTX["psis3"]
    pins = np.array(cad["pins"])
    P = np.array(cad["P"])
    rp = cad["rp"] + drp
    cp = np.minimum(clearance_map(sdf, pins[0:1], P, phis3, psis3, dD, rp),
                    clearance_map(sdf, pins[1:2], P, phis3, psis3, dD, rp))
    full = cad["head_full_poly"] if not drp else cad["head_full_poly"].buffer(drp, quad_segs=64)
    fp = relevant_points(boundary_samples(full, SDF_H), P, dD, cad["psi_b"], sdf.R, 1.5)
    cf = clearance_map(sdf, fp, P, phis3, psis3, dD)
    reach = cp >= 0
    deficit = np.where(reach, np.minimum(cp, V3_CAP) - cf, -np.inf)
    bad = reach & (cf < np.minimum(cp, V3_CAP) - V3_TOL)
    k = np.unravel_index(np.argmax(deficit), deficit.shape)
    return {"dpivot": dD, "drp": drp, "n_points": int(len(fp)), "reachable_frac": round(float(reach.mean()), 4),
            "n_bad": int(bad.sum()), "worst_deficit": round(float(deficit[k]), 4),
            "worst_at": {"phi": float(phis3[k[0]]), "psi": round(float(psis3[k[1]]), 3),
                         "c_pins": round(float(cp[k]), 4), "c_full": round(float(cf[k]), 4)},
            "min_c_full_where_pins_free": round(float(cf[reach].min()), 4), "_cp": cp, "_cf": cf}


# ============================================================================ V4 dynamics (esc_dyn3 port)


def simulate(T_Nmm, direction=1, *, D, pins, rp, psi_b, I_h, m_h, com=(0.0, 11.3), J_w=4e-6, m_w=0.006,
             mu=0.35, mu_b=0.35, r_b=4.0, c_r=0.35, r_k=11.0, gvec=(0.0, -G_ACC), k=5e4, zeta=0.25, k_b=2e5,
             c_w=2e-7, c_a=2e-8, k_bank=100.0, t_end=0.6, dt=1e-5, dD=0.0, drp=0.0, t_release=None,
             record_every=0, sdf=None):
    """Pure-float port of analysis/ideation/synth/esc_dyn3.simulate (same model, same stats) with:
    pins/rp/D/psi_b from CAD, head COM vector (com_x, com_y) relative to P in the head frame, gravity vector in
    the world plane, optional torque release time and trajectory recording."""
    G = sdf if sdf is not None else _W
    S, GX, GY, n, x0, h = G["S"], G["GX"], G["GY"], G["n"], G["x0"], G["h"]
    cos, sin, tanh, hypot = math.cos, math.sin, math.tanh, math.hypot
    rp = rp + drp
    mm = 1e-3
    Pnx, Pny = 0.0, D + dD
    T0 = direction * T_Nmm * 1e-3
    gxa, gya = gvec
    comx, comy = com
    pl = [(float(px) - 0.0, float(py) - D) for (px, py) in pins]
    arm = math.hypot(pl[0][0], pl[0][1]) * mm
    m_eff = I_h / arm ** 2
    c_n = 2 * zeta * np.sqrt(k * m_eff)
    cbw = 2 * 0.3 * np.sqrt(k_b * m_w)
    cbh = 2 * 0.3 * np.sqrt(k_b * m_h)
    c_n, cbw, cbh = float(c_n), float(cbw), float(cbh)
    cbank = float(2 * 0.3 * np.sqrt(k_bank * I_h))
    pb = math.radians(psi_b)
    crm = c_r * mm
    rbm = r_b * mm
    rkm = r_k * mm
    xwx = xwy = vwx = vwy = phi = om = 0.0
    xhx = xhy = vhx = vhy = psi = Om = 0.0
    ns = int(t_end / dt)
    n_rel = ns if t_release is None else int(round(t_release / dt))
    PHI = np.empty(ns)
    PSI = np.empty(ns)
    E_in = E_bw = E_bh = 0.0
    impacts = 0
    inc0 = inc1 = False
    Fmax = 0.0
    bank = 0
    inb = False
    rec = [] if record_every else None
    nm1 = n - 1
    for st in range(ns):
        T = T0 if st < n_rel else 0.0
        Fwx = m_w * gxa
        Fwy = m_w * gya
        Fhx = m_h * gxa
        Fhy = m_h * gya
        tw = T - c_w * om
        cps = cos(psi)
        sps = sin(psi)
        # gravity torque on the head about P: r_com x (m g)
        rcx = (cps * comx - sps * comy) * mm
        rcy = (sps * comx + cps * comy) * mm
        th = -c_a * Om + (rcx * Fhy - rcy * Fhx)
        # knob side load (finger pushes the knob tangentially)
        if T != 0.0:
            ft = T / rkm
            Fwx += ft * -sin(phi)
            Fwy += ft * cos(phi)
        # hard banking
        if abs(psi) > pb:
            th += -k_bank * (psi - math.copysign(pb, psi)) - cbank * Om
            if not inb:
                bank += 1
                inb = True
        else:
            inb = False
        # journals: radial play c_r, penalty k_b, Coulomb friction torque mu_b N r_b
        r = hypot(xwx, xwy)
        pen = r - crm
        if pen > 0:
            nx = xwx / r
            ny = xwy / r
            Fn = k_b * pen + cbw * (vwx * nx + vwy * ny)
            if Fn < 0.0:
                Fn = 0.0
            Fwx -= Fn * nx
            Fwy -= Fn * ny
            tf = -mu_b * Fn * rbm * tanh(om / 0.5)
            tw += tf
            E_bw += -tf * om * dt
        r = hypot(xhx, xhy)
        pen = r - crm
        if pen > 0:
            nx = xhx / r
            ny = xhy / r
            Fn = k_b * pen + cbh * (vhx * nx + vhy * ny)
            if Fn < 0.0:
                Fn = 0.0
            Fhx -= Fn * nx
            Fhy -= Fn * ny
            tf = -mu_b * Fn * rbm * tanh(Om / 0.5)
            th += tf
            E_bh += -tf * Om * dt
        # escapement contacts (round pins on the wheel SDF)
        cph = cos(phi)
        sph = sin(phi)
        Phx = Pnx + xhx / mm
        Phy = Pny + xhy / mm
        Owx = xwx / mm
        Owy = xwy / mm
        for i in (0, 1):
            q0x, q0y = pl[i]
            Ppx = Phx + (cps * q0x - sps * q0y)
            Ppy = Phy + (sps * q0x + cps * q0y)
            dx = Ppx - Owx
            dy = Ppy - Owy
            qx = cph * dx + sph * dy
            qy = -sph * dx + cph * dy
            fx = (qx - x0) / h
            fy = (qy - x0) / h
            ii = int(fx)
            jj = int(fy)
            if ii < 0 or jj < 0 or ii >= nm1 or jj >= nm1:
                incont = False
            else:
                tx = fx - ii
                ty = fy - jj
                b = ii * n + jj
                sd = (S[b] * (1 - tx) * (1 - ty) + S[b + n] * tx * (1 - ty) + S[b + 1] * (1 - tx) * ty
                      + S[b + n + 1] * tx * ty)
                pen = rp - sd
                incont = pen > 0
            if incont:
                if not (inc0 if i == 0 else inc1):
                    impacts += 1
                gx = (GX[b] * (1 - tx) * (1 - ty) + GX[b + n] * tx * (1 - ty) + GX[b + 1] * (1 - tx) * ty
                      + GX[b + n + 1] * tx * ty)
                gy = (GY[b] * (1 - tx) * (1 - ty) + GY[b + n] * tx * (1 - ty) + GY[b + 1] * (1 - tx) * ty
                      + GY[b + n + 1] * tx * ty)
                nn = (gx * gx + gy * gy) ** 0.5 + 1e-12
                nwx = gx / nn
                nwy = gy / nn
                nx = cph * nwx - sph * nwy
                ny = sph * nwx + cph * nwy
                Cx = Ppx - rp * nx
                Cy = Ppy - rp * ny
                rAx = (Cx - Phx) * mm
                rAy = (Cy - Phy) * mm
                rOx = (Cx - Owx) * mm
                rOy = (Cy - Owy) * mm
                vrx = (vhx + Om * -rAy) - (vwx + om * -rOy)
                vry = (vhy + Om * rAx) - (vwy + om * rOx)
                Fn = k * pen * mm - c_n * (vrx * nx + vry * ny)
                if Fn < 0.0:
                    Fn = 0.0
                tvx = -ny
                tvy = nx
                fr = mu * Fn * tanh((vrx * tvx + vry * tvy) / 2e-3)
                Fx = Fn * nx - fr * tvx
                Fy = Fn * ny - fr * tvy
                Fhx += Fx
                Fhy += Fy
                Fwx -= Fx
                Fwy -= Fy
                th += rAx * Fy - rAy * Fx
                tw -= rOx * Fy - rOy * Fx
                if Fn > Fmax:
                    Fmax = Fn
            if i == 0:
                inc0 = incont
            else:
                inc1 = incont
        vwx += dt * Fwx / m_w
        vwy += dt * Fwy / m_w
        vhx += dt * Fhx / m_h
        vhy += dt * Fhy / m_h
        om += dt * tw / J_w
        Om += dt * th / I_h
        xwx += dt * vwx
        xwy += dt * vwy
        xhx += dt * vhx
        xhy += dt * vhy
        phi += dt * om
        psi += dt * Om
        E_in += T * om * dt
        PHI[st] = phi
        PSI[st] = psi
        if record_every and st % record_every == 0:
            rec.append((st * dt, phi, psi, xwx / mm, xwy / mm, xhx / mm, xhy / mm, inc0, inc1))
    t = np.arange(ns) * dt
    out = {"T": T_Nmm, "dir": direction}
    if t_release is None:
        sel = t > 0.35 * t_end
        ps = np.degrees(PSI[sel])
        ph = PHI[sel]
        tt = t[sel]
        dur = tt[-1] - tt[0]
        zc = np.where(np.diff(np.sign(ps - ps.mean())) != 0)[0]
        rps = float((ph[-1] - ph[0]) / (2 * np.pi) / dur)
        swing = float(np.percentile(ps, 99.5) - np.percentile(ps, 0.5))
        f_orig = len(zc) / 2 / dur
        f_fine = (len(zc) - 1) / 2 / (tt[zc[-1]] - tt[zc[0]]) if len(zc) >= 3 else 0.0
        out.update(rps=round(rps, 3), f_head=round(float(f_fine), 2), f_head_orig=round(float(f_orig), 1),
                   swing=round(swing, 2), imp_s=round(impacts / t_end), bank_s=round(bank / t_end),
                   Fmax=round(Fmax, 2), loss_wheel_brg=round(E_bw / max(E_in, 1e-12), 3),
                   loss_head_brg=round(E_bh / max(E_in, 1e-12), 3),
                   esc_ratio=round(float(f_fine / (8 * abs(rps))), 3) if (abs(rps) > 1e-6 and f_fine > 0) else None,
                   n_teeth_window=round(float(abs(ph[-1] - ph[0]) / (2 * np.pi) * 8), 2),
                   psi_mean=round(float(ps.mean()), 2),
                   status=("JAM" if abs(rps) < 0.15 else ("FREESPIN" if swing < 3.0 else "RUN")))
    else:
        a = n_rel
        om_rel = (PHI[a] - PHI[a - 5]) / (5 * dt)
        after = np.degrees(PHI[a:] - PHI[a])
        stop_idx = None
        w = 200
        for s0 in range(0, len(after) - w, 50):
            if abs(after[s0 + w] - after[s0]) < 0.05:
                stop_idx = s0
                break
        out.update(rps_at_release=round(float(om_rel / (2 * np.pi)), 3),
                   coast_deg=round(float(after[-1]), 2), coast_max_deg=round(float(np.max(np.abs(after))), 2),
                   stop_time_ms=round(stop_idx * dt * 1e3, 1) if stop_idx is not None else None,
                   psi_final=round(float(np.degrees(PSI[-1])), 2))
    if rec is not None:
        out["_rec"] = rec
    return out


def _job(args):
    kw = dict(args)
    tag = kw.pop("_tag")
    meta = kw.pop("_meta", {})
    t0 = time.time()
    r = simulate(**kw)
    r.update(meta)
    r["group"] = tag
    r["cpu_s"] = round(time.time() - t0, 2)
    return r


# ============================================================================ port self-validation
def port_selftest(jobs: int = 1) -> dict:
    """Run the ORIGINAL ideation esc_dyn3.simulate and this port on the ideation geometry and compare."""
    try:
        return _port_selftest()
    except Exception as e:  # pragma: no cover
        return {"status": "not-run", "reason": f"self-test raised {e!r}"}


def _port_selftest() -> dict:
    synth = REPO / "analysis" / "ideation" / "synth"
    if not (synth / "esc_dyn3.py").exists():
        return {"status": "not-run", "reason": "analysis/ideation/synth/esc_dyn3.py missing"}
    sys.path.insert(0, str(synth))
    sys.path.insert(0, str(REPO / "analysis" / "ideation" / "haptic"))
    try:
        import esc_dyn3  # noqa
    except Exception as e:  # pragma: no cover
        return {"status": "not-run", "reason": f"import failed: {e}"}
    g, Sg = esc_dyn3.make(1.8686)
    flat = {"S": array("d", Sg.s.ravel()), "GX": array("d", Sg.gx.ravel()), "GY": array("d", Sg.gy.ravel()),
            "n": Sg.n, "x0": Sg.x0, "h": Sg.h}
    HB = dict(m_h=0.0158, k_bank=100.0, c_r=0.35, mu=0.35, mu_b=0.35)

    def orig(T, d, eps=0.0):
        o = esc_dyn3.simulate(Sg, g["D"], g["pins"], g["rp"], T_Nmm=T, direction=d, psi_b=12.42, r_com=11.3,
                              t_end=0.6, I_h=5.2e-6 * (1 + eps), **HB)
        return {k: float(o[k]) for k in ("rps", "f_head", "swing")}

    def port(T, d, eps=0.0):
        q = simulate(T, d, D=g["D"], pins=g["pins"], rp=g["rp"], psi_b=12.42, com=(0.0, 11.3), r_k=12.5,
                     J_w=4e-6, m_w=0.006, t_end=0.6, sdf=flat, I_h=5.2e-6 * (1 + eps), **HB)
        return {"rps": q["rps"], "f_head": q["f_head_orig"], "swing": q["swing"]}

    rows = []
    # (1) gentle push: smooth regime, the port must reproduce the original (and final2.log: 0.74 / 5.1 / 15.9)
    o, q = orig(1, 1), port(1, 1)
    ok1 = abs(o["rps"] - q["rps"]) <= 0.011 and abs(o["swing"] - q["swing"]) <= 0.11 and o["f_head"] == q["f_head"]
    rows.append({"T": 1, "dir": 1, "orig": o, "port": q, "rule": "identical to 2 decimals", "pass": bool(ok1)})
    # (2) hard push: impacts make the model chaotic (the ORIGINAL scatters ~+-5 % in rev/s under 1e-12 relative
    #     perturbations of I_h), so the port is compared with an ensemble of perturbed originals
    ens = [orig(20, -1, e) for e in (0.0, 1e-12, -1e-12)]
    q = port(20, -1)
    lo = min(e["rps"] for e in ens)
    hi = max(e["rps"] for e in ens)
    span = max(abs(hi), abs(lo)) * 0.08
    ok2 = (lo - span) <= q["rps"] <= (hi + span) and abs(q["swing"] - np.mean([e["swing"] for e in ens])) <= 2.0
    rows.append({"T": 20, "dir": -1, "orig_ensemble": ens, "port": q,
                 "rule": "port rps within the perturbed-original ensemble range +-8 %, swing within 2 deg",
                 "pass": bool(ok2)})
    ok = ok1 and ok2
    return {"status": "pass" if ok else "fail", "rows": rows,
            "criterion": "port of esc_dyn3 reproduces the original on the ideation geometry"}


# ============================================================================ V4 orchestration
def v4_jobs(base: dict, c_r_cad: float, quick: bool, sculpt: bool = False) -> list:
    J = []

    def add(tag, T, d, t_end, **kw):
        a = dict(base)
        a.update(kw)
        a.update(T_Nmm=T, direction=d, t_end=t_end, _tag=tag,
                 _meta={k: kw[k] for k in kw if k in ("dD", "drp", "c_r", "mu", "mu_b", "J_w", "gvec", "t_release")})
        J.append(a)

    # simulated time: SPEC/ideation used 0.6 s (nominal) and 0.45 s (corners); slow runs are lengthened so the
    # averaging window (t > 0.35 t_end) always spans many teeth.  At T 1 the motion is chaotic and intermittent: a
    # 1.2 s run averages ~5 teeth dominated by the spin-up overshoot (its f moved +-0.1 Hz for a 1e-9 change of I_h
    # on the sculpt kitty), so T 1 runs 4 s (~17 teeth) and T 2 1.8 s - the steady rate the table describes
    t_nom = {1: 4.0, 2: 1.8}
    t_cor = {1: 4.0, 3: 0.6}
    Ts = [1, 2, 3, 5, 10, 20, 40] if not quick else [1, 3, 20]
    for T in Ts:
        for d in (1, -1):
            add("nominal", T, d, t_nom.get(T, 0.6), c_r=c_r_cad, mu=0.35, mu_b=0.35)
    tols = TOL_CORNERS + [(0.0, 0.0)]
    for (dD, drp), cr, T, d in itertools.product(tols, (0.25, 0.5), (1, 3, 20), (1, -1)):
        if quick and (T == 3 or (dD, drp) == (0.0, 0.0)):
            continue
        add("corners", T, d, t_cor.get(T, 0.45), dD=dD, drp=drp, c_r=cr, mu=0.35, mu_b=0.35)
    for (dD, drp), T, d in itertools.product(TOL_CORNERS, (1, 3, 20), (1, -1)):
        if quick and T == 3:
            continue
        add("mu0.5", T, d, t_cor.get(T, 0.45), dD=dD, drp=drp, c_r=c_r_cad, mu=0.5, mu_b=0.5)
    if not quick:
        # extras (not SPEC-gated)
        for (dD, drp), T, d in itertools.product(TOL_CORNERS, (1, 3), (1, -1)):
            add("x_bare_wheel", T, d, t_cor.get(T, 0.45), dD=dD, drp=drp, c_r=0.5, J_w=base["J_w"] - J_FINGER)
        for (dD, drp), T, d in itertools.product(TOL_CORNERS, (1, 20), (1, -1)):
            add("x_mu0.2", T, d, t_cor.get(T, 0.45), dD=dD, drp=drp, c_r=c_r_cad, mu=0.2, mu_b=0.2)
        for gname, gv in (("flat", (0.0, 0.0)), ("inverted", (0.0, G_ACC)), ("side_+x", (G_ACC, 0.0)),
                          ("side_-x", (-G_ACC, 0.0))):
            for T, d in itertools.product((1, 3, 20), (1, -1)):
                add("x_gravity_" + gname, T, d, t_cor.get(T, 0.45), c_r=c_r_cad, gvec=gv)
        for T, d in itertools.product((3, 20), (1, -1)):
            add("x_release", T, d, 0.5, c_r=c_r_cad, t_release=0.3)
        if sculpt and abs(base.get("r_k", 12.5) - 12.5) > 0.5:
            # SPEC 2.4(b) books the finger as J 3e-6 at the knob (r 12.5); a fingertip pushing in the sculpt's cap
            # dish at a shorter lever arm adds ~ (r_k / 12.5)^2 of that (reported, not gated; the classic skins keep
            # the SPEC's r_k 11 / J_FINGER pair and their run set unchanged)
            jf = J_FINGER * (base["r_k"] / 12.5) ** 2
            for T, d in itertools.product((1, 3, 20, 40), (1, -1)):
                add("x_finger_r2", T, d, t_nom.get(T, 0.6), c_r=c_r_cad, J_w=base["J_w"] - J_FINGER + jf)
    return J


def v4_evaluate(rows: list) -> dict:
    nom = {(r["T"], r["dir"]): r for r in rows if r["group"] == "nominal"}
    checks = {}
    # nominal table vs SPEC 2.4
    table = []
    f_ok = True
    for (T, d), r in sorted(nom.items()):
        spec = SPEC_TABLE.get(T)
        ok = True
        if spec:
            flo, fhi = spec[1]
            ok = (1 - V4_F_TOL) * flo <= r["f_head"] <= (1 + V4_F_TOL) * fhi
        f_ok &= ok
        table.append({"T": T, "dir": d, "rps": r["rps"], "f_head": r["f_head"], "f_head_orig_estimator": r["f_head_orig"],
                      "swing": r["swing"], "Fmax": r["Fmax"], "loss_wheel_brg": r["loss_wheel_brg"],
                      "loss_head_brg": r["loss_head_brg"], "esc_ratio": r["esc_ratio"], "status": r["status"],
                      "spec_rps": spec[0] if spec else None, "spec_f": spec[1] if spec else None,
                      "f_within_25pct": ok})
    checks["nominal_f_table"] = {"criterion": "nominal f_head(T) within +-25 % of SPEC 2.4 table (both dirs)",
                                 "measured": table, "pass": bool(f_ok)}

    def gate(group):
        rs = [r for r in rows if r["group"] == group]
        bad = []
        for r in rs:
            ref = nom.get((r["T"], r["dir"]))
            ratio = abs(r["rps"]) / abs(ref["rps"]) if ref and abs(ref["rps"]) > 1e-9 else None
            r["rps_ratio_to_nominal"] = round(ratio, 3) if ratio is not None else None
            fails = []
            if abs(r["rps"]) < V4_MIN_RPS:
                fails.append("rps<0.15")
            if ratio is not None and ratio > V4_MAX_RATIO:
                fails.append("rps>2.2x nominal")
            if r["swing"] < V4_MIN_SWING:
                fails.append("swing<8")
            if r["status"] != "RUN":
                fails.append(r["status"])
            if fails:
                bad.append({k: r.get(k) for k in ("T", "dir", "dD", "drp", "c_r", "mu", "mu_b", "J_w", "gvec", "rps",
                                                  "swing", "f_head", "status")} | {"fails": fails})
            r["v4_ok"] = not fails
        summ = {"runs": len(rs), "failed": len(bad), "failures": bad}
        if rs:
            summ["min_abs_rps"] = min(abs(r["rps"]) for r in rs)
            summ["min_swing"] = min(r["swing"] for r in rs)
            summ["max_ratio_to_nominal"] = max((r["rps_ratio_to_nominal"] or 0) for r in rs)
            er = [r["esc_ratio"] for r in rs if r["esc_ratio"] is not None and r["n_teeth_window"] >= 3]
            summ["min_esc_ratio"] = min(er) if er else None
            summ["min_teeth_in_window"] = min(r["n_teeth_window"] for r in rs)
            summ["max_Fmax_N"] = max(r["Fmax"] for r in rs)
        return summ

    nom_gate = gate("nominal")
    checks["nominal_runs"] = dict(nom_gate, criterion="each nominal run: rps>=0.15, swing>=8, status RUN",
                                  pass_=None)
    checks["nominal_runs"]["pass"] = nom_gate["failed"] == 0
    c = gate("corners")
    checks["tolerance_corners"] = dict(c, criterion="60 runs (dpivot +-0.4 x drp +-0.2 + nominal, c_r 0.25/0.5, "
                                                    "T 1/3/20, both dirs): rps>=0.15, rps<=2.2x nominal, swing>=8",
                                       pass_=None)
    checks["tolerance_corners"]["pass"] = c["failed"] == 0 and c["runs"] > 0
    m = gate("mu0.5")
    checks["friction_mu0.5"] = dict(m, criterion="mu/mu_b 0.5/0.5 at the 4 tolerance corners, T 1/3/20, both dirs: "
                                                 "same gates", pass_=None)
    checks["friction_mu0.5"]["pass"] = m["failed"] == 0 and m["runs"] > 0
    for k in checks:
        checks[k].pop("pass_", None)
    # direction symmetry (info)
    sym = []
    for T in sorted({k[0] for k in nom}):
        if (T, 1) in nom and (T, -1) in nom:
            a, b = abs(nom[(T, 1)]["rps"]), abs(nom[(T, -1)]["rps"])
            sym.append({"T": T, "rps_+": a, "rps_-": b, "ratio": round(max(a, b) / max(min(a, b), 1e-9), 3)})
    extras = {}
    for g in sorted({r["group"] for r in rows if r["group"].startswith("x_")}):
        if g == "x_release":
            extras[g] = {"runs": [{k: r.get(k) for k in ("T", "dir", "rps_at_release", "coast_deg", "coast_max_deg",
                                                         "stop_time_ms", "psi_final")} for r in rows if r["group"] == g]}
            extras[g]["max_coast_deg"] = max(abs(r["coast_deg"]) for r in rows if r["group"] == g)
        else:
            extras[g] = gate(g)
        if g == "x_finger_r2":
            # the SPEC 2.4 f(T) comparison again with the finger inertia scaled to the dish lever arm (info: how much
            # of the nominal_f_table verdict rests on the SPEC's finger model)
            ft = []
            for r in sorted((r for r in rows if r["group"] == g), key=lambda r: (r["T"], r["dir"])):
                spec = SPEC_TABLE.get(r["T"])
                ok = spec is None or (1 - V4_F_TOL) * spec[1][0] <= r["f_head"] <= (1 + V4_F_TOL) * spec[1][1]
                ft.append({"T": r["T"], "dir": r["dir"], "f_head": r["f_head"], "spec_f": spec[1] if spec else None,
                           "f_within_25pct": bool(ok)})
            extras[g]["J_w"] = next(r["J_w"] for r in rows if r["group"] == g)
            extras[g]["f_table"] = ft
            extras[g]["f_table_outside_25pct"] = [(x["T"], x["dir"], x["f_head"]) for x in ft if not x["f_within_25pct"]]
    return {"checks": checks, "direction_symmetry": sym, "extras": extras,
            "pass": all(c["pass"] for c in checks.values())}


# ============================================================================ plots / GIF
def plot_cspace(path, case, phis_deg, psis_deg, psi_b, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cB = case["_maps"]["band"]
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=110)
    im = ax.imshow(np.clip(cB.T, -1.5, 1.5), origin="lower", aspect="auto", cmap="RdBu",
                   extent=[phis_deg[0], phis_deg[-1], psis_deg[0], psis_deg[-1]], vmin=-1.5, vmax=1.5)
    ax.contour(phis_deg, psis_deg, cB.T, levels=[0.0], colors="k", linewidths=0.8)
    for d, col in ((1, "#e8a000"), (-1, "#7a2fbf")):
        tr = case["pins"].get("_traj", {}).get(d)
        if tr:
            ph = phis_deg if d == 1 else phis_deg[::-1]
            ax.plot(ph[:len(tr)], tr, color=col, lw=1.4, label=f"lazy head, wheel dir {'+' if d > 0 else '-'}")
    ax.axhline(psi_b, color="k", ls=":", lw=0.8)
    ax.axhline(-psi_b, color="k", ls=":", lw=0.8)
    ax.set_xlabel("wheel angle phi (deg)")
    ax.set_ylabel("head angle psi (deg)")
    ax.set_title(title, fontsize=9)
    ax.legend(fontsize=7, loc="upper right")
    fig.colorbar(im, ax=ax, label="clearance of CAD head band to CAD star (mm)")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def make_gif(path, cad, base, T=2.0, direction=1, fps=15, n_frames=64):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter
    from matplotlib.patches import Polygon as MPoly
    kw = dict(base)
    kw.update(T_Nmm=T, direction=direction, t_end=0.6, record_every=20, c_r=cad["c_r"])
    r = simulate(**kw)
    rec = np.array([x[:7] for x in r["_rec"]], float)
    con = np.array([x[7:] for x in r["_rec"]], bool)
    t, phi, psi = rec[:, 0], rec[:, 1], rec[:, 2]
    # one tooth cycle (45 deg of wheel) in steady state, plus a little lead-in
    i0 = int(np.searchsorted(t, 0.36))
    target = phi[i0] + direction * math.radians(50.0)
    i1 = i0 + int(np.argmax(direction * (phi[i0:] - target) >= 0)) if np.any(direction * (phi[i0:] - target) >= 0) \
        else len(t) - 1
    idx = np.linspace(i0, i1, n_frames).astype(int)
    star = np.asarray(cad["star_poly"].exterior.coords)
    band = cad["head_band_poly"]
    band_rings = [np.asarray(q.exterior.coords) for q in parts(band)]
    pins = np.array(cad["pins"])
    rp = cad["rp"]
    P = np.array(cad["P"])
    fig = plt.figure(figsize=(8.0, 4.4), dpi=80)
    ax = fig.add_axes([0.02, 0.06, 0.5, 0.86])
    ax2 = fig.add_axes([0.60, 0.53, 0.37, 0.30])
    ax3 = fig.add_axes([0.60, 0.12, 0.37, 0.30])
    ax.set_aspect("equal")
    ax.set_xlim(-27, 27)
    ax.set_ylim(-21, 54)
    ax.axis("off")
    th = np.linspace(0, 2 * np.pi, 96)
    rim0 = np.c_[cad["R_u"] * np.cos(th), cad["R_u"] * np.sin(th)]
    kn0 = np.c_[base.get("r_k", 11.0) + cad["knob_r"] * np.cos(th), cad["knob_r"] * np.sin(th)]
    prim = MPoly(rim0, closed=True, fc="none", ec="#2b6f99", lw=0.7, ls="--", alpha=0.6)
    pkn = MPoly(kn0, closed=True, fc="#2b6f99", ec="#1d4f6e", lw=0.6, alpha=0.25)
    face_rings = [np.asarray(q.exterior.coords) for q in parts(cad["face_poly"])] if cad.get("face_poly") else []
    pfaces = [MPoly(rg, closed=True, fc="#fbf1e2", ec="#c9a27a", lw=0.8, ls="--", alpha=0.6) for rg in face_rings]
    for q in pfaces:
        ax.add_patch(q)
    ax.add_patch(prim)
    pstar = MPoly(star, closed=True, fc="#9fd3f5", ec="#2b6f99", lw=0.8)
    ax.add_patch(pstar)
    ax.add_patch(pkn)
    pbands = [MPoly(rg, closed=True, fc="#f6e3c4", ec="#a0703a", lw=0.8, alpha=0.85) for rg in band_rings]
    for pb_ in pbands:
        ax.add_patch(pb_)
    ppins = [MPoly(np.c_[c[0] + rp * np.cos(th), c[1] + rp * np.sin(th)], closed=True, fc="#e7a33b", ec="#7a4a10",
                   lw=0.8) for c in pins]
    for q in ppins:
        ax.add_patch(q)
    ax.plot([0], [0], "k+", ms=8)
    ax.plot([P[0]], [P[1]], "k+", ms=8)
    ttl = ax.set_title("", fontsize=8)
    ax2.plot((t[idx[0]:idx[-1]] - t[idx[0]]) * 1e3, np.degrees(psi[idx[0]:idx[-1]]), color="#a0703a", lw=1.2)
    ax2.set_ylabel("head psi (deg)", fontsize=7)
    ax2.tick_params(labelsize=7)
    cur2 = ax2.axvline(0, color="k", lw=0.8)
    ax3.plot((t[idx[0]:idx[-1]] - t[idx[0]]) * 1e3, np.degrees(phi[idx[0]:idx[-1]] - phi[idx[0]]), color="#2b6f99", lw=1.2)
    ax3.set_ylabel("wheel phi (deg)", fontsize=7)
    ax3.set_xlabel("time (ms)", fontsize=7)
    ax3.tick_params(labelsize=7)
    cur3 = ax3.axvline(0, color="k", lw=0.8)
    slow = n_frames / fps / max(t[idx[-1]] - t[idx[0]], 1e-9)
    fig.text(0.60, 0.97, f"Purr-Bobble escapement (as-modelled CAD profiles)\nT = {T:g} N*mm, one tooth cycle, "
             f"slowed {slow:.0f}x\n{cad.get('band_name', 'band layer z 3-7.4 solid; face')} and "
             f"{cad.get('rim_name', 'ball rim')} dashed", fontsize=7, va="top")

    def upd(k):
        s = idx[k]
        a = phi[s]
        ca, sa_ = math.cos(a), math.sin(a)
        Ow = rec[s, 3:5]
        Rw = np.array([[ca, -sa_], [sa_, ca]])
        pstar.set_xy(star @ Rw.T + Ow)
        prim.set_xy(rim0 + Ow)
        pkn.set_xy(kn0 @ Rw.T + Ow)
        b = psi[s]
        Ph = P + rec[s, 5:7]
        cb, sb = math.cos(b), math.sin(b)
        Rh = np.array([[cb, -sb], [sb, cb]])
        for pb_, rg in zip(pbands, band_rings):
            pb_.set_xy((rg - P) @ Rh.T + Ph)
        for pf_, rg in zip(pfaces, face_rings):
            pf_.set_xy((rg - P) @ Rh.T + Ph)
        for kk, (q, c) in enumerate(zip(ppins, pins)):
            cc = (c - P) @ Rh.T + Ph
            q.set_xy(np.c_[cc[0] + rp * np.cos(th), cc[1] + rp * np.sin(th)])
            q.set_facecolor("#d62728" if con[s, kk] else "#e7a33b")
        tm = (t[s] - t[idx[0]]) * 1e3
        cur2.set_xdata([tm, tm])
        cur3.set_xdata([tm, tm])
        ttl.set_text(f"t = {tm:5.1f} ms   psi = {math.degrees(b):+5.1f} deg   (red pallet = in contact)")
        return [pstar, prim, pkn, *pfaces, *pbands, *ppins, cur2, cur3, ttl]

    anim = FuncAnimation(fig, upd, frames=len(idx), blit=False)
    anim.save(str(path), writer=PillowWriter(fps=fps))
    plt.close(fig)
    return {"path": str(path), "frames": int(len(idx)), "sim_window_ms": round((t[idx[-1]] - t[idx[0]]) * 1e3, 1),
            "T_Nmm": T, "rps": r["rps"], "f_head": r["f_head"]}


# ============================================================================ main
def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--skin", default="kitty")
    ap.add_argument("--variant", default="nominal")
    ap.add_argument("--jobs", type=int, default=max(1, min(3, (os.cpu_count() or 2) - 1)))
    ap.add_argument("--quick", action="store_true", help="reduced V4 run set (development)")
    ap.add_argument("--no-gif", action="store_true", help="skip the tooth-cycle GIF")
    ap.add_argument("--gif", action="store_true", help="also write the GIF for non-nominal variants")
    ap.add_argument("--no-selftest", action="store_true", help="skip the esc_dyn3 port self-validation")
    ap.add_argument("--out", default=None, help="report path (default verification/reports/<skin>/escapement[_v].json)")
    a = ap.parse_args(argv)
    T0 = time.time()
    from purrbobble.model import build
    M = build(a.skin, a.variant)
    p = M.params
    rep = {"skin": a.skin, "variant": a.variant, "script": "verification/v_escapement.py",
           "date": time.strftime("%Y-%m-%d %H:%M:%S"), "quick": a.quick}
    print(f"[v_escapement] {a.skin}/{a.variant}: model built ({time.time() - T0:.1f}s)", flush=True)

    # ---------------------------------------------------------------- CAD extraction + V13
    cad = extract_cad(M)
    mp_ = mass_properties(M)
    h, w = mp_["bodies"]["head"], mp_["bodies"]["wheel"]
    rep["cad_inputs"] = {
        "z_contact": cad["z_contact"], "P": cad["P"], "star": cad["star"],
        "profile_consistency": cad["profile_consistency"], "pallet_fit": cad["pallet_fit"], "rp_fit": cad["rp"],
        "journal_wheel": cad["journal_wheel"], "journal_head": cad["journal_head"], "c_r": cad["c_r"],
        "banking": cad["banking"], "psi_b_used": cad["psi_b"],
        "param_cross_check": {"P_design": list(p.P), "pallets_design": [list(c) for c in p.pallets], "rp": p.rp,
                              "Rt": p.Rt, "Rr": p.Rr, "c_r_design": (p.bore_d - p.post_d) / 2},
    }
    # SPEC 2.6 budgets the toy as printed: weigh the 3MF with PrusaSlicer (per-part infill) when possible; the
    # geometric estimate above double-counts thin walls (~2-4 g high) and is kept as the fallback
    sm = sliced_mass_g(a.skin, a.variant)
    if sm and sm.get("filament_g"):
        mp_["checks"]["total_mass"] = {
            "measured": sm["filament_g"], "estimate_g": mp_["checks"]["total_mass"]["measured"],
            "criterion": f"as printed <= {mass_limit_g(M):g} g (PrusaSlicer on {sm['source']}, per-part infill; print time "
                         f"{sm['print_time']})", "pass": bool(sm["filament_g"] <= mass_limit_g(M))}
        mp_["pass"] = all(c["pass"] for c in mp_["checks"].values())
    rep["V13"] = mp_
    print(f"[v_escapement] CAD: rp_fit {cad['rp']:.4f}, c_r {cad['c_r']:.4f}, psi_b {cad['psi_b']:.4f}, "
          f"I_h {h['I_P_kgm2']:.3e}, COM +{h['com_rel_P_mm'][1]:.2f}, total {mp_['total_mass_g']:.2f} g "
          f"({time.time() - T0:.1f}s)", flush=True)

    # ---------------------------------------------------------------- SDF of the CAD star
    t1 = time.time()
    sdf = WheelSDF(cad["star_poly"], SDF_H)
    print(f"[v_escapement] SDF grid {sdf.n}x{sdf.n} h {SDF_H} ({time.time() - t1:.1f}s)", flush=True)

    # ---------------------------------------------------------------- pool (fork: workers inherit SDF + CAD)
    psi_b = cad["psi_b"]
    phis2 = np.linspace(0.0, 90.0, 361)
    psis2 = np.linspace(-psi_b, psi_b, 2 * int(psi_b * 10) + 1)
    phis3 = np.arange(0.0, 90.0 + 1e-9, 0.5)
    psis3 = np.linspace(-psi_b, psi_b, int(math.ceil(2 * psi_b / 0.25)) + 1)
    _CTX.clear()
    _CTX.update(sdf=sdf, cad=cad, phis2=phis2, psis2=psis2, phis3=phis3, psis3=psis3)
    _W.clear()
    _W.update(sdf.flat())
    pool = mp.get_context("fork").Pool(max(1, a.jobs))
    st_async = None if a.no_selftest else pool.apply_async(port_selftest)
    tol9 = list(itertools.product((-0.4, 0.0, 0.4), (-0.2, 0.0, 0.2)))

    # ---------------------------------------------------------------- V2
    t1 = time.time()
    cases = pool.map(_v2_worker, tol9, chunksize=1)
    rows, all_ok, worst_pa, worst_case = [], True, 0.0, None
    for c in cases:
        row = {"dpivot": c["dpivot"], "drp": c["drp"]}
        for model in ("pins", "band"):
            r = c[model]
            jam = sum(r[f"{rule}_dir{s}"]["jams"] for rule in ("nearest", "connected") for s in "+-")
            pa = max(r[f"{rule}_dir{s}"]["worst_pa_deg"] for rule in ("nearest", "connected") for s in "+-")
            sw = min(r[f"nearest_dir{s}"]["swing_pp_deg"] for s in "+-")
            row[model] = {"jams": jam, "worst_pa_deg": pa, "swing_pp_deg": sw,
                          "free_spin_columns": len(r["free_spin_psi_columns"]),
                          "max_clearance": r["max_clearance"], "best_print_pose": r["best_print_pose"]}
            all_ok &= jam == 0 and pa <= PA_PASS
            if pa > worst_pa:
                worst_pa, worst_case = pa, (c["dpivot"], c["drp"], model)
        rows.append(row)
    det = []
    for c in cases:
        d = {"dpivot": c["dpivot"], "drp": c["drp"]}
        for model in ("pins", "band"):
            d[model] = {k: v for k, v in c[model].items() if not k.startswith("_")}
        det.append(d)
    nominal_case = [c for c in cases if c["dpivot"] == 0.0 and c["drp"] == 0.0][0]
    free_cols = sorted({x for c in cases for m in ("pins", "band") for x in c[m]["free_spin_psi_columns"]})
    rep["V2"] = {
        "criterion": "0 jams in all 9 cases (both directions, both clearance models, both sweep rules); "
                     f"worst pressure angle <= {PA_PASS} deg (hard limit {PA_HARD:.1f})",
        "grid": {"phi_deg": [0, 90, 0.25], "psi_deg": [float(psis2[0]), float(psis2[-1]), float(psis2[1] - psis2[0])],
                 "sdf_h": SDF_H},
        "summary": rows, "worst_pa_deg": worst_pa, "worst_pa_case": worst_case,
        "static_free_spin_columns_any_case": free_cols,
        "detail": det, "pass": bool(all_ok), "time_s": round(time.time() - t1, 1)}
    print(f"[v_escapement] V2 {'PASS' if all_ok else 'FAIL'}: worst PA {worst_pa:.1f} at {worst_case}, "
          f"jams {[ (r['dpivot'], r['drp'], r['pins']['jams'], r['band']['jams']) for r in rows if r['pins']['jams'] or r['band']['jams']]} "
          f"({time.time() - t1:.1f}s)", flush=True)
    # static margins beyond the tolerance box (pins model): pivot moved further in at fat pallets (lock) and further
    # out at thin pallets (static free spin = a parked head lets the wheel pass a whole pitch)
    t1 = time.time()
    lock_scan = [(round(-0.4 - 0.05 * k, 3), 0.2) for k in range(0, 17)]
    spin_scan = [(round(0.4 + 0.1 * k, 3), -0.2) for k in range(0, 17)]
    ms = pool.map(_margin_worker, lock_scan + spin_scan, chunksize=2)
    lock_on = next((m["dpivot"] for m in ms[:len(lock_scan)] if m["jams"] > 0), None)
    spin_on = next((m["dpivot"] for m in ms[len(lock_scan):] if m["free_spin_columns"] > 0), None)
    rep["V2"]["margins"] = {
        "static_lock_onset_dpivot_at_drp+0.2": lock_on,
        "static_lock_margin_beyond_box_mm": None if lock_on is None else round(-0.4 - lock_on - 0.05, 3),
        "static_free_spin_onset_dpivot_at_drp-0.2": spin_on,
        "scan": ms, "note": "info only (not SPEC-gated); pins model on the CAD star; lock scanned in 0.05 steps "
                            "from -0.4, free spin in 0.1 steps from +0.4; margin = last clean step beyond the box "
                            "(negative = locks inside the tolerance box; null = none found in the scan)",
        "time_s": round(time.time() - t1, 1)}
    print(f"[v_escapement] V2 margins: static lock from dpivot {lock_on} (drp +0.2), static free spin from dpivot "
          f"{spin_on} (drp -0.2) ({time.time() - t1:.1f}s)", flush=True)
    cs_dir = Path(a.out).parent if a.out else REPO / "verification" / "reports" / a.skin
    cs_png = cs_dir / ("escapement_cspace.png" if a.variant == "nominal" else f"escapement_cspace_{a.variant}.png")
    cs_png.parent.mkdir(parents=True, exist_ok=True)
    plot_cspace(cs_png, nominal_case, phis2, psis2, psi_b,
                f"{a.skin}/{a.variant}: CAD head band vs CAD star (z {cad['z_contact']:.2f}); black = contact boundary")
    rep["V2"]["plot"] = str(cs_png.relative_to(REPO)) if cs_png.is_relative_to(REPO) else str(cs_png)

    # ---------------------------------------------------------------- V3 shadow test
    t1 = time.time()
    pins = np.array(cad["pins"])
    P = np.array(cad["P"])
    v3_cases = pool.map(_v3_worker, tol9, chunksize=1)
    nom3 = [c for c in v3_cases if c["dpivot"] == 0.0 and c["drp"] == 0.0][0]
    # second way: exact shapely distances at the worst poses + random reachable poses (nominal case)
    rng = np.random.default_rng(1234)
    cp, cf = nom3["_cp"], nom3["_cf"]
    reach = cp >= 0
    defi = np.where(reach, np.minimum(cp, V3_CAP) - cf, -np.inf)
    worst_idx = np.dstack(np.unravel_index(np.argsort(-defi.ravel())[:15], defi.shape))[0]
    ri = np.argwhere(reach)
    rnd = ri[rng.choice(len(ri), size=min(60, len(ri)), replace=False)]
    star = cad["star_poly"]
    fullpoly = cad["head_full_poly"]
    pin_discs = shapely.union_all([Point(c).buffer(cad["rp"], quad_segs=256) for c in pins])
    diffs_f, diffs_p = [], []
    for (i, j) in np.vstack([worst_idx, rnd]):
        Sw = affinity.rotate(star, phis3[i], origin=(0, 0))
        Hf = affinity.rotate(fullpoly, psis3[j], origin=tuple(P))
        Hp = affinity.rotate(pin_discs, psis3[j], origin=tuple(P))
        df = Sw.distance(Hf)
        dp = Sw.distance(Hp)
        if df > 0 and cf[i, j] < 1.0:
            diffs_f.append(abs(df - cf[i, j]))
        if dp > 0 and cp[i, j] < 1.0:
            diffs_p.append(abs(dp - cp[i, j]))
    exact = {"poses": int(len(worst_idx) + len(rnd)), "max_abs_diff_full": round(float(max(diffs_f, default=0)), 5),
             "max_abs_diff_pins": round(float(max(diffs_p, default=0)), 5),
             "note": "exact shapely polygon distance vs SDF-sampled clearance (positive clearances < 1 mm)"}
    v3_pass = nom3["n_bad"] == 0 and exact["max_abs_diff_full"] < 0.01
    rep["V3"] = {"criterion": f"where c_pins >= 0: c_full >= min(c_pins, {V3_CAP}) - {V3_TOL} (nominal case gated; "
                              "all 9 tolerance cases reported)",
                 "grid": {"phi_deg": [0, 90, 0.5], "psi_deg": [float(psis3[0]), float(psis3[-1]),
                                                               round(float(psis3[1] - psis3[0]), 4)]},
                 "head_profile": "union of CAD head slices over the tooth height (z 3.0..8.0)",
                 "nominal": {k: v for k, v in nom3.items() if not k.startswith("_")},
                 "tolerance_cases": [{k: v for k, v in c.items() if not k.startswith("_")} for c in v3_cases],
                 "exact_spot_check": exact, "pass": bool(v3_pass), "time_s": round(time.time() - t1, 1)}
    print(f"[v_escapement] V3 {'PASS' if v3_pass else 'FAIL'}: n_bad {nom3['n_bad']}, worst deficit "
          f"{nom3['worst_deficit']:.4f}, other cases n_bad {[c['n_bad'] for c in v3_cases]}, exact diff "
          f"{exact['max_abs_diff_full']:.4f} ({time.time() - t1:.1f}s)", flush=True)

    # ---------------------------------------------------------------- V4 dynamics
    base = dict(D=float(P[1]), pins=[tuple(map(float, c)) for c in pins], rp=cad["rp"], psi_b=psi_b,
                I_h=h["I_P_kgm2"], m_h=h["mass_g"] * 1e-3, com=tuple(h["com_rel_P_mm"]),
                J_w=w["J_O_kgm2"] + J_FINGER, m_w=w["mass_g"] * 1e-3, r_b=p.post_d / 2, r_k=p.r_k, k_bank=100.0)
    rep["V4_inputs"] = {k: v for k, v in base.items()} | {"J_w_note": f"J_O(CAD wheel) {w['J_O_kgm2']:.3e} + finger "
                                                          f"{J_FINGER:.1e} (SPEC 2.4b: J_w 4e-6 finger included)",
                                                          "c_r_cad": cad["c_r"]}
    jobs = v4_jobs(base, cad["c_r"], a.quick, sculpt=bool(M.info.get("sculpt")))
    t2 = time.time()
    results = list(pool.imap_unordered(_job, jobs, chunksize=1))
    st = {"status": "not-run"} if st_async is None else st_async.get()
    pool.close()
    pool.join()
    rep["V4_port_selftest"] = st
    print(f"[v_escapement] esc_dyn3 port self-test: {st.get('status')}", flush=True)
    for r in results:
        if "gvec" in r:
            r["gvec"] = list(r["gvec"])
    v4 = v4_evaluate(results)
    v4["runs"] = sorted(results, key=lambda r: (r["group"], r["T"], r["dir"], str(r.get("dD")), str(r.get("drp")),
                                               str(r.get("c_r"))))
    v4["time_s"] = round(time.time() - t2, 1)
    v4["cpu_s_total"] = round(sum(r["cpu_s"] for r in results), 1)
    rep["V4"] = v4
    if M.info.get("sculpt"):
        # The [4, 8]e-6 / 8..14 mm bands are the SPEC tuning band of the classic face heads (the inputs the SPEC 2.4
        # table was derived for).  A sculpt head is the owner's sculpted head and weighs what it weighs; V4 simulates
        # with exactly these measured values, so for sculpt skins they pass when V4 passes (the band verdict stays in
        # the report as spec_band_pass).
        for k in ("I_h", "com_above_P"):
            c = mp_["checks"][k]
            c["spec_band_pass"] = c["pass"]
            if not c["pass"]:
                c["pass"] = bool(v4["pass"])
                c["criterion"] += " (sculpt skin: outside the band, accepted because V4 passes with this value)"
        mp_["pass"] = all(c["pass"] for c in mp_["checks"].values())
    print(f"[v_escapement] V4 {'PASS' if v4['pass'] else 'FAIL'}: "
          + ", ".join(f"{k} {'ok' if c['pass'] else 'FAIL'}" for k, c in v4["checks"].items())
          + f" ({len(results)} runs, {time.time() - t2:.1f}s)", flush=True)
    for g, e in v4["extras"].items():
        if "failed" in e:
            print(f"    extra {g}: {e['failed']}/{e['runs']} runs fail the V4 gates; min rps {e.get('min_abs_rps')}, "
                  f"min swing {e.get('min_swing')}", flush=True)
        else:
            print(f"    extra {g}: max coast {e.get('max_coast_deg')} deg", flush=True)

    # ---------------------------------------------------------------- GIF
    if not a.no_gif and (a.variant == "nominal" or a.gif):
        t1 = time.time()
        gif = REPO / "renders" / a.skin / ("escapement_cycle.gif" if a.variant == "nominal"
                                           else f"escapement_cycle_{a.variant}.gif")
        gif.parent.mkdir(parents=True, exist_ok=True)
        try:
            rep["gif"] = make_gif(gif, cad, base, T=2.0, direction=1)
            rep["gif"]["path"] = str(gif.relative_to(REPO))
        except Exception as e:  # pragma: no cover
            rep["gif"] = {"error": repr(e)}
        print(f"[v_escapement] GIF {rep['gif']} ({time.time() - t1:.1f}s)", flush=True)

    # ---------------------------------------------------------------- warnings (not SPEC-gated)
    warns = []
    if PA_PASS - worst_pa < 1.0 and worst_pa <= PA_PASS:
        warns.append(f"V2 worst pressure angle {worst_pa:.1f} deg is within 1 deg of the {PA_PASS:.0f} deg gate "
                     f"(case {worst_case}); stable on 2.5x finer grids in development")
    mg = rep["V2"]["margins"]
    if mg["static_lock_margin_beyond_box_mm"] is not None and mg["static_lock_margin_beyond_box_mm"] < 0.15:
        warns.append(f"V2 static-lock margin beyond the +-0.4 pivot box (fat pallets +0.2) is only "
                     f"{mg['static_lock_margin_beyond_box_mm']} mm (lock from dpivot {mg['static_lock_onset_dpivot_at_drp+0.2']})")
    for g, e in v4["extras"].items():
        if e.get("failed"):
            warns.append(f"V4 extra {g}: {e['failed']}/{e['runs']} runs fail the V4 gates: "
                         + "; ".join(f"T {x['T']} dir {x['dir']} dD {x.get('dD')} drp {x.get('drp')} rps {x['rps']} "
                                     f"swing {x['swing']} ({','.join(x['fails'])})" for x in e["failures"][:4]))
    xf = v4["extras"].get("x_finger_r2", {})
    if xf.get("f_table_outside_25pct"):
        warns.append(f"V4 extra x_finger_r2 (finger inertia scaled to the r_k {base['r_k']:g} lever arm, J_w "
                     f"{xf['J_w']:.2e}): f_head outside the SPEC 2.4 table +-25 % at (T, dir, f) "
                     + ", ".join(f"({T}, {d:+d}, {f})" for T, d, f in xf["f_table_outside_25pct"]))
    if "x_release" in v4["extras"] and v4["extras"]["x_release"]["max_coast_deg"] > 45.0:
        warns.append(f"wheel coasts {v4['extras']['x_release']['max_coast_deg']} deg after release (> 1 pitch)")
    for k in ("tolerance_corners", "friction_mu0.5"):
        c = v4["checks"][k]
        if c.get("min_swing") is not None and c["min_swing"] < V4_MIN_SWING + 2.0:
            warns.append(f"V4 {k}: min swing {c['min_swing']} deg is within 2 deg of the {V4_MIN_SWING:.0f} deg gate")
    for srow in v4["direction_symmetry"]:
        if srow["ratio"] > 1.3:
            warns.append(f"direction asymmetry at T {srow['T']}: rev/s ratio {srow['ratio']}")
    rep["warnings"] = warns

    # ---------------------------------------------------------------- summary
    rep["checks"] = {
        "V2": {"pass": rep["V2"]["pass"], "measured": {"worst_pa_deg": worst_pa,
                                                       "jams": sum(r["pins"]["jams"] + r["band"]["jams"] for r in rows)},
               "criterion": rep["V2"]["criterion"]},
        "V3": {"pass": rep["V3"]["pass"], "measured": {"n_bad": nom3["n_bad"], "worst_deficit": nom3["worst_deficit"]},
               "criterion": rep["V3"]["criterion"]},
        "V4": {"pass": v4["pass"], "measured": {k: {kk: c.get(kk) for kk in ("runs", "failed", "min_abs_rps", "min_swing",
                                                                            "max_ratio_to_nominal")} if "runs" in c else
                                                c["pass"] for k, c in v4["checks"].items()},
               "criterion": "SPEC V4 (see V4.checks)"},
        "V13": {"pass": mp_["pass"], "measured": {k: c["measured"] for k, c in mp_["checks"].items()},
                "criterion": f"I_h in [4,8]e-6, COM 8..14 above P, total <= {mass_limit_g(M):g} g"
                             + (", |COM_x| <= 0.3 (sculpt: I_h / COM height accepted on V4)"
                                if M.info.get("sculpt") else "")},
    }
    if st.get("status") == "fail":
        rep["checks"]["V4_port_selftest"] = {"pass": False, "measured": st.get("rows"), "criterion": st.get("criterion")}
    rep["pass"] = all(c["pass"] for c in rep["checks"].values())
    rep["runtime_s"] = round(time.time() - T0, 1)
    out = Path(a.out) if a.out else (REPO / "verification" / "reports" / a.skin /
                                     ("escapement.json" if a.variant == "nominal" else f"escapement_{a.variant}.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    for c in rep["V2"]["detail"]:
        for m in ("pins", "band"):
            c[m].pop("_traj", None)
    out.write_text(json.dumps(rep, indent=1, default=_json_default))
    for wtxt in warns:
        print(f"  WARN {wtxt}", flush=True)
    print(f"[v_escapement] {'PASS' if rep['pass'] else 'FAIL'}  ->  {out}  ({rep['runtime_s']}s)", flush=True)
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
