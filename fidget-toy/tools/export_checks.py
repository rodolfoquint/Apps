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
    n_fail = sum(v == "fail" for r in out["skins"].values() for v in r.values())
    out["note"] = (f"Full run {summ['date']}: " + ("every character passes; warnings are documented in "
                   "verification/reports/SUMMARY.md." if n_fail == 0 else
                   f"{n_fail} checker group(s) still failing; see verification/reports/SUMMARY.md."))
    dst = ROOT / "web" / "models" / "checks.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
