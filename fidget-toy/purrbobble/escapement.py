"""Escapement geometry, SPEC section 2.3 (frozen core values in params.py).

Star2D is in the WHEEL frame (phi = 0); pallets and fingers are in the HEAD frame (psi = 0), which
coincides with the world/design frame.  Equations:

    pitch p   = 360 / N                                = 45 deg
    gamma     = (m + 1/2) p / 2                        = 56.25 deg
    rho       = (Rt + Rr)/2 + rp + drho                = 15.6142
    D         = rho * tilt / cos(gamma)                = 24.710      (P = (0, D))
    pallet_i  = (+-rho sin gamma, rho cos gamma)       = (+-12.983, 8.675)
    u_i       = pallet_i / rho                         = (+-0.8315, 0.5556)

Star2D: for k = 0..N-1, a0 = p k, polar vertices (Rr, a0 - root_frac p/2), (Rr, a0 + root_frac p/2),
(Rt, a0 + p/2 - tip_frac p/2), (Rt, a0 + p/2 + tip_frac p/2); convex corners rounded r_f (offset -r_f, +r_f),
then concave corners rounded r_f (offset +r_f, -r_f).  Identical to ``esc_opt.star`` of the ideation scripts.
"""
from __future__ import annotations

import math

import numpy as np
from manifold3d import CrossSection

from . import geom2d as g2
from .params import Params

TOL_ESC = 0.002   # chord tolerance for teeth and pallet tips (mm)


def star_polygon_pts(p: Params) -> np.ndarray:
    pts = []
    pitch = 2 * math.pi / p.N
    for k in range(p.N):
        a0 = k * pitch
        for a, r in ((a0 - p.root_frac * pitch / 2, p.Rr), (a0 + p.root_frac * pitch / 2, p.Rr),
                     (a0 + pitch / 2 - p.tip_frac * pitch / 2, p.Rt), (a0 + pitch / 2 + p.tip_frac * pitch / 2, p.Rt)):
            pts.append((r * math.cos(a), r * math.sin(a)))
    return np.array(pts)


def star2d(p: Params) -> CrossSection:
    """Star wheel outline in the wheel frame (root lands centred on 0, 45, ...; tips on 22.5, 67.5, ...)."""
    W = g2.poly(star_polygon_pts(p))
    W = g2.grow(g2.grow(W, -p.r_f, TOL_ESC), p.r_f, TOL_ESC)    # round convex corners
    W = g2.grow(g2.grow(W, p.r_f, TOL_ESC), -p.r_f, TOL_ESC)    # round concave corners
    return g2.check(W, "star2d", n_pieces=1)


def pallet_centres(p: Params) -> tuple:
    """((xL, yL), (xR, yR)) in the head frame."""
    return p.pallets


def pallet_discs2d(p: Params) -> CrossSection:
    """Union of the two round pallet tips (radius rp)."""
    return g2.union([g2.circle(c, p.rp, TOL_ESC) for c in p.pallets])


def finger2d(p: Params, i: int) -> CrossSection:
    """Finger i (0 = left, 1 = right): disc(pallet_i, rp) U trapezoid running outward along u_i for finger_L,
    half-width rp at the pallet centre and rp + finger_L tan(taper) at the outer end."""
    c = np.array(p.pallets[i])
    u = np.array(p.u[i])
    n = np.array([-u[1], u[0]])
    w0 = p.rp
    w1 = p.rp + p.finger_L * math.tan(math.radians(p.finger_taper))
    trap = g2.poly([c + n * w0, c + u * p.finger_L + n * w1, c + u * p.finger_L - n * w1, c - n * w0])
    return g2.union([trap, g2.circle(c, p.rp, TOL_ESC)])


def fingers2d(p: Params) -> CrossSection:
    return g2.union([finger2d(p, 0), finger2d(p, 1)])


def summary(p: Params) -> dict:
    """V1 recompute: every derived escapement value."""
    return dict(pitch=p.pitch, gamma=p.gamma, Rr=p.Rr, rho=p.rho, D=p.D, P=p.P,
                pallets=[list(c) for c in p.pallets], u=[list(v) for v in p.u],
                pallet_arm=p.pallet_arm,
                pallet_span_deg=2 * p.gamma,
                finger_outer_half_width=p.rp + p.finger_L * math.tan(math.radians(p.finger_taper)))
