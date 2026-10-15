"""Find the working window of pin depth (drho) for a candidate, then centre it and re-check tolerance cases."""
import numpy as np, json, sys
from esc_dyn2 import simulate, geometry
from esc_opt import sdf_grid
p0 = json.loads(sys.argv[1]); tag = sys.argv[2]
W, _, _ = geometry(p0)
G = sdf_grid(W, p0['Rt'], h=0.05)
def runs(p, dD=0.0, drp=0.0, Ts=(3, 20)):
    _, A, pins = geometry(p)
    res = []
    for T in Ts:
        for d in (1, -1):
            r = simulate(G, A + np.array([0, dD]), pins, p['rp'] + drp, T, p['psi_b'], direction=d, t_end=0.5)
            res.append(r)
    return all(abs(r['wheel_rps']) > 0.3 for r in res), res
win = []
for dd in np.arange(-0.4, 1.81, 0.2):
    p = dict(p0); p['drho'] = p0['drho'] + dd
    ok, res = runs(p)
    print(tag, 'drho %+.1f' % dd, 'RUN' if ok else 'jam', [(r['T'], r['freq_Hz'], r['swing_pp'], r['wheel_rps']) for r in res], flush=True)
    if ok: win.append(dd)
if win:
    c = 0.5*(min(win) + max(win))
    p = dict(p0); p['drho'] = p0['drho'] + c
    print(tag, 'window', min(win), max(win), 'centre', c, json.dumps(p))
    allok = True
    for dD, drp in [(-0.4, 0), (0.4, 0), (0, 0.2), (0, -0.2), (-0.4, 0.2), (0.4, -0.2), (0.4, 0.2), (-0.4, -0.2)]:
        ok, res = runs(p, dD, drp)
        allok &= ok
        print(tag, 'centred tol dD %+.1f drp %+.1f' % (dD, drp), 'RUN' if ok else 'JAM', [(r['T'], r['dir'], r['freq_Hz'], r['swing_pp'], r['wheel_rps']) for r in res], flush=True)
    print(tag, 'CENTRED_ALL_OK' if allok else 'CENTRED_SOME_JAM')
