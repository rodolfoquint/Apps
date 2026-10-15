import numpy as np, json, sys
from esc_opt import evaluate, star, sdf_grid
rng = np.random.default_rng(int(sys.argv[1])); n_iter = int(sys.argv[2])
found = []
for it in range(n_iter):
    p = dict(N=int(rng.choice([7, 8, 9])), Rt=float(rng.uniform(15, 19.5)), tooth_h=float(rng.uniform(4.0, 7.0)),
             tip_frac=float(rng.uniform(0.07, 0.16)), root_frac=float(rng.uniform(0.08, 0.28)), rp=float(rng.uniform(1.8, 2.8)),
             drho=float(rng.uniform(0.3, 2.0)), m=2, tilt=float(rng.uniform(0.85, 1.05)), psi_b=float(rng.uniform(10, 14)))
    args = (p['N'], p['Rt'], p['Rt'] - p['tooth_h'], p['tip_frac'], p['root_frac'], p['rp'], p['drho'], p['m'], p['tilt'], p['psi_b'])
    try:
        W = star(p['N'], p['Rt'], p['Rt'] - p['tooth_h'], p['tip_frac'], p['root_frac'])
        G = sdf_grid(W, p['Rt'])
        r, _ = evaluate(*args, G=G, W=W)
    except Exception as e:
        continue
    if not (r['ok'] and r['swing_pp'] >= 7 and r['D'] - p['Rt'] <= 14):
        continue
    worst = dict(swing=r['swing_pp'], pa=r['worst_pressure_angle'], ok=True)
    for dD, drp in [(-0.4, 0), (0.4, 0), (0, 0.2), (0, -0.2), (-0.4, 0.2), (0.4, -0.2)]:
        rr, _ = evaluate(*args, G=G, W=W, dD=dD, drp=drp)
        good = rr['jams'] == 0 and rr['worst_pressure_angle'] < 66 and rr['swing_pp'] >= 4
        worst['ok'] &= good
        worst['swing'] = min(worst['swing'], rr['swing_pp']); worst['pa'] = max(worst['pa'], rr['worst_pressure_angle'])
        if not good: break
    r.update(p); r['robust'] = worst
    print(('ROBUST ' if worst['ok'] else 'nominal ') + json.dumps(r), flush=True)
