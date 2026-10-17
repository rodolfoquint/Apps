"""2-DOF penalty-contact simulation of a hand-driven, spring-free pin-pallet (foliot) escapement.
Wheel driven by constant thumb torque T; anchor (foliot = character's wings/tail) has inertia only.
Outputs oscillation frequency, swing amplitude, wheel speed, impact rate, peak contact force.
"""
import numpy as np, shapely
from scipy.ndimage import map_coordinates
from esc_cspace import star

def build(N, Rt, Rr, tip_frac=0.18, root_frac=0.30, h=0.04):
    W = star(N, Rt, Rr, tip_frac, root_frac)
    L = Rt + 4
    xs = np.arange(-L, L + h, h)
    X, Y = np.meshgrid(xs, xs, indexing='ij')
    d = shapely.distance(W.boundary, shapely.points(X.ravel(), Y.ravel())).reshape(X.shape)
    inside = shapely.contains_xy(W, X.ravel(), Y.ravel()).reshape(X.shape)
    sdf = np.where(inside, -d, d)
    gx, gy = np.gradient(sdf, h)
    return dict(sdf=sdf, gx=gx, gy=gy, x0=-L, h=h)

def sample(G, q):
    i = (q[0] - G['x0'])/G['h']; j = (q[1] - G['x0'])/G['h']
    c = np.array([[i], [j]])
    s = map_coordinates(G['sdf'], c, order=1)[0]
    gx = map_coordinates(G['gx'], c, order=1)[0]; gy = map_coordinates(G['gy'], c, order=1)[0]
    n = np.array([gx, gy]); n /= (np.linalg.norm(n) + 1e-12)
    return s, n

def simulate(G, D, pins_local, rp, T_Nmm, I_a=4e-6, J_w=4e-6, mu=0.35, k=5e4, zeta=0.25,
             c_w=2e-7, c_a=2e-8, t_end=1.2, dt=1.5e-5, psi0=0.0, direction=1):
    A = np.array([0.0, D])
    phi, w = 0.0, 0.0
    psi, om = np.radians(psi0), 0.0
    T = direction*T_Nmm*1e-3
    n_steps = int(t_end/dt)
    log_psi = np.empty(n_steps); log_phi = np.empty(n_steps); Fmax = 0.0; impacts = 0
    in_contact = [False, False]
    m_eff = I_a/((np.linalg.norm(pins_local[0]))*1e-3)**2
    c_n = 2*zeta*np.sqrt(k*m_eff)
    for s in range(n_steps):
        tau_w = T - c_w*w; tau_a = -c_a*om
        cps, sps = np.cos(psi), np.sin(psi)
        cph, sph = np.cos(phi), np.sin(phi)
        for pi_, pl in enumerate(pins_local):
            P = A + np.array([cps*pl[0] - sps*pl[1], sps*pl[0] + cps*pl[1]])   # mm, world
            q = np.array([cph*P[0] + sph*P[1], -sph*P[0] + cph*P[1]])       # wheel frame
            sd, nw = sample(G, q)
            pen = rp - sd
            if pen > 0:
                if not in_contact[pi_]:
                    impacts += 1; in_contact[pi_] = True
                n = np.array([cph*nw[0] - sph*nw[1], sph*nw[0] + cph*nw[1]])  # world normal, wheel->pin
                C = P - rp*n   # contact point (mm)
                rA = (C - A)*1e-3; rO = C*1e-3
                v_pin = om*np.array([-rA[1], rA[0]]); v_wh = w*np.array([-rO[1], rO[0]])
                vrel = v_pin - v_wh
                vn = vrel @ n
                Fn = max(0.0, k*pen*1e-3 - c_n*vn)
                t = np.array([-n[1], n[0]]); vt = vrel @ t
                Ft = -mu*Fn*np.tanh(vt/2e-3)
                F = Fn*n + Ft*t   # on pin
                tau_a += rA[0]*F[1] - rA[1]*F[0]
                tau_w -= rO[0]*F[1] - rO[1]*F[0]
                Fmax = max(Fmax, Fn)
            else:
                in_contact[pi_] = False
        w += dt*tau_w/J_w; om += dt*tau_a/I_a
        phi += dt*w; psi += dt*om
        log_psi[s] = psi; log_phi[s] = phi
    t = np.arange(n_steps)*dt
    sel = t > 0.4*t_end
    ps = np.degrees(log_psi[sel]); ph = log_phi[sel]
    mean = ps.mean()
    zc = np.where(np.diff(np.sign(ps - mean)) != 0)[0]
    freq = len(zc)/2/(t[sel][-1] - t[sel][0]) if len(zc) > 2 else 0.0
    wheel_rps = (ph[-1] - ph[0])/(2*np.pi)/(t[sel][-1] - t[sel][0])
    return dict(T_Nmm=T_Nmm, freq_Hz=round(freq, 1), swing_pp_deg=round(float(np.percentile(ps, 99) - np.percentile(ps, 1)), 1),
                wheel_rps=round(float(wheel_rps), 2), impacts_per_s=round(impacts/t_end, 0), Fmax_N=round(Fmax, 2),
                psi_mean=round(float(mean), 1))

if __name__ == '__main__':
    import sys, json
    N, Rt, Rr, rho_off, m, tilt = 9, 16.0, 10.0, 0.0, 2, 1.0
    if len(sys.argv) > 1:
        N, Rt, Rr, rho_off, m, tilt = [float(x) for x in sys.argv[1:7]]; N = int(N); m = int(m)
    rp = 2.0
    pitch = 2*np.pi/N
    gam = (m + 0.5)*pitch/2
    rho = (Rt + Rr)/2 + rp + rho_off
    D = rho/np.cos(gam)*tilt
    P1 = np.array([-rho*np.sin(gam), rho*np.cos(gam)]); P2 = np.array([rho*np.sin(gam), rho*np.cos(gam)])
    A = np.array([0, D])
    pins_local = [P1 - A, P2 - A]
    print('geometry D=%.2f ra=%.2f' % (D, np.linalg.norm(P1 - A)))
    G = build(N, Rt, Rr)
    I_a = float(sys.argv[7]) if len(sys.argv) > 7 else 4e-6
    for T in [2, 5, 10, 20, 40]:
        for d in [1, -1]:
            r = simulate(G, D, pins_local, rp, T, I_a=I_a, direction=d)
            r['dir'] = d
            print(r, flush=True)
