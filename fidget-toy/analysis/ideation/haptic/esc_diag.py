import numpy as np, sys
import os as _os; _HERE = _os.path.dirname(_os.path.abspath(__file__))  # repo-relative paths
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
import esc_dyn
from esc_dyn import build, sample
N,Rt,Rr,drho,m,tilt = 8,16.,10.,1.5,1,1.1
mu = float(sys.argv[1]) if len(sys.argv)>1 else 0.35
T = float(sys.argv[2]) if len(sys.argv)>2 else 10
rp=2.0; pitch=2*np.pi/N; gam=(m+.5)*pitch/2; rho=(Rt+Rr)/2+rp+drho
D=rho/np.cos(gam)*tilt; A=np.array([0,D])
P1=np.array([-rho*np.sin(gam), rho*np.cos(gam)]); P2=np.array([rho*np.sin(gam), rho*np.cos(gam)])
G=build(N,Rt,Rr)
# monkeypatch to record
import types
src = open(_os.path.join(_HERE, 'esc_dyn.py')).read()
ns = {}
code = src.split("if __name__")[0].replace("    t = np.arange(n_steps)*dt\n", "    t = np.arange(n_steps)*dt\n    globals()['LOG']=(t,log_phi.copy(),log_psi.copy())\n")
exec(code, ns)
r = ns['simulate'](G,D,[P1-A,P2-A],rp,T,mu=mu,t_end=0.6)
print(r)
t,ph,ps = ns['LOG']
fig,ax=plt.subplots(2,1,figsize=(10,6),sharex=True)
ax[0].plot(t,np.degrees(ph)); ax[0].set_ylabel('wheel deg')
ax[1].plot(t,np.degrees(ps)); ax[1].set_ylabel('anchor deg')
plt.savefig(_os.path.join(_HERE, f'diag_mu{mu}_T{T}.png'),dpi=70)
