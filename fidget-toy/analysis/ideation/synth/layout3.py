"""Layout v3: body/roof only where the moving band parts are NOT already covered by the face (reduces I3)."""
import json, numpy as np, shapely, sys
from shapely.geometry import Point, Polygon, LineString
from layout import build, PAR, swept, max_inscribed_width, rot
import os as _os; _HERE = _os.path.dirname(_os.path.abspath(__file__))  # repo-relative paths
sys.path.insert(0, _os.path.join(_HERE, '..', 'haptic'))
from esc_opt import evaluate
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
L = build(); g = L['g']; P = L['P']; O = Point(0, 0)
exposed = L["head_band"].difference(L["face_up"]).buffer(-0.05).buffer(0.05).simplify(0.01)
exposed = shapely.make_valid(exposed)
exposed = shapely.union_all([q for q in (exposed.geoms if hasattr(exposed, "geoms") else [exposed]) if q.geom_type == "Polygon" and q.area > 0.5])                     # head-frame band parts not under own face
exp_sw = swept(exposed, P, PAR['psi_b'])
body = shapely.union_all([O.buffer(PAR['body_r'], 128), exp_sw.buffer(PAR['gap'] + PAR['wall'], 32)]).buffer(3, 32).buffer(-3, 32)
roof = body.difference(O.buffer(PAR['R_hole_roof'], 128)).difference(Point(P).buffer(PAR['hub_r'] + PAR['gap'], 64))
fill_band = body.difference(L['head_band_swept'].buffer(PAR['gap'], 32)).difference(O.buffer(g['Rt'] + 0.5, 128))
roof_sw = swept(roof.buffer(PAR['gap'], 16), P, PAR['psi_b'])
face_mid = L['face_up'].difference(roof_sw)
I3 = L['face_up'].intersection(roof_sw)
chan = exp_sw.buffer(PAR['gap']).difference(O.buffer(PAR['R_hole_roof'], 128))
backdrop = shapely.union_all([body, L['face_up_swept'].buffer(PAR['backdrop_margin'], 64)]).buffer(2, 32).buffer(-2, 32)
bx = backdrop.bounds
rep = dict(I3_area=round(I3.area, 1), roof_area=round(roof.area, 1), body_bbox=[round(v, 1) for v in body.bounds],
           overall_W_H=(round(bx[2] - bx[0], 1), round(bx[3] - bx[1], 1)), bbox=[round(v, 1) for v in bx],
           channel_bridge_widths=[round(max_inscribed_width(p), 2) for p in (chan.geoms if chan.geom_type == 'MultiPolygon' else [chan])],
           backplate_area=round(backdrop.area, 0))
# floating areas over back plate (I1) : wheel band footprint + head band swept? use head band (single pose) + wheel star
rep['I1_area_head_band'] = round(L['head_band'].area, 0); rep['I1_area_wheel'] = round(g['W'].area, 0)
# static pressure-angle / jam screen at re-centred pin depth (ideation evaluate(), mu=0.35, 8 deg margin)
p = dict(N=8, Rt=14.2992, tooth_h=5.3968, tip_frac=0.0765, root_frac=0.1333, rp=2.1448, drho=PAR['drho'], m=2, tilt=0.8792, psi_b=12.42)
for dD, drp in [(0, 0), (-0.4, 0.2), (0.4, -0.2), (0.4, 0.2), (-0.4, -0.2)]:
    r, _ = evaluate(p['N'], p['Rt'], p['Rt'] - p['tooth_h'], p['tip_frac'], p['root_frac'], p['rp'], p['drho'], p['m'], p['tilt'], p['psi_b'], dD=dD, drp=drp)
    rep['static_dD%+.1f_drp%+.1f' % (dD, drp)] = dict(jams=r['jams'], worst_pa=r['worst_pressure_angle'], swing_quasistatic=r['swing_pp'], ok=r['ok'])
print(json.dumps(rep, indent=1))
import pickle
pickle.dump(dict(body=body, roof=roof, fill_band=fill_band, face_mid=face_mid, I3=I3, backdrop=backdrop, chan=chan,
                 head_band=L['head_band'], face_up=L['face_up'], W=g['W'], pins=g['pins'], rp=g['rp'], P=P, D=g['D']), open(_os.path.join(_HERE, 'layout3.pkl'), 'wb'))
fig, axs = plt.subplots(1, 3, figsize=(16, 8))
for ax, ang in zip(axs, [-PAR['psi_b'], 0, PAR['psi_b']]):
    def draw(geom, **kw):
        for q in (geom.geoms if hasattr(geom, 'geoms') else [geom]):
            if q.is_empty: continue
            x, y = q.exterior.xy; ax.fill(x, y, **kw)
            for h in q.interiors:
                x, y = h.xy; ax.fill(x, y, color='white')
    draw(backdrop, color='#e8e0d0', ec='k', lw=0.5)
    draw(fill_band, color='#c8b8a0'); draw(roof, color='#a08060', alpha=0.45)
    draw(rot(L['head_band'], ang, P), color='#f4a6a6', alpha=0.85)
    draw(rot(L['face_up'], ang, P), color='#f6d365', alpha=0.75)
    draw(rot(I3, ang, P), color='#ff6600', alpha=0.6)
    draw(Point(0, 0).buffer(PAR['R_u']), color='#7fb3ff', alpha=0.35)
    draw(shapely.affinity.rotate(g['W'], 7*ang, origin=(0, 0)), color='#3060c0', alpha=0.7)
    ax.set_aspect('equal'); ax.set_title('head swing %+.1f deg' % ang); ax.grid(alpha=0.3)
plt.savefig(_os.path.join(_HERE, 'layout_swing.png'), dpi=90, bbox_inches='tight')
