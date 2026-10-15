import numpy as np, json
import os as _os; _HERE = _os.path.dirname(_os.path.abspath(__file__))  # repo-relative paths
from esc_cspace import run
# tangent-geometry parameterisation: pins at polar radius rho, angles +-gamma about O, 2*gamma=(m+0.5)*pitch
rows = []
for N in [8, 9, 10]:
    pitch = 360/N
    for m in [1, 2]:
        gam = np.radians((m+0.5)*pitch/2)
        for Rt, Rr in [(15, 10.5), (16, 10.0)]:
            for drho in [-0.5, 0.5, 1.5]:
                rp = 2.0
                rho = (Rt+Rr)/2 + rp + drho
                for tilt in [0.9, 1.0, 1.1]:   # move pivot off the tangent point (adds recoil component)
                    D = rho/np.cos(gam)*tilt
                    P = np.array([rho*np.sin(gam), rho*np.cos(gam)])
                    v = P - np.array([0, D]); ra = np.linalg.norm(v); beta = np.degrees(np.arctan2(v[0], -v[1]))
                    if D - Rt < 5.5:
                        continue   # need room for the anchor hub (r~4.5 + gap)
                    r, *_ = run(N=N, Rt=Rt, Rr=Rr, D=D, ra=ra, beta_deg=beta, rp=rp, verbose=False)
                    r.update(m=m, drho=drho, tilt=tilt)
                    rows.append(r)
                    print(N, m, Rt, Rr, drho, tilt, 'D %.1f ra %.1f beta %.1f | swing %.1f jams %d chan %.1f printclr %.2f' % (D, ra, beta, r['swing_pp_deg'], r['jams'], r['min_channel_width_deg'], r['best_print_clear']), flush=True)
json.dump(rows, open(_os.path.join(_HERE, 'scan2.json'), 'w'))
