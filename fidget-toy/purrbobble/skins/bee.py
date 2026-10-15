"""Bumble (bee) skin (SPEC section 4.4).

A round, happy bumblebee sitting in a five-petal flower, hugging a honeycomb pollen ball with her striped
arms, wings on her shoulders and a striped, stinger-tipped bottom peeking out behind the ball.  (SPEC 1 promises
a "bumblebee buzz band" at a hard push; the head inertia below lies inside the 2.9e-6 .. 1e-5 range the dynamics
were verified over, but this skin has not been re-simulated.)

Head (head frame, C_h = P + (0, 11)):

* Face2D = disc(C_h, 16.0) + two chunky antennae: a 6.0-wide stalk from C_h + 12.0 (sin +-30, cos +-30) to an
  D8.0 ball at C_h + 23.8 (sin +-40, cos +-40); antenna roots rounded r 2.0, ball necks r 1.0.
  SPEC lists the stalk C_h + 13 @ 22 deg -> C_h + 21 @ 30 deg: with the ball centre only 21 from C_h the 6.0 stalk
  shows just 1 mm outside the head and the balls read as mouse ears in the renders.  The ball sits 2.8 mm
  further out and splays 10 deg wider instead, so the antennae read as antennae.  Splaying keeps the
  swept antenna inside the 85 mm height (H 84.1 nominal, 84.3 shallow).
* Face features (relative to C_h): the kitty eyes (D7.0 domes at (+-6.5, -1.0), D2.0 x 0.4 highlight dimples at
  (+1.3, +1.3)); a "u" smile (r 3.3 arc, 1.1 wide x 0.5 deep, 205-335 deg, centred (0, -5.3)); cheek dots
  (4.6 x 3.0 ellipses debossed 0.5 at (+-8.85, -6.25), the largest that keeps the 3 mm edge rule and 0.6 mm
  from the eyes); a shiny D4.6 x 0.6 dome ("bobble") on each antenna ball (``edge_ok``: inside the r 1.5 rim
  fillet, on the ball's flat top).

Frame:

* Backdrop2D extra = the SPEC flower: disc(C_h, 19) U five D16 petals at C_h + 19 (sin(72k + 36), cos(...)),
  clipped to |x| <= 32 (64 W).  Exposed petal parts get a 0.8 x 0.3 outline groove 1.6 inside the petal edge
  plus a centre vein.
* Body decor (raised 1.6 on the roof, z 10.4 -> 12.0):
  - wings: two overlapping teardrop lobes per shoulder (fore + hind wing) with 0.8 x 0.4 vein grooves.  They are
    kept >= 12.3 mm from the swept head outline (not just the core's 2 mm), so no moving gap in the face's Z band
    falls in the 2-12 mm pinch range (V12).
  - a striped bottom (abdomen) peeking out behind the ball at the lower left, with two 2.0-wide x 0.5 deep
    stripes and a rounded stinger tip (r 2.0).
* Paws = striped bee arms: a 10-wide stadium leg along the paw-span bisector (7.5 deg / 172.5 deg) out to r 25.5,
  two 1.4-wide x 0.4 deboss stripes across its flat top (r 19.6 and 22.4).  The core clips it to the span, adds
  the lip over the ball rim and rounds it.

Wheel: honeycomb pollen ball - pointy-top hex dimples D4.0 (corner to corner) x 0.5 deep on a 4.46 mm lattice
(1.0 mm walls), clipped to r <= 16.5 and >= 7.5 from the knob axis; slivers thinner than 0.8 or smaller than
1.5 mm^2 dropped.

Inertia (solid PLA, verification/v_basic.py): head 14.9 g, I_h = 5.74e-6 kg m^2 about P, centre of mass 12.3 mm
above P (target 4-8e-6, 8-14 mm), so no pockets (``head_pockets2d`` = None).
"""
from __future__ import annotations

import math

import numpy as np
from manifold3d import CrossSection

from .. import geom2d as g2
from ..sweep import swept
from .base import Feature, Skin

TOL = 0.01


def _pol(c, r, a_deg):
    """Point at distance r from c in direction a (deg, measured from +Y toward +X, SPEC 4.4 convention)."""
    a = math.radians(a_deg)
    return np.asarray(c, float) + r * np.array([math.sin(a), math.cos(a)])


def _polO(r, a_deg):
    """Point at distance r from O at polar angle a (deg, CCW from +X)."""
    a = math.radians(a_deg)
    return np.array([r * math.cos(a), r * math.sin(a)])


def _band(c, u, half_len, half_w):
    """Rectangle centred on c: 2 half_w thick along the unit vector u, 2 half_len long across it."""
    u = np.asarray(u, float)
    t = np.array([-u[1], u[0]])
    c = np.asarray(c, float)
    return g2.poly([c - half_w * u - half_len * t, c + half_w * u - half_len * t,
                    c + half_w * u + half_len * t, c - half_w * u + half_len * t])


class BeeSkin(Skin):
    name = "bee"
    colors = {"frame": "#b9a4f4", "wheel": "#f7a325", "head": "#ffd23f"}   # lavender flower, honey, bee yellow

    # ---- face outline
    face_r = 16.0
    ant_w = 6.0                      # stalk width (SPEC)
    ant_r0, ant_a0 = 12.0, 22.0      # stalk root: distance from C_h, direction (deg from +Y) (SPEC 22 deg)
    ant_r1, ant_a1 = 23.1, 31.5      # ball centre (68.5 deg about P: >= 12 mm from the exposed crown wall, V12)
    ant_ball_d = 8.0                 # (SPEC)
    root_fillet = 2.0                # concave antenna root (makes the root > 8 wide)
    ant_base_r = 14.72               # tapered base on the head circle = the kitty ear base (r 14.72, 14..54 deg)
    ant_base_angles = (14.0, 54.0)
    ant_taper_r, ant_taper_a = 22.0, 32.0    # base tapers up into the stalk just below the ball (cap at the crown
    #                                          notch >= facemid_open + 0.3, so no collar is needed, like the kitty)
    neck_fillet = 1.0                # stalk / ball junction

    # ---- face features (relative to C_h)
    # fix round 1 (design review): bigger, lower kawaii eyes (D 8.2 = 0.26 x face width, eye line 0.15 R below the
    # head centre); the cheeks move down under them (4.0 x 2.2, still >= 3 mm inside the face edge)
    eye_d, eye_xy = 8.2, (6.8, -2.4)
    hl_d, hl_dxy, hl_depth = 2.4, (1.5, 1.5), 0.4
    smile_c, smile_r, smile_w, smile_a, smile_depth = (0.0, -5.3), 3.3, 1.1, (205.0, 335.0), 0.5
    cheek_ab, cheek_xy, cheek_depth = (2.0, 1.1), (7.6, -8.3), 0.5
    bobble_r = 2.3

    # ---- flower backdrop (SPEC)
    petal_R, petal_d, petal_n, petal_a0 = 19.0, 16.0, 5, 36.0
    flower_disc_r = 19.0
    max_half_w = 32.0                # final outline <= 64 W

    # ---- wings (world frame, right side; mirrored for the left): (root xy, root r, tip xy, tip r)
    wing_lobes = (((19.8, 10.6), 2.2, (26.4, 14.8), 4.0),      # forewing
                  ((20.6, 8.9), 2.0, (27.8, 9.9), 2.8))        # hindwing (partly tucked behind the arm)
    v12_clear = 12.3                 # decor >= 12.3 from the swept face: no 2-12 mm moving gap (V12)

    # ---- abdomen (world frame, lower left)
    abd_c, abd_ab, abd_ang = (-20.6, -14.6), (6.6, 4.9), 18.0      # ellipse centre, semi-axes, tilt (deg)
    sting_tip = (-29.0, -17.6)
    abd_stripes = (-2.4, 1.6)        # stripe centres along the abdomen axis (2.0 wide, 2.0 apart)

    # ---- arms (paws)
    leg_w = 10.0
    leg_end_r = 25.5
    leg_stripes = (19.6, 22.4)       # stripe centres, distance from O along the arm axis
    leg_stripe_w = 1.4

    # ---- wheel honeycomb
    hex_d = 4.0                      # corner-to-corner (SPEC "hex dimples D4 x 0.5")
    hex_wall = 1.0

    def __init__(self):
        self._cache = {}

    # ================================================================== head
    def ball_centre(self, C_h, s):
        return _pol(C_h, self.ant_r1, s * self.ant_a1)

    def stalk2d(self, C_h, s):
        stalk = g2.stadium(_pol(C_h, self.ant_r0, s * self.ant_a0), self.ball_centre(C_h, s), self.ant_w, TOL)
        # Tapered antenna base (fix round 2, V12 / sharp points): like the kitty's ear it sits on the head circle
        # from ant_base_angles[0] out to ant_base_angles[1], so beyond the crown edge the head is one cap + antenna
        # blob that meets the crown edge only where the head circle crosses it.  (A bare stalk left a notch
        # between its outer side and the head circle right at the crown edge: a 2-4 mm squeeze and a knife edge.)
        a0, a1 = (s * a for a in self.ant_base_angles)
        tri = g2.poly([tuple(_pol(C_h, self.ant_base_r, a0)), tuple(_pol(C_h, self.ant_base_r, a1)),
                       tuple(_pol(C_h, self.ant_taper_r, s * self.ant_taper_a))])
        if s < 0:
            tri = g2.poly([tuple(_pol(C_h, self.ant_base_r, a1)), tuple(_pol(C_h, self.ant_base_r, a0)),
                           tuple(_pol(C_h, self.ant_taper_r, s * self.ant_taper_a))])
        base = g2.grow(g2.grow(tri, 2.6, TOL), -0.6, TOL)          # = the kitty ear's rounding
        return g2.union([stalk, base])

    def face2d(self, C_h, p) -> CrossSection:
        head = g2.circle(C_h, self.face_r, 0.005)
        face = g2.closing(g2.union([head, self.stalk2d(C_h, -1), self.stalk2d(C_h, +1)]), self.root_fillet, TOL)
        balls = [g2.circle(self.ball_centre(C_h, s), self.ant_ball_d / 2, TOL) for s in (-1, 1)]
        return g2.closing(g2.union([face] + balls), self.neck_fillet, TOL)

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
            cc = C + np.array([s * self.cheek_xy[0], self.cheek_xy[1]])
            feats.append(Feature(f"cheek_{tag}", g2.ellipse(tuple(cc), *self.cheek_ab, 0.0, TOL), "deboss",
                                 self.cheek_depth))
            bc = self.ball_centre(C_h, s)
            feats.append(Feature(f"bobble_{tag}", g2.circle(bc, self.bobble_r, TOL), "dome", 0.6,
                                 center=tuple(bc), radius=self.bobble_r, edge_ok=True))
        # "u" smile: lower arc with round caps (cap polygons turned half a segment: no vertex on a corner)
        sc = C + np.array(self.smile_c)
        r0, r1 = self.smile_r - self.smile_w / 2, self.smile_r + self.smile_w / 2
        parts = [g2.sector(r0, r1, self.smile_a[0], self.smile_a[1], c=tuple(sc), tol=0.005)]
        for a in self.smile_a:
            e = sc + self.smile_r * np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
            parts.append(CrossSection.circle(self.smile_w / 2, 24).rotate(7.5).translate(tuple(e)))
        feats.append(Feature("smile", g2.clean(g2.union(parts), "cut"), "deboss", self.smile_depth))
        return feats

    # ================================================================== frame: flower backdrop
    def petal_centres(self, p):
        return [_pol(p.C_h, self.petal_R, 72 * k + self.petal_a0) for k in range(self.petal_n)]

    def backdrop2d(self, p) -> CrossSection:
        parts = [g2.circle(p.C_h, self.flower_disc_r, TOL)]
        parts += [g2.circle(c, self.petal_d / 2, TOL) for c in self.petal_centres(p)]
        w = self.max_half_w
        return g2.intersect(g2.union(parts), g2.poly([(-w, -100), (w, -100), (w, 150), (-w, 150)]))

    def backdrop_features(self, p, backdrop2d, body2d, swept_faceup2d) -> list[Feature]:
        """Petal outlines (1.6 inside the petal edge) and centre veins, 0.8 x 0.3, where the plate top is exposed
        (outside the body and the swept face, so they never meet the skid ribs)."""
        parts = []
        r = self.petal_d / 2 - 1.6
        for k, c in enumerate(self.petal_centres(p)):
            a = 72 * k + self.petal_a0
            parts.append(g2.difference(g2.circle(c, r + 0.4, TOL), g2.circle(c, r - 0.4, TOL)))
            parts.append(g2.stadium(_pol(p.C_h, self.petal_R - 2.0, a), _pol(p.C_h, self.petal_R + 3.5, a), 0.8, TOL))
        v = g2.difference(g2.union(parts), g2.grow(body2d, 0.8, TOL), g2.grow(swept_faceup2d, 0.8, TOL))
        v = g2.intersect(v, g2.grow(backdrop2d, -1.2, TOL))
        v = g2.drop_small(g2.opening(v, 0.6, TOL), 0.6)
        return [Feature("petal_lines", v, "deboss", 0.3)] if not v.is_empty() else []

    # ================================================================== frame: wings + striped bottom
    def _swept_face(self, p) -> CrossSection:
        """Swept(Face2D) (a superset of the core's Swept(FaceUp2D)), for the V12 keep-clear of the wings."""
        key = ("swept_face", p)
        if key not in self._cache:
            self._cache[key] = swept(self.face2d(p.C_h, p), p.P, p.psi_b, 41, allowance=0.1)
        return self._cache[key]

    def wing_lobe2d(self, s, k) -> CrossSection:
        (rx, ry), rr, (tx, ty), tr = self.wing_lobes[k]
        return CrossSection.batch_hull([g2.circle((s * rx, ry), rr, TOL), g2.circle((s * tx, ty), tr, TOL)])

    def wings2d(self, p) -> CrossSection:
        """Both wings, kept >= v12_clear from the swept face, plan corners rounded r 2.0."""
        key = ("wings", p)
        if key not in self._cache:
            w = g2.union([self.wing_lobe2d(s, k) for s in (-1, 1) for k in range(len(self.wing_lobes))])
            w = g2.difference(w, g2.grow(self._swept_face(p), self.v12_clear, 0.05))
            self._cache[key] = g2.opening(w, 4.0, TOL)
        return self._cache[key]

    def _abd_axis(self):
        a = math.radians(180.0 + self.abd_ang)
        return np.array([math.cos(a), math.sin(a)])       # unit vector toward the stinger

    def abdomen2d(self, p) -> CrossSection:
        """Oval bottom + tapered stinger, every convex corner rounded r 2.0."""
        oval = g2.ellipse(self.abd_c, self.abd_ab[0], self.abd_ab[1], self.abd_ang, TOL)
        u = self._abd_axis()
        t = np.array([-u[1], u[0]])
        base = np.asarray(self.abd_c) + u * (self.abd_ab[0] - 2.2)
        sting = g2.poly([base + 2.6 * t, base - 2.6 * t, np.asarray(self.sting_tip)])
        return g2.opening(g2.union([oval, sting]), 4.0, TOL)

    def body_decor2d(self, p) -> CrossSection:
        return g2.union([self.wings2d(p), self.abdomen2d(p)])

    def body_decor_features(self, p) -> list[Feature]:
        """Wing veins (0.8 x 0.4 groove 1.4 inside each lobe, open toward the root) and two 2.0 x 0.5 abdomen
        stripes.  Everything stays on the flat decor top (>= 0.9 inside its r 0.8 stepped top edge, so no
        sub-layer slivers are left where a groove would meet a fillet step) and off the funnel seat."""
        wings = self.wings2d(p)
        arms = g2.union([self.paw_plan_right(p), self.paw_plan_right(p).mirror((1.0, 0.0))])
        keep = g2.difference(g2.grow(wings, -1.2, TOL), g2.grow(arms, 1.0, TOL))
        feats = []
        for s, tag in ((-1, "L"), (1, "R")):
            rings = []
            for k in range(len(self.wing_lobes)):
                w = self.wing_lobe2d(s, k)
                ring = g2.difference(g2.grow(w, -1.4, TOL), g2.grow(w, -2.2, TOL))
                (rx, ry), rr = self.wing_lobes[k][:2]
                ring = g2.difference(ring, g2.circle((s * rx, ry), rr + 2.5, TOL))
                if k > 0:      # hindwing vein stops short of the forewing
                    ring = g2.difference(ring, g2.grow(self.wing_lobe2d(s, 0), 0.8, TOL))
                rings.append(ring)
            v = g2.drop_small(g2.opening(g2.intersect(g2.union(rings), keep), 0.6, TOL), 0.5)
            if not v.is_empty():
                feats.append(Feature(f"wing_vein_{tag}", v, "deboss", 0.4))
        u = self._abd_axis()
        c = np.asarray(self.abd_c)
        bands = g2.union([_band(c + d * u, u, 7.0, 1.0) for d in self.abd_stripes])
        bands = g2.intersect(bands, g2.grow(self.abdomen2d(p), -0.9, TOL))
        bands = g2.difference(bands, g2.circle((0, 0), p.paw_wall_r + 0.6, TOL))
        feats.append(Feature("abdomen_stripes", g2.drop_small(bands, 0.5), "deboss", 0.5))
        return feats

    # ================================================================== paws: striped bee arms
    def _arm_axis(self, p):
        a0, a1 = p.paw_span_R
        return _polO(1.0, 0.5 * (a0 + a1))

    def paw_plan_right(self, p) -> CrossSection:
        u = self._arm_axis(p)
        arm = g2.stadium(14.0 * u, (self.leg_end_r - self.leg_w / 2) * u, self.leg_w, TOL)
        # (fix round 1) a cuff with radial sides where the arm meets the 45 deg lip over the ball rim: the straight
        # arm sides met the lip cone at 74 deg, a sharp exposed corner at every layer (V12.corners); radial sides
        # meet it square, like the kitty's mitts
        a = math.degrees(math.atan2(u[1], u[0]))
        half = math.degrees(math.asin((self.leg_w / 2) / p.paw_lip_r)) + 0.5
        cuff = g2.sector(p.paw_lip_r - 0.5, 21.5, a - half, a + half, tol=TOL)
        return g2.union([arm, cuff])

    def paw_features_right(self, p, plan2d) -> list[Feature]:
        """Two 1.4 x 0.4 deboss stripes across the arm, on its flat top (>= 1.1 inside the r 1.0 stepped edge)."""
        u = self._arm_axis(p)
        flat = g2.grow(plan2d, -(p.frame_top_fillet + 0.1), TOL)
        return [Feature(f"stripe_{k}", g2.intersect(_band(d * u, u, 8.0, self.leg_stripe_w / 2), flat), "deboss", 0.4)
                for k, d in enumerate(self.leg_stripes)]

    # ================================================================== wheel: honeycomb pollen ball
    def wheel_relief2d(self, p) -> CrossSection:
        R = self.hex_d / 2
        d = R * math.sqrt(3.0) + self.hex_wall          # lattice spacing = across flats + wall
        hexagon = g2.poly([(R * math.cos(math.radians(60 * k + 30)), R * math.sin(math.radians(60 * k + 30)))
                           for k in range(6)])
        cells = []
        n = int(p.relief_r_max / d) + 3
        for i in range(-2 * n, 2 * n + 1):
            for j in range(-n, n + 1):
                x, y = d * (i + 0.5 * j), d * (math.sqrt(3) / 2) * j
                if math.hypot(x, y) - R <= p.relief_r_max:
                    cells.append(hexagon.translate((x, y)))
        clip = g2.difference(g2.circle((0, 0), p.relief_r_max, TOL),
                             g2.circle((p.r_k, 0.0), p.relief_knob_clear, TOL))
        rel = g2.intersect(g2.union(cells), clip)
        return g2.drop_small(g2.opening(rel, 0.8, 0.005), 1.5)
