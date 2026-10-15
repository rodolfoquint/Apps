"""Skin interface (SPEC section 4.3).

A skin supplies only the decorative / identity geometry.  The core (core2d.py, solids.py) derives every
functional section, pocket, gap and capture from it automatically.  All 2-D shapes are
``manifold3d.CrossSection`` in mm.  Head-related shapes are in the HEAD frame (psi = 0, which equals the
design/world frame); wheel shapes are in the WHEEL frame (phi = 0, knob axis at (r_k, 0)).

Contract (checked by ``core2d.check_skin`` - violations raise):

* ``face2d(C_h, p)``: Face2D polygon.  Must contain disc(P, 7.5) and both leg ends B_i with >= 3 mm margin.
  No feature narrower than 6.0 mm; outer corners r >= 2.
* ``face_features(C_h, p)``: list of :class:`Feature` on the face top (z_front1).  Raised features are 0.4-0.6
  tall, debossed 0.3-0.5 deep (a dimple cut into a raised feature up to 0.7); all >= 3 mm inside FaceUp2D's edge (unless ``edge_ok`` is set
  because the SPEC places it closer, e.g. the kitty inner ears at inset 2.0).
* ``backdrop2d(p)``: extra outline unioned into Backdrop2D (may be empty).  Final outline <= 64 W x 85 H.
* ``backdrop_features(p, backdrop2d, body2d, swept_faceup2d)``: debossed grooves in the back-plate top
  (z 2.0), e.g. the kitty cushion stitch groove.  Default: none.
* ``body_decor2d(p)``: raised 1.6 reliefs on the roof (z 10.4 -> 12.0): feet, tail ...  The core clips them to
  stay >= 2 mm outside Swept(FaceUp2D) and unions them into Body2D.
* ``body_decor_features(p)``: debossed details on top of the decor (optional).
* ``paw_style(p)``: ``{"R": PawStyle, "L": PawStyle}``; plan outline (clipped by the core to the paw angular
  span and r >= 17.0) plus top deboss features.  Default implementation mirrors the right paw.
* ``wheel_relief2d(p)``: groove pattern (0.6 wide x 0.5 deep) on the ball top; the core clips it to r <= 16.5
  and away from the knob.
* ``head_pockets2d(p)``: optional closed internal pockets for inertia trimming (walls >= 2.0).
* ``colors``: render colours {"frame", "wheel", "head"}; ``plate_color`` / ``details_color`` for the multi-colour
  3MF and renders (back plate below z_bp, raised face details above z_front1).
* ``param_overrides``: decorative parameter overrides (e.g. the kitty's taller feet, ``{"z_decor1": 14.4}``).
* ``backdrop2d(p)`` may also take ``(p, S)``: ``S["body_pre2d"]`` and ``S["swept_faceup2d"]`` are then available
  (e.g. to frame the character with a scalloped cushion).

Inertia check (SPEC 4.3, done by verification): I_h about P (solid PLA 1.24 g/cm^3) in [4.0, 8.0]e-6 kg m^2,
centre of mass 8-14 mm above P.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from manifold3d import CrossSection

from .. import geom2d as g2


@dataclass
class Feature:
    """A surface feature on a flat top face.

    mode:
      * ``"raise"``  - extrude ``shape`` upward by ``depth`` from the surface.
      * ``"deboss"`` - cut ``shape`` downward by ``depth`` from the surface.
      * ``"dome"``   - spherical cap of height ``depth`` over the circle (``center``, ``radius``).
      * ``"dimple"`` - spherical dimple: a sphere cut so that the opening is the circle (``center``, ``radius``)
                        and the deepest point is ``depth`` below the local surface.  ``on`` names the feature
                        it is cut into (its surface height is used), or None for the flat base surface.
    """
    name: str
    shape: CrossSection | None
    mode: str
    depth: float
    center: tuple | None = None
    radius: float | None = None
    on: str | None = None
    edge_ok: bool = False          # allowed closer than 3 mm to the face edge (SPEC places it there)
    color: str | None = None       # multi-colour print: "details" (eyes, nose, mouth) or "accent" (bow, blush,
    #                                tongue, toe beans ...) for raised features; None = the body's own colour


@dataclass
class PawStyle:
    plan2d: CrossSection                      # plan outline, world frame
    features: list = field(default_factory=list)   # Feature list on the paw top (z 16.0)


class Skin:
    """Base class.  Subclasses must implement ``face2d``; everything else has neutral defaults."""

    name = "base"
    colors = {"frame": "#d9d2c5", "wheel": "#7fb3ff", "head": "#ffd27f"}
    # Multi-colour print / render palette (see assemble.write_3mf(multicolor=True)): the back plate (z < z_bp) and
    # the raised face details (z >= z_front1) can take their own filament.  Defaults: same as frame / dark brown.
    plate_color: str | None = None
    details_color: str = "#3b2a2a"
    # Decorative parameter overrides applied by params.get_params for this skin (e.g. {"z_decor1": 14.4}).
    param_overrides: dict = {}

    def palette(self) -> dict:
        """frame / plate / wheel / head / details colours."""
        c = dict(self.colors)
        c.setdefault("plate", self.plate_color or c["frame"])
        if self.plate_color:
            c["plate"] = self.plate_color
        c.setdefault("details", self.details_color)
        return c

    # ------------------------------------------------------------------ head
    def face2d(self, C_h, p) -> CrossSection:
        raise NotImplementedError

    def face_features(self, C_h, p) -> list[Feature]:
        return []

    def head_pockets2d(self, p) -> CrossSection | None:
        return None

    # ------------------------------------------------------------------ frame
    def backdrop2d(self, p) -> CrossSection | None:
        return None

    def backdrop_features(self, p, backdrop2d, body2d, swept_faceup2d) -> list[Feature]:
        return []

    def body_decor2d(self, p) -> CrossSection | None:
        return None

    def body_decor_features(self, p) -> list[Feature]:
        return []

    def paw_plan_right(self, p) -> CrossSection:
        """Default: plain annular sector out to a generous radius (core clips to Body2D outline)."""
        a0, a1 = p.paw_span_R
        return g2.sector(p.paw_lip_r, p.body_r + 2.0, a0, a1)

    def paw_features_right(self, p, plan2d) -> list[Feature]:
        return []

    def paw_style(self, p) -> dict:
        planR = self.paw_plan_right(p)
        featR = self.paw_features_right(p, planR)
        planL = planR.mirror((1.0, 0.0))
        featL = [Feature(f.name + "_L", None if f.shape is None else f.shape.mirror((1.0, 0.0)), f.mode, f.depth,
                         None if f.center is None else (-f.center[0], f.center[1]), f.radius, f.on, f.edge_ok)
                 for f in featR]
        return {"R": PawStyle(planR, featR), "L": PawStyle(planL, featL)}

    # ------------------------------------------------------------------ wheel
    def wheel_relief2d(self, p) -> CrossSection | None:
        return None
