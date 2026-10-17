"""Purr-Bobble: print-in-place, spring-free foliot / pin-pallet escapement fidget (docs/SPEC.md).

    from purrbobble import build
    M = build(skin="kitty", variant="nominal")
    M.frame, M.wheel, M.head          # manifold3d.Manifold, design frame (phi = 0, psi = 0)
    M.posed(12.0, 5.96)               # {'frame','wheel','head'} at the print pose

See purrbobble/README.md.
"""
from .params import Params, get_params, VARIANTS  # noqa: F401


def build(skin="kitty", variant="nominal", **kw):
    from .model import build as _build
    return _build(skin=skin, variant=variant, **kw)
