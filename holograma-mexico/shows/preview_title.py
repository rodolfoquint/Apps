#!/usr/bin/env python3
"""Preview a piece with its title on top, the way the assembled video shows it.

  python3 shows/preview_title.py PIECE [TIMES] [OUT.png]

PIECE is a piece id or source path, e.g. 10-mariachi or show2/pieces/10-mariachi.html.
TIMES are piece-time seconds (default 3,6,9). The name and place come from the playlist
in shows/ that contains the piece. Writes one strip of frames (default out-titles/<id>.png).
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent


def find(piece):
    for pl in sorted((ROOT / "shows").glob("*.json")):
        cfg = json.loads(pl.read_text())
        for p in cfg["pieces"]:
            if piece in (p["src"], Path(p["src"]).stem):
                return cfg, p
    sys.exit(f"{piece} is not in any playlist in shows/")


def duration_of(html):
    for line in html.read_text().splitlines():
        if "duration:" in line:
            return float(line.split("duration:")[1].split(",")[0].strip())


def main():
    if not sys.argv[1:]:
        sys.exit(__doc__)
    cfg, p = find(sys.argv[1])
    times = sys.argv[2] if len(sys.argv) > 2 else "3,6,9"
    html = ROOT / p["src"]
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / "out-titles" / f"{html.stem}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    T = float(cfg["transition"]["seconds"])
    body = duration_of(html) - 2 * T
    render = str(ROOT / "show" / "render.js")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["node", render, str(html), f"{tmp}/p", "1", "30", "--stills", times], check=True, capture_output=True)
        # the title's clock starts when the piece's body starts (after the incoming transition)
        ttimes = ",".join(f"{max(0.0, float(t) - T):.3f}" for t in times.split(","))
        q = f"name={quote(p['name'])}&place={quote(p.get('place', ''))}&D={body:.3f}"
        subprocess.run(["node", render, f"{ROOT / cfg['titles']['page']}?{q}", f"{tmp}/t", "1", "30", "--stills", ttimes],
                       check=True, capture_output=True)
        n = len(times.split(","))
        inputs, graph = [], ""
        for i in range(n):
            inputs += ["-i", f"{tmp}/p/f{i:05d}.png", "-i", f"{tmp}/t/f{i:05d}.png"]
            graph += f"[{2 * i}][{2 * i + 1}]overlay,scale=540:540[v{i}];"
        if n > 1:
            graph += "".join(f"[v{i}]" for i in range(n)) + f"hstack=inputs={n}"
        else:
            graph = graph.rstrip(";").replace("[v0]", "")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph, str(out)], check=True)
    print(f"saved {out} ({p['name']} / {p.get('place', '')}, t = {times})")


if __name__ == "__main__":
    main()
