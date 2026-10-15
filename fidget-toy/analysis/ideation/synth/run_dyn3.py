import sys, json, itertools, multiprocessing as mp, numpy as np
sys.path.insert(0, '.')
from esc_dyn3 import make, simulate, P_ESC
_cache = {}
def job(args):
    drho, kw = args
    key = drho
    if key not in _cache: _cache[key] = make(drho)
    g, S = _cache[key]
    r = simulate(S, g['D'], g['pins'], g['rp'], psi_b=P_ESC['psi_b'], **kw)
    r.update({k: v for k, v in kw.items() if k not in ('T_Nmm', 'direction')}); r['drho'] = drho
    return r
if __name__ == '__main__':
    mode = sys.argv[1]
    d0 = P_ESC['drho']
    jobs = []
    if mode == 'nominal':
        for T in [1, 2, 3, 5, 10, 20, 40]:
            for d in [1, -1]:
                jobs.append((d0, dict(T_Nmm=T, direction=d)))
    elif mode == 'window':
        for dd in np.arange(-1.6, 1.21, 0.2):
            for T in [2, 20]:
                for d in [1, -1]:
                    for cr in [0.35, 0.5]:
                        jobs.append((round(d0 + dd, 4), dict(T_Nmm=T, direction=d, c_r=cr, t_end=0.45)))
    elif mode == 'corners':
        drho = float(sys.argv[2])
        for dD, drp, cr, mu, mub, I in itertools.product([-0.4, 0.4], [-0.2, 0.2], [0.25, 0.5], [0.2, 0.6], [0.2, 0.5], [3e-6, 1.2e-5]):
            for T in [2, 20]:
                jobs.append((drho, dict(T_Nmm=T, direction=1 if (len(jobs) % 2 == 0) else -1, dD=dD, drp=drp, c_r=cr, mu=mu, mu_b=mub, I_h=I, t_end=0.45)))
    elif mode == 'torque':
        drho = float(sys.argv[2])
        for I in [4e-6, 6e-6, 9e-6]:
            for T in [1, 2, 3, 5, 10, 20, 40]:
                for d in [1, -1]:
                    jobs.append((drho, dict(T_Nmm=T, direction=d, I_h=I)))
    with mp.Pool(4) as pool:
        for r in pool.imap(job, jobs):
            print(json.dumps(r), flush=True)
