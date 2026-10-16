"""Purr Kitty from the owner's sculpt (round 5).

The owner's Meshy model (sculpt/Yarn_Cuddle_Kitty_Meshy_AI.3mf, 58.2 x 75.0 x 18.9 mm) is the kitty: scaled x1.139
so that its yarn ball is the 36 mm escape wheel (ball centre on O), it becomes all three bodies (purrbobble/sculpt.py):
the head is its whole head (``head_blob``: ears and bow included), the spinning part is the centre of its yarn ball
(r 10), and everything else - cushion, body, arms, paws and feet, the ball's outer strands, tail - is the static frame
with the mechanism inside.

The skin hooks only give the mechanism core the outlines it needs:
* face2d: the sculpt's face (slice at z 13) - kept narrow below y 32 (a circle there), where the swinging head band
  must stay clear of the stop pads.
* backdrop2d: the sculpt's footprint (the cushion outline).
No face features, decor or relief: the sculpt carries them.  The wheel's umbrella is shrunk (param_overrides) so
that it hides under the sculpt's yarn ball; it is not part of the escapement (teeth and pallets are unchanged).
"""
from __future__ import annotations

import functools

from manifold3d import CrossSection

from .. import geom2d as g2
from .base import Skin

TOL = 0.01


class SculptKittySkin(Skin):
    name = "kitty"
    colors = {"frame": "#f6e7d3", "wheel": "#f2787d", "head": "#f6e7d3"}
    plate_color = None
    details_color = "#3a2723"

    # sculpt placement (face-up frame of the source mesh, x centred): ball centre and scale (ball r 15.8 -> 18.0)
    source = "sculpt/Yarn_Cuddle_Kitty_Meshy_AI.3mf"
    ball_c = (-0.6, 23.3)
    scale = 18.0 / 15.8
    # the mechanism axis sits mech_dx (world mm) right of the yarn ball's centre: the bow makes the sculpted head
    # heavier on its right, and the head's centre of mass must lie on the line through its pivot P (an off-centre
    # mass is a constant gravity torque when the toy is held up: V4 runs slow one way and jams at high friction)
    mech_dx = 1.22
    # as-printed mass budget (verification/v_escapement.py V13): the classic 50 g scaled with the footprint - the
    # owner's model at x1.14 is 66 x 85 mm against the classic 60 x 85 (frame mass does not enter the dynamics)
    mass_limit_g = 55.0
    # integration (purrbobble/sculpt.py)
    cap_r = 10.0            # spinning centre of the yarn ball
    cap_gap = 0.5           # radial gap cap <-> static ring (+ the variant's extra gap_xy)
    seam_chamfer = 0.6      # the static ring's inner edge is chamfered 45 deg from this far under the yarn surface
    # hidden flange ring on the wheel (r 14.7 -> 16.2, z 8.5-9.45 under the yarn ball's static ring): the wheel is
    # then 32.4 wide, more than the 31.7 small-parts cylinder (V10).  Limits: the head's hub collar is 17.81 from O
    # (deep 17.65; >= 1.4 clear), the chin's floor envelope at r 18.44, and the ring over it stays >= 2 thick
    flange_r = 16.2
    flange_z = (8.5, 9.45)
    cap_min_h = 1.5         # the cap is at least this tall above the umbrella top
    ring_pitch = 2.0        # skid rings on the umbrella top (the static ring floats on them)
    dish_d, dish_depth = 7.5, 3.0     # finger dish in the cap, centred at (r_k, 0) = (5, 0) (param_overrides)
    head_blob_z = 8.0       # the head is the sculpt above the neck line where it stands >= this tall (ears included)
    neck_y = 18.8           # neck line (the crease between the chin and the chest)
    float_z = 5.4           # lowest head floor where the head swings over its own uncovered footprint / cushion
    float_top = 14.0        # highest floor level considered
    floor_step = 0.2        # floors are quantised to this
    floor_rest = 0.2        # head floors clear the frame by gap_z + z_lift + this: face up, the head rests on its
                            # band's back ribs (gap_z lower than printed) and keeps one layer under its floors then
    t_min = 0.8             # the head keeps at least this much material under its surface (else: pocket)
    overhang_max = 0.9      # a floor terrace overhangs the head's material below it by at most this ...
    float_reach = 1.8       # ... or reaches at most this far beyond frame just under its seam (V9 float reach 1.9)
    leg_low_top = 4.27      # legs whose sweep passes under sculpt too thin for a cover_t frame cover over their top
                            # seam are lowered to this (1.27 tall); a cover >= cover_t runs over them
    cover_t = 1.25          # frame over the legs: at least this thick (low bosses where the sculpt is thinner;
                            # 1.25: a margin over the 1.2 wall rule once rounded to float32)
    ball_keep_r = 18.5      # the head body never swings over the yarn ball (r <= this about O)
    pad_back = 2.0          # stop pad backing (fill around each pad)
    # visible relief (sculpt.integrate): the cushion behind the head between the left ear and the bow (box x -16..-4,
    # y 44..56) is lowered to z 5.82 where the left ear's inner half swings over it (it stands 6.2-6.5): the ear's
    # floors then come down to ~6.44 and its root is deep enough for the V10 protrusion load (13.4 -> ~9.7 MPa).
    # About 31 mm2 of cushion lowered by <= 0.72 (mean 0.43).
    reliefs = (((-24.0, 40.0, -5.0, 52.0), (-16.0, 44.0, -4.0, 56.0), 5.82),)
    gap_xy, gap_z = 0.5, 0.4137      # (gap_z off round numbers too, see sculpt.GRID_OFFSET)
    head_slice_z = 13.0
    narrow_below_y = 32.0
    # the wheel's umbrella shrinks under the sculpt's yarn ball: r 15 (cone 45 deg from r 14.3 at z 8.0), top 10.5,
    # so the static ring of the ball above it stays >= 2 mm thick where the ball dips under the chin (nominal 2.2;
    # loose 1.8, its seams being z_lift wider)
    # The finger drives the wheel in the cap's dish at r 5 (r_k: also the lever arm of the V4 dynamics' finger load);
    # the classic recessed well is not cut (wheel_drive "dish").
    param_overrides = {"z_feat": 22.5, "R_u": 15.0, "umb_rim_z0": 8.7, "umb_rim_z1": 9.5, "z_umb_top": 10.5,
                       "r_k": 5.0, "wheel_drive": "dish"}

    def sculpt(self):
        from ..sculpt import REPO, load_sculpt
        bc = (self.ball_c[0] + self.mech_dx / self.scale, self.ball_c[1])
        return load_sculpt(str(REPO / self.source), bc, float(self.scale))

    @functools.lru_cache(maxsize=2)
    def _head_outline(self) -> CrossSection:
        """The head's face (slice at head_slice_z above the neck): the mechanism's face outlines."""
        K = self.sculpt()
        sl = K.slice(self.head_slice_z)
        hd = g2.intersect(sl, g2.poly([(-80, self.neck_y), (80, self.neck_y), (80, 120), (-80, 120)]))
        parts = sorted(hd.decompose(), key=lambda q: -q.area())
        return g2.opening(g2.closing(parts[0], 1.0, TOL), 3.0, TOL)

    @functools.lru_cache(maxsize=2)
    def head_blob(self) -> CrossSection:
        """The whole sculpted head (ears and bow included) seen from the top: above the neck line, the union of the
        sculpt's slices from head_blob_z up (the cheeks bulge out over the cushion), the pieces touching the face."""
        import numpy as np
        K = self.sculpt()
        ref = g2.grow(self._head_outline(), 0.5, TOL)
        upper = g2.poly([(-80, self.neck_y), (80, self.neck_y), (80, 120), (-80, 120)])
        keep = []
        for z in np.arange(self.head_blob_z, K.bounding_box()[5], 0.5):
            sl = g2.intersect(K.slice(float(z)), upper)
            keep += [q for q in sl.decompose() if not g2.intersect(q, ref).is_empty()]
        return g2.opening(g2.closing(g2.union(keep), 1.5, TOL), 1.0, TOL)

    # ------------------------------------------------------------------ head
    def face2d(self, C_h, p) -> CrossSection:
        head = self._head_outline()
        lower = g2.union([g2.circle(C_h, 16.0, 0.005),
                          g2.poly([(-80, self.narrow_below_y), (80, self.narrow_below_y), (80, 120), (-80, 120)])])
        face = g2.intersect(head, lower)
        parts = sorted(face.decompose(), key=lambda q: -q.area())
        return g2.opening(g2.closing(parts[0], 1.0, TOL), 4.0, TOL)

    def face_front2d(self, C_h, p, S=None) -> CrossSection:
        return self._head_outline()

    def face_features(self, C_h, p) -> list:
        return []

    # ------------------------------------------------------------------ frame
    def backdrop2d(self, p, S=None) -> CrossSection:
        K = self.sculpt()
        foot = K.slice(0.3)
        parts = sorted(foot.decompose(), key=lambda q: -q.area())
        return parts[0]
