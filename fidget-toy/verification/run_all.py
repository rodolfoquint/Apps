#!/usr/bin/env python3
"""Run the whole verification suite for every skin and write one summary.

    python3 verification/run_all.py                    # build + all checks, kitty / bee / robot
    python3 verification/run_all.py --skins kitty      # one skin (comma list)
    python3 verification/run_all.py --quick            # development run (see below)
    python3 verification/run_all.py --no-build         # re-check the exports already in stl/ (must be current)
    python3 verification/run_all.py --jobs 4 --render  # also re-render every skin / variant while building

What runs (per skin):

    build          python3 -m purrbobble.build --skin S --all       (nominal, deep, shallow, loose; STL/3MF/json)
    basic          v_basic.py        nominal                         V1, V7, mass, inertia (+ --slice unless --quick)
    escapement     v_escapement.py   nominal                         V2, V3, V4 (dynamics), V13
    kinematics     v_kinematics.py   nominal + loose                 V5, V6, V11 ...
    printability   v_printability.py nominal + loose                 V8, V9, layers (+ PrusaSlicer unless --quick)
    safety         v_safety.py       nominal                         V10, V12 (pinch audit), V14, design review

--quick: escapement --quick (reduced V4 run set), safety --fast (half the pinch-audit poses), no slicer.  A quick run
is for iteration only; the release gate is the full run.

Every job writes its usual report (verification/reports/<skin>/...) plus a log in verification/reports/run_all/.
The summary goes to verification/reports/SUMMARY.md and SUMMARY.json.  Exit status: 0 only if every job ran and no
check failed (warnings allowed).

Jobs run in parallel on --jobs CPU slots (default: all CPUs); each job declares how many slots it uses (the
escapement check runs its V4 simulations on 2 worker processes), so the machine is never oversubscribed.  A full
run of the three skins takes about 30-40 min on 4 CPUs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VER = REPO / "verification"
REPORTS = VER / "reports"
LOGS = REPORTS / "run_all"
SKINS = ("kitty", "bee", "robot")
PY = sys.executable or "python3"


# ------------------------------------------------------------------------------------------------ jobs
class Job:
    def __init__(self, skin, check, variant, cmd, report, slots=1, after=None, timeout=3600):
        self.skin, self.check, self.variant = skin, check, variant
        self.cmd, self.report, self.slots = cmd, Path(report) if report else None, slots
        self.after = after or []          # job keys that must finish first
        self.timeout = timeout
        self.proc = self.log = None
        self.t0 = self.t1 = None
        self.rc = None

    @property
    def key(self):
        return f"{self.skin}:{self.check}:{self.variant}"

    @property
    def log_path(self):
        return LOGS / f"{self.skin}_{self.check}_{self.variant}.log"


def make_jobs(skins, quick, build, render, slicer):
    jobs = []
    for s in skins:
        bkey = []
        if build:
            cmd = [PY, "-m", "purrbobble.build", "--skin", s, "--all", "-q"] + ([] if render else ["--no-render"])
            jobs.append(Job(s, "build", "all", cmd, None, slots=1, timeout=1800))
            bkey = [f"{s}:build:all"]
        rep = REPORTS / s
        cmd = [PY, str(VER / "v_basic.py"), "--skin", s, "--variant", "nominal"] + (["--slice"] if slicer else [])
        jobs.append(Job(s, "basic", "nominal", cmd, rep / "basic.json", after=bkey))
        cmd = [PY, str(VER / "v_escapement.py"), "--skin", s, "--variant", "nominal", "--jobs", "2", "--no-gif"]
        cmd += ["--quick"] if quick else []
        jobs.append(Job(s, "escapement", "nominal", cmd, rep / "escapement.json", slots=2, after=bkey, timeout=5400))
        for v in ("nominal", "loose"):
            sfx = "" if v == "nominal" else f"_{v}"
            cmd = [PY, str(VER / "v_kinematics.py"), "--skin", s, "--variant", v, "-q"]
            jobs.append(Job(s, "kinematics", v, cmd, rep / f"kinematics{sfx}.json", after=bkey))
            cmd = [PY, str(VER / "v_printability.py"), "--skin", s, "--variant", v, "-q"]
            cmd += [] if slicer else ["--no-slicer"]
            jobs.append(Job(s, "printability", v, cmd, rep / f"printability{sfx}.json", after=bkey))
        cmd = [PY, str(VER / "v_safety.py"), "--skin", s, "--variant", "nominal", "-q"] + (["--fast"] if quick else [])
        jobs.append(Job(s, "safety", "nominal", cmd, rep / "safety.json", after=bkey, timeout=5400))
    return jobs


def run_jobs(jobs, slots_total, verbose=True):
    LOGS.mkdir(parents=True, exist_ok=True)
    pending = list(jobs)
    running = []
    done = {}
    t_start = time.time()
    # longest first among the ready ones (safety, escapement, printability ...)
    weight = {"build": 0, "safety": 1, "escapement": 2, "printability": 3, "kinematics": 4, "basic": 5}
    while pending or running:
        for j in list(running):
            rc = j.proc.poll()
            if rc is None and time.time() - j.t0 > j.timeout:
                j.proc.kill()
                rc = -9
                j.log.write(f"\n[run_all] TIMEOUT after {j.timeout} s\n")
            if rc is not None:
                j.rc, j.t1 = rc, time.time()
                j.log.close()
                running.remove(j)
                done[j.key] = j
                if verbose:
                    print(f"[run_all] {time.time() - t_start:7.1f}s done  {j.key:32s} rc={rc} ({j.t1 - j.t0:.0f}s)",
                          flush=True)
        used = sum(j.slots for j in running)
        ready = [j for j in pending if all(a in done for a in j.after)]
        ready.sort(key=lambda j: weight.get(j.check, 9))
        for j in ready:
            if any(done[a].rc != 0 for a in j.after):
                j.rc, j.t0, j.t1 = -2, time.time(), time.time()
                LOGS.mkdir(parents=True, exist_ok=True)
                j.log_path.write_text("[run_all] skipped: a prerequisite job failed\n")
                pending.remove(j)
                done[j.key] = j
                continue
            if used + j.slots > slots_total and running:
                continue
            j.log = open(j.log_path, "w")
            j.log.write("$ " + " ".join(j.cmd) + "\n")
            j.log.flush()
            j.t0 = time.time()
            j.proc = subprocess.Popen(j.cmd, cwd=REPO, stdout=j.log, stderr=subprocess.STDOUT,
                                      env=dict(os.environ, PYTHONUNBUFFERED="1"))
            running.append(j)
            pending.remove(j)
            used += j.slots
            if verbose:
                print(f"[run_all] {time.time() - t_start:7.1f}s start {j.key:32s} ({j.slots} slot{'s' * (j.slots > 1)})",
                      flush=True)
        time.sleep(0.5)
    return done, time.time() - t_start


# ------------------------------------------------------------------------------------------------ reports
def _status_of(v):
    if isinstance(v, dict):
        if "status" in v:
            return str(v["status"])
        if "pass" in v:
            return "pass" if v["pass"] else "fail"
    if isinstance(v, bool):
        return "pass" if v else "fail"
    return None


def parse_report(job):
    """-> (overall status, {check id: status}, [notes]) from the job's JSON report (formats differ per tool)."""
    if job.check == "build":
        return ("pass" if job.rc == 0 else "fail"), {}, []
    if job.report is None or not job.report.exists() or (job.t0 and job.report.stat().st_mtime < job.t0 - 1):
        return "error", {}, [f"no fresh report ({job.report}); exit code {job.rc}"]
    try:
        d = json.loads(job.report.read_text())
    except Exception as e:  # pragma: no cover
        return "error", {}, [f"unreadable report: {e}"]
    checks, notes = {}, []
    if isinstance(d.get("checks"), list):                       # kinematics, safety, escapement
        for c in d["checks"]:
            cid = c.get("id") or c.get("name")
            checks[str(cid)] = str(c.get("status"))
            if c.get("status") in ("fail", "warn"):
                m = c.get("measured", c.get("detail", ""))
                notes.append(f"[{c.get('status').upper()}] {cid}: {json.dumps(m, default=str)[:300]}")
    elif isinstance(d.get("checks"), dict) and not isinstance(d.get("summary"), dict):   # escapement
        for cid, c in d["checks"].items():
            st = _status_of(c) or "?"
            checks[str(cid)] = st
            if st in ("fail", "warn"):
                notes.append(f"[{st.upper()}] {cid}: {json.dumps(c.get('measured', ''), default=str)[:300]}")
    elif isinstance(d.get("summary"), dict):                    # printability
        checks = {k: str(v) for k, v in d["summary"].items()}
        for f in d.get("findings", []):
            if f.get("severity") in ("fail", "warn"):
                notes.append(f"[{f['severity'].upper()}] {f.get('check')}: {str(f.get('finding'))[:300]}")
    else:                                                       # basic
        for k in ("V1", "V7"):
            if k in d:
                checks[k] = _status_of(d[k]) or "?"
        hi = (d.get("mass") or {}).get("head_inertia")
        if hi:
            checks["head_inertia"] = "pass" if hi.get("pass") else "fail"
        for w in (d.get("skin_contract") or {}).get("warnings", []):
            notes.append(f"[NOTE] skin contract: {w}")
    if job.check == "escapement":
        for k in ("V2", "V3", "V4", "V13"):
            if k in d and k not in checks:
                checks[k] = _status_of(d[k]) or "?"
        for w in d.get("warnings", []) or []:
            notes.append(f"[WARN] {str(w)[:300]}")
    st = [v for v in checks.values()]
    if d.get("pass") is False or "fail" in st or "error" in st:
        overall = "fail"
    elif "warn" in st:
        overall = "warn"
    else:
        overall = "pass" if d.get("pass", True) else "fail"
    if job.rc not in (0, None) and overall != "fail":
        notes.append(f"exit code {job.rc} although the report reads {overall}")
        overall = "fail"
    return overall, checks, notes


def summarise(done, wall, args):
    rows = []
    for key, j in done.items():
        overall, checks, notes = parse_report(j) if j.rc != -2 else ("skipped", {}, ["prerequisite failed"])
        rows.append({"skin": j.skin, "check": j.check, "variant": j.variant, "status": overall, "exit_code": j.rc,
                     "runtime_s": round((j.t1 or 0) - (j.t0 or 0), 1), "checks": checks, "notes": notes,
                     "report": str(j.report.relative_to(REPO)) if j.report else None,
                     "log": str(j.log_path.relative_to(REPO))})
    order = {c: i for i, c in enumerate(("build", "basic", "escapement", "kinematics", "printability", "safety"))}
    rows.sort(key=lambda r: (SKINS.index(r["skin"]) if r["skin"] in SKINS else 9, order.get(r["check"], 9),
                             r["variant"] != "nominal", r["variant"]))
    all_pass = all(r["status"] in ("pass", "warn") for r in rows)
    js = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "quick": args.quick, "slicer": not args.quick and not args.no_slicer,
          "skins": args.skins, "wall_time_s": round(wall, 1), "all_pass": all_pass, "jobs": rows}
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "SUMMARY.json").write_text(json.dumps(js, indent=1, default=str))

    sym = {"pass": "pass", "warn": "warn", "fail": "**FAIL**", "error": "**ERROR**", "skipped": "skipped"}
    cols = [("basic", "nominal"), ("escapement", "nominal"), ("kinematics", "nominal"), ("kinematics", "loose"),
            ("printability", "nominal"), ("printability", "loose"), ("safety", "nominal")]
    L = ["# Purr-Bobble verification summary", "",
         f"Run {js['date']} - {'QUICK (development) run' if args.quick else 'full run'}"
         f"{'' if js['slicer'] else ', no slicer'} - wall time {wall / 60:.1f} min - "
         f"**{'ALL PASS' if all_pass else 'FAILURES'}** (warnings allowed).", "",
         "Generated by `python3 verification/run_all.py`; per-check reports in `verification/reports/<skin>/`, logs in "
         "`verification/reports/run_all/`.", "",
         "| skin | build | " + " | ".join(f"{c} ({v})" for c, v in cols) + " |",
         "|---|---|" + "---|" * len(cols)]
    for s in args.skins:
        get = {(r["check"], r["variant"]): r for r in rows if r["skin"] == s}
        b = get.get(("build", "all"))
        cells = [sym.get(b["status"], b["status"]) if b else "-"]
        for c in cols:
            r = get.get(c)
            cells.append(sym.get(r["status"], r["status"]) if r else "-")
        L.append(f"| {s} | " + " | ".join(cells) + " |")
    L += ["", "## Check details", ""]
    for r in rows:
        if r["check"] == "build":
            continue
        bad = {k: v for k, v in r["checks"].items() if v not in ("pass", "not-run", "None")}
        L.append(f"- **{r['skin']} / {r['check']} ({r['variant']})**: {r['status']} in {r['runtime_s']:.0f} s"
                 + (f" - non-pass: {', '.join(f'{k}={v}' for k, v in bad.items())}" if bad else ""))
    fails = [r for r in rows if r["status"] not in ("pass", "warn")]
    L += ["", "## Failures", ""]
    if not fails:
        L.append("None.")
    for r in fails:
        L.append(f"### {r['skin']} / {r['check']} ({r['variant']}) - {r['status']}")
        L += [f"- {n}" for n in r["notes"] if not n.startswith("[WARN]") and not n.startswith("[NOTE]")][:20]
        L.append(f"- log: `{r['log']}`")
        L.append("")
    L += ["", "## Warnings (accepted trade-offs and cosmetic notes)", ""]
    for r in rows:
        ws = [n for n in r["notes"] if n.startswith("[WARN]") or n.startswith("[NOTE]")]
        if ws:
            L.append(f"**{r['skin']} / {r['check']} ({r['variant']})**")
            L += [f"- {w}" for w in ws[:25]]
            L.append("")
    (REPORTS / "SUMMARY.md").write_text("\n".join(L) + "\n")
    return all_pass, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skins", default=",".join(SKINS), help="comma list (default: kitty,bee,robot)")
    ap.add_argument("--quick", action="store_true", help="development run: reduced V4, half pinch poses, no slicer")
    ap.add_argument("--no-build", action="store_true", help="use the current exports (stl/) instead of rebuilding")
    ap.add_argument("--render", action="store_true", help="also re-render while building")
    ap.add_argument("--no-slicer", action="store_true", help="skip PrusaSlicer in the full run")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4, help="CPU slots (default: all CPUs)")
    ap.add_argument("--checks", default="", help="only these checks (comma list of basic,escapement,kinematics,"
                                                  "printability,safety)")
    args = ap.parse_args(argv)
    args.skins = [s.strip() for s in args.skins.split(",") if s.strip()]
    for s in args.skins:
        if s not in SKINS:
            ap.error(f"unknown skin {s!r} (known: {', '.join(SKINS)})")
    slicer = not args.quick and not args.no_slicer
    jobs = make_jobs(args.skins, args.quick, not args.no_build, args.render, slicer)
    if args.checks:
        keep = set(c.strip() for c in args.checks.split(",")) | {"build"}
        jobs = [j for j in jobs if j.check in keep]
    print(f"[run_all] {len(jobs)} jobs on {args.jobs} slots ({'quick' if args.quick else 'full'} run)", flush=True)
    done, wall = run_jobs(jobs, max(1, args.jobs))
    all_pass, rows = summarise(done, wall, args)
    print(f"[run_all] {'ALL PASS' if all_pass else 'FAILURES'} in {wall / 60:.1f} min -> "
          f"{(REPORTS / 'SUMMARY.md').relative_to(REPO)}", flush=True)
    for r in rows:
        if r["status"] not in ("pass", "warn"):
            print(f"  FAIL {r['skin']}/{r['check']}/{r['variant']}: {r['notes'][:3]}", flush=True)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
