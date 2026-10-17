"""Swept envelopes of the swinging head (SPEC 2.4(e), 2.5).

    Swept(X)    = U over psi in [-psi_b, +psi_b] of Rot_P(+psi)(X)    (head-frame shape -> world frame)
    SweptInv(X) = U over psi in [-psi_b, +psi_b] of Rot_P(-psi)(X)    (world-frame shape -> head frame)

Implemented with CrossSection.rotate on n >= 100 poses (step <= 0.25 deg) and one Clipper2 batch union.
The result is grown by ``allowance`` (default 0.05 mm, SPEC "add 0.05 mm to every swept offset for chord
error").  For the symmetric range used here both sets of angles coincide, so ``swept_inv`` equals ``swept``
mathematically; both are kept so call sites read like the SPEC equations (and an asymmetric
``psi_range`` works correctly).
"""
from __future__ import annotations

import math

import numpy as np
from manifold3d import CrossSection, OpType

from . import geom2d as g2

N_MIN = 100


def poses(psi_range, n: int | None = None, max_step: float = 0.25) -> np.ndarray:
    lo, hi = psi_range
    need = int(math.ceil((hi - lo) / max_step)) + 1
    n = max(n or 0, need, N_MIN)
    return np.linspace(lo, hi, n)


def _sweep(cs: CrossSection, pivot, angles, allowance: float, simplify_eps: float) -> CrossSection:
    if cs.is_empty():
        return cs
    base = cs.simplify(simplify_eps) if simplify_eps > 0 else cs
    copies = [g2.rot_about(base, float(a), pivot) for a in angles]
    out = CrossSection.batch_boolean(copies, OpType.Add)
    if allowance > 0:
        out = g2.grow(out, allowance, 0.002)
    return out.simplify(simplify_eps) if simplify_eps > 0 else out


def swept(cs: CrossSection, pivot, psi_b: float = 12.42, n: int | None = 101, allowance: float = 0.05,
          psi_range=None, simplify_eps: float = 0.001) -> CrossSection:
    """World-frame envelope of head-frame shape ``cs`` rotated about ``pivot`` over the swing."""
    rng = psi_range if psi_range is not None else (-psi_b, psi_b)
    return _sweep(cs, pivot, poses(rng, n), allowance, simplify_eps)


def swept_inv(cs: CrossSection, pivot, psi_b: float = 12.42, n: int | None = 101, allowance: float = 0.05,
              psi_range=None, simplify_eps: float = 0.001) -> CrossSection:
    """Head-frame envelope of world-frame shape ``cs`` (i.e. rotations by -psi)."""
    rng = psi_range if psi_range is not None else (-psi_b, psi_b)
    return _sweep(cs, pivot, -poses(rng, n), allowance, simplify_eps)
