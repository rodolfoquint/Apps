"""Put the mechanism inside a sculpted mesh (round 5: the owner's Meshy kitty, sculpt/Yarn_Cuddle_Kitty_Meshy_AI.3mf).

The sculpt is one solid relief (back on z = 0, face up).  It is scaled so that its yarn ball is the 36 mm escape
wheel (ball centre on O) and split into the three print-in-place bodies so that, at rest, the outside of the toy is
the sculpt's own surface everywhere, cut only by thin seams (see ``integrate``):

* HEAD  = the whole sculpted head (ears and bow included), each point from its own floor up to the sculpt surface,
  plus the mechanism's head band (hub, legs, pallet fingers) underneath.
* WHEEL = the escape wheel (teeth, a small umbrella r 15 that hides under the yarn ball) + the sculpt's ball centre
  inside r <= ``cap_r`` (the spinning cap, with a finger dish) + skid rings on the umbrella top.
* FRAME = the rest of the sculpt (cushion, body, arms, paws, feet, tail, and the ball's outer strands as a static
  ring over the umbrella) minus the head's and the wheel's swept envelopes, plus the fixed mechanism parts: back
  ribs, the two posts and the stop pads.

Nothing of the mechanism stands above the sculpt's surface.  Where the head swings it opens a shallow recess in the
cushion around it (its thin edge needs a floor clearance), and shallow pockets in the chest under its chin corners.
"""
from __future__ import annotations

import functools
import math
import re
from pathlib import Path

import numpy as np
from manifold3d import CrossSection, Manifold, Mesh, OpType

from . import geom2d as g2
from .sweep import swept

REPO = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------------------------ loading
def read_3mf_mesh(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Vertices / triangles of the first object of a (single-object, core-spec) 3MF file."""
    import zipfile
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".model"))
        txt = z.read(name).decode("utf-8")
    v = np.array(re.findall(r'<vertex x="([-0-9.eE+]+)" y="([-0-9.eE+]+)" z="([-0-9.eE+]+)"', txt), dtype=np.float64)
    t = np.array(re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"', txt), dtype=np.int64)
    return v, t


@functools.lru_cache(maxsize=4)
def load_sculpt(path: str, ball_c: tuple, scale: float) -> Manifold:
    """The sculpt face-up (back on z = 0), its ball centre ``ball_c`` (face-up frame, x centred) moved to O and
    scaled uniformly by ``scale`` about O.  Cached as .npz next to the source (ignored by git)."""
    src = Path(path)
    cache = src.with_suffix(".faceup.npz")
    if cache.exists() and cache.stat().st_mtime >= src.stat().st_mtime:
        d = np.load(cache)
        v, f = d["v"], d["f"]
    else:
        v, f = read_3mf_mesh(src)
        m = Manifold(Mesh(vert_properties=np.ascontiguousarray(v, np.float32), tri_verts=np.ascontiguousarray(f, np.uint32)))
        m = m.rotate((-90.0, 0.0, 0.0))
        bb = m.bounding_box()
        m = m.translate((-(bb[0] + bb[3]) / 2.0, -bb[1], -bb[2]))
        mesh = m.to_mesh()
        v = np.array(np.asarray(mesh.vert_properties)[:, :3], dtype=np.float32, order="C", copy=True)
        f = np.array(np.asarray(mesh.tri_verts), dtype=np.uint32, order="C", copy=True)
        np.savez_compressed(cache, v=v, f=f)
    m = Manifold(Mesh(vert_properties=np.ascontiguousarray(v, np.float32), tri_verts=np.ascontiguousarray(f, np.uint32)))
    m = m.translate((-ball_c[0], -ball_c[1], 0.0)).scale((scale, scale, scale))
    return clean_sculpt(m)


def clean_sculpt(m: Manifold) -> Manifold:
    """AI-generated meshes carry small defects: keep the main shell only (drops zero-volume slivers and fills
    internal voids, which come out as separate inverted shells), then weld every point where two parts of the
    surface touch (a pinch vertex: fine in memory, non-manifold once written to STL) with a 0.06 mm sphere."""
    main = max(m.decompose(), key=lambda q: q.volume())
    # the back is printed on the bed: fill its shallow dips (up to ~0.3 mm on the owner's model) so it is flat
    main = main + main.slice(0.3).extrude(0.3)
    return weld_pinches(main)


def weld_pinches(m: Manifold, r: float = 0.06, iters: int = 16) -> Manifold:
    """Weld pinch vertices (two parts of the surface touching at a point or along an edge) with tiny spheres, or
    thin vertical capsules where they line up along a vertical edge; keep the main shell.
    r 0.06 is far below every designed clearance (>= 0.35)."""
    from .solids import pinch_vertices
    for i in range(iters):
        pv = pinch_vertices(m)
        if not len(pv):
            break
        pts = np.unique(np.round(pv, 4), axis=0)
        ri = min(r * (1.0 + 0.25 * i), 0.15)   # a weld landing tangent to another surface makes a new pinch: vary r
        jit = 0.013 * ((i * 7) % 5 - 2)       # ... and shift the centres a little (deterministic)
        # carve dimples (never add material: a bump would eat into the 0.41 / 0.5 clearances to the other bodies);
        # only the last few rounds may add, as a last resort
        op = OpType.Subtract if i < iters - 4 else (OpType.Add if i % 2 == 0 else OpType.Subtract)
        tools = []
        keys = np.round(pts[:, :2], 2)
        for key in np.unique(keys, axis=0):
            grp = pts[np.all(keys == key, axis=1)]
            grp = grp[np.argsort(grp[:, 2])]
            x, y = map(float, grp[:, :2].mean(axis=0) + jit)
            # runs of points along a vertical pinch edge (consecutive z <= 0.25 apart: the layer pitch) get one
            # capsule each (spheres would only move the pinch along the edge); never bridge separate runs
            runs, cur = [], [grp[0]]
            for q in grp[1:]:
                if q[2] - cur[-1][2] <= 0.25:
                    cur.append(q)
                else:
                    runs.append(cur)
                    cur = [q]
            runs.append(cur)
            for run in runs:
                z0, z1 = float(run[0][2]), float(run[-1][2])
                if len(run) > 1 and z1 - z0 > 1e-3:
                    tools.append(Manifold.hull(Manifold.batch_boolean(
                        [Manifold.sphere(ri, 8).translate((x, y, z0)), Manifold.sphere(ri, 8).translate((x, y, z1))],
                        OpType.Add)))
                else:
                    tools += [Manifold.sphere(ri, 8).translate(tuple(map(float, q + jit))) for q in run]
        m = Manifold.batch_boolean([m] + tools, op)
        m = max(m.decompose(), key=lambda q: q.volume())
    return m


# ------------------------------------------------------------------------------------------------ envelopes
FLOOR_OFFSET = 0.037   # head floor levels: z_band0 + 0.4 + k 0.2 + this (fewest sculpt flats within 6 um, kitty)
GRID_OFFSET = 0.0137    # envelope layer boundaries sit off every round height: the sculpt has broad flats (e.g. the
                        # cushion at z 5.0 once scaled) and the mechanism its levels; a layer face coplanar with
                        # either leaves pinch vertices


def _layers(z0: float, z1: float, h: float) -> list[tuple[float, float]]:
    z0 = math.floor((z0 - GRID_OFFSET) / h) * h + GRID_OFFSET
    n = max(1, int(math.ceil((z1 - z0) / h)))
    return [(z0 + k * h, z0 + (k + 1) * h) for k in range(n)]


def _slab_outline(m: Manifold, za: float, zb: float) -> CrossSection:
    secs = [m.slice(float(z)) for z in (za + 0.01, 0.5 * (za + zb), zb - 0.01)]
    return g2.union([s for s in secs if not s.is_empty()]).simplify(0.005)


def stack(slabs: list[tuple[float, float, CrossSection]], gap_z: float) -> Manifold:
    """The slabs dilated by gap_z in Z, as stacked prisms that never overlap: each layer takes the union of the
    outlines within +-gap_z and is extruded over its own height only (overlapping prisms with nearly identical walls
    would leave pinch vertices); the first / last layer extends gap_z down / up."""
    slabs = [(za, zb, cs) for za, zb, cs in slabs if cs is not None and not cs.is_empty()]
    if not slabs:
        return Manifold()
    parts = []
    for k, (za, zb, _) in enumerate(slabs):
        near = [cs for zc, zd, cs in slabs if zc < zb + gap_z - 1e-9 and zd > za - gap_z + 1e-9]
        cs = near[0] if len(near) == 1 else g2.union(near)
        z0 = za - (gap_z if k == 0 else 0.0)
        z1 = zb + (gap_z if k == len(slabs) - 1 else 0.0)
        parts.append(cs.extrude(z1 - z0).translate((0.0, 0.0, z0)))
    return Manifold.batch_boolean(parts, _ADD) if len(parts) > 1 else parts[0]


from manifold3d import OpType  # noqa: E402
_ADD = OpType.Add


def nested_stack(slabs: list[tuple[float, float, CrossSection]], eps: float, grows_up: bool) -> Manifold:
    """Prisms (z0, z1, section) stacked bottom to top whose sections only grow (grows_up) or only shrink upward.
    Each section is grown by eps (2 um) times its rank from the small end, so every section strictly contains its
    smaller neighbour wherever their outlines coincide (shared walls leave pinch vertices); equal consecutive
    sections are merged first."""
    merged = []
    for z0, z1, cs in slabs:
        if cs is None or z1 <= z0:
            continue
        if merged and abs(merged[-1][1] - z0) < 1e-9:
            prev = merged[-1][2]
            if abs(g2.difference(prev, cs).area()) + abs(g2.difference(cs, prev).area()) < 1e-6:
                merged[-1] = (merged[-1][0], z1, prev)
                continue
        merged.append((z0, z1, cs))
    n = len(merged)
    parts = []
    for k, (z0, z1, cs) in enumerate(merged):
        rank = k if grows_up else n - 1 - k
        sec = g2.grow(cs, eps * rank, 0.002) if rank else cs
        if not sec.is_empty():
            parts.append(sec.extrude(z1 - z0).translate((0.0, 0.0, z0)))
    return Manifold.batch_boolean(parts, _ADD) if len(parts) > 1 else (parts[0] if parts else Manifold())


def stack_sections(slabs: list[tuple[float, float, CrossSection]], eps: float) -> Manifold:
    """Prisms (z0, z1, section) stacked bottom to top, consecutive equal sections merged.  Every other prism is
    grown by eps (2 um): where two neighbours share part of their outline the walls would otherwise coincide and
    leave pinch vertices (the 2 um steps are far below print resolution)."""
    merged = []
    for z0, z1, cs in slabs:
        if cs is None or cs.is_empty() or z1 <= z0:
            continue
        if merged and abs(merged[-1][1] - z0) < 1e-9:
            prev = merged[-1][2]
            if abs(g2.difference(prev, cs).area()) + abs(g2.difference(cs, prev).area()) < 1e-6:
                merged[-1] = (merged[-1][0], z1, prev)
                continue
        merged.append((z0, z1, cs))
    parts = []
    for k, (z0, z1, cs) in enumerate(merged):
        sec = g2.grow(cs, eps, 0.001) if k % 2 else cs
        parts.append(sec.extrude(z1 - z0).translate((0.0, 0.0, z0)))
    return Manifold.batch_boolean(parts, _ADD) if len(parts) > 1 else (parts[0] if parts else Manifold())


def head_envelope(head: Manifold, P, psi_b: float, n: int, gap_xy: float, gap_z: float, h: float = 0.2) -> Manifold:
    """Region the head sweeps over +-psi_b about P (per layer), grown gap_xy, dilated gap_z."""
    bb = head.bounding_box()
    slabs = []
    for za, zb in _layers(bb[2], bb[5], h):
        cs = _slab_outline(head, za, zb)
        if cs.is_empty():
            continue
        sw = swept(cs, P, psi_b, n, allowance=0.0)
        # (concave cusps of the swept outline filled r 0.3: a cusp at the same place in every layer leaves a
        # knife-edge of sculpt that pinches between layers)
        slabs.append((za, zb, g2.closing(g2.grow(sw, gap_xy, 0.01), 0.3, 0.01)))
    return stack(slabs, gap_z)


def wheel_envelope(wheel: Manifold, gap_xy: float, gap_z: float, h: float = 0.2, nseg: int = 360,
                   z_floor: float | None = None) -> Manifold:
    """Region the wheel sweeps turning about O (per layer: the disc of its largest radius), grown, dilated.
    z_floor: the lowest prism reaches down to there (a cavity with straight walls down to the plate)."""
    bb = wheel.bounding_box()
    slabs = []
    for za, zb in _layers(bb[2], bb[5], h):
        cs = _slab_outline(wheel, za, zb)
        if cs.is_empty():
            continue
        pts = np.vstack([np.asarray(c, float) for c in cs.to_polygons() if len(c)])
        r = round(float(np.max(np.hypot(pts[:, 0], pts[:, 1]))) + gap_xy + 0.005, 2)   # quantised: equal layers
        slabs.append((za, zb, r))                                                       # share identical walls
    circles = {r: CrossSection.circle(r / math.cos(math.pi / nseg), nseg) for r in {q[2] for q in slabs}}
    # per layer, the largest radius within +-gap_z (dilation), then merge equal neighbours into one prism
    rad = [max(r2 for zc, zd, r2 in slabs if zc < zb + gap_z - 1e-9 and zd > za - gap_z + 1e-9) for za, zb, _ in slabs]
    parts, k = [], 0
    while k < len(slabs):
        j = k
        while j + 1 < len(slabs) and rad[j + 1] == rad[k]:
            j += 1
        z0 = (min(z_floor, slabs[k][0] - gap_z) if z_floor is not None else slabs[k][0] - gap_z) if k == 0 \
            else slabs[k][0]
        z1 = slabs[j][1] + (gap_z if j == len(slabs) - 1 else 0.0)
        parts.append(circles[rad[k]].extrude(z1 - z0).translate((0.0, 0.0, z0)))
        k = j + 1
    return Manifold.batch_boolean(parts, _ADD) if len(parts) > 1 else parts[0]


# ------------------------------------------------------------------------------------------------ integration
def integrate(M, verbose: bool = False) -> dict:
    """Replace M.frame / M.head / M.wheel by the sculpt-integrated bodies (in place).  Returns build info.

    At rest the outside of the three bodies is the sculpt's own surface, split by thin seams:
    * HEAD  = the sculpt's whole head (skin.head_blob(): ears and bow included) from its floor up to the sculpt
      surface, plus the mechanism's head band (hub, legs, pallet fingers; z 3.0-7.4) underneath.  The floor is
      float_z (just under the cushion around the head) where the head swings over the cushion, chin_floor where it
      swings over the tall chest / paws (so the pockets it opens there stay shallow and the chest keeps a cover
      over the legs), and the band itself under the face.  Legs whose sweep passes under thin sculpt are lowered
      to leg_low_top so that sculpt still covers them.  The head yields to the stop pads and never swings over the
      yarn ball.
    * WHEEL = the escape wheel + skid rings on the umbrella top + the sculpt's ball centre (cap) with a finger dish.
    * FRAME = the sculpt minus the head's and the wheel's swept envelopes (grown by the design gaps), down to the
      plate top (z 2.0) under the band and wheel, plus the mechanism's fixed parts: back ribs, the two posts and the
      stop pads with their backing.
    """
    import time
    from . import solids
    t0 = time.time()
    p, S, sk = M.params, M.sections, M.skin
    K = sk.sculpt()
    P = tuple(p.P)
    O = (0.0, 0.0)
    # the variants' looser gaps apply here too (loose: gap_xy 0.55, the floating bodies lifted z_lift)
    zl = p.z_lift
    gxy, gz = max(sk.gap_xy, p.gap_xy), sk.gap_z + zl
    EPS = solids.EPS
    info = {}

    def log(msg):
        if verbose:
            print(f"  [sculpt {time.time() - t0:6.1f}s] {msg}", flush=True)

    def ext(cs, z0, z1):
        return cs.extrude(z1 - z0).translate((0.0, 0.0, z0)) if not cs.is_empty() else Manifold()

    # ---------------- wheel: escape wheel + skid rings on the umbrella top + sculpted cap with a finger dish
    zt = p.z_umb_top + zl                     # (M.wheel is already lifted by z_lift)
    rings = []
    for r in np.arange(sk.cap_r + sk.cap_gap + 1.2, p.R_u - 1.0 + 1e-6, sk.ring_pitch):
        rings.append(g2.difference(g2.circle(O, r + p.rib_w / 2, 0.01), g2.circle(O, r - p.rib_w / 2, 0.01)))
    ribs = ext(g2.union(rings), zt - EPS, zt + p.rib_h) if rings else Manifold()
    cap2d = CrossSection.circle(sk.cap_r, 256)
    cap = K ^ ext(cap2d, zt - EPS, 60.0)
    cap = cap + ext(cap2d, zt - EPS, zt + sk.cap_min_h)
    wheel = solids.union3([M.wheel, ribs, cap])
    # finger dish in the cap: a sphere cut, opening sk.dish_d at (r_k, 0), sk.dish_depth below the cap's surface
    cxy = (p.r_k, 0.0)                        # (the drive lever arm in the V4 dynamics, too)
    ztop = _top_z(K, cxy, sk.dish_d / 2.0)
    a, dep = sk.dish_d / 2.0, sk.dish_depth
    rs = (a * a + dep * dep) / (2 * dep)
    dish = Manifold.sphere(rs, 96).translate((cxy[0], cxy[1], ztop - dep + rs))
    wheel = solids.finish(weld_pinches(wheel - dish), p, "wheel")
    log("wheel")

    # ---------------- frame parts the mechanism needs: stop pads (with backing), posts, back ribs
    HB = sk.head_blob()
    C = HB                                    # the part of the head's footprint it covers at every pose
    for a_ in np.linspace(-p.psi_b, p.psi_b, 41):
        C = g2.intersect(C, g2.rot_about(HB, float(a_), P))
    C = g2.grow(C, -gxy, 0.01)
    pad_low_top = sk.float_z - gz - 0.05      # pads under the head: below its lowest float floor
    pads_low, pads_full = [], []
    for pad in g2.pieces(S["stoppads2d"]):
        blk = g2.union([pad, g2.intersect(S["fill2d"], g2.grow(pad, sk.pad_back, 0.01))])
        blk = g2.clean(g2.drop_small(g2.opening(blk, 0.4, 0.005), 0.5), "solid")
        # pads under the head's float floor stop at float_z - gz (flush with the moat floor when the head swings
        # away); pads below the chin keep the full band height (the chest covers them)
        under_head = g2.intersect(pad, HB).area() > 0.05 * pad.area()
        top = pad_low_top if under_head else p.z_band1
        (pads_low if under_head else pads_full).append(ext(blk, p.z_bp - EPS, top))
    pads_full = solids.union3(pads_full) if pads_full else Manifold()
    pads = solids.union3(pads_low + [pads_full])
    posts = solids.union3([solids.post(p, O), solids.post(p, P)])
    log("pads / posts")

    # ---------------- head
    # the head band: its functional parts (hub, legs, pallet fingers) and, of the face part, only what the head
    # always covers (inside it the head body reaches the band level anyway; beyond it the band would sweep a slot
    # down to the plate through the cushion around the head)
    mech2d = g2.union([S["hub2d"], S["legs2d"], S["fingers2d"]])
    band2d = g2.intersect(S["headband2d"], g2.union([g2.grow(C, -0.5, 0.01), g2.grow(mech2d, 0.05, 0.01)]))
    band2d = g2.clean(g2.opening(band2d, 0.5, 0.005), "solid")
    band2d = max(g2.pieces(band2d), key=lambda q: q.area())
    # under the band's sweep and the wheel the frame is cut down to the plate top, with the back ribs inside
    # (the band's own cavity is the first slab of its envelope below, which starts at the plate top)
    sw_band = g2.grow(swept(band2d, P, p.psi_b, p.n_sweep, allowance=0.05), gxy, 0.01)
    low2d_cav = g2.union([sw_band, g2.circle(O, p.wheel_ex_r, 0.01)])
    ribs_back = ext(g2.intersect(S["ribs_back2d"], g2.grow(low2d_cav, -0.3, 0.01)), p.z_bp - EPS, p.z_bp + p.rib_h)
    # legs lowered where their sweep passes under sculpt thinner than cover_min (outside the head and the ball)
    foot = K.slice(0.3)
    TV = TopView(K, 2.5, 0.1)                  # top-view height regions (undercut-aware)
    thin = g2.difference(foot, TV.at(sk.cover_min, up=True), g2.grow(HB, 0.3, 0.01), g2.circle(O, p.R_u - 0.5, 0.01))
    # (any band part whose sweep passes over thin sculpt, also the parts of the legs inside the head blob that swing
    # out below the neck line; the always-covered face part never leaves the blob)
    low2d = g2.drop_small(g2.intersect(band2d, swept(g2.grow(thin, gxy, 0.01), P, p.psi_b, p.n_sweep, allowance=0.05)),
                          0.2)
    # the frame over the lowered legs keeps >= cover_t above their swept envelope; where the sculpt is thinner than
    # that (cushion valleys beside the chin) a low boss fills it up to cover_t (the head's floors clear it too)
    cov_top = sk.leg_low_top + zl + sk.gap_z + sk.cover_t
    sw_low = g2.difference(g2.grow(swept(low2d, P, p.psi_b, p.n_sweep, allowance=0.05), gxy, 0.01),
                           g2.grow(HB, 0.3, 0.01)) if not low2d.is_empty() else CrossSection()
    boss2d = g2.drop_small(g2.difference(sw_low, TV.at(cov_top, up=True)), 0.05) if not sw_low.is_empty() \
        else CrossSection()
    Ks = K
    if not boss2d.is_empty():
        boss2d = g2.intersect(g2.closing(g2.grow(boss2d, 0.4, 0.01), 0.5, 0.01), g2.grow(foot, -0.5, 0.01))
        Ks = K + ext(boss2d, 0.0, cov_top)
        TV = TopView(Ks, 2.5, 0.1)
    info["cover_boss_mm2"] = round(boss2d.area(), 1)
    # stacked slabs, each section strictly inside the one below (eps_stack): the full band up to leg_low_top, the
    # band without the lowered legs up to the pallet top, then without the pallet fingers (they run under the
    # umbrella) up to the band top.  (A cut instead would leave walls meeting the band's outline at single
    # points: pinch vertices.)
    eps = p.eps_stack
    keep = g2.clean(g2.grow(g2.difference(band2d, low2d), -eps, 0.001), "solid")
    top = g2.clean(g2.grow(g2.difference(keep, g2.grow(S["wheelex2d"], 0.05, 0.005)), -eps, 0.001), "solid")
    band = solids.union3([ext(g2.clean(band2d, "solid"), p.z_band0, sk.leg_low_top), ext(keep, sk.leg_low_top, p.z_pallet_top),
                          ext(top, p.z_pallet_top, p.z_band1)])
    # head body: the sculpt over the head blob, each point from its own floor up.  A head point's floor clears
    # (by gap_z) everything static it ever swings over: the sculpt outside the head (cushion, chest, paws: they keep
    # their surface), the stop pads, the cover over the legs (>= cover_min under the chest), and float_z over the
    # part of the head's own footprint that the head uncovers when it swings.  Points that only ever swing over
    # the always-covered middle of the head go down to the band (z_band0): mass high up in the head.  The floor
    # is capped t_min under the point's own surface (the sculpt there is cut down instead: a shallow pocket).
    def swp(cs):
        """Swept envelope for the cosmetic floors / frame cut: 41 poses on a 0.01-simplified outline (chord error
        < 0.001 mm at r 30, covered by the 0.05 allowance)."""
        from .sweep import _sweep
        return _sweep(cs.simplify(0.01), P, np.linspace(-p.psi_b, p.psi_b, 41), 0.05, 0.001)

    # the head body's outline: 0.1 inside the blob (the blob's outline is made of the sculpt's own slice contours: a
    # prism wall on them would touch the sculpt surface tangentially, and one outside them would take a sliver of
    # cushion whose low floor would cut a recess all around the head as it swings)
    HBb = g2.clean(g2.difference(g2.grow(HB, -0.1, 0.01), ball_keep_2d(p, P, sk, swept)), "solid")
    partial = g2.difference(HBb, C)                         # head footprint uncovered at some pose
    out = g2.grow(HB, 0.3, 0.01)
    legs_cov = g2.difference(swept(g2.difference(keep, g2.grow(HB, -0.3, 0.01)), P, p.psi_b, p.n_sweep,
                                   allowance=0.05), out)    # full-height legs outside the head
    pads_low2d = g2.union([g2.pieces(S["stoppads2d"])[k] for k in range(len(g2.pieces(S["stoppads2d"])))
                           if g2.intersect(g2.pieces(S["stoppads2d"])[k], HB).area() > 0])
    pads_full2d = g2.difference(S["stoppads2d"], pads_low2d)
    hard = [(sk.cover_min + gz, legs_cov), (cov_top + gz, sw_low), (p.z_band1 + gz, g2.grow(pads_full2d, sk.pad_back, 0.01)),
            (pad_low_top + gz, g2.grow(pads_low2d, sk.pad_back, 0.01))]
    # (floor levels sit off the sculpt's flats - its cushion top is flat at 5.60-5.62 - by FLOOR_OFFSET: a floor
    # coplanar with a flat leaves thousands of pinch vertices)
    levels = [p.z_band0 + zl] + list(np.round(np.arange(p.z_band0 + 2 * sk.floor_step, sk.float_top + 1e-6,
                                                   sk.floor_step) + FLOOR_OFFSET, 4))
    reach = g2.grow(swp(HBb), gxy + 0.2, 0.01)               # all the head ever swings over
    R = {}                                                    # level -> head points whose floor is >= level
    for k, L in enumerate(levels[1:]):
        Lp = levels[k]                                        # floors round UP to a level: a point needing a floor
        soft = [g2.intersect(g2.difference(TV.at(Lp - gz + 1e-3, up=False), out), reach)]    # above Lp gets L
        if Lp < sk.float_z - 1e-9:
            soft.append(partial)
        Rs = g2.intersect(HBb, swp(g2.grow(g2.union(soft), gxy, 0.01)), TV.at(L + sk.t_min, up=True))
        hs = [cs for zt_, cs in hard if zt_ > Lp + 1e-9 and not cs.is_empty()]
        Rh = g2.intersect(HBb, swp(g2.grow(g2.union(hs), gxy, 0.01))) if hs else CrossSection()
        # (closed r 0.25: no pinholes / slits between the parts, which would leave needles of head down to z_band0)
        R[L] = g2.clean(g2.intersect(g2.closing(g2.drop_small(g2.union([Rs, Rh]), 0.05), 0.25, 0.01), HBb), "solid")
        if k and not g2.difference(R[L], R[levels[k]]).is_empty():
            R[L] = g2.clean(g2.intersect(R[L], R[levels[k]]), "solid")      # nested: floors only rise
    log(f"head floors: {len(levels) - 1} levels")
    # no slivers of a lower floor (they would be lost when the outlines are simplified for the sweep, and the frame
    # cut would miss them): the head points present below each level are opened by 0.1 (their floor rises instead)
    for L in levels[1:]:
        R[L] = g2.clean(g2.difference(HBb, g2.opening(g2.difference(HBb, R[L]), 0.1, 0.005)), "solid")
    # floors as a stacked cut (sections shrink upward: nested), and the matching swept envelope for the frame
    cut_slabs, env_slabs = [], []
    ring = g2.difference(g2.grow(HBb, 2.0, 0.01), g2.grow(HBb, -0.05, 0.01))   # (the cut reaches past the body's
    for k, L in enumerate(levels[1:]):                                          # outline: no walls along it)
        L0 = levels[k]
        cut_slabs.append((L0 if k else p.z_band0 - 1.0, L, g2.union([R[L], ring])))
        env_slabs.append((L0 - gz, L - gz, g2.grow(swp(g2.difference(HBb, R[L])), gxy, 0.01)))
    env_slabs.append((levels[-1] - gz, 60.0, g2.grow(swp(HBb), gxy, 0.01)))
    log("head floor sweeps")
    cut = nested_stack(cut_slabs, p.eps_stack, grows_up=False)
    log("head floor cut stack")
    body = (K ^ ext(HBb, p.z_band0 + zl, 60.0)) - cut
    log("head body")
    # the band and its bore are built at nominal z and lifted with the floating bodies (solids.bore works in the
    # body's local z); the body above keeps its floors (they already clear the frame by gap_z)
    band = band - solids.bore(p, P)
    if zl:
        band = band.translate((0.0, 0.0, zl))
    head = band + (body - solids.bore(p, P).translate((0.0, 0.0, zl)))
    info["head_pinches_before_weld"] = len(solids.pinch_vertices(head))
    head = solids.finish(weld_pinches(head), p, "head")
    info.update({"head_blob_mm2": round(HB.area(), 1), "legs_lowered_mm2": round(low2d.area(), 1),
                 "head_always_covered_mm2": round(C.area(), 1),
                 "floor_area_mm2": {float(L): round(R[L].area(), 1) for L in levels[1:]}})
    log("head")

    # ---------------- frame: the sculpt minus the moving envelopes, plus the mechanism's fixed parts
    sw = lambda cs: g2.grow(swept(cs, P, p.psi_b, p.n_sweep, allowance=0.05), gxy, 0.01)    # (band: functional)
    z_fl = sk.leg_low_top + sk.gap_z           # (the band is lifted by zl itself)
    band_env = [(p.z_bp, z_fl + zl, sw_band), (z_fl + zl, p.z_band1 + zl + sk.gap_z, sw(keep))]
    Eh = solids.union3([stack_sections(band_env, p.eps_stack), nested_stack(env_slabs, p.eps_stack, grows_up=True)])
    log("head envelope")
    # the wheel's envelope: per layer below the umbrella top, exact above it (layer rounding would leave the
    # static ring 0.7 above the skid rings instead of gap_z): the umbrella disc to its top + gap_z, the skid rings
    # to their tops + gap_z, the cap with its radial gap
    zc = zt - 0.25
    Ew = wheel_envelope(wheel ^ ext(CrossSection.circle(40.0, 64), -1.0, zc), gxy, gz, z_floor=p.z_bp)
    r_ring = (max(np.arange(sk.cap_r + sk.cap_gap + 1.2, p.R_u - 1.0 + 1e-6, sk.ring_pitch)) + p.rib_w / 2
              if rings else sk.cap_r)
    Ew = solids.union3([Ew, ext(g2.circle(O, p.R_u + gxy, 0.005), zc - 0.05, zt + gz),
                        ext(g2.circle(O, r_ring + gxy, 0.005), zt + gz - 0.05, zt + p.rib_h + gz),
                        ext(g2.circle(O, sk.cap_r + sk.cap_gap, 0.005), zt + p.rib_h + gz - 0.05, 60.0)])
    log("wheel envelope")
    # under the band and the wheel the cavities reach down to the plate top (back ribs added again below)
    Kf = Ks - solids.union3([Eh, Ew])
    frame = solids.union3([Kf, ribs_back, posts, pads])
    info["frame_pinches_before_weld"] = len(solids.pinch_vertices(frame))
    frame = solids.finish(weld_pinches(frame), p, "frame")
    log("frame")
    M.frame, M.head, M.wheel = frame, head, wheel
    info.update({"t_sculpt_s": round(time.time() - t0, 1)})
    return info


class TopView:
    """Top-view height regions of a relief that may have undercuts (the sculpt's ears and cheeks overhang the
    cushion): at(z) = where the solid reaches height >= z, i.e. the union of its slices from z up (a single slice
    misses an ear rim with air under it).  Slices every ``h`` mm from z_lo up, cumulated from the top down."""

    def __init__(self, m: Manifold, z_lo: float, h: float = 0.1, clip: CrossSection | None = None):
        bb = m.bounding_box()
        self.h, self.z0 = h, z_lo
        zs = np.arange(z_lo, bb[5] + h, h)
        self.cum = [None] * len(zs)
        acc = CrossSection()
        for k in range(len(zs) - 1, -1, -1):
            sl = m.slice(float(zs[k]))
            if clip is not None:
                sl = g2.intersect(sl, clip)
            acc = g2.union([acc, sl]) if not acc.is_empty() else sl
            self.cum[k] = acc
        self.zs = zs

    def at(self, z: float, up: bool) -> CrossSection:
        """Region reaching >= z: on the slice grid rounded down (up=False: never smaller than true) or up."""
        k = (math.ceil if up else math.floor)((z - self.z0) / self.h - 1e-9)
        if k < 0:
            k = 0
        if k >= len(self.cum):
            return CrossSection()
        return self.cum[k]


def ball_keep_2d(p, P, sk, swept) -> CrossSection:
    """Head-frame region that would ever swing over the yarn ball (disc(O, ball_keep_r)): never head body."""
    return swept(g2.circle((0.0, 0.0), sk.ball_keep_r, 0.01), P, p.psi_b, p.n_sweep, allowance=0.05)


def _top_z(m: Manifold, c, r: float) -> float:
    """Highest z of m over the disc (c, r) (coarse: a few vertical probes)."""
    best = -1e9
    for dx, dy in [(0, 0)] + [(r * math.cos(t), r * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 8, endpoint=False)]:
        col = m ^ Manifold.cylinder(60.0, 0.05, 0.05, 8).translate((c[0] + dx, c[1] + dy, -5.0))
        if not col.is_empty():
            best = max(best, col.bounding_box()[5])
    return best
