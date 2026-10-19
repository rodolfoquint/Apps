// Shared toolkit for the hologram-fan motion graphics.
// Every piece is a pure function of time: HG.start({duration, assets, render(t, A)}).
// render.js calls window.render(t) for each frame, so nothing may depend on the
// previous frame — particles and effects are computed analytically from t.
(() => {
  const W = 1080, C = W / 2;
  const cv = document.getElementById('c');
  const ctx = cv.getContext('2d');

  // ---------- math
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, k) => a + (b - a) * k;
  const smooth = (a, b, t) => { const x = clamp((t - a) / (b - a)); return x * x * (3 - 2 * x); };
  const ease = {
    out3: x => 1 - Math.pow(1 - clamp(x), 3),
    in3: x => Math.pow(clamp(x), 3),
    inOut3: x => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; },
    outBack: x => { x = clamp(x); const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); },
  };
  // fade in over [a, a+fi], hold, fade out over [b-fo, b]
  const window_ = (t, a, b, fi = 0.6, fo = 0.6) => smooth(a, a + fi, t) * (1 - smooth(b - fo, b, t));
  function rng(seed) { let s = seed >>> 0 || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }

  // ---------- palette (Mexican festive, tuned to glow on LEDs)
  const COLORS = {
    gold: [255, 190, 70], warm: [255, 225, 160], white: [255, 250, 240],
    green: [40, 220, 120], red: [255, 50, 70], pink: [255, 60, 170], magenta: [230, 40, 200],
    turquoise: [40, 220, 230], orange: [255, 130, 20], yellow: [255, 220, 40], purple: [160, 80, 255],
    marigold: [255, 150, 20],
  };
  const TRICOLOR = [COLORS.green, COLORS.white, COLORS.red];
  const FIESTA = [COLORS.pink, COLORS.orange, COLORS.yellow, COLORS.turquoise, COLORS.green, COLORS.purple];
  const rgba = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

  // ---------- assets and layers
  const load = src => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('cannot load ' + src)); i.src = src; });
  function layer() { const c = document.createElement('canvas'); c.width = c.height = W; return { cv: c, ctx: c.getContext('2d') }; }
  const spriteCache = new Map();
  // soft glowing dot, white-hot core fading into the colour
  function sprite(color, size = 64) {
    const key = color.join(',') + '/' + size;
    if (spriteCache.has(key)) return spriteCache.get(key);
    const s = document.createElement('canvas'); s.width = s.height = size; const g = s.getContext('2d');
    const h = size / 2, grd = g.createRadialGradient(h, h, 0, h, h, h);
    grd.addColorStop(0, 'rgba(255,255,255,1)');
    grd.addColorStop(0.18, rgba(color, 0.95));
    grd.addColorStop(0.45, rgba(color, 0.35));
    grd.addColorStop(1, rgba(color, 0));
    g.fillStyle = grd; g.fillRect(0, 0, size, size);
    spriteCache.set(key, s); return s;
  }

  function reset(c = ctx) {
    c.setTransform(1, 0, 0, 1, 0, 0); c.globalCompositeOperation = 'source-over'; c.globalAlpha = 1; c.filter = 'none';
    c.shadowBlur = 0;
  }
  function clear() { reset(); ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, W); }

  // draw a sprite dot additively
  function dot(c, color, x, y, size, alpha) {
    if (alpha <= 0.003 || size <= 0) return;
    c.globalAlpha = Math.min(1, alpha);
    c.drawImage(sprite(color), x - size / 2, y - size / 2, size, size);
  }

  // image with a soft additive bloom; centred at (x, y), width w (height keeps aspect)
  function glowImage(c, img, x, y, w, { alpha = 1, bloom = 0.6, blur = 14, rotation = 0, scaleY = 1 } = {}) {
    if (alpha <= 0) return;
    const h = w * img.height / img.width * scaleY;
    c.save(); c.translate(x, y); c.rotate(rotation);
    if (bloom > 0) {
      c.globalCompositeOperation = 'lighter'; c.globalAlpha = alpha * bloom; c.filter = `blur(${blur}px)`;
      c.drawImage(img, -w / 2, -h / 2, w, h); c.filter = 'none';
    }
    c.globalCompositeOperation = 'source-over'; c.globalAlpha = alpha;
    c.drawImage(img, -w / 2, -h / 2, w, h);
    c.restore();
  }

  // line art drawn in light, revealed from a centre point outward behind a ring of light.
  // k: 0..1 progress; returns nothing, draws additively onto ctx.
  const _lx = layer();
  function lineReveal(img, x, y, w, k, { alpha = 1, rotation = 0, color = COLORS.warm, cx = null, cy = null, feather = 90, ring = true } = {}) {
    if (k <= 0 || alpha <= 0) return;
    const h = w * img.height / img.width;
    const lx = _lx.ctx; reset(lx); lx.clearRect(0, 0, W, W);
    lx.translate(x, y); lx.rotate(rotation);
    lx.globalAlpha = 0.85; lx.filter = 'blur(6px)'; lx.drawImage(img, -w / 2, -h / 2, w, h);
    lx.filter = 'none'; lx.globalAlpha = 1; lx.drawImage(img, -w / 2, -h / 2, w, h);
    reset(lx);
    const ox = cx ?? x, oy = cy ?? y;
    if (k < 1) {
      const maxR = Math.hypot(w, h) / 2 + Math.hypot(ox - x, oy - y) + feather;
      const rho = Math.max(1, k * maxR);
      lx.globalCompositeOperation = 'destination-in';
      const g = lx.createRadialGradient(ox, oy, 0, ox, oy, rho);
      g.addColorStop(0, 'rgba(0,0,0,1)'); g.addColorStop(Math.max(0, 1 - feather / rho), 'rgba(0,0,0,1)'); g.addColorStop(1, 'rgba(0,0,0,0)');
      lx.fillStyle = g; lx.fillRect(0, 0, W, W);
      if (ring) {
        lx.globalCompositeOperation = 'source-atop';
        const rg = lx.createRadialGradient(ox, oy, Math.max(0, rho - 40), ox, oy, rho);
        rg.addColorStop(0, rgba(color, 0)); rg.addColorStop(0.8, rgba(color, 0.9)); rg.addColorStop(1, rgba(color, 0));
        lx.fillStyle = rg; lx.fillRect(0, 0, W, W);
      }
    }
    reset(ctx); ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = alpha; ctx.drawImage(_lx.cv, 0, 0); reset(ctx);
  }

  // glowing circle outline
  function ring(c, x, y, r, color, { width = 6, blur = 10, alpha = 1 } = {}) {
    if (alpha <= 0) return;
    c.save(); c.globalCompositeOperation = 'lighter'; c.strokeStyle = rgba(color, 1); c.lineWidth = width;
    c.globalAlpha = alpha * 0.8; c.filter = `blur(${blur}px)`; c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2); c.stroke();
    c.filter = 'none'; c.globalAlpha = alpha; c.lineWidth = Math.max(1.5, width / 3); c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2); c.stroke();
    c.restore();
  }

  // ---------- particle systems (stateless: positions are functions of t)

  // n sparks spiralling in from far away onto a ring of radius r around (x, y)
  function converge(t, { x = C, y = C, r = 420, n = 600, start = 0, dur = 2.2, colors = [COLORS.gold], size = 12, seed = 7, orbit = 0.12, alpha = 1, scatter = 0 } = {}) {
    const R = rng(seed);
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    for (let i = 0; i < n; i++) {
      const a0 = R() * Math.PI * 2, r0 = r + 300 + R() * 420, spin = 1.2 + R() * 1.6, d = R() * 0.9, s = 0.6 + R() * 1.8, jit = (R() - 0.5) * 26, tw = R() * 6.28, col = colors[Math.floor(R() * colors.length)];
      const k = ease.out3((t - start - d) / dur);
      if (k <= 0) continue;
      let rad = lerp(r0, r + jit, k) + scatter * (r0 - r);
      const ang = a0 + spin * (1 - k) + orbit * t;
      const twk = 0.55 + 0.45 * Math.sin(t * 5 + tw);
      dot(ctx, col, x + Math.cos(ang) * rad, y + Math.sin(ang) * rad, size * s, clamp(k * 1.4) * twk * alpha);
    }
    ctx.restore();
  }

  // a firework shell: launches from below at t0, bursts at (x, y) at t0+rise into n stars that fall with gravity
  function firework(t, { t0, x, y, color, color2 = null, n = 110, speed = 260, rise = 0.9, life = 2.2, seed = 1, size = 9, launchFrom = W + 40, trail = 5 } = {}) {
    const dt = t - t0; if (dt < 0 || dt > rise + life) return;
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    if (dt < rise) {
      const k = ease.out3(dt / rise);
      const yy = lerp(launchFrom, y, k), xx = x + Math.sin(dt * 9 + seed) * 4 * (1 - k);
      for (let j = 0; j < 6; j++) dot(ctx, COLORS.warm, xx, yy + j * 10, 10 - j, (1 - j / 6) * 0.9);
      ctx.restore(); return;
    }
    const bt = dt - rise, R = rng(seed);
    const fade = 1 - smooth(life * 0.45, life, bt);
    if (bt < 0.18) dot(ctx, COLORS.white, x, y, 220 * (1 - bt / 0.18) + 40, 0.9 * (1 - bt / 0.18)); // flash
    for (let i = 0; i < n; i++) {
      const a = R() * Math.PI * 2, v = speed * (0.55 + 0.45 * Math.sqrt(R())), col = color2 && R() < 0.4 ? color2 : color, tw = R() * 6.28;
      for (let j = 0; j < trail; j++) {
        const tt = Math.max(0, bt - j * 0.035);
        const drag = (1 - Math.exp(-2.2 * tt)) / 2.2;
        const px = x + Math.cos(a) * v * drag, py = y + Math.sin(a) * v * drag + 60 * tt * tt;
        const sparkle = 0.7 + 0.3 * Math.sin(t * 30 + tw);
        dot(ctx, col, px, py, size * (1 - j / trail) * (j ? 0.8 : 1.2), fade * sparkle * (1 - j / trail));
      }
    }
    ctx.restore();
  }

  // confetti burst from (x, y) at t0: tumbling coloured paper pieces with gravity and flutter
  function confetti(t, { t0, x, y, n = 160, speed = 520, colors = FIESTA, seed = 3, life = 4, alpha = 1, w = 14, h = 8 } = {}) {
    const dt = t - t0; if (dt < 0 || dt > life) return;
    const R = rng(seed), fade = (1 - smooth(life * 0.6, life, dt)) * alpha;
    ctx.save();
    for (let i = 0; i < n; i++) {
      const a = -Math.PI / 2 + (R() - 0.5) * Math.PI * 1.6, v = speed * (0.4 + 0.6 * R()), col = colors[Math.floor(R() * colors.length)];
      const spin = (R() - 0.5) * 14, flip = 4 + R() * 8, ph = R() * 6.28, sway = 20 + R() * 40;
      const drag = (1 - Math.exp(-1.8 * dt)) / 1.8;
      const px = x + Math.cos(a) * v * drag + Math.sin(dt * 2 + ph) * sway * smooth(0.4, 1.2, dt);
      const py = y + Math.sin(a) * v * drag + 120 * dt * dt * 0.5 + 60 * dt;
      ctx.save(); ctx.translate(px, py); ctx.rotate(ph + spin * dt);
      ctx.scale(1, Math.cos(ph + flip * dt));
      ctx.globalAlpha = fade; ctx.fillStyle = rgba(col, 1);
      ctx.shadowColor = rgba(col, 0.9); ctx.shadowBlur = 8;
      ctx.fillRect(-w / 2, -h / 2, w, h);
      ctx.restore();
    }
    ctx.restore();
  }

  // gentle ambient dust that drifts upward
  function dust(t, { n = 120, colors = [COLORS.gold], seed = 11, alpha = 0.5, size = 6, r = 520 } = {}) {
    const R = rng(seed);
    ctx.save(); ctx.globalCompositeOperation = 'lighter';
    for (let i = 0; i < n; i++) {
      const x0 = R() * W, sp = 15 + R() * 40, ph = R() * 1000, s = 0.5 + R(), col = colors[Math.floor(R() * colors.length)];
      const y = W - ((ph + sp * t) % (W + 100)) + 50, x = x0 + Math.sin(t * 0.7 + ph) * 20;
      if (Math.hypot(x - C, y - C) > r) continue;
      dot(ctx, col, x, y, size * s, alpha * (0.5 + 0.5 * Math.sin(t * 3 + ph)));
    }
    ctx.restore();
  }

  // ---------- piece lifecycle
  function start({ duration, assets = {}, render }) {
    window.DURATION = duration;
    window.ready = (async () => {
      const A = {};
      for (const [k, src] of Object.entries(assets)) A[k] = await load(src);
      await document.fonts.ready;
      window.render = t => { clear(); render(t, A); reset(); };
      window.render(0);
      return true;
    })();
  }

  window.HG = { W, C, ctx, clamp, lerp, smooth, ease, window: window_, rng, COLORS, TRICOLOR, FIESTA, rgba,
    load, layer, sprite, reset, clear, dot, glowImage, lineReveal, ring, converge, firework, confetti, dust, start };
})();
