#!/usr/bin/env python3
"""Make the Mexico hologram-fan scenes with the Higgsfield API.

Each scene is made in two steps: a still image on pure black, then an
image-to-video clip that animates it. Every attempt is kept under out/ so
you can pick the best one before spending money on the next step.

  python3 generate.py [--set NAME] COMMAND ...      # --set NAME uses scenes-NAME.json and out-NAME/
  python3 generate.py estimate                      # cost of one image + one video
  python3 generate.py image  SCENE [--extra TEXT] [--seed N] [--dry-run]
  python3 generate.py select SCENE N                # use image attempt N for the video
  python3 generate.py video  SCENE [--extra TEXT] [--duration S] [--dry-run]
  python3 generate.py frames SCENE                  # 3x3 frame sheet of the chosen video
  python3 generate.py select-video SCENE N          # use video attempt N
  python3 generate.py fan    [SCENE ...] [--size PX] # square, black-crushed, circle-masked clips
  python3 generate.py loop                          # join the fan clips into one playlist video
  python3 generate.py sheet                         # contact sheet of every chosen image
  python3 generate.py status

Credentials come from HF_API_KEY_ID and HF_API_KEY_SECRET (Higgsfield Cloud).
HF_BUDGET_USD (default 30) caps the total recorded spend of the chosen set.
"""

import argparse
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

API = "https://api.higgsfield.ai"
IMAGE_MODEL = "alibaba/qwen-image-3/text-to-image"
# Kling O3 takes a required last frame; passing the still as both first and last
# frame makes each clip loop seamlessly and pushes turntables to a full turn.
VIDEO_MODEL = "kling-video/o3/first-last-frame"
VIDEO_MODE = "pro"
VIDEO_SECONDS = 15
FAN_SIZE = 1080

HERE = Path(__file__).resolve().parent
# Set by use_set(): each set of scenes has its own scene list, outputs and spend log.
SCENES_FILE = HERE / "scenes.json"
OUT = HERE / "out"
SPEND_LOG = OUT / "spend.jsonl"


def use_set(name):
    global SCENES_FILE, OUT, SPEND_LOG
    if name:
        SCENES_FILE = HERE / f"scenes-{name}.json"
        OUT = HERE / f"out-{name}"
        SPEND_LOG = OUT / "spend.jsonl"
        if not SCENES_FILE.exists():
            die(f"no scene list {SCENES_FILE.name}")


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def load_scenes():
    with open(SCENES_FILE, encoding="utf-8") as f:
        return json.load(f)


def find_scene(cfg, scene_id):
    for i, scene in enumerate(cfg["scenes"]):
        if scene["id"] == scene_id:
            return i, scene
    die(f"unknown scene '{scene_id}'. Known: {', '.join(s['id'] for s in cfg['scenes'])}")


# ---------- per-scene state (one file per scene so parallel runs don't collide)

def state_path(scene_id):
    return OUT / "state" / f"{scene_id}.json"


def load_state(scene_id):
    p = state_path(scene_id)
    if p.exists():
        return json.loads(p.read_text())
    return {"images": [], "videos": [], "selected_image": None, "selected_video": None, "pending": {}}


def save_state(scene_id, state):
    p = state_path(scene_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(p)


# ---------- HTTP

def credentials():
    key_id = os.environ.get("HF_API_KEY_ID")
    secret = os.environ.get("HF_API_KEY_SECRET")
    if not key_id or not secret:
        die("set HF_API_KEY_ID and HF_API_KEY_SECRET (from console.higgsfield.ai)")
    return f"{key_id}:{secret}"


def call(method, path, body=None, idempotency_key=None):
    url = path if path.startswith("http") else f"{API}/{path}"
    headers = {"Authorization": f"Key {credentials()}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    attempt = 0
    busy_until = time.time() + 45 * 60
    while attempt < 10:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            # Hitting the account's concurrency limit is normal when several scenes run
            # at once; wait for a slot without using up the error retries.
            if e.code == 400 and "concurrent" in text.lower() and time.time() < busy_until:
                print("  account concurrency limit reached, waiting 30s...", flush=True)
                time.sleep(30 + random.uniform(0, 10))
                continue
            attempt += 1
            if e.code == 403:
                die(f"Higgsfield refused the request (403, usually insufficient credits): {text}")
            if e.code in (423, 429) or e.code >= 500:
                wait = min(60, 2 ** attempt) + random.uniform(0, 2)
                print(f"  HTTP {e.code}, retrying in {wait:.0f}s...", flush=True)
                time.sleep(wait)
                continue
            die(f"HTTP {e.code} from {url}: {text}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            attempt += 1
            wait = min(60, 2 ** attempt) + random.uniform(0, 2)
            print(f"  network error ({e}), retrying in {wait:.0f}s...", flush=True)
            time.sleep(wait)
    die(f"gave up after repeated failures calling {url}")


def estimate_usd(model, body):
    return float(call("POST", f"estimate/{model}", body)["usd"])


def spent_usd():
    if not SPEND_LOG.exists():
        return 0.0
    return sum(json.loads(line)["usd"] for line in SPEND_LOG.read_text().splitlines() if line.strip())


def in_flight_usd():
    total = 0.0
    for p in (OUT / "state").glob("*.json"):
        total += sum(req["cost"] for req in json.loads(p.read_text()).get("pending", {}).values())
    return total


def check_budget(cost):
    budget = float(os.environ.get("HF_BUDGET_USD", "30"))
    committed = spent_usd() + in_flight_usd()
    if committed + cost > budget:
        die(f"budget stop: ${committed:.2f} spent or in flight + ${cost:.2f} would pass "
            f"HF_BUDGET_USD=${budget:.2f}")


def record_spend(scene_id, kind, cost, request_id):
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(SPEND_LOG, "a") as f:
        f.write(json.dumps({"scene": scene_id, "kind": kind, "usd": cost, "request_id": request_id}) + "\n")


def run_request(scene_id, kind, model, body, cost, meta, poll_every):
    """Submit one generation (or resume an interrupted one) and wait for it.

    The request is saved as pending before polling, so if this process is
    killed, running the same command again picks it up instead of paying twice.
    Returns (result, pending); call finish() once the output is downloaded.
    """
    state = load_state(scene_id)
    pending = state.setdefault("pending", {}).get(kind)
    if pending:
        print(f"  resuming request {pending['request_id']} from an earlier run "
              "(its original settings apply)", flush=True)
    else:
        check_budget(cost)
        submitted = call("POST", model, body, idempotency_key=str(uuid.uuid4()))
        request_id = submitted["request_id"]
        pending = {"request_id": request_id, "cost": cost, "meta": meta,
                   "status_url": submitted.get("status_url") or f"{API}/requests/{request_id}/status"}
        state["pending"][kind] = pending
        save_state(scene_id, state)
        print(f"  submitted {request_id}", flush=True)

    deadline = time.time() + 30 * 60
    last = None
    while True:
        result = call("GET", pending["status_url"])
        status = result["status"]
        if status != last:
            print(f"  status: {status}", flush=True)
            last = status
        if status == "completed":
            return result, pending
        if status in ("failed", "nsfw", "canceled"):
            state = load_state(scene_id)
            state["pending"].pop(kind, None)
            save_state(scene_id, state)
            die(f"request {pending['request_id']} ended as '{status}' ({result.get('error')}); "
                "failed and nsfw requests are not charged")
        if time.time() > deadline:
            die(f"request {pending['request_id']} still '{status}' after 30 minutes; "
                "run the same command again to keep waiting")
        time.sleep(poll_every)


def finish(scene_id, kind, pending, entry):
    """Record a downloaded output as the newest attempt and select it."""
    state = load_state(scene_id)
    items, selected = ("images", "selected_image") if kind == "image" else ("videos", "selected_video")
    state[items].append(entry)
    state[selected] = entry["n"]
    state["pending"].pop(kind, None)
    save_state(scene_id, state)
    record_spend(scene_id, kind, pending["cost"], pending["request_id"])


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp, \
                    tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp:
                while chunk := resp.read(1 << 16):
                    tmp.write(chunk)
            Path(tmp.name).replace(dest)
            return
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"  download failed ({e}), retrying...", flush=True)
            time.sleep(2 ** attempt)
    die(f"could not download {url}")


# ---------- request bodies

def image_body(cfg, scene, extra=None, seed=None):
    parts = [scene["subject"].rstrip(".") + "."]
    if extra:
        parts.append(extra)
    parts.append(cfg["image_style"])
    body = {
        "prompt": " ".join(parts),
        "negative_prompt": cfg["image_negative"],
        "resolution": "2k",
        "aspect_ratio": "1:1",
        "prompt_extend": False,
        "enable_thinking": False,
    }
    if seed is not None:
        body["seed"] = seed
    return body


def video_body(cfg, scene, image_url, extra=None, duration=VIDEO_SECONDS):
    # Scenes with one-way motion (a train crossing, boats gliding past) set
    # "loop": false and get no last frame; the fan fades hide the restart.
    loop = scene.get("loop", True)
    parts = [scene["motion"]]
    if extra:
        parts.append(extra)
    parts.append(cfg["video_style"])
    if loop and cfg.get("loop_style"):
        parts.append(cfg["loop_style"])
    body = {"prompt": " ".join(parts), "first_frame_url": image_url,
            "duration": duration, "mode": VIDEO_MODE, "aspect_ratio": "1:1", "sound": "off",
            "multi_shots": False}
    if loop:
        body["last_frame_url"] = image_url
    return body


# ---------- commands

def cmd_estimate(args):
    cfg = load_scenes()
    scene = cfg["scenes"][0]
    img = estimate_usd(IMAGE_MODEL, image_body(cfg, scene))
    vid = estimate_usd(VIDEO_MODEL, video_body(cfg, scene, "https://example.com/frame.png"))
    n = len(cfg["scenes"])
    print(f"image ${img:.3f} · {VIDEO_SECONDS}s {VIDEO_MODE} video ${vid:.3f}")
    print(f"{n} scenes, one attempt each: ${n * (img + vid):.2f}")
    print(f"recorded spend so far: ${spent_usd():.2f}")


def cmd_image(args):
    cfg = load_scenes()
    _, scene = find_scene(cfg, args.scene)
    if args.subject:
        scene = {**scene, "subject": args.subject}
    body = image_body(cfg, scene, args.extra, args.seed)
    cost = estimate_usd(IMAGE_MODEL, body)
    if args.dry_run:
        print(json.dumps(body, indent=2, ensure_ascii=False))
        print(f"estimated ${cost:.3f}")
        return
    print(f"{scene['id']}: generating image (${cost:.3f})", flush=True)
    result, pending = run_request(scene["id"], "image", IMAGE_MODEL, body, cost,
                                  {"extra": args.extra, "seed": args.seed, "subject": args.subject},
                                  poll_every=4)

    n = len(load_state(scene["id"])["images"]) + 1
    url = result["images"][0]["url"]
    suffix = Path(url.split("?")[0]).suffix.lower() or ".png"
    raw = OUT / "images" / f"{scene['id']}-{n}{suffix}"
    download(url, raw)
    dest = raw
    if suffix not in (".png", ".jpg", ".jpeg"):
        dest = raw.with_suffix(".png")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw), str(dest)], check=True)
        raw.unlink()
    finish(scene["id"], "image", pending, {"n": n, "file": str(dest.relative_to(OUT)), "url": url,
                                           "request_id": pending["request_id"], **pending["meta"]})
    print(f"saved {dest} (attempt {n}, now selected)")


def cmd_select(args):
    cfg = load_scenes()
    _, scene = find_scene(cfg, args.scene)
    state = load_state(scene["id"])
    if not any(img["n"] == args.n for img in state["images"]):
        die(f"{scene['id']} has no image attempt {args.n}")
    state["selected_image"] = args.n
    save_state(scene["id"], state)
    print(f"{scene['id']}: image {args.n} selected")


def cmd_select_video(args):
    cfg = load_scenes()
    _, scene = find_scene(cfg, args.scene)
    state = load_state(scene["id"])
    if not any(v["n"] == args.n for v in state["videos"]):
        die(f"{scene['id']} has no video attempt {args.n}")
    state["selected_video"] = args.n
    save_state(scene["id"], state)
    print(f"{scene['id']}: video {args.n} selected")


def cmd_video(args):
    cfg = load_scenes()
    _, scene = find_scene(cfg, args.scene)
    state = load_state(scene["id"])
    if not state["selected_image"]:
        die(f"{scene['id']} has no image yet; run: generate.py image {scene['id']}")
    image = next(img for img in state["images"] if img["n"] == state["selected_image"])
    if scene.get("animate") == "spin":
        spin_video(scene["id"], image, args.duration)
        return
    body = video_body(cfg, scene, image["url"], args.extra, args.duration)
    cost = estimate_usd(VIDEO_MODEL, body)
    if args.dry_run:
        print(json.dumps(body, indent=2, ensure_ascii=False))
        print(f"estimated ${cost:.3f}")
        return
    print(f"{scene['id']}: animating image {image['n']} (${cost:.3f}); this takes a few minutes", flush=True)
    result, pending = run_request(scene["id"], "video", VIDEO_MODEL, body, cost,
                                  {"image": image["n"], "extra": args.extra}, poll_every=10)

    n = len(load_state(scene["id"])["videos"]) + 1
    url = result["video"]["url"]
    dest = OUT / "videos" / f"{scene['id']}-{n}.mp4"
    download(url, dest)
    finish(scene["id"], "video", pending, {"n": n, "file": str(dest.relative_to(OUT)), "url": url,
                                           "request_id": pending["request_id"], **pending["meta"]})
    print(f"saved {dest} (attempt {n}, now selected)")


def subject_circle(src, grid=256, limit=12):
    """Center and radius (in source pixels) of the smallest circle around the
    subject's center that holds every non-black pixel."""
    width, height = (int(v) for v in subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(src)], check=True, capture_output=True, text=True).stdout.strip().split(","))
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(src), "-vf",
                          f"scale={grid}:{grid},format=gray", "-f", "rawvideo", "-"],
                         check=True, capture_output=True).stdout
    pts = [(i % grid, i // grid) for i, v in enumerate(raw) if v > limit]
    if not pts:
        die(f"{src} looks completely black")
    cx = (min(x for x, _ in pts) + max(x for x, _ in pts) + 1) / 2
    cy = (min(y for _, y in pts) + max(y for _, y in pts) + 1) / 2
    r = max(math.hypot(x + 0.5 - cx, y + 0.5 - cy) for x, y in pts) + 1
    return cx * width / grid, cy * height / grid, r * max(width, height) / grid


def spin_video(scene_id, image, seconds):
    """Spin a round-ish subject locally (free, exact, loops): one full turn
    about every 7.5 s, with a cheerful bounce and color pulse twice per turn."""
    src = OUT / image["file"]
    cx, cy, r = subject_circle(src)
    # Square canvas around the subject's center, big enough that no part of it
    # leaves the frame while turning, plus room for the 6% bounce.
    side = round(2 * r * 1.08 / 2) * 2
    pad = side
    turns = max(1, round(seconds / 7.5))
    beat = seconds / turns / 2
    n = len(load_state(scene_id)["videos"]) + 1
    dest = OUT / "videos" / f"{scene_id}-{n}.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "30", "-t", str(seconds),
                    "-i", str(src), "-vf",
                    f"pad=iw+{2 * pad}:ih+{2 * pad}:{pad}:{pad}:black,"
                    f"crop={side}:{side}:{round(cx + pad - side / 2)}:{round(cy + pad - side / 2)},"
                    f"rotate=2*PI*{turns}*t/{seconds}:c=black,"
                    # bounce: zoom in up to 6% and back, twice per turn
                    f"zoompan=z='1+0.06*pow(sin(PI*in_time/{beat}),2)':d=1:s={side}x{side}:fps=30"
                    f":x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2',"
                    # shimmer: colors get richer on each bounce; black has no color, so it stays black
                    f"hue=s='1+0.35*pow(sin(PI*t/{beat}),2)',format=yuv420p",
                    "-c:v", "libx264", "-crf", "16", "-r", "30", str(dest)], check=True)
    state = load_state(scene_id)
    state["videos"].append({"n": n, "file": str(dest.relative_to(OUT)), "image": image["n"], "spin": True})
    state["selected_video"] = n
    save_state(scene_id, state)
    print(f"saved {dest} ({turns} full turn(s) in {seconds}s, rendered locally at no cost; attempt {n}, now selected)")


def duration_of(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def selected_video(scene_id):
    state = load_state(scene_id)
    if not state["selected_video"]:
        return None
    video = next(v for v in state["videos"] if v["n"] == state["selected_video"])
    return OUT / video["file"]


def cmd_frames(args):
    cfg = load_scenes()
    _, scene = find_scene(cfg, args.scene)
    src = selected_video(scene["id"])
    if not src:
        die(f"{scene['id']} has no video yet")
    dest = OUT / "frames" / f"{src.stem}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 9 evenly spaced frames; the last one is taken just before the end so the
    # loop point (first vs last frame) can be compared.
    length = duration_of(src)
    times = [i * (length - 0.1) / 8 for i in range(9)]
    inputs = []
    for t in times:
        inputs += ["-ss", f"{t:.3f}", "-i", str(src)]
    graph = "".join(f"[{i}:v]scale=400:400:force_original_aspect_ratio=decrease,"
                    f"pad=400:400:(ow-iw)/2:(oh-ih)/2,trim=end_frame=1,setpts=PTS-STARTPTS[f{i}];"
                    for i in range(9))
    graph += "".join(f"[f{i}]" for i in range(9)) + "xstack=inputs=9:layout=" + "|".join(
        f"{c * 400}_{r * 400}" for r in range(3) for c in range(3))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph,
                    "-frames:v", "1", str(dest)], check=True)
    print(f"saved {dest} (9 frames from {src.name} at "
          f"{', '.join(f'{t:.1f}s' for t in times)}; left-to-right, top-to-bottom)")


def circle_mask(size, feather=0.0):
    """Black overlay that hides everything outside the fan's circle. With
    feather > 0 the outer part of the circle (that fraction of the radius)
    fades smoothly to black, so full scenes look like a glowing round window."""
    mask = OUT / "fan" / f".mask-{size}-{feather:.2f}.png"
    if not mask.exists():
        mask.parent.mkdir(parents=True, exist_ok=True)
        r = size / 2 - 1
        if feather > 0:
            r0 = r * (1 - feather)
            alpha = f"255*clip((hypot(X-{size}/2,Y-{size}/2)-{r0:.1f})/{r - r0:.1f},0,1)"
        else:
            alpha = f"if(gt(hypot(X-{size}/2,Y-{size}/2),{r}),255,0)"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
                        "-i", f"color=black:s={size}x{size},format=rgba",
                        "-vf", f"geq=r=0:g=0:b=0:a='{alpha}'",
                        "-frames:v", "1", str(mask)], check=True)
    return mask


def cmd_fan(args):
    cfg = load_scenes()
    wanted = set(args.scenes)
    mask = circle_mask(args.size, cfg.get("fan_feather", 0.0))
    made = 0
    for i, scene in enumerate(cfg["scenes"], start=1):
        if wanted and scene["id"] not in wanted:
            continue
        src = selected_video(scene["id"])
        if not src:
            print(f"skip {scene['id']}: no video yet")
            continue
        dest = OUT / "fan" / f"{i:02d}-{scene['id']}.mp4"
        length = duration_of(src)
        # Square crop, shrink by --fit so the subject sits inside the fan's circle,
        # crush near-blacks to true black (LEDs off = transparent), mask outside
        # the circle, and fade in/out so clips chain cleanly.
        fit = scene.get("fan_fit") or args.fit or cfg.get("fan_fit") or 0.9
        inner = round(args.size * fit / 2) * 2
        graph = (f"[0:v]crop='min(iw,ih)':'min(iw,ih)',scale={inner}:{inner}:flags=lanczos,"
                 f"pad={args.size}:{args.size}:(ow-iw)/2:(oh-ih)/2:black,"
                 f"colorlevels=rimin=0.06:gimin=0.06:bimin=0.06[v];"
                 f"[v][1:v]overlay=shortest=1,"
                 f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0.0, length - 0.5):.2f}:d=0.4,format=yuv420p")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-loop", "1", "-i", str(mask),
                        "-filter_complex", graph, "-an", "-c:v", "libx264", "-crf", "18",
                        "-maxrate", "10M", "-bufsize", "20M",
                        "-preset", "medium", "-r", "30", "-movflags", "+faststart", str(dest)], check=True)
        print(f"saved {dest}")
        made += 1
    print(f"{made} fan clip(s) written to {OUT / 'fan'}")


def cmd_loop(args):
    clips = sorted((OUT / "fan").glob("[0-9][0-9]-*.mp4"))
    if not clips:
        die("no fan clips yet; run: generate.py fan")
    listing = OUT / "fan" / ".playlist.txt"
    listing.write_text("".join(f"file '{c.name}'\n" for c in clips))
    dest = OUT / "mexico_loop.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", "-movflags", "+faststart", str(dest)], check=True)
    print(f"saved {dest} ({len(clips)} clips, {duration_of(dest):.0f}s)")
    if args.preview:
        # Small copy for sharing in chat or email; use the full-size files on the fan.
        preview = OUT / "mexico_loop_preview.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(dest), "-vf", "scale=540:540",
                        "-c:v", "libx264", "-b:v", "750k", "-maxrate", "900k", "-bufsize", "1800k",
                        "-preset", "slow", "-movflags", "+faststart", str(preview)], check=True)
        print(f"saved {preview} ({preview.stat().st_size / 1e6:.1f} MB)")


def cmd_sheet(args):
    cfg = load_scenes()
    files = []
    for scene in cfg["scenes"]:
        state = load_state(scene["id"])
        if state["selected_image"]:
            img = next(i for i in state["images"] if i["n"] == state["selected_image"])
            files.append(OUT / img["file"])
    if not files:
        die("no images yet")
    cols = 6
    rows = -(-len(files) // cols)
    listing = OUT / ".sheet.txt"
    listing.write_text("".join(f"file '{f}'\nduration 1\n" for f in files))
    dest = OUT / "contact_sheet.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-vf", f"scale=320:320,tile={cols}x{rows}:padding=4:color=0x333333",
                    "-frames:v", "1", str(dest)], check=True)
    print(f"saved {dest} ({len(files)} images, scene order left-to-right)")


def cmd_status(args):
    cfg = load_scenes()
    print(f"{'#':>2}  {'scene':<20} {'images':>6} {'sel':>4} {'videos':>6} {'sel':>4}  fan")
    for i, scene in enumerate(cfg["scenes"], start=1):
        state = load_state(scene["id"])
        fan = (OUT / "fan" / f"{i:02d}-{scene['id']}.mp4").exists()
        print(f"{i:>2}  {scene['id']:<20} {len(state['images']):>6} {state['selected_image'] or '-':>4} "
              f"{len(state['videos']):>6} {state['selected_video'] or '-':>4}  {'yes' if fan else '-'}")
    print(f"recorded spend: ${spent_usd():.2f} of ${float(os.environ.get('HF_BUDGET_USD', '30')):.2f} budget")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--set", default="", help="scene set: uses scenes-NAME.json and out-NAME/")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("estimate").set_defaults(fn=cmd_estimate)

    s = sub.add_parser("image")
    s.add_argument("scene")
    s.add_argument("--extra", help="extra prompt text, e.g. a correction after reviewing an attempt")
    s.add_argument("--subject", help="replace the scene's subject text for this attempt")
    s.add_argument("--seed", type=int)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_image)

    s = sub.add_parser("select")
    s.add_argument("scene")
    s.add_argument("n", type=int)
    s.set_defaults(fn=cmd_select)

    s = sub.add_parser("select-video")
    s.add_argument("scene")
    s.add_argument("n", type=int)
    s.set_defaults(fn=cmd_select_video)

    s = sub.add_parser("video")
    s.add_argument("scene")
    s.add_argument("--extra", help="extra motion instructions")
    s.add_argument("--duration", type=int, default=VIDEO_SECONDS, choices=range(3, 16), metavar="3-15")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_video)

    s = sub.add_parser("frames")
    s.add_argument("scene")
    s.set_defaults(fn=cmd_frames)

    s = sub.add_parser("fan")
    s.add_argument("scenes", nargs="*")
    s.add_argument("--size", type=int, default=FAN_SIZE)
    s.add_argument("--fit", type=float,
                   help="scale the picture to this fraction of the circle (default: the scene's "
                        "or set's fan_fit, else 0.9)")
    s.set_defaults(fn=cmd_fan)

    s = sub.add_parser("loop")
    s.add_argument("--preview", action="store_true", help="also write a small 540px preview copy")
    s.set_defaults(fn=cmd_loop)
    sub.add_parser("sheet").set_defaults(fn=cmd_sheet)
    sub.add_parser("status").set_defaults(fn=cmd_status)

    args = p.parse_args()
    use_set(args.set)
    args.fn(args)


if __name__ == "__main__":
    main()
