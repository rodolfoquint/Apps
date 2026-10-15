import sys, json, itertools, multiprocessing as mp
sys.path.insert(0, '.')
from run_dyn3 import job
if __name__ == '__main__':
    jobs = []
    for Jw, T, d, (dD, drp) in itertools.product([8e-7, 1.5e-5], [1, 3, 20], [1, -1], [(0, 0), (0.4, -0.2), (-0.4, 0.2)]):
        jobs.append((1.8686, dict(T_Nmm=T, direction=d, J_w=Jw, dD=dD, drp=drp, c_r=0.35, I_h=5.2e-6, m_h=0.0158, r_com=11.3, k_bank=100.0, r_k=11.0, t_end=0.45, dt=8e-6)))
    with mp.Pool(4) as pool:
        for r in pool.imap(job, jobs):
            print(json.dumps(r), flush=True)
