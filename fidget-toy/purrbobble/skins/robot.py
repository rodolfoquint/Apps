"""Pip the Robot skin (SPEC section 4.4).

A friendly little robot peeking out of a round porthole, hugging a big orange gear-ball with two clamp hands.

Face2D (head frame, relative to C_h = P + (0, 11)):

* Head: a rounded "gumdrop" square 28.4 wide, top at C_h + 15 with r 7 corners (as the SPEC), and a U-shaped
  jaw (bottom corners r 11).  The chin is placed from the ball, 1.95 above the rim (y = R_u + 1.95), so the
  face <-> ball rim gap is 1.45-1.95 over the swing in every variant (V6 1.4-2.0, V12 < 2 mm).
* Antenna: stadium 6 wide from C_h + (0, 14) to C_h + (0, 19) with a D8 ball at C_h + (0, 20.5) (SPEC).
* Ear bolts: discs r 4.0 at C_h + (+-16.6, 2.0), at eye level, joined to the head by r 1.5 fillets.

Why not the SPEC's 34 x 28 rectangle (C_h + (0, 1), r 7) with r 3.5 bolts at C_h + (+-17.5, 0)?  Its lower
corners sweep through the stop-pad zones: the face itself (not the leg flank) then slides 0.06-0.46 mm past the
four stop pads over the whole swing, and at the print pose the frame comes within 0.34 of the head (V7 fails).
Below y = C_h - 4.7 the face must stay inside |x| <= 14.7, and for 5.7 <= |x| <= 12.6 above y = 20.94 (stop pads
grown by the swept gap + 0.05, swept back into the head frame); the gumdrop keeps >= 0.37 from that zone in
every variant and the head <-> pad clearances are then identical to the kitty's.  The SPEC rectangle's flat
chin (C_h - 13) would also leave a 4.1-4.7 mm face <-> ball gap that opens and closes with the swing (V12).
With the narrower head the ear bolts move in to x = 16.6 (r 4.0) so they keep a full-width root.

Face features (z 15.4): a debossed visor (stadium 22 x 10, 0.5 deep; SPEC 24 x 9) holding two big D7 domed LED
eyes (SPEC D6) on round columns with a 0.4 bezel, each with a D2 x 0.4 highlight dimple; a smiling three-slot
mouth grille (1.3 wide, 0.5 deep); two round cheek lights (D3 x 0.3); a cross-head screw in each ear bolt and a
D4.6 light-bulb dome on the antenna ball.

Frame: a porthole back plate (disc r 30 at C_h - (0, 3.2); SPEC r 27 at C_h - (0, 4)) - enlarged so it also
contains the antenna sweep and reads as one clean circle - with D2 x 0.4 rivet dimples and a 0.8 x 0.3 porthole
frame line where the plate top is exposed; two rounded boots under the ball with a sole line; clamp hands: a
three-finger gripper bar over the ball rim (two finger slots and a knuckle groove) and a wrist block with a hex
bolt socket (all 0.5 deep).

Wheel: a 0.6 x 0.5 groove tracing a 24-tooth gear outline around the rim and a bold outlined power symbol, set
upright at the print pose.

Inertia (solid PLA, verification/v_basic.py --skin robot): I_h = 4.96e-6 kg m^2 about P, centre of mass 11.2 mm
above P (target 4-8e-6, 8-14 mm) - no pockets needed.
"""
from __future__ import annotations

import math

import numpy as np
from manifold3d import CrossSection

from .. import geom2d as g2
from .base import Feature, Skin

TOL = 0.01


def _arc_pts(c, r, a0, a1, n):
    t = np.radians(np.linspace(a0, a1, n))
    return np.c_[c[0] + r * np.cos(t), c[1] + r * np.sin(t)]


def _rrect(c, w, h, r, tol=TOL) -> CrossSection:
    """Rounded rectangle w x h (corner radius r) centred at c."""
    cx, cy = c
    core = g2.poly([(cx - w / 2 + r, cy - h / 2 + r), (cx + w / 2 - r, cy - h / 2 + r),
                    (cx + w / 2 - r, cy + h / 2 - r), (cx - w / 2 + r, cy + h / 2 - r)])
    return g2.grow(core, r, tol)


def _gumdrop(cx, half_w, y0, y1, r_top, r_bot, tol=TOL) -> CrossSection:
    """Rounded rectangle with different top / bottom corner radii (half width half_w, from y0 to y1)."""
    nt, nb = (g2.nseg(r, tol) // 4 + 1 for r in (r_top, r_bot))
    pts = []
    pts += list(_arc_pts((cx + half_w - r_bot, y0 + r_bot), r_bot, -90, 0, nb))
    pts += list(_arc_pts((cx + half_w - r_top, y1 - r_top), r_top, 0, 90, nt))
    pts += list(_arc_pts((cx - half_w + r_top, y1 - r_top), r_top, 90, 180, nt))
    pts += list(_arc_pts((cx - half_w + r_bot, y0 + r_bot), r_bot, 180, 270, nb))
    a = np.asarray(pts)
    keep = np.r_[True, np.hypot(*np.diff(a, axis=0).T) > 1e-6]
    return g2.poly(a[keep])


class RobotSkin(Skin):
    name = "robot"
    colors = {"frame": "#86b9f0", "wheel": "#ffb347", "head": "#d8dfe8"}

    # ------------------------------------------------------------------ face (relative to C_h)
    head_half_w = 14.2
    head_top = 15.0            # SPEC: 28 tall rectangle centred at C_h + (0, 1)
    chin_gap = 1.95            # chin 1.95 above the ball rim (R_u) at rest: 1.45-1.95 over the swing
    head_r_top = 7.0
    head_r_bot = 11.0
    antenna_w = 6.0
    antenna_y = (14.0, 19.0)
    antenna_ball = (20.5, 4.0)  # (y, radius)
    bolt_xy, bolt_r = (15.2, 1.0), 3.6   # inside the crown edge (r_P <= 22.97 < 23.05): no island beyond it (V12)
    face_close = 1.5

    visor_wh = (22.0, 10.0)    # SPEC 24 x 9 (r 4.5); stadium sized for the narrower head and the D7 eyes
    visor_y = 3.5
    visor_depth = 0.5
    eye_d, eye_x, eye_bezel = 7.0, 5.6, 0.4
    hl_d, hl_dxy, hl_depth = 2.0, (1.2, 1.2), 0.4
    mouth_y, mouth_R, mouth_w, mouth_depth = -8.2, 8.5, 1.3, 0.5
    mouth_angles = (-25.0, 0.0, 25.0)
    mouth_slot_half = 4.8      # deg, half angular length of each slot centre line (walls between slots ~1.0)
    cheek_xy, cheek_d, cheek_depth = (8.3, -4.6), 3.0, 0.3
    screw_len, screw_w, screw_depth = 3.2, 0.8, 0.4
    bulb_d = 4.6               # antenna bulb dome (the ball's flat top is D4.9 inside the r 1.5 rim)

    # ------------------------------------------------------------------ head
    def head2d(self, C_h, p) -> CrossSection:
        cx, cy = C_h
        # the chin is placed from the ball (O), not from C_h, so the face <-> ball rim gap is the same in every
        # variant (deep / shallow move P and C_h by -+0.24)
        y0 = p.O[1] + p.R_u + self.chin_gap
        return _gumdrop(cx, self.head_half_w, y0, cy + self.head_top, self.head_r_top, self.head_r_bot)

    def face2d(self, C_h, p) -> CrossSection:
        cx, cy = C_h
        parts = [self.head2d(C_h, p),
                 g2.stadium((cx, cy + self.antenna_y[0]), (cx, cy + self.antenna_y[1]), self.antenna_w, TOL),
                 g2.circle((cx, cy + self.antenna_ball[0]), self.antenna_ball[1], TOL)]
        for s in (-1, 1):
            parts.append(g2.circle((cx + s * self.bolt_xy[0], cy + self.bolt_xy[1]), self.bolt_r, TOL))
        return g2.closing(g2.union(parts), self.face_close, 0.02).simplify(0.002)

    def face_features(self, C_h, p) -> list[Feature]:
        C = np.asarray(C_h, float)
        feats = []
        vw, vh = self.visor_wh
        vc = C + (0.0, self.visor_y)
        visor = g2.stadium(vc + (-(vw - vh) / 2, 0.0), vc + ((vw - vh) / 2, 0.0), vh, TOL)
        eyes = []
        for s, tag in ((-1, "L"), (1, "R")):
            ec = vc + (s * self.eye_x, 0.0)
            eyes.append(ec)
            feats.append(Feature(f"eye_{tag}", g2.circle(ec, self.eye_d / 2, TOL), "dome", 0.6,
                                 center=tuple(ec), radius=self.eye_d / 2))
            hc = ec + np.array(self.hl_dxy)
            feats.append(Feature(f"eye_highlight_{tag}", g2.circle(hc, self.hl_d / 2, TOL), "dimple", self.hl_depth,
                                 center=tuple(hc), radius=self.hl_d / 2, on=f"eye_{tag}"))
        # the visor recess goes around the eyes: each LED dome sits on its own round column whose top (a thin
        # bezel ring) stays at the face top (z 15.4), 0.5 above the visor floor
        holes = [g2.circle(e, self.eye_d / 2 + self.eye_bezel, TOL) for e in eyes]
        feats.insert(0, Feature("visor", g2.difference(visor, *holes), "deboss", self.visor_depth))
        # smiling mouth grille: three slots on an arc (centre above the mouth)
        mc = C + (0.0, self.mouth_y + self.mouth_R)
        slots = []
        for a in self.mouth_angles:
            pts = _arc_pts(mc, self.mouth_R, -90 + a - self.mouth_slot_half, -90 + a + self.mouth_slot_half, 9)
            slots.append(g2.polyline_stadium(pts, self.mouth_w, TOL))
        feats.append(Feature("mouth", g2.union(slots), "deboss", self.mouth_depth))
        for s, tag in ((-1, "L"), (1, "R")):
            cc = C + (s * self.cheek_xy[0], self.cheek_xy[1])
            feats.append(Feature(f"cheek_{tag}", g2.circle(cc, self.cheek_d / 2, TOL), "deboss", self.cheek_depth))
            # cross-head screw in each ear bolt (closer than 3 mm to the edge: the bolt is only D8)
            bc = C + (s * self.bolt_xy[0], self.bolt_xy[1])
            L, w = self.screw_len / 2, self.screw_w
            cross = g2.union([g2.stadium(bc + (-L, 0), bc + (L, 0), w, TOL), g2.stadium(bc + (0, -L), bc + (0, L), w, TOL)])
            feats.append(Feature(f"ear_screw_{tag}", cross, "deboss", self.screw_depth, edge_ok=True))
        # antenna light bulb: a small dome on the flat top of the antenna ball (inside its r 1.5 rim)
        bc = C + (0.0, self.antenna_ball[0])
        feats.append(Feature("antenna_bulb", g2.circle(bc, self.bulb_d / 2, TOL), "dome", 0.6,
                             center=tuple(bc), radius=self.bulb_d / 2, edge_ok=True))
        return feats

    # ------------------------------------------------------------------ frame
    porthole_c, porthole_r = (0.0, -3.2), 30.0      # relative to C_h; SPEC: r 27 at C_h - (0, 4)
    rivet_d, rivet_depth, rivet_inset, rivet_pitch = 2.0, 0.4, 1.6, 10.0
    ring_inset = 5.1

    def backdrop2d(self, p) -> CrossSection:
        cx, cy = p.C_h
        return g2.circle((cx + self.porthole_c[0], cy + self.porthole_c[1]), self.porthole_r, 0.02)

    def backdrop_features(self, p, backdrop2d, body2d, swept_faceup2d) -> list[Feature]:
        """Rivet dimples around the porthole rim, only where the plate top is exposed (never under the fill /
        roof body, and clear of the head's swept footprint where the skid ribs stand)."""
        cx, cy = p.C_h
        c = (cx + self.porthole_c[0], cy + self.porthole_c[1])
        rr = self.porthole_r - self.rivet_inset - self.rivet_d / 2 - 0.2
        keep = g2.difference(g2.grow(backdrop2d, -self.rivet_inset, TOL),
                             g2.grow(body2d, 1.0, TOL), g2.grow(swept_faceup2d, 1.0, TOL))
        feats = []
        n = int(round(2 * math.pi * rr / self.rivet_pitch))
        for k in range(n):
            a = math.radians(90.0 + (k + 0.5) * 360.0 / n)
            q = (c[0] + rr * math.cos(a), c[1] + rr * math.sin(a))
            disc = g2.circle(q, self.rivet_d / 2, TOL)
            if g2.difference(disc, keep).area() > 1e-6:
                continue
            feats.append(Feature(f"rivet_{k}", disc, "dimple", self.rivet_depth, center=q, radius=self.rivet_d / 2))
        # porthole frame line inside the rivet ring (0.8 wide x 0.3 deep), where exposed
        rg = self.porthole_r - self.ring_inset
        ring = g2.difference(g2.circle(c, rg + 0.4, TOL), g2.circle(c, rg - 0.4, TOL))
        ring = g2.drop_small(g2.opening(g2.intersect(ring, keep), 0.6, TOL), 2.0)
        if not ring.is_empty():
            feats.append(Feature("porthole_ring", ring, "deboss", 0.3))
        return feats

    boot_xy, boot_wh, boot_r = (8.8, -19.4), (10.4, 4.6), 2.2

    def body_decor2d(self, p) -> CrossSection:
        bx, by = self.boot_xy
        return g2.union([_rrect((s * bx, by), *self.boot_wh, self.boot_r) for s in (-1, 1)])

    def body_decor_features(self, p) -> list[Feature]:
        bx, by = self.boot_xy
        feats = []
        for s, tag in ((-1, "L"), (1, "R")):
            x0 = s * bx
            feats.append(Feature(f"boot_line_{tag}", g2.stadium((x0 - 2.2, by - 0.3), (x0 + 2.2, by - 0.3), 0.8, TOL),
                                 "deboss", 0.4))
        return feats

    # clamp hands: a three-finger gripper bar over the ball rim and a wrist block (radii about O)
    knuckle_r = 21.0     # knuckle groove centre line (finger / palm boundary)
    jaw_r = 22.8         # outer edge of the gripper bar (>= 1.25 outside the groove: clear of the r 1.0 fillet)
    wrist_r = 26.6       # wrist block outer end
    wrist_w = 10.0       # wrist block width (tangential)
    finger_gap = 5.8     # deg, half angle between the two finger slots
    groove_w = 1.1       # finger slots and knuckle groove: 1.1 wide x 0.5 deep
    hex_r, hex_c = 1.6, 23.8   # hex bolt socket: circumradius and centre radius

    def paw_plan_right(self, p) -> CrossSection:
        a0, a1 = p.paw_span_R
        jaw = g2.sector(p.paw_lip_r, self.jaw_r, a0, a1, tol=TOL)
        am = math.radians(0.5 * (a0 + a1))
        u = np.array([math.cos(am), math.sin(am)])
        t = np.array([-u[1], u[0]])
        h, rc = self.wrist_w / 2, 2.5
        r0, r1 = self.knuckle_r, self.wrist_r
        wrist = g2.grow(g2.poly([u * (r0 + rc) + t * (h - rc), u * (r1 - rc) + t * (h - rc),
                                 u * (r1 - rc) - t * (h - rc), u * (r0 + rc) - t * (h - rc)]), rc, TOL)
        return g2.union([jaw, wrist])

    def paw_features_right(self, p, plan2d) -> list[Feature]:
        a0, a1 = p.paw_span_R
        am = 0.5 * (a0 + a1)
        u = np.array([math.cos(math.radians(am)), math.sin(math.radians(am))])
        w = self.groove_w
        feats = []
        # three fingers: two radial slots from the rim (clear of the lip's top fillet) to the knuckle groove
        for k, da in enumerate((-self.finger_gap, self.finger_gap)):
            v = np.array([math.cos(math.radians(am + da)), math.sin(math.radians(am + da))])
            feats.append(Feature(f"finger_slot_{k}", g2.stadium(v * 18.8, v * self.knuckle_r, w, TOL), "deboss", 0.5))
        pts = _arc_pts((0.0, 0.0), self.knuckle_r, am - 10.5, am + 10.5, 11)
        feats.append(Feature("knuckle_groove", g2.polyline_stadium(pts, w, TOL), "deboss", 0.5))
        # hex bolt socket on the wrist (a flat faces the knuckle groove: >= 0.85 land)
        c = u * self.hex_c
        hexagon = g2.poly([c + self.hex_r * np.array([math.cos(math.radians(30 + 60 * k + am)),
                                                      math.sin(math.radians(30 + 60 * k + am))]) for k in range(6)])
        feats.append(Feature("hex_bolt", hexagon, "deboss", 0.5))
        return feats

    # ------------------------------------------------------------------ wheel
    gear_n = 24
    gear_r = (14.2, 15.8)       # root / tip radius of the traced gear outline
    gear_flank = 0.18           # fraction of the tooth pitch taken by each flank
    power_c = (-4.4, 0.0)       # wheel frame
    power_R = 4.3               # ring centre-line radius of the power glyph
    power_stroke = 1.8          # glyph stroke (traced by a 0.6 outline groove)
    power_gap = 100.0           # deg, opening of the ring (>= 0.85 land between the stem and ring grooves)
    power_stem = (0.4, 6.0)     # stem from / to (along the glyph's up direction)

    def _gear_outline(self, p) -> CrossSection:
        r0, r1 = self.gear_r
        n = self.gear_n
        pitch = 360.0 / n
        f = self.gear_flank * pitch
        land = (pitch - 2 * f) / 2
        pts = []
        for k in range(n):
            a = k * pitch
            for ang, r in ((a, r0), (a + land, r0), (a + land + f, r1), (a + 2 * land + f, r1)):
                pts.append((r * math.cos(math.radians(ang)), r * math.sin(math.radians(ang))))
        return g2.poly(pts)

    def _power_glyph(self, p) -> CrossSection:
        up = 90.0 - p.phi_print                     # upright at the print pose
        c = np.asarray(self.power_c, float)
        R, w = self.power_R, self.power_stroke
        a_gap = self.power_gap / 2
        ring = g2.sector(R - w / 2, R + w / 2, up + a_gap, up + 360.0 - a_gap, c=tuple(c), tol=TOL)
        ends = []
        for a in (up + a_gap, up - a_gap):
            q = c + R * np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
            ends.append(g2.circle(q, w / 2, TOL))
        u = np.array([math.cos(math.radians(up)), math.sin(math.radians(up))])
        stem = g2.stadium(c + u * self.power_stem[0], c + u * self.power_stem[1], w, TOL)
        return g2.union([ring, stem] + ends)

    def wheel_relief2d(self, p) -> CrossSection:
        w = p.relief_w
        gear = self._gear_outline(p)
        gear_groove = g2.difference(g2.grow(gear, w / 2, TOL), g2.grow(gear, -w / 2, TOL))
        glyph = self._power_glyph(p)
        glyph_groove = g2.difference(g2.grow(glyph, w / 2, TOL), g2.grow(glyph, -w / 2, TOL))
        return g2.union([gear_groove, glyph_groove])
