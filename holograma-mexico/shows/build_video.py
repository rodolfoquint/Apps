#!/usr/bin/env python3
"""Assemble a fan video from a playlist: pieces from show/ and show2/, the playlist's
transition between them, and each piece's title (name + place) over its middle.

  python3 shows/build_video.py shows/gente-y-lugares.json [--size N]

Writes, under the playlist's "out" folder:
  segments/NN-<piece>.mp4  gapless segments (piece body + transition into the next piece)
  <slug>.mp4               the whole loop (what the fan plays)
  <slug>_preview.mp4       a small preview of the loop
Pieces, transitions and titles are rendered once and cached in raw/ and titles/; they
are re-rendered when their page, its engine or its assets change.

Pieces made with show2's engine (and the titles) render natively at --size; pieces made
with show/'s fixed 1080 engine are rendered at 1080 and scaled up.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "show" / "render.js"


def run(cmd):
    subprocess.run(cmd, check=True)


def duration_of(html):
    for line in html.read_text().splitlines():
        if "duration:" in line:
            return float(line.split("duration:")[1].split(",")[0].strip())
    sys.exit(f"{html}: no 'duration:' found")


def engine_of(page):
    """The engine a page loads (pieces and transitions sit one folder below their engine)."""
    return page.parent.parent / "engine.js"


def scalable(engine):
    return "new URLSearchParams(location.search).get('size')" in engine.read_text()


def stale(dest, sources):
    return not dest.exists() or dest.stat().st_mtime < max(s.stat().st_mtime for s in sources)


class Video:
    def __init__(self, playlist, size=None):
        self.cfg = json.loads(playlist.read_text())
        self.out = ROOT / self.cfg["out"]
        self.size = int(size or self.cfg.get("size") or 1080)
        self.T = float(self.cfg["transition"]["seconds"])
        self.tag = "" if self.size == 1080 else f"_{self.size}"

    def frames(self, page, query, seconds, dest, crf=14, alpha=False):
        """Render page?query frame by frame into dest (scaled to the video size)."""
        native = alpha or scalable(engine_of(page))
        q = query + (f"&size={self.size}" if native and self.size != 1080 else "")
        url = f"{page}?{q.lstrip('&')}" if q.strip("&") else str(page)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_dest = dest.with_name(".tmp-" + dest.name)
        with tempfile.TemporaryDirectory() as tmp:
            run(["node", str(RENDER), url, tmp, str(seconds), "30"])
            vf = [] if native or self.size == 1080 else ["-vf", f"scale={self.size}:{self.size}:flags=lanczos"]
            codec = (["-c:v", "qtrle", "-pix_fmt", "argb"] if alpha else
                     ["-c:v", "libx264", "-crf", str(crf), "-preset", "slow", "-pix_fmt", "yuv420p"])
            run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "30", "-i", f"{tmp}/f%05d.png", *vf, *codec, str(tmp_dest)])
        tmp_dest.replace(dest)
        print(f"rendered {dest.relative_to(ROOT)}", flush=True)

    def raw(self, piece):
        html = ROOT / piece["src"]
        key = f"{html.parent.parent.name}-{html.stem}"
        dest = self.out / "raw" / f"{key}{self.tag}.mp4"
        assets = list((html.parent.parent / "assets").glob(f"{html.stem}*"))
        if stale(dest, [html, engine_of(html), *assets]):
            self.frames(html, "", duration_of(html), dest)
        return key, dest

    def transition(self, params):
        page = ROOT / self.cfg["transition"]["page"]
        name = page.stem + ("_" + params.replace("=", "-").replace("&", "_") if params else "")
        out = {}
        for layer in ("mask", "fx"):
            dest = self.out / "raw" / f"_{name}_{layer}_{self.T}{self.tag}.mp4"
            if stale(dest, [page, engine_of(page)]):
                self.frames(page, f"layer={layer}&T={self.T}&{params}", self.T, dest, crf=10)
            out[layer] = dest
        return out

    def title(self, piece, key, body):
        if not piece.get("name"):
            return None
        page = ROOT / self.cfg["titles"]["page"]
        dest = self.out / "titles" / f"{key}{self.tag}.mov"
        q = f"name={quote(piece['name'])}&place={quote(piece.get('place', ''))}&D={body:.3f}"
        stamp = dest.with_suffix(".txt")
        if stale(dest, [page, ROOT / "show2" / "engine.js"]) or not stamp.exists() or stamp.read_text() != q:
            self.frames(page, q, body, dest, alpha=True)
            stamp.write_text(q)
        return dest

    def mask(self):
        m = self.out / f".mask{self.tag}.png"
        if not m.exists():
            m.parent.mkdir(parents=True, exist_ok=True)
            S = self.size
            run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={S}x{S},format=rgba",
                 "-vf", f"geq=r=0:g=0:b=0:a='if(gt(hypot(X-{S / 2},Y-{S / 2}),{S / 2 - 1}),255,0)'",
                 "-frames:v", "1", str(m)])
        return m

    def build(self):
        pieces, T = self.cfg["pieces"], self.T
        raws = [self.raw(p) for p in pieces]
        seg_dir = self.out / "segments"
        seg_dir.mkdir(parents=True, exist_ok=True)
        for old in seg_dir.glob("*.mp4"):
            old.unlink()
        segments = []
        for i, p in enumerate(pieces):
            nxt = (i + 1) % len(pieces)
            key, a = raws[i]
            b = raws[nxt][1]
            dur = duration_of(ROOT / p["src"])
            body = dur - 2 * T
            tr = self.transition(pieces[nxt].get("transition", ""))
            title = self.title(p, key, body)
            dest = seg_dir / f"{i + 1:02d}-{key}.mp4"
            inputs = ["-i", str(a), "-i", str(b), "-i", str(tr["mask"]), "-i", str(tr["fx"]), "-loop", "1", "-i", str(self.mask())]
            body_chain = f"[0:v]trim=start={T}:end={dur - T},setpts=PTS-STARTPTS,fps=30,format=yuv420p[body0];"
            if title:
                inputs += ["-i", str(title)]
                body_chain += "[5:v]fps=30,format=rgba[ttl];[body0][ttl]overlay=shortest=0:eof_action=pass,format=yuv420p[body];"
            else:
                body_chain += "[body0]null[body];"
            graph = (body_chain +
                     f"[0:v]trim=start={dur - T}:end={dur},setpts=PTS-STARTPTS,fps=30,format=gbrp[a];"
                     f"[1:v]trim=start=0:end={T},setpts=PTS-STARTPTS,fps=30,format=gbrp[b];"
                     f"[2:v]fps=30,format=gbrp[m];[3:v]fps=30,format=gbrp[fx];"
                     f"[a][b][m]maskedmerge[x];[x][fx]blend=all_mode=screen,format=yuv420p[tr];"
                     f"[body][tr]concat=n=2:v=1:a=0[seq];[seq][4:v]overlay=shortest=1,format=yuv420p")
            run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph,
                 "-c:v", "libx264", "-crf", "18", "-maxrate", "12M", "-bufsize", "24M", "-preset", "slow", "-r", "30",
                 "-movflags", "+faststart", str(dest)])
            segments.append(dest)
            print(f"saved {dest.relative_to(ROOT)}", flush=True)
        listing = self.out / ".segments.txt"
        listing.write_text("".join(f"file '{s}'\n" for s in segments))
        slug = self.cfg["slug"]
        full = self.out / f"{slug}{self.tag}.mp4"
        run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", "-movflags", "+faststart", str(full)])
        preview = self.out / f"{slug}_preview.mp4"
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(full), "-vf", "scale=540:540",
             "-c:v", "libx264", "-b:v", "1200k", "-maxrate", "1400k", "-bufsize", "2800k", "-preset", "slow",
             "-movflags", "+faststart", str(preview)])
        total = sum(duration_of(ROOT / p["src"]) for p in pieces) - len(pieces) * T
        print(f"saved {full.relative_to(ROOT)} and {preview.name}: {len(pieces)} pieces, {total:.1f} s loop, {self.size}px")


def main():
    args = sys.argv[1:]
    size = None
    if "--size" in args:
        i = args.index("--size")
        size = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit(__doc__)
    Video(Path(args[0]).resolve(), size).build()


if __name__ == "__main__":
    main()
