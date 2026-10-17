"""Risset-rhythm ratchet: tooth angles + drop heights for an 'endless accelerando' per revolution.
Layers j=0..L-1 have beat rate n*2^j*ln2*2^tau per rev; nested grids -> union = finest grid.
Beat k (k=0..n*2^(L-1)-1) at tau_k = log2(1 + k/(n*2^(L-1))). Loudness = sum of envelopes of layers it belongs to.
Then split beats between two feet (two Z-tracks), check min same-track pitch, and map loudness to drop height
using the overshoot-impact law v ~ omega*sqrt(h_eff^2 - c^2) (foot neutral sits c above root).
"""
import numpy as np

def risset(n=3, L=3):
    K = n*2**(L-1)
    k = np.arange(K)
    tau = np.log2(1 + k/K)
    def v2(x):
        if x == 0: return 99
        c = 0
        while x % 2 == 0: x//=2; c+=1
        return c
    A = lambda x: np.sin(np.pi*x/L)**2
    loud = np.array([sum(A(j + t) for j in range(L) if j >= L-1-min(v2(kk), L-1)) for kk, t in zip(k, tau)])
    return k, tau, loud

for (n, L) in [(3, 3), (4, 3), (2, 4)]:
    k, tau, loud = risset(n, L)
    print(f'n={n} L={L}: {len(k)} beats/rev')
    print('  angle deg :', np.round(360*tau, 1))
    print('  spacing   :', np.round(np.diff(np.r_[360*tau, 360]), 1))
    print('  loudness  :', np.round(loud, 2))

# chosen: n=3, L=3 -> 12 beats. Two feet: assign k%4 in {0,1}->Left, {2,3}->Right
n, L = 3, 3
k, tau, loud = risset(n, L)
ang = 360*tau
R_track = 19.0  # mm, tooth tip radius on the ball
left = [i for i in k if i % 4 in (0, 1)]
right = [i for i in k if i % 4 in (2, 3)]
for name, idx in [('L', left), ('R', right)]:
    a = ang[idx]
    sp = np.diff(np.r_[a, a[0] + 360])
    print(name, 'teeth', len(idx), 'angles', np.round(a, 1), 'pitch deg', np.round(sp, 1), 'min arc mm %.1f' % (np.radians(sp.min())*R_track))

# loudness -> drop height. Foot neutral sits c above root; impact velocity ~ omega*sqrt(h^2-c^2) (undamped SHM overshoot)
c = 0.40   # mm print clearance, foot neutral above root
hmax = 1.60
vmax = np.sqrt(hmax**2 - c**2)
target_v = loud/loud.max()*vmax
h = np.sqrt(target_v**2 + c**2)
h[loud < 0.08] = 0.0   # fully faded -> no tooth (just ramp continues)
print('drop heights mm:', np.round(h, 2))
print('relative impact speed:', np.round(target_v/vmax, 2), ' dB rel max:', np.round(20*np.log10(np.maximum(target_v/vmax, 1e-3)), 1))

# leg flexure: compliant hinge leaf + rigid leg lever. foot contact at r_f from hinge, visible paw at r_v
E = 3500.0  # MPa PLA (printed ~3.0-3.5 GPa)
t, w, Lf = 1.0, 6.0, 16.0   # leaf thickness, Z-width, length (mm)
r_f, r_v = 7.0, 26.0
theta = (hmax - c)/r_f      # rad, max rotation (lift beyond neutral)
eps = t*theta/(2*Lf)
krot = E*w*t**3/(12*Lf)     # N mm / rad
F_foot = krot*theta/r_f
print(f'leg rot {np.degrees(theta):.1f} deg, leaf strain {100*eps:.2f}%, k_rot {krot:.0f} Nmm/rad, foot force {F_foot:.2f} N, paw travel {r_v*theta:.1f} mm')
# torque to turn: ramp slope over the pitch, friction mu
mu = 0.35
pitch_arc = np.radians(30)*R_track
slope = (hmax - c)/pitch_arc
alpha = np.arctan(slope)
Ft = F_foot*np.tan(alpha + np.arctan(mu))
print(f'ramp pressure angle {np.degrees(alpha):.1f} deg, peak tangential {Ft:.2f} N, peak torque {Ft*R_track:.1f} Nmm per foot')
# leaf natural frequency (leg inertia): leg ~ 1.2 g at radius ~14 mm
I_leg = 1.2e-3*(14e-3)**2
f_leg = np.sqrt(krot*1e-3/I_leg)/(2*np.pi)
print(f'leg natural freq ~{f_leg:.0f} Hz -> snap-back time ~{1000/(4*f_leg):.1f} ms (quarter period)')
