"""Synthesis check 1: escapement band layout with REAL pallet fingers + legs + hub (not just pin circles).
Checks that only the round pallet tips can ever touch the wheel teeth (fingers/legs/hub stay clear),
over the whole reachable C-space, for both rotation directions.
World frame: wheel axis O=(0,0), head axis P=(0,D), y up.  psi>0 = CCW head rotation.
"""
import sys, json, numpy as np, shapely
from shapely.geometry import Point, Polygon, LineString
from shapely import affinity
sys.path.insert(0, '/tmp/claude-0/-home-user-Apps/023789a6-f9f1-563f-a565-9790ebbd0388/scratchpad/ideation/haptic')
from esc_opt import star

P_ESC = {"N": 8, "Rt": 14.2992, "tooth_h": 5.3968, "tip_frac": 0.0765, "root_frac": 0.1333,
         "rp": 2.1448, "drho": 1.8686, "m": 2, "tilt": 0.8792, "psi_b": 12.42}

def esc_geometry(p=P_ESC, drho=None):
    N, Rt = p['N'], p['Rt']; Rr = Rt - p['tooth_h']
    pitch = 2*np.pi/N; gam = (p['m'] + 0.5)*pitch/2
    dr = p['drho'] if drho is None else drho
    rho = (Rt + Rr)/2 + p['rp'] + dr
    D = rho/np.cos(gam)*p['tilt']
    pins = [np.array([-rho*np.sin(gam), rho*np.cos(gam)]), np.array([rho*np.sin(gam), rho*np.cos(gam)])]
    W = star(N, Rt, Rr, p['tip_frac'], p['root_frac'])
    return dict(W=W, D=D, pins=pins, rp=p['rp'], Rt=Rt, Rr=Rr, rho=rho, gam=gam)

def head_band(g, finger_w=None, r_root=19.0, leg_w=4.6, hub_r=7.0, finger_len_extra=0.0):
    """Head escapement-band outline at psi=0: round pallet tips on radial fingers, fingers to r_root (from O),
    then straight legs to the hub disc around P."""
    rp = g['rp']; P = np.array([0.0, g['D']])
    fw = 2*rp if finger_w is None else finger_w
    parts = [Point(P).buffer(hub_r, 128)]
    tips = []
    for c in g['pins']:
        u = c/np.linalg.norm(c)
        root = u*r_root
        tip = Point(c).buffer(rp, 128)
        finger = LineString([c, root]).buffer(fw/2, cap_style=2)
        leg = LineString([root, P]).buffer(leg_w/2, cap_style=1, resolution=64)
        parts += [tip, finger, leg]
        tips.append(tip)
    H = shapely.union_all(parts)
    return H, tips

def cspace_check(g, H, tips, psi_b, n_phi=181, n_psi=101, verbose=True):
    W = g['W']; shapely.prepare(W)
    P = (0.0, g['D'])
    pitch = 360.0/8
    phis = np.linspace(0, 2*pitch, n_phi); psis = np.linspace(-psi_b, psi_b, n_psi)
    cl_pin = np.zeros((n_phi, n_psi)); cl_full = np.zeros((n_phi, n_psi))
    tipU = shapely.union_all(tips)
    for j, ps in enumerate(psis):
        Hr = affinity.rotate(H, ps, origin=P); Tr = affinity.rotate(tipU, ps, origin=P)
        for i, ph in enumerate(phis):
            # wheel rotated by +ph == head rotated by -ph about O
            Hw = affinity.rotate(Hr, -ph, origin=(0, 0)); Tw = affinity.rotate(Tr, -ph, origin=(0, 0))
            dp = W.distance(Tw)
            if dp == 0: dp = -np.sqrt(W.intersection(Tw).area)
            df = W.distance(Hw)
            if df == 0: df = -np.sqrt(W.intersection(Hw).area)
            cl_pin[i, j] = dp; cl_full[i, j] = df
    reach = cl_pin >= 0
    bad = reach & (cl_full < np.minimum(cl_pin, 0.6) - 0.02)
    out = dict(reachable_frac=float(reach.mean()), n_bad=int(bad.sum()),
               min_full_clear_where_pins_free=float(cl_full[reach].min()),
               worst_deficit=float((np.minimum(cl_pin, 0.6) - cl_full)[reach].max()),
               print_pose_clear=float(cl_full.max()),
               print_pose=(float(phis[np.unravel_index(cl_full.argmax(), cl_full.shape)[0]]),
                           float(psis[np.unravel_index(cl_full.argmax(), cl_full.shape)[1]])))
    if verbose: print(json.dumps(out, indent=1))
    return out, phis, psis, cl_pin, cl_full

if __name__ == '__main__':
    g = esc_geometry()
    print('D=%.3f rho=%.3f pins=%s rp=%.3f Rt=%.3f Rr=%.3f' % (g['D'], g['rho'], [list(np.round(c, 3)) for c in g['pins']], g['rp'], g['Rt'], g['Rr']))
    P = np.array([0, g['D']])
    print('pin-to-pivot arm %.3f mm' % np.linalg.norm(g['pins'][1] - P))
    for r_root in [18.0, 19.0, 20.0]:
        for fw in [2*g['rp'], 2*g['rp'] - 0.4]:
            H, tips = head_band(g, finger_w=fw, r_root=r_root)
            print('--- r_root', r_root, 'finger_w %.2f' % fw)
            cspace_check(g, H, tips, P_ESC['psi_b'], n_phi=91, n_psi=51)
