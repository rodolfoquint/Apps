"""Purr Kitty skin (SPEC section 4.4) - the default skin.

A chubby kawaii kitty on a round quilted cushion hugging a yarn ball:

* Face2D: disc(C_h, 16.0) + two rounded triangle ears (base at 14.72 from C_h at +-14 and +-54 deg, tip at
  22.5 at +-34 deg; rounded (+)2.6 then (-)0.6).
* Face features (relative to C_h): domed eyes D7.0 at (+-6.5, -1.0) with D2.0 x 0.4 highlight dimples at
  (+1.3, +1.3) from each eye centre; rounded-triangle nose 3.0 x 2.2 at (0, -5.0); "omega" mouth of two r 1.8
  arcs 0.8 wide x 0.5 deep centred (+-1.8, -7.2); blush ellipses 5 x 3 debossed 0.3; inner ears debossed 0.4
  at inset 2.0.
* Back plate: the computed round cushion outline with a 0.6 x 0.3 stitch groove 1.6 inside the edge.
* Body decor: feet ovals 9 x 5 at (+-8.5, -20.0) with toe creases; tail = stadium of width 5 along
  (-13, -18) -> (-21, -14) -> (-23, -9).
* Paws: mitts on the ball rim with toe-bean dimples (D5 + three D2.5, 0.4 deep).
* Wheel: three families of yarn arcs (0.6 wide x 0.5 deep grooves).
"""
from __future__ import annotations

import math

import numpy as np
from manifold3d import CrossSection

from .. import geom2d as g2
from .base import Feature, PawStyle, Skin

TOL = 0.01


class KittySkin(Skin):
    name = "kitty"
    colors = {"frame": "#f9c5d5", "wheel": "#9ad0f5", "head": "#ffd9a0"}

    # face constants (SPEC 4.4)
    face_r = 16.0
    ear_base_r = 14.72
    ear_base_angles = (14.0, 54.0)
    ear_tip_r = 24.0                 # fix round 1: 22.5 -> 24.0 (ear tips >= 6 mm above the crown, DR.ears)
    ear_tip_angle = 34.0
    ear_grow, ear_shrink = 2.6, 0.6
    # fix round 1 (design review): bigger, lower kawaii eyes (D 8.4 = 0.26 x face width, eye line 0.16 R below the
    # head centre), a nose that reads at arm's length (4.0 x 2.8), a 0.9 wide mouth and 0.4 deep blush
    eye_d, eye_xy = 8.4, (7.0, -2.6)
    hl_d, hl_dxy, hl_depth = 2.4, (1.5, 1.5), 0.4
    nose_wh, nose_xy = (4.0, 2.8), (0.0, -4.6)
    mouth_r, mouth_w, mouth_depth, mouth_xy = 1.8, 0.9, 0.5, (1.8, -7.6)
    blush_ab, blush_xy, blush_depth = (4.0, 2.2), (7.3, -8.9), 0.4
    inner_ear_inset, inner_ear_depth = 2.0, 0.4
    feature_edge_margin = 3.0

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

    def _blush_centre(self, C_h, s):
        """SPEC position (+-10.0, -6.5) puts the 5 x 3 ellipse 1.9 mm from the face edge, violating the
        skin contract (>= 3 mm).  Move it radially inward by the minimum amount that satisfies it."""
        a, b = self.blush_ab[0] / 2, self.blush_ab[1] / 2
        x0, y0 = self.blush_xy
        limit = self.face_r - self.feature_edge_margin
        t = np.linspace(0, 2 * math.pi, 721)
        d = np.array([x0, y0]) / math.hypot(x0, y0)
        k = 0.0
        while True:
            cx, cy = x0 - d[0] * k, y0 - d[1] * k
            r = np.hypot(cx + a * np.cos(t), cy + b * np.sin(t)).max()
            if r <= limit + 1e-6:
                break
            k += 0.01
        return (C_h[0] + s * cx, C_h[1] + cy)

    def face_features(self, C_h, p) -> list[Feature]:
        C = np.asarray(C_h, float)
        feats = []
        for s, tag in ((-1, "L"), (1, "R")):
            ec = C + np.array([s * self.eye_xy[0], self.eye_xy[1]])
            feats.append(Feature(f"eye_{tag}", g2.circle(ec, self.eye_d / 2, TOL), "dome", 0.6,
                                 center=tuple(ec), radius=self.eye_d / 2))
            hc = ec + np.array(self.hl_dxy)
            feats.append(Feature(f"eye_highlight_{tag}", g2.circle(hc, self.hl_d / 2, TOL), "dimple", self.hl_depth,
                                 center=tuple(hc), radius=self.hl_d / 2, on=f"eye_{tag}"))
            bc = self._blush_centre(C_h, s)
            feats.append(Feature(f"blush_{tag}", g2.ellipse(bc, self.blush_ab[0] / 2, self.blush_ab[1] / 2, 0.0, TOL),
                                 "deboss", self.blush_depth))
            inner = g2.grow(self.ear2d(C_h, s), -self.inner_ear_inset, TOL)
            # keep the inner ear in the ear itself (not on the forehead): cut a band inside the head circle
            inner = g2.difference(inner, g2.circle(C_h, self.face_r - 2.2, TOL))
            inner = g2.opening(inner, 1.2, TOL)
            feats.append(Feature(f"inner_ear_{tag}", inner, "deboss", self.inner_ear_depth, edge_ok=True))
        # nose: rounded triangle, point down
        w, h = self.nose_wh
        nc = C + np.array(self.nose_xy)
        tri = g2.poly([nc + (-w / 2, h / 2), nc + (w / 2, h / 2), nc + (0.0, -h / 2)])
        nose = g2.opening(tri, 0.9, 0.005)
        feats.append(Feature("nose", nose, "raise", 0.6))
        # omega mouth: two lower half-annuli (r 1.8 +- 0.4) that share their inner end segment at the centre,
        # plus round caps at the outer ends (cap polygons turned half a segment so no vertex sits on a corner)
        parts = []
        for s in (-1, 1):
            mc = C + np.array([s * self.mouth_xy[0], self.mouth_xy[1]])
            ro, ri = self.mouth_r + self.mouth_w / 2, self.mouth_r - self.mouth_w / 2
            parts.append(g2.sector(ri, ro, 180.0, 360.0, c=tuple(mc), tol=0.005))
            cap = CrossSection.circle(self.mouth_w / 2, 24).rotate(7.5)
            parts.append(cap.translate(tuple(mc + np.array([s * self.mouth_r, 0.0]))))
        feats.append(Feature("mouth", g2.clean(g2.union(parts), "cut"), "deboss", self.mouth_depth))
        return feats

    # ------------------------------------------------------------------ frame
    def backdrop_features(self, p, backdrop2d, body2d, swept_faceup2d) -> list[Feature]:
        """Cushion stitch groove 0.8 wide x 0.4 deep (2 nozzle widths, 2 layers), 1.6 mm inside the backdrop edge,
        where the plate top is exposed (not under the fill/roof body)."""
        c = 1.6
        ring = g2.difference(g2.grow(backdrop2d, -(c - 0.4), TOL), g2.grow(backdrop2d, -(c + 0.4), TOL))
        ring = g2.difference(ring, g2.grow(body2d, 0.6, TOL))
        ring = g2.drop_small(ring, 0.5)
        return [Feature("stitch_groove", ring, "deboss", 0.4)]

    def body_decor2d(self, p) -> CrossSection:
        feet = [g2.ellipse((s * 8.5, -20.0), 4.5, 2.5, 0.0, TOL) for s in (-1, 1)]
        tail = g2.polyline_stadium([(-13.0, -18.0), (-21.0, -14.0), (-23.0, -9.0)], 5.0, TOL)
        tail = g2.closing(tail, 3.0, TOL)
        return g2.union(feet + [tail])

    def body_decor_features(self, p) -> list[Feature]:
        """Two toe creases on each foot (0.8 wide x 0.4 deep) - makes the ovals read as paws/feet."""
        feats = []
        for s, tag in ((-1, "L"), (1, "R")):
            cx, cy = s * 8.5, -20.0
            parts = [g2.stadium((cx + dx, cy - 1.4), (cx + dx, cy - 0.2), 0.8, TOL) for dx in (-1.5, 1.5)]
            feats.append(Feature(f"toes_{tag}", g2.union(parts), "deboss", 0.4))
        return feats

    def paw_plan_right(self, p) -> CrossSection:
        """Mitt: the paw span out to r 24 plus a round pad around the bean pads (core clips it to the span,
        r >= 17.0 and the Body2D outline)."""
        a0, a1 = p.paw_span_R
        ring = g2.sector(p.paw_lip_r, 23.6, a0, a1, tol=TOL)
        am = math.radians(0.5 * (a0 + a1))
        mitt = g2.circle((21.2 * math.cos(am), 21.2 * math.sin(am)), 5.4, TOL)
        return g2.union([ring, mitt])

    # toe-bean layout (found by a small search so the D5 pad + three D2.5 toes sit on the flat paw top, inside
    # the r 1.0 top fillet and the r 17.0 lip face, with >= 0.75 between beans)
    bean_angle = 7.0          # deg, direction of the pad centre from O
    bean_main_r = 23.2        # pad centre radius from O
    bean_toe_R = 4.5          # toe centres on an arc of this radius around the pad centre ...
    bean_toe_spread = 45.0    # ... at -45, 0, +45 deg ...
    bean_toe_tilt = 20.0      # ... about the direction toward the ball, fanned 20 deg upward

    def paw_features_right(self, p, plan2d) -> list[Feature]:
        """Toe beans: D5 main pad + three D2.5 toes (toward the ball, like fingers over the rim), 0.4 deep."""
        a = math.radians(self.bean_angle)
        u = np.array([math.cos(a), math.sin(a)])
        t = np.array([-u[1], u[0]])
        main = self.bean_main_r * u
        feats = [Feature("bean_main", g2.circle(main, 2.5, TOL), "deboss", 0.4)]
        for k, off in enumerate((-self.bean_toe_spread, 0.0, self.bean_toe_spread)):
            th = math.radians(off + self.bean_toe_tilt)
            c = main + self.bean_toe_R * (-u * math.cos(th) + t * math.sin(th))
            feats.append(Feature(f"bean_{k}", g2.circle(c, 1.25, TOL), "deboss", 0.4))
        return feats

    # ------------------------------------------------------------------ wheel
    yarn_poles = (-30.0, 90.0, 210.0)   # deg, wheel frame (knob at 0 deg sits between two lobes)
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
