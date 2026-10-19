#!/usr/bin/env python3
"""Turn an artwork on black into show assets.

  python3 show/prepare.py SRC NAME [--color 255,196,70] [--size 1024] [--circle]

Writes show/assets/NAME.png (the subject cut out on transparency, squared and
centred) and show/assets/NAME_lines.png (its edges as glowing line art in
--color). --circle cuts a round subject such as the Sun Stone with a clean
circular edge instead of the soft luminance edge.
"""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("src")
    p.add_argument("name")
    p.add_argument("--color", default="255,196,70")
    p.add_argument("--size", type=int, default=1024)
    p.add_argument("--circle", action="store_true")
    p.add_argument("--edge-low", type=float, default=70, help="edge percentile treated as no line")
    p.add_argument("--edge-high", type=float, default=99.3, help="edge percentile treated as full line")
    a = p.parse_args()

    img = Image.open(a.src).convert("RGB")
    rgb = np.asarray(img).astype(np.float32)
    lum = rgb.mean(axis=2)
    ys, xs = np.where(lum > 12)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    half = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2 + 6
    box = tuple(int(round(v)) for v in (cx - half, cy - half, cx + half, cy + half))
    sq = Image.new("RGB", (box[2] - box[0], box[3] - box[1]))
    sq.paste(img.crop((max(0, box[0]), max(0, box[1]), min(img.width, box[2]), min(img.height, box[3]))),
             (max(0, -box[0]), max(0, -box[1])))
    sq = sq.resize((a.size, a.size), Image.LANCZOS)
    d = np.asarray(sq).astype(np.float32)
    n = a.size
    yy, xx = np.mgrid[0:n, 0:n]
    rr = np.hypot(xx - (n - 1) / 2, yy - (n - 1) / 2)
    if a.circle:
        alpha = np.clip((n / 2 - 1 - rr) * 2, 0, 1)
    else:
        # black background becomes transparent with a soft edge
        l = d.mean(axis=2)
        alpha = np.clip((l - 6) / 28, 0, 1)
        alpha = np.asarray(Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))) / 255.0
    (HERE / "assets").mkdir(exist_ok=True)
    Image.fromarray(np.dstack([d, alpha * 255]).astype(np.uint8), "RGBA").save(HERE / "assets" / f"{a.name}.png")

    g = np.asarray(sq.convert("L").filter(ImageFilter.GaussianBlur(1.6))).astype(np.float32)
    gx = np.zeros_like(g); gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1, :] = g[2:, :] - g[:-2, :]
    mag = np.hypot(gx, gy) * (alpha > 0.05)
    lo, hi = np.percentile(mag[alpha > 0.05], a.edge_low), np.percentile(mag[alpha > 0.05], a.edge_high)
    mag = np.clip((mag - lo) / max(hi - lo, 1e-6), 0, 1) ** 0.8
    color = np.array([float(v) for v in a.color.split(",")], np.float32)
    lines = np.dstack([np.broadcast_to(color, (n, n, 3)), mag * 255]).astype(np.uint8)
    Image.fromarray(lines, "RGBA").save(HERE / "assets" / f"{a.name}_lines.png")
    print(f"assets/{a.name}.png and assets/{a.name}_lines.png ({n}px, line coverage {float((mag > 0.3).mean()):.3f})")


if __name__ == "__main__":
    main()
