"""All 2-D sections of SPEC section 2.5 / 3.4, computed with manifold3d.CrossSection (Clipper2).

Notation (SPEC 2.5): (+)/(-) offset with round joins; Swept/SweptInv see sweep.py; open_t see geom2d.opening.

Head frame:  Hub2D, Leg2D_i, Face2D (skin), Finger2D_i, WheelEx2D, BallEx2D, HeadBand2D, FaceUp2D
World frame: Exposed2D, Body2D, Cavity2D, StopPads2D, Fill2D, Roof2D, RoofSweepInv (head frame), FaceMid2D,
             I3_2D (head frame), Backdrop2D, rib fields, paw plans, body decor.

``build_sections(p, skin)`` returns a ``Sections`` dict-like object; every entry is a CrossSection and every
step is checked (non-empty, expected piece counts) so a broken parameter set fails loudly.
"""
from __future__ import annotations

import dataclasses

import math
import time

import numpy as np
from manifold3d import CrossSection

from . import escapement as esc
from . import geom2d as g2
from .params import Params
from .sweep import swept, swept_inv


# sections extruded as material / as cuts (cleaned of point contacts at the end of build_sections)
SOLID_SECTIONS = ("star2d", "headband2d", "faceup2d", "facemid2d", "fill2d", "roof2d", "body2d", "ribs_band2d",
                  "ribs_front2d",
                  "crown_skirt2d", "groove_rib2d",
                  "paw_plan_R", "paw_plan_L", "decor2d", "ribs_back2d", "ribs_roof2d")
CUT_SECTIONS = ("roof_sweep_inv2d", "slot2d", "crown_recess2d", "band_groove2d")


class Sections(dict):
    """dict of name -> CrossSection with attribute access (``S.headband2d``)."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e

    def areas(self) -> dict:
        return {k: round(v.area(), 2) for k, v in self.items() if isinstance(v, CrossSection)}


# ---------------------------------------------------------------------------------------------- head frame
def hub2d(p: Params) -> CrossSection:
    return g2.circle(p.P, p.hub_r, g2.TOL_FUNC)


def leg2d(p: Params, i: int) -> CrossSection:
    return g2.stadium(p.leg_A[i], p.leg_Bs[i], p.leg_w, g2.TOL_FUNC)


def legs2d(p: Params) -> CrossSection:
    return g2.union([leg2d(p, 0), leg2d(p, 1)])


def _inside_margin(face: CrossSection, pt, hi: float = 20.0) -> float:
    """Largest r such that disc(pt, r) lies inside ``face`` (negative if pt is outside)."""
    tiny = g2.circle(pt, 0.01, n=12)
    if g2.difference(tiny, face).area() > 1e-9:
        return -1.0
    lo = 0.0
    for _ in range(22):
        mid = 0.5 * (lo + hi)
        if g2.difference(g2.circle(pt, mid, 0.002), face).area() > 1e-6:
            hi = mid
        else:
            lo = mid
    return lo


def check_skin(p: Params, face: CrossSection, name: str = "skin") -> dict:
    """SPEC 4.3 face contract.

    Hard requirements (raise): Face2D is one piece, overlaps the hub, and both leg ends B_i lie inside it.
    Soft requirements (reported in ``warnings``): disc(P, 7.5) inside Face2D; B_i >= 3 mm inside; no part
    narrower than 6.0 mm.  The reference kitty face (disc(P + (0, 11), 16)) cannot contain disc(P, 7.5) and has
    B_i only 1.33 mm inside - the core compensates with a hub collar (solids.py) so the blind bore is always
    walled by >= 2.6 mm.
    """
    out = {"warnings": []}
    mB = [_inside_margin(face, b) for b in p.leg_Bs]
    out["leg_B_margin"] = [round(m, 3) for m in mB]
    if min(mB) <= 0:
        raise AssertionError(f"{name}: leg ends B_i must lie inside Face2D (margins {mB})")
    if min(mB) < p.leg_B_margin - 1e-3:
        out["warnings"].append(f"B_i only {min(mB):.2f} mm inside Face2D (contract {p.leg_B_margin})")
    hub_out = g2.difference(g2.circle(p.P, p.R_hub_cut, 0.01), face).area()
    out["hub_disc_outside_area"] = round(hub_out, 3)
    if g2.intersect(g2.circle(p.P, p.hub_r, 0.01), face).area() < 1.0:
        raise AssertionError(f"{name}: Face2D does not overlap the hub")
    if hub_out > 1e-3:
        out["warnings"].append(f"disc(P, {p.R_hub_cut}) not inside Face2D ({hub_out:.1f} mm^2 outside); "
                               "hub collar z {:.1f}-{:.1f} added".format(p.z_band1, p.z_roof0))
    thin = g2.difference(face, g2.opening(face, 6.0 - 0.02)).area()
    out["narrower_than_6mm_area"] = round(thin, 3)
    if thin > 0.5:
        out["warnings"].append(f"Face2D has {thin:.1f} mm^2 narrower than 6.0 mm")
    return out


def open_keep_outline(raw: CrossSection, t: float, min_dist: float = 0.01, **_ignored) -> CrossSection:
    """open_t(raw) that keeps raw's own polyline wherever nothing is removed.

    A plain opening re-polygonises every boundary (offset arcs), so stacked sections that share an outline
    (fill, roof, back plate) or exact functional curves (pallet tips) would move by round-off.  Here only the
    parts of raw lying farther than ``min_dist`` (10 um) from open_t(raw) - real slivers, feathers and sharp
    convex corners - are cut away; the boundary noise of the re-polygonised opening is ignored."""
    opened = g2.opening(raw, t, 0.005)
    far = g2.difference(raw, g2.grow(opened, min_dist, 0.002))
    if far.is_empty() or far.area() < 1e-9:
        return raw
    return g2.difference(raw, g2.grow(far, min_dist / 2, 0.002))


def _ang_extreme(p: Params, cs: CrossSection, side: int, lowest: bool = True) -> float:
    """Angle about P (deg from the horizontal, right side = CCW from +X, left side mirrored) of the lowest
    (``lowest=True``) or highest point of ``cs`` on one side; bisection on polygon clipping, so long straight
    edges are handled exactly.  Returns +90 (lowest) / -90 (highest) when cs has nothing on that side."""
    lo, hi = -90.0, 90.0
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        if lowest:
            w = g2.wedge(-90.0, mid, 300.0, c=p.P) if side > 0 else g2.wedge(180.0 - mid, 270.0, 300.0, c=p.P)
        else:
            w = g2.wedge(mid, 90.0, 300.0, c=p.P) if side > 0 else g2.wedge(90.0, 180.0 - mid, 300.0, c=p.P)
        hit = g2.intersect(cs, w).area() > 1e-3
        if lowest:
            hi, lo = (mid, lo) if hit else (hi, mid)
        else:
            lo, hi = (mid, hi) if hit else (lo, mid)
    return hi if lowest else lo


def crown_lune_cut(p: Params, face: CrossSection) -> CrossSection:
    """Face2D with a radial notch where its outline leaves the crown arc: the part of the face beyond
    R_b + swept_gap then starts with an edge radial to P, so the face mid layer meets the crown edge at 90 deg
    (a sliding corner, not a closing wedge - V12)."""
    rb = p.crown_R + p.swept_gap
    outer = g2.difference(face, g2.circle(p.P, rb, 0.01))
    if outer.is_empty():
        return face
    cuts = []
    for side in (+1, -1):
        a = _ang_extreme(p, outer, side, lowest=True)
        if a >= 89.0:
            continue
        w = (g2.wedge(a - 1.0, a + p.crown_lune_deg, 300.0, c=p.P) if side > 0 else
             g2.wedge(180.0 - a - p.crown_lune_deg, 181.0 - a, 300.0, c=p.P))
        # local: only the face just outside the crown edge (a skin part farther out at the same angle, e.g. the bee's
        # antenna ball, is not touched)
        cuts.append(g2.intersect(g2.difference(w, g2.circle(p.P, rb - 0.01, 0.01)),
                                 g2.circle(p.P, rb + p.crown_lune_depth, 0.01)))
    out = g2.difference(face, *cuts)
    # the notch leaves a radial edge; keep concave corners r >= 1 (closing) without filling the notch back
    return g2.check(out, "face2d (crown notch)", n_pieces=1)


def crown_window_deg(p: Params) -> float:
    """Conservative start angle of the crown window (deg about P) before the face is known: the leg-channel walls
    around the swept legs + fingers + hub (no face covering any of them) - >= the final th_R."""
    hb = g2.union([hub2d(p), legs2d(p), esc.fingers2d(p)])
    need = g2.difference(g2.grow(swept(hb, p.P, p.psi_b, p.n_sweep, allowance=p.sweep_allowance), p.gap_xy + p.wall,
                                 0.01), g2.circle(p.P, p.crown_R + 0.05, 0.01))
    return max(_ang_extreme(p, need, +1, lowest=False), _ang_extreme(p, need, -1, lowest=False)) + p.crown_margin_deg


def crown_fence(p: Params, face: CrossSection) -> tuple[CrossSection, dict]:
    """Face2D with a concentric "collar" beyond the crown edge where the skin needs one (fix round 1, V12).

    Beyond the crown edge the face mid layer must meet the frame only along concentric edges (constant gap) and
    radial ends (sliding corners).  A skin part that leaves a ray gap there - the bee's antenna stalks rising from
    a thin head cap, the robot's ear bolts poking out as islands - shows a P-facing, non-concentric edge 2-11 mm
    from the crown edge, and the swing then opens and closes that gap (a squeeze).  The collar - an annular sector
    about P from the crown edge (R_b + swept_gap) out by crown_fence_t, between the two crown notches - joins such
    parts to the head with one concentric edge.  Skins without the problem (the kitty) are left unchanged."""
    info = {"applied": False}
    rb = p.crown_R + p.swept_gap
    outer = g2.difference(face, g2.circle(p.P, rb, 0.01))
    if outer.is_empty() or outer.area() < 0.5:
        return face, info
    # (face already notched: its part beyond the crown starts at the notches' radial edges)
    th_lo, th_hi = _ang_extreme(p, outer, +1), 180.0 - _ang_extreme(p, outer, -1)
    fm = g2.drop_small(g2.opening(outer, p.facemid_open, 0.01), 0.5)
    n_pieces = len(fm.decompose())
    # rays from P: where facemid (beyond the crown) exists within R_b + 12, it must start at the crown edge
    import shapely
    F = g2.to_shapely(fm)
    P = np.asarray(p.P, float)
    th = np.radians(np.arange(th_lo, th_hi + 1e-9, 0.25))
    rs = np.arange(rb, p.crown_R + 12.0, 0.05)
    X = P[0] + np.outer(np.cos(th), rs)
    Y = P[1] + np.outer(np.sin(th), rs)
    inside = shapely.contains_xy(F, X, Y)
    bad = [float(np.degrees(t)) for t, row in zip(th, inside) if row.any() and rs[int(np.argmax(row))] > rb + 1.1]
    # the face mid layer must start right at the notches with a radial end: a cap thinner than the FaceMid opening
    # there is trimmed back to a rounded, oblique end that slides along the crown edge (a squeeze, V12)
    def cap(th_deg):
        t = math.radians(th_deg)
        seg = shapely.LineString([(P[0] + rb * math.cos(t), P[1] + rb * math.sin(t)),
                                  (P[0] + (rb + 6.0) * math.cos(t), P[1] + (rb + 6.0) * math.sin(t))])
        return F.intersection(seg).length
    thin_ends = [round(a, 2) for a in (th_lo + 0.75, th_hi - 0.75) if cap(a) < p.facemid_open + 0.3]
    info.update({"pieces_beyond": n_pieces, "bad_rays": len(bad), "thin_cap_at_notch_deg": thin_ends})
    if n_pieces <= 1 and not bad and not thin_ends:
        info["range_deg"] = [round(th_lo, 2), round(th_hi, 2)]
        return face, info
    # the collar runs on until the crown wall left exposed beyond its ends is >= 12 mm from every face part beyond
    # the collar (antenna balls ...): only the collar's radial end then faces the frame there
    far = g2.difference(outer, g2.circle(p.P, rb + p.crown_fence_t, 0.01))
    if not far.is_empty() and p.crown_fence_extend:
        Fa = g2.to_shapely(far)
        for k in range(1200):
            t = math.radians(th_lo - 0.1)
            if Fa.distance(shapely.Point(P[0] + p.crown_R * math.cos(t), P[1] + p.crown_R * math.sin(t))) >= 12.0:
                break
            th_lo -= 0.1
        for k in range(1200):
            t = math.radians(th_hi + 0.1)
            if Fa.distance(shapely.Point(P[0] + p.crown_R * math.cos(t), P[1] + p.crown_R * math.sin(t))) >= 12.0:
                break
            th_hi += 0.1
    # ... but its ends stay >= 12 mm (swept) from the fixed steps where the crown arc meets the shoulders (V12)
    th_w = crown_window_deg(p)
    lim = th_w + math.degrees(2.0 * math.asin(12.0 / (2.0 * rb))) + p.psi_b + p.crown_fence_margin_deg
    info["clamped_to_step_rule"] = bool(th_lo < lim or th_hi > 180.0 - lim)
    th_lo, th_hi = max(th_lo, lim), min(th_hi, 180.0 - lim)
    info["range_deg"] = [round(th_lo, 2), round(th_hi, 2)]
    fence = g2.sector(rb - p.crown_fence_in + 0.5, rb + p.crown_fence_t, th_lo, th_hi, c=p.P, tol=g2.TOL_FUNC)
    out = g2.closing(g2.union([face, fence]), 1.0, 0.01)
    info["applied"] = True
    return g2.check(out, "face2d (crown collar)", n_pieces=1), info


def crown_geometry(p: Params, S: Sections) -> dict:
    """Crown ring (fix round 1): radius R_b (p.crown_R) about P and the angular window [th_R, 180 - th_R] (world,
    deg CCW from +X about P) in which the body outline is the concentric arc R_b.

    The arc must reach below the lowest point any part of FaceUp beyond R_b + swept_gap can swing to (so the
    face only ever meets the frame along concentric edges: constant gaps), and stay above the highest point
    where the swept head band needs body beyond R_b (the leg-channel walls)."""
    P = np.asarray(p.P, float)
    R_b = p.crown_R

    beyond = g2.difference(S["faceup2d"], g2.circle(p.P, R_b + p.swept_gap, 0.01))
    face_lo = min(_ang_extreme(p, beyond, +1), _ang_extreme(p, beyond, -1)) - p.psi_b
    # body needed for the leg channels: walls around the swept exposed band (legs, fingers, hub)
    need = g2.difference(g2.grow(S["swept_exposed2d"], p.gap_xy + p.wall, 0.01), g2.circle(p.P, R_b + 0.05, 0.01))
    need_hi = max(_ang_extreme(p, need, +1, lowest=False), _ang_extreme(p, need, -1, lowest=False))
    th = need_hi + p.crown_margin_deg
    if th > face_lo - p.crown_margin_deg:
        raise AssertionError(f"crown ring: no room between the leg-channel walls ({need_hi:.1f} deg) and the "
                             f"face's reach ({face_lo:.1f} deg)")
    # the step where the crown arc meets the shoulders is a fixed, non-concentric edge: the swept face must stay
    # >= 12 mm from it (V12); reported here, checked by v_safety's pinch audit
    step_clear = 2.0 * (R_b + p.swept_gap) * math.sin(math.radians(max(0.0, face_lo - th)) / 2.0)
    return {"R_b": R_b, "th_R": th, "face_lo_deg": face_lo, "need_hi_deg": need_hi,
            "step_to_swept_face_mm": round(step_clear, 2)}


def crown_body(p: Params, S: Sections, body: CrossSection, log=lambda m: None) -> CrossSection:
    """Body2D with the crown ring: inside the window the outline is the arc R_b about P, and the roof spans as a
    full annulus (P hole .. R_b) over the top of the hub, under the face.  The face (FaceMid, front layer) then
    only meets concentric roof edges: the I3 slot is a pure annulus (no swept-out strips at the print pose) and
    the slot mouths are constant-gap."""
    cg = crown_geometry(p, S)
    S["crown"] = cg
    th = cg["th_R"]
    sector = g2.wedge(th, 180.0 - th, 300.0, c=p.P)
    disc_b = g2.circle(p.P, cg["R_b"], g2.TOL_FUNC)
    body = g2.union([g2.difference(body, g2.difference(sector, disc_b)), g2.intersect(sector, disc_b)])
    # the step where the arc meets the shoulders is outside the face's reach: round its corners (r >= 1.5)
    body = g2.opening(g2.closing(body, p.corner_r, 0.01), 2 * p.corner_r, 0.01).simplify(0.005)
    # mouth guard: where the face band passes under the crown edge the frame comes down to a skirt (z_skirt)
    # over a groove in the band top, and a sill rib stands on the plate - the opening left at the crown edge
    # (sill top 2.6 .. skirt 5.7) is too low for a 4 mm fingertip probe, so the band / fill jaws inside it are
    # out of reach.  The fill under the skirt is recessed (annulus R_b - w .. R_b) from the sill to the skirt.
    Rb, w = cg["R_b"], p.crown_skirt_w
    ann = g2.difference(g2.circle(p.P, Rb + 2.0, 0.01), g2.circle(p.P, Rb - w, g2.TOL_FUNC, hole=True))
    S["crown_recess2d"] = g2.intersect(ann, sector)
    S["crown_skirt2d"] = g2.intersect(g2.difference(disc_b, g2.circle(p.P, Rb - w, g2.TOL_FUNC, hole=True)),
                                      sector)
    # sill rib right at the crown edge (a 4 mm probe then reaches < 1 mm into the 3.1 mm opening)
    sill = g2.difference(g2.circle(p.P, Rb - 0.02, 0.01), g2.circle(p.P, Rb - 0.02 - p.rib_w, 0.01))
    S["crown_sill2d"] = g2.intersect(sill, g2.wedge(th - 3.0, 183.0 - th, 300.0, c=p.P))
    # band groove (head frame): every part of the band that can swing under the skirt
    hw = g2.wedge(th - p.psi_b - 1.0, 180.0 - th + p.psi_b + 1.0, 300.0, c=p.P)
    gann = g2.difference(g2.circle(p.P, Rb + p.swept_gap, g2.TOL_FUNC, hole=True),
                         g2.circle(p.P, Rb - w - p.swept_gap, g2.TOL_FUNC))
    S["band_groove2d"] = g2.intersect(gann, hw)
    # one skid rib along the groove (concentric about P, centred under the skirt): the skirt bridges the leg
    # channels and, where the band is under it, floats 0.40 over this rib top instead of over a flat floor
    rr = Rb - w / 2.0
    grib = g2.intersect(g2.difference(g2.circle(p.P, rr + p.rib_w / 2, g2.TOL_DECO),
                                      g2.circle(p.P, rr - p.rib_w / 2, g2.TOL_DECO)), hw,
                        g2.grow(S["headband2d"], -0.3, 0.01))
    S["groove_rib2d"] = g2.drop_small(g2.opening(grib, 0.5, 0.01), 0.3)
    log(f"crown ring R_b {cg['R_b']:.2f}, window {th:.1f} .. {180 - th:.1f} deg")
    return body


def crown_fill_levels(p: Params, S: Sections) -> list:
    """Fill sections (z0, section) between the sill top and the skirt underside.

    The fill under the crown skirt is recessed (annulus R_b - w .. R_b) so that the band / fill jaws sit >= w inside
    the 3.1 mm mouth, out of a 4 mm probe's reach (V12).  From z_skirt - w upward the recess closes at 45 deg in
    0.2 x 0.2 steps (micro-steps, V9), so the skirt is not a w-wide flat cantilever: where fill lies under it it
    grows out of a self-supporting chamfer, over the leg channels it bridges between the fill walls (and floats on
    the band's groove rib).  Each level is opened by open_t: strips left between the cavity and the recess edge
    are not slivers (V8)."""
    Rb, w = S["crown"]["R_b"], p.crown_skirt_w
    st = 0.2
    n = int(round(w / st))
    z_c0 = p.z_skirt - n * st
    if z_c0 <= p.z_bp + p.rib_h + 1e-6:
        raise AssertionError("crown skirt chamfer starts below the sill top")
    base = S["crown_recess2d"]
    F = S["fill2d"]
    out = [(p.z_bp + p.rib_h, g2.clean(open_keep_outline(g2.difference(F, base), p.open_t), "solid"))]
    for j in range(n):
        rec = g2.difference(base, g2.circle(p.P, Rb - w + st * (j + 0.5), g2.TOL_FUNC))
        sec = open_keep_outline(g2.difference(F, rec), p.open_t)
        # never more than one 0.2 step beyond the level below (where a narrow fill tongue tapers, the opened tip
        # would otherwise jump ahead by more than the step: an unlisted overhang)
        sec = g2.intersect(sec, g2.grow(out[-1][1], st, 0.005))
        out.append((z_c0 + st * j, g2.clean(sec, "solid")))
    return out


def face_jowls(p: Params, S: Sections) -> CrossSection:
    """Front-layer cheeks that fill the crescent between the face and the yarn-ball rim (fix round 1, V12).

    A round face over a round ball leaves a crescent whose width varies as the head swings (3.5 -> 5.6 mm at the
    cheeks: a squeeze).  The front layer (z 11.4-15.4 only) is extended down to SweptInv(disc(O, R_u + gap)) (gap
    1.45: V6 face <-> ball 1.4-2.0) between the two tangents from O to the face, so the face edge near the ball
    is either the constant-ish ~1.5 mm chin slit or a line radial to O (it slides along the rim, nothing closes).
    The jowls lie inside the I3 slot, i.e. they ride over the crown roof on the front-layer ribs."""
    face = S["face2d"]
    cy = p.C_h[1]
    pts = np.vstack([np.asarray(c, float) for c in face.to_polygons()])
    pts = pts[pts[:, 1] < cy]
    hull = CrossSection.hull_points([(0.0, 0.0)] + [tuple(q) for q in pts])
    below = g2.poly([(-200.0, -200.0), (200.0, -200.0), (200.0, cy), (-200.0, cy)])
    ball = swept_inv(g2.circle((0.0, 0.0), p.R_u + p.face_ball_gap, g2.TOL_FUNC, hole=True), p.P, p.psi_b,
                     p.n_sweep, allowance=0.0)
    j = g2.difference(g2.intersect(hull, below), face, ball)
    j = g2.intersect(j, g2.grow(S["roof_sweep_inv2d"], -0.05, 0.005))
    j = g2.drop_small(g2.opening(j, 1.6, 0.01), 2.0)
    return j


def front_extension(p: Params, S: Sections, ext: CrossSection, keep_clear: CrossSection) -> CrossSection:
    """Front-layer-only widening of the head (round 4: the kitty's wide "mochi" cheeks, fur tufts, forehead curls).

    The skin draws the extra outline; the core keeps the parts that can be built and stay safe:
      * over the crown roof (inside RoofSweepInv, like face_jowls), where the front-layer ribs carry it, or at most
        front_overhang (1.5) beyond the full-height face mid layer (a short cantilever, V9 own_rib_bridge <= 1.9);
      * clear of the yarn ball's sweep (SweptInv(disc(O, R_u + face_ball_gap)), V6 face <-> ball);
      * >= decor_face_clear (12) from the paws and body decor at every pose (they share the front layer's Z band,
        V12)."""
    P, psi_b, n = p.P, p.psi_b, p.n_sweep
    allowed = g2.union([g2.grow(S["roof_sweep_inv2d"], -0.05, 0.005), g2.grow(S["facemid2d"], 1.5, 0.01)])
    ball = swept_inv(g2.circle((0.0, 0.0), p.R_u + p.face_ball_gap, g2.TOL_FUNC, hole=True), P, psi_b, n,
                     allowance=0.0)
    cut = [ball]
    if keep_clear is not None and not keep_clear.is_empty():
        cut.append(swept_inv(g2.grow(keep_clear, p.decor_face_clear, 0.02), P, psi_b, n, allowance=0.0))
    e = g2.difference(g2.intersect(ext, allowed), *cut)
    e = g2.difference(e, S["faceup2d"])
    # merge with the face and keep only what joins it in one piece, corners r >= 1.5
    whole = g2.opening(g2.union([S["faceup2d"], e]), 2.0 * p.corner_r, 0.01)
    e = g2.difference(g2.intersect(whole, g2.union([e, S["faceup2d"]])), g2.grow(S["faceup2d"], -0.02, 0.005))
    return g2.drop_small(e, 2.0)


def _call_with_sections(fn, p, S):
    """Call a skin hook ``fn(p)``, or ``fn(p, S)`` if it accepts the (partial) sections as a second argument."""
    import inspect
    try:
        n = len([q for q in inspect.signature(fn).parameters.values()
                 if q.kind in (q.POSITIONAL_ONLY, q.POSITIONAL_OR_KEYWORD)])
    except (TypeError, ValueError):
        n = 1
    return fn(p, S) if n >= 2 else fn(p)


# ---------------------------------------------------------------------------------------------- main
def build_sections(p: Params, skin, verbose: bool = False) -> Sections:
    t0 = time.time()
    S = Sections()
    P = p.P
    O = (0.0, 0.0)
    psi_b = p.psi_b
    n = p.n_sweep
    alw = p.sweep_allowance

    def log(msg):
        if verbose:
            print(f"  [core2d {time.time() - t0:6.2f}s] {msg}", flush=True)

    # ---------------- escapement
    S["star2d"] = esc.star2d(p)
    S["pallets2d"] = esc.pallet_discs2d(p)
    S["fingers2d"] = g2.check(esc.fingers2d(p), "fingers2d", n_pieces=2)

    # ---------------- head frame
    S["hub2d"] = hub2d(p)
    S["legs2d"] = g2.check(legs2d(p), "legs2d", n_pieces=2)
    face = skin.face2d(p.C_h, p)
    g2.check(face, "face2d", n_pieces=1)
    S["skin_contract"] = check_skin(p, face, skin.name)
    if p.crown_ring:
        face = crown_lune_cut(p, face)
        face, S["skin_contract"]["crown_collar"] = crown_fence(p, face)
        # the notch / collar leave sharp convex corners in the outline: round them r 1.5 (exterior, V12.corners);
        # the skin's own outline (corners >= r 1.5 by the skin contract) keeps its exact polyline
        face = g2.check(open_keep_outline(face, 2.0 * p.corner_r), "face2d (notch corners rounded)", n_pieces=1)
    S["face2d"] = face
    # the wheel-ex disc is a cut -> circumscribed polygon (true clearance never smaller than designed)
    S["wheelex2d"] = swept_inv(g2.circle(O, p.wheel_ex_r, g2.TOL_FUNC, hole=True), P, psi_b, n, allowance=0.0)
    S["ballex2d"] = swept_inv(g2.circle(O, p.ball_ex_r, g2.TOL_FUNC, hole=True), P, psi_b, n, allowance=0.0)
    hb = g2.difference(g2.union([face, S["hub2d"], S["legs2d"]]), S["wheelex2d"])
    hb = g2.union([hb, S["fingers2d"]])
    # remove hair-thin feathers (e.g. the finger trapezoid's outer corners poke 0.02 out of the leg's round cap);
    # the pallet discs (r 2.14) and every edge wider than 1.0 keep their exact polylines
    hb = open_keep_outline(hb, 1.0)
    S["headband2d"] = g2.check(hb, "headband2d", n_pieces=1)
    S["faceup2d"] = g2.check(g2.difference(face, S["ballex2d"]), "faceup2d", n_pieces=1)
    log("head band / face up")

    # ---------------- world frame
    exposed = g2.difference(S["headband2d"], S["faceup2d"])
    exposed = g2.drop_small(g2.opening(exposed, 0.1, 0.01), 0.5)
    S["exposed2d"] = g2.check(exposed, "exposed2d")
    S["swept_exposed2d"] = swept(exposed, P, psi_b, n, allowance=alw)
    S["swept_headband2d"] = swept(S["headband2d"], P, psi_b, n, allowance=alw)
    S["swept_headband2d_exact"] = swept(S["headband2d"], P, psi_b, n, allowance=0.0)
    S["swept_faceup2d"] = swept(S["faceup2d"], P, psi_b, n, allowance=alw)
    log("sweeps")

    # skin pieces that enlarge the body
    paws = skin.paw_style(p)
    spans = {"R": p.paw_span_R, "L": p.paw_span_L}
    paw_plans = {}
    for side, ps in paws.items():
        a0, a1 = ps.span if getattr(ps, "span", None) is not None else spans[side]
        plan = g2.intersect(ps.plan2d, g2.sector(p.paw_lip_r, 80.0, a0, a1, tol=0.01))
        paw_plans[side] = g2.check(plan, f"paw_plan_{side}", n_pieces=1)
    paw_fp = g2.union(list(paw_plans.values()))

    decor = _call_with_sections(skin.body_decor2d, p, S)
    if decor is not None and not decor.is_empty():
        keep_clear = g2.grow(S["swept_faceup2d"], p.decor_face_clear, 0.01)
        decor = g2.difference(decor, keep_clear)
    else:
        decor = CrossSection()
    S["decor2d"] = decor

    body = g2.union([g2.circle(O, p.body_r, g2.TOL_DECO),
                     g2.grow(S["swept_exposed2d"], p.gap_xy + p.wall, 0.01),
                     decor, paw_fp])
    body = g2.round_r(body, p.body_round, p.corner_r, 0.01).simplify(0.005)
    if p.crown_ring:
        body = crown_body(p, S, body, log)
    log("body")

    # backdrop (needed first: every frame section stacked on the plate must lie inside it, otherwise the
    # union leaves zero-width overhang slivers / pinch vertices along nearly coincident outlines)
    S["body_pre2d"] = body          # the body outline before the plate trims it (for skins that frame it)
    # reliefs standing on the plate (e.g. a tail on the cushion): clear of the swinging head - >= decor_face_clear
    # from Swept(FaceUp2D) if they rise into the head's Z band (z_band0), else >= 0.8 - and inside the plate
    plate_decor = []
    for t in (skin.plate_decor(p, S) if hasattr(skin, "plate_decor") else []) or []:
        clear = p.decor_face_clear if t.z1 > p.z_band0 - 0.05 else 0.8
        shp = g2.drop_small(g2.difference(t.shape, g2.grow(S["swept_faceup2d"], clear, 0.01)), 1.0)
        if not shp.is_empty():
            plate_decor.append(dataclasses.replace(t, shape=shp))
    S["plate_decor"] = plate_decor
    S["plate_decor2d"] = g2.union([t.shape for t in plate_decor]) if plate_decor else CrossSection()
    S["body_pre2d"] = g2.union([body, S["plate_decor2d"]]) if plate_decor else body
    extra = _call_with_sections(skin.backdrop2d, p, S)
    S["body_pre2d"] = body
    bd = g2.union([body, g2.grow(S["swept_faceup2d"], p.backdrop_margin, 0.01),
                   g2.grow(S["plate_decor2d"], 1.5, 0.01) if plate_decor else CrossSection(),
                   extra if extra is not None else CrossSection()])
    S["backdrop2d"] = g2.check(g2.round_r(bd, p.backdrop_round, p.backdrop_corner_r, 0.02).simplify(0.01),
                               "backdrop2d", n_pieces=1)
    # Body2D is kept >= 0.05 inside the plate outline: where the two are flush they are two independent
    # approximations of the same curve, and stacking walls that cross each other at z 2.0 would leave pinch
    # vertices in the frame mesh.  (A 0.05 mm ledge is below print resolution.)
    S["body2d"] = g2.check(g2.intersect(body, g2.grow(S["backdrop2d"], -p.plate_ledge, 0.005)).simplify(0.002),
                           "body2d", n_pieces=1)
    log("backdrop")

    # cavity, stop pads, fill
    S["cavity2d"] = g2.grow(S["swept_headband2d"], p.gap_xy, 0.005).simplify(0.001)
    raw_fill = g2.difference(S["body2d"], S["cavity2d"], g2.circle(O, p.fill_wheel_r, g2.TOL_FUNC, hole=True))
    # every part of the head band except the leg that banks on a pad must stay >= swept_gap from that pad at every
    # pose (a wide Face2D, e.g. the SPEC robot rectangle, would otherwise slide over the pads)
    nonleg = [swept(g2.difference(S["headband2d"], g2.grow(leg2d(p, i), 0.3, 0.01)), P, psi_b, n, allowance=alw)
              for i in (0, 1)]
    fill_open = open_keep_outline(raw_fill, p.open_t)
    pads = []
    pad_contact = []
    pad_raw_area = 0.0
    for s in (+1, -1):
        for i in (0, 1):
            ang = s * psi_b
            leg_r = g2.rot_about(leg2d(p, i), ang, P)
            A, B = np.array(p.leg_A[i]), np.array(p.leg_Bs[i])
            M = g2.rot_pt((A + B) / 2.0, ang, P)
            # (+0.05 so the pad overlaps the fill wall and merges with it instead of touching it)
            pad = g2.difference(g2.grow(leg_r, p.swept_gap + 0.05, 0.005), S["swept_headband2d_exact"])
            # SPEC: "intersected with disc(Rot(M_i), 3.0)".  The flank is leg_w/2 = 3.5 from M_i, so a 3.0 disc
            # around M_i never reaches it (empty pads).  Read as "+-3.0 mm of flank around M_i": use the disc
            # whose chord at the pad's outer edge (leg_w/2 + swept_gap from M_i) is 2 x 3.0 long.
            r_pad = math.hypot(p.stop_pad_r, p.leg_w / 2 + p.swept_gap)
            pad = g2.intersect(pad, g2.circle(M, r_pad, 0.01))
            pad_raw_area += pad.area()
            # fix round 1: (a) clear of the rest of the swinging band, (b) backed by the fill wall - a pad corner that
            # sticks out past a fill corner is a free 0.6 x 6.4 mm fin (V8)
            pad = g2.difference(pad, g2.grow(nonleg[i], p.swept_gap, 0.005))
            pad = g2.intersect(pad, g2.grow(fill_open, 0.6, 0.005))
            pad = g2.drop_small(g2.opening(pad, 0.4, 0.005), 0.05)     # no feather tips
            name = f"stop_pad_{'+' if s > 0 else '-'}{'LR'[i]}"
            # banking contact: length of pad edge within 0.05 of the leg flank at the limit pose
            contact = g2.intersect(pad, g2.grow(leg_r, 0.05, 0.005)).area() / 0.05
            pad_contact.append(round(contact, 2))
            if contact < p.stop_pad_min_contact:
                raise AssertionError(f"{skin.name}: {name} touches the leg over only {contact:.2f} mm "
                                     f"(< {p.stop_pad_min_contact}); Face2D reaches the stop-pad zone")
            pads.append(g2.check(pad, name))
    S["stoppads2d"] = g2.union(pads)
    S["skin_contract"]["stop_pad_area_ratio"] = round(S["stoppads2d"].area() / max(pad_raw_area, 1e-9), 3)
    S["skin_contract"]["stop_pad_contact_mm"] = pad_contact
    if S["stoppads2d"].area() < 0.5 * pad_raw_area:
        raise AssertionError(f"{skin.name}: Face2D reaches the stop-pad zones (pads keep only "
                             f"{S['stoppads2d'].area():.1f} of {pad_raw_area:.1f} mm^2); keep the face inside the "
                             "core's pad keep-out (see skins/base.py)")
    S["fill2d"] = g2.check(g2.union([fill_open, S["stoppads2d"]]), "fill2d")
    # funnel-seat tongues: fill strips narrower than tongue_w inside r tongue_r are cut down to z_tongue in 3-D
    # (the 45 deg umbrella keep-out would otherwise thin them to a knife edge near the roof level)
    S["fill_tongues2d"] = g2.drop_small(g2.difference(g2.intersect(S["fill2d"], g2.circle(O, p.tongue_r, 0.01)),
                                                      g2.opening(S["fill2d"], p.tongue_w, 0.01)), 0.05)
    S["fill_slivers2d"] = g2.difference(raw_fill, S["fill2d"])
    log("fill")

    # roof
    raw_roof = g2.difference(S["body2d"], g2.circle(O, p.R_hole_roof, g2.TOL_FUNC, hole=True),
                             g2.circle(P, p.R_hub_cut, g2.TOL_FUNC, hole=True))
    S["roof2d"] = g2.check(open_keep_outline(raw_roof, p.open_t), "roof2d")
    S["roof_sweep_inv2d"] = g2.grow(swept_inv(S["roof2d"], P, psi_b, n, allowance=alw), p.gap_xy, 0.005)
    # FaceMid = FaceUp - RoofSweepInv, without the hair-thin feathers left where the sweep boundary runs
    # almost tangent to the face edge (they are moved into the I3 slot, i.e. become front-layer overhang)
    raw_mid = g2.difference(S["faceup2d"], S["roof_sweep_inv2d"])
    S["facemid2d"] = g2.check(open_keep_outline(raw_mid, p.facemid_open), "facemid2d")
    extra_slot = [g2.grow(g2.difference(raw_mid, S["facemid2d"]), 0.02, 0.005)]
    if p.crown_ring and p.col_r > 0:
        # the face mid layer around P (the "column" through the crown's P hole) is a disc about P: its edge facing
        # the yarn ball is concentric with the swing (constant gap at every point, V12) instead of the round chin
        # (fix round 1).  The annulus col_r .. P-hole sweep is left open under the front layer.
        ann = g2.difference(g2.circle(P, p.R_hub_cut + p.swept_gap, 0.01), g2.circle(P, p.col_r, g2.TOL_FUNC))
        S["facemid2d"] = g2.check(g2.difference(S["facemid2d"], ann), "facemid2d")
        extra_slot.append(g2.intersect(ann, S["faceup2d"]))
    S["slot2d"] = g2.union([S["roof_sweep_inv2d"]] + extra_slot)
    if p.face_jowls:
        S["jowl2d"] = face_jowls(p, S)
        if not S["jowl2d"].is_empty():
            S["faceup2d"] = g2.union([S["faceup2d"], S["jowl2d"]])
    ext = skin.face_front2d(p.C_h, p, S) if hasattr(skin, "face_front2d") else None
    if ext is not None and not ext.is_empty():
        S["front_ext2d"] = front_extension(p, S, ext, g2.union([paw_fp, decor]))
        if not S["front_ext2d"].is_empty():
            S["faceup2d"] = g2.check(g2.union([S["faceup2d"], S["front_ext2d"]]), "faceup2d + front ext",
                                     n_pieces=1)
    # the swept front layer including any extension (Swept(FaceUp2D) above predates it): frame parts added later on
    # the body top (tiers) keep clear of this one
    S["swept_faceup_full2d"] = swept(S["faceup2d"], P, psi_b, n, allowance=alw) if "front_ext2d" in S \
        else S["swept_faceup2d"]
    if "front_ext2d" in S and not S["front_ext2d"].is_empty():
        # front layer only: below z_front0 the extension is cut away with the I3 slot (where it overhangs the face
        # mid layer instead of riding on the crown roof, it would otherwise stand full height over nothing)
        S["slot2d"] = g2.union([S["slot2d"], g2.grow(g2.difference(S["front_ext2d"], S["facemid2d"]), 0.02, 0.005)])
    S["i3_2d"] = g2.check(g2.difference(S["faceup2d"], S["facemid2d"]), "i3_2d")
    S["bridges2d"] = g2.intersect(S["roof2d"], S["cavity2d"])      # roof spans over the head channels
    log("roof / face mid / I3")

    # everything standing on the body top (z 10.4) must lie inside the body top face
    top = g2.union([S["fill2d"], S["roof2d"]])
    S["top2d"] = top
    lip_zone = g2.circle(O, p.paw_wall_r + 0.3, 0.01)        # lip part of the paw floats above the ball
    for side in paw_plans:
        plan = g2.intersect(paw_plans[side], S["body2d"])
        plan = g2.intersect(plan, g2.union([top, g2.intersect(lip_zone, plan)]))
        paw_plans[side] = g2.check(g2.drop_small(plan, 1.0), f"paw_plan_{side}", n_pieces=1)
    S["paw_plan_R"], S["paw_plan_L"] = paw_plans["R"], paw_plans["L"]
    S["paw_plans"] = paw_plans          # every lip piece (R, L and any extra, e.g. the kitty's feet RF / LF)
    S["decor2d"] = g2.drop_small(g2.intersect(decor, top), 1.0) if not decor.is_empty() else decor

    # ---------------- rib fields (SPEC 3.4)
    def arcs_about(c, r0, pitch, n_arcs, clip):
        out = []
        for j in range(n_arcs):
            r = r0 + pitch * j
            ring = g2.difference(g2.circle(c, r + p.rib_w / 2, g2.TOL_DECO), g2.circle(c, r - p.rib_w / 2, g2.TOL_DECO))
            out.append(ring)
        return g2.intersect(g2.union(out), clip)

    post_clear = g2.union([g2.circle(c, p.post_r + p.post_root_fillet + p.rib_post_clear, 0.01)
                           for c in (O, P)])
    # ribs stay 0.3 inside the swept band (never touching the cavity walls or the stop pads)
    back_clip = g2.difference(g2.grow(S["swept_headband2d_exact"], -0.3, 0.01), g2.circle(O, p.fill_wheel_r, 0.01),
                              post_clear, g2.grow(S["stoppads2d"], 0.3, 0.01))
    ribs_back = arcs_about(P, p.rib_back_r0, p.rib_back_pitch, p.rib_back_n, back_clip)
    rings = g2.union([g2.difference(g2.circle(O, r + p.rib_w / 2, g2.TOL_DECO), g2.circle(O, r - p.rib_w / 2, g2.TOL_DECO))
                      for r in p.rib_rings_O])
    rings = g2.difference(g2.intersect(rings, g2.circle(O, p.rib_rings_clip, 0.01)), post_clear)
    S["ribs_back2d"] = g2.drop_small(g2.opening(g2.union([ribs_back, rings]), 0.5, 0.01), 0.3)
    # fill-in arcs (fix round 1): a skin part far from P (bee antenna balls, robot ear bolts) can fall between two
    # SPEC arcs at the print pose; add an arc about P through every part of the head band farther than the float
    # reach (pitch 4.5: 1.85 + 0.02) from every rib
    reach = (4.5 - p.rib_w) / 2.0 + 0.02
    extra = []
    for _ in range(4):
        hb_print = g2.rot_about(S["headband2d"], p.psi_print, P)
        unc = g2.drop_small(g2.difference(hb_print, g2.grow(S["ribs_back2d"], reach, 0.01),
                                          g2.circle(P, p.bore_r + 0.05, 0.01)), 0.1)
        if unc.is_empty():
            break
        new, segs = [], []
        for q in unc.decompose():
            pts = np.vstack([np.asarray(c, float) for c in q.to_polygons()])
            r0 = float(np.mean(np.hypot(pts[:, 0] - P[0], pts[:, 1] - P[1])))
            # a local arc segment only (the swept zone of that part), not a whole new ring; near the band's outer tip
            # the arc moves inward until it fits inside the clip and still reaches the whole part
            loc = swept(g2.grow(g2.rot_about(q, -p.psi_print, P), 1.5, 0.01), P, psi_b, n, allowance=0.0)
            for dr in (0.0, -0.3, 0.3, -0.6, 0.6, -0.9, 0.9, -1.2, -1.5):
                r = r0 + dr
                seg = g2.intersect(g2.difference(g2.circle(P, r + p.rib_w / 2, g2.TOL_DECO),
                                                 g2.circle(P, r - p.rib_w / 2, g2.TOL_DECO)), loc, back_clip)
                seg = g2.drop_small(g2.opening(seg, 0.76, 0.01), 0.3)      # full-width rib only
                if not seg.is_empty() and g2.difference(q, g2.grow(seg, reach + 0.03, 0.01)).area() < 1e-3:
                    new.append(r)
                    segs.append(seg)
                    break
        extra += new
        if not segs:
            break
        add = g2.union(segs)
        S["ribs_back2d"] = g2.drop_small(g2.opening(g2.union([S["ribs_back2d"], add]), 0.5, 0.01), 0.3)
    S["rib_back_extra_radii"] = [round(r, 2) for r in extra]
    roof_clip = g2.intersect(S["roof2d"], swept(g2.grow(S["i3_2d"], p.rib_roof_i3_grow, 0.01), P, psi_b, n, allowance=0.0),
                             g2.grow(S["body2d"], -(p.frame_top_fillet + 0.2), 0.01))
    if p.crown_ring:
        # concentric arcs about P covering the I3 annulus (slot inner edge R_hub_cut - gap .. crown edge R_b + gap)
        # at pitch <= rib_roof_pitch: every point of the front layer within (pitch - rib_w)/2 of a rib top
        # front-layer ribs (HEAD, z front0 - rib_h .. front0, hanging under the I3 front layer, concentric about
        # P): they glide 0.40 over the crown's flat top.  Frame ribs on the roof top would face the face mid
        # layer across the 1.0 slit above the roof (a varying in-plane gap where the face's outer part ends, V12);
        # head ribs leave only head material in that slit.  The front layer then bridges between its own ribs.
        r_first = p.R_hub_cut + p.rib_w / 2 + 0.6
        r_last = S["crown"]["R_b"] - p.frame_top_fillet - 0.3 - p.rib_w / 2
        k = max(1, int(math.ceil((r_last - r_first) / p.rib_roof_pitch)))
        radii = np.linspace(r_first, r_last, k + 1)
        # 1.5 inside the face outline: the 3.3 mm slit between crown top and front layer admits no 4 mm probe, so
        # the rib ends are out of reach (a rib end at the face edge would face the ball rim, V12)
        # (the rim rib's two tails near the chin reach over the crown's P hole, where nothing is under their first
        # layer: they may reach only front_rib_hole_reach into it (a sub-millimetre cantilever) - they carry the
        # front layer there, so they are shortened, not removed; fix round 2: the robot's reached 1.2 mm)
        fclip = g2.difference(g2.intersect(g2.grow(S["i3_2d"], -0.3, 0.01), g2.grow(S["faceup2d"], -1.5, 0.01)),
                              g2.grow(S["facemid2d"], 0.3, 0.01),
                              g2.circle(P, p.R_hub_cut - p.front_rib_hole_reach, 0.01))
        arcs = [g2.difference(g2.circle(P, r + p.rib_w / 2, g2.TOL_DECO), g2.circle(P, r - p.rib_w / 2, g2.TOL_DECO))
                for r in radii]
        # plus a rim rib following the face outline (same 1.5 inset): the arcs cross the round face obliquely, so
        # the corners between arc ends and the face edge would otherwise be > 1.9 from any rib (V9)
        rim = g2.difference(g2.grow(S["faceup2d"], -1.5, 0.01), g2.grow(S["faceup2d"], -1.5 - p.rib_w, 0.01))
        S["ribs_front2d"] = g2.drop_small(g2.opening(g2.intersect(g2.union(arcs + [rim]), fclip), 0.5, 0.01), 0.3)
        S["ribs_roof2d"] = CrossSection()
        S["crown"]["front_rib_radii"] = [round(float(r), 3) for r in radii]
        # band-top ribs (head frame, z band1 .. band1 + rib_h): the crown roof prints over them as a rib-supported
        # float 0.40 above (SPEC 3.4 float type 1, here head -> frame).  Kept 0.3 inside the band top that lies under
        # the roof sweep, clear of the face mid layer, the hub collar, the groove and the ball.
        bclip = g2.difference(g2.intersect(S["headband2d"], S["roof_sweep_inv2d"]),
                              g2.grow(S["facemid2d"], 0.3, 0.01), g2.circle(P, p.R_hub_cut + 0.3, 0.01),
                              g2.grow(S["band_groove2d"], 0.3, 0.01),
                              # (ribs stay >= 0.8 under the roof's wheel-hole edge: inside the 1.0 slit at every pose)
                              swept_inv(g2.circle(O, p.R_hole_roof + 0.8, 0.02), P, psi_b, n, allowance=0.0))
        bclip = g2.grow(bclip, -0.3, 0.01)
        b_last = S["crown"]["R_b"] - p.crown_skirt_w - p.swept_gap - 0.6 - p.rib_w / 2
        kb = max(1, int(math.ceil((b_last - r_first) / p.rib_band_pitch)))
        bradii = list(np.linspace(r_first, b_last, kb + 1))
        # extend the field outward (legs under the lobes) at the same pitch
        while bradii[-1] < 32.0:
            bradii.append(bradii[-1] + (b_last - r_first) / kb)
        # plus radial spokes about P: with arcs alone the slicer can lay the roof's first-layer strands almost
        # tangent to the arcs, running ~28 mm between two of them unsupported (SLICER check, layer 8.6).  Spokes
        # every rib_band_spoke_deg turn the field into a web, so a strand in any direction meets a rib within
        # ~r * spoke pitch (<= 5.6 mm at r 32 for 10 deg).
        spokes = []
        for a in np.arange(0.0, 360.0, p.rib_band_spoke_deg):
            t = math.radians(a)
            d = np.array([math.cos(t), math.sin(t)])
            spokes.append(g2.stadium(tuple(P + d * r_first), tuple(P + d * bradii[-1]), p.rib_w))
        S["ribs_band2d"] = g2.drop_small(g2.opening(
            g2.intersect(g2.union([g2.difference(g2.circle(P, r + p.rib_w / 2, g2.TOL_DECO),
                                                 g2.circle(P, r - p.rib_w / 2, g2.TOL_DECO)) for r in bradii]
                                  + spokes),
                         bclip), 0.5, 0.01), 0.3)
        S["crown"]["band_rib_radii"] = [round(float(r), 3) for r in bradii]
        S["ribs_back2d"] = g2.union([S["ribs_back2d"], S["crown_sill2d"]])
    else:
        S["ribs_roof2d"] = g2.drop_small(g2.opening(arcs_about(P, p.rib_roof_r0, p.rib_roof_pitch, p.rib_roof_n,
                                                               roof_clip), 0.5, 0.01), 0.3)
    log("ribs")

    # remove point contacts from every section that is extruded (see geom2d.clean), keeping the stacking
    # relations exact: plate >= fill2d (z 2.0), top2d >= fill2d (z 8.4), FaceUp <= HeadBand (z 7.4)
    for k in SOLID_SECTIONS:
        if k in S and not S[k].is_empty():
            S[k] = g2.clean(S[k], "solid")
    for k in CUT_SECTIONS:
        if k in S and not S[k].is_empty():
            S[k] = g2.clean(S[k], "cut")
    S["paw_plans"] = {k: (S[f"paw_plan_{k}"] if k in ("R", "L") else g2.clean(v, "solid"))
                      for k, v in S["paw_plans"].items()}
    S["top2d"] = g2.clean(g2.union([S["roof2d"], S["fill2d"]]), "cut")
    S["backdrop2d"] = g2.clean(S["backdrop2d"], "cut")
    fu = g2.intersect(S["faceup2d"], S["headband2d"])
    if "jowl2d" in S and not S["jowl2d"].is_empty():
        fu = g2.union([fu, S["jowl2d"]])
    if "front_ext2d" in S and not S["front_ext2d"].is_empty():
        fu = g2.union([fu, S["front_ext2d"]])
    S["faceup2d"] = g2.clean(fu, "solid")
    if p.crown_ring and "crown_recess2d" in S and not S["crown_recess2d"].is_empty():
        # the skirt stands under the roof: inside the body top face (the rounded window-end corners)
        S["crown_skirt2d"] = g2.clean(g2.intersect(S["crown_skirt2d"], S["top2d"]), "solid")
        S["crown_fill_levels"] = crown_fill_levels(p, S)
    log("clean")
    S["_time_s"] = time.time() - t0
    return S


def section_report(p: Params, S: Sections) -> dict:
    """Numbers worth checking against the SPEC (areas, widths, overall size)."""
    bx = S["backdrop2d"].bounds()
    rep = dict(
        overall_W=round(bx[2] - bx[0], 2), overall_H=round(bx[3] - bx[1], 2), backdrop_bounds=[round(v, 2) for v in bx],
        i3_area=round(S["i3_2d"].area(), 1), headband_area=round(S["headband2d"].area(), 1),
        faceup_area=round(S["faceup2d"].area(), 1), facemid_area=round(S["facemid2d"].area(), 1),
        fill_area=round(S["fill2d"].area(), 1), roof_area=round(S["roof2d"].area(), 1),
        fill_slivers_removed_area=round(S["fill_slivers2d"].area(), 2),
        stoppads_area=round(S["stoppads2d"].area(), 2),
        max_bridge_width=round(max([g2.max_inscribed_width(q) for q in g2.pieces(S["bridges2d"], 0.5)] or [0.0]), 2),
        n_bridge_pieces=len(g2.pieces(S["bridges2d"], 0.5)),
    )
    return rep


# ---------------------------------------------------------------------------------------------- analysis
def print_pose_clearance(p: Params, S: Sections, phi: float, psi: float, full: bool = True) -> float:
    """2-D clearance between Star2D (rotated phi about O) and HeadBand2D (full=True) or the pallet discs
    (rotated psi about P); negative if they overlap.  Uses shapely (analysis only)."""
    W = g2.rot_about(S["star2d"], phi, (0.0, 0.0))
    H = g2.rot_about(S["headband2d"] if full else S["pallets2d"], psi, p.P)
    if not g2.intersect(W, H).is_empty():
        return -1.0
    return g2.min_distance_polys(W, H)


def search_print_pose(p: Params, S: Sections, coarse=(0.5, 0.25), fine=(0.05, 0.01)) -> tuple:
    """Pose (phi, psi) maximising the head-band <-> star clearance (SPEC 2.4(d)); returns (clearance, phi, psi)."""
    import shapely
    from shapely import affinity
    Wsh = g2.to_shapely(S["star2d"])
    Hsh = g2.to_shapely(S["headband2d"])
    shapely.prepare(Wsh)

    def clr(phi, psi):
        Hr = affinity.rotate(affinity.rotate(Hsh, psi, origin=p.P), -phi, origin=(0, 0))
        return -1.0 if Wsh.intersects(Hr) else Wsh.distance(Hr)

    best = (-9.0, 0.0, 0.0)
    lim = p.psi_b - 0.4
    for phi in np.arange(0.0, p.pitch, coarse[0]):
        for psi in np.arange(-lim, lim + 1e-9, coarse[1]):
            c = clr(phi, psi)
            if c > best[0]:
                best = (c, float(phi), float(psi))
    _, ph0, ps0 = best
    for phi in np.arange(ph0 - coarse[0], ph0 + coarse[0] + 1e-9, fine[0]):
        for psi in np.arange(ps0 - coarse[1], ps0 + coarse[1] + 1e-9, fine[1]):
            c = clr(phi, psi)
            if c > best[0]:
                best = (c, float(phi), float(psi))
    return best
