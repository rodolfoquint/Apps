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
        return self.posed(self.params.phi_print, self.params.psi_print)


def build(skin: str | Skin = "kitty", variant: str = "nominal", params: Params | None = None,
          verbose: bool = False) -> Model:
    t0 = time.time()
    sk = get_skin(skin)
    p = params if params is not None else get_params(variant, skin=sk.name)
    S = core2d.build_sections(p, sk, verbose=verbose)
    t1 = time.time()
    wheel, winfo = solids.build_wheel(p, S, sk)
    head, hinfo = solids.build_head(p, S, sk)
    frame, finfo = solids.build_frame(p, S, sk)
    S["wheel_relief2d"] = winfo["relief2d"]
    S["collar2d"] = hinfo["collar2d"]
    t2 = time.time()
    sinfo = {}
    if hasattr(sk, "sculpt"):
        # round 5: the mechanism goes inside the skin's sculpted mesh (purrbobble/sculpt.py)
        from . import sculpt as _sc
        M0 = Model(frame=frame, wheel=wheel, head=head, params=p, sections=S, skin=sk, info={})
        sinfo = _sc.integrate(M0, verbose=verbose)
        frame, wheel, head = M0.frame, M0.wheel, M0.head
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
