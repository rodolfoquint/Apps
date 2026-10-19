#!/usr/bin/env python3
"""Render the show: each pieces/NN-name.html -> out-show/NN-name.mp4, then one loop.

  python3 show/build.py                 # render every piece, then the loop and a preview
  python3 show/build.py 03-piedra-del-sol 05-mariposas   # only these pieces (no loop)
  python3 show/build.py --stills 02-mapa 1,4,8            # 3 stills of a piece -> out-show/stills/
  python3 show/build.py --loop                            # just rebuild the loop from rendered pieces

Needs node with playwright-core (cd show && npm install) and ffmpeg.
"""

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


def mask():
    m = OUT / ".mask.png"
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
        run(["node", str(HERE / "render.js"), str(html), tmp, str(seconds), "30"])
        dest = OUT / f"{name}.mp4"
        # round mask for the fan; short fades so pieces chain smoothly
        run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "30", "-i", f"{tmp}/f%05d.png", "-loop", "1", "-i", str(mask()),
             "-filter_complex", f"[0:v][1:v]overlay=shortest=1,fade=t=in:st=0:d=0.3,fade=t=out:st={seconds - 0.35:.2f}:d=0.3,format=yuv420p",
             "-c:v", "libx264", "-crf", "18", "-maxrate", "10M", "-bufsize", "20M", "-preset", "slow", "-r", "30",
             "-movflags", "+faststart", str(dest)])
    print(f"saved {dest}")


def stills(name, times):
    html = HERE / "pieces" / f"{name}.html"
    dest = OUT / "stills"
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        run(["node", str(HERE / "render.js"), str(html), tmp, "1", "30", "--stills", times])
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
    args = sys.argv[1:]
    OUT.mkdir(exist_ok=True)
    if args[:1] == ["--stills"]:
        stills(args[1], args[2])
    elif args[:1] == ["--loop"]:
        loop()
    elif args:
        for name in args:
            render_piece(name)
    else:
        for html in sorted((HERE / "pieces").glob("[0-9][0-9]-*.html")):
            render_piece(html.stem)
        loop()


if __name__ == "__main__":
    main()
