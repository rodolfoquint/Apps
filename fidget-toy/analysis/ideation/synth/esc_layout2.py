"""Head escapement-band outline v2: a 'bib' plate (sector around P) with the swept wheel-tip exclusion cut out,
plus tapered radial pallet fingers. Full C-space check (fingers+bib vs real star wheel)."""
import sys, json, numpy as np, shapely
from shapely.geometry import Point, Polygon, LineString
from shapely import affinity
from esc_layout import esc_geometry, cspace_check, P_ESC

def swept_exclusion(g, r_ex, psi_b, n=50):
    """Union over psi of disc(O, r_ex) expressed in the HEAD frame (i.e. disc rotated by -psi about P)."""
    P = (0.0, g['D'])
    discs = [affinity.rotate(Point(0, 0).buffer(r_ex, 128), -ps, origin=P) for ps in np.linspace(-psi_b, psi_b, n)]
    return shapely.union_all(discs)

def finger(c, rp, L, taper_deg):
    """Round tip of radius rp at c, straight-tapered radial finger running outward length L (half-angle taper)."""
    u = c/np.linalg.norm(c); n = np.array([-u[1], u[0]])
    w0 = rp; w1 = rp + L*np.tan(np.radians(taper_deg))
    poly = Polygon([c + n*w0, c + u*L + n*w1, c + u*L - n*w1, c - n*w0])
    return shapely.union_all([poly, Point(c).buffer(rp, 128)])

def head_band2(g, R_bib=22.0, bib_half_angle=75.0, r_ex_margin=0.6, L_f=7.0, taper=8.0, psi_b=12.42, hub_r=7.0):
    P = np.array([0.0, g['D']])
    # sector around P pointing down
    angs = np.radians(np.linspace(-bib_half_angle, bib_half_angle, 121))
    pts = [tuple(P)] + [tuple(P + R_bib*np.array([np.sin(a), -np.cos(a)])) for a in angs]
    bib = Polygon(pts).union(Point(P).buffer(hub_r, 64))
    ex = swept_exclusion(g, g['Rt'] + r_ex_margin, psi_b)
    bib = bib.difference(ex)
    tips = []
    parts = [bib]
    for c in g['pins']:
        f = finger(c, g['rp'], L_f, taper)
        parts.append(f); tips.append(Point(c).buffer(g['rp'], 128))
    H = shapely.union_all(parts)
    if H.geom_type != 'Polygon':
        H = max(H.geoms, key=lambda q: q.area)
    return H, tips, bib

if __name__ == '__main__':
    g = esc_geometry()
    for L_f, taper, marg in [(7.0, 0.0, 0.6), (7.0, 6.0, 0.6), (8.0, 6.0, 0.8), (8.0, 10.0, 0.8)]:
        H, tips, bib = head_band2(g, L_f=L_f, taper=taper, r_ex_margin=marg)
        print('=== L_f', L_f, 'taper', taper, 'ex margin', marg, 'H area %.0f mm2' % H.area, 'type', H.geom_type)
        cspace_check(g, H, tips, P_ESC['psi_b'], n_phi=91, n_psi=51)
