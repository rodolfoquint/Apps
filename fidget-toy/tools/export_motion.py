"""Export simulated escapement motion for the web viewer.

    python3 tools/export_motion.py [--skins kitty,bee,robot] [--out web/models/motion.json]

For each skin (nominal variant) this runs the same 6-DOF contact-dynamics model the V4 check uses
(verification/v_escapement.simulate) on the as-modelled CAD profiles and mass properties, at several
finger torques, and stores a steady-state window of wheel angle phi(t) and head angle psi(t).  It also
stores the 2-D star wheel outline (wheel frame) and the head band outline (head frame) at the pallet
contact height, so the page can draw the mechanism from the same geometry.  Skins not exported in this run keep
their entry in the output file.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "verification"))

import v_escapement as ve  # noqa: E402
from purrbobble import build  # noqa: E402

TORQUES = (1.0, 3.0, 10.0, 40.0)   # finger torque, N*mm (gentle stroke ... hard push)
T_END = 0.75
WINDOW = (0.45, 0.75)               # steady-state window, s
RECORD_EVERY = 20                   # dt 1e-5 s -> one sample per 0.2 ms


def ring(coords, step=0.25):
    pts = np.asarray(coords, float)
    keep = [pts[0]]
    for q in pts[1:]:
        if np.hypot(*(q - keep[-1])) >= step:
            keep.append(q)
    return np.round(np.array(keep), 3).tolist()


def export_skin(skin: str) -> dict:
    M = build(skin, "nominal")
    p = M.params
    cad = ve.extract_cad(M)
    mp = ve.mass_properties(M)
    h, w = mp["bodies"]["head"], mp["bodies"]["wheel"]
    flat = ve.WheelSDF(cad["star_poly"], ve.SDF_H).flat()
    base = dict(D=float(cad["P"][1]), pins=[tuple(map(float, c)) for c in cad["pins"]], rp=cad["rp"],
                psi_b=cad["psi_b"], I_h=h["I_P_kgm2"], m_h=h["mass_g"] * 1e-3, com=tuple(h["com_rel_P_mm"]),
                J_w=w["J_O_kgm2"] + ve.J_FINGER, m_w=w["mass_g"] * 1e-3, r_b=p.post_d / 2, r_k=p.r_k,
                k_bank=100.0, c_r=cad["c_r"])
    runs = []
    for T in TORQUES:
        r = ve.simulate(T, 1, sdf=flat, t_end=T_END, record_every=RECORD_EVERY, **base)
        rec = np.array([x[:3] for x in r["_rec"]], float)
        sel = (rec[:, 0] >= WINDOW[0]) & (rec[:, 0] < WINDOW[1])
        t = rec[sel, 0] - rec[sel, 0][0]
        phi = np.degrees(rec[sel, 1] - rec[sel, 1][0])
        psi = np.degrees(rec[sel, 2])
        runs.append({"T_Nmm": T, "rps": r["rps"], "f_head_hz": r["f_head"], "swing_pp_deg": r["swing"],
                     "clicks_per_s": r["imp_s"], "status": r["status"], "dt_ms": RECORD_EVERY * 1e-2,
                     "phi_deg": np.round(phi, 2).tolist(), "psi_deg": np.round(psi, 2).tolist()})
        print(f"{skin:6s} T={T:5.1f} N*mm  {r['rps']:.2f} rev/s  head {r['f_head']:.1f} Hz  "
              f"swing {r['swing']:.1f} deg  {r['status']}  ({len(t)} samples)", flush=True)
    band_poly = cad["head_band_poly"]
    if M.info.get("sculpt"):
        # a sculpt head's legs under thin sculpt are lowered (top 3.97, below the contact height) and its sculpted
        # body reaches down around the band: draw the head's slices over the band height (legs included) inside
        # the band outline
        hb = ve.cs_to_shapely(M.sections["headband2d"], holes=False).buffer(0.05)
        band_poly = cad["head_full_poly"].intersection(hb)
    band = [ring(g.exterior.coords) for g in ve.parts(band_poly)]
    return {"P": [float(cad["P"][0]), float(cad["P"][1])], "psi_b": float(cad["psi_b"]),
            "rp": float(cad["rp"]), "pins": [list(map(float, c)) for c in cad["pins"]],
            "star": ring(cad["star_poly"].exterior.coords, 0.15), "head_band": band,
            "I_h": h["I_P_kgm2"], "head_g": h["mass_g"], "total_g": mp["total_mass_g"], "runs": runs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skins", default="kitty,bee,robot")
    ap.add_argument("--out", default=str(ROOT / "web" / "models" / "motion.json"))
    a = ap.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(out.read_text())          # entries of the skins not exported now stay
    except (OSError, ValueError):
        data = {}
    data.update({s: export_skin(s) for s in a.skins.split(",")})
    out.write_text(json.dumps(data, separators=(",", ":")))
    print(f"wrote {out} ({out.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()
