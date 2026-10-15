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
from manifold3d import Manifold

# per-part slicer settings written into the 3MF (PrusaSlicer volume config).  SPEC 6: head and wheel 100 %,
# frame 20 % gyroid.
PART_SETTINGS = {
    "frame": {"fill_density": "20%", "fill_pattern": "gyroid"},
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
