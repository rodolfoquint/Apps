// Child-safety plugs for the padlock tabs on the gate.
//
// Four separate plugs, one per hole. Each fills the hole in one steel tab so
// a finger can't go into it.
//
//  - Cap sits on one face of the tab (the outer face, away from the other tab).
//  - Shank stops just short of the opposite face, so nothing sticks out on
//    that side and the gate still closes past the other tab.
//  - Crush ribs give a press fit; a little outdoor adhesive makes it permanent.
//  - Cap is wider than 31.7 mm, so even a loose plug is not a choking-size part.
//
// Print `part = "gauge"` first if you are not sure of the sizes, then set
// hole_d / tab_t below and print `part = "plate"`.

/* [Measured sizes, mm] */
hole_d = 17.5;   // hole diameter (largest gauge peg that slides in)
tab_t  = 5.0;    // tab thickness (narrowest gauge slot that slides on)

/* [Plug] */
cap_d     = 35;    // keep > 31.7 (small-parts / choke-test cylinder)
cap_h     = 3.5;   // cap thickness at the centre
cap_edge  = 0.8;   // straight rim before the 45-degree chamfer
recess    = 0.5;   // shank ends this far inside the hole (never protrudes)
glue_gap  = 0.4;   // shank core is this much smaller than hole_d
rib_n     = 8;     // number of crush ribs
rib_over  = 0.5;   // ribs are this much bigger than hole_d (press fit)
rib_d     = 1.6;   // crush rib size
lead_in   = 0.8;   // chamfer at the shank tip
groove_h  = 0.5;   // adhesive groove depth under the cap

/* [Output] */
part  = "plate";   // [plate, plug, gauge, demo]
count = 4;

$fn = 96;
eps = 0.01;

cap_r   = cap_d / 2;
core_r  = (hole_d - glue_gap) / 2;
rib_r   = (hole_d + rib_over) / 2;
shank_l = tab_t - recess;

// ---------------------------------------------------------------------------
// Plug, modelled the way it is installed: cap underside at z = 0, cap above,
// shank going down into the hole.

module cap() {
    difference() {
        rotate_extrude()
            polygon([[0, 0], [cap_r, 0], [cap_r, cap_edge],
                     [cap_r - (cap_h - cap_edge), cap_h], [0, cap_h]]);
        // shallow ring groove on the underside to hold adhesive
        translate([0, 0, -eps])
            difference() {
                cylinder(r = cap_r - 2.5, h = groove_h + eps);
                cylinder(r = hole_d / 2 + 1.5, h = groove_h + 2 * eps);
            }
    }
}

module shank() {
    intersection() {
        union() {
            translate([0, 0, -shank_l]) cylinder(r = core_r, h = shank_l + eps);
            for (i = [0 : rib_n - 1])
                rotate([0, 0, i * 360 / rib_n])
                    translate([rib_r - rib_d / 2, 0, -shank_l])
                        cylinder(d = rib_d, h = shank_l + eps, $fn = 24);
        }
        // envelope with a lead-in chamfer at the tip
        rotate_extrude()
            polygon([[0, -shank_l], [core_r - lead_in, -shank_l],
                     [rib_r + eps, -shank_l + lead_in + (rib_r - core_r)],
                     [rib_r + eps, eps], [0, eps]]);
    }
}

module plug() {
    cap();
    shank();
}

// Print orientation: flat top of the cap on the bed, shank pointing up.
module plug_print() {
    translate([0, 0, cap_h]) rotate([180, 0, 0]) plug();
}

module plate() {
    cols  = ceil(sqrt(count));
    pitch = cap_d + 5;
    for (i = [0 : count - 1])
        translate([(i % cols) * pitch, floor(i / cols) * pitch, 0])
            plug_print();
}

// ---------------------------------------------------------------------------
// Sizing gauge.
//  - Pegs: push into the hole; the largest one that goes in is hole_d.
//  - Slots along the top edge: slide onto the tab's edge; the narrowest one
//    that fits is tab_t.
// Printed on the same printer as the plugs, so it also absorbs printer error.

gauge_pegs  = [15.5, 16, 16.5, 17, 17.5, 18, 18.5, 19, 19.5, 20];
gauge_slots = [3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 8];
cell_w = 24;
base_t = 3;
peg_h  = 6;
slot_depth = 8;

module label(s, size = 3.6) {
    linear_extrude(0.6)
        text(s, size = size, font = "Liberation Sans:style=Bold",
             halign = "center", valign = "center");
}

module gauge() {
    n    = len(gauge_pegs);
    cols = 5;
    rows = ceil(n / cols);
    row_h = 30;
    slot_band = slot_depth + 7;
    W = cols * cell_w;
    H = rows * row_h + slot_band;

    difference() {
        cube([W, H, base_t]);
        // thickness slots cut into the top edge
        for (i = [0 : len(gauge_slots) - 1])
            translate([(i + 0.5) * W / len(gauge_slots) - gauge_slots[i] / 2,
                       H - slot_depth, -eps])
                cube([gauge_slots[i], slot_depth + eps, base_t + 2 * eps]);
    }
    // slot labels
    for (i = [0 : len(gauge_slots) - 1])
        translate([(i + 0.5) * W / len(gauge_slots), H - slot_depth - 3.5, base_t])
            label(str(gauge_slots[i]), 2.8);

    // hole pegs with labels
    for (i = [0 : n - 1]) {
        x = (i % cols + 0.5) * cell_w;
        y = (rows - 1 - floor(i / cols)) * row_h;
        translate([x, y + 4, base_t]) label(str(gauge_pegs[i]));
        translate([x, y + 18, base_t])
            cylinder(h = peg_h, d1 = gauge_pegs[i], d2 = gauge_pegs[i]);
        translate([x, y + 18, base_t + peg_h])
            cylinder(h = 0.6, d1 = gauge_pegs[i], d2 = gauge_pegs[i] - 1.2);
    }
}

// ---------------------------------------------------------------------------
// Preview only: one plug sitting in one steel tab.

module steel_tab() {
    difference() {
        hull() {
            cylinder(d = 32, h = tab_t);
            translate([-30, -16, 0]) cube([1, 32, tab_t]);
        }
        translate([0, 0, -eps]) cylinder(d = hole_d, h = tab_t + 2 * eps);
    }
}

module demo() {
    color("lightgrey") steel_tab();
    color("orange") translate([0, 0, tab_t]) plug();
}

// ---------------------------------------------------------------------------

if (part == "plug")       plug_print();
else if (part == "gauge") gauge();
else if (part == "demo")  demo();
else                      plate();
