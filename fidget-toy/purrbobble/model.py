"""Top-level model: ``build(skin, variant) -> Model``.

    from purrbobble.model import build
    M = build("kitty", "nominal")
    M.frame, M.wheel, M.head      # manifold3d.Manifold, DESIGN frame (phi = 0, psi = 0), mm, Z up
    M.O, M.P                      # (0, 0), (0, D) - wheel and head axes (vertical lines x, y)
    M.params                      # purrbobble.params.Params
    M.sections                    # dict name -> CrossSection (see core2d.build_sections)
    M.posed(phi_deg, psi_deg)     # {'frame','wheel','head'}: wheel rotated phi about O, head psi about P
    M.print_pose()                # = posed(p.phi_print, p.psi_print) = posed(12.0, 5.96)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from manifold3d import Manifold

from . import core2d, solids
from .params import Params, get_params
from .skins import get_skin
from .skins.base import Skin


@dataclass
class Model:
    frame: Manifold
    wheel: Manifold
    head: Manifold
    params: Params
    sections: core2d.Sections
    skin: Skin
    info: dict = field(default_factory=dict)
    _pp: dict | None = field(default=None, repr=False)      # (cached float32-clean print pose, sculpt skins)

    @property
    def O(self) -> tuple:
        return (0.0, 0.0)

    @property
    def P(self) -> tuple:
        return self.params.P

    @property
    def bodies(self) -> dict:
        return {"frame": self.frame, "wheel": self.wheel, "head": self.head}

    def wheel_at(self, phi_deg: float) -> Manifold:
        return self.wheel.rotate((0.0, 0.0, float(phi_deg))) if phi_deg else self.wheel

    def head_at(self, psi_deg: float) -> Manifold:
        if not psi_deg:
            return self.head
        px, py = self.P
        return self.head.translate((-px, -py, 0.0)).rotate((0.0, 0.0, float(psi_deg))).translate((px, py, 0.0))

    def posed(self, phi_deg: float = 0.0, psi_deg: float = 0.0) -> dict:
        """World-frame bodies with the wheel at phi (CCW+ about O) and the head at psi (CCW+ about P)."""
        return {"frame": self.frame, "wheel": self.wheel_at(phi_deg), "head": self.head_at(psi_deg)}

    def print_pose(self) -> dict:
        b = self.posed(self.params.phi_print, self.params.psi_print)
        if hasattr(self.skin, "sculpt"):
            # the sculpt bodies are float32-clean as built; turned to the print pose, float32 rounding can make new
            # sliver triangles: the exported (and checked) posed head and wheel are made float32-clean themselves
            from .sculpt import float32_stable
            if self._pp is None:
                self._pp = {k: (float32_stable(v, self.params, k) if k != "frame" else v) for k, v in b.items()}
            return dict(self._pp)
        return b


def build(skin: str | Skin = "kitty", variant: str = "nominal", params: Params | None = None,
          verbose: bool = False) -> Model:
    t0 = time.time()
    sk = get_skin(skin)
    p = params if params is not None else get_params(variant, skin=sk.name)
    S = core2d.build_sections(p, sk, verbose=verbose)
    t1 = time.time()
    wheel, winfo = solids.build_wheel(p, S, sk)
    S["wheel_relief2d"] = winfo["relief2d"]
    if hasattr(sk, "sculpt"):
        # the classic head and frame are not used by a sculpt skin (purrbobble/sculpt.py builds both from the
        # sculpt and the sections), so they are not built
        head, hinfo = Manifold(), {"features": [], "collar2d": None}
        frame, finfo = Manifold(), {}
    else:
        head, hinfo = solids.build_head(p, S, sk)
        frame, finfo = solids.build_frame(p, S, sk)
        S["collar2d"] = hinfo["collar2d"]
    t2 = time.time()
    sinfo = {}
    if hasattr(sk, "sculpt"):
        # round 5: the mechanism goes inside the skin's sculpted mesh (purrbobble/sculpt.py).  The integration takes
        # a few minutes, so its bodies are cached on disk under a hash of every input (see _sculpt_cache)
        from . import sculpt as _sc
        hit = _sculpt_cache(sk, p)
        if hit is not None and hit[0].exists():
            frame, wheel, head, sinfo = _cache_load(hit[0])
            sinfo = dict(sinfo, cache="hit")
        else:
            M0 = Model(frame=frame, wheel=wheel, head=head, params=p, sections=S, skin=sk, info={})
            sinfo = _sc.integrate(M0, verbose=verbose)
            frame, wheel, head = M0.frame, M0.wheel, M0.head
            if hit is not None:
                _cache_save(hit[0], frame, wheel, head, sinfo)
        hinfo = dict(hinfo, head_base=None, feature_parts={})
    info = {"t_sections_s": round(t1 - t0, 2), "t_solids_s": round(t2 - t1, 2),
            "skin_contract": S.get("skin_contract"), "face_features": [f.name for f in hinfo["features"]],
            # solids for the colour regions (assemble.colour_parts): the bodies before their surface features and
            # each draped feature's added / removed solid
            "head_base": hinfo.get("head_base"), "head_feature_parts": hinfo.get("feature_parts", {}),
            "frame_colour_masks": finfo.get("colour_masks", []), "sculpt": sinfo}
    if verbose:
        print(f"  [model] sections {t1 - t0:.1f}s, solids {t2 - t1:.1f}s", flush=True)
    return Model(frame=frame, wheel=wheel, head=head, params=p, sections=S, skin=sk, info=info)


# ------------------------------------------------------------------------------------------------ sculpt body cache
CACHE_DIR = Path(__file__).resolve().parents[1] / "build_cache"
CACHE_VERSION = 1           # bump to invalidate every cached body (e.g. after changing build() itself)
# modules that cannot change the bodies (colours, export, reports): edits there keep the cache
NON_GEOMETRY = {"assemble.py", "build.py", "__init__.py", "model.py"}


def _sculpt_cache(sk, p: Params):
    """(path, key) of the cached integrated bodies for this skin and parameter set, or None if caching is off
    (PURRBOBBLE_NO_CACHE=1).  The key hashes every geometry source file of the package (not NON_GEOMETRY; bump
    CACHE_VERSION when build() itself changes), the sculpt file, the skin's class attributes and the full parameter
    set, so any change to the geometry rebuilds."""
    import hashlib
    import os
    if os.environ.get("PURRBOBBLE_NO_CACHE"):
        return None
    h = hashlib.sha1(f"v{CACHE_VERSION}".encode())
    pkg = Path(__file__).resolve().parent
    for f in sorted(pkg.rglob("*.py")):
        rel = f.relative_to(pkg).as_posix()
        if rel in NON_GEOMETRY:
            continue
        h.update(rel.encode())
        h.update(f.read_bytes())
    src = Path(__file__).resolve().parents[1] / sk.source
    st = src.stat()
    h.update(f"{src.name}:{st.st_size}:{int(st.st_mtime)}".encode())
    attrs = {k: getattr(type(sk), k) for k in dir(type(sk)) if not k.startswith("_")
             and not callable(getattr(type(sk), k))}
    h.update(repr(sorted((k, repr(v)) for k, v in attrs.items())).encode())
    h.update(repr(p).encode())
    key = h.hexdigest()[:16]
    return CACHE_DIR / f"{sk.name}_{p.variant}_{key}.npz", key


def _cache_save(path: Path, frame, wheel, head, info: dict) -> None:
    import json
    import numpy as np
    path.parent.mkdir(parents=True, exist_ok=True)
    arrs = {}
    for name, m in (("frame", frame), ("wheel", wheel), ("head", head)):
        mesh = m.to_mesh()
        arrs[name + "_v"] = np.asarray(mesh.vert_properties, dtype=np.float32)[:, :3]
        arrs[name + "_f"] = np.asarray(mesh.tri_verts, dtype=np.uint32)
    tmp = path.with_suffix(".tmp.npz")
    np.savez_compressed(tmp, info=np.array(json.dumps(info, default=str)), **arrs)
    tmp.replace(path)


def _cache_load(path: Path):
    import json
    import numpy as np
    from manifold3d import Mesh
    d = np.load(path)
    out = []
    for name in ("frame", "wheel", "head"):
        v = np.array(d[name + "_v"], dtype=np.float32, order="C", copy=True)
        f = np.array(d[name + "_f"], dtype=np.uint32, order="C", copy=True)
        out.append(Manifold(Mesh(vert_properties=v, tri_verts=f)))
    return out[0], out[1], out[2], json.loads(str(d["info"]))
