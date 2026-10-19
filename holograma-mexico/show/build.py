#!/usr/bin/env python3
"""Render the show: each pieces/NN-name.html -> out-show/NN-name.mp4, then one loop.

  python3 show/build.py                 # render every piece, then the loop and a preview
  python3 show/build.py 03-piedra-del-sol 05-mariposas   # only these pieces (no loop)
  python3 show/build.py --stills 02-mapa 1,4,8            # 3 stills of a piece -> out-show/stills/
  python3 show/build.py --loop                            # just rebuild the loop from rendered pieces
  python3 show/build.py --show                            # the finished show: pieces in show.json order joined by
                                                          # the show's transition, as one seamless loop
                                                          # (out-show/show.mp4) plus gapless segments (out-show/segments/)
  --size N (any command)                                  # render at N x N instead of 1080 (pieces whose engine
                                                          # supports ?size=, i.e. show2/); --show also reads "size"
                                                          # from show.json

Needs node with playwright-core (cd show && npm install) and ffmpeg.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out-show"
SIZE = 1080


def run(cmd):
    subprocess.run(cmd, check=True)


def duration_of_piece(html):
    for line in html.read_text().splitlines():
        if "duration:" in line:
            return float(line.split("duration:")[1].split(",")[0].strip())
    sys.exit(f"{html.name}: no 'duration:' found")


def page(html, query=""):
    """Page URL for render.js: adds ?size= when rendering above 1080."""
    q = [query] if query else []
    if SIZE != 1080:
        q.append(f"size={SIZE}")
    return f"{html}?{'&'.join(q)}" if q else str(html)


def sized(name):
    return name if SIZE == 1080 else f"{name}_{SIZE}"


def mask():
    m = OUT / f".mask{'' if SIZE == 1080 else SIZE}.png"
    if not m.exists():
        OUT.mkdir(exist_ok=True)
        run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={SIZE}x{SIZE},format=rgba",
             "-vf", f"geq=r=0:g=0:b=0:a='if(gt(hypot(X-{SIZE / 2},Y-{SIZE / 2}),{SIZE / 2 - 1}),255,0)'",
             "-frames:v", "1", str(m)])
    return m


def render_piece(name):
    html = HERE / "pieces" / f"{name}.html"
    seconds = duration_of_piece(html)
    with tempfile.TemporaryDirectory() as tmp:
        run(["node", str(HERE / "render.js"), page(html), tmp, str(seconds), "30"])
        dest = OUT / f"{name}.mp4"
        # round mask for the fan; short fades so pieces chain smoothly
        run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "30", "-i", f"{tmp}/f%05d.png", "-loop", "1", "-i", str(mask()),
             "-filter_complex", f"[0:v][1:v]overlay=shortest=1,fade=t=in:st=0:d=0.3,fade=t=out:st={seconds - 0.35:.2f}:d=0.3,format=yuv420p",
             "-c:v", "libx264", "-crf", "18", "-maxrate", "10M", "-bufsize", "20M", "-preset", "slow", "-r", "30",
             "-movflags", "+faststart", str(dest)])
    print(f"saved {dest}")


def frames_to_mp4(page, seconds, dest, crf=14):
    """Render a page frame by frame to an unmasked, high-quality mp4."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        run(["node", str(HERE / "render.js"), page, tmp, str(seconds), "30"])
        run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "30", "-i", f"{tmp}/f%05d.png",
             "-c:v", "libx264", "-crf", str(crf), "-preset", "slow", "-pix_fmt", "yuv420p", str(dest)])


def raw(name):
    """Unmasked render of a piece for the show; re-rendered when the page, toolkit or assets change."""
    html = HERE / "pieces" / f"{name}.html"
    dest = OUT / "raw" / f"{sized(name)}.mp4"
    newest = max([html.stat().st_mtime, (HERE / "engine.js").stat().st_mtime] +
                 [a.stat().st_mtime for a in (HERE / "assets").glob(f"{name}*")])
    if not dest.exists() or dest.stat().st_mtime < newest:
        frames_to_mp4(page(html), duration_of_piece(html), dest)
        print(f"rendered {dest}")
    return dest


def portal(seconds, transition="portal.html", extra=""):
    """Render a transition page's two layers (mask: white = next piece; fx: light on black)."""
    src = HERE / "transitions" / transition
    tag = Path(transition).stem + (f"_{extra.replace('=', '-').replace('&', '_')}" if extra else "")
    out = {}
    for layer in ("mask", "fx"):
        dest = OUT / "raw" / f"_{sized(tag)}_{layer}_{seconds}.mp4"
        if not dest.exists() or dest.stat().st_mtime < max(src.stat().st_mtime, (HERE / "engine.js").stat().st_mtime):
            query = f"layer={layer}&T={seconds}" + (f"&{extra}" if extra else "")
            frames_to_mp4(page(src, query), seconds, dest, crf=10)
        out[layer] = dest
    return out


def show():
    global SIZE
    cfg = json.loads((HERE / "show.json").read_text())
    T, order = cfg["transition_seconds"], cfg["order"]
    if SIZE == 1080 and cfg.get("size"):
        SIZE = int(cfg["size"])
    # transition: one page for every boundary, or per boundary extra query parameters
    # ("transition_params": {"<incoming piece>": "k=v&..."}) e.g. to tint or vary it
    missing = [n for n in order if not (HERE / "pieces" / f"{n}.html").exists()]
    if missing:
        sys.exit(f"missing pieces: {', '.join(missing)}")
    raws = {n: raw(n) for n in order}
    transition = cfg.get("transition", "portal.html")
    params = cfg.get("transition_params", {})
    seg_dir = OUT / "segments"
    seg_dir.mkdir(parents=True, exist_ok=True)
    for old in seg_dir.glob("*.mp4"):
        old.unlink()
    segments = []
    for i, a in enumerate(order):
        b = order[(i + 1) % len(order)]
        dur = duration_of_piece(HERE / "pieces" / f"{a}.html")
        dest = seg_dir / f"{i + 1:02d}-{a}.mp4"
        tr = portal(T, transition, params.get(b, ""))
        # every piece's first T seconds play inside the previous transition (the last
        # piece's transition leads back into the first), so each segment is the piece's
        # body followed by the portal into the next piece: gapless and loopable
        graph = (f"[0:v]trim=start={T}:end={dur - T},setpts=PTS-STARTPTS,fps=30,format=yuv420p[body];"
                 f"[0:v]trim=start={dur - T}:end={dur},setpts=PTS-STARTPTS,fps=30,format=gbrp[a];"
                 f"[1:v]trim=start=0:end={T},setpts=PTS-STARTPTS,fps=30,format=gbrp[b];"
                 f"[2:v]fps=30,format=gbrp[m];[3:v]fps=30,format=gbrp[fx];"
                 f"[a][b][m]maskedmerge[x];[x][fx]blend=all_mode=screen,format=yuv420p[tr];"
                 f"[body][tr]concat=n=2:v=1:a=0[seq];[seq][4:v]overlay=shortest=1,format=yuv420p")
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raws[a]), "-i", str(raws[b]),
             "-i", str(tr["mask"]), "-i", str(tr["fx"]), "-loop", "1", "-i", str(mask()),
             "-filter_complex", graph, "-c:v", "libx264", "-crf", "18", "-maxrate", "10M", "-bufsize", "20M",
             "-preset", "slow", "-r", "30", "-movflags", "+faststart", str(dest)])
        segments.append(dest)
        print(f"saved {dest}")
    listing = OUT / ".show.txt"
    listing.write_text("".join(f"file '{s}'\n" for s in segments))
    full = OUT / "show.mp4"
    run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", "-movflags", "+faststart", str(full)])
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(full), "-vf", "scale=540:540",
         "-c:v", "libx264", "-b:v", "1200k", "-maxrate", "1400k", "-bufsize", "2800k", "-preset", "slow",
         "-movflags", "+faststart", str(OUT / "show_preview.mp4")])
    print(f"saved {full} and show_preview.mp4 ({len(segments)} pieces, {SIZE}px, {T}s {transition} transitions)")


def stills(name, times):
    html = HERE / "pieces" / f"{name}.html"
    dest = OUT / "stills"
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        run(["node", str(HERE / "render.js"), page(html), tmp, "1", "30", "--stills", times])
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", f"{tmp}/f%05d.png",
             "-vf", f"scale=400:400,tile={len(times.split(','))}x1:padding=4", "-frames:v", "1", str(dest / f"{name}.png")])
    print(f"saved {dest / f'{name}.png'} (t = {times})")


def loop():
    clips = sorted(OUT.glob("[0-9][0-9]-*.mp4"))
    listing = OUT / ".playlist.txt"
    listing.write_text("".join(f"file '{c.name}'\n" for c in clips))
    run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", "-movflags", "+faststart", str(OUT / "show.mp4")])
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(OUT / "show.mp4"), "-vf", "scale=540:540",
         "-c:v", "libx264", "-b:v", "900k", "-maxrate", "1100k", "-bufsize", "2200k", "-preset", "slow",
         "-movflags", "+faststart", str(OUT / "show_preview.mp4")])
    print(f"saved {OUT / 'show.mp4'} and show_preview.mp4 ({len(clips)} pieces)")


def main():
    global SIZE
    args = sys.argv[1:]
    if "--size" in args:
        i = args.index("--size")
        SIZE = int(args[i + 1])
        del args[i:i + 2]
    OUT.mkdir(exist_ok=True)
    if args[:1] == ["--stills"]:
        stills(args[1], args[2])
    elif args[:1] == ["--loop"]:
        loop()
    elif args[:1] == ["--show"]:
        show()
    elif args:
        for name in args:
            render_piece(name)
    else:
        for html in sorted((HERE / "pieces").glob("[0-9][0-9]-*.html")):
            render_piece(html.stem)
        loop()


if __name__ == "__main__":
    main()
