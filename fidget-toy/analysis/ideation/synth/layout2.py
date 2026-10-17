"""Layout v2: apply the final Z-band rules, compute I3 overlap, roof spans, wall widths, and draw a top view."""
import json, numpy as np, shapely
import os as _os; _HERE = _os.path.dirname(_os.path.abspath(__file__))  # repo-relative paths
from shapely.geometry import Point, Polygon, LineString
from shapely import affinity
from layout import build, PAR, swept, max_inscribed_width, rot
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt

L = build(); g = L['g']; P = L['P']
O = Point(0, 0)
body = L['body']
roof = body.difference(O.buffer(PAR['R_hole_roof'], 128)).difference(Point(P).buffer(PAR['hub_r'] + PAR['gap'], 64))
fill_band = body.difference(L['head_band_swept'].buffer(PAR['gap'], 32)).difference(O.buffer(g['Rt'] + 0.5, 128))
roof_sw = swept(roof.buffer(PAR['gap'], 16), P, PAR['psi_b'])  # roof in head frame, all poses
face_mid = L['face_up'].difference(roof_sw)
I3 = L['face_up'].intersection(roof_sw)                 # front level printed over roof (ribs)
# channel covered by roof = swept legs/fingers band outside the ball hole (bridged with 1.0 clearance)
chan = L['channel']
rep = {}
rep['I3_face_over_roof_area_mm2'] = round(I3.area, 1)
rep['face_mid_area'] = round(face_mid.area, 1)
rep['roof_area'] = round(roof.area, 1)
rep['roof_min_width'] = round(max_inscribed_width(roof), 2)
# narrowest frame material in band level: erode test
def min_feature(poly, lim=1.6):
    # fraction of area lost when opening by lim/2 -> thin parts
    op = poly.buffer(-lim/2).buffer(lim/2)
    return round(poly.difference(op).area, 1)
rep['band_fill_area_thinner_than_1.6mm'] = min_feature(fill_band)
rep['roof_area_thinner_than_2.0mm'] = min_feature(roof, 2.0)
# head band thin features
rep['head_band_area_thinner_than_2.0mm'] = min_feature(L['head_band'], 2.0)
# bridges: roof must span channel pieces; channel width
rep['channel_widths'] = [round(max_inscribed_width(p), 2) for p in (chan.geoms if chan.geom_type == 'MultiPolygon' else [chan])]
# minimal gap between moving head band (any pose) and frame band fill = by construction 0.5; verify numerically
mins = []
for a in np.linspace(-PAR['psi_b'], PAR['psi_b'], 13):
    hb = rot(L['head_band'], a, P)
    mins.append(hb.distance(fill_band) if not hb.intersects(fill_band) else -hb.intersection(fill_band).area)
rep['head_band_to_frame_band_gap_min'] = round(min(mins), 3)
mins = []
for a in np.linspace(-PAR['psi_b'], PAR['psi_b'], 13):
    fm = rot(face_mid, a, P)
    mins.append(fm.distance(roof) if not fm.intersects(roof) else -fm.intersection(roof).area)
rep['face_mid_to_roof_gap_min'] = round(min(mins), 3)
print(json.dumps(rep, indent=1))

fig, ax = plt.subplots(figsize=(7, 10))
def draw(geom, **kw):
    gs = geom.geoms if hasattr(geom, 'geoms') else [geom]
    for q in gs:
        if q.is_empty: continue
        x, y = q.exterior.xy; ax.fill(x, y, **kw)
        for h in q.interiors:
            x, y = h.xy; ax.fill(x, y, color='white')
draw(L['backdrop'], color='#e8e0d0', ec='k', lw=0.5)
draw(fill_band, color='#c8b8a0', alpha=0.9)
draw(roof, color='#a08060', alpha=0.5)
draw(L['head_band'], color='#f4a6a6', alpha=0.8)
draw(L['face_up'], color='#f6d365', alpha=0.7)
draw(I3, color='#ff6600', alpha=0.6)
draw(Point(0, 0).buffer(PAR['R_u']), color='#7fb3ff', alpha=0.35)
draw(g['W'], color='#3060c0', alpha=0.7)
for c in g['pins']: draw(Point(c).buffer(g['rp']), color='k')
ax.plot([0], [0], 'k+'); ax.plot([P[0]], [P[1]], 'r+')
ax.set_aspect('equal'); ax.grid(alpha=0.3)
ax.set_title('Purr-Bobble core: top view (print pose psi=0)\nbeige=backplate, tan=frame band fill, brown=roof, pink=head band, yellow=face(up), orange=I3, blue=wheel/umbrella')
plt.savefig(_os.path.join(_HERE, 'layout_top.png'), dpi=110, bbox_inches='tight')
