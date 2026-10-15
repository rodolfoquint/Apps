"""3-D construction of the three bodies (SPEC sections 2.6, 2.7, 3.1, 3.3, 3.4).

Every solid is built in the DESIGN frame (phi = 0, psi = 0), Z up = print direction, back plate on z = 0.
Floating bodies (wheel, head) are built at their nominal Z and then lifted by ``p.z_lift`` (0.05 in the
"loose" variant); their V-grooves stay centred on the frame's V-ridges.

Faceting is conservative: solids are inscribed polygons (vertices on the true surface) and every cut
that creates a clearance (bores, V-grooves, keep-outs, holes) is circumscribed, so an as-meshed clearance is
never smaller than its designed value.

Fillets are approximated by stepped insets (SPEC 2.7 allows this): ``stepped_top``.
"""
from __future__ import annotations

import math
import sys
from typing import Iterable

import numpy as np
from manifold3d import CrossSection, Error, Manifold, OpType

from . import geom2d as g2
from .params import Params
from .skins.base import Feature

EPS = 0.1   # embedding depth for features strictly inside a host (never where side walls coincide)


# ============================================================================== generic helpers
def pinch_vertices(m: Manifold, decimals: int = 6) -> np.ndarray:
    """Positions shared by topologically distinct vertices (zero-volume pinches / touching sheets).

    Such a mesh is a valid manifold, but once written to STL (positions only) the shared positions turn
    into non-manifold edges, so every exported body must have none."""
    v = np.asarray(m.to_mesh().vert_properties, dtype=np.float64)[:, :3]
    _, inv, cnt = np.unique(np.round(v, decimals), axis=0, return_inverse=True, return_counts=True)
    return v[cnt[inv.ravel()] > 1]


def finish(m: Manifold, p: Params, name: str) -> Manifold:
    """Final clean-up of a body: merge sub-micron slivers (Manifold.simplify), then validate."""
    if p.mesh_simplify > 0:
        m = m.simplify(p.mesh_simplify)
    parts = m.decompose()
    if len(parts) > 1:
        # Boolean round-off leaves zero-volume sliver shells, and overlapping cuts can isolate tiny crumbs
        # (e.g. ~1 mm^3 between the crown recess steps and the tongue cut in the deep variant).  A detached
        # crumb would print as loose debris inside the mechanism, so drop anything under min_crumb_mm3.
        keep = [q for q in parts if abs(q.volume()) > p.min_crumb_mm3]
        dropped = [round(abs(q.volume()), 3) for q in parts if abs(q.volume()) <= p.min_crumb_mm3]
        if dropped and any(v > 1e-3 for v in dropped):
            print(f"[{name}] dropped detached crumbs (mm^3): {dropped}", file=sys.stderr)
        if keep and len(keep) < len(parts):
            m = keep[0] if len(keep) == 1 else Manifold.compose(keep)
    return check_solid(m, name)


def check_solid(m: Manifold, name: str, n_bodies: int | None = 1, pinch_ok: bool = False) -> Manifold:
    st = m.status()
    if st != Error.NoError:
        raise AssertionError(f"{name}: manifold status {st}")
    if m.is_empty() or m.volume() <= 0:
        raise AssertionError(f"{name}: empty solid")
    if n_bodies is not None:
        k = len(m.decompose())
        if k != n_bodies:
            raise AssertionError(f"{name}: {k} separate bodies, expected {n_bodies}")
    if not pinch_ok:
        pv = pinch_vertices(m)
        if len(pv):
            raise AssertionError(f"{name}: {len(pv)} pinch vertices (shared positions), e.g. {np.round(pv[:4], 3).tolist()}")
    return m


def union3(items: Iterable[Manifold]) -> Manifold:
    items = [i for i in items if i is not None and not i.is_empty()]
    if not items:
        return Manifold()
    if len(items) == 1:
        return items[0]
    return Manifold.batch_boolean(items, OpType.Add)


def subtract3(a: Manifold, items: Iterable[Manifold]) -> Manifold:
    items = [i for i in items if i is not None and not i.is_empty()]
    if not items:
        return a
    return Manifold.batch_boolean([a] + items, OpType.Subtract)


def extrude(cs: CrossSection, z0: float, z1: float, mode: str = "solid") -> Manifold:
    """Prism z0..z1.  The section is first cleaned of point contacts (geom2d.clean): ``mode="solid"`` separates
    them (material), ``mode="cut"`` merges them (for sections that are subtracted)."""
    if cs is None or cs.is_empty() or z1 <= z0:
        return Manifold()
    cs = g2.clean(cs, mode)
    return cs.extrude(z1 - z0).translate((0.0, 0.0, z0))


def round_insets(r: float, steps: int) -> list[tuple[float, float, float]]:
    """(dz0, dz1, inset) for a quarter-round of radius r approximated by ``steps`` equal Z steps.
    dz measured downward from the top; inset evaluated at mid-height of each step."""
    h = r / steps
    out = []
    for k in range(steps):
        z_lo = r - (k + 1) * h        # distance below the top: from r .. 0
        z_hi = r - k * h
        t = r - 0.5 * (z_lo + z_hi)   # height above the fillet start
        d = r - math.sqrt(max(r * r - t * t, 0.0))
        out.append((z_lo, z_hi, d))
    return out


def stepped_top(cs: CrossSection, z0: float, z1: float, r: float, steps: int,
                protect: CrossSection | None = None, tol: float = g2.TOL_DECO) -> Manifold:
    """extrude(cs, z0, z1) with its top perimeter rounded r by ``steps`` inset steps.
    ``protect`` (optional) is never inset (e.g. where another solid continues upward)."""
    if r <= 0 or steps <= 0:
        return extrude(cs, z0, z1)
    r = min(r, z1 - z0)
    parts = [extrude(cs, z0, z1 - r)]
    for dz_lo, dz_hi, d in round_insets(r, steps):
        sec = g2.grow(cs, -d, tol) if d > 1e-4 else cs
        if protect is not None:
            sec = g2.union([sec, g2.intersect(cs, protect)])
        parts.append(extrude(sec, z1 - dz_hi, z1 - dz_lo))
    return union3(parts)


def chamfer_bottom(cs: CrossSection, z0: float, z1: float, c: float, steps: int = 5,
                   tol: float = g2.TOL_DECO) -> Manifold:
    """extrude(cs, z0, z1) with a c x 45 deg bottom-edge chamfer (stepped)."""
    h = c / steps
    parts = []
    for k in range(steps):
        d = c - (k + 0.5) * h
        parts.append(extrude(g2.grow(cs, -d, tol), z0 + k * h, z0 + (k + 1) * h))
    parts.append(extrude(cs, z0 + c, z1))
    return union3(parts)


def revolve_rz(pts_rz, n: int, hole: bool = False, center=(0.0, 0.0)) -> Manifold:
    """Revolve an (r, z) profile polygon about the vertical axis through ``center``.
    hole=True circumscribes (r / cos(pi/n)) so the facets are tangent to the true surface."""
    a = np.asarray(pts_rz, float).copy()
    if hole:
        a[:, 0] = a[:, 0] / math.cos(math.pi / n)
    cs = g2.poly(a)
    m = Manifold.revolve(cs, n)
    if center[0] or center[1]:
        m = m.translate((float(center[0]), float(center[1]), 0.0))
    return m


def arc_pts(c, r, a0_deg, a1_deg, n):
    t = np.radians(np.linspace(a0_deg, a1_deg, n))
    return [(c[0] + r * math.cos(x), c[1] + r * math.sin(x)) for x in t]


# ============================================================================== posts, bores
def post_profile(p: Params) -> list:
    r, f = p.post_r, p.post_root_fillet
    z0, z1, c = p.post_z0, p.post_z1, p.post_chamfer
    ra, zr = p.ridge_apex_r, p.ridge_z
    h = ra - r
    pts = [(0.0, z0 - 0.6), (r + f, z0 - 0.6), (r + f, z0)]
    # concave root fillet: centre (r+f, z0+f)
    pts += [(r + f - f * math.sin(t), z0 + f - f * math.cos(t)) for t in np.radians(np.linspace(10, 90, 9))]
    pts += [(r, zr - h), (ra, zr), (r, zr + h), (r, z1 - c), (r - c, z1), (0.0, z1)]
    return pts


def post(p: Params, center) -> Manifold:
    n = g2.nseg(p.post_r + p.post_root_fillet, g2.TOL_FUNC, mult=8)
    return revolve_rz(post_profile(p), n, hole=False, center=center)


def bore_profile(p: Params, z_lift: float) -> list:
    """Cut profile in the floating body's LOCAL z (body built at nominal z, lifted afterwards)."""
    rb, c = p.bore_r, p.bore_chamfer
    z0 = p.z_band0
    zr = p.ridge_z - z_lift                    # groove apex stays on the frame ridge
    rg = p.groove_apex_r
    dz = rg - rb
    return [(0.0, z0 - 1.0), (rb + c + 1.0, z0 - 1.0), (rb + c, z0), (rb, z0 + c),
            (rb, zr - dz), (rg, zr), (rb, zr + dz), (rb, p.bore_roof_z), (0.0, p.bore_roof_z)]


def bore(p: Params, center) -> Manifold:
    n = g2.nseg(p.groove_apex_r + 1, g2.TOL_FUNC, mult=8)
    return revolve_rz(bore_profile(p, p.z_lift), n, hole=True, center=center)


# ============================================================================== wheel
def umbrella_profile(p: Params) -> list:
    R, f = p.R_u, p.umb_fillet
    z_top = p.z_umb_top
    pts = [(0.0, p.z_teeth1), (p.umb_r0, p.z_teeth1), (R, p.umb_rim_z0), (R, p.umb_rim_z1)]
    pts += arc_pts((R - f, p.umb_rim_z1), f, 0, 90, 13)[1:-1]
    pts += [(R - f, z_top), (0.0, z_top)]
    return pts


def knob_profile(p: Params) -> list:
    a = p.knob_d / 2
    fr, ft = p.knob_root_fillet, p.knob_top_fillet
    z0, z1 = p.z_umb_top, p.z_knob_top
    pts = [(0.0, z0 - 0.4), (a + fr, z0 - 0.4), (a + fr, z0)]
    pts += [(a + fr - fr * math.sin(t), z0 + fr - fr * math.cos(t)) for t in np.radians(np.linspace(10, 90, 7))]
    pts += arc_pts((a - ft, z1 - ft), ft, 0, 90, 17)
    pts += [(0.0, z1)]
    return pts


def well_profile(p: Params, n_arc: int = 24) -> list:
    """(r, z) cut profile of the recessed finger well (about its own axis): spherical dish of opening diameter
    well_d and depth well_depth below the ball top, rim rounded r well_rim_r (tangent to dish and top)."""
    a, h, f = p.well_d / 2, p.well_depth, p.well_rim_r
    zt = p.z_umb_top
    Rs = (a * a + h * h) / (2 * h)
    zs = zt - h + Rs                                   # sphere centre
    zcf = zt - f
    rc = math.sqrt((Rs + f) ** 2 - (zs - zcf) ** 2)   # fillet centre radius (fillet externally tangent to sphere)
    th_t = math.atan2(zs - zcf, -rc)                   # tangent point direction seen from the fillet centre
    al_t = math.atan2(rc, zs - zcf)                    # same point seen from the sphere centre (angle from -Z)
    pts = [(0.0, zt - h)]
    for t in np.linspace(0.0, al_t, n_arc)[1:]:
        pts.append((Rs * math.sin(t), zs - Rs * math.cos(t)))
    for t in np.linspace(th_t, math.pi / 2, max(4, n_arc // 2))[1:]:
        pts.append((rc + f * math.cos(t), zcf + f * math.sin(t)))
    pts += [(rc, zt + 1.0), (0.0, zt + 1.0)]
    return pts


def wheel_relief_cut(p: Params, relief2d: CrossSection | None) -> tuple[Manifold, CrossSection]:
    if relief2d is None or relief2d.is_empty():
        return Manifold(), CrossSection()
    clip = g2.difference(g2.circle((0, 0), p.relief_r_max, 0.01),
                         g2.circle((p.r_k, 0.0), p.relief_knob_clear, 0.01))
    rel = g2.drop_small(g2.intersect(relief2d, clip), 0.2)
    z = p.z_umb_top
    return extrude(rel, z - p.relief_depth, z + 1.0, mode="cut"), rel


def build_wheel(p: Params, S, skin) -> tuple[Manifold, dict]:
    nU = g2.nseg(p.R_u, g2.TOL_FUNC, mult=8)
    teeth = extrude(S["star2d"], p.z_band0, p.z_teeth1)
    umb = revolve_rz(umbrella_profile(p), nU)
    cuts = [bore(p, (0.0, 0.0))]
    if p.wheel_drive == "knob":
        nK = g2.nseg(p.knob_d / 2 + 1, g2.TOL_DECO, mult=8)
        # the knob foot (r 6.0 about (r_k, 0)) is tangent to the rim-fillet start circle (r 17.0) at (17, 0): turn
        # the knob mesh by half a segment so that point is a facet midpoint (strictly inside), not a shared vertex
        knob = revolve_rz(knob_profile(p), nK).rotate((0.0, 0.0, 180.0 / nK)).translate((p.r_k, 0.0, 0.0))
        body = union3([teeth, umb, knob])
    else:
        body = union3([teeth, umb])
        nW = g2.nseg(p.well_d / 2 + p.well_rim_r, g2.TOL_DECO, mult=8)
        cuts.append(revolve_rz(well_profile(p), nW, hole=True).rotate((0.0, 0.0, 180.0 / nW))
                    .translate((p.r_k, 0.0, 0.0)))
    relief_cut, rel2d = wheel_relief_cut(p, skin.wheel_relief2d(p))
    wheel = subtract3(body, cuts + [relief_cut])
    wheel = wheel.translate((0.0, 0.0, p.z_lift)) if p.z_lift else wheel
    return finish(wheel, p, "wheel"), {"relief2d": rel2d}


# ============================================================================== head
def _dome(f: Feature, z_base: float, n_arc: int = 10) -> Manifold:
    a, h = f.radius, f.depth
    Rs = (a * a + h * h) / (2 * h)
    zc = z_base + h - Rs
    # the sphere is continued 0.03 mm past the base circle so it meets the flat top transversally (a base ring lying
    # exactly in the top plane can leave coincident vertices after the union)
    a1 = min(a + 0.03, 0.999 * Rs)
    t = np.linspace(math.asin(a1 / Rs), 0.0, n_arc)
    z1 = zc + Rs * math.cos(t[0])
    pts = [(0.0, z_base - EPS), (a1, z_base - EPS), (a1, z1)][:2 + (z1 > z_base - EPS + 1e-6)] + \
        [(Rs * math.sin(x), zc + Rs * math.cos(x)) for x in t]
    return revolve_rz(pts, g2.nseg(a, g2.TOL_DECO, mult=4), center=f.center)


def _dome_height(f: Feature, x: float, y: float) -> float:
    a, h = f.radius, f.depth
    Rs = (a * a + h * h) / (2 * h)
    d2 = (x - f.center[0]) ** 2 + (y - f.center[1]) ** 2
    return h - Rs + math.sqrt(max(Rs * Rs - d2, 0.0))


def apply_features(base: Manifold, feats: list[Feature], z_surf: float, protect_raise_round: float = 0.0
                   ) -> Manifold:
    """Apply raise/deboss/dome/dimple features to a flat top face at z_surf."""
    adds, cuts = [], []
    by_name = {f.name: f for f in feats}
    for f in feats:
        if f.mode == "raise":
            if protect_raise_round > 0:
                adds.append(stepped_top(f.shape, z_surf - EPS, z_surf + f.depth, min(protect_raise_round, f.depth), 2))
            else:
                adds.append(extrude(f.shape, z_surf - EPS, z_surf + f.depth))
        elif f.mode == "dome":
            adds.append(_dome(f, z_surf))
    for f in feats:
        if f.mode == "deboss":
            cuts.append(extrude(f.shape, z_surf - f.depth, z_surf + 5.0, mode="cut"))
        elif f.mode == "dimple":
            host = by_name.get(f.on)
            zs = z_surf + (_dome_height(host, *f.center) if host is not None and host.mode == "dome"
                           else (host.depth if host is not None else 0.0))
            a, dep = f.radius, f.depth
            rd = (a * a + dep * dep) / (2 * dep)
            cuts.append(Manifold.sphere(rd, g2.nseg(rd, g2.TOL_DECO, mult=4)).translate(
                (f.center[0], f.center[1], zs + rd - dep)))
        elif f.mode not in ("raise", "dome"):
            raise ValueError(f"unknown feature mode {f.mode}")
    out = union3([base] + adds)
    return subtract3(out, cuts)


def check_face_features(p: Params, S, feats: list[Feature], margin: float = 3.0) -> None:
    """SPEC 4.3: face features stay >= 3 mm inside FaceUp2D's edge (unless flagged edge_ok); raised 0.6,
    debossed 0.3-0.5."""
    inner = g2.grow(S["faceup2d"], -margin, 0.01)
    edge = g2.grow(S["faceup2d"], -p.face_top_round - 0.05, 0.01)     # never on the rounded rim
    for f in feats:
        if f.shape is None:
            continue
        lim = edge if f.edge_ok else inner
        out = g2.difference(f.shape, lim).area()
        if out > 1e-3 and f.edge_ok and f.mode == "deboss":
            # edge features (e.g. inner ears) follow the face outline; the core may have notched that outline
            # (crown notch) after the skin drew them: clip them to the flat top inside the rim instead of failing
            f.shape = g2.drop_small(g2.opening(g2.intersect(f.shape, g2.grow(lim, -0.02, 0.01)), 0.6, 0.01), 0.3)
            out = g2.difference(f.shape, lim).area() if not f.shape.is_empty() else 0.0
        if out > 1e-3:
            raise AssertionError(f"face feature {f.name}: {out:.3f} mm^2 closer than {margin} mm to the face edge")
        if f.mode in ("raise", "dome") and abs(f.depth - 0.6) > 1e-9:
            raise AssertionError(f"face feature {f.name}: raised features are 0.6 tall (got {f.depth})")
        if f.mode in ("deboss", "dimple") and not (0.3 - 1e-9 <= f.depth <= 0.5 + 1e-9):
            raise AssertionError(f"face feature {f.name}: deboss depth must be 0.3-0.5 (got {f.depth})")


def build_head(p: Params, S, skin) -> tuple[Manifold, dict]:
    """HEAD = extrude(HeadBand2D, 3.0-7.4) U extrude(FaceMid2D, 7.4-11.4) U extrude(FaceUp2D, 11.4-15.4, top r1.5)
    U face features - hub bore.

    Built as  band U (FaceUp block 7.4-15.4) - (RoofSweepInv slot 7.4-11.4)  which is the same solid but
    avoids coincident side walls (FaceMid and FaceUp share the face outline).  A hub collar disc(P, 6.90) is
    added for z 7.4-8.4 because the kitty face cannot contain disc(P, 7.5) (see core2d.check_skin): it walls
    the blind bore and stays 0.6 inside the roof hole (r 7.5)."""
    eps = p.eps_stack
    groove = S.get("band_groove2d")
    if groove is not None and not groove.is_empty():
        # crown mouth guard: the band top is lowered to z_groove in the annulus under the frame's skirt
        # (head features that lie under frame parts are lowered by z_lift so that, after the loose variant's lift,
        # their gap to the frame stays the designed 0.40)
        # groove floor rib_h below the rib tops (z_groove); one skid rib along the groove carries the skirt float
        zg = p.z_groove - p.z_lift
        zf = zg - p.rib_h
        parts_b = [extrude(S["headband2d"], p.z_band0, zf),
                   extrude(g2.grow(g2.difference(S["headband2d"], groove), -eps, 0.001), zf, p.z_band1)]
        grib = S.get("groove_rib2d")
        if grib is not None and not grib.is_empty():
            parts_b.append(extrude(grib, zf - 0.05, zg))
        band = union3(parts_b)
        block_eps = 2 * eps
    else:
        band = extrude(S["headband2d"], p.z_band0, p.z_band1)
        block_eps = eps
    ribs_band = S.get("ribs_band2d")
    if ribs_band is not None and not ribs_band.is_empty():
        band = union3([band, extrude(ribs_band, p.z_band1, p.z_band1 + p.rib_h - p.z_lift)])
    # pallet fingers lowered under the umbrella plate (only the fingers reach into WheelEx2D)
    band = band - extrude(g2.grow(S["wheelex2d"], 0.05, 0.005), p.z_pallet_top, p.z_band1 + p.rib_h + 0.1, mode="cut")
    block = stepped_top(g2.grow(S["faceup2d"], -block_eps, 0.001), p.z_band1, p.z_front1, p.face_top_round,
                        p.face_top_steps)
    slot = extrude(S["slot2d"], p.z_band1, p.z_front0, mode="cut")
    collar2d = g2.circle(p.P, p.R_hub_cut - p.swept_gap - 0.05, g2.TOL_FUNC)
    collar = extrude(collar2d, p.z_band1, p.z_roof0)
    parts = [band, block - slot, collar]
    ribs_front = S.get("ribs_front2d")
    if ribs_front is not None and not ribs_front.is_empty():
        # hanging from the front layer down to gap_rib above the crown roof top
        parts.append(extrude(ribs_front, p.z_roof1 + p.gap_rib, p.z_front0 + 0.05))
    head = union3(parts)
    feats = skin.face_features(p.C_h, p)
    check_face_features(p, S, feats)
    head = apply_features(head, feats, p.z_front1, protect_raise_round=0.25)
    pockets = skin.head_pockets2d(p)
    cuts = [bore(p, p.P)]
    if pockets is not None and not pockets.is_empty():
        cuts.append(extrude(pockets, p.z_band1 + 2.0, p.z_front1 - 2.0, mode="cut"))
    head = subtract3(head, cuts)
    head = head.translate((0.0, 0.0, p.z_lift)) if p.z_lift else head
    return finish(head, p, "head"), {"features": feats, "collar2d": collar2d}


# ============================================================================== frame
def keepout_u(p: Params) -> Manifold:
    return revolve_rz(p.keepout, g2.nseg(18.6, g2.TOL_FUNC, mult=8), hole=True)


def paw_profile(p: Params) -> list:
    c = p.paw_lip_c
    return [(p.paw_lip_r, c - p.paw_lip_r), (p.paw_wall_r, c - p.paw_wall_r), (p.paw_wall_r, p.paw_z0 - 1.0),
            (60.0, p.paw_z0 - 1.0), (60.0, p.paw_z1 + 1.0), (p.paw_lip_r, p.paw_z1 + 1.0)]


def build_paw(p: Params, plan2d: CrossSection, feats: list[Feature]) -> Manifold:
    nP = g2.nseg(p.paw_lip_r, g2.TOL_FUNC, mult=8)
    ring = revolve_rz(paw_profile(p), nP, hole=True)
    block = stepped_top(plan2d, p.paw_z0, p.paw_z1, p.frame_top_fillet, p.frame_top_steps)
    paw = ring ^ block
    return apply_features(paw, feats, p.paw_z1)


def build_body_stack(p: Params, S) -> tuple[Manifold, CrossSection]:
    """Fill (2.0-8.4) + roof (8.4-10.4) of the frame, before the keep-out cut.

    Stacked slabs: fill2d (2.0-8.4) | top2d = fill U roof (8.4-9.4) | top2d n clip_k (3 inset steps, 9.4-10.4:
    exterior top edge rounded r 1.0, not under paws / decor).  At every interface one section lies strictly
    inside the other (the covered one is shrunk by eps_stack = 2 um): shared outlines would otherwise be
    nearly-coincident walls whose branch points leave pinch vertices in the boolean result.
    Returns (solid, top-face section at z 10.4)."""
    r, nst = p.frame_top_fillet, p.frame_top_steps
    eps = p.eps_stack
    protect = g2.grow(g2.union([S["paw_plan_R"], S["paw_plan_L"], S["decor2d"]]), 0.5, 0.02)
    if S.get("crown_skirt2d") is not None and "crown" in S:
        # (fix round 1) no top-edge round along the crown arc: there the edge faces the head's face mid layer across the
        # constant 0.5 slot; an inset top edge would leave a varying 0.5-1.5 gap at the ends of the head's concentric
        # edges (V12).  A square 90 deg edge passes V12.sharp_points (ball fraction 0.25).
        Rb = S["crown"]["R_b"]
        th = S["crown"]["th_R"]
        arc = g2.intersect(g2.difference(g2.circle(p.P, Rb + 1.0, 0.01), g2.circle(p.P, Rb - 1.6, 0.01)),
                           g2.wedge(th + 6.0, 174.0 - th, 300.0, c=p.P))
        protect = g2.union([protect, arc])
    T = S.get("fill_tongues2d")
    Tg = g2.grow(T, 0.05, 0.005) if T is not None and not T.is_empty() else CrossSection()
    top = g2.clean(g2.difference(S["top2d"], Tg), "cut") if not Tg.is_empty() else S["top2d"]
    # fill slabs from the plate up to the roof.  Fix round 1: funnel-seat tongues stop at z_tongue (no knife edge
    # along the 45 deg keep-out); crown mouth guard: fill recessed under the skirt between the sill (z bp + rib_h)
    # and the skirt underside, skirt added above.  Consecutive slabs are strictly nested (eps steps) so that no
    # two slabs share a wall.
    F = S["fill2d"]
    skirt = S.get("crown_skirt2d")
    levels = [(p.z_bp, F)]
    if S.get("crown_fill_levels"):
        # recessed fill under the skirt, closing at 45 deg (core2d.crown_fill_levels), then fill + skirt
        levels += list(S["crown_fill_levels"])
        F = g2.union([F, skirt])
        levels.append((p.z_skirt, F))
    wider = set()
    if not Tg.is_empty():
        # the slab under the roof is kept eps WIDER than the one below it (except at the tongue cut): an eps-narrower
        # slab would leave a 2 um ledge 0.2 under the roof bridge (a sub-layer air gap under a bridge, V9)
        wider.add(len(levels))
        levels.append((p.z_tongue, g2.difference(F, Tg)))
    levels.append((p.z_roof0, None))
    shrink = []        # eps multiple per slab so that each pair of neighbours is strictly nested
    for k, (z0, sec) in enumerate(levels[:-1]):
        if k == 0:
            shrink.append(1)
            continue
        prev = levels[k - 1][1]
        grows = not g2.difference(sec, prev).is_empty() and g2.difference(sec, prev).area() > 1e-6
        shrink.append(shrink[-1] - 1 if (grows or k in wider) else shrink[-1] + 1)
    base = 1 - min(shrink)
    slabs = []
    for k, (z0, sec) in enumerate(levels[:-1]):
        z1 = levels[k + 1][0]
        e = (shrink[k] + base) * eps
        slabs.append(extrude(g2.grow(sec, -e, 0.001), z0, z1))
    # the topmost fill slab must lie strictly inside top2d (unshrunk): guaranteed since e >= eps
    slabs.append(extrude(top, p.z_roof0, p.z_roof1 - r, mode="cut"))
    sec = top
    for dz_lo, dz_hi, d in round_insets(r, nst):
        sec = g2.clean(g2.grow(g2.intersect(sec, g2.union([g2.grow(S["body2d"], -d, 0.01), protect])), -eps, 0.001))
        slabs.append(extrude(sec, p.z_roof1 - dz_hi, p.z_roof1 - dz_lo))
    return union3(slabs), sec


def build_frame(p: Params, S, skin) -> tuple[Manifold, dict]:
    info = {}
    # back plate with bottom chamfer and skin grooves (stitch)
    plate = chamfer_bottom(S["backdrop2d"], 0.0, p.z_bp, p.bp_chamfer, steps=p.bp_chamfer_steps)
    plate_feats = skin.backdrop_features(p, S["backdrop2d"], S["body2d"], S["swept_faceup2d"])
    plate = apply_features(plate, plate_feats, p.z_bp)
    info["plate_features"] = plate_feats

    # body: fill + roof minus the umbrella keep-out, exterior top edge rounded r 1.0 (stepped).
    ko = keepout_u(p)
    body, top_face = build_body_stack(p, S)
    body = body - ko
    tongue_cut = Manifold()
    T = S.get("fill_tongues2d")
    if T is not None and not T.is_empty():
        tongue_cut = extrude(g2.grow(T, 0.05, 0.005), p.z_tongue, p.z_roof1 + p.rib_h + 0.05, mode="cut")
    on_top = g2.grow(top_face, -p.eps_stack, 0.001)   # footprint allowed for anything standing on the body top
    info["top_face2d"] = top_face
    ribs_roof = subtract3(extrude(g2.intersect(S["ribs_roof2d"], on_top), p.z_roof1, p.z_roof1 + p.rib_h), [ko, tongue_cut])
    ribs_back = extrude(S["ribs_back2d"], p.z_bp, p.z_bp + p.rib_h)
    posts = [post(p, (0.0, 0.0)), post(p, p.P)]

    # paws (their footprint on the roof must lie inside the body top face)
    paws = []
    style = skin.paw_style(p)
    lip_zone = g2.circle((0.0, 0.0), p.paw_wall_r + 0.3, 0.01)
    for side in ("R", "L"):
        plan = S[f"paw_plan_{side}"]
        plan = g2.intersect(plan, g2.union([on_top, g2.intersect(lip_zone, plan)]))
        plan = g2.opening(plan, 2 * p.corner_r, 0.01)          # exterior plan corners r >= 1.5
        paws.append(build_paw(p, g2.clean(plan, "solid"), style[side].features))

    # body decor (raised 1.6 on the roof, rounded top edge), kept out of the umbrella keep-out
    decor = Manifold()
    if not S["decor2d"].is_empty():
        decor = stepped_top(g2.intersect(S["decor2d"], on_top), p.z_roof1, p.z_decor1, 0.8, 3) - ko
        decor = apply_features(decor, skin.body_decor_features(p), p.z_decor1)

    frame = union3([plate, body, ribs_roof, ribs_back, decor] + posts + paws)
    return finish(frame, p, "frame"), info
