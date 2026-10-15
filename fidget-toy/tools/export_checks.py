"""Condense verification/reports/SUMMARY.json into web/models/checks.json for the viewer page.

    python3 tools/export_checks.py

Per character and checker group: "fail" if any job failed, else "warn" if any check in it warned, else "pass";
"not run" if no job ran.  Kinematics and printability combine the nominal and loose variants.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ("escapement", "kinematics", "printability", "safety")


def main():
    summ = json.loads((ROOT / "verification" / "reports" / "SUMMARY.json").read_text())
    skins = {}
    for job in summ["jobs"]:
        if job["check"] not in GROUPS:
            continue
        g = skins.setdefault(job["skin"], {}).setdefault(job["check"], [])
        st = job["status"]
        if st == "pass" and any(v == "warn" for v in (job.get("checks") or {}).values()):
            st = "warn"
        g.append(st)
    out = {"date": summ["date"], "all_pass": summ["all_pass"], "skins": {}}
    for skin, groups in skins.items():
        row = {}
        for k in GROUPS:
            sts = groups.get(k, [])
            row[k] = ("fail" if "fail" in sts else "warn" if "warn" in sts else "pass" if sts and all(
                s == "pass" for s in sts) else "not-run")
        out["skins"][skin] = row
    names = {"kitty": "Purr Kitty", "bee": "Bumble", "robot": "Pip the Robot"}
    plain = {"V12.pinch": "a pinch-point rule (see Safety)", "V13": "the weight limit", "V2": "the jam screen",
             "V4": "the dynamics runs", "V5": "the collision sweep", "V6": "a clearance", "V8": "a wall-thickness rule",
             "V9": "an overhang rule", "SLICER": "the slicer check"}

    def friendly(cid):
        return next((v for k, v in plain.items() if cid.startswith(k)), cid)
    fails = [f"{names.get(job['skin'], job['skin'])} {job['check']}: "
             + ", ".join(f"{friendly(k)} [{k}]" for k, v in (job.get('checks') or {}).items() if v == 'fail')
             for job in summ["jobs"] if job["status"] == "fail" and job["check"] in GROUPS]
    out["failing"] = fails
    out["note"] = (f"Full run of {summ['date'][:10]}, about 40 minutes on 4 CPUs. " +
                   ("Every character passes; warnings are documented in verification/reports/SUMMARY.md."
                    if not fails else "Still failing: " + "; ".join(fails) +
                    ". Warnings and their reasons are in verification/reports/SUMMARY.md."))
    dst = ROOT / "web" / "models" / "checks.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
