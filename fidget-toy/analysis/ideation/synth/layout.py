"""Synthesis check 3: 2-D layout of the closed-back Purr-Bobble core + kitty skin.
Builds every body's outline per Z band with shapely, then checks: finger C-space at the re-centred pin depth,
face vs ball nip gap over the swing, roof bridge spans, wall widths, overall size, small-parts, mass & inertia."""
import sys, json, numpy as np, shapely
import os as _os; _HERE = _os.path.dirname(_os.path.abspath(__file__))  # repo-relative paths
from shapely.geometry import Point, Polygon, LineString, MultiPolygon
from shapely import affinity
from esc_layout import esc_geometry, cspace_check, P_ESC
from esc_layout2 import finger, swept_exclusion

PAR = dict(drho=1.8686, psi_b=12.42,
           ex_margin=0.6,                  # wheel tip circle + margin cut from head band
           L_f=7.0, taper=8.0,              # pallet fingers
           hub_r=7.0, post_r=4.0,
           face_dy=11.0, face_r=16.0,       # face circle centre above P, radius
           leg_w=7.0, leg_end=(11.0, 26.0), leg_root_r=21.0,
           R_u=18.0, R_hole_roof=17.1, nip=1.0,
           gap=0.5, wall=2.5, body_r=21.5, backdrop_margin=2.0)

def rot(geom, deg, origin): return affinity.rotate(geom, deg, origin=origin)

def swept(geom, origin, psi_b, n=33):
    geom = geom.simplify(0.01).buffer(0)
    acc = None
    for a in np.linspace(-psi_b, psi_b, n):
        r = rot(geom, a, origin).buffer(0)
        acc = r if acc is None else acc.union(r).buffer(0)
    return acc

def build(par=PAR):
    g = esc_geometry(drho=par['drho'])
    D = g['D']; P = (0.0, D)
    # ---------- head ----------
    C_h = (0.0, D + par['face_dy'])
    face = Point(C_h).buffer(par['face_r'], 128)
    # ears: rounded triangles at +-34 deg from vertical
    ears = []
    for s in (-1, 1):
        a0, a1, at = np.radians(s*14), np.radians(s*54), np.radians(s*34)
        base0 = np.array(C_h) + par['face_r']*0.92*np.array([np.sin(a0), np.cos(a0)])
        base1 = np.array(C_h) + par['face_r']*0.92*np.array([np.sin(a1), np.cos(a1)])
        tip = np.array(C_h) + (par['face_r'] + 6.5)*np.array([np.sin(at), np.cos(at)])
        ears.append(Polygon([base0, tip, base1]).buffer(2.6, 32).buffer(-0.6, 32))
    face = shapely.union_all([face] + ears)
    hub = Point(P).buffer(par['hub_r'], 64)
    legs = []
    fingers = []
    for c in g['pins']:
        u = c/np.linalg.norm(c)
        root = u*par['leg_root_r']
        end = np.array([np.sign(c[0])*par['leg_end'][0], par['leg_end'][1]])
        legs.append(LineString([root, end]).buffer(par['leg_w']/2, cap_style=1, resolution=32))
        fingers.append(finger(c, g['rp'], par['L_f'], par['taper']))
    wheel_ex = swept_exclusion(g, g['Rt'] + par['ex_margin'], par['psi_b'])
    head_band = shapely.union_all([face, hub] + legs).difference(wheel_ex)
    head_band = shapely.union_all([head_band] + fingers)
    # face (mid/front levels) must avoid the ball (umbrella) rim + nip clearance for every swing angle
    ball_ex_headframe = swept_exclusion(g, par['R_u'] + par['nip'], par['psi_b'])
    face_up = face.difference(ball_ex_headframe)
    # ---------- wheel ----------
    W = g['W']
    umbrella = Point(0, 0).buffer(par['R_u'], 128)
    # ---------- frame ----------
    head_band_swept = swept(head_band, P, par['psi_b'])
    face_up_swept = swept(face_up, P, par['psi_b'])
    # legs region that is NOT under the face (needs a roof) and not under the umbrella
    legs_swept = swept(shapely.union_all(legs + fingers), P, par['psi_b'])
    body = shapely.union_all([Point(0, 0).buffer(par['body_r'], 128),
                              legs_swept.buffer(par['gap'] + par['wall'], 32)])
    body = body.buffer(3, 32).buffer(-3, 32)           # smooth
    roof = body.difference(Point(0, 0).buffer(par['R_hole_roof'], 128))
    channel = legs_swept.buffer(par['gap']).difference(Point(0, 0).buffer(par['R_hole_roof'], 128))
    channel_open = channel.difference(face_up_swept)   # portion of channel not hidden under the face at every pose
    backdrop = shapely.union_all([body, face_up_swept.buffer(par['backdrop_margin'], 64)]).buffer(2, 32).buffer(-2, 32)
    return dict(g=g, P=P, C_h=C_h, face=face, face_up=face_up, hub=hub, legs=legs, fingers=fingers, head_band=head_band,
                wheel_ex=wheel_ex, ball_ex=ball_ex_headframe, W=W, umbrella=umbrella, body=body, roof=roof,
                channel=channel, channel_open=channel_open, backdrop=backdrop, face_up_swept=face_up_swept,
                head_band_swept=head_band_swept)

def max_inscribed_width(poly):
    lo, hi = 0.0, 30.0
    for _ in range(30):
        mid = 0.5*(lo + hi)
        if poly.buffer(-mid).is_empty: hi = mid
        else: lo = mid
    return 2*lo

if __name__ == '__main__':
    L = build()
    g, P = L['g'], L['P']
    rep = {}
    rep['D_pivot'] = round(g['D'], 3); rep['pins'] = [list(np.round(c, 3)) for c in g['pins']]
    rep['pin_arm'] = round(float(np.linalg.norm(g['pins'][1] - np.array(P))), 3)
    rep['rho_pin_centre'] = round(g['rho'], 3)
    # face nip gap to ball rim over swing (face_up already excludes r<R_u+nip in all poses)
    nip = []
    for a in np.linspace(-PAR['psi_b'], PAR['psi_b'], 25):
        f = rot(L['face_up'], a, P)
        nip.append(Point(0, 0).buffer(PAR['R_u'], 256).exterior.distance(f) if not f.intersects(Point(0, 0).buffer(PAR['R_u'])) else -1)
    rep['face_to_ball_rim_gap_min_max'] = (round(min(nip), 3), round(max(nip), 3))
    # roof bridge spans: width of open channel pieces (roof must bridge them)
    ch = L['channel']
    rep['roof_channel_max_inscribed_width'] = round(max_inscribed_width(ch), 2)
    pieces = list(ch.geoms) if ch.geom_type == 'MultiPolygon' else [ch]
    rep['roof_channel_pieces'] = [dict(area=round(p.area, 1), width=round(max_inscribed_width(p), 2)) for p in pieces]
    # frame wall between channel and outer outline
    rep['min_wall_channel_to_outline'] = round(L['body'].exterior.distance(L['channel'].buffer(0)), 2) if True else None
    bx = L['backdrop'].bounds
    rep['overall_bbox_xy'] = [round(v, 1) for v in bx]; rep['overall_W_H'] = (round(bx[2] - bx[0], 1), round(bx[3] - bx[1], 1))
    rep['head_band_area'] = round(L['head_band'].area, 0); rep['face_up_area'] = round(L['face_up'].area, 0)
    # mass/inertia of head (PLA 1.24 g/cm3, solid) about P: band 3.0-7.4 (4.4) + face_up 7.4-15.4 (8.0)
    def mom(poly, t):
        # sample area moments on grid
        minx, miny, maxx, maxy = poly.bounds; h = 0.25
        xs = np.arange(minx, maxx, h) + h/2; ys = np.arange(miny, maxy, h) + h/2
        X, Y = np.meshgrid(xs, ys); ins = shapely.contains_xy(poly, X.ravel(), Y.ravel())
        x = X.ravel()[ins]; y = Y.ravel()[ins] - P[1]
        A = ins.sum()*h*h
        return A*t, (x*0).sum() + (y.sum()*h*h*t), ((x**2 + y**2).sum()*h*h*t)
    v1, my1, j1 = mom(L['head_band'], 4.4); v2, my2, j2 = mom(L['face_up'], 8.0)
    rho = 1.24e-3  # g/mm3
    for fill, lab in [(1.0, 'solid'), (0.55, 'typ_3walls_25pct')]:
        m = (v1 + v2)*rho*fill; I = (j1 + j2)*rho*fill*1e-9   # g*mm2 -> kg m2 : 1e-3*1e-6
        rep['head_mass_g_' + lab] = round(m, 1); rep['head_I_kgm2_' + lab] = float('%.2e' % I)
    rep['head_com_above_P_mm'] = round((my1 + my2)/(v1 + v2), 1)
    # small parts: min bounding width of each body
    def minw(poly):
        best = 1e9
        for a in range(0, 180, 2):
            b = rot(poly, a, (0, 0)).bounds; best = min(best, b[2] - b[0])
        return best
    rep['head_min_width'] = round(minw(L['head_band'].union(L['face_up'])), 1)
    rep['wheel_min_width'] = round(2*PAR['R_u'], 1)
    print(json.dumps(rep, indent=1))
    import pickle; pickle.dump({k: v for k, v in L.items() if k != 'g'}, open(_os.path.join(_HERE, 'layout.pkl'), 'wb'))
