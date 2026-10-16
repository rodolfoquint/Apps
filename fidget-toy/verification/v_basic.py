"""Basic verification: V1 (escapement parameters), V7 (print pose), per-body bbox / mass / volume, head inertia.

    python3 verification/v_basic.py --skin kitty [--variant nominal] [--slice]

Writes verification/reports/<skin>/basic.json (or basic_<variant>.json for non-nominal variants) and exits
non-zero if any check fails.

V1  D = 24.710 +- 0.001, pallets (+-12.983, 8.675) +- 0.001 (nominal; other variants report the recomputed values),
    plus a cross-check that the CAD sections carry exactly these values (pallet disc centres, post spacing).
    Sculpt skins (purrbobble/sculpt.py rebuilds all three bodies from the sculpt): the bodies themselves are probed
    as well - posts at O and P in the frame, both bores clear, the head bore walled and roofed as the classic hub
    collar did (r 6.85, up to z 8.35), the pallet pins in the head.
V7  print pose (phi 12.0, psi 5.96): three disjoint, valid, watertight, single-component shells (also after an
    STL round trip through trimesh); global minimum gap >= 0.35; pallet <-> tooth gap >= 1.3.
Also: bbox / volume / solid PLA mass per body, overall size, head I_h about P and COM height above P
(SPEC 4.3: I_h in [4.0, 8.0]e-6 kg m^2, COM 8-14 mm above P), optional PrusaSlicer slice of the 3MF.  The exit
status gates V1 and V7; the head inertia is gated by run_all (classic skins) and by V13 in v_escapement.py.  A sculpt
head outside that band is reported as a warning here: V13 accepts it only if V4 passes with the measured values.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import trimesh  # noqa: E402
from manifold3d import Manifold  # noqa: E402

from purrbobble import escapement as esc  # noqa: E402
from purrbobble import geom2d as g2  # noqa: E402
from purrbobble.assemble import mesh_arrays, write_3mf, write_stl  # noqa: E402
from purrbobble.model import build  # noqa: E402

SPEC_D = 24.710
SPEC_PALLET = (12.983, 8.675)
TOL_V1 = 1e-3
GAP_MIN = 0.35
GAP_TOL = 2e-3          # float / faceting tolerance on the 0.35 journal and ridge gaps
PALLET_MIN = 1.3
PROBE_MIN = 0.999       # sculpt body probes: share of the probe inside the body (faceting allowance)


def v1(M) -> dict:
    p = M.params
    s = esc.summary(p)
    out = {"recomputed": s, "checks": {}}
    nominal = p.variant in ("nominal", "loose")
    if nominal:
        out["checks"]["D"] = {"value": p.D, "spec": SPEC_D, "pass": abs(p.D - SPEC_D) <= TOL_V1}
        for i, (x, y) in enumerate(p.pallets):
            sx = SPEC_PALLET[0] * (1 if x > 0 else -1)
            ok = abs(x - sx) <= TOL_V1 and abs(y - SPEC_PALLET[1]) <= TOL_V1
            out["checks"][f"pallet_{'LR'[i]}"] = {"value": [x, y], "spec": [sx, SPEC_PALLET[1]], "pass": ok}
    else:
        out["checks"]["D"] = {"value": p.D, "note": f"variant drho {p.drho}: D follows rho*tilt/cos(gamma)",
                              "pass": abs(p.D - p.rho * p.tilt / math.cos(math.radians(p.gamma))) < 1e-9}
    # CAD carries the same numbers: pallet disc centroids and radius
    for i, q in enumerate(sorted(g2.pieces(M.sections["pallets2d"]), key=lambda c: c.bounds()[0])):
        b = q.bounds()
        c = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        want = p.pallets[i]
        err = math.hypot(c[0] - want[0], c[1] - want[1])
        out["checks"][f"cad_pallet_{'LR'[i]}"] = {"centre": c, "err": err, "pass": err <= TOL_V1}
    out["checks"]["cad_P"] = {"value": M.P, "pass": abs(M.P[1] - p.D) < 1e-12}
    if M.info.get("sculpt"):
        out["checks"].update(v1_sculpt_bodies(M))
    out["pass"] = all(c["pass"] for c in out["checks"].values())
    return out


def _probe(c, r0, r1, z0, z1, n=96) -> Manifold:
    """Vertical cylinder (r0 = 0) or annulus r0..r1 about c, z0..z1."""
    m = Manifold.cylinder(z1 - z0, r1, r1, n).translate((c[0], c[1], z0))
    if r0 > 0:
        m = m - Manifold.cylinder(z1 - z0 + 0.2, r0, r0, n).translate((c[0], c[1], z0 - 0.1))
    return m


def v1_sculpt_bodies(M) -> dict:
    """Sculpt skins: the frame and head are rebuilt from the sculpt (posts added again by hand, no hub collar), so
    the section cross-checks above say nothing about the bodies.  Probe them: the posts at O and P are in the frame,
    the wheel / head bores around them are clear, the head walls and roofs its blind bore as the classic hub collar
    did (disc(P, 6.90) up to z_roof0 8.4: wall >= 2.5 from the bore, roof 0.4 over bore_roof_z), and the pallet pins
    are in the head (band slab up to z_pallet_top).  Floating bodies are probed at their lifted z."""
    p = M.params
    zl = p.z_lift
    O, P = (0.0, 0.0), tuple(M.P)
    out = {}

    def inside(body, probe):
        return float((body ^ probe).volume()) / float(probe.volume())

    za, zb = p.post_z0 + p.post_root_fillet + 0.05, p.post_z1 - p.post_chamfer - 0.05
    for name, c, body in (("O", O, "wheel"), ("P", P, "head")):
        f = inside(M.frame, _probe(c, 0.0, p.post_r - 0.05, za, zb))
        out[f"cad_post_{name}"] = {"in_frame": round(f, 5), "spec": PROBE_MIN, "pass": f >= PROBE_MIN}
        bore = _probe(c, 0.0, p.bore_r - 0.05, p.z_band0 + p.bore_chamfer + zl + 0.05, p.bore_roof_z + zl - 0.05)
        v = float((M.bodies[body] ^ bore).volume())
        out[f"cad_bore_{name}"] = {"body": body, "material_in_bore_mm3": round(v, 5), "pass": v <= 1e-6}
    r_w = p.R_hub_cut - p.swept_gap - 0.05 - 0.05            # the classic collar radius (6.90) less 0.05
    wall = _probe(P, p.groove_apex_r + 0.05, r_w, p.z_band0 + zl + 0.05, p.z_roof0 + zl - 0.05)
    roof = _probe(P, 0.0, r_w, p.bore_roof_z + zl + 0.05, p.z_roof0 + zl - 0.05)
    fw, fr = inside(M.head, wall), inside(M.head, roof)
    out["cad_bore_wall_P"] = {"wall_in_head": round(fw, 5), "roof_in_head": round(fr, 5), "r_wall": round(r_w, 3),
                              "wall_mm": round(r_w - p.bore_r, 3), "roof_mm": round(p.z_roof0 - p.bore_roof_z, 3),
                              "spec": PROBE_MIN, "pass": min(fw, fr) >= PROBE_MIN}
    for i, (x, y) in enumerate(p.pallets):
        f = inside(M.head, _probe((x, y), 0.0, p.rp - 0.05, p.z_band0 + zl + 0.05, p.z_pallet_top + zl - 0.05))
        out[f"cad_pallet_body_{'LR'[i]}"] = {"in_head": round(f, 5), "spec": PROBE_MIN, "pass": f >= PROBE_MIN}
    return out


def v7(M, bodies) -> dict:
    p = M.params
    out = {"pose": {"phi": p.phi_print, "psi": p.psi_print}, "bodies": {}, "pairs": [], "checks": {}}
    ok_bodies = True
    for k, b in bodies.items():
        n_comp = len(b.decompose())
        v, f = mesh_arrays(b)
        tm = trimesh.Trimesh(v, f, process=True)
        info = {"status": str(b.status()), "components": n_comp, "genus": int(b.genus()),
                "watertight": bool(tm.is_watertight), "winding_consistent": bool(tm.is_winding_consistent),
                "volume_mm3": round(float(b.volume()), 2), "triangles": int(b.num_tri())}
        info["pass"] = info["status"].endswith("NoError") and n_comp == 1 and info["watertight"]
        ok_bodies &= info["pass"]
        out["bodies"][k] = info
    # STL round trip: one file, three shells
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "pp.stl"
        write_stl(path, bodies)
        tm = trimesh.load(str(path), force="mesh")
        tm.merge_vertices()
        shells = tm.split(only_watertight=False, repair=False)
        out["stl_roundtrip"] = {"shells": len(shells), "all_watertight": all(s.is_watertight for s in shells)}
    out["checks"]["three_valid_shells"] = {"pass": ok_bodies and out["stl_roundtrip"]["shells"] == 3
                                           and out["stl_roundtrip"]["all_watertight"]}
    names = list(bodies)
    gmin = math.inf
    disjoint = True
    for i in range(3):
        for j in range(i + 1, 3):
            a, b = bodies[names[i]], bodies[names[j]]
            ov = float((a ^ b).volume())
            gap = 0.0 if ov > 1e-9 else float(a.min_gap(b, 5.0))
            out["pairs"].append({"a": names[i], "b": names[j], "overlap_mm3": ov, "min_gap": round(gap, 5)})
            disjoint &= ov <= 1e-9
            gmin = min(gmin, gap)
    out["checks"]["disjoint"] = {"pass": disjoint}
    out["checks"]["global_min_gap"] = {"value": round(gmin, 5), "spec": GAP_MIN, "tol": GAP_TOL,
                                       "pass": gmin >= GAP_MIN - GAP_TOL}
    # pallet <-> tooth gap: 2-D (exact polygons) and 3-D (band slab z 3.0 .. 7.4)
    S = M.sections
    star = S["star2d"].rotate(p.phi_print)
    pal = g2.rot_about(S["pallets2d"], p.psi_print, p.P)
    hb = g2.rot_about(S["headband2d"], p.psi_print, p.P)
    d_pal = g2.min_distance_polys(star, pal)
    d_hb = g2.min_distance_polys(star, hb)
    z0, z1 = p.z_band0 + p.z_lift + 0.05, p.z_band1 + p.z_lift - 0.05
    slab = lambda m: m.trim_by_plane((0, 0, 1), z0).trim_by_plane((0, 0, -1), -z1)  # noqa: E731
    d3 = float(slab(bodies["head"]).min_gap(slab(bodies["wheel"]), 5.0))
    out["checks"]["pallet_tooth_gap"] = {"pallet_2d": round(d_pal, 4), "headband_2d": round(d_hb, 4),
                                         "band_slab_3d": round(d3, 4), "spec": PALLET_MIN,
                                         "pass": bool(min(d_pal, d3) >= PALLET_MIN)}
    out["pass"] = all(c["pass"] for c in out["checks"].values())
    return out


def mass_props(M, bodies) -> dict:
    p = M.params
    out = {}
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for k, b in bodies.items():
        bb = np.array(b.bounding_box(), float)
        lo, hi = np.minimum(lo, bb[:3]), np.maximum(hi, bb[3:])
        out[k] = {"bbox": [round(x, 3) for x in bb], "size": [round(x, 2) for x in bb[3:] - bb[:3]],
                  "volume_mm3": round(float(b.volume()), 1), "mass_solid_pla_g": round(float(b.volume()) * p.rho_pla, 2)}
    out["overall_size_WxHxD"] = [round(x, 2) for x in hi - lo]
    out["total_mass_solid_g"] = round(sum(out[k]["mass_solid_pla_g"] for k in bodies), 2)
    # head inertia about P in the DESIGN frame (solid PLA)
    v, f = mesh_arrays(M.head)
    tm = trimesh.Trimesh(v, f, process=True)
    tm.density = p.rho_pla * 1e-3          # kg / mm^3 -> moments in kg mm^2
    com = tm.center_mass
    Icom = tm.moment_inertia                # about COM, kg mm^2
    dx, dy = com[0] - M.P[0], com[1] - M.P[1]
    I_P = (Icom[2, 2] + tm.mass * (dx * dx + dy * dy)) * 1e-6   # kg m^2
    out["head_inertia"] = {"mass_g": round(tm.mass * 1e3, 2), "I_P_kgm2": float(f"{I_P:.4g}"),
                           "com_above_P_mm": round(dy, 2), "com_x_mm": round(dx, 3),
                           "spec_I_range": [4.0e-6, 8.0e-6], "spec_com_range": [8.0, 14.0],
                           "pass": bool(4.0e-6 <= I_P <= 8.0e-6 and 8.0 <= dy <= 14.0)}
    if M.info.get("sculpt"):
        # the band is the classic face heads' tuning band; a sculpt head weighs what the owner's sculpt weighs, and
        # V13 (v_escapement.py) accepts it outside the band only because V4 simulates and passes with exactly these
        # values.  Here: a warning, never a pass (the verdict on the band itself stays in "pass")
        hi = out["head_inertia"]
        hi["status"] = "pass" if hi["pass"] else "warn"
        if not hi["pass"]:
            hi["note"] = "sculpt skin: outside the SPEC 4.3 band; gated by V13 in v_escapement (accepted only if V4 passes)"
    vw, fw = mesh_arrays(M.wheel)
    tw = trimesh.Trimesh(vw, fw, process=True)
    tw.density = p.rho_pla * 1e-3
    cw = tw.center_mass
    J = (tw.moment_inertia[2, 2] + tw.mass * (cw[0] ** 2 + cw[1] ** 2)) * 1e-6
    out["wheel_inertia"] = {"mass_g": round(tw.mass * 1e3, 2), "J_O_kgm2": float(f"{J:.4g}")}
    return out


def slice_check(M, bodies) -> dict:
    """Optional: slice the 3MF with PrusaSlicer (0.2 mm, 3 perimeters) and read filament / time."""
    with tempfile.TemporaryDirectory() as td:
        f3 = Path(td) / "pb.3mf"
        write_3mf(f3, bodies)
        gc = Path(td) / "pb.gcode"
        cmd = ["prusa-slicer", "--export-gcode", "--layer-height", "0.2", "--nozzle-diameter", "0.4",
               "--filament-diameter", "1.75", "--perimeters", "3", "--top-solid-layers", "5",
               "--bottom-solid-layers", "5", "--center", "100,100", "-o", str(gc), str(f3)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            return {"ok": False, "stderr": r.stderr[-2000:]}
        txt = gc.read_text(errors="ignore")
        out = {"ok": True}
        for key, pat in (("filament_g", r"filament used \[g\] = ([\d.]+)"),
                         ("filament_mm", r"filament used \[mm\] = ([\d.]+)"),
                         ("time", r"estimated printing time \(normal mode\) = (.+)")):
            m = re.search(pat, txt)
            out[key] = m.group(1).strip() if m else None
        out["support_material"] = "support_material = 1" in txt
        return out


def _json_default(o):
    if hasattr(o, "item"):
        return o.item()
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skin", default="kitty")
    ap.add_argument("--variant", default="nominal")
    ap.add_argument("--slice", action="store_true", help="also slice the 3MF with PrusaSlicer")
    a = ap.parse_args(argv)
    t0 = time.time()
    M = build(a.skin, a.variant)
    t_build = time.time() - t0
    bodies = M.print_pose()
    sculpt = bool(M.info.get("sculpt"))
    rep = {"skin": a.skin, "variant": a.variant, "build_time_s": round(t_build, 2),
           "params": {k: v for k, v in M.params.as_dict().items() if k != "derived"},
           "skin_contract": M.info.get("skin_contract")}
    if sculpt:
        # the classic face contract's hub collar and crown collar are not built in a sculpt head / frame (the bore
        # wall they stood for is probed on the head itself: V1 cad_bore_wall_P); the face / leg / stop pad items stay
        # (the sculpt band and pads are still cut from those sections)
        sc = dict(rep["skin_contract"] or {})
        sc.pop("crown_collar", None)
        sc["warnings"] = [w for w in sc.get("warnings", []) if "collar" not in w]
        sc["note"] = "sculpt skin: hub collar / crown collar items n/a (not built); bore wall: V1 cad_bore_wall_P"
        rep["skin_contract"] = sc
        rep["sculpt"] = True
        rep["sculpt_info"] = M.info["sculpt"]
    rep["V1"] = v1(M)
    rep["V7"] = v7(M, bodies)
    rep["mass"] = mass_props(M, bodies)
    rep["section_report"] = __import__("purrbobble.core2d", fromlist=["x"]).section_report(M.params, M.sections)
    if sculpt:
        # sections of classic features that a sculpt build does not contain (its frame overhangs / bridges over the
        # head and wheel cavities are measured on the bodies by v_printability.py)
        for k in ("i3_area", "faceup_area", "facemid_area", "fill_area", "roof_area", "fill_slivers_removed_area",
                  "max_bridge_width", "n_bridge_pieces"):
            rep["section_report"].pop(k, None)
        rep["section_report"]["note"] = "sculpt bodies: classic I3 slot / face / fill / roof / bridge sections not built"
    if a.slice:
        rep["slice"] = slice_check(M, bodies)
    rep["pass"] = rep["V1"]["pass"] and rep["V7"]["pass"]
    rep["time_s"] = round(time.time() - t0, 2)
    out_dir = REPO / "verification" / "reports" / a.skin
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "basic.json" if a.variant == "nominal" else f"basic_{a.variant}.json"
    (out_dir / name).write_text(json.dumps(rep, indent=1, default=_json_default))
    print(json.dumps({"V1": rep["V1"]["pass"], "V7": rep["V7"]["pass"],
                      "global_min_gap": rep["V7"]["checks"]["global_min_gap"]["value"],
                      "pallet_tooth": rep["V7"]["checks"]["pallet_tooth_gap"],
                      "overall": rep["mass"]["overall_size_WxHxD"],
                      "head_inertia": rep["mass"]["head_inertia"],
                      "slice": rep.get("slice"), "report": str((out_dir / name).relative_to(REPO))}, indent=1,
                     default=_json_default))
    sys.exit(0 if rep["pass"] else 1)


if __name__ == "__main__":
    main()
