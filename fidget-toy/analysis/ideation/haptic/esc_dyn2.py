"""Dynamic check (penalty contact, Coulomb friction, banking stops) for a candidate from esc_opt."""
import numpy as np, json, sys
from scipy.ndimage import map_coordinates
from esc_opt import star, sdf_grid

def simulate(G, A, pins, rp, T_Nmm, psi_b, I_a=4e-6, J_w=4e-6, mu=0.35, k=5e4, zeta=0.25, c_w=2e-7, c_a=2e-8,
             t_end=0.8, dt=1.5e-5, direction=1, k_bank=2.0, log=False):
    h, x0 = G['h'], G['x0']
    def samp(q):
        c = np.array([[(q[0] - x0)/h], [(q[1] - x0)/h]])
        s = map_coordinates(G['s'], c, order=1, mode='nearest')[0]
        gx = map_coordinates(G['gx'], c, order=1, mode='nearest')[0]; gy = map_coordinates(G['gy'], c, order=1, mode='nearest')[0]
        n = np.array([gx, gy]); return s, n/(np.linalg.norm(n) + 1e-12)
    phi = w = psi = om = 0.0
    T = direction*T_Nmm*1e-3
    ns = int(t_end/dt)
    P_ = np.empty(ns); S_ = np.empty(ns)
    m_eff = I_a/(np.linalg.norm(pins[0])*1e-3)**2
    c_n = 2*zeta*np.sqrt(k*m_eff)
    impacts = 0; incont = [False, False]; Fmax = 0.0; bank_hits = 0; inbank = False
    pb = np.radians(psi_b)
    for s in range(ns):
        tw = T - c_w*w; ta = -c_a*om
        # banking stops (stiff torsional spring + damping)
        if abs(psi) > pb:
            ta += -k_bank*(psi - np.sign(psi)*pb) - 2*0.3*np.sqrt(k_bank*I_a)*om
            if not inbank: bank_hits += 1; inbank = True
        else:
            inbank = False
        cps, sps, cph, sph = np.cos(psi), np.sin(psi), np.cos(phi), np.sin(phi)
        for i, pl in enumerate(pins):
            P = A + np.array([cps*pl[0] - sps*pl[1], sps*pl[0] + cps*pl[1]])
            q = np.array([cph*P[0] + sph*P[1], -sph*P[0] + cph*P[1]])
            sd, nw = samp(q)
            pen = rp - sd
            if pen > 0:
                if not incont[i]: impacts += 1; incont[i] = True
                n = np.array([cph*nw[0] - sph*nw[1], sph*nw[0] + cph*nw[1]])
                C = P - rp*n
                rA = (C - A)*1e-3; rO = C*1e-3
                vrel = om*np.array([-rA[1], rA[0]]) - w*np.array([-rO[1], rO[0]])
                Fn = max(0.0, k*pen*1e-3 - c_n*(vrel @ n))
                t = np.array([-n[1], n[0]])
                F = Fn*n - mu*Fn*np.tanh((vrel @ t)/2e-3)*t
                ta += rA[0]*F[1] - rA[1]*F[0]; tw -= rO[0]*F[1] - rO[1]*F[0]
                Fmax = max(Fmax, Fn)
            else:
                incont[i] = False
        w += dt*tw/J_w; om += dt*ta/I_a; phi += dt*w; psi += dt*om
        P_[s] = phi; S_[s] = psi
    t = np.arange(ns)*dt; sel = t > 0.35*t_end
    ps = np.degrees(S_[sel]); ph = P_[sel]
    zc = np.where(np.diff(np.sign(ps - ps.mean())) != 0)[0]
    dur = t[sel][-1] - t[sel][0]
    out = dict(T=T_Nmm, dir=direction, freq_Hz=round(len(zc)/2/dur, 1), swing_pp=round(float(np.percentile(ps, 99.5) - np.percentile(ps, 0.5)), 1),
               wheel_rps=round(float((ph[-1] - ph[0])/(2*np.pi)/dur), 2), impacts_s=round(impacts/t_end), bank_hits_s=round(bank_hits/t_end),
               Fmax=round(float(Fmax), 1))
    if log: out['_log'] = (t, P_, S_)
    return out

def geometry(p):
    N, Rt, Rr = p['N'], p['Rt'], p['Rt'] - p['tooth_h']
    pitch = 2*np.pi/N; gam = (p['m'] + 0.5)*pitch/2
    rho = (Rt + Rr)/2 + p['rp'] + p['drho']
    D = rho/np.cos(gam)*p['tilt']; A = np.array([0.0, D])
    pins = [np.array([-rho*np.sin(gam), rho*np.cos(gam)]) - A, np.array([rho*np.sin(gam), rho*np.cos(gam)]) - A]
    W = star(N, Rt, Rr, p['tip_frac'], p['root_frac'])
    return W, A, pins

if __name__ == '__main__':
    p = json.loads(sys.argv[1])
    I_a = float(sys.argv[2]) if len(sys.argv) > 2 else 4e-6
    W, A, pins = geometry(p)
    G = sdf_grid(W, p['Rt'], h=0.05)
    for T in [2, 5, 10, 20, 40]:
        for d in [1, -1]:
            print(simulate(G, A, pins, p['rp'], T, p['psi_b'], I_a=I_a, direction=d), flush=True)
