import sys, json, itertools, multiprocessing as mp
import os as _os; _HERE = _os.path.dirname(_os.path.abspath(__file__))  # repo-relative paths
sys.path.insert(0, _HERE)
from run_dyn3 import job
if __name__ == '__main__':
    jobs = []
    for drho in [1.5686, 1.7186, 1.8686]:
        for mu, mub in [(0.35, 0.35), (0.45, 0.45), (0.5, 0.5), (0.6, 0.35)]:
            for dD, drp in itertools.product([-0.4, 0.4], [-0.2, 0.2]):
                for T in [2, 20]:
                    for d in [1, -1]:
                        jobs.append((drho, dict(T_Nmm=T, direction=d, dD=dD, drp=drp, c_r=0.35, mu=mu, mu_b=mub, I_h=6e-6, t_end=0.45)))
    with mp.Pool(4) as pool:
        for r in pool.imap(job, jobs):
            print(json.dumps(r), flush=True)
