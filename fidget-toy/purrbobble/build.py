"""Command-line build: STL / 3MF / renders for one skin and variant (or all variants).

    python3 -m purrbobble.build --skin kitty --variant nominal
    python3 -m purrbobble.build --skin kitty --all            # nominal, deep, shallow, loose
    python3 -m purrbobble.build --skin kitty --all --no-render

Outputs (repo-relative):

    stl/<skin>/purrbobble_<skin>_<variant>.stl             one binary STL, three shells at the print pose
    stl/<skin>/purrbobble_<skin>_nominal_{frame,wheel,head}.stl   per-body STLs (print pose, nominal only)
    stl/<skin>/purrbobble_<skin>_nominal.3mf               one object, three parts (head & wheel 100 % infill)
    stl/<skin>/build_<variant>.json                        sizes, volumes, gaps, timings, section report
    renders/<skin>/purrbobble_<skin>_<variant>_<view>.png  (nominal: face, three_quarter, iso, top_down,
                                                            back, section_x0, section_z5)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from manifold3d import Manifold

from . import core2d
from .assemble import check_print_pose, write_3mf, write_3mf_multicolour, write_stl
from .model import Model, build
from .params import VARIANTS

REPO = Path(__file__).resolve().parents[1]

# OpenSCAD gimbal camera angles (rotx, roty, rotz); Z is the toy's front.
VIEWS = {
    "face": (14, 0, 8),             # at the face (toy front), slightly tilted for shading
    "three_quarter": (28, 0, 18),   # front, slightly from below-right
    "iso": (55, 0, 30),
    "top_down": (62, 0, 180),       # from above the ears
    "back": (180, 0, 0),
}


def _bbox(m: Manifold) -> list:
    bb = m.bounding_box()
    return [round(float(x), 3) for x in bb]


def model_report(M: Model, bodies: dict) -> dict:
    p = M.params
    rep = {"skin": M.skin.name, "variant": p.variant, "pose": {"phi": p.phi_print, "psi": p.psi_print},
           "D": p.D, "P": p.P, "pallets": p.pallets, "info": M.info,
           "sections": core2d.section_report(p, M.sections), "bodies": {}}
    for k, b in bodies.items():
        bb = _bbox(b)
        rep["bodies"][k] = {"volume_mm3": round(b.volume(), 1), "mass_solid_g": round(b.volume() * p.rho_pla, 2),
                            "triangles": b.num_tri(), "bbox": bb,
                            "size": [round(bb[3] - bb[0], 2), round(bb[4] - bb[1], 2), round(bb[5] - bb[2], 2)]}
    allbb = [min(rep["bodies"][k]["bbox"][i] for k in bodies) for i in range(3)] + \
            [max(rep["bodies"][k]["bbox"][i] for k in bodies) for i in range(3, 6)]
    rep["overall_size"] = [round(allbb[3] - allbb[0], 2), round(allbb[4] - allbb[1], 2), round(allbb[5] - allbb[2], 2)]
    return rep


def render_model(M: Model, bodies: dict, out_prefix: Path, views=None, sections: bool = True) -> list[Path]:
    sys.path.insert(0, str(REPO / "tools"))
    from render import render_views  # noqa: E402
    from .assemble import colour_parts, palette_of
    pal = palette_of(M.skin)
    parts = {k: (bodies[k], pal.get(k, "#cccccc")) for k in ("frame", "wheel", "head")}
    # views in the multi-colour palette (cushion, body, ball, face details, accents)
    cparts = {k: (m, pal[c]) for k, (m, c) in colour_parts(M).items()}
    out = []
    views = views or VIEWS
    for name, cam in views.items():
        pngs = render_views(cparts, out_prefix.parent / "_tmp", views=(cam,), size=(1100, 1000))
        dst = out_prefix.parent / f"{out_prefix.name}_{name}.png"
        pngs[0].replace(dst)
        out.append(dst)
    if sections:
        # section at x = 0 (through both axes), seen from +X
        cut = {k: (b.trim_by_plane((-1.0, 0.0, 0.0), 0.0), c) for k, (b, c) in parts.items()}
        pngs = render_views(cut, out_prefix.parent / "_tmp", views=((90, 0, 90),), size=(1100, 1000))
        dst = out_prefix.parent / f"{out_prefix.name}_section_x0.png"
        pngs[0].replace(dst)
        out.append(dst)
        # section at z = 5.2 (pallet / tooth level), seen from +Z
        cutz = {k: (b.trim_by_plane((0.0, 0.0, -1.0), -5.2), c) for k, (b, c) in parts.items()}
        cutz = {k: v for k, v in cutz.items() if not v[0].is_empty()}
        pngs = render_views(cutz, out_prefix.parent / "_tmp", views=((0, 0, 0),), size=(1100, 1000))
        dst = out_prefix.parent / f"{out_prefix.name}_section_z5.png"
        pngs[0].replace(dst)
        out.append(dst)
    return out


def build_one(skin: str, variant: str, stl_dir: Path, render_dir: Path | None, verbose: bool = True,
              per_body: bool | None = None, threemf: bool | None = None) -> dict:
    t0 = time.time()
    M = build(skin, variant, verbose=verbose)
    bodies = M.print_pose()
    chk = check_print_pose(bodies, min_gap=0.35)
    stl_dir.mkdir(parents=True, exist_ok=True)
    base = f"purrbobble_{M.skin.name}_{variant}"
    files = []
    ntri = write_stl(stl_dir / f"{base}.stl", bodies)
    files.append(str((stl_dir / f"{base}.stl").relative_to(REPO)))
    per_body = (variant == "nominal") if per_body is None else per_body
    threemf = (variant == "nominal") if threemf is None else threemf
    if per_body:
        for k, b in bodies.items():
            write_stl(stl_dir / f"{base}_{k}.stl", {k: b})
            files.append(str((stl_dir / f"{base}_{k}.stl").relative_to(REPO)))
    if threemf:
        write_3mf(stl_dir / f"{base}.3mf", bodies, name=base)
        files.append(str((stl_dir / f"{base}.3mf").relative_to(REPO)))
        # multi-colour version: one volume per colour region with its filament slot (assemble.colour_slots)
        write_3mf_multicolour(stl_dir / f"{base}_multicolour.3mf", M, name=base + "_multicolour")
        files.append(str((stl_dir / f"{base}_multicolour.3mf").relative_to(REPO)))
    t_export = time.time() - t0
    renders = []
    if render_dir is not None:
        render_dir.mkdir(parents=True, exist_ok=True)
        views = VIEWS if variant == "nominal" else {"face": VIEWS["face"], "three_quarter": VIEWS["three_quarter"]}
        renders = render_model(M, bodies, render_dir / base, views, sections=(variant == "nominal"))
        renders = [str(r.relative_to(REPO)) for r in renders]
        tmp = render_dir / "_tmp"
        if tmp.exists() and tmp.is_dir():
            for f in tmp.iterdir():
                f.unlink()
            tmp.rmdir()
    rep = model_report(M, bodies)
    rep.update({"print_pose_check": chk, "stl_triangles": ntri, "files": files, "renders": renders,
                "time_build_export_s": round(t_export, 2), "time_total_s": round(time.time() - t0, 2)})
    (stl_dir / f"build_{variant}.json").write_text(json.dumps(rep, indent=1, default=str))
    if verbose:
        print(f"[{M.skin.name}/{variant}] {ntri} tris, min gap {chk['global_min_gap']:.3f}, "
              f"size {rep['overall_size']}, {rep['time_total_s']} s", flush=True)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skin", default="kitty", help="skin name, or 'all' for every registered skin that imports")
    ap.add_argument("--variant", default="nominal", choices=VARIANTS)
    ap.add_argument("--all", action="store_true", help="build every variant")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--out", default=str(REPO), help="output root (stl/ and renders/ go below it)")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)
    from .skins import available
    skins = available() if a.skin == "all" else [a.skin]
    variants = VARIANTS if a.all else (a.variant,)
    root = Path(a.out)
    for s in skins:
        for v in variants:
            build_one(s, v, root / "stl" / s, None if a.no_render else root / "renders" / s, verbose=not a.quiet)


if __name__ == "__main__":
    main()
