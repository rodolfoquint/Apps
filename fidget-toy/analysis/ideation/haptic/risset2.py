"""Risset drum: n=4, L=3 -> 16 beats/rev, two sticks (two Z tracks). Computes lifts, ramps, torque profile,
energy per rev, click impact speeds, per-stick min tooth spacing, and a synthetic click-train WAV for listening."""
import numpy as np, wave, struct
import os as _os; _HERE = _os.path.dirname(_os.path.abspath(__file__))  # repo-relative paths
n, L = 4, 3
K = n*2**(L-1)
k = np.arange(K); tau = np.log2(1 + k/K)
def v2(x):
    if x == 0: return 99
    c = 0
    while x % 2 == 0: x //= 2; c += 1
    return c
A = lambda x: np.sin(np.pi*x/L)**2
loud = np.array([sum(A(j + t) for j in range(L) if j >= L-1-min(v2(kk), L-1)) for kk, t in zip(k, tau)])
ang = 360*tau
# physical parameters
R = 19.0; c = 0.40; lift_max = 1.40          # mm: root radius of track at R, neutral gap c, max lift beyond neutral
E = 3500.; t = 1.2; w = 6.0; Lf = 22.0; r_f = 9.0; r_v = 30.0
krot = E*w*t**3/(12*Lf)                      # Nmm/rad
I_lever = 1.5e-3*(15e-3)**2                  # kg m^2
omega = np.sqrt(krot*1e-3/I_lever)
mu = 0.35
vmax = np.sqrt(lift_max**2 - c**2)
lift = np.sqrt((loud/loud.max())**2*vmax**2 + c**2)
lift[loud/loud.max() < 0.05] = 0.0           # fully faded: no tooth
v_imp = omega*np.sqrt(np.clip(lift**2 - c**2, 0, None))*1e-3   # m/s at stick tip
stick = np.where(k % 4 < 2, 'L', 'R')
print(f'K={K} beats/rev; k_rot={krot:.0f} Nmm/rad; lever f_n={omega/2/np.pi:.0f} Hz')
print(' k  angle  loud  lift(mm) crest_above_root  v_imp(m/s)  dB  stick')
for i in k:
    db = 20*np.log10(max(v_imp[i], 1e-4)/v_imp.max())
    print(f'{i:2d} {ang[i]:6.1f} {loud[i]:5.2f} {lift[i]:6.2f} {lift[i]+c if lift[i]>0 else 0:6.2f} {v_imp[i]:8.2f} {db:6.1f}   {stick[i]}')
for s in 'LR':
    a = ang[(stick == s) & (lift > 0)]
    sp = np.diff(np.r_[a, a[0] + 360])
    print(s, 'teeth', len(a), 'min spacing %.1f deg = %.1f mm arc' % (sp.min(), np.radians(sp.min())*R))
# torque: each tooth ramps over min(0.8*gap to previous tooth on its track, 28 deg); torque = F*tan(alpha+phi)*R
phis = np.linspace(0, 360, 3601)
tq = np.zeros_like(phis)
energy = 0
for s in 'LR':
    idx = np.where((stick == s) & (lift > 0))[0]
    a = ang[idx]; prev = np.r_[a[-1] - 360, a[:-1]]
    for ai, pi, li in zip(a, prev, lift[idx]):
        ramp = min(0.8*(ai - pi), 28.0)
        lift_from = 0.0  # contact begins when crest region rises above neutral (c above root); we ramp from root
        arc = np.radians(ramp)*R
        slope = (li + c)/arc
        al = np.arctan(slope)
        sel = (phis > ai - ramp) & (phis <= ai)
        y = (phis[sel] - (ai - ramp))/ramp*(li + c) - c   # lift beyond neutral
        y = np.clip(y, 0, None)
        F = krot*(y/r_f)/r_f
        tq[sel] += F*np.tan(al + np.arctan(mu))*R
        energy += 0.5*krot*(li/r_f)**2
print('peak torque %.1f Nmm, mean torque %.1f Nmm, stored energy/rev %.1f mJ' % (tq.max(), tq.mean(), energy))
print('max lever rotation %.1f deg, leaf strain %.2f %%, paw travel %.1f mm' % (np.degrees(lift_max/r_f), 100*t*(lift_max/r_f)/(2*Lf), r_v*lift_max/r_f))
# synthetic audio: 6 s at 0.5 rev/s, decaying 1.6 kHz/3.1 kHz click per impact, amplitude ~ v_imp
fs = 22050; dur = 6.0; rps = 0.5
x = np.zeros(int(fs*dur))
tt = np.arange(int(0.03*fs))/fs
clk = (np.sin(2*np.pi*1600*tt) + 0.5*np.sin(2*np.pi*3100*tt))*np.exp(-tt/0.006)
for rev in range(int(dur*rps) + 1):
    for i in k:
        if v_imp[i] <= 0: continue
        t0 = (rev + tau[i])/rps
        s0 = int(t0*fs)
        if s0 + len(clk) < len(x):
            x[s0:s0 + len(clk)] += v_imp[i]/v_imp.max()*clk
x /= np.abs(x).max()*1.1
with wave.open(_os.path.join(_HERE, 'risset_drum_preview.wav'), 'w') as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(fs)
    wf.writeframes(b''.join(struct.pack('<h', int(v*32767)) for v in x))
print('wrote risset_drum_preview.wav')
