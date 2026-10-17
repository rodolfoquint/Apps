import sys, json, itertools, multiprocessing as mp
import os as _os; _HERE = _os.path.dirname(_os.path.abspath(__file__))  # repo-relative paths
sys.path.insert(0, _HERE)
from run_dyn3 import job
HB = dict(I_h=5.2e-6, m_h=0.0158, r_com=11.3, k_bank=100.0)
if __name__ == '__main__':
    jobs = []
    for T in [1, 2, 3, 5, 10, 20, 40]:
        for d in [1, -1]:
            jobs.append((1.8686, dict(T_Nmm=T, direction=d, c_r=0.35, mu=0.35, mu_b=0.35, t_end=0.6, **HB)))
    for (mu, mub), (dD, drp), T, d in itertools.product([(0.5, 0.5), (0.6, 0.35), (0.6, 0.5), (0.2, 0.2)], [(-0.4, 0.2), (0.4, -0.2), (-0.4, -0.2), (0.4, 0.2)], [1, 20], [1, -1]):
        jobs.append((1.8686, dict(T_Nmm=T, direction=d, dD=dD, drp=drp, c_r=0.35, mu=mu, mu_b=mub, t_end=0.45, **HB)))
    for I, m in [(2.9e-6, 0.0087), (1.0e-5, 0.025)]:
        for T in [1, 20]:
            for d in [1, -1]:
                jobs.append((1.8686, dict(T_Nmm=T, direction=d, c_r=0.35, I_h=I, m_h=m, r_com=11.3, k_bank=100.0, t_end=0.45)))
    with mp.Pool(4) as pool:
        for r in pool.imap(job, jobs):
            print(json.dumps(r), flush=True)
