# purrbobble - parametric CAD for the Purr-Bobble Kitty

Print-in-place, spring-free foliot / pin-pallet escapement fidget (design spec: `docs/SPEC.md`).
Three captive bodies - FRAME, WHEEL (yarn ball = escape wheel), HEAD (kitty face = foliot) - built with
Python + manifold3d (`CrossSection` for all 2-D work, `Manifold` for solids). One skin + variant builds in
about 5-8 s.

## Quick start

```bash
cd /home/user/Apps/fidget-toy
python3 -m purrbobble.build --skin kitty --variant nominal     # STL + 3MF + renders
python3 -m purrbobble.build --skin kitty --all                 # nominal, deep, shallow, loose
python3 -m purrbobble.build --skin kitty --all --no-render
python3 verification/v_basic.py --skin kitty [--variant nominal] [--slice]   # V1 + V7 + mass/inertia
```

Outputs:

| Path | Content |
|---|---|
| `stl/<skin>/purrbobble_<skin>_<variant>.stl` | one binary STL, three shells (frame, wheel, head) at the print pose |
| `stl/<skin>/purrbobble_<skin>_nominal_{frame,wheel,head}.stl` | per-body STLs, print pose (same placement as the combined file) |
| `stl/<skin>/purrbobble_<skin>_nominal.3mf` | one object with three named parts; PrusaSlicer volume config sets frame 20 % gyroid, wheel and head 100 % infill |
| `stl/<skin>/build_<variant>.json` | sizes, volumes, triangle counts, print-pose gaps, section report, timings |
| `renders/<skin>/purrbobble_<skin>_<variant>_<view>.png` | face, three_quarter, iso, top_down, back, section_x0, section_z5 (nominal) |
| `verification/reports/<skin>/basic.json` | V1 / V7 / mass report |

## Conventions (SPEC 2.1)

* Units mm and degrees. Z up = print direction; the back plate lies on the bed (z = 0) and the face points to +Z.
* O = (0, 0) is the wheel axis, P = (0, D) the head axis, D = rho tilt / cos(gamma) = **24.710** (nominal).
  +Y is "up" when the toy is held upright.
* phi = wheel rotation about O, psi = head rotation about P; both counter-clockwise-positive seen from +Z.
  Head range psi in [-12.42, +12.42] (hard banking on four stop pads).
* DESIGN frame = phi 0, psi 0 (head frame coincides with the world frame). Every `Model` body is stored in the
  design frame; `Model.posed(phi, psi)` places them. Print pose = `posed(p.phi_print, p.psi_print)` =
  `posed(12.0, 5.96)` for nominal, shallow and loose; the deep variant prints at its max-clearance pose
  `(11.6, 6.22)` (pallet <-> tooth 1.303; at 12.0 / 5.96 it would be only 1.21).
* Wheel frame: knob axis at (r_k, 0) = (11, 0); star root lands centred on 0, 45, ... deg; tips on 22.5, 67.5, ...
* Floating bodies in the `loose` variant are lifted by `z_lift` = 0.05 (their V-grooves stay on the frame ridge).

## API

```python
from purrbobble import build                    # == purrbobble.model.build
M = build(skin="kitty", variant="nominal")      # Model
M.frame, M.wheel, M.head                        # manifold3d.Manifold, design frame
M.O, M.P                                        # (0.0, 0.0), (0.0, 24.70976)
M.params                                        # purrbobble.params.Params (frozen dataclass)
M.sections                                      # core2d.Sections (dict + attribute access) of CrossSection
M.posed(phi_deg, psi_deg)                       # {'frame','wheel','head'} in the world frame
M.print_pose()                                  # posed(12.0, 5.96)
M.wheel_at(phi), M.head_at(psi)                 # single posed bodies
M.skin, M.info                                  # skin instance; timings + skin-contract warnings
```

* `params.get_params(variant="nominal", skin="kitty", **overrides) -> Params`; `VARIANTS = ("nominal",
  "deep", "shallow", "loose")`. Derived properties: `Rr, pitch, gamma, rho, D, P, C_h, u, pallets, leg_A,
  leg_Bs, pallet_arm, post_r, bore_r, ridge_apex_r, groove_apex_r, swept_gap`; `p.replace(**kw)`,
  `p.as_dict()`. Variants: deep drho 1.7186, shallow drho 2.0186 (P moves with drho exactly as in the ideation
  analysis), loose = bore 8.80 / gap_xy 0.55 (swept gaps 0.60) / z_lift 0.05 / ridge normal gap 0.40.
* `escapement`: `star2d(p)` (wheel frame), `pallet_centres(p)`, `pallet_discs2d(p)`, `finger2d(p, i)`,
  `fingers2d(p)`, `summary(p)` (V1 numbers), `star_polygon_pts(p)`.
* `sweep`: `swept(cs, pivot, psi_b=12.42, n=101, allowance=0.05, psi_range=None)` = U Rot_P(+psi)(cs) grown by
  `allowance`; `swept_inv(...)` = U Rot_P(-psi)(cs); `poses(psi_range, n)` (>= 100 poses, step <= 0.25 deg).
* `core2d.build_sections(p, skin) -> Sections`; `core2d.section_report(p, S)`; `core2d.check_skin(p, face)`;
  `core2d.print_pose_clearance(p, S, phi, psi, full=True)` (2-D star <-> head band / pallet distance);
  `core2d.search_print_pose(p, S) -> (clearance, phi, psi)`; `core2d.open_keep_outline(cs, t)`.
* `solids`: `build_wheel/build_head/build_frame(p, S, skin) -> (Manifold, info)`, `post(p, c)`, `bore(p, c)`,
  `keepout_u(p)`, `umbrella_profile(p)`, `knob_profile(p)`, `paw_profile(p)`, `stepped_top(cs, z0, z1, r,
  steps)`, `chamfer_bottom(...)`, `extrude(cs, z0, z1, mode)`, `revolve_rz(pts_rz, n, hole)`,
  `pinch_vertices(m)`, `check_solid(m, name)`.
* `assemble`: `print_bodies(M)`, `check_print_pose(bodies, min_gap=0.35)`, `write_stl(path, bodies)`,
  `write_3mf(path, bodies, name)`, `mesh_arrays(m) -> (verts, faces)`.
* `geom2d`: CrossSection helpers (`circle(c, r, tol, hole=)`, `stadium`, `sector`, `ellipse`, `grow`,
  `opening`, `closing`, `round_r`, `rot_about`, `union/difference/intersect`, `to_shapely`,
  `min_distance_polys`, `max_inscribed_width`, `touch_points`, `clean`).

### Sections (`M.sections[...]`, all `manifold3d.CrossSection`)

Head frame (psi = 0): `star2d` (wheel frame), `pallets2d`, `fingers2d`, `hub2d`, `legs2d`, `face2d`,
`wheelex2d` = SweptInv(disc(O,14.90)), `ballex2d` = SweptInv(disc(O,19.00)), `headband2d`, `faceup2d`,
`facemid2d` = FaceUp - RoofSweepInv, `i3_2d` = FaceUp n RoofSweepInv, `roof_sweep_inv2d`, `collar2d`.
World frame: `exposed2d`, `swept_exposed2d`, `swept_headband2d` (+0.05), `swept_headband2d_exact`,
`swept_faceup2d`, `body2d`, `cavity2d`, `stoppads2d`, `fill2d`, `fill_slivers2d` (removed by open_1.6),
`roof2d`, `top2d` (= fill U roof, body top), `bridges2d` (roof spans over channels), `backdrop2d`,
`ribs_back2d`, `ribs_roof2d`, `paw_plan_R`, `paw_plan_L`, `decor2d`, `wheel_relief2d` (wheel frame).
Also `skin_contract` (dict) and `_time_s`.

### Z stack (SPEC 2.6, design frame)

| z | FRAME | WHEEL | HEAD |
|---|---|---|---|
| 0-2.0 | back plate = Backdrop2D, 0.5 chamfer, stitch groove | | |
| 2.0-2.6 | skid ribs | | |
| 2.0-7.6 | posts D8.00 at O and P (V-ridge apex r 4.80 @ z 5.0) | | |
| 2.0-8.4 | Fill2D | teeth Star2D 3.0-8.0 | HeadBand2D 3.0-7.4 |
| 8.4-10.4 | Fill U Roof (top edge r 1.0) | umbrella from 8.0 (45 deg cone) | FaceMid2D 7.4-11.4 (+ hub collar 7.4-8.4) |
| 10.4-11.0 | roof-top ribs under I3 | rim to 13.3 | |
| 10.4-16.0 | paws (lip z = 31.714 - r), decor 10.4-12.0 | knob 13.3-18.3 | FaceUp2D 11.4-15.4 (top r 1.5), features to 16.0 |

## Skin interface (SPEC 4.3) - `skins/base.py`

Subclass `skins.base.Skin` and register it in `skins/__init__.py` (`REGISTRY` already maps `bee ->
purrbobble.skins.bee:BeeSkin` and `robot -> purrbobble.skins.robot:RobotSkin`; `--skin all` builds every
registered module that exists). Implement:

| Method | Returns | Kitty example |
|---|---|---|
| `face2d(C_h, p)` (required) | Face2D, head frame | disc(C_h, 16) + two rounded triangle ears |
| `face_features(C_h, p)` | list of `Feature(name, shape, mode, depth, center, radius, on, edge_ok)`; modes `raise` (0.6), `deboss` (0.3-0.5), `dome` (spherical cap, 0.6), `dimple` (spherical dimple cut into feature `on`) | D7 dome eyes + D2 x 0.4 highlight dimples, rounded-triangle nose, omega mouth, blush, inner ears (`edge_ok`, inset 2.0) |
| `backdrop2d(p)` | extra Backdrop2D outline or None | None (the computed outline is the round cushion) |
| `backdrop_features(p, backdrop2d, body2d, swept_faceup2d)` | Features cut into the plate top (z 2.0) | 0.6 x 0.3 stitch groove 1.6 inside the edge |
| `body_decor2d(p)` | raised 1.6 reliefs on the roof (core clips >= 2 mm outside Swept(FaceUp2D) and unions into Body2D) | feet ovals 9 x 5, curled tail |
| `body_decor_features(p)` | Features on the decor top (z 12.0) | toe creases on the feet |
| `paw_plan_right(p)` / `paw_features_right(p, plan)` (or override `paw_style(p)` -> `{"R": PawStyle, "L": PawStyle}`) | paw plan (core clips to the span and r >= 17.0) and top features; the default `paw_style` mirrors the right paw | round mitt + toe beans (D5 + three D2.5, 0.4 deep) |
| `wheel_relief2d(p)` | groove pattern, wheel frame (core clips to r <= 16.5 and >= 7.5 from the knob axis; 0.6 x 0.5 grooves) | three families of yarn arcs |
| `head_pockets2d(p)` | closed pockets in the head (z 9.4-13.4) for inertia trimming, or None | None |
| `colors` | `{"frame","wheel","head"}` hex colours for renders | pink / sky blue / cream |

The core checks the contract and fails loudly: Face2D must be one piece, overlap the hub and contain both leg
ends; features must stay >= 3 mm inside FaceUp2D (or outside the r 1.5 rim when `edge_ok`), raised 0.6 / debossed
0.3-0.5. Soft violations (disc(P, 7.5) not inside Face2D, B_i closer than 3 mm to the edge, parts narrower
than 6 mm) are reported in `M.info["skin_contract"]["warnings"]`. Inertia (I_h in [4, 8]e-6 kg m^2, COM 8-14
above P) is reported by `verification/v_basic.py`.

## Mesh hygiene

* Faceting is conservative: solids are inscribed, every clearance-making cut (bores, V-grooves, keep-outs, holes)
  is circumscribed, so as-meshed gaps are never below the designed value. Chord tolerance 0.005 mm on journals,
  ridges, umbrella and knob (0.002 on teeth and pallets), 0.03 on decoration.
* Stacked slabs never share coincident-but-different walls (the covered section is shrunk 2 um, Body2D sits
  0.05 inside the plate outline), 2-D sections are cleaned of point contacts, and every body is finished with
  `Manifold.simplify(1e-5)` and checked to have no pinch vertices - each exported shell is watertight in STL.

## Implementation notes / SPEC deviations

See the structured build summary, `stl/<skin>/build_<variant>.json` and comments in the code (search for
"SPEC"). In short: hub collar (kitty face cannot contain disc(P, 7.5)); stop-pad disc radius 5.04 (a 3.0 disc
around the leg midpoint never reaches the flank); paw lip z = 31.714 - r (31.3 ignored the rim fillet); kitty
blush moved 1.2 mm inward to honour the 3 mm feature rule; round_rN = closing rN + opening r1.5; keep-out
cylinder 14.79 (same cone).
