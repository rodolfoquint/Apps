import sys, json, itertools, multiprocessing as mp
sys.path.insert(0, '.')
from run_dyn3 import job
if __name__ == '__main__':
    jobs = []
    for drho in [2.1686, 2.3186, 2.4686]:
        for (dD, drp), cr, T, d in itertools.product([(0.4, -0.2), (0.0, 0.0)], [0.25, 0.5], [1, 3, 20], [1, -1]):
            jobs.append((drho, dict(T_Nmm=T, direction=d, dD=dD, drp=drp, c_r=cr, mu=0.35, mu_b=0.35, I_h=5.2e-6, m_h=0.0158, r_com=11.3,
                                    k_bank=100.0, t_end=0.45)))
    with mp.Pool(4) as pool:
        for r in pool.imap(job, jobs):
            print(json.dumps(r), flush=True)
