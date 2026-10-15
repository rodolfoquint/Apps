"""Fast geometric screening + random search for a jam-free symmetric pin-pallet (foliot) escapement.
Uses a wheel SDF grid: C-space clearance, lazy-anchor quasi-static sweep in both directions, pressure angles
at contacts (pin side and wheel side, must stay below 90deg - friction angle - margin), banking stops.
"""
import numpy as np, json, sys
DEBUG = False
from scipy.ndimage import map_coordinates
from shapely.geometry import Polygon
import shapely

def star(N, Rt, Rr, tip_frac, root_frac, fil=0.7):
    pts = []; p = 2*np.pi/N
    for i in range(N):
        a0 = i*p
        for (a, r) in [(a0 - root_frac*p/2, Rr), (a0 + root_frac*p/2, Rr),
                       (a0 + p/2 - tip_frac*p/2, Rt), (a0 + p/2 + tip_frac*p/2, Rt)]:
            pts.append((r*np.cos(a), r*np.sin(a)))
    W = Polygon(pts)
    W = W.buffer(-fil, join_style=1).buffer(fil, join_style=1)
    W = W.buffer(fil, join_style=1).buffer(-fil, join_style=1)
    return W

def sdf_grid(W, Rt, h=0.08):
    L = Rt + 5
    xs = np.arange(-L, L + h, h)
    X, Y = np.meshgrid(xs, xs, indexing='ij')
    d = shapely.distance(W.boundary, shapely.points(X.ravel(), Y.ravel())).reshape(X.shape)
    ins = shapely.contains_xy(W, X.ravel(), Y.ravel()).reshape(X.shape)
    s = np.where(ins, -d, d)
    gx, gy = np.gradient(s, h)
    return dict(s=s, gx=gx, gy=gy, x0=-L, h=h)

def samp(G, x, y, key='s'):
    c = np.vstack([(x.ravel() - G['x0'])/G['h'], (y.ravel() - G['x0'])/G['h']])
    return map_coordinates(G[key], c, order=1, mode='nearest').reshape(x.shape)

def evaluate(N, Rt, Rr, tip_frac, root_frac, rp, drho, m, tilt, psi_b, mu=0.35, margin=8.0, G=None, W=None, dD=0.0, drp=0.0):
    pitch = 2*np.pi/N
    gam = (m + 0.5)*pitch/2
    rho = (Rt + Rr)/2 + rp + drho
    D = rho/np.cos(gam)*tilt
    A0 = np.array([0.0, D])
    pins = [np.array([-rho*np.sin(gam), rho*np.cos(gam)]) - A0, np.array([rho*np.sin(gam), rho*np.cos(gam)]) - A0]
    D = D + dD; A = np.array([0.0, D]); rp = rp + drp
    if W is None:
        W = star(N, Rt, Rr, tip_frac, root_frac)
    if G is None:
        G = sdf_grid(W, Rt)
    phis = np.radians(np.linspace(0, 2*360/N, 361))
    psis = np.radians(np.linspace(-psi_b, psi_b, 2*int(psi_b*10) + 1))
    PH, PS = np.meshgrid(phis, psis, indexing='ij')
    cl = np.full(PH.shape, np.inf); which = np.zeros(PH.shape, int)
    geo = []
    for k, pl in enumerate(pins):
        x = A[0] + np.cos(PS)*pl[0] - np.sin(PS)*pl[1]
        y = A[1] + np.sin(PS)*pl[0] + np.cos(PS)*pl[1]
        xw = np.cos(PH)*x + np.sin(PH)*y; yw = -np.sin(PH)*x + np.cos(PH)*y
        d = samp(G, xw, yw) - rp
        which = np.where(d < cl, k, which); cl = np.minimum(cl, d)
        geo.append((x, y, xw, yw))
    free = cl >= 0
    out = dict(D=round(D, 2), ra=round(float(np.linalg.norm(pins[0])), 2), hub_gap=round(D - Rt, 2))
    # print pose: max of min clearance
    k = np.unravel_index(np.argmax(cl), cl.shape)
    out['print_clear'] = round(float(cl[k]), 2)
    worst_pa = 0.0; jams = 0; swing = []
    for direction in [1, -1]:
        order = range(len(phis)) if direction == 1 else range(len(phis) - 1, -1, -1)
        j = int(np.argmax(np.where(free[list(order)[0]], -np.abs(psis), -1e9)))
        traj = []
        for i in order:
            row = free[i]
            if not row[j]:
                cand = np.where(row)[0]
                if len(cand) == 0:
                    jams += 1; continue
                jn = cand[np.argmin(np.abs(cand - j))]
                # contact: anchor pushed from j to jn; evaluate pressure angles at the blocking contact (row i, index j)
                kk = which[i, j]
                x, y, xw, yw = [g[i, j] for g in geo[kk]]
                gx = samp(G, np.array([xw]), np.array([yw]), 'gx')[0]; gy = samp(G, np.array([xw]), np.array([yw]), 'gy')[0]
                nw = np.array([gx, gy]); nw /= np.linalg.norm(nw) + 1e-12
                ph = phis[i]
                n = np.array([np.cos(ph)*nw[0] - np.sin(ph)*nw[1], np.sin(ph)*nw[0] + np.cos(ph)*nw[1]])
                C = np.array([x, y]) - rp*n
                v_pin = np.array([-(C - A)[1], (C - A)[0]]); v_pin /= np.linalg.norm(v_pin)
                v_wh = direction*np.array([-C[1], C[0]]); v_wh /= np.linalg.norm(v_wh)
                # wheel pushes pin along +n: pin must be able to move: angle(n, +-v_pin) and wheel angle(n, v_wh)
                pa_pin = np.degrees(np.arccos(min(1, abs(n @ v_pin))))
                pa_wh = np.degrees(np.arccos(np.clip(n @ v_wh, -1, 1)))
                dpsi_dphi = abs(psis[jn] - psis[j])/abs(phis[1] - phis[0])
                tip_zone = np.linalg.norm(C) > Rt - 0.35
                cand_pa = 0.0 if tip_zone else max(pa_pin, pa_wh if dpsi_dphi > 0.25 else 0.0)
                if DEBUG and cand_pa > 60: print('dbg dir',direction,'phi %.1f psi %.1f->%.1f pin %d pa_pin %.1f pa_wh %.1f dpsi/dphi %.2f r_contact %.2f' % (np.degrees(ph), np.degrees(psis[j]), np.degrees(psis[jn]), kk, pa_pin, pa_wh, dpsi_dphi, np.linalg.norm(C)))
                worst_pa = max(worst_pa, cand_pa)
                j = jn
            traj.append(psis[j])
        swing.append(np.degrees(max(traj) - min(traj)) if traj else 0)
    out['jams'] = jams
    out['swing_pp'] = round(float(min(swing)), 1)
    out['worst_pressure_angle'] = round(worst_pa, 1)
    lock_limit = 90 - np.degrees(np.arctan(mu)) - margin
    out['ok'] = bool(jams == 0 and worst_pa < lock_limit and out['print_clear'] >= 0.5 and D - Rt >= 6.0)
    return out, dict(A=A, pins=pins, W=W, G=G, D=D)

if __name__ == '__main__':
    rng = np.random.default_rng(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    n_iter = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    best = []
    for it in range(n_iter):
        p = dict(N=int(rng.choice([7, 8, 9, 10])), Rt=float(rng.uniform(14, 17)), tooth_h=float(rng.uniform(3.0, 5.5)),
                 tip_frac=float(rng.uniform(0.08, 0.2)), root_frac=float(rng.uniform(0.05, 0.3)), rp=float(rng.uniform(1.5, 2.5)),
                 drho=float(rng.uniform(-1.0, 2.5)), m=int(rng.choice([1, 2])), tilt=float(rng.uniform(0.85, 1.3)),
                 psi_b=float(rng.uniform(8, 16)))
        try:
            r, _ = evaluate(p['N'], p['Rt'], p['Rt'] - p['tooth_h'], p['tip_frac'], p['root_frac'], p['rp'], p['drho'], p['m'], p['tilt'], p['psi_b'])
        except Exception as e:
            continue
        r.update(p)
        if r['ok']:
            best.append(r)
            print('OK', json.dumps(r), flush=True)
    best.sort(key=lambda r: -r['swing_pp'])
    json.dump(best, open(f'opt_{sys.argv[1] if len(sys.argv)>1 else 0}.json', 'w'), indent=1)
    print('n ok', len(best))
