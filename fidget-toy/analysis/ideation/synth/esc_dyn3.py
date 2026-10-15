"""Synthesis check 2: escapement contact dynamics WITH journal play, journal Coulomb friction, knob side-load and gravity.
6 DOF: wheel (x,y,phi) on a fixed post at O, head (x,y,psi) on a fixed post at P. Penalty contacts everywhere.
Extends the ideation model esc_dyn2.py (which had rigid frictionless pivots)."""
import sys, json, numpy as np
import os as _os; _HERE = _os.path.dirname(_os.path.abspath(__file__))  # repo-relative paths
sys.path.insert(0, _os.path.join(_HERE, '..', 'haptic'))
from esc_opt import star, sdf_grid
from esc_layout import esc_geometry, P_ESC

class SDF:
    def __init__(self, W, Rt, h=0.04):
        G = sdf_grid(W, Rt, h=h); self.s, self.gx, self.gy, self.x0, self.h = G['s'], G['gx'], G['gy'], G['x0'], G['h']
        self.n = self.s.shape[0]
    def __call__(self, x, y):
        fx = (x - self.x0)/self.h; fy = (y - self.x0)/self.h
        i = int(fx); j = int(fy)
        if i < 0 or j < 0 or i >= self.n - 1 or j >= self.n - 1: return 99.0, 1.0, 0.0
        tx = fx - i; ty = fy - j
        def bl(a): return (a[i, j]*(1-tx)*(1-ty) + a[i+1, j]*tx*(1-ty) + a[i, j+1]*(1-tx)*ty + a[i+1, j+1]*tx*ty)
        gx = bl(self.gx); gy = bl(self.gy); nn = (gx*gx + gy*gy)**0.5 + 1e-12
        return bl(self.s), gx/nn, gy/nn

def simulate(S, D, pins, rp, T_Nmm, psi_b, direction=1, I_h=6e-6, m_h=0.010, J_w=4e-6, m_w=0.006,
             mu=0.35, mu_b=0.35, r_b=4.0, c_r=0.35, r_k=12.5, r_com=12.0, gravity=True,
             k=5e4, zeta=0.25, k_b=2e5, c_w=2e-7, c_a=2e-8, k_bank=2.0, t_end=0.6, dt=1e-5, dD=0.0, drp=0.0, seed=0):
    rp = rp + drp
    Pn = np.array([0.0, D + dD])          # nominal head-post centre (post position error dD)
    T = direction*T_Nmm*1e-3
    g = 9.81 if gravity else 0.0
    mm = 1e-3
    # state (SI): wheel offset xw (m), head offset xh (m)
    xw = np.zeros(2); vw = np.zeros(2); phi = 0.0; om = 0.0
    xh = np.zeros(2); vh = np.zeros(2); psi = 0.0; Om = 0.0
    m_eff = I_h/(np.linalg.norm(pins[0] - np.array([0, D]))*mm)**2
    c_n = 2*zeta*np.sqrt(k*m_eff)
    cbw = 2*0.3*np.sqrt(k_b*m_w); cbh = 2*0.3*np.sqrt(k_b*m_h)
    pl = [(p - np.array([0, D])) for p in pins]   # pins in head frame (mm) relative to pivot
    ns = int(t_end/dt)
    PHI = np.empty(ns); PSI = np.empty(ns)
    E_in = 0.0; E_bw = 0.0; E_bh = 0.0; impacts = 0; incont = [False, False]; Fmax = 0.0; bank = 0; inb = False
    phk0 = 0.0
    for s in range(ns):
        Fw = np.array([0.0, -m_w*g]); Fh = np.array([0.0, -m_h*g])
        tw = T - c_w*om; th = -c_a*Om + m_h*g*r_com*mm*np.sin(psi)
        # knob side load (finger pushes knob tangentially)
        a = phi + phk0
        Fw += (T/(r_k*mm))*np.array([-np.sin(a), np.cos(a)])
        # banking
        pb = np.radians(psi_b)
        if abs(psi) > pb:
            th += -k_bank*(psi - np.sign(psi)*pb) - 2*0.3*np.sqrt(k_bank*I_h)*Om
            if not inb: bank += 1; inb = True
        else: inb = False
        # journals (radial play c_r), friction torque mu_b*N*r_b
        for which in (0, 1):
            x, v, m, cb = (xw, vw, m_w, cbw) if which == 0 else (xh, vh, m_h, cbh)
            r = np.hypot(x[0], x[1]); pen = r - c_r*mm
            if pen > 0:
                nrm = x/r
                Fn = max(0.0, k_b*pen + cb*(v @ nrm))
                Fb = -Fn*nrm
                if which == 0:
                    Fw += Fb; tf = -mu_b*Fn*r_b*mm*np.tanh(om/0.5); tw += tf; E_bw += -tf*om*dt
                else:
                    Fh += Fb; tf = -mu_b*Fn*r_b*mm*np.tanh(Om/0.5); th += tf; E_bh += -tf*Om*dt
        # escapement contacts
        cps, sps, cph, sph = np.cos(psi), np.sin(psi), np.cos(phi), np.sin(phi)
        Ph = Pn + xh/mm                     # head pivot (mm)
        Ow = xw/mm                          # wheel centre (mm)
        for i, q0 in enumerate(pl):
            Pp = Ph + np.array([cps*q0[0] - sps*q0[1], sps*q0[0] + cps*q0[1]])
            d = Pp - Ow
            qx = cph*d[0] + sph*d[1]; qy = -sph*d[0] + cph*d[1]
            sd, nx, ny = S(qx, qy)
            pen = rp - sd
            if pen > 0:
                if not incont[i]: impacts += 1; incont[i] = True
                n = np.array([cph*nx - sph*ny, sph*nx + cph*ny])
                C = Pp - rp*n
                rA = (C - Ph)*mm; rO = (C - Ow)*mm
                vrel = (vh + Om*np.array([-rA[1], rA[0]])) - (vw + om*np.array([-rO[1], rO[0]]))
                Fn = max(0.0, k*pen*mm - c_n*(vrel @ n))
                t = np.array([-n[1], n[0]])
                F = Fn*n - mu*Fn*np.tanh((vrel @ t)/2e-3)*t
                Fh += F; Fw -= F
                th += rA[0]*F[1] - rA[1]*F[0]; tw -= rO[0]*F[1] - rO[1]*F[0]
                Fmax = max(Fmax, Fn)
            else: incont[i] = False
        vw += dt*Fw/m_w; vh += dt*Fh/m_h; om += dt*tw/J_w; Om += dt*th/I_h
        xw += dt*vw; xh += dt*vh; phi += dt*om; psi += dt*Om
        E_in += T*om*dt
        PHI[s] = phi; PSI[s] = psi
    t = np.arange(ns)*dt; sel = t > 0.35*t_end
    ps = np.degrees(PSI[sel]); ph = PHI[sel]; dur = t[sel][-1] - t[sel][0]
    zc = np.where(np.diff(np.sign(ps - ps.mean())) != 0)[0]
    rps = float((ph[-1] - ph[0])/(2*np.pi)/dur)
    swing = float(np.percentile(ps, 99.5) - np.percentile(ps, 0.5))
    return dict(T=T_Nmm, dir=direction, rps=round(rps, 2), f_head=round(len(zc)/2/dur, 1), swing=round(swing, 1),
                imp_s=round(impacts/t_end), bank_s=round(bank/t_end), Fmax=round(Fmax, 1),
                loss_wheel_brg=round(E_bw/max(E_in, 1e-12), 3), loss_head_brg=round(E_bh/max(E_in, 1e-12), 3),
                status=('JAM' if abs(rps) < 0.15 else ('FREESPIN' if swing < 3.0 else 'RUN')))

def make(drho=None):
    g = esc_geometry(drho=drho)
    S = SDF(g['W'], g['Rt'])
    return g, S

if __name__ == '__main__':
    import multiprocessing as mp
    mode = sys.argv[1] if len(sys.argv) > 1 else 'nominal'
    print(mode, flush=True)
