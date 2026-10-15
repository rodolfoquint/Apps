"""Static (quasi-static, hard-banking) jam map: for each nominal pin depth drho, find the centre-distance error dD range
for which the lazy-head C-space channel stays open in both directions (no hard lock), at pin size error drp."""
import sys, json, numpy as np, multiprocessing as mp
sys.path.insert(0, '/tmp/claude-0/-home-user-Apps/023789a6-f9f1-563f-a565-9790ebbd0388/scratchpad/ideation/haptic')
from esc_opt import evaluate, star, sdf_grid
p = dict(N=8, Rt=14.2992, tooth_h=5.3968, tip_frac=0.0765, root_frac=0.1333, rp=2.1448, m=2, tilt=0.8792, psi_b=12.42)
W = star(p['N'], p['Rt'], p['Rt'] - p['tooth_h'], p['tip_frac'], p['root_frac']); G = sdf_grid(W, p['Rt'], h=0.05)
def one(args):
    drho, dD, drp, psib = args
    r, _ = evaluate(p['N'], p['Rt'], p['Rt'] - p['tooth_h'], p['tip_frac'], p['root_frac'], p['rp'], drho, p['m'], p['tilt'], psib, G=G, W=W, dD=dD, drp=drp)
    return dict(drho=drho, dD=dD, drp=drp, psib=psib, jams=r['jams'], pa=r['worst_pressure_angle'], swing=r['swing_pp'])
if __name__ == '__main__':
    jobs = [(d, dD, drp, 12.42) for d in [1.5686, 1.7186, 1.8686, 2.0186, 2.1686] for dD in np.round(np.arange(-1.0, 1.01, 0.2), 2) for drp in (-0.2, 0.0, 0.2)]
    with mp.Pool(4) as pool:
        res = pool.map(one, jobs)
    import collections
    tab = collections.defaultdict(dict)
    for r in res: tab[(r['drho'], r['drp'])][r['dD']] = r
    for k in sorted(tab):
        row = tab[k]
        print('drho %.4f drp %+.1f |' % k, ' '.join('%+.1f:%s%.0f' % (dD, 'J' if row[dD]['jams'] else '.', row[dD]['pa']) for dD in sorted(row)))
