"""Pose the bodies at the print pose, assert they are disjoint, and export STL / 3MF (SPEC 3.4 "Export").

    from purrbobble.assemble import print_bodies, check_print_pose, write_stl, write_3mf
    B = print_bodies(M)                         # {'frame','wheel','head'} at (phi_print, psi_print)
    rep = check_print_pose(B, min_gap=0.35)     # raises AssertionError on overlap / bad topology
    write_stl("x.stl", B)                       # one binary STL, one shell per body
    write_3mf("x.3mf", B)                       # one object with three parts + per-part infill (PrusaSlicer)
"""
from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import numpy as np
from manifold3d import Manifold, OpType

_ADD = OpType.Add

# per-part slicer settings written into the 3MF (PrusaSlicer volume config).  SPEC 6: head and wheel 100 %,
# frame 20 % gyroid.
PART_SETTINGS = {
    # bridge_angle 180 (= along X; PrusaSlicer reads 0 as "automatic"): the crown roof's first layer then crosses
    # both leg channels steeply and the band-top rib web every few mm (longest unsupported strand 12.7 mm vs
    # ~20 mm with the automatic direction, which runs along a channel)
    "frame": {"fill_density": "20%", "fill_pattern": "gyroid", "bridge_angle": "180"},
    "wheel": {"fill_density": "100%"},
    "head": {"fill_density": "100%"},
}


def print_bodies(model) -> dict:
    return model.print_pose()


def mesh_arrays(m: Manifold) -> tuple[np.ndarray, np.ndarray]:
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    f = np.asarray(mesh.tri_verts, dtype=np.int64)
    return v, f


def check_print_pose(bodies: dict, min_gap: float = 0.35, tol: float = 2e-3, search: float = 3.0) -> dict:
    """Three disjoint, valid, single-component shells with pairwise min gap >= min_gap (- tol)."""
    rep = {"bodies": {}, "pairs": []}
    for k, b in bodies.items():
        n = len(b.decompose())
        rep["bodies"][k] = {"components": n, "genus": b.genus(), "volume_mm3": round(b.volume(), 2),
                            "status": str(b.status())}
        if n != 1:
            raise AssertionError(f"{k}: {n} components")
    names = list(bodies)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = bodies[names[i]], bodies[names[j]]
            ov = (a ^ b).volume()
            gap = 0.0 if ov > 1e-9 else a.min_gap(b, search)
            rep["pairs"].append({"a": names[i], "b": names[j], "overlap_mm3": ov, "min_gap": gap})
            if ov > 1e-9 or gap < min_gap - tol:
                raise AssertionError(f"{names[i]}/{names[j]}: overlap {ov:.4f} mm^3, gap {gap:.4f} < {min_gap}")
    rep["global_min_gap"] = min(r["min_gap"] for r in rep["pairs"])
    return rep


# ---------------------------------------------------------------------------------------------- STL
def write_stl(path, bodies: dict | Manifold) -> int:
    """Binary STL; several bodies become separate shells in one file.  Returns the triangle count."""
    if isinstance(bodies, Manifold):
        bodies = {"body": bodies}
    tris = []
    for b in bodies.values():
        v, f = mesh_arrays(b)
        tris.append(v[f])
    T = np.concatenate(tris, axis=0)
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)
    rec = np.zeros(len(T), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"] = n
    rec["v"] = T
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        hdr = b"purrbobble binary STL"
        fh.write(hdr + b" " * (80 - len(hdr)))
        fh.write(struct.pack("<I", len(T)))
        fh.write(rec.tobytes())
    return len(T)


# ---------------------------------------------------------------------------------------------- 3MF
_CT = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="text/xml"/>
</Types>
"""
_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def write_3mf(path, bodies: dict, name: str = "purrbobble", settings: dict | None = None) -> dict:
    """One 3MF object made of three parts.

    The object holds one mesh with the three shells; ``Metadata/Slic3r_PE_model.config`` declares each
    shell as a named volume (frame / wheel / head) with its own infill (PrusaSlicer, and slicers that read its
    3MF flavour, e.g. OrcaSlicer).  Other slicers see one object with three shells.
    """
    settings = PART_SETTINGS if settings is None else settings
    vs, fs, ranges = [], [], []
    v0 = t0 = 0
    for k, b in bodies.items():
        v, f = mesh_arrays(b)
        vs.append(v)
        fs.append(f + v0)
        ranges.append((k, t0, t0 + len(f) - 1))
        v0 += len(v)
        t0 += len(f)
    V = np.concatenate(vs)
    F = np.concatenate(fs)
    vert_xml = "\n".join(f'     <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>' for x, y, z in V)
    tri_xml = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in F)
    model = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
 xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">
 <metadata name="Title">{name}</metadata>
 <metadata name="Application">purrbobble (manifold3d)</metadata>
 <metadata name="slic3rpe:Version3mf">1</metadata>
 <resources>
  <object id="1" name="{name}" type="model">
   <mesh>
    <vertices>
{vert_xml}
    </vertices>
    <triangles>
{tri_xml}
    </triangles>
   </mesh>
  </object>
 </resources>
 <build>
  <item objectid="1" printable="1"/>
 </build>
</model>
"""
    vol_xml = []
    for k, a, b in ranges:
        md = [f'   <metadata type="volume" key="name" value="{k}"/>',
              '   <metadata type="volume" key="volume_type" value="ModelPart"/>']
        for sk, sv in settings.get(k, {}).items():
            md.append(f'   <metadata type="volume" key="{sk}" value="{sv}"/>')
        vol_xml.append(f'  <volume firstid="{a}" lastid="{b}">\n' + "\n".join(md) + "\n  </volume>")
    config = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n'
              f' <object id="1" instances_count="1">\n  <metadata type="object" key="name" value="{name}"/>\n'
              + "\n".join(vol_xml) + "\n </object>\n</config>\n")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/Slic3r_PE_model.config", config)
    return {"triangles": int(len(F)), "vertices": int(len(V)), "parts": [r[0] for r in ranges]}


# ------------------------------------------------------------------------------------------- multi-colour
# Filament slots for the multi-colour 3MF: one per distinct colour of the skin's palette, numbered in SLOT_ORDER
# (kitty: 1 cream body + head, 2 coral ball + accents, 3 mint cushion, 4 dark details).  Every skin keeps to
# MAX_SLOTS colours so one Bambu AMS / Prusa MMU prints it; the viewer and renders show the same colours.
SLOT_ORDER = ("frame", "wheel", "head", "plate", "accent", "details")
MAX_SLOTS = 4
COLOUR_SKIN = 0.4       # thickness of a coloured floor under a recess / of a flush inlay (2 layers)
PLATE_RELIEF_MAX = 1.2  # raised cushion relief (piping, quilting) on the plate top: up to z_bp + 1.2


def _prism(cs, z0, z1):
    from . import geom2d as g2
    if cs is None or cs.is_empty():
        return Manifold()
    return g2.grow(cs, 0.03, 0.005).extrude(z1 - z0).translate((0.0, 0.0, z0))


def colour_parts(M, phi: float | None = None, psi: float | None = None) -> dict:
    """Split the three bodies into colour regions, posed at (phi, psi) (default: print pose).

    Returns {name: (Manifold, colour_key)} with names frame_plate, frame_body, frame_accent, head_body,
    head_details, head_accent, wheel; colour keys index ``skin.palette()`` (+ "accent").  Regions are cut with
    prisms over the skin's coloured features (Feature.color) above the surface they sit on, so a dimple cut into
    a dark eye (the highlight) stays in the body colour.  A sculpt skin (purrbobble/sculpt.py) has no colour
    regions of its own: frame_body, head_body and wheel, one colour each."""
    p, sk = M.params, M.skin
    phi = p.phi_print if phi is None else phi
    psi = p.psi_print if psi is None else psi
    lift = p.z_lift
    out = {}
    # frame: plate below z_bp, body above; accents raised on the decor / paw tops
    F = M.frame
    # split 1 um above the plate top: a cut exactly on the plate's top face leaves coplanar slivers
    zs = p.z_bp + 1e-3
    from . import geom2d as g2
    S = M.sections
    if (M.info or {}).get("sculpt"):
        # the sculpt's cushion is its own surface, not the classic backdrop2d - body2d (still in S, but not in the
        # bodies): no plate region.  The skin has no decor, paw or face features (and no torso2d), so the frame,
        # head and wheel come out whole, one colour each (frame / head cream, wheel coral)
        body = F
    else:
        # the plate, plus the skid ribs where they lie on the exposed cushion (outside the body): cushion colour
        exposed = g2.difference(S["backdrop2d"], g2.grow(S["body2d"], 0.05, 0.005))
        pd = S.get("plate_decor2d")
        if pd is not None and not pd.is_empty():
            exposed = g2.difference(exposed, g2.grow(pd, 0.05, 0.005))        # a tail on the cushion stays cream
        # the cushion: the plate, its raised quilting / piping and the skid ribs where they lie on the exposed cushion
        z_cush = p.z_bp + max(p.rib_h, PLATE_RELIEF_MAX) + 0.05
        pmask = Manifold.cube((400.0, 400.0, zs + 200.0)).translate((-200.0, -200.0, -200.0)) + \
            _prism(exposed, zs - 0.01, z_cush)
        out["frame_plate"] = (F ^ pmask, "plate")
        body = F - pmask
    acc = {"accent": [], "details": []}
    for f in sk.body_decor_features(p) or []:
        if f.color in acc:
            acc[f.color].append(_prism(f.shape, p.z_decor1 - 1e-3, p.z_decor1 + 2.0))
    draped = (M.info or {}).get("frame_colour_masks") or []
    names_draped = set()
    for side, style in (sk.paw_style(p) or {}).items():
        if getattr(style, "round_xy", 0.0) > 0:
            continue                                       # draped: masks come from the build
        for f in style.features or []:
            if f.color in acc:
                acc[f.color].append(_prism(f.shape, p.paw_z1 - 1e-3, p.paw_z1 + 2.0))
    for key, m in draped:
        if key in acc and not m.is_empty():
            acc[key].append(m)
    for key, ms in acc.items():
        if ms:
            mask = Manifold.batch_boolean(ms, _ADD) if len(ms) > 1 else ms[0]
            reg = body ^ mask
            if not reg.is_empty():
                out[f"frame_{key}"] = (reg, key)
                body = body - mask
    # the body above the plate outside the skin's torso outline (and its paws, decor, tiers) is cushion-coloured
    torso = sk.torso2d(p, S) if hasattr(sk, "torso2d") else None
    if torso is not None and not torso.is_empty():
        keep = [torso, S["decor2d"], S.get("tiers2d", None), S.get("plate_decor2d", None)] + \
            list((S.get("paw_plans") or {}).values())
        keep = g2.union([k for k in keep if k is not None and not k.is_empty()])
        hood2d = g2.difference(g2.grow(S["backdrop2d"], 1.0, 0.01), g2.grow(keep, 0.02, 0.005))
        hood = body ^ _prism(hood2d, zs - 0.01, 40.0)
        if not hood.is_empty():
            out["frame_hood"] = (hood, "plate")
            body = body - _prism(hood2d, zs - 0.01, 40.0)
    out["frame_body"] = (body, "frame")
    # head (design frame), then posed
    H = M.head
    z0 = p.z_front1 + lift
    masks = {"details": [], "accent": []}
    fparts = (M.info or {}).get("head_feature_parts") or {}
    base = (M.info or {}).get("head_base")
    for f in sk.face_features(p.C_h, p) or []:
        if f.color not in masks:
            continue
        if fparts and base is not None:
            # draped features (pillowed face): raised = what stands above the featureless head; recessed = a 0.4
            # floor under the cut; inlay = the top 0.4 of the surface
            add, cut = fparts.get(f.name, (None, None))
            if f.mode in ("raise", "dome") and add is not None:
                masks[f.color].append(add - base)
            elif f.mode == "deboss" and cut is not None:
                masks[f.color].append(cut.translate((0.0, 0.0, -COLOUR_SKIN)))
            elif f.mode == "inlay":
                masks[f.color].append(_prism(f.shape, p.z_front0, p.z_feat + 5.0)
                                      ^ (base - base.translate((0.0, 0.0, -COLOUR_SKIN))))
        elif f.mode in ("raise", "dome"):
            masks[f.color].append(_prism(f.shape, z0, z0 + 2.0))
    hb = H
    for key, ms in masks.items():
        ms = [m for m in ms if not m.is_empty()]
        if ms:
            mk = Manifold.batch_boolean(ms, _ADD) if len(ms) > 1 else ms[0]
            out[f"head_{key}"] = (H ^ mk, key)
            hb = hb - mk
    out["head_body"] = (hb, "head")
    px, py = M.P
    for k in [k for k in out if k.startswith("head")]:
        m, c = out[k]
        out[k] = (m.translate((-px, -py, 0.0)).rotate((0.0, 0.0, float(psi))).translate((px, py, 0.0)), c)
    out["wheel"] = (M.wheel.rotate((0.0, 0.0, float(phi))), "wheel")
    return {k: v for k, v in out.items() if not v[0].is_empty() and v[0].volume() > 1e-3}


def palette_of(skin) -> dict:
    pal = skin.palette()
    pal.setdefault("accent", getattr(skin, "accent_color", None) or pal["wheel"])
    if getattr(skin, "accent_color", None):
        pal["accent"] = skin.accent_color
    return pal


def colour_slots(skin) -> tuple[dict, dict]:
    """(colour class -> filament slot, slot -> colour): one slot per distinct palette colour, in SLOT_ORDER."""
    pal = palette_of(skin)
    slot_of, colours = {}, {}
    for k in SLOT_ORDER:
        c = pal[k].lower()
        slot = next((n for n, cc in colours.items() if cc == c), None)
        if slot is None:
            slot = len(colours) + 1
            colours[slot] = c
        slot_of[k] = slot
    if len(colours) > MAX_SLOTS:
        raise ValueError(f"skin {skin.name}: {len(colours)} colours, more than {MAX_SLOTS} filament slots")
    return slot_of, colours


def write_3mf_multicolour(path, M, name: str = "purrbobble") -> dict:
    """One object, one volume per colour region (print pose), each with its filament slot (``extruder``) and the
    per-part settings of its body.  Slots: colour_slots()."""
    slot_of, colours = colour_slots(M.skin)
    bodies, settings = {}, {}
    for k, (m, ckey) in colour_parts(M).items():
        body = k.split("_")[0]
        bodies[k] = m
        settings[k] = dict(PART_SETTINGS.get(body, {}), extruder=str(slot_of[ckey]))
    info = write_3mf(path, bodies, name=name, settings=settings)
    info["slots"] = {str(n): c for n, c in colours.items()}
    return info
