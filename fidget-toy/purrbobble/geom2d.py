"""Small 2-D helpers on manifold3d.CrossSection (Clipper2) used by every module.

All functions return new CrossSections; nothing is mutated.  Circles are polygons with their
vertices ON the true circle (inscribed) unless ``hole=True`` is passed, in which case the polygon
is circumscribed (its edges are tangent to the true circle).  Use ``hole=True`` for any disc that
is subtracted to make a clearance so that the as-meshed clearance is never smaller than designed.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
from manifold3d import CrossSection, JoinType, OpType

# Default chord-error targets (mm).  Functional curves (pallets, teeth, journals) use TOL_FUNC.
TOL_FUNC = 0.005
TOL_DECO = 0.03


def nseg(r: float, tol: float = TOL_FUNC, min_n: int = 12, mult: int = 4) -> int:
    """Number of segments per full circle so that the chord sagitta r(1-cos(pi/n)) <= tol."""
    r = abs(float(r))
    if r <= tol:
        return min_n
    n = math.ceil(math.pi / math.acos(max(-1.0, 1.0 - tol / r)))
    n = max(min_n, n)
    return int(math.ceil(n / mult) * mult)


def poly(pts) -> CrossSection:
    """CrossSection from one (N,2) point list (orientation fixed automatically)."""
    a = np.asarray(pts, dtype=float)
    if _signed_area(a) < 0:
        a = a[::-1]
    return CrossSection([a])


def _signed_area(a: np.ndarray) -> float:
    x, y = a[:, 0], a[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def circle(c=(0.0, 0.0), r: float = 1.0, tol: float = TOL_FUNC, n: int | None = None,
           hole: bool = False) -> CrossSection:
    n = n or nseg(r, tol)
    rr = r / math.cos(math.pi / n) if hole else r
    return CrossSection.circle(rr, n).translate(tuple(map(float, c)))


def ellipse(c, a: float, b: float, angle_deg: float = 0.0, tol: float = TOL_DECO) -> CrossSection:
    n = nseg(max(a, b), tol)
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    pts = np.c_[a * np.cos(t), b * np.sin(t)]
    return poly(pts).rotate(angle_deg).translate(tuple(map(float, c)))


def stadium(a, b, width: float, tol: float = TOL_DECO) -> CrossSection:
    """Segment a-b grown by width/2 with round caps."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    r = width / 2.0
    d = b - a
    L = float(np.hypot(*d))
    if L < 1e-9:
        return circle(a, r, tol)
    n = nseg(r, tol)
    # build directly: rectangle + two discs (union)
    nrm = np.array([-d[1], d[0]]) / L * r
    rect = poly([a + nrm, b + nrm, b - nrm, a - nrm])
    return union([rect, circle(a, r, n=n), circle(b, r, n=n)])


def polyline_stadium(pts: Sequence, width: float, tol: float = TOL_DECO) -> CrossSection:
    return union([stadium(pts[i], pts[i + 1], width, tol) for i in range(len(pts) - 1)])


def sector(r_in: float, r_out: float, a0_deg: float, a1_deg: float, c=(0.0, 0.0), tol: float = TOL_DECO,
           hole_in: bool = False) -> CrossSection:
    """Annular sector between angles a0..a1 (deg, CCW from +X) about c."""
    n_out = max(4, int(math.ceil(nseg(r_out, tol) * (a1_deg - a0_deg) / 360.0)))
    t = np.radians(np.linspace(a0_deg, a1_deg, n_out + 1))
    outer = np.c_[r_out * np.cos(t), r_out * np.sin(t)]
    if r_in > 0:
        n_in = max(4, int(math.ceil(nseg(r_in, tol) * (a1_deg - a0_deg) / 360.0)))
        ti = np.radians(np.linspace(a1_deg, a0_deg, n_in + 1))
        half = math.radians((a1_deg - a0_deg) / (2.0 * n_in))
        ri = r_in / math.cos(half) if hole_in else r_in
        inner = np.c_[ri * np.cos(ti), ri * np.sin(ti)]
    else:
        inner = np.zeros((1, 2))
    return poly(np.vstack([outer, inner])).translate(tuple(map(float, c)))


def wedge(a0_deg: float, a1_deg: float, R: float = 200.0, c=(0.0, 0.0)) -> CrossSection:
    """Infinite-ish angular wedge (polygonal; only its two straight edges matter)."""
    t = np.radians(np.linspace(a0_deg, a1_deg, max(3, int(abs(a1_deg - a0_deg) / 5) + 2)))
    pts = np.vstack([[0.0, 0.0], np.c_[R * np.cos(t), R * np.sin(t)]])
    return poly(pts).translate(tuple(map(float, c)))


def rot_about(cs: CrossSection, deg: float, pivot=(0.0, 0.0)) -> CrossSection:
    px, py = map(float, pivot)
    if px == 0.0 and py == 0.0:
        return cs.rotate(deg)
    return cs.translate((-px, -py)).rotate(deg).translate((px, py))


def rot_pt(pt, deg: float, pivot=(0.0, 0.0)) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    x, y = pt[0] - pivot[0], pt[1] - pivot[1]
    return np.array([pivot[0] + c * x - s * y, pivot[1] + s * x + c * y])


def union(items: Iterable[CrossSection]) -> CrossSection:
    items = [i for i in items if i is not None and not i.is_empty()]
    if not items:
        return CrossSection()
    if len(items) == 1:
        return items[0]
    return CrossSection.batch_boolean(items, OpType.Add)


def difference(a: CrossSection, *bs: CrossSection) -> CrossSection:
    bs = [b for b in bs if b is not None and not b.is_empty()]
    if not bs:
        return a
    return CrossSection.batch_boolean([a] + bs, OpType.Subtract)


def intersect(a: CrossSection, *bs: CrossSection) -> CrossSection:
    out = a
    for b in bs:
        out = CrossSection.batch_boolean([out, b], OpType.Intersect)
    return out


def grow(cs: CrossSection, d: float, tol: float = TOL_FUNC) -> CrossSection:
    """Round-join offset (+ grows, - shrinks).  Segment count set from |d| and tol."""
    if d == 0 or cs.is_empty():
        return cs
    return cs.offset(d, JoinType.Round, 2.0, nseg(abs(d), tol))


def opening(cs: CrossSection, t: float, tol: float = TOL_DECO) -> CrossSection:
    """open_t(X) = (X (-) t/2) (+) t/2 : removes parts thinner than t, rounds convex corners r t/2."""
    return grow(grow(cs, -t / 2.0, tol), t / 2.0, tol)


def closing(cs: CrossSection, r: float, tol: float = TOL_DECO) -> CrossSection:
    """(X (+) r) (-) r : fills notches narrower than 2r, rounds concave corners r."""
    return grow(grow(cs, r, tol), -r, tol)


def round_r(cs: CrossSection, r: float, r_convex: float = 1.5, tol: float = TOL_DECO) -> CrossSection:
    """round_rN of the SPEC: concave corners rounded r (closing), convex corners rounded r_convex (opening).

    A pure opening with radius r would delete legitimate thin skin decor (e.g. the 5 mm kitty tail inside
    Body2D), so the convex side uses the exterior-corner rule r >= 1.5 (SPEC 2.7)."""
    out = closing(cs, r, tol)
    if r_convex > 0:
        out = opening(out, 2 * r_convex, tol)
    return out


def pieces(cs: CrossSection, min_area: float = 0.0) -> list[CrossSection]:
    return [q for q in cs.decompose() if q.area() > min_area]


def drop_small(cs: CrossSection, min_area: float) -> CrossSection:
    return union(pieces(cs, min_area))


def simplify(cs: CrossSection, eps: float = 0.002) -> CrossSection:
    return cs.simplify(eps)


def touch_points(cs: CrossSection, tol: float = 2e-5) -> np.ndarray:
    """Points where the boundary touches itself: a vertex lying (within ``tol``) on a non-adjacent edge or
    vertex of any contour.  Extruded, such a point becomes a pinch edge (non-manifold once written to STL)."""
    if cs.is_empty():
        return np.zeros((0, 2))
    conts = [np.asarray(c, dtype=np.float64) for c in cs.to_polygons()]
    # drop near-duplicate consecutive vertices (sub-tol edges are not contacts)
    conts2 = []
    for c in conts:
        keep = np.r_[True, np.hypot(*np.diff(c, axis=0).T) > tol]
        c = c[keep]
        if len(c) > 2 and np.hypot(*(c[0] - c[-1])) <= tol:
            c = c[:-1]
        if len(c) >= 3:
            conts2.append(c)
    conts = conts2
    if not conts:
        return np.zeros((0, 2))
    V, A, B, owner_v, owner_e, idx_v, idx_e = [], [], [], [], [], [], []
    for ci, c in enumerate(conts):
        n = len(c)
        V.append(c)
        A.append(c)
        B.append(np.roll(c, -1, axis=0))
        owner_v.append(np.full(n, ci))
        owner_e.append(np.full(n, ci))
        idx_v.append(np.arange(n))
        idx_e.append(np.arange(n))
    V, A, B = np.vstack(V), np.vstack(A), np.vstack(B)
    ov, oe = np.concatenate(owner_v), np.concatenate(owner_e)
    iv, ie = np.concatenate(idx_v), np.concatenate(idx_e)
    nlen = {ci: len(c) for ci, c in enumerate(conts)}
    D = B - A
    L2 = np.maximum((D * D).sum(1), 1e-30)
    # bounding-box prefilter per edge
    lo = np.minimum(A, B) - tol
    hi = np.maximum(A, B) + tol
    hits = []
    chunk = 256
    for s0 in range(0, len(V), chunk):
        v = V[s0:s0 + chunk]
        inb = ((v[:, None, 0] >= lo[None, :, 0]) & (v[:, None, 0] <= hi[None, :, 0]) &
               (v[:, None, 1] >= lo[None, :, 1]) & (v[:, None, 1] <= hi[None, :, 1]))
        vi, ei = np.nonzero(inb)
        if len(vi) == 0:
            continue
        P = v[vi]
        t = np.clip(((P - A[ei]) * D[ei]).sum(1) / L2[ei], 0.0, 1.0)
        d = np.hypot(*(A[ei] + t[:, None] * D[ei] - P).T)
        gv = vi + s0
        same = ov[gv] == oe[ei]
        n_c = np.array([nlen[c] for c in ov[gv]])
        adjacent = same & ((ie[ei] == iv[gv]) | (ie[ei] == (iv[gv] - 1) % n_c))
        bad = (d < tol) & ~adjacent
        if bad.any():
            hits.append(V[gv[bad]])
    if not hits:
        return np.zeros((0, 2))
    return np.unique(np.round(np.vstack(hits), 6), axis=0)


def clean(cs: CrossSection, mode: str = "solid", delta: float = 0.002, r: float = 0.005,
          max_iter: int = 4) -> CrossSection:
    """Remove point contacts / zero-width spikes so an extrusion has no pinch edges.

    ``mode="solid"``: opening by ``delta`` (result is INSIDE the input - use for material).
    ``mode="cut"``  : closing by ``delta`` (result CONTAINS the input - use for voids, and for an upper slab that
    must cover the slab below it).  Remaining touch points (smooth tangencies) are then separated (solid) or
    merged (cut) with tiny discs of radius ``r``.  Raises if any touch point survives."""
    if cs.is_empty():
        return cs
    cs = cs.simplify(1e-6)            # drops near-duplicate / collinear vertices (< 1 um)
    if not len(touch_points(cs)):
        return cs
    out = (opening(cs, 2 * delta, 0.001) if mode == "solid" else closing(cs, delta, 0.001)).simplify(1e-6)
    if len(touch_points(out)):
        # zero-width slits between pieces survive an opening: close them first
        out = (opening(closing(out, delta, 0.001), 2 * delta, 0.001) if mode == "solid"
               else closing(out, 4 * delta, 0.001)).simplify(1e-6)
    for _ in range(max_iter):
        tp = touch_points(out)
        if len(tp) == 0:
            return out
        discs = union([CrossSection.circle(r, 8).translate((float(x), float(y))) for x, y in tp])
        out = (difference(out, discs) if mode == "solid" else union([out, discs])).simplify(1e-6)
    if len(touch_points(out)):
        raise AssertionError(f"clean(): could not remove touch points {touch_points(out)[:3]}")
    return out


def check(cs: CrossSection, name: str, n_pieces: int | None = None, min_area: float = 1e-6) -> CrossSection:
    """Fail loudly if a section is empty or (optionally) has the wrong number of pieces."""
    if cs.is_empty() or cs.area() < min_area:
        raise AssertionError(f"section {name} is empty")
    if n_pieces is not None:
        k = len(pieces(cs, 1e-3))
        if k != n_pieces:
            raise AssertionError(f"section {name} has {k} pieces, expected {n_pieces}")
    return cs


def min_distance_polys(a: CrossSection, b: CrossSection) -> float:
    """Exact polygon-polygon distance (analysis helper; uses shapely)."""
    return to_shapely(a).distance(to_shapely(b))


def to_shapely(cs: CrossSection):
    """Convert to a shapely (Multi)Polygon - for analysis only."""
    import shapely
    from shapely.geometry import Polygon
    polys = []
    for q in cs.decompose():
        cont = q.to_polygons()
        rings = [np.asarray(c) for c in cont]
        areas = [_signed_area(r) for r in rings]
        i0 = int(np.argmax(areas))
        holes = [rings[i] for i in range(len(rings)) if i != i0]
        polys.append(Polygon(rings[i0], holes))
    if not polys:
        return Polygon()
    return shapely.union_all(polys)


def max_inscribed_width(cs: CrossSection, hi: float = 40.0, iters: int = 24) -> float:
    """2 x radius of the largest inscribed disc (bisection on inward offsets)."""
    lo = 0.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if grow(cs, -mid, 0.05).is_empty():
            hi = mid
        else:
            lo = mid
    return 2 * lo
