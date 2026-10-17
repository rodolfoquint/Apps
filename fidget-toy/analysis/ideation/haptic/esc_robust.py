import numpy as np, json, sys
from esc_dyn2 import simulate, geometry
from esc_opt import sdf_grid, star
p = {"N": 8, "Rt": 14.681, "tooth_h": 5.286, "tip_frac": 0.093, "root_frac": 0.175, "rp": 2.1, "drho": 0.739, "m": 2, "tilt": 0.877, "psi_b": 12.155}
case = sys.argv[1]
W, A, pins = geometry(p)
G = sdf_grid(W, p['Rt'], h=0.05)
def show(tag, r): print(tag, r, flush=True)
if case == 'mu':
    for mu in [0.2, 0.5, 0.6]:
        for T in [3, 20]:
            for d in [1, -1]:
                show(f'mu={mu}', simulate(G, A, pins, p['rp'], T, p['psi_b'], mu=mu, direction=d))
elif case == 'inertia':
    for I in [2e-6, 8e-6, 1.6e-5]:
        for T in [3, 20]:
            show(f'I={I}', simulate(G, A, pins, p['rp'], T, p['psi_b'], I_a=I))
elif case == 'tol':
    for drp in [-0.2, 0.2]:
        for T in [3, 20]:
            for d in [1, -1]:
                show(f'rp{drp:+}', simulate(G, A, pins, p['rp'] + drp, T, p['psi_b'], direction=d))
    for dD in [-0.4, 0.4]:
        for T in [3, 20]:
            show(f'D{dD:+}', simulate(G, A + np.array([0, dD]), pins, p['rp'], T, p['psi_b']))
    for dx in [-0.4, 0.4]:
        for T in [3, 20]:
            show(f'x{dx:+}', simulate(G, A + np.array([dx, 0]), pins, p['rp'], T, p['psi_b']))
