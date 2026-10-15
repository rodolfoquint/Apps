"""Purr Kitty skin (SPEC section 4.4) - the default skin.

A chubby kawaii kitten sitting on a quilted, scalloped cushion and hugging a yarn ball.  Restyled (round 3) after
concept art: big glossy eyes with two highlights, an open smile with a tongue, a bow on one ear, a fur tuft, big
round hind feet with toe beans, a fat curled tail and a diamond-quilted cushion.

* Face2D: disc(C_h, 16.0) + two rounded triangle ears (base at 14.72 from C_h at +-14 and +-54 deg, tip at
  24.0 at +-34 deg; rounded (+)2.6 then (-)0.6).  Unchanged: the head outline is part of the verified mechanism
  envelope (crown crossing, stop pads, chin-ball gap).
* Face features (relative to C_h, on the face top z_front1):
  - eyes: D9.0 domes 0.6 at (+-6.8, -1.6) [details]; highlights cut 0.65 deep so they reach the head colour
    in a multi-colour print: D3.2 at (+1.6, +1.7) and D1.5 at (-1.9, -1.5) from each eye centre
  - nose: rounded triangle 3.2 x 2.2 at (0, -5.5), raised 0.6 [details]
  - open smile: a D-shaped mouth under the nose with a "w" top edge, raised 0.6 [details], with a window for
    the tongue (raised 0.4 [accent])
  - blush: ellipses 4.2 x 2.4 at (+-9.0, -7.4), raised 0.4 [accent]
  - inner ears raised 0.4 [accent]; fur tuft (three bumps) on the forehead, raised 0.6 (head colour)
  - bow at the right ear base (3.4 x 2.0 lobes, largest that fits the flat top), raised 0.6 [accent]
* Cushion (back plate): the character outline grown 3.2 with a scalloped edge (r 3.9 lobes), a stitch groove
  1.6 inside the edge and diamond quilting (0.8 x 0.4 grooves) wherever the plate top is exposed.
* Body decor (raised to z 13.6 via ``param_overrides``): round hind feet r 5.6 at (+-17.2, -18.5) with raised toe
  beans [accent]; a fat tail (w 4.8) curling up the right side with a raised tip [accent].
* Paws: mitts on the ball rim with two finger grooves each (0.8 x 0.4).
* Wheel: three families of yarn arcs (0.8 wide grooves).

Colour classes (``Feature.color``) drive the multi-colour 3MF: plate = cushion (mint), frame/head = cream,
details = dark brown, accent = the ball's coral.
"""
from __future__ import annotations

import math

import numpy as np
from manifold3d import CrossSection

from .. import geom2d as g2
from .base import Feature, PawStyle, Skin

TOL = 0.01


def _rot(v, deg):
    a = math.radians(deg)
    return np.array([v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a)])


class KittySkin(Skin):
    name = "kitty"
    # cream kitty, coral yarn, mint cushion, dark-brown face details (concept art palette)
    colors = {"frame": "#f6e7d3", "wheel": "#f2787d", "head": "#f6e7d3"}
    plate_color = "#74cfae"
    details_color = "#3a2723"
    accent_color = "#f2787d"
    # feet and tail stand 3.2 proud of the roof (z 10.4 -> 13.6): above the ball top (13.3), like the concept art.
    # They stay >= 12 mm from the swept face (decor_face_clear) and outside the ball keep-out (r 18.6).
    param_overrides = {"z_decor1": 13.6}

    # face outline (SPEC 4.4; unchanged by the restyle)
    face_r = 16.0
    ear_base_r = 14.72
    ear_base_angles = (14.0, 54.0)
    ear_tip_r = 24.0
    ear_tip_angle = 34.0
    ear_grow, ear_shrink = 2.6, 0.6

    # face features (relative to C_h)
    eye_d, eye_xy = 9.0, (6.8, -1.6)
    hl_big = (3.2, (1.6, 1.7))           # diameter, offset from the eye centre
    hl_small = (1.5, (-1.9, -1.5))
    hl_depth = 0.65                      # through the 0.6 dark dome into the head colour
    nose_wh, nose_xy = (3.2, 2.2), (0.0, -5.5)
    mouth_c, mouth_rx, mouth_ry, mouth_top = (0.0, -8.7), 2.9, 2.6, -7.5
    tongue_c, tongue_ab = (0.0, -10.2), (1.55, 1.25)
    blush_ab, blush_xy = (4.2, 2.4), (9.0, -7.4)
    inner_ear_inset = 2.0
    tuft = ((-1.8, 10.0, 1.4), (0.0, 11.0, 1.5), (1.8, 10.0, 1.4))
    # bow at the right ear base: found by a small search for the largest bow lying wholly on the flat face top
    # (>= 1.65 inside the rim) clear of the eyes and the tuft
    bow_c, bow_angle, bow_size = (8.6, 12.7), -15.0, (3.4, 2.0)   # centre, tilt, (half span, lobe half-height)

    # ------------------------------------------------------------------ head
    def _ear_triangle(self, C_h, s):
        C = np.asarray(C_h, float)
        a0, a1 = (math.radians(s * a) for a in self.ear_base_angles)
        at = math.radians(s * self.ear_tip_angle)
        b0 = C + self.ear_base_r * np.array([math.sin(a0), math.cos(a0)])
        b1 = C + self.ear_base_r * np.array([math.sin(a1), math.cos(a1)])
        tip = C + self.ear_tip_r * np.array([math.sin(at), math.cos(at)])
        return g2.poly([b0, tip, b1])

    def ear2d(self, C_h, s):
        tri = self._ear_triangle(C_h, s)
        return g2.grow(g2.grow(tri, self.ear_grow, TOL), -self.ear_shrink, TOL)

    def face2d(self, C_h, p) -> CrossSection:
        head = g2.circle(C_h, self.face_r, 0.005)
        face = g2.union([head, self.ear2d(C_h, -1), self.ear2d(C_h, +1)])
        # soften the concave ear/head junction (all edges r >= 1.0, SPEC 6)
        return g2.closing(face, 1.0, TOL)

    def _mouth2d(self, C):
        mc = C + np.array(self.mouth_c)
        oval = g2.ellipse(tuple(mc), self.mouth_rx, self.mouth_ry, 0.0, TOL)
        below = g2.poly([(mc[0] - 9, C[1] + self.mouth_top), (mc[0] + 9, C[1] + self.mouth_top),
                         (mc[0] + 9, mc[1] - 9), (mc[0] - 9, mc[1] - 9)])
        mouth = g2.intersect(oval, below)
        # "w" top edge: two bites from the top, rounded
        bites = [g2.circle((C[0] + s * 1.35, C[1] + self.mouth_top + 0.55), 1.2, TOL) for s in (-1, 1)]
        return g2.opening(g2.difference(mouth, *bites), 0.8, TOL)

    def _bow2d(self, C):
        c = C + np.array(self.bow_c)
        hs, hh = self.bow_size
        lobes = []
        for s in (-1, 1):
            tri = g2.poly([(0.0, 0.0), (s * hs, hh), (s * hs, -hh)])
            lobes.append(g2.grow(g2.grow(tri, 0.9, TOL), -0.5, TOL))
        knot = g2.circle((0.0, 0.0), 1.25, TOL)
        bow = g2.union(lobes + [knot]).rotate(self.bow_angle).translate(tuple(c))
        return g2.opening(bow, 0.8, TOL)

    def face_features(self, C_h, p) -> list[Feature]:
        C = np.asarray(C_h, float)
        feats = []
        for s, tag in ((-1, "L"), (1, "R")):
            ec = C + np.array([s * self.eye_xy[0], self.eye_xy[1]])
            feats.append(Feature(f"eye_{tag}", g2.circle(ec, self.eye_d / 2, TOL), "dome", 0.6,
                                 center=tuple(ec), radius=self.eye_d / 2, color="details"))
            for k, (d, off) in enumerate((self.hl_big, self.hl_small)):
                hc = ec + np.array(off)
                feats.append(Feature(f"eye_highlight{k}_{tag}", g2.circle(hc, d / 2, TOL), "dimple", self.hl_depth,
                                     center=tuple(hc), radius=d / 2, on=f"eye_{tag}"))
            bc = C + np.array([s * self.blush_xy[0], self.blush_xy[1]])
            feats.append(Feature(f"blush_{tag}", g2.ellipse(tuple(bc), self.blush_ab[0] / 2, self.blush_ab[1] / 2,
                                                            0.0, TOL), "raise", 0.4, edge_ok=True, color="accent"))
            inner = g2.grow(self.ear2d(C_h, s), -self.inner_ear_inset, TOL)
            # keep the inner ear in the ear itself (not on the forehead): cut a band inside the head circle
            inner = g2.difference(inner, g2.circle(C_h, self.face_r - 2.2, TOL))
            inner = g2.opening(inner, 1.2, TOL)
            if s > 0:   # the bow sits on the right ear
                inner = g2.drop_small(g2.opening(g2.difference(inner, g2.grow(self._bow2d(C), 0.9, TOL)), 1.0, TOL),
                                      1.0)
            feats.append(Feature(f"inner_ear_{tag}", inner, "raise", 0.4, edge_ok=True, color="accent"))
        # nose: rounded triangle, point down
        w, h = self.nose_wh
        nc = C + np.array(self.nose_xy)
        tri = g2.poly([nc + (-w / 2, h / 2), nc + (w / 2, h / 2), nc + (0.0, -h / 2)])
        feats.append(Feature("nose", g2.opening(tri, 0.9, 0.005), "raise", 0.6, color="details"))
        # open smile with a tongue window (the tongue is raised 0.3 in the accent colour)
        mouth = self._mouth2d(C)
        tongue = g2.intersect(g2.ellipse(tuple(C + np.array(self.tongue_c)), *self.tongue_ab, 0.0, TOL),
                              g2.grow(mouth, -0.45, TOL))
        rim = g2.opening(g2.difference(mouth, g2.grow(tongue, 0.25, TOL)), 0.8, TOL)
        feats.append(Feature("mouth", rim, "raise", 0.6, color="details"))
        feats.append(Feature("tongue", g2.opening(tongue, 0.8, TOL), "raise", 0.4, color="accent"))
        # forehead fur tuft (head colour)
        tuft = g2.union([g2.circle(tuple(C + np.array([x, y])), r, TOL) for x, y, r in self.tuft])
        feats.append(Feature("tuft", tuft, "raise", 0.6))
        feats.append(Feature("bow", self._bow2d(C), "raise", 0.6, edge_ok=True, color="accent"))
        return feats

    # ------------------------------------------------------------------ cushion (back plate)
    cushion_out = 3.2         # lobe tips this far outside the character outline (body U swept face (+) 0.6)
    scallop_r = 3.9           # lobe radius ...
    scallop_step = 6.4        # ... and spacing along the smoothed outline (dips stay > 2.0 outside the face)
    quilt_pitch = 5.2         # diamond quilting: line spacing ...
    quilt_angle = 58.0        # ... at +- this angle from the horizontal (taller than wide diamonds)

    def backdrop2d(self, p, S) -> CrossSection:
        """A cushion framing the character: lobes of scallop_r centred on the character outline smoothed and
        grown by cushion_out - scallop_r, so the lobe tips stand cushion_out outside it."""
        base = g2.union([S["body_pre2d"], g2.grow(S["swept_faceup2d"], 0.6, TOL)])
        core = g2.grow(base, self.cushion_out - self.scallop_r, TOL)
        core = g2.opening(g2.closing(core, 7.0, 0.02), 4.0, 0.02)     # one smooth, convex-ish outline
        lobes = []
        for poly in core.to_polygons():
            pts = np.asarray(poly, float)
            if len(pts) < 3:
                continue
            seg = np.diff(np.vstack([pts, pts[:1]]), axis=0)
            L = np.r_[0.0, np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))]
            n = max(8, int(round(L[-1] / self.scallop_step)))
            for t in np.linspace(0.0, L[-1], n, endpoint=False):
                k = int(np.searchsorted(L, t, side="right") - 1)
                f = (t - L[k]) / max(L[k + 1] - L[k], 1e-9)
                lobes.append(g2.circle(tuple(pts[k] + f * seg[k]), self.scallop_r, TOL))
        return g2.closing(g2.union([core] + lobes), 0.8, TOL)

    def backdrop_features(self, p, backdrop2d, body2d, swept_faceup2d) -> list[Feature]:
        """Stitch groove 1.6 inside the scalloped edge and diamond quilting, both 0.8 wide x 0.4 deep, where the
        plate top is exposed (outside the body and the swept face, so never under the skid ribs)."""
        c = 1.6
        free = g2.difference(g2.grow(backdrop2d, -1.0, TOL), g2.grow(body2d, 0.6, TOL),
                             g2.grow(swept_faceup2d, 0.8, TOL))
        ring = g2.difference(g2.grow(backdrop2d, -(c - 0.4), TOL), g2.grow(backdrop2d, -(c + 0.4), TOL))
        ring = g2.intersect(ring, free)
        lines = []
        bx = backdrop2d.bounds()
        span = max(bx[2] - bx[0], bx[3] - bx[1]) + 40.0
        cx, cy = 0.5 * (bx[0] + bx[2]), 0.5 * (bx[1] + bx[3])
        for sgn in (-1, 1):
            a = math.radians(sgn * self.quilt_angle)
            d = np.array([math.cos(a), math.sin(a)])
            nrm = np.array([-d[1], d[0]])
            for k in range(-int(span / self.quilt_pitch), int(span / self.quilt_pitch) + 1):
                o = np.array([cx, cy]) + nrm * k * self.quilt_pitch
                lines.append(g2.stadium(tuple(o - d * span / 2), tuple(o + d * span / 2), 0.8, TOL))
        # quilting only inside the stitch line
        quilt = g2.intersect(g2.union(lines), free, g2.grow(backdrop2d, -(c + 1.2), TOL))
        grooves = g2.drop_small(g2.opening(g2.union([ring, quilt]), 0.6, TOL), 0.6)
        return [Feature("quilting", grooves, "deboss", 0.4)]

    # ------------------------------------------------------------------ body decor
    foot_c, foot_r = (17.2, -18.5), 5.6
    tail_path = ((12.5, -21.6), (20.5, -19.6), (24.6, -12.5), (24.4, -5.0))
    tail_w = 4.8
    def body_decor2d(self, p) -> CrossSection:
        feet = [g2.circle((s * self.foot_c[0], self.foot_c[1]), self.foot_r, TOL) for s in (-1, 1)]
        tail = g2.polyline_stadium(list(self.tail_path), self.tail_w, TOL)
        tail = g2.union([tail, g2.circle(self.tail_path[-1], self.tail_w / 2 + 0.6, TOL)])   # fluffy tip
        return g2.closing(g2.union(feet + [tail]), 2.0, TOL)

    def body_decor_features(self, p) -> list[Feature]:
        """Toe beans on each hind foot, raised 0.5 in the accent colour: an oval pad and three toes."""
        feats = []
        for s, tag in ((-1, "L"), (1, "R")):
            fc = np.array([s * self.foot_c[0], self.foot_c[1]])
            pad = g2.ellipse(tuple(fc + np.array([0.0, -1.0])), 1.9, 1.5, 0.0, TOL)
            toes = [g2.circle(tuple(fc + np.array([dx, 2.0 - 0.25 * abs(dx)])), 0.95, TOL) for dx in (-2.2, 0.0, 2.2)]
            feats.append(Feature(f"beans_{tag}", g2.union([pad] + toes), "raise", 0.5, color="accent"))
        # pink tail tip
        feats.append(Feature("tail_tip", g2.circle(self.tail_path[-1], self.tail_w / 2 - 0.4, TOL), "raise", 0.5,
                             color="accent"))
        return feats

    # ------------------------------------------------------------------ paws
    def paw_plan_right(self, p) -> CrossSection:
        """Mitt: the paw span out to r 24 plus a round pad (core clips it to the span, r >= 17.0 and Body2D)."""
        a0, a1 = p.paw_span_R
        ring = g2.sector(p.paw_lip_r, 23.6, a0, a1, tol=TOL)
        am = math.radians(0.5 * (a0 + a1))
        mitt = g2.circle((21.2 * math.cos(am), 21.2 * math.sin(am)), 5.4, TOL)
        return g2.union([ring, mitt])

    finger_angles = (1.5, 9.5)      # deg about O: two finger grooves on each mitt, over the ball rim
    finger_r = (18.3, 21.0)

    def paw_features_right(self, p, plan2d) -> list[Feature]:
        """Two finger grooves (0.8 wide x 0.4 deep) where the mitt curls over the ball."""
        parts = []
        for a in self.finger_angles:
            u = np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
            parts.append(g2.stadium(tuple(u * self.finger_r[0]), tuple(u * self.finger_r[1]), 0.8, TOL))
        return [Feature("fingers", g2.intersect(g2.union(parts), g2.grow(plan2d, -1.2, TOL)), "deboss", 0.4)]

    # ------------------------------------------------------------------ wheel
    yarn_poles = (-30.0, 90.0, 210.0)   # deg, wheel frame (finger well at 0 deg sits between two lobes)
    yarn_pole_r = 20.5                 # poles just outside the ball rim
    yarn_pitch = 2.4                   # 0.8 grooves (2 nozzle widths) with 1.6 lands
    yarn_seam = 0.6                    # half-gap between lobes

    def wheel_relief2d(self, p) -> CrossSection:
        """Yarn ball: three families of concentric arcs ("wraps"), each wrapped around a pole just outside the
        rim and filling one Voronoi lobe of the ball face; lobes are separated by plain seams."""
        w = max(p.relief_w, 0.8)
        poles = [self.yarn_pole_r * np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
                 for a in self.yarn_poles]
        out = []
        for k, pole in enumerate(poles):
            reg = g2.circle((0, 0), p.relief_r_max, TOL)
            for j, q in enumerate(poles):
                if j == k:
                    continue
                m = (pole + q) / 2
                nrm = (pole - q) / np.linalg.norm(pole - q)
                t = np.array([-nrm[1], nrm[0]])
                m = m + self.yarn_seam * nrm
                reg = g2.intersect(reg, g2.poly([m + 60 * t, m - 60 * t, m + 60 * nrm - 60 * t, m + 60 * nrm + 60 * t]))
            rings = [g2.difference(g2.circle(pole, r + w / 2, TOL), g2.circle(pole, r - w / 2, TOL))
                     for r in np.arange(4.0, 40.0, self.yarn_pitch)]
            out.append(g2.intersect(g2.union(rings), reg))
        # drop the tiny splinters where a lobe corner clips an arc
        return g2.drop_small(g2.opening(g2.union(out), 0.5, TOL), 0.8)
