import numpy as np, json, sys
from esc_dyn2 import simulate, geometry
from esc_opt import sdf_grid
p = json.loads(sys.argv[1]); tag = sys.argv[2]
W, A, pins = geometry(p)
G = sdf_grid(W, p['Rt'], h=0.05)
cases = [('nom', 0, 0, 0), ('D-0.4', -0.4, 0, 0), ('D+0.4', 0.4, 0, 0), ('rp+0.2', 0, 0.2, 0), ('rp-0.2', 0, -0.2, 0),
         ('D-0.4,rp+0.2', -0.4, 0.2, 0), ('D+0.4,rp-0.2', 0.4, -0.2, 0)]
allok = True
for name, dD, drp, _ in cases:
    for T in [3, 20]:
        for d in [1, -1]:
            r = simulate(G, A + np.array([0, dD]), pins, p['rp'] + drp, T, p['psi_b'], direction=d, t_end=0.6)
            ok = abs(r['wheel_rps']) > 0.3
            allok &= ok
            print(tag, name, 'OK ' if ok else 'JAM', r, flush=True)
print(tag, 'ALL_OK' if allok else 'SOME_JAM')
