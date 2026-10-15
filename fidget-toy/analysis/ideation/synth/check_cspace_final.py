import pickle, json, numpy as np, shapely
from shapely.geometry import Point
from shapely import affinity
from esc_layout import esc_geometry, cspace_check
from layout import build, PAR
L = build(); g = L['g']
tips = [Point(c).buffer(g['rp'], 128) for c in g['pins']]
out, phis, psis, clp, clf = cspace_check(g, L['head_band'], tips, PAR['psi_b'], n_phi=91, n_psi=51)
j0 = np.argmin(np.abs(psis))
i0 = np.argmax(clf[:, j0])
print('print pose at psi=0: phi=%.1f deg, min head-band-to-wheel clearance %.2f mm (pins %.2f)' % (phis[i0], clf[i0, j0], clp[i0, j0]))
