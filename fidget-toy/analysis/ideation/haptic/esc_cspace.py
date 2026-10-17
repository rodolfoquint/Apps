"""Quick C-space exploration of a symmetric pin-pallet runaway (foliot) escapement.
Wheel: symmetric star with N teeth. Anchor: two cylindrical pins on a rocker pivoted at A=(0,D).
For each wheel angle phi and anchor angle psi compute clearance of each pin to the wheel.
Then push a 'lazy' anchor quasi-statically and report the forced swing, jams, pressure angles.
"""
import numpy as np
from shapely.geometry import Polygon, Point
from shapely import affinity
import sys, json

def star(N, Rt, Rr, tip_frac=0.18, root_frac=0.30, fil=0.8):
    # symmetric trapezoid-ish teeth: flat-ish tip occupying tip_frac of pitch, root land root_frac
    pts = []
    p = 2*np.pi/N
    for i in range(N):
        a0 = i*p
        # root land centre at a0, tip centre at a0+p/2
        for (a, r) in [(a0 - root_frac*p/2, Rr), (a0 + root_frac*p/2, Rr),
                       (a0 + p/2 - tip_frac*p/2, Rt), (a0 + p/2 + tip_frac*p/2, Rt)]:
            pts.append((r*np.cos(a), r*np.sin(a)))
    poly = Polygon(pts)
    # round convex and concave corners
    poly = poly.buffer(-fil, join_style=1).buffer(fil, join_style=1)
    poly = poly.buffer(fil, join_style=1).buffer(-fil, join_style=1)
    return poly

def run(N=10, Rt=15.0, Rr=10.5, D=24.0, ra=12.0, beta_deg=40.0, rp=2.0, tip_frac=0.18, root_frac=0.30,
        mu=0.35, verbose=True):
    W = star(N, Rt, Rr, tip_frac, root_frac)
    Wb = W.boundary
    A = np.array([0.0, D])
    b = np.radians(beta_deg)
    pins0 = [A + ra*np.array([-np.sin(b), -np.cos(b)]), A + ra*np.array([np.sin(b), -np.cos(b)])]
    pitch = 360.0/N
    phis = np.linspace(0, 2*pitch, 241)
    psis = np.linspace(-35, 35, 701)
    def pin_pos(psi):
        c, s = np.cos(np.radians(psi)), np.sin(np.radians(psi))
        R = np.array([[c, -s], [s, c]])
        return [A + R @ (p - A) for p in pins0]
    def clear(phi, psi):
        # clearance (distance pin edge to wheel) for both pins, wheel rotated by phi
        c, s = np.cos(np.radians(-phi)), np.sin(np.radians(-phi))
        Rm = np.array([[c, -s], [s, c]])
        out = []
        for p in pin_pos(psi):
            q = Rm @ p
            pt = Point(q)
            d = Wb.distance(pt)
            if W.contains(pt):
                d = -d
            out.append(d - rp)
        return out
    # free-space map (vectorized)
    import shapely
    PH, PS = np.meshgrid(np.radians(phis), np.radians(psis), indexing='ij')
    cl = np.full(PH.shape, np.inf)
    for p in pins0:
        v = p - A
        # pin position in world after anchor rotation psi
        x = A[0] + np.cos(PS)*v[0] - np.sin(PS)*v[1]
        y = A[1] + np.sin(PS)*v[0] + np.cos(PS)*v[1]
        # into wheel frame (rotate by -phi)
        xw = np.cos(-PH)*x - np.sin(-PH)*y
        yw = np.sin(-PH)*x + np.cos(-PH)*y
        pts = shapely.points(xw.ravel(), yw.ravel())
        d = shapely.distance(Wb, pts).reshape(PH.shape)
        inside = shapely.contains_xy(W, xw.ravel(), yw.ravel()).reshape(PH.shape)
        d = np.where(inside, -d, d) - rp
        cl = np.minimum(cl, d)
    free = cl >= 0.0
    # lazy-anchor push sweep (forward), starting from a free psi near 0
    j0 = np.argmax(np.where(free[0], -np.abs(psis), -1e9))
    traj = [psis[j0]]; jams = 0
    j = j0
    for i in range(1, len(phis)):
        row = free[i]
        if row[j]:
            traj.append(psis[j]); continue
        # find nearest free psi connected (anchor gets pushed)
        cand = np.where(row)[0]
        if len(cand) == 0:
            jams += 1; traj.append(np.nan); continue
        j = cand[np.argmin(np.abs(cand - j))]
        traj.append(psis[j])
    traj = np.array(traj)
    # max clearance pose for printing: find (phi,psi) maximizing min clearance
    k = np.unravel_index(np.argmax(cl), cl.shape)
    res = dict(N=N, Rt=Rt, Rr=Rr, D=D, ra=ra, beta=beta_deg, rp=rp,
               swing_pp_deg=float(np.nanmax(traj) - np.nanmin(traj)),
               jams=int(jams), best_print_clear=float(cl[k]), print_pose=(float(phis[k[0]]), float(psis[k[1]])),
               free_frac=float(free.mean()))
    # channel width per phi (span of free component containing traj)
    widths = []
    for i in range(len(phis)):
        if np.isnan(traj[i]): widths.append(0); continue
        jj = np.argmin(np.abs(psis - traj[i]))
        lo = jj
        while lo > 0 and free[i, lo-1]: lo -= 1
        hi = jj
        while hi < len(psis)-1 and free[i, hi+1]: hi += 1
        widths.append(psis[hi] - psis[lo])
    res['min_channel_width_deg'] = float(np.min(widths))
    if verbose:
        print(json.dumps(res, indent=1))
    return res, phis, psis, cl, traj, W, pins0

if __name__ == '__main__':
    import matplotlib; matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    best = None
    for N in [8, 9, 10]:
        for D in [22, 24, 26]:
            for ra in [10, 12, 14]:
                for beta in [30, 38, 46, 54]:
                    r, *_ = run(N=N, D=D, ra=ra, beta_deg=beta, verbose=False)
                    ok = r['jams'] == 0 and r['min_channel_width_deg'] > 0
                    if ok and (best is None or r['swing_pp_deg'] > best['swing_pp_deg']):
                        best = r
                    print(N, D, ra, beta, 'swing %.1f jams %d chan %.1f printclr %.2f' % (r['swing_pp_deg'], r['jams'], r['min_channel_width_deg'], r['best_print_clear']))
    print('BEST', best)
