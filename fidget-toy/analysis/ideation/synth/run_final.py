import sys, json, itertools, multiprocessing as mp
import os as _os; _HERE = _os.path.dirname(_os.path.abspath(__file__))  # repo-relative paths
sys.path.insert(0, _HERE)
from run_dyn3 import job
if __name__ == '__main__':
    jobs = []
    for T in [1, 2, 3, 5, 10, 20, 40]:
        for d in [1, -1]:
            jobs.append((1.5686, dict(T_Nmm=T, direction=d, I_h=5.2e-6, m_h=0.0158, r_com=11.3, c_r=0.35, mu=0.35, mu_b=0.35, t_end=0.6)))
    # infill variant (lighter head)
    for T in [2, 20]:
        for d in [1, -1]:
            jobs.append((1.5686, dict(T_Nmm=T, direction=d, I_h=2.9e-6, m_h=0.0087, r_com=11.3, c_r=0.35, t_end=0.5)))
    # gravity sideways / upside-down proxy: no gravity
    for T in [2, 20]:
        jobs.append((1.5686, dict(T_Nmm=T, direction=1, I_h=5.2e-6, m_h=0.0158, gravity=False, t_end=0.5)))
    with mp.Pool(4) as pool:
        for r in pool.imap(job, jobs):
            print(json.dumps(r), flush=True)
