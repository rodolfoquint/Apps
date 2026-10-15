# Purr-Bobble: a print-in-place escapement fidget for kids

Turn the yarn ball and the kitty's head shivers with giggles. Inside is a spring-free clock escapement: the yarn
ball is an 8-tooth escape wheel, the kitty's head is the swinging regulator (a foliot), and the child's thumb is
the mainspring. Push gently for a slow giggle (about 5 shivers a second), harder for a purr and then a buzz
(about 36 a second). Let go and it stops at once, in either direction.

One PLA print, three captive moving parts, no supports, no springs, magnets, screws or glue. Three characters
share the same mechanism core: **Purr Kitty**, **Bumble** the bee and **Pip the Robot**.

| | |
|---|---|
| Size (kitty) | 52.8 × 84.3 × 18.3 mm |
| Weight | about 41–43 g of PLA as printed (PrusaSlicer, head and ball 100 % infill) |
| Print time | about 5 h 15 min – 5 h 25 min (0.2 mm layers, PrusaSlicer estimate for an MK4-class printer) |
| Ages | 6+ (home-printed toys are not certified to EN 71 / ASTM F963) |

## How the mechanism was designed

1. **Ideation** (`analysis/ideation/ideation_result.json`). A prior-art survey of printable fidgets, then five
   inventors working from different angles (compliant mechanisms, computed profiles, linkages, rolling
   mechanisms, haptics) proposed ten mechanisms. Three judges scored them for engineering and printability,
   novelty and play value, and child safety and charm. The winner was the escapement, and a synthesis step
   wrote the build spec (`docs/SPEC.md`).
2. **Computed geometry** (`analysis/ideation/haptic`, `analysis/ideation/synth`). A random search over more
   than 1,000 star-wheel and pallet geometries kept only shapes that a hand-pushed wheel can never jam or slip
   past. It checked both directions, posts printed 0.4 mm off, pallets 0.2 mm too fat or thin, bearing play
   and friction up to μ 0.5. A 6-DOF contact-dynamics model then set the pallet depth inside that tolerance
   window. Every pocket and gap in the body is the swept shape of the motion.
3. **Parametric CAD** (`purrbobble/`): Python + manifold3d. One character and variant builds in about 5–10 s.
   See `purrbobble/README.md` for the API and the skin interface.
4. **Verification** (`verification/`): four independent checkers, run for every character by
   `verification/run_all.py`. Results are in `verification/reports/SUMMARY.md`.

## Print it

Files: `stl/<character>/purrbobble_<character>_nominal.3mf` (recommended: it carries the per-part settings).
Rebuild the STLs and the other variants with `python3 -m purrbobble.build --all`.

| Setting | Value |
|---|---|
| Material | PLA or PLA+ only (dry PETG is too grippy and can stall the escapement) |
| Layers / nozzle | 0.20 mm / 0.4 mm |
| Orientation | as exported: back plate on the bed, face up; do not scale |
| Supports / brim | none / none |
| Walls | 3 perimeters, 5 top and 5 bottom layers |
| Infill | frame 20 % gyroid; head and ball 100 % (set per part in the 3MF) |
| Bridges | fan 100 %, about 25 mm/s, thick bridges off, **bridging angle 180°** (set on the frame in the 3MF; with an STL, set it for the whole print) |
| Seam | rear / aligned, never on the posts or bores |

Variants: **loose** (0.40 mm bearings, 0.60 mm swept gaps, 0.6 mm float gaps) for printers that fuse tight gaps;
**deep** if the ball skips teeth; **shallow** if it feels notchy.

Freeing it: let the bed cool below 30 °C; rock the head left and right ten times; turn the ball slowly five
turns each way, then fast for 30 s each way; clear any strings around the ball or under the chin with a pick
(never pliers); finally pull the head and the ball firmly (about 20 N). Neither should move more than about 1 mm.

## Safety notes

* All three parts are larger than the small-parts test cylinder (ball Ø 36 mm, head ≥ 41 mm, body about
  53 × 84 mm), and each moving part is captured by two independent features.
* The escapement is sealed between the back plate, the ball and the body. Almost every reachable moving edge
  keeps a constant gap, stays under 2 mm, or opens to 12 mm or more. The exception: where the head's shoulders
  slide past the edge of the body's crown, the gap opens to about 5 mm and closes to 0.55 mm over the swing. It
  is a blunt, rounded, finger-driven nip (15 g head) present on all three characters; the V12 audit flags it on
  the bee, whose outline lets the 4 mm test probe reach it.
* Suggested label: *Ages 6+. Home 3D-printed toy, not certified to EN 71 / ASTM F963. An adult should check it
  for cracks before each play session. Not for children who still put toys in their mouths.*

## Verification status

Latest full run (`verification/reports/SUMMARY.md`, 2026-10-15, about 40 min on 4 CPUs):

| Character | Escapement (V1–V4, V13) | Motion and clearances (V5–V7, V11) | Printability (V8, V9, slicer) | Child safety (V10, V12, V14) |
|---|---|---|---|---|
| Purr Kitty | pass | pass, with warnings | pass, with warnings | pass, with warnings |
| Pip the Robot | pass | pass, with warnings | pass, with warnings | pass, with warnings |
| Bumble | pass | pass, with warnings | pass, with warnings | **fail**: V12.pinch_00 |

* **Escapement:** every character keeps shivering in all 60 tolerance-corner runs and at friction μ 0.5. A
  gentle push (1 N·mm) gives 0.6–0.8 turns/s and a 5–6 Hz giggle; a hard push (40 N·mm) gives a 35–38 Hz buzz.
  As-printed weight is 41–43 g (PrusaSlicer on the 3MF).
* **Open finding (Bumble, V12.pinch_00):** where the head's shoulder slides past the edge of the body's crown,
  the gap at the crown edge goes from 0.55 mm to 4.95 mm over the swing. The kitty and robot have the same
  geometry there; the audit's 4 mm probe reaches it only around the bee's outline. Treat it as a blunt,
  low-force nip and keep the bee for the older end of the age range, or print the kitty or robot.
* **Warnings kept by design:** the stop pads touch the legs only at the ±12.42° banking limit; the 2 mm back plate
  behind the head is the weakest panel (about 38 MPa under a 50 N push on its top edge); a few cosmetic debosses
  are 0.3 mm deep; wall-thickness warnings sit at edge rounds and ribs (0.8 mm by design).

## Layout

| Path | Content |
|---|---|
| `docs/SPEC.md` | build specification from the ideation stage |
| `analysis/ideation/` | prior art, concepts, judge scores, escapement search, tolerance and dynamics scripts |
| `purrbobble/` | parametric model (core, sweeps, solids, skins, build CLI) |
| `verification/` | checkers V1–V14, `run_all.py`, reports |
| `stl/` | 3MF print files and build metadata (STLs are regenerated, not committed) |
| `renders/` | rendered views of every character and variant |
| `web/` | interactive viewer page (three.js) with simulated motion |
| `tools/` | shared mesh checks, rendering, web export |
