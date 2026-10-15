import numpy as np, json, sys
from esc_dyn2 import simulate, geometry
from esc_opt import sdf_grid, evaluate
p = {"N": 8, "Rt": 14.2992, "tooth_h": 5.3968, "tip_frac": 0.0765, "root_frac": 0.1333, "rp": 2.1448, "drho": 1.8686, "m": 2, "tilt": 0.8792, "psi_b": 12.42}
W, A, pins = geometry(p)
which = sys.argv[1]
if which == 'geo':
    print('A', A, 'pins(world)', [list(np.round(A + q, 2)) for q in pins], 'ra', np.linalg.norm(pins[0]))
    r, _ = evaluate(p['N'], p['Rt'], p['Rt'] - p['tooth_h'], p['tip_frac'], p['root_frac'], p['rp'], p['drho'], p['m'], p['tilt'], p['psi_b'])
    print('static', r)
    print('wheel area mm2', W.area, 'root radius', p['Rt'] - p['tooth_h'])
    sys.exit()
G = sdf_grid(W, p['Rt'], h=0.05)
if which == 'torque':
    for T in [1, 2, 5, 10, 40]:
        print(simulate(G, A, pins, p['rp'], T, p['psi_b'], t_end=0.6), flush=True)
elif which == 'mu':
    for mu in [0.2, 0.5, 0.6]:
        for T in [3, 20]:
            print('mu', mu, simulate(G, A, pins, p['rp'], T, p['psi_b'], mu=mu, t_end=0.6), flush=True)
elif which == 'inertia':
    for I in [2e-6, 8e-6, 1.6e-5]:
        for T in [3, 20]:
            print('I', I, simulate(G, A, pins, p['rp'], T, p['psi_b'], I_a=I, t_end=0.6), flush=True)
