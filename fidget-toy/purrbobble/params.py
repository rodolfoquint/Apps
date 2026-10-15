"""All named parameters of the Purr-Bobble core (SPEC section 2.3, 2.5-2.7, 3.1-3.2, 4.2).

Units: mm and degrees.  Conventions (SPEC section 2.1):

* O = (0, 0) is the wheel axis, +Y is "up" when the toy is held upright.
* Z is the print direction; the bed is z = 0, the back plate lies on it and the face points to +Z.
* P = (0, D) is the head axis, D = rho * tilt / cos(gamma) (24.710 for the nominal variant).
* phi (wheel, about O) and psi (head, about P) are counter-clockwise-positive seen from +Z.

Usage::

    from purrbobble.params import get_params, VARIANTS
    p = get_params("nominal")          # frozen dataclass
    p.D, p.P, p.pallets                # derived values (properties)
    q = p.replace(drho=1.70)           # any field can be overridden
    p.as_dict()                        # JSON-able dict incl. derived values

Variants (SPEC 3.2 and 7):

* ``nominal``  - as designed.
* ``deep``     - drho 1.7186 (-0.15): cures tooth slip / free spin.  P moves with drho (same equations as the
                 ideation analysis, ``esc_layout.esc_geometry(drho)``).
* ``shallow``  - drho 2.0186 (+0.15): cures notchy / locking wheels.
* ``loose``    - rough printers: journals 0.40 (bore 8.80), swept gaps 0.60 (gap_xy 0.55 + 0.05 allowance),
                 rib Z gap 0.45 (every floating body lifted 0.05), V-ridge normal gap 0.40.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

VARIANTS = ("nominal", "deep", "shallow", "loose")


@dataclass(frozen=True)
class Params:
    # ------------------------------------------------------------------ identity
    skin: str = "kitty"
    variant: str = "nominal"

    # ------------------------------------------------------------------ escapement (SPEC 2.3, frozen core)
    N: int = 8                      # teeth
    Rt: float = 14.2992             # tip radius
    tooth_h: float = 5.3968         # tooth height -> Rr = Rt - tooth_h = 8.9024
    tip_frac: float = 0.0765        # tip land, fraction of pitch
    root_frac: float = 0.1333       # root land, fraction of pitch
    r_f: float = 0.70               # corner rounding of Star2D
    rp: float = 2.1448              # pallet tip radius
    drho: float = 1.8686            # pallet depth
    m: int = 2                      # pallet span in pitches
    tilt: float = 0.8792
    psi_b: float = 12.42            # banking, deg (hard stops at +-psi_b)

    # ------------------------------------------------------------------ head band layout (SPEC 2.5)
    hub_r: float = 7.0              # Hub2D = disc(P, hub_r)
    leg_w: float = 7.0              # stadium width
    leg_A_r: float = 21.0           # A_i = leg_A_r * u_i
    leg_B: tuple = (11.0, 26.0)     # B_i = (+-11.0, 26.0) (absolute, as in layout.py)
    leg_B_margin: float = 3.0       # B_i must lie >= 3 mm inside Face2D
    finger_L: float = 7.0           # pallet finger length along u_i
    finger_taper: float = 8.0       # half-angle, deg (half-width 2.1448 -> 3.129)
    face_dy: float = 11.0           # C_h = P + (0, face_dy)
    face_r: float = 16.0            # head disc radius (skin may use it)
    wheel_ex_r: float = 14.90       # WheelEx2D = SweptInv(disc(O, wheel_ex_r))
    ball_ex_r: float = 19.00        # BallEx2D  = SweptInv(disc(O, ball_ex_r))

    # ------------------------------------------------------------------ frame layout (SPEC 2.5, 3.1)
    body_r: float = 21.5            # body ring around O
    wall: float = 2.5               # wall beyond every channel; Body2D uses (gap_xy + wall) = 3.0
    body_round: float = 3.0         # round_r3 of Body2D
    corner_r: float = 1.5           # exterior plan corners r >= 1.5
    backdrop_corner_r: float = 2.0  # backdrop (cushion / flower / porthole) convex corners (skin brief: r >= 2)
    open_t: float = 2.0             # SPEC open_1.6, raised to 2.0: removes slivers thinner than 2.0 and rounds the
                                    # exposed convex fill / roof corners r 1.0 (SPEC 6: every edge r >= 1.0)
    facemid_open: float = 2.0       # FaceMid2D opening (slot-mouth corners r 1.0, no thin fins)
    crown_ring: bool = True         # roof ring over the top of the hub, concentric outer edge (core2d.crown_body)
    crown_R: float = 22.5           # crown arc radius about P: outside the swept leg-channel walls, and its step to the
                                    # shoulders >= 12 mm from the swept face (V12)
    crown_margin_deg: float = 2.0
    crown_lune_deg: float = 5.0     # radial notch where the face leaves the crown arc ...
    crown_lune_depth: float = 3.0   # ... cut only this far beyond the crown edge
    crown_fence_t: float = 2.6      # concentric collar beyond the crown edge for skins that need it (core2d.crown_fence)
    crown_fence_margin_deg: float = 1.0   # collar ends: this much beyond the >= 12 mm (swept) clearance to the steps
    crown_fence_in: float = 0.55    # the collar starts this far inside the crown edge (R_b + swept_gap - 0.05 ... )
    crown_fence_extend: bool = False  # extend the collar past the notches until far parts are >= 12 mm from the
                                      # exposed crown wall (its free radial ends then slide along the crown: V12 medium)
    crown_skirt_w: float = 2.0      # mouth guard: skirt / fill recess width (annulus R_b - w .. R_b)
    z_skirt: float = 5.7            # skirt underside (sill top 2.6 -> 3.1 mm opening: no 4 mm probe)
    z_groove: float = 5.3           # band groove rib top under the skirt (0.40 below the skirt: the skirt bridges
                                    # the leg channels and floats on this rib); groove floor rib_h lower (4.7)
    rib_band_pitch: float = 4.2     # band-top ribs (head) under the crown roof
    rib_band_spoke_deg: float = 10.0    # radial spokes about P joining the band-top arcs into a web
    face_jowls: bool = False        # front-layer cheeks down to the ball rim (core2d.face_jowls); not needed
                                    # once the front layer clears the ball top
    face_ball_gap: float = 1.45     # jowl edge >= 1.45 from the ball rim at every pose (V6 1.4-2.0)
    col_r: float = 5.0              # face mid layer column about P (crown mode): disc(P, col_r), chin-ball gap 1.71
    tongue_r: float = 17.5          # funnel seat: fill tongues narrower than tongue_w inside r tongue_r ...
    tongue_w: float = 3.8
    z_tongue: float = 8.2           # ... are cut down to this height
    fill_wheel_r: float = 14.80     # disc(O, 14.80) cut from Fill2D (tooth tips 14.30 -> 0.50)
    R_hole_roof: float = 17.10      # roof hole around O
    R_hub_cut: float = 7.50         # roof hole around P
    backdrop_margin: float = 2.0    # Backdrop2D includes Swept(FaceUp2D) (+) 2.0
    backdrop_round: float = 2.0     # round_r2
    plate_ledge: float = 0.05       # Body2D kept this far inside Backdrop2D where flush (clean meshes)
    eps_stack: float = 0.002        # stacked slabs: the covered section is shrunk by this much so walls of
                                    # different slabs never coincide (avoids T-junction pinches); 2 um
    mesh_simplify: float = 1e-5     # final Manifold.simplify tolerance (merges sub-micron slivers)
    min_crumb_mm3: float = 5.0      # detached pieces smaller than this are dropped from a body (finish())
    stop_pad_r: float = 3.0         # pad = ... intersected with disc(Rot(M_i), 3.0)
    stop_pad_min_contact: float = 4.0   # each pad must meet the leg flank over >= 4 mm at the banking pose

    # ------------------------------------------------------------------ clearances (SPEC 3.2)
    gap_xy: float = 0.50            # swept XY gap (cavity, roof sweep); + sweep_allowance = 0.55
    sweep_allowance: float = 0.05   # added to every swept offset for chord error
    n_sweep: int = 101              # >= 100 poses, step <= 0.25 deg
    gap_rib: float = 0.40           # Z gap floating body underside <-> rib tops
    decor_face_clear: float = 12.0  # body decor >= 12 mm outside Swept(FaceUp2D) (SPEC 2.7 says >= 2; decor z
                                    # 10.4-12.0 shares the face front layer's Z band, so V12 needs >= 12)

    # ------------------------------------------------------------------ posts / bores (SPEC 3.1, 3.3)
    post_d: float = 8.00
    bore_d: float = 8.70            # journal radial gap 0.35
    post_z0: float = 2.0
    post_z1: float = 7.6
    post_chamfer: float = 0.6       # 0.6 x 45 deg top chamfer
    post_root_fillet: float = 1.0
    ridge_h: float = 0.80           # V-ridge apex r = post_d/2 + ridge_h = 4.80
    ridge_z: float = 5.0            # V-ridge / V-groove apex height (frame z)
    ridge_gap_n: float = 0.35       # normal gap between 45 deg flanks (0.495 radial / axial)
    bore_chamfer: float = 0.6       # 0.6 x 45 deg entry chamfer
    bore_roof_z: float = 8.0        # blind bore roof (post top 7.6 -> 0.40)

    # ------------------------------------------------------------------ Z stack (SPEC 2.6)
    z_bp: float = 2.0               # back plate top (0 .. 2.0)
    bp_chamfer: float = 0.5         # 0.5 x 45 deg bottom-edge chamfer
    bp_chamfer_steps: int = 2       # stepped (0.25 mm steps; the printer resolves 0.2 mm layers)
    rib_h: float = 0.6              # skid ribs (2.0 .. 2.6 on the back plate, 10.4 .. 11.0 on the roof)
    rib_w: float = 0.8
    z_band0: float = 3.0            # head band / wheel teeth bottom
    z_band1: float = 7.4            # head band top
    z_teeth1: float = 8.0           # wheel teeth top = umbrella plate bottom
    z_roof0: float = 8.4
    z_roof1: float = 10.4           # roof top = body top
    # Fix round 1: the face front layer is raised 2.3 (SPEC 11.4 / 15.4 / 16.0) so its underside clears the yarn
    # ball's top (13.3) by 0.4.  The round face and the round ball no longer share a Z band, so the crescent between
    # cheek and ball rim (a 3.5 -> 6 mm squeeze as the head swings, V12) disappears; the overall depth returns to
    # the SPEC's 18.3 now that the knob is a recessed finger well.
    z_front0: float = 13.7          # face front layer bottom
    z_front1: float = 17.7          # face front layer top
    z_feat: float = 18.3            # raised face features top (paw tops are paw_z1)
    z_umb_top: float = 13.3         # ball top
    z_knob_top: float = 18.3        # overall depth
    z_decor1: float = 12.0          # body decor relief top (raised 1.6 on the roof)
    z_lift: float = 0.0             # lift of every floating body (loose variant 0.05)

    # ------------------------------------------------------------------ wheel (SPEC 2.7)
    R_u: float = 18.0               # umbrella (yarn ball) radius
    umb_r0: float = 14.30           # cone start radius at z_teeth1
    umb_rim_z0: float = 11.70       # cone end (r = R_u)
    umb_rim_z1: float = 12.30       # rim cylinder top (then r 1.0 fillet to z_umb_top)
    umb_fillet: float = 1.0
    r_k: float = 11.0               # knob / finger-well centre radius (wheel frame (r_k, 0))
    # Fix round 1 (V12 pinch audit + V10): the protruding D10 knob made a shear with the paw-lip span ends
    # (12.4 -> 1.0 mm) and a squeeze under the chin, and would be a small part if it snapped.  The child now drives
    # the ball with a fingertip in a recessed spherical finger well at the same radius r_k (same lever arm for the
    # dynamics); nothing of the wheel stands above the ball top (z 13.3).  wheel_drive = "knob" restores the SPEC knob.
    wheel_drive: str = "well"
    well_d: float = 8.4             # well opening diameter (dish) before the rim round: top edge r 4.65 about the
                                    # well axis (D 9.3), leaving a 1.35 land of ball top before the r 1.0 rim round
                                    # at r 17.0 (V8 >= 1.2; D 10 left 0.62)
    well_depth: float = 2.0
    well_rim_r: float = 1.0         # rim round (SPEC 6: every edge r >= 1.0)
    knob_d: float = 10.0
    knob_top_fillet: float = 2.5
    knob_root_fillet: float = 1.0
    relief_w: float = 0.6           # skin top relief grooves 0.6 wide x 0.5 deep
    relief_depth: float = 0.5
    relief_r_max: float = 16.5      # grooves for r <= 16.5
    relief_knob_clear: float = 7.5  # no grooves within 7.5 of the knob / well axis (well top edge r 4.65 + 2.85)

    # ------------------------------------------------------------------ keep-out under the umbrella (SPEC 2.7)
    # SPEC polygon (0,2)-(14.80,2)-(14.80,7.80)-(18.60,11.60)-(18.60,40)-(0,40); the vertical part is pulled in to
    # 14.79 (same 45 deg cone: r = z + 7.0) so it never coincides with the Fill2D wheel pocket wall (r 14.80).
    keepout: tuple = ((0.0, 2.0), (14.79, 2.0), (14.79, 7.79), (18.60, 11.60), (18.60, 40.0), (0.0, 40.0))

    # ------------------------------------------------------------------ paws (SPEC 3.1)
    paw_span_R: tuple = (-10.0, 25.0)
    paw_span_L: tuple = (155.0, 190.0)
    paw_wall_r: float = 18.6        # paw inner wall radius below the lip
    paw_lip_r: float = 17.0         # lip inner face radius (z 14.3 .. 16.0)
    # lip underside z = paw_lip_c - r for r in [17.0, 18.6].  SPEC writes 31.3 (= 13.3 + 1.0 + 17.0, i.e. 1.0
    # above the ball top at r 17.0) but that ignores the r 1.0 rim fillet: the lip then comes within 0.41
    # (normal) / 0.59 (vertical) of the ball and 0.71 of the knob root fillet (V6 wants knob<->paw >= 0.9).
    # Adding (sqrt(2) - 1) * umb_fillet restores every SPEC clearance: ball top <-> lip >= 1.00 vertical
    # everywhere, lift stop exactly 1.0 (SPEC 3.3 "<= 1.0"), knob root <-> lip 1.0 normal.
    # Fix round 1: SPEC 3.2 (ball top <-> lip >= 1.00) and SPEC 3.3 / V11 (ridge-less lift <= 1.0) pin the stop at
    # exactly 1.0, so faceting decides pass / fail (measured 0.9985 .. 1.0029).  The lip is lowered 0.015 so the
    # ridge-less lift stop is 0.985 (inside both 0.02 tolerances: lift <= 1.0, ball <-> lip >= 0.98).
    paw_lip_c: float = 31.3 + (2 ** 0.5 - 1.0) * 1.0 - 0.015
    paw_z0: float = 10.4
    paw_z1: float = 16.0

    # ------------------------------------------------------------------ ribs (SPEC 3.4)
    rib_back_r0: float = 6.0        # arcs about P at r = 6.0 + 4.5 j, j = 0..8
    rib_back_pitch: float = 4.5
    rib_back_n: int = 9
    rib_rings_O: tuple = (7.0, 11.0, 13.8)
    rib_rings_clip: float = 14.3
    rib_post_clear: float = 0.3     # ribs >= 0.3 clear of post root fillets
    rib_roof_r0: float = 9.0        # arcs about P at r = 9.0 + 4.0 j, j = 0..7
    rib_roof_pitch: float = 4.0
    rib_roof_n: int = 8
    rib_roof_i3_grow: float = 0.5   # clipped to Roof2D n Swept(I3 (+) 0.5)

    # ------------------------------------------------------------------ fillets (stepped approximations)
    face_top_round: float = 1.5     # FaceUp2D top perimeter r 1.5 ...
    face_top_steps: int = 6         # ... as 6 inset steps
    frame_top_fillet: float = 1.0   # frame exterior top edges r 1.0
    frame_top_steps: int = 3

    # ------------------------------------------------------------------ print pose (SPEC 3.4)
    phi_print: float = 12.0
    psi_print: float = 5.96

    # ------------------------------------------------------------------ meshing
    tol_func: float = 0.005         # chord error target, functional curves (journals, pallets, teeth)
    tol_deco: float = 0.02          # chord error target, decorative curves

    # ------------------------------------------------------------------ material
    rho_pla: float = 1.24e-3        # g / mm^3

    # ================================================================== derived values
    @property
    def Rr(self) -> float:
        return self.Rt - self.tooth_h

    @property
    def pitch(self) -> float:
        return 360.0 / self.N

    @property
    def gamma(self) -> float:
        """Half pallet span, deg: (m + 1/2) * pitch / 2 = 56.25."""
        return (self.m + 0.5) * self.pitch / 2.0

    @property
    def rho(self) -> float:
        """Pallet-centre radius about O: (Rt + Rr)/2 + rp + drho = 15.6142."""
        return (self.Rt + self.Rr) / 2.0 + self.rp + self.drho

    @property
    def D(self) -> float:
        """Head-axis height: rho * tilt / cos(gamma) = 24.710."""
        return self.rho * self.tilt / math.cos(math.radians(self.gamma))

    @property
    def O(self) -> tuple:
        return (0.0, 0.0)

    @property
    def P(self) -> tuple:
        return (0.0, self.D)

    @property
    def C_h(self) -> tuple:
        return (0.0, self.D + self.face_dy)

    @property
    def u(self) -> tuple:
        """Pallet radial unit vectors (left, right) = (-+sin g, cos g)."""
        g = math.radians(self.gamma)
        return ((-math.sin(g), math.cos(g)), (math.sin(g), math.cos(g)))

    @property
    def pallets(self) -> tuple:
        """Pallet centres (left, right) in the head frame: (+-rho sin g, rho cos g) = (+-12.983, 8.675)."""
        return tuple((self.rho * ux, self.rho * uy) for ux, uy in self.u)

    @property
    def leg_A(self) -> tuple:
        return tuple((self.leg_A_r * ux, self.leg_A_r * uy) for ux, uy in self.u)

    @property
    def leg_Bs(self) -> tuple:
        bx, by = self.leg_B
        return ((-bx, by), (bx, by))

    @property
    def pallet_arm(self) -> float:
        px, py = self.pallets[1]
        return math.hypot(px, py - self.D)

    @property
    def post_r(self) -> float:
        return self.post_d / 2.0

    @property
    def bore_r(self) -> float:
        return self.bore_d / 2.0

    @property
    def ridge_apex_r(self) -> float:
        return self.post_r + self.ridge_h

    @property
    def groove_apex_r(self) -> float:
        """V-groove apex radius: ridge apex + normal gap * sqrt(2) (45 deg flanks) = 5.295."""
        return self.ridge_apex_r + self.ridge_gap_n * math.sqrt(2.0)

    @property
    def swept_gap(self) -> float:
        """Total swept XY gap incl. allowance (0.55 nominal, 0.60 loose)."""
        return self.gap_xy + self.sweep_allowance

    def replace(self, **kw) -> "Params":
        return dataclasses.replace(self, **kw)

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["derived"] = dict(Rr=self.Rr, pitch=self.pitch, gamma=self.gamma, rho=self.rho, D=self.D,
                            P=self.P, C_h=self.C_h, pallets=self.pallets, u=self.u, leg_A=self.leg_A,
                            leg_B=self.leg_Bs, pallet_arm=self.pallet_arm, groove_apex_r=self.groove_apex_r,
                            swept_gap=self.swept_gap)
        return d


def get_params(variant: str = "nominal", skin: str = "kitty", **overrides) -> Params:
    """Parameter set for a named variant (see module docstring)."""
    base = Params(skin=skin, variant=variant)
    if variant == "nominal":
        p = base
    elif variant == "deep":
        # Fix round 1: SPEC 7 lists drho 1.7186 (-0.15), but on the as-built CAD static lock starts between drho
        # 1.75 and 1.7686 at the worst V2 corner (pivot -0.4, pallets +0.2): -0.15 fails V2.  -0.10 (1.7686)
        # passes all 9 V2 cases and still deepens the engagement.  Print pose = max-clearance pose
        # (core2d.search_print_pose; the nominal (12.0, 5.96) leaves the deeper pallets < 1.3 from the teeth).
        p = base.replace(drho=1.7686, phi_print=11.6, psi_print=6.18)
    elif variant == "shallow":
        p = base.replace(drho=2.0186)
    elif variant == "loose":
        # z_lift 0.2 (one full 0.2 mm layer): a 0.05 lift is lost to layer quantisation (the floats would start
        # in the same layer as nominal), so the printed rib gap becomes 0.60 instead of 0.40.
        p = base.replace(bore_d=8.80, gap_xy=0.55, z_lift=0.2, ridge_gap_n=0.40)
    else:
        raise ValueError(f"unknown variant {variant!r}; choose from {VARIANTS}")
    if abs(p.D - base.D) > 1e-12 and "face_dy" not in overrides:
        # P moves with drho (D = rho tilt / cos gamma) but the face stays at its nominal world position: the chin
        # <-> ball rim gap (V6 1.4-2.0) and the overall height are then the same in every variant
        p = p.replace(face_dy=base.face_dy + (base.D - p.D))
    return p.replace(**overrides) if overrides else p
