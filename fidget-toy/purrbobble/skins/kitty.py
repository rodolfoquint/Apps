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
    param_overrides = {"face_pillow_xy": 4.0, "face_pillow_z": 2.0, "face_pillow_steps": 20,
                       "relief_w": 0.8, "relief_depth": 0.75, "relief_bevel": 0.3}

    # face outline (SPEC 4.4; unchanged by the restyle)
    face_r = 16.0
    ear_base_r = 14.72
    ear_base_angles = (14.0, 54.0)
    ear_tip_r = 24.0
    ear_tip_angle = 34.0
    ear_grow, ear_shrink = 2.6, 0.6

    # ---------------------------------------------------------------- concept head (round 4)
    # The concept's wide "mochi" head is built as a front-layer-only widening (face_front2d): a rounded rectangle
    # +-21.5 x (C_h -16.2 .. +13.3), two fur tufts per cheek and forehead curls that break the silhouette.  The core
    # keeps only what rides on the crown roof (or overhangs the full-height head by <= 1.5) and stays >= 12 mm from
    # the paws (core2d.front_extension), so the head is widest at the cheeks, where the concept is.
    mochi_hw, mochi_y, mochi_r = 21.5, (-16.2, 13.3), 9.0
    cheek_tufts = ((21.4, -4.2, 2.6), (21.0, 1.3, 2.6))          # (x, y, r) relative to C_h, mirrored
    curls = ((-5.6, 13.8, 1.6), (-3.2, 15.5, 1.9), (-0.4, 16.3, 1.9))

    # face features (relative to C_h); the front layer is a pillow (param_overrides face_pillow_*): its top edge
    # rounds down 2.0 over the outer 4.0, and every raised / debossed feature is draped over it
    eye_d, eye_xy = 8.0, (10.0, -2.9)
    hl_big = (2.4, (-0.8, 1.9))          # diameter, offset from the eye centre (upper-left in both eyes)
    hl_small = (1.0, (2.3, -1.8))
    hl_depth = 0.65                      # through the 0.6 dark dome into the head colour
    nose_wh, nose_xy = (3.0, 1.6), (0.0, -4.7)
    mouth_top, mouth_rx, mouth_ry = -6.2, 2.7, 4.8
    tongue_c, tongue_ab = (0.0, -9.4), (1.7, 1.3)
    blush_ab, blush_xy = (5.2, 4.6), (14.0, -9.3)
    brow_xy, brow_len, brow_tilt = (9.7, 5.3), 2.4, 15.0
    inner_ear_inset = 2.4
    bow_c, bow_angle = (6.8, 11.6), -32.0      # knot centre (rel. C_h, inner base of the right ear), lobe axis tilt
    bow_span, bow_h = 5.8, 3.5                 # lobe length from the knot, lobe half-height

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

    def face_front2d(self, C_h, p, S=None) -> CrossSection:
        C = np.asarray(C_h, float)
        y0, y1 = (C[1] + v for v in self.mochi_y)
        r = self.mochi_r
        core = g2.poly([(-self.mochi_hw + r, y0 + r), (self.mochi_hw - r, y0 + r),
                        (self.mochi_hw - r, y1 - r), (-self.mochi_hw + r, y1 - r)])
        parts = [g2.grow(core, r, TOL)]
        for x, y, rr in self.cheek_tufts:
            parts += [g2.circle((C[0] + s * x, C[1] + y), rr, TOL) for s in (-1, 1)]
        parts += [g2.circle((C[0] + x, C[1] + y), rr, TOL) for x, y, rr in self.curls]
        parts.append(self._bow2d(C))
        return g2.union(parts)

    def _mouth2d(self, C):
        """Open "D" mouth under a hooked "w" top line."""
        top = C[1] + self.mouth_top
        oval = g2.ellipse((C[0], top), self.mouth_rx, self.mouth_ry, 0.0, TOL)
        below = g2.poly([(C[0] - 9, top), (C[0] + 9, top), (C[0] + 9, top - 9), (C[0] - 9, top - 9)])
        mouth = g2.intersect(oval, below)
        bites = [g2.circle((C[0] + s * 1.3, top + 0.45), 1.05, TOL) for s in (-1, 1)]
        return g2.opening(g2.difference(mouth, *bites), 0.8, TOL)

    def _smile_hooks2d(self, C):
        """The "w" line's up-curled ends: two short arcs beside the mouth corners."""
        top = C[1] + self.mouth_top
        out = []
        for s in (-1, 1):
            c = np.array([C[0] + s * 3.55, top + 0.15])
            arc = [tuple(c + 0.9 * np.array([s * math.cos(t), math.sin(t)]))
                   for t in np.radians(np.linspace(-150.0, -10.0, 8))]
            out.append(g2.polyline_stadium(arc, 0.8, TOL))
        return g2.union(out)

    def _bow2d(self, C):
        """Two puffy lobes: ellipses flaring from the knot (wider at their outer ends)."""
        c = C + np.array(self.bow_c)
        lobes = []
        for s in (-1, 1):
            e = g2.ellipse((s * self.bow_span * 0.52, 0.0), self.bow_span * 0.52, self.bow_h, 0.0, TOL)
            pinch = g2.poly([(0.0, -0.9), (s * self.bow_span * 1.2, -self.bow_h * 1.3),
                             (s * self.bow_span * 1.2, self.bow_h * 1.3), (0.0, 0.9)])
            lobes.append(g2.intersect(e, pinch))
        bow = g2.union(lobes).rotate(self.bow_angle).translate(tuple(c))
        return g2.opening(g2.union([bow, self._bow_knot2d(C)]), 0.8, TOL)

    def _bow_knot2d(self, C):
        return g2.ellipse(tuple(C + np.array(self.bow_c)), 1.8, 2.2, self.bow_angle, TOL)

    def face_features(self, C_h, p) -> list[Feature]:
        C = np.asarray(C_h, float)
        feats = []
        bow = self._bow2d(C)
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
                                                            0.0, TOL), "raise", 0.4, color="accent"))
            # brow marks: tiny curved strokes above the eyes
            bc = C + np.array([s * self.brow_xy[0], self.brow_xy[1]])
            u = _rot((1.0, 0.0), -s * self.brow_tilt)
            n_ = np.array([-u[1], u[0]])
            pts = [tuple(bc + u * t * self.brow_len / 2 + n_ * 0.35 * (1 - t * t)) for t in np.linspace(-1, 1, 7)]
            feats.append(Feature(f"brow_{tag}", g2.polyline_stadium(pts, 0.8, TOL), "deboss", 0.4))
            # inner ears: recessed, coral floor
            inner = g2.grow(self.ear2d(C_h, s), -self.inner_ear_inset, TOL)
            inner = g2.difference(inner, g2.circle(C_h, self.face_r - 1.6, TOL))
            if s > 0:
                inner = g2.difference(inner, g2.grow(bow, 0.8, TOL))
            inner = g2.drop_small(g2.opening(inner, 1.2, TOL), 1.0)
            if not inner.is_empty():
                feats.append(Feature(f"inner_ear_{tag}", inner, "deboss", 0.5, color="accent"))
        # nose: small rounded triangle, point down
        w, h = self.nose_wh
        nc = C + np.array(self.nose_xy)
        tri = g2.poly([nc + (-w / 2, h / 2), nc + (w / 2, h / 2), nc + (0.0, -h / 2)])
        feats.append(Feature("nose", g2.opening(tri, 0.7, 0.005), "raise", 0.6, color="details"))
        # recessed open mouth (dark floor) around a flush tongue (coral inlay), hooked smile ends
        mouth = self._mouth2d(C)
        tongue = g2.intersect(g2.ellipse(tuple(C + np.array(self.tongue_c)), *self.tongue_ab, 0.0, TOL),
                              g2.grow(mouth, -0.5, TOL))
        tongue = g2.opening(tongue, 0.8, TOL)
        feats.append(Feature("mouth", g2.opening(g2.difference(mouth, tongue), 0.6, TOL), "deboss", 0.5,
                             color="details"))
        feats.append(Feature("tongue", tongue, "inlay", 0.4, color="accent"))
        feats.append(Feature("smile_hooks", self._smile_hooks2d(C), "raise", 0.5, color="details"))
        # forehead fur curls: bumps of the front-layer outline (face_front2d), rounded by the pillow, with a short
        # groove under each (a raised curl on the pillow's slope would stand out as a sharp point, V12)
        for k, (x, y, r) in enumerate(self.curls[:-1]):
            x2, y2, _ = self.curls[k + 1]
            m = C + np.array([(x + x2) / 2, (y + y2) / 2])
            d = np.array([x2 - x, y2 - y]) / math.hypot(x2 - x, y2 - y)
            nrm = np.array([d[1], -d[0]])
            feats.append(Feature(f"curl_groove_{k}", g2.stadium(tuple(m + nrm * 0.2), tuple(m - nrm * 2.4), 0.8, TOL),
                                 "deboss", 0.4))
        # big puffy bow on the right ear base: two lobes and a proud knot (coral)
        feats.append(Feature("bow", g2.difference(bow, g2.grow(self._bow_knot2d(C), -0.6, TOL)), "raise", 1.2,
                             round=1.0, color="accent"))
        feats.append(Feature("bow_knot", self._bow_knot2d(C), "raise", 1.6, round=0.9, color="accent"))
        return feats

    # ------------------------------------------------------------------ cushion (back plate)
    # concept: a cloud of big scallops (r 9 lobes every ~14 mm, tips 5 outside the character), a raised piping bead
    # along the edge and raised, pillowed quilting diamonds (all on top of the 2.0 plate, <= 1.0 proud: the head
    # swings over the cushion from z 3.0, V12)
    cushion_out = 5.0
    scallop_r = 9.0
    scallop_step = 14.0
    bead_w, bead_h, bead_gap = 2.8, 1.0, 0.7          # piping: width, height, gap to the quilted field
    quilt_pitch, quilt_angle, quilt_groove = 6.0, 50.0, 0.9
    quilt_h, quilt_round = 0.7, 0.6

    def backdrop2d(self, p, S) -> CrossSection:
        """Big scallops on the character outline smoothed and grown by cushion_out - scallop_r."""
        base = g2.union([S["body_pre2d"], g2.grow(S["swept_faceup2d"], 0.6, TOL)])
        core = g2.grow(base, self.cushion_out - self.scallop_r, TOL)
        core = g2.opening(g2.closing(core, 7.0, 0.02), 4.0, 0.02)
        lobes = []
        for poly in core.to_polygons():
            pts = np.asarray(poly, float)
            if len(pts) < 3:
                continue
            seg = np.diff(np.vstack([pts, pts[:1]]), axis=0)
            L = np.r_[0.0, np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))]
            n = max(8, int(round(L[-1] / self.scallop_step)))
            # start the lobes at the top centre so the outline is symmetric
            k0 = int(np.argmax(pts[:, 1] - 0.01 * np.abs(pts[:, 0])))
            for t in (L[k0] + np.linspace(0.0, L[-1], n, endpoint=False)) % L[-1]:
                k = int(np.searchsorted(L, t, side="right") - 1)
                fr = (t - L[k]) / max(L[k + 1] - L[k], 1e-9)
                lobes.append(g2.circle(tuple(pts[k] + fr * seg[k]), self.scallop_r, TOL))
        # never closer than 1.5 to the character: a scallop dip flush with the body would trim Body2D there and
        # leave slivers against the crown recess steps
        return g2.union([g2.closing(g2.union([core] + lobes), 0.6, TOL), g2.grow(base, 1.5, TOL)])

    def backdrop_features(self, p, backdrop2d, body2d, swept_faceup2d) -> list[Feature]:
        """Piping bead along the edge and quilted pillow diamonds, raised on the exposed plate (never under the
        swinging head or the body)."""
        free = g2.difference(g2.grow(backdrop2d, -0.6, TOL), g2.grow(body2d, 0.6, TOL),
                             g2.grow(swept_faceup2d, 0.8, TOL))
        pd = getattr(self, "_plate_decor2d", None)
        if pd is not None and not pd.is_empty():
            free = g2.difference(free, g2.grow(pd, 0.6, TOL))
        inner = g2.grow(backdrop2d, -(0.6 + self.bead_w), TOL)
        bead = g2.drop_small(g2.opening(g2.difference(free, inner), 1.4, TOL), 2.0)
        field = g2.intersect(free, g2.grow(inner, -self.bead_gap, TOL))
        lines = []
        bx = backdrop2d.bounds()
        span = max(bx[2] - bx[0], bx[3] - bx[1]) + 40.0
        cx, cy = 0.0, 0.5 * (bx[1] + bx[3])
        for sgn in (-1, 1):
            a = math.radians(sgn * self.quilt_angle)
            d = np.array([math.cos(a), math.sin(a)])
            nrm = np.array([-d[1], d[0]])
            for k in range(-int(span / self.quilt_pitch), int(span / self.quilt_pitch) + 1):
                o = np.array([cx, cy]) + nrm * (k + 0.5) * self.quilt_pitch
                lines.append(g2.stadium(tuple(o - d * span / 2), tuple(o + d * span / 2), self.quilt_groove, TOL))
        cells = g2.difference(field, g2.union(lines))
        cells = g2.drop_small(g2.opening(cells, 1.4, TOL), 3.0)
        return [Feature("piping", bead, "raise", self.bead_h, round=self.bead_h),
                Feature("quilting", cells, "raise", self.quilt_h, round=self.quilt_round)]

    # ------------------------------------------------------------------ torso, tail, feet (round 4)
    # the cream torso outline (concept: a pear under the chin); the crown ring around the head is cushion-coloured
    torso_pts = ((0.0, 24.0), (10.0, 23.2), (15.0, 20.4), (19.0, 17.0), (22.3, 12.5), (24.6, 4.0), (25.6, -7.0), (24.2, -14.0),
                 (19.0, -19.8), (0.0, -20.5))
    belly_z, belly_round = (11.9, (3.0, 1.5))
    tail_path = ((24.0, -15.0), (28.6, -6.0), (29.4, 2.5), (27.6, 8.6), (24.0, 11.4), (21.0, 10.4))
    tail_w = 5.4
    foot_c, foot_ab, foot_tilt = (19.0, -14.0), (8.0, 8.6), -12.0
    foot_span = (-60.0, -15.0)
    # domes start above the lip underside (z <= 14.7): a terrace crossing the 45 deg lip cone leaves pinch vertices
    foot_z1, foot_round = 16.6, (4.0, 1.75)
    beans = ((-0.9, -1.8, 3.0, 3.15), (4.7, 0.9, 1.3, 1.3), (2.7, 3.7, 1.4, 1.4), (-1.1, 4.1, 1.45, 1.45))

    def torso2d(self, p, S=None) -> CrossSection:
        pts = list(self.torso_pts)
        ring = pts + [(-x, y) for x, y in reversed(pts[1:-1])]
        return g2.opening(g2.closing(g2.poly(ring), 3.0, TOL), 3.0, TOL)

    def body_tiers(self, p, S=None) -> list:
        """A pillowy torso: the body top inside the torso outline rises to z 11.9 (the ball stays 1.4 prouder)."""
        from .base import Tier
        return [Tier("belly", self.torso2d(p, S), self.belly_z, *self.belly_round)]

    def plate_decor(self, p, S=None) -> list:
        """A round tail lying on the cushion, curling up the right side and tucking in behind the mitt."""
        from .base import Tier
        tail = g2.polyline_stadium(list(self.tail_path), self.tail_w, TOL)
        r = self.tail_w / 2
        t = Tier("tail", tail, p.z_bp + self.tail_w, r, r)
        self._plate_decor2d = tail
        return [t]

    def body_decor2d(self, p) -> CrossSection | None:
        return None

    def body_decor_features(self, p) -> list[Feature]:
        return []

    # ------------------------------------------------------------------ paws and feet (lip pieces)
    def paw_plan_right(self, p) -> CrossSection:
        """Mitt: the paw span out to r 23.6 plus an egg-shaped mitt (core clips it to the span, r >= 17.0)."""
        a0, a1 = p.paw_span_R
        ring = g2.sector(p.paw_lip_r, 23.6, a0, a1, tol=TOL)
        am = math.radians(0.5 * (a0 + a1))
        mitt = g2.ellipse((21.0 * math.cos(am), 21.0 * math.sin(am)), 6.0, 6.3, 0.5 * (a0 + a1), TOL)
        return g2.union([ring, mitt])

    finger_angles = (3.5, 11.5)     # deg about O: two toe grooves on each mitt, over the ball rim
    finger_r = (19.4, 22.2)          # just beyond the lip zone (r <= 18.9), which keeps its full height

    def paw_features_right(self, p, plan2d) -> list[Feature]:
        parts = []
        for a in self.finger_angles:
            u = np.array([math.cos(math.radians(a)), math.sin(math.radians(a))])
            parts.append(g2.stadium(tuple(u * self.finger_r[0]), tuple(u * self.finger_r[1]), 0.8, TOL))
        return [Feature("fingers", g2.intersect(g2.union(parts), g2.grow(plan2d, -0.8, TOL)), "deboss", 0.5)]

    def _foot2d(self, s):
        c = (s * self.foot_c[0], self.foot_c[1])
        return g2.ellipse(c, self.foot_ab[0], self.foot_ab[1], s * self.foot_tilt, TOL)

    def _beans(self, s):
        c = np.array([s * self.foot_c[0], self.foot_c[1]])
        out = []
        for dx, dy, ax, ay in self.beans:
            # offsets are for the right foot (toes on its upper-outer side); mirrored for the left
            out.append(g2.ellipse(tuple(c + np.array([s * dx, dy])), ax, ay, 0.0, TOL))
        return g2.union(out)

    def paw_style(self, p) -> dict:
        from .base import PawStyle, mirror_features
        planR = self.paw_plan_right(p)
        featR = self.paw_features_right(p, planR)
        mitt = dict(round_xy=3.0, round_z=1.15)
        out = {"R": PawStyle(planR, featR, **mitt),
               "L": PawStyle(planR.mirror((1.0, 0.0)), mirror_features(featR), **mitt)}
        fs = dict(z1=self.foot_z1, round_xy=self.foot_round[0], round_z=self.foot_round[1])
        a0, a1 = self.foot_span
        for s, key in ((1, "RF"), (-1, "LF")):
            plan = self._foot2d(s)          # the oval reaches over the ball rim (r < 17) by itself
            span = (a0, a1) if s > 0 else (180.0 - a1, 180.0 - a0)
            beans = Feature(f"beans_{key}", self._beans(s), "raise", 0.8, round=0.5, color="accent")
            out[key] = PawStyle(plan, [beans], span=span, **fs)
        return out

    # ------------------------------------------------------------------ wheel
    # concept yarn ball (round 4): a diagonal band of 4 strands lying on top, a fan of strands bowing left in the
    # upper part, strands wrapping the lower-left rim, short strands parallel to the band at lower right, a groove
    # setting off the rim ring and a plain collar round the finger hole.  The grooves are stepped V's
    # (relief_bevel), so the lands between them read as rounded cords.  Drawn with the hole at -45 deg (as in the
    # concept) and turned +45 deg into the wheel frame (hole at 0 deg).
    yarn_pitch = 2.4
    yarn_band = ((2.0, 2.5), 37.0, 4.8)       # band centre point, direction (deg), half-width
    yarn_fan_pole = (30.0, 7.0)
    yarn_rim_groove_r = 15.6

    def wheel_relief2d(self, p) -> CrossSection:
        w = max(p.relief_w, 0.6)
        R = p.relief_r_max + 1.0
        disc = g2.circle((0, 0), R, TOL)
        c, ang, hw = np.array(self.yarn_band[0]), math.radians(self.yarn_band[1]), self.yarn_band[2]
        u = np.array([math.cos(ang), math.sin(ang)])
        n = np.array([-u[1], u[0]])

        def halfplane(o, nrm):          # points x with nrm . (x - o) >= 0
            t = np.array([-nrm[1], nrm[0]])
            o = np.asarray(o, float)
            return g2.poly([o + 80 * t, o - 80 * t, o - 80 * t + 80 * nrm, o + 80 * t + 80 * nrm])

        def lines(offsets):
            return g2.union([g2.stadium(tuple(c + n * d - u * 60), tuple(c + n * d + u * 60), w, TOL) for d in offsets])

        def arcs(pole, radii):
            return g2.union([g2.difference(g2.circle(tuple(pole), r + w / 2, TOL), g2.circle(tuple(pole), r - w / 2, TOL))
                             for r in radii])

        band = g2.intersect(halfplane(c - n * hw, n), halfplane(c + n * hw, -n))
        above = halfplane(c + n * hw, n)
        below = halfplane(c - n * hw, -n)
        lower_left = g2.intersect(below, halfplane(c, -u))
        lower_right = g2.intersect(below, halfplane(c, u))
        P = self.yarn_pitch
        grooves = [
            # band: its two edges and the lines between its 4 strands
            lines(np.arange(-hw, hw + 1e-6, P * hw * 2 / (4 * P) )),
            g2.intersect(arcs(self.yarn_fan_pole, np.arange(20.0, 50.0, P)), above),
            g2.intersect(arcs((0.0, 0.0), np.arange(4.0, 15.0, P)), lower_left),
            g2.intersect(lines(-hw - P * np.arange(1, 12)), lower_right),
            # seam where the wrap meets the short parallels, and the groove round the rim ring
            g2.intersect(g2.stadium(tuple(c - n * hw), tuple(c - n * 40), w, TOL), below),
            g2.difference(g2.circle((0, 0), self.yarn_rim_groove_r + w / 2, TOL),
                          g2.circle((0, 0), self.yarn_rim_groove_r - w / 2, TOL)),
        ]
        rel = g2.intersect(g2.union(grooves), disc)
        rel = rel.rotate(45.0)
        return g2.drop_small(g2.opening(rel, 0.4, TOL), 0.8)
