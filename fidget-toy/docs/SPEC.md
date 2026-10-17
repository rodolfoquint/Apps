# Purr-Bobble Kitty: build specification (v1.0, synthesis stage)

A single print in PLA with three captive bodies (frame, wheel, head). No supports and no hardware.

Every number below comes from the scripts in
`/tmp/claude-0/-home-user-Apps/023789a6-f9f1-563f-a565-9790ebbd0388/scratchpad/ideation/synth/`:

- `layout.py`, `layout2.py`, `layout3.py`: 2-D layout and sweeps.
- `esc_layout*.py` and `check_cspace_final.py`: C-space checks.
- `esc_dyn3.py`, `run_*.py`, and the `*.log` files: dynamics.
- `static_map.py`: static lock map.
- `layout_top.png` and `layout_swing.png`: top views.

They build on the ideation scripts in `.../ideation/haptic/` (`esc_opt.py`, `esc_dyn2.py`, `esc_window.py`).

---

## 1. Concept and story

**What the child sees and feels.** A chubby kawaii kitty sits on a round cushion, hugging a big yarn ball in her lap. The child circles the knob on the ball with a fingertip, or rolls the ball's face with a thumb.

- The ball will not spin freely. It moves as if through honey, and you can feel a purr in your fingertip.
- The kitty's whole head shivers ±10° and her ears flick, as if she were giggling.
- Turning gently gives a slow, visible giggle-shiver: about 5–11 Hz, 50–90 soft clicks per second, like a real purr.
- Pushing harder raises the pitch through a purr to a buzz: about 37 Hz and 130 clicks/s at 40 N·mm.
- On release she stops at once. Nothing coasts.
- It works the same in both directions.
- With the toy held upright and the knob untouched, her head gently tilts to one side and rests there, like a curious tilt. That is because the head is a balanced inverted pendulum resting on a banking stop.

**How it works, in one line.** The yarn ball is the escape wheel of a 13th-century-style foliot escapement with no springs. The child's thumb is the mainspring, and the kitty's head is the foliot, so the expression is the regulator.

**The honest "AI-designed" story.** "The shape of the 8-tooth star wheel, the two pallet tips and the exact place where Kitty's head pivots were found by a computer search. The search rejected every geometry in which a hand-pushed wheel could ever lock her head or slip past it. It checked turning in both directions, posts printed 0.4 mm off, pallets 0.2 mm too fat or thin, bearing play and friction. Every hidden pocket and gap in the body was then computed as the swept shape of the motion."

**Shared core and three skins.** One parametric core is used by all three skins: escapement, posts, head band layer, wheel band and umbrella, body cavity, roof, paws and ribs. Each skin is its own complete single print.

1. **Purr Kitty** (default): cat head with ears, sitting on a round quilted cushion, with a yarn-ball wheel and toe-bean paws.
2. **Bumble**: bee head with two chunky antennae and a five-petal flower backdrop. The wheel is a pollen ball with a honeycomb relief, and a hard push lands in a bumblebee buzz band.
3. **Pip the Robot**: rounded-square robot head with an antenna ball and a visor, in a round porthole backdrop. The wheel has gear-rim relief and a power symbol, and the robot makes a beep-rattle.

---

## 2. Mechanism

### 2.1 Coordinate system and conventions

- Units are mm and degrees.
- O = (0, 0) is the wheel axis. +Y is "up" when the toy is held upright.
- Z is the print height. The bed is at z = 0, the toy's back lies on the bed, and the front faces +Z.
- P = (0, 24.710) is the head axis.
- φ is the wheel rotation about O and ψ is the head rotation about P. Both are counter-clockwise-positive when viewed from +Z.
- The head range is ψ ∈ [−12.42°, +12.42°]. The banking limits are hard stops.
- "Head frame" means the head geometry at ψ = 0. Posed geometry is Rot_P(ψ) applied to it.

### 2.2 Bodies, joints and degrees of freedom

| Body | Joint to frame | DOF | Notes |
|---|---|---|---|
| FRAME (F) | — | 0 | Back plate (backdrop/cushion), body fill, roof, two fixed posts, paws, ribs |
| WHEEL (W) | Revolute: Ø8.70 bore on the fixed Ø8.00 post at O; V-ridge captures Z | 1 (φ) | Star teeth in the band layer, Ø36 "umbrella" (yarn-ball face), Ø10 knob |
| HEAD (H) | Revolute: Ø8.70 blind bore on the fixed Ø8.00 post at P; V-ridge captures Z | 1 (ψ), banking ±12.42° | Band layer (hub, legs, pallet fingers), face (full height), front layer that overhangs the roof |

**Motion flow.**

1. The finger torque T on the knob turns W.
2. A star tooth flank meets one round pallet tip, kicks the head away and sends it swinging.
3. The other pallet dives into the next tooth gap and is caught by the next tooth's opposite flank. The swing reverses and the cycle repeats.

The result is one head oscillation per tooth, so f_head ≈ 8 × (wheel rev/s). The wheel and head are coupled only through this intermittent contact. The mechanism is a runaway pin-pallet escapement with no restoring spring. The wheel speed rises roughly with √T, which gives the governor or "honey" feel.

### 2.3 Escapement geometry (frozen core values)

Parameters, from the ideation search, re-centred and re-verified here:

| Parameter | Value |
|---|---|
| N | 8 |
| Rt (tip radius) | 14.2992 |
| Tooth height | 5.3968 |
| Rr (root radius) | 8.9024 |
| tip_frac | 0.0765 |
| root_frac | 0.1333 |
| Corner rounding | r_f = 0.70 |
| rp (pallet tip radius) | 2.1448 |
| drho (pallet depth) | 1.8686 |
| m (pallet span in pitches) | 2 |
| tilt | 0.8792 |
| ψ_b (banking) | 12.42° |

Derived values:

- pitch p = 45°
- γ = (m + ½)·p/2 = 56.25°
- ρ = (Rt + Rr)/2 + rp + drho = 15.6142 (pallet-centre radius)
- **D = ρ·tilt / cos γ = 24.710** (so P = (0, D))
- **Pallet centres (head frame) = (±ρ sin γ, ρ cos γ) = (±12.983, 8.675)**
- Pallet arm |pallet − P| = 20.632
- Pallet span = 112.5° (2.5 pitches)
- Pallet radial direction u = (±0.8315, 0.5556)

**Star2D (wheel frame).** For k = 0…7, with a0 = 45°·k, take the polar vertices in this order:

1. (Rr, a0 − 3.000°)
2. (Rr, a0 + 3.000°)
3. (Rt, a0 + 22.5° − 1.721°)
4. (Rt, a0 + 22.5° + 1.721°)

So root lands are centred on 0°, 45° and so on, and tip lands on 22.5°, 67.5° and so on. Then round the convex corners (offset −0.70 then +0.70, round joins) and the concave corners (offset +0.70 then −0.70).

**Pallet fingers (head frame).** Each finger is the union of:

- the disc(pallet_i, 2.1448), and
- a trapezoid running radially outward along u_i for 7.0 mm. Its half-width is 2.1448 at the pallet centre and 3.129 at its outer end (8° half-angle taper).

### 2.4 Computational design element: algorithm, equations, objective

**(a) Jam-free C-space screen (static, hard banking).**

The wheel's signed distance field is SDF_W on a 0.05 mm grid. The pallet clearance is

c(φ, ψ) = min_i [ SDF_W( Rot(−φ)·( P + Rot(ψ)·(p_i − P) ) ) − rp ]

The free set is c ≥ 0. A "lazy" head stays at its current ψ unless pushed. For each φ step of 0.25° over two pitches, in both directions, the head moves to the nearest free ψ in [−ψ_b, ψ_b].

A design is rejected if any of these hold:

- The free channel disappears (a jam).
- The contact pressure angle on a forced push exceeds 90° − atan μ − 8° = 62.7° at μ = 0.35.
- The best print-pose clearance is below 0.5 mm.

The ideation random search (1000+ samples) chose the parameters above to maximise swing under these constraints.

**(b) Contact dynamics, extended here to 6 DOF (`esc_dyn3.py`).**

- Wheel state: x, y, φ, with J_w = 4e-6 (finger included), m_w = 6 g.
- Head state: x, y, ψ, with I_h = 5.25e-6 and m = 15.8 g. The centre of mass is 11.3 mm above P, so gravity makes the head an inverted pendulum.
- Pallet contacts: penalty k = 5e4 N/m, ζ = 0.25, Coulomb μ.
- Journals: radial play c_r, penalty k_b = 2e5 N/m, friction torque μ_b·N·r_b with r_b = 4.0 mm.
- Knob: tangential force T/r_k at the knob, which also side-loads the wheel journal.
- Banking: hard stops at ±12.42° (k = 100 N·m/rad).
- Viscous losses: c_w = 2e-7 and c_a = 2e-8 N·m·s.
- Integration: explicit, dt = 1e-5 s.

**(c) Tolerance-window placement of the pallet depth (new in this stage).**

- **Static lock map** (`static_map.py`). At drho = 1.8686 there are no static jams anywhere in the box Δpivot ∈ [−0.4, +0.4] × Δrp ∈ [−0.2, +0.2]. The worst pressure angle in the box is 59°, below the 62.7° limit. Static locks start at drho ≤ 1.72 in the worst corner (Δrp = +0.2, Δpivot = −0.4).
- **Dynamic free-spin edge** (with play and hard banking). The first tooth slip appears at drho ≥ 2.17 in the worst corner (Δpivot = +0.4, Δrp = −0.2, c_r = 0.5).
- **Result.** drho = 1.8686 has about −0.15 mm margin to static lock and about +0.30 mm margin to slip, both at the worst tolerance corner. Journal play tends to relieve locks, because contact forces push the bodies apart.

**(d) Shadow test for the real head outline (`check_cspace_final.py`).**

The full band-layer outline of the head was checked against the real star at 91 × 51 poses (fingers, legs and hub, built as in §2.5). Where the pallets are free, the rest of the head is never closer to the wheel than the pallets: deficit = 0.000 mm.

- Best print pose: φ = 12.0°, ψ = +5.96°, giving a minimum pallet-to-tooth gap of **1.38 mm**.
- Symmetric alternative: φ = 0°, ψ = 0°, giving 0.69 mm.

**(e) Swept-envelope synthesis.** The body cavity, roof, face undercut slot, backdrop, stop pads and rib fields are all computed as unions of the moving outlines over ψ ∈ [−12.42°, +12.42°]:

- Sample at least 100 poses (step ≤ 0.25°).
- Add 0.05 mm to every swept offset for chord error.

**(f) Per-skin inertia tuning.** Compute I_h about P from each skin's head mesh at the specified infill. It must fall in [4.0, 8.0]e-6 kg·m². Trim with closed internal pockets (walls ≥ 2.0) or with ear/antenna size.

**Verified performance** (solid head, c_r 0.35, μ = μ_b = 0.35, hard banking, gravity upright, both directions; `final2.log`):

| T (N·mm) | Wheel (rev/s) | Head shiver (Hz) | Swing (° p-p) | Clicks/s | Peak contact (N) |
|---|---|---|---|---|---|
| 1 | 0.61–0.74 | 5.1 | 16–17 | ~50 | 2.4 |
| 2 | 1.05–1.14 | 7.7–9.0 | 18–20 | ~75 | 4.5 |
| 3 | 1.27–1.34 | 10.3–11.5 | 20–22 | 72–87 | 5.4 |
| 5 | 1.61–1.73 | 12.8–14.1 | 19 | 90–97 | 7.4 |
| 10 | 2.43–2.47 | 18–20.5 | 22–24 | 105–117 | 12.7 |
| 20 | 3.53–3.56 | 28 | 24–25 | ~120 | 17.8 |
| 40 | 4.63–4.69 | 37 | 24 | ~130 | 27.9 |

Bearing losses are 22–27% at the wheel and 6–19% at the head. That compares with ≥ 50% for the ideation R21 rim bearing.

**Robustness** (`hardbank*.log`, `final2.log`, `jw.log`):

- **Tolerance corners:** 60/60 hard-banking corner runs work. The corners were Δpivot ±0.4, Δrp ±0.2, c_r 0.25/0.5, T = 1/3/20, both directions.
- **Friction:** every corner works at μ/μ_b = 0.5/0.5 and at 0.2/0.2. At μ = 0.6 (dry PETG-like), 3 of 16 runs stall, so the material must be PLA.
- **Head inertia:** works from 2.9e-6 to 1e-5.
- **Wheel inertia:** works from 8e-7 to 1.5e-5. The only failure is a harmless occasional tooth slip at J_w 8e-7 combined with the worst shallow corner.

**Why the cam-style "pressure angle ≤ 30–35°" rule does not apply.** This is an impulse escapement, not a continuously driven cam. The governing criterion is friction lock: the contact angle must stay below 90° − atan μ − margin. The computed worst case is 56–59°, against a 62.7° limit at μ 0.35 with 8° margin. The dynamics model friction explicitly and show no lock for μ ≤ 0.5.

**Dead points.** The knob drives the wheel directly with no linkage. The escapement's free channel stays open throughout the tolerance box in both directions.

### 2.5 Exact 2-D definitions (all skins)

Notation:

- ⊕ / ⊖: offset (round joins).
- Swept(X) = ∪ over ψ ∈ [−12.42°, 12.42°] of Rot_P(ψ)(X), in the world frame.
- SweptInv(X) = ∪ over ψ of Rot_P(−ψ)(X), in the head frame.
- open_t(X) = (X ⊖ t/2) ⊕ t/2. This removes slivers thinner than t.

**Head frame**

- Hub2D = disc(P, 7.0)
- Leg2D_i = stadium of width 7.0 from A_i = (±17.462, 11.667) (that is, 21.0·u_i) to B_i = (±11.0, 26.0). B_i must lie at least 3 mm inside Face2D.
- Face2D comes from the skin (§4.4).
- WheelEx2D = SweptInv(disc(O, 14.90))
- BallEx2D = SweptInv(disc(O, 19.00))
- **HeadBand2D** = [(Face2D ∪ Hub2D ∪ Leg2D_L ∪ Leg2D_R) − WheelEx2D] ∪ Finger2D_L ∪ Finger2D_R
- **FaceUp2D** = Face2D − BallEx2D. The minimum gap from the face to the ball rim over the full swing is 1.53–1.71 mm.

**World frame**

- Exposed2D = HeadBand2D − FaceUp2D. These are band parts not hidden under the head's own face.
- **Body2D** = round_r3( disc(O, 21.5) ∪ [Swept(Exposed2D) ⊕ 3.0] ∪ SkinBodyDecor2D ∪ PawFootprints2D ). The wall is at least 2.5 mm beyond every channel.
- Cavity2D = Swept(HeadBand2D) ⊕ 0.55
- **Fill2D** = open_1.6( Body2D − Cavity2D − disc(O, 14.80) ) ∪ StopPads2D
- **StopPads2D**: for s = ±1 and i = L, R:
  - Pad = [Rot_P(s·12.42°)(Leg2D_i) ⊕ 0.55] − Swept(HeadBand2D), intersected with disc(Rot_P(s·12.42°)(M_i), 3.0), where M_i = (A_i + B_i)/2 = (±14.23, 18.83).
  - This gives four pads. Each leg flank touches its pad exactly at ±12.42°.
- **Roof2D** = open_1.6( Body2D − disc(O, 17.10) − disc(P, 7.50) )
- RoofSweepInv = SweptInv(Roof2D ⊕ 0.55), in the head frame.
- **FaceMid2D** = FaceUp2D − RoofSweepInv
- **I3_2D** = FaceUp2D ∩ RoofSweepInv. This is where the face's front layer overhangs the roof, about 189 mm² for the kitty.
- **Backdrop2D** = round_r2( Body2D ∪ [Swept(FaceUp2D) ⊕ 2.0] ∪ SkinBackdrop2D )

### 2.6 Z stack (print orientation, mm)

| z | FRAME | WHEEL | HEAD |
|---|---|---|---|
| 0.0–2.0 | Back plate = Backdrop2D (0.5×45° bottom-edge chamfer) | — | — |
| 2.0–2.6 | Skid ribs on the back plate (§3.4) | — | — |
| 2.0–7.6 | Posts Ø8.00 at O and P (V-ridge, §3.3) | — | — |
| 3.0–7.4 | Fill2D extrusion (2.0→10.4, trimmed by the umbrella keep-out) | Star2D teeth z 3.0–8.0 | HeadBand2D (fingers, legs, hub, face base) |
| 7.4–8.4 | (fill continues) | Umbrella plate from 8.0 | FaceMid2D starts at 7.4 |
| 8.4–10.4 | Roof2D (bridges the leg channels, 1.0 above the legs) | Cone, 45° | FaceMid2D (to 11.4) |
| 10.4–11.0 | Roof-top ribs under I3 (§3.4); paws start | Cone / rim | — |
| 11.4–15.4 | Paws (to 16.0) | Rim to 13.3; knob 13.3–18.3 | FaceUp2D front layer (overhangs the roof in I3) |
| 15.4–16.0 | Paw tops | Knob | Face features (raised 0.6) |

**Body thicknesses.** Face 16.0, body roof 10.4, ball top 13.3, knob top **18.3** (overall depth).

**Kitty overall size.** **52.7 W × 82.9 H × 18.3 D**, about 37 g PLA:

- head solid 15.9 g
- wheel solid about 8 g
- frame about 13 g at 3 walls and 20% infill

The size is within the 85 mm limit.

### 2.7 Body construction (3-D)

**HEAD** =

- extrude(HeadBand2D, 3.0→7.4)
- ∪ extrude(FaceMid2D, 7.4→11.4)
- ∪ extrude(FaceUp2D, 11.4→15.4)
- ∪ face features (15.4→16.0)
- − hub bore at P (§3.3)
- with the top perimeter of FaceUp2D rounded r 1.5. Approximate it with 6 inset steps if not using B-rep.

**WHEEL** =

- extrude(Star2D, 3.0→8.0)
- ∪ revolve about O of the profile (r, z): (0, 8.0) → (14.30, 8.0) → (18.00, 11.70) → (18.00, 12.30) → r 1.0 fillet → (17.00, 13.30) → (0, 13.30)
- ∪ knob: cylinder Ø10.0 centred at (11.0, 0) in the wheel frame, z 13.3→18.3, top fillet r 2.5, root fillet r 1.0
- − bore at O (§3.3)
- − skin top relief: grooves 0.6 wide × 0.5 deep, kept at least 1.5 mm from the knob root and the rim.

**FRAME** =

- extrude(Backdrop2D, 0→2.0)
- ∪ [extrude(Fill2D, 2.0→10.4) ∪ extrude(Roof2D, 8.4→10.4)] − KeepOut_U
- ∪ posts
- ∪ ribs
- ∪ paws (§3.5)
- ∪ skin body decor (raised z 10.4→12.0, kept at least 2 mm outside Swept(FaceUp2D))

KeepOut_U = revolve about O of the polygon (0, 2.0) → (14.80, 2.0) → (14.80, 7.80) → (18.60, 11.60) → (18.60, 40) → (0, 40).

This keep-out leaves a 45° funnel seat 0.50 normal below the umbrella cone, 0.60 radial from the rim, and a 0.40 vertical gap where the roof's inner edge (r 17.10) tucks under the ball rim. Exterior plan corners are r ≥ 1.5 and top edges are filleted r 1.0.

---

## 3. Dimensions, clearances, printing and capture

### 3.1 Dimension table (core; kitty skin where noted)

| Item | Value |
|---|---|
| Wheel axis O / head axis P | (0, 0) / (0, 24.710) |
| Escape wheel | 8 teeth; Rt 14.299, Rr 8.902; teeth z 3.0–8.0 (contact height 4.4 with pallets) |
| Umbrella (yarn-ball face) | Ø36.00; 45° cone from r 14.30 @ z 8.0 to r 18.00 @ z 11.70; rim to z 13.30; r 1.0 top fillet |
| Knob | Ø10.0 × 5.0 at r_k 11.0; top fillet r 2.5, root fillet r 1.0 |
| Pallet tips | Ø4.290 at (±12.983, 8.675) head frame; fingers 7.0 long, 8° taper (root width 6.26); z 3.0–7.4 |
| Pallet arm / span / banking | 20.632 / 112.5° / ±12.42° (4 stop pads) |
| Head legs | 7.0 wide, (±17.462, 11.667) → (±11.0, 26.0); z 3.0–7.4 |
| Hub | disc r 7.0 around P, band layer |
| Kitty face | circle C_h = (0, 35.710), r 16.0, plus ears (§4.4); full height z 3.0–15.4; front layer 11.4–15.4 |
| Posts (×2) | Ø8.00, z 2.0–7.6, 0.6×45° top chamfer, r 1.0 root fillet; V-ridge apex r 4.80 @ z 5.0, 45° flanks (ridge spans z 4.2–5.8) |
| Bores (×2) | Ø8.70, z 3.0 → roof 8.0; 0.6×45° entry chamfer; V-groove apex r 5.295 @ z 5.0, 45° flanks meeting the bore wall at z 4.055 / 5.945 |
| Back plate | 2.0 thick |
| Body fill / roof | z 2.0–8.4 / 8.4–10.4; roof hole r 17.10 (O) and r 7.50 (P); body ring r 21.5 around O |
| Leg channels (roof bridges) | max span 13.0 (computed), 1.0 mm over the legs |
| Paws (×2) | angular span −10°…+25° (right) and 155°…190° (left) about O; r 18.6 → body outline; z 10.4–16.0; lip underside z = 31.3 − r for r ∈ [17.0, 18.6]; inner face r 17.0 for z 14.3–16.0 |
| Skid ribs | 0.8 wide × 0.6 tall; back plate pitch 4.5, roof top pitch 4.0 |
| Overall (kitty) | 52.7 × 82.9 × 18.3 (16.0 at face) |

### 3.2 Clearances (all designed values)

| Interface | Gap |
|---|---|
| Post ↔ bore journal (radial) | 0.35 |
| V-ridge ↔ V-groove (normal) | 0.35 (0.495 radial, 0.495 axial; the journal takes radial load) |
| Post top ↔ bore roof (Z) | 0.40 |
| Wheel/head underside ↔ back-plate ribs (Z) | 0.40 at ribs / 1.00 field |
| Head legs/fingers top ↔ roof underside (Z) | 1.00 (roof printed as bridges) |
| Pallet top ↔ umbrella plate (Z) | 0.60 |
| Head band ↔ frame fill (XY, swept) | 0.55 incl. sweep allowance; stop pads contact at ±12.42° |
| Wheel tooth tips ↔ frame fill (XY) | 0.50 (14.30 vs 14.80) |
| Umbrella cone ↔ funnel seat (normal) | 0.50 |
| Umbrella underside ↔ roof top at r 17.10 (Z) | 0.40 |
| Umbrella rim ↔ paw inner wall (radial) | 0.60 |
| Umbrella top ↔ paw lip (Z) | ≥ 1.00 (lip only stops lift if the V-ridge fails) |
| Knob ↔ paw lip face (radial, constant) | 1.00 |
| Face mid layer ↔ roof edge (XY, swept) | 0.55 |
| Face front underside ↔ roof-top ribs (Z) | 0.40 at ribs / 1.00 field |
| Face (FaceUp) ↔ ball rim (XY) | 1.53–1.71 over the swing (designed ≥ 1.0) |
| Pallet ↔ tooth at print pose (φ 12.0°, ψ +5.96°) | 1.38 |

Clearance variant "loose" (rough printers): journals 0.40, swept gaps 0.60, rib Z gap 0.45 (shift every floating body up 0.05), ridge normal 0.40.

### 3.3 How every moving part is captured

Each part is held by geometry, never by friction.

| Body | Radial | −Z | +Z | Independent second capture |
|---|---|---|---|---|
| HEAD | Ø8.00 post in Ø8.70 blind bore | back-plate ribs | V-ridge in hub V-groove | The roof edge is clamped in the head's I3 slot: band layer below (z ≤ 7.4) and front layer above (z ≥ 11.4) on both shoulders. The head cannot lift, tilt out or be pried off even with a broken ridge |
| WHEEL | Ø8.00 post in Ø8.70 blind bore | funnel seat / ribs | V-ridge in wheel V-groove | Two paw lips over the umbrella rim limit lift to ≤ 1.0 mm. The umbrella cannot pass the paws (Ø36 vs lip r 17.0) |

Strength checks:

- Ridge pull-out: about 450 N to shear (45 mm² × 10 MPa interlayer).
- Hub hoop stress at 300 N pull: 3.2 MPa.
- Posts in bending at 36 N impact: 1.5 MPa. A 50 N sideways yank on the head gives 3 MPa.
- Pallet fingers in-plane at 28 N: 6.4 MPa.
- Legs in-plane at 28 N (7.0 wide, moment arm 15.5): 11 MPa peak (40 N·mm case only); 7.5 MPa or less for T ≤ 10.
- Knob under a 50 N side push: about 3 MPa interlayer.
- Hertz pallet/tooth contact: about 39 MPa at the 40 N·mm peak, 21 MPa typical. Use PLA/PLA+.

### 3.4 Print orientation, layers, overhangs and bridges

**Orientation and slicing**

- One print, face up, with the back plate on the bed. Do not scale.
- 0.2 mm layers, 0.4 nozzle, no supports, no brim (the back plate is a large flat base).
- **The first layer has no moving gaps at all**, so elephant foot cannot fuse the mechanism. Use 0.1 elephant-foot compensation for looks only.
- Every working clearance is either a vertical wall with an XY gap, or a Z gap of one of these designed types:
  1. **Floating over skid ribs.** The head and wheel undersides (z 3.0) sit over back-plate ribs (z 2.0–2.6) at 0.40, with 1.00 elsewhere. The face's front layer in I3 sits over roof-top ribs (10.4–11.0) at 0.40.
  2. **Bridges with 1.0 mm air below.** The roof bridges the leg channels (span ≤ 13.0).
  3. **Bridges with small spans.** The umbrella plate bridges the tooth gaps (≤ 10.3, 0.6 over the pallets). The bore roofs bridge Ø8.7 (0.4 over the post tops).
  4. **45° self-supporting surfaces.** The umbrella cone, V-ridge and V-groove flanks, and paw lips.

**Rib layout**

- Back plate: arcs about P at r = 6.0 + 4.5·j (j = 0…8), clipped to Swept(HeadBand2D) − disc(O, 14.8). Rings about O at r 7.0, 11.0 and 13.8, clipped to disc(O, 14.3). Keep everything at least 0.3 mm clear of post root fillets.
- Roof top: arcs about P at r = 9.0 + 4.0·j (j = 0…7), clipped to Roof2D ∩ Swept(I3_2D ⊕ 0.5).
- The visible back-plate arcs read as cushion quilting, and the visible roof arcs read as a collar ruff.

**Overhang rule.** Any downward-facing area steeper than 45° from vertical must be one of:

- the bed,
- a listed bridge, or
- a listed rib-supported float.

Nothing else is allowed.

**Print pose.** Wheel at φ = +12.0° (Star2D rotated CCW; knob at 12.0°). Head at ψ = +5.96°. The kitty prints with a 6° curious head-tilt.

**Export**

- One 3MF: one object with three parts (frame, wheel, head) so per-part infill can be set. Also export one STL with three shells.
- Per-body STLs.
- STEP is optional.

---

## 4. Parametric model structure

### 4.1 Tool choice

- **Python + manifold3d** for everything solid. Use `CrossSection` (Clipper2: robust integer 2-D booleans and offsets) for all 2-D work and sweeps. Use `extrude` per Z band, `revolve` for the posts, bores, umbrella and keep-out, and `Manifold` booleans to assemble. This approach is fast and robust.
- **shapely/numpy** only for analysis: SDF grid, distances, C-space. shapely unions of many rotated copies threw topology exceptions in testing, so do the production sweeps in `CrossSection`.
- **build123d** is optional: B-rep fillets on skin outlines and STEP export.
- **OpenSCAD 2021.01** only to `import()` STLs for headless PNG renders. CGAL is too slow for the sweeps.
- **trimesh** for proximity, ray-cast thickness, mass properties and 3MF export.

### 4.2 Modules

1. `params.py`: one JSON or dict holding all named parameters:
   - escapement: `N, Rt, tooth_h, tip_frac, root_frac, r_f, rp, drho, m, tilt, psi_b`
   - layout: `post_d, bore_d, ridge_h, ridge_z, hub_r, leg_w, leg_A_r, leg_B, finger_L, finger_taper, R_u, R_hole_roof, R_hub_cut, body_r, wall, gap_xy, gap_rib, gap_field, sweep_allowance, ball_ex_r, wheel_ex_r, backdrop_margin, r_k, knob_d, knob_h, paw spans, rib pitches`
   - Z levels: `z_bp, z_band0, z_band1, z_roof0, z_roof1, z_front0, z_front1, z_feat`
   - print pose: `phi_print, psi_print`
   - skin name
2. `escapement.py`: `star2d()`, `pallet_centres()` (equations in §2.3), `fingers2d()`.
3. `sweep.py`: `swept(cs, pivot, psi_b, n≥100, allowance)`, `swept_inv()`. Implement with CrossSection rotate + batch union.
4. `core2d.py`: HeadBand2D, FaceUp2D, Exposed2D, Body2D, Cavity2D, Fill2D, StopPads2D, Roof2D, FaceMid2D, I3_2D, Backdrop2D, rib fields.
5. `solids.py`: extrusions per §2.6/§2.7; posts and V-ridges (revolve a triangle profile); bores and V-grooves; umbrella and keep-out (revolve); knob; paws (lip built as a stack of 0.2 mm slices or a hull of two offset sections); stepped top fillets; bottom chamfers.
6. `skins/kitty.py`, `skins/bee.py`, `skins/robot.py`: each skin implements the interface in §4.3.
7. `assemble.py`: pose bodies to the print pose, assert pairwise disjointness, export.
8. `verify/`: scripts for §5. Reuse `esc_layout2.py`, `static_map.py`, `esc_dyn3.py` and `run_hardbank.py`, fed from the CAD outlines and trimesh mass properties.

### 4.3 Skin interface (contract)

A skin supplies the following. The core derives everything else automatically.

- `face2d(C_h)`: polygon. It must contain disc(P, 7.5) and both leg ends B_i with ≥ 3 mm margin. No feature narrower than 6.0 mm, and outer corners r ≥ 2.
- `face_features()`: a list of (2-D shape, mode, depth). Raised features are 0.6 (z 15.4→16.0). Debossed features are 0.3–0.5. All stay ≥ 3 mm inside FaceUp2D's edge.
- `backdrop2d()`: extra outline unioned into Backdrop2D. The final outline must stay ≤ 64 W × 85 H.
- `body_decor2d()`: raised 1.6 reliefs (feet, tail and so on) on the roof. Each must lie inside Body2D and ≥ 2 mm outside Swept(FaceUp2D).
- `paw_style()`: plan outline inside the core paw spans, with top debossing.
- `wheel_relief2d()`: groove pattern for r ≤ 16.5, excluding a Ø14 zone around the knob.
- **Inertia check:** I_h about P from trimesh (solid PLA, 1.24 g/cm³) must be in [4.0, 8.0]e-6 kg·m², and the centre of mass 8–14 mm above P. If not, add closed pockets in FaceMid2D (walls ≥ 2.0) or resize the ears.

### 4.4 The three skins (parameters)

**Purr Kitty (default)**

Face2D:

- Disc(C_h = P + (0, 11.0), r 16.0).
- Two ears. Each is a triangle with base points at C_h + 14.72·(sin a, cos a) for a = ±14° and ±54°, and tip at C_h + 22.5·(sin ±34°, cos ±34°). Round it with ⊕2.6 then ⊖0.6.

Features (relative to C_h):

- Eyes: Ø7.0 raised domes at (±6.5, −1.0), each with a Ø2.0 × 0.4 highlight dimple at (+1.3, +1.3) from the eye centre.
- Nose: rounded triangle 3.0 × 2.2, raised, at (0, −5.0).
- "ω" mouth: two r 1.8 arcs, 0.8 wide × 0.5 deep, centred at (±1.8, −7.2).
- Blush: ellipses 5 × 3 debossed 0.3 at (±10.0, −6.5).
- Inner ears: deboss 0.4, inset 2.0.

Measured on this skin: mass 15.9 g, I_h 5.25e-6, centre of mass 11.3 mm above P.

Frame and wheel:

- Backdrop: a round cushion. The computed outline gets a 0.6 × 0.3 stitch groove 1.6 mm inside the edge.
- Feet: ovals 9 × 5 at (±8.5, −20.0).
- Tail: stadium of width 5 along (−13, −18) → (−21, −14) → (−23, −9).
- Paws: toe-bean dimples (Ø5 + three Ø2.5, 0.4 deep).
- Wheel: three families of yarn arcs.

**Bumble (bee)**

Face2D:

- Disc(C_h, 16.0).
- Antennae: stadium 6.0 wide from C_h + 13·(sin ±22°, cos ±22°) to C_h + 21·(sin ±30°, cos ±30°), each ending in a Ø8.0 disc.

Features: eyes as for the kitty, a "u" smile, cheek dots.

Frame and wheel:

- Backdrop: union of disc(C_h, 19) and five petals of Ø16 at C_h + 19·(sin(72k + 36°), cos(…)), clipped to ≤ 64 W.
- Wheel: hex dimples Ø4 × 0.5.
- Paws: become striped bee legs (0.4 deboss).

**Pip the Robot**

Face2D:

- Rounded rectangle 34 × 28 (r 7) centred at C_h + (0, 1).
- Antenna: stadium 6 wide from C_h + (0, 14) to C_h + (0, 19), with a Ø8 ball at C_h + (0, 20.5).
- Ear bolts: discs r 3.5 at C_h + (±17.5, 0).

Features: visor deboss 24 × 9 (r 4.5, 0.5 deep) with two Ø6 raised LED eyes, and a three-slot mouth grille.

Frame and wheel:

- Backdrop: porthole disc r 27 at C_h − (0, 4), with Ø2 rivet dimples.
- Wheel: gear-tooth rim relief and a power symbol.
- Paws: become clamps.

Per §4.3, verify I_h for each skin and trim with pockets.

---

## 5. Verification plan (pass/fail)

| # | Check | Method | Pass criterion |
|---|---|---|---|
| V1 | Escapement parameters | Recompute from params | D = 24.710 ± 0.001; pallets (±12.983, 8.675) ± 0.001 |
| V2 | Static jam screen on exported 2-D profiles | `static_map.py`-style lazy-head C-space, hard banking, both directions, Δpivot ∈ {−0.4, 0, +0.4} × Δrp ∈ {−0.2, 0, +0.2} | 0 jams in all 9 cases; worst pressure angle ≤ 60° (hard limit 62.7°) |
| V3 | Shadow test (only tips touch) | Full HeadBand2D vs Star2D, φ 0–90° step 0.5°, ψ ±12.42° step 0.25° | Where c_pins ≥ 0: c_full ≥ min(c_pins, 0.6) − 0.02 |
| V4 | Dynamics on as-modelled geometry | `esc_dyn3.py` with CAD profiles, trimesh I_h/m/COM, hard banking, gravity, knob r_k 11.0 | All of: 60 tolerance corners (Δpivot ±0.4, Δrp ±0.2, c_r 0.25/0.5, T 1/3/20, both directions) run; μ/μ_b 0.5/0.5 corners run; each run has rev/s ≥ 0.15, rev/s ≤ 2.2 × nominal and swing ≥ 8° p-p; nominal f(T) within ±25% of the §2.4 table |
| V5 | 3-D collision sweep | manifold3d: head ψ −12.42…+12.42 step 0.25°; wheel φ 0…45° step 0.5° (one pitch), plus φ 0…360° step 2° for knob/paw/face checks | Intersection volume frame∩head = frame∩wheel = 0 at every pose (stop pads may touch only at |ψ| = 12.42°); head∩wheel = 0 at every C-space-free (φ, ψ) |
| V6 | Minimum clearances | trimesh proximity on ≤ 0.2 mm surface samples, all poses of V5 | Journals 0.35 ± 0.02; ridge normal ≥ 0.33; head↔fill ≥ 0.50 (|ψ| ≤ 12.2°); face-mid↔roof ≥ 0.50; wheel↔frame ≥ 0.45 XY / ≥ 0.40 Z; face↔ball rim 1.4–2.0; knob↔paw ≥ 0.9; rib Z gaps 0.40 ± 0.02, field ≥ 0.95 |
| V7 | Print pose | Pose of §3.4 | Three disjoint watertight shells; global min gap ≥ 0.35; pallet↔tooth ≥ 1.3 |
| V8 | Topology and wall thickness | trimesh; inward ray casting, ≥ 2000 samples per body | Each body one connected manifold; walls ≥ 1.2 everywhere, back plate/roof ≥ 2.0, fingers ≥ 4.29, legs ≥ 7.0, posts Ø8.0; no slivers < 1.6 in Fill2D/Roof2D |
| V9 | Overhang map | Face normals at print pose | Every face > 45° from vertical is bed, a listed bridge (roof ≤ 13.5, umbrella plate ≤ 10.5, bores Ø8.7), or a listed rib-supported float with rib pitch ≤ 4.5 and gap 0.40 |
| V10 | Small parts | Min width over all orientations plus cylinder-fit test (Ø31.7 × 25.4) | Wheel ≥ 35.5 (designed 36.0); head ≥ 38 (designed 41.0); no body fits. Every breakable protrusion (knob, ears, antennae, paws) has a root ≥ 8 × 5 and < 10 MPa under a 50 N lateral load |
| V11 | Captivity | Displace each moving body 1.0 mm in ±X, ±Y, ±Z at 20 poses; repeat with V-ridges deleted | Always interferes, i.e. cannot separate, including the ridge-less case (head held by the I3 slot; wheel lift ≤ 1.0 before the paws stop it) |
| V12 | Pinch audit | Track every exposed moving edge against neighbours in the same Z band over the full sweep | Each gap is constant (variation ≤ 0.1), < 2.0 mm, or ≥ 12 mm. Nothing may vary across the 2–12 mm band |
| V13 | Mass properties | trimesh, per skin | I_h ∈ [4.0, 8.0]e-6 kg·m²; COM 8–14 above P; total ≤ 45 g |
| V14 | Renders | `xvfb-run -a openscad --render -o …png` on imported STLs | Front, back and ¾ views at ψ = −12.4°, 0, +12.4° (wheel at 3 angles); section at x = 0 and at the pallet (z 5.2); GIF of one tooth cycle from V4; all three skins |
| V15 | Physical | Escapement coupon (core only: back plate, posts, wheel band and plate, head band with a 30 × 20 × 8 mass block, roof; about 35 min) | Frees by hand; turns both directions; no free spin at a slow turn; slow-motion phone video shows shiver frequency within ±30% of the table at a slow turn (≈ 1 rev/s) and a fast turn |

---

## 6. Child safety and print/finishing instructions

### Safety design

- **Three bodies, all larger than the small-parts cylinder:** wheel Ø36.0, head 41 mm minimum width, frame about 53 × 83 mm.
- **Nothing designed to detach.** Each moving body has two independent geometric captures (§3.3).
- **No springs or flexures.** Nothing can fatigue, creep or splinter.
- **Escapement sealed.** The nip is enclosed by the back plate behind, the umbrella in front, and the roof and fill around it. The only openings are 0.4–1.0 mm Z gaps and shear slits.
- **Exposed moving boundaries.** Each is a concentric constant gap, a Z overlap, or a slit under 2 mm:
  - umbrella rim to frame: 0.6 concentric / 0.9 overlap
  - face front layer edges sliding over the roof: 0.4–1.0 Z gap
  - face chin to ball rim: 1.5–1.7
  - knob to paw lip: 1.0 constant
  - head over backdrop: Z gap only, so the ears have no in-plane neighbours at all
- **Low energy.** The only power source is the child's finger. The head carries ≤ 6 mJ even at the fastest buzz, and the ear tip moves ≤ 1.5 m/s.
- **Robust shapes.** All edges r ≥ 1.0 (exterior ≥ 1.5). Ears, antennae and paws are at least 8 mm wide at the root and 12 mm thick in Z. The knob is Ø10 with a root fillet.
- **Noise.** At a hard push the buzz is loud, about 130 clicks/s.
- **Label:** "Ages 6+. Home 3D-printed toy, not certified to EN 71 / ASTM F963. An adult should inspect for cracks before each play session. Do not give to children who mouth toys."

### Material

- Use **PLA or PLA+ only**. The mechanism needs pallet friction μ ≤ 0.5.
- Do not use dry PETG: at μ ≈ 0.6 it can stall at worst-case tolerances.
- Avoid silk PLA (weak and higher shrink).

### Slicer settings

- 0.2 mm layers.
- 3 perimeters. Frame infill 20% gyroid. **Head and wheel at 100% infill** (part modifiers); this gives the computed inertia.
- 5 top / 5 bottom layers.
- Arachne is fine.
- Seam: rear/aligned. Paint the seam onto the outer back-plate and body outline, never on post or bore walls.
- Z-hop 0.4.
- Bridges: fan 100%, speed about 25 mm/s, "thick bridges" off.
- Max fan for overhangs.
- No supports, no brim.
- Expect about 2.5–3 h on an MK4 / A1 / P1S, and about 37 g.

### Freeing (break-in)

1. Let the bed cool below 30 °C before removing the print. Removing it hot can tack the floats.
2. Hold the body and rock the head left and right 10 times with gentle thumb pressure. You should feel crisp releases as the rib contacts let go.
3. Turn the knob slowly: 5 turns each way, then 30 s fast each way.
4. If the wheel will not move, look for strings in the slits around the ball and between the chin and the ball. Clear them with a pick, then retry.
5. Never use pliers.
6. No lubricant is needed in PLA.
7. Finally, pull the head and the ball firmly (about 20 N). Neither should move more than about 1 mm.

**Optional colour.** A filament swap at z 15.6 and back at z 16.2 prints the raised eyes, nose and mouth in black. The knob will get a decorative dark band. Never use stickers or glued eyes: they are small parts.

---

## 7. Risks and fallbacks

| Risk | Symptom | Fallback |
|---|---|---|
| Rib-supported floats tack (head and wheel over the back plate, about 1,590 mm² total; face front over roof ribs, about 190 mm²) | Stiff or frozen after printing | Cool fully, then break in. If still stuck, use the "loose" variant (rib gap 0.45, journals 0.40, swept gaps 0.60). Rib pitch can drop to 4.0 |
| Wheel slips teeth or free-spins (shallow engagement: oversize post spacing, thin pallets, loose journals) | Head barely moves; ball spins easily | "Deep" variant drho 1.7186 (−0.15). Verify post spacing with a ruler coupon |
| Wheel locks or is notchy (deep engagement, fat pallets, high friction) | A hard spot each tooth | "Shallow" variant drho 2.0186 (+0.15). Confirm PLA not PETG. Check pallet tips for blobs or seams |
| Roof bridges sag onto the legs (span 13.0) | Head rubs mid-swing | Enable bridge cooling and slower bridging. Optional 0.2 increase of the leg-to-roof gap (z_roof0 8.6) |
| V-ridge too tight on some printers | Rough turning that does not wear in | Ridge normal gap 0.40 variant (journal stays 0.35) |
| Pallet and flank wear after hours of hard buzzing | Swing drops; more slipping | PLA+/tough PLA. Print the coupon and compare after a 30-minute buzz test. Shallow wear pushes toward the "deep" variant |
| Noise at hard push | Loud buzz | Heavier head (I up to 1e-5 tested OK: slower and calmer). Smaller knob radius (r_k 9; bearing loss rises to about 16%) |
| Giggle only readable at gentle turning (> about 2 rev/s is a blur) | Kids push fast | Advertise "slow = giggle, fast = purr/buzz". The heavier-head option lowers f(T) |
| Light finger touch plus worst shallow corner gives an occasional tooth slip (simulated) | A rare skip | Harmless. The deep variant removes it |
| Skins exceed the inertia band or the 85 mm envelope | V13/V10 fail | Pockets, smaller ears or antennae, or a backdrop trimmed to Swept(FaceUp2D) ⊕ 2.0 exactly |
| Head-band sweeps produce slivers in Fill2D/Roof2D | Thin fragile walls | open_1.6 is mandatory. If a wall is under 1.2, raise `wall` to 3.0 |

**Order of work**

1. Print the V15 escapement coupon first, in the target PLA.
2. Then print the full kitty.
3. Ship three STLs (nominal, deep, shallow) plus the loose-clearance variant of the nominal.

---

## 8. As-built changes (integration rounds 1 to 4)

The CAD in `purrbobble/` follows this spec except where independent verification found a problem. Every change
below is in the code with a `fix round` comment; the checkers in `verification/` test the as-built geometry.

| Area | Spec | As built | Why |
|---|---|---|---|
| Knob | Ø10 knob, 5 mm proud of the ball | Recessed spherical finger well Ø8.4 (Ø9.3 at the rounded rim) × 2.0 deep at r 11 | The knob passed the paw-lip ends like a guillotine (gap 12.4 → 1.0 mm) and under the chin (V12); a well removes the pinch and a small-part risk |
| Roof over the head | Two roof lobes over the leg channels; face front layer over roof-top ribs | Crown ring: a roof disc R_b 22.5 about P with an arc edge, band-top ribs (arcs + radial spokes every 10°) under it, front-layer ribs hanging from the head over its top | Lobe bridges reached 20.9 mm (limit 13.5); the I3 front layer had unsupported regions; the lobe ends formed a squeeze jaw with the cheeks (V9, V12) |
| Bridging direction | automatic | Frame bridges at 180° (3MF part setting; documented for STL printing) | PrusaSlicer's automatic direction ran the roof's first layer about 20 mm along a leg channel; at 180° the longest unsupported strand is 12.7 mm |
| Face front layer | z 11.4–15.4, features to 16.0 | z 13.7–17.7, features to 18.3 (overall depth still 18.3) | raised so the round face and the round ball no longer share a Z band: the crescent between cheek and ball rim was a 3.5–6 mm squeeze (V12) |
| Stop pads | [Rot(Leg) ⊕ 0.55] − Swept(HB) | also clipped to the fill wall (⊕ 0.6) | the lower pads stood out as free 0.6 mm fins (V8) |
| Funnel seat | keep-out cone trims the fill | fill tongues narrower than 3.8 mm lowered to z 8.2 | knife-edge walls down to 0.05 mm (V8) |
| Deep variant | drho 1.7186 | drho 1.7686, face kept at its nominal world position, print pose (11.6°, 6.22°) | the spec's deep variant jams at the worst tolerance corner (V2) |
| Loose variant | floats lifted 0.05 | lifted 0.20 (one layer); crown ribs shortened by the lift | a 0.05 lift disappears in 0.2 mm layer slicing |
| Pallet fingers | top at z 7.4 (0.6 under the umbrella plate) | top at z 6.9 inside WheelEx2D (1.1 under the plate) | head and wheel axial play add up to 0.8 mm, enough for the pallet tops to rub the plate when the ball is pressed (V5x) |
| Bee antennae | 6 mm stalk from C_h + 13 @ 22° to a ball at 21 @ 30° | kitty-ear-shaped tapered base (14°–54°, tip 23.6 @ 34°) carrying the ball at 23.3 @ 33° | the bare stalk left a notch at the crown edge: a 2–5 mm squeeze and a knife edge (V12) |
| Robot head | 34 × 28 rounded rectangle | kitty head circle (r 16) as a helmet over a 28.4-wide square jaw; ear bolts at the temples (C_h + (±13.5, 7), r 4.2) | the rectangle hit the stop-pad zones and its straight sides squeezed against the crown edge (V7, V12) |
| Kitty face | Ø7 eyes, 3.0 × 2.2 nose, ears to 22.5 | Ø8.4 eyes with Ø2.4 highlights, 4.0 × 2.8 nose, ears to 24.0, 0.8 mm yarn grooves, 0.4 mm debosses | design review: features too small to read and to print cleanly |
| Kitty look (round 3) | flat face features, plain body | Ø9.0 domed eyes with two highlights each, open smile with tongue, blush, inner ears, bow, fur tuft; a quilted, scalloped cushion around the character on the back plate (outline grown 3.2, r 3.9 lobes); hind feet r 5.6 with toe beans and a curled tail, raised to z 13.6 by the skin's `param_overrides`; overall 59.7 × 90.8 × 18.3 mm | restyled from the owner's concept art; the head outline and every mechanism envelope are unchanged, and the kitty trims cushion and decor height to stay under the 45 g limit (44.4 g as sliced) |
| Colour | one colour per part | an extra `_multicolour.3mf` per character: one volume per colour region (raised face details, accents, back plate / cushion) with its filament slot, at most 4 slots per character (`assemble.colour_slots`) | the concept art is multi-coloured; colour regions never cross a moving gap |
| Mass check (V13) | total ≤ 45 g | as printed ≤ 45 g: PrusaSlicer's filament weight for the exported 3MF (head and ball 100 %, frame 20 % gyroid); a shell + infill estimate when the slicer is missing; solid mass reported | the spec's 37 g budget was an as-printed figure |
| Short overhangs | ≤ 2 nozzle widths (0.8 mm) unlisted | ≤ 1.0 mm | the kitty's front-rib tails overhang the crown's P hole by 0.84 mm; a sub-millimetre perimeter cantilever prints cleanly |
| Crown field over the band top (loose) | ≥ 0.95 | ≥ 0.75 (rib gap + 0.35) | the loose lift shrinks this field to 0.80; the roof there is a rib-supported float with spans ≤ 4.2 mm |
| V12 probe raster (round 3) | not specified | 0.25 mm cells anchored to world multiples of 0.25; a cell is touched when a reachable probe centre lies within r + 0.25·√2 | the cells used to start at each skin's bounding box: the kitty's larger cushion shifted them and flipped a contact that is only 0.3 mm deep (the crown face beside the head's neck). With the fixed raster the crown-edge nip is reported on all three characters, as their geometry there is identical |
| Kitty to the concept art (round 4) | flat-topped extrusions | **Head:** a front-layer-only widening (skin hook `face_front2d`, kept by `core2d.front_extension` only where it rides on the crown roof or overhangs the full-height head by <= 1.5, clear of the ball sweep and >= 12 mm from paws and decor at every pose) gives the wide cheeks, fur tufts and forehead curls; the front layer is a pillow (top edge a 4.0 x 2.0 quarter-ellipse in 20 terraces, each re-rounded r 1.5) and features are draped over it (`solids.apply_features_draped`); Ø8 eyes at C_h + (+-10, -2.9), recessed open mouth with a flush tongue, puffy bow (raised 1.2-1.6). **Body:** skin tiers on the body top (a pillowy belly to z 11.9) and on the plate (a Ø5.4 tail tube), extra lip pieces per side (`PawStyle.span`: domed feet 16 x 17 over the ball's lower rim, same lip profile as the paws), domed mitts, a big-scallop cushion with raised piping and pillowed quilting (<= 1.0 proud: the head swings over it from z 3.0), and the frame above the plate outside a torso outline coloured as cushion. **Ball:** stepped-V grooves in the yarn-ball icon layout. Overall 65.1 x 91.5 x 19.3 mm | the owner asked for the concept art's look; every mechanism section and swept envelope is derived as before |
| Mass limit (V13) | <= 45 g | <= 50 g as printed (`v_escapement.MASS_LIMIT_G`); kitty 48.0 g | the 45 g was a budget from the first estimate, not a mechanism or safety need (frame mass does not enter V4); the concept's cushion relief, feet and tail are frame material |
| Mesh clean-up | Manifold.simplify on every body | only where the raw mesh has pinch vertices or detached pieces | simplifying the clean round-4 kitty frame tilted crown-recess step faces into small oblique overhangs (V9); bee and robot meshes keep their volumes (more triangles) |
| V8 zoning (round 4) | cosmetic windows at flat feature planes | windows start at the bottom of each pillow round; raised cushion relief is cosmetic; the frame-layer sliver check warns (not fails) on cosmetic relief | raised, draped and pillowed decoration sits below the old flat planes |

## 9. Rounds 5 to 7: the mechanism inside the owner's sculpt (Purr Kitty)

The kitty is no longer built from the parametric skin. The owner's own sculpted model
(`sculpt/Yarn_Cuddle_Kitty_Meshy_AI.3mf`, 58.2 × 75.0 × 18.9 mm) is scaled ×1.139 so its yarn ball is the 36 mm escape
wheel, and `purrbobble/sculpt.py` splits it into the three print-in-place bodies around the unchanged escapement core.
At rest the outside of the toy is the sculpt's own surface everywhere except thin seams. The round-4 kitty is kept as
the skin `kitty_classic`.

| Area | Classic skins | Sculpt kitty | Why |
|---|---|---|---|
| Bodies | Parametric head, roof, face layers, crown, paws | Head = the sculpt over its head blob (ears and bow included), each point from its own floor up; wheel = escape wheel + small umbrella + the yarn ball's centre (r 10) as a spinning cap; frame = the rest of the sculpt minus the swept envelopes, plus ribs, posts and stop pads | The owner asked for their model, not a restyled skin |
| Umbrella | R_u 17.75 (Ø 35.5), visible yarn face | R_u 15, under the sculpt's yarn ball; a hidden flange r 14.7–16.2 (underside 55° from vertical, flat top at z 10.25) runs in a stepped slot in the frame and widens the wheel to Ø 32.4 | The ball's outer strands are the static ring over the wheel; the flange keeps the wheel out of the small-parts cylinder (31.7) and prints without supports |
| Drive | Knob / finger well at r 11 | Spherical finger dish Ø 7.5 × 3 in the cap at r_k 5 | The cap is only r 10; V4 uses r_k 5 as the finger's lever arm |
| Head band | Full height z 3.0–7.4 | Legs passing under cushion too thin for a cover are lowered to 4.27 (1.27 tall); a hub collar disc(P, 6.9) z 7.4–8.4 over the bore; full-band corners rounded r 1 except at the pallet discs | Hidden under the sculpt; the collar restores the classic bore wall (2.45 mm) |
| Head floors | Flat face layers | Quantised floors (3.0, then 3.437 + 0.2 k); a floor clears everything static it swings over by gap_z + z_lift + floor_rest (0.2 more: face up the head rests on its back ribs); the rim floats above the cushion (float_z 6.95: no moat); floors rise over undercut films and where a terrace would overhang its support in the print pose | Print-in-place, rest-on-ribs clearance, printability |
| Back ribs | Arcs about P and rings about O, bridging angle 180° | The same, plus fill-in arcs and 12 radial spokes that join them into a web: a straight bridge strand in any direction crosses a rib every ≤ 5 mm | The head's and the wheel's first layers bridge over the ribs; the slicer's automatic bridge direction is safe on every part |
| Stop pads | Full-height pads | Pads only as tall as the legs that bank on them (all four legs are lowered, so all four pads are low), hidden under the cushion | No blade of frame in the neck crease |
| Frame covers | Roof ≥ 2.0 over 13.5 mm leg channels | Covers ≥ cover_t 1.25 over the lowered legs (~7 mm channel), filled up to that where the sculpt is thinner (tapered 45° bosses, ≤ 0.3 above the cushion); hidden 45° stepped eaves under the covers and over the full-height band's channel, so no cover layer starts in mid-air | The head is also held by the post ridge and the collar under the frame |
| Seams | Gaps 0.40–0.55 | gap_xy 0.5 (loose 0.55), gap_z 0.4137 over a floating body in every variant, + z_lift under it; cap seam r 10/10.5 with a 0.6 chamfer on the static ring (the two tallest yarn strands at the seam are notched over ±1°) | Off round numbers (no faces coplanar with the sculpt's flats); the chamfer keeps the ring's inner edge printable and blunt |
| Left ear | — | Where the left ear and its root swing, the cushion is lowered to z 5.0 (a crescent ~0.5–1.5 mm deep around the ear), and the ear's root keeps its floors at 5.64 | The ear's root carries the V10 protrusion load (13.4 → 9.2 MPa); visible relief, accepted for child safety |
| Balance | Head on the P axis | The mechanism axis sits 1.22 mm right of the sculpted ball's centre | The bow makes the head heavier on its right; an off-axis COM is a gravity torque that slows the escapement one way |
| Mesh | Clean CAD | Sculpt welded (pinch vertices), every body float32-stable (STL / 3MF / cache) | The AI-generated mesh has defects |
| Colour | Multi-colour regions | One colour, as the owner's model | The owner's model is single-colour |
| Mass | ≤ 50 g | ≤ 55 g (owner's model at ×1.14 is 66 × 85 mm) | Frame mass does not enter the dynamics |

Accepted deviations (reported by the checkers, not hidden):

* Head inertia ~3.26e-6 kg·m² and COM ~6.9 mm above P (0.27 mm to the left) are below the classic band (4–8e-6, 8–14 mm). The sculpt head is
  what it is; V13 accepts it only because V4 passes with these values.
* V4 averages the T = 1 and 2 N·mm runs over 4 s / 1.8 s (was 1.2 / 0.9 s): at the gentlest push the motion is chaotic
  and a 1.2 s run measured the spin-up overshoot, not the steady giggle the SPEC 2.4 table describes.
* V10 wheel width: the classic 35.5 mm cannot be reached hidden inside the sculpted ball; the sculpt kitty's criterion
  is the small-parts test itself with a 0.5 mm margin (Ø 32.4 > 32.2).
* V12 pinch points at the cheeks and chin (the owner's head is not an arc about the pivot): finger-wide gaps that close
  from ~9 to ~2.5 mm as the head swings. The squeeze force is child-powered through the escapement (≈ 3 N for a normal
  push, ≈ 6 N for a hard one) and nothing stores energy. Making them constant would mean recutting the visible cheeks.
