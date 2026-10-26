#!/usr/bin/env python3
"""Apply each mNN.patch to a scratch copy of rtl/, run the directed tests plus
100 seeds against it and expect something to fail. Stops a mutant at its first
failure and records which check caught it.

  run_mutations.py [m04 m09 ...]
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import run_regression as rr

OUT = os.path.join(ROOT, "build", "mut")
SEEDS = range(100)


def killer(out, summary):
    """Name the check that fired first: an SVA label from the sim log, else the scoreboard check."""
    for log in sorted(glob.glob(os.path.join(out, "d*.log"))):
        m = re.search(r"Assertion failed in \S+: (A\d \w+)", open(log, errors="replace").read())
        if m:
            return m.group(1)
    for errs in summary["errors"].values():
        m = re.match(r"check (\d)", errs[0])
        if m:
            return f"scoreboard check {m.group(1)}"
    return "simulator stopped"


def mutate(patch):
    name = os.path.basename(patch)[:-len(".patch")]
    out = os.path.join(OUT, name)
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "rtl"), os.path.join(out, "rtl"))
    subprocess.run(["patch", "-s", "-p1", "-d", out, "-i", patch], check=True)
    items = [(t, 1) for t in rr.CFG["directed"]] + [("rand", s) for s in SEEDS]
    s = rr.run(out, items, rtl=os.path.join(out, "rtl"), stop_on_fail=True, waves=False)
    if not s["failed"]:
        return {"mutant": name, "killed": False, "by": None, "first_fail": None}
    test, seed = s["failed"][0]
    return {"mutant": name, "killed": True, "by": killer(out, s), "first_fail": f"{test} seed {seed}"}


def main():
    patches = sorted(glob.glob(os.path.join(ROOT, "mutations", "m*.patch")))
    if sys.argv[1:]:
        patches = [p for p in patches if os.path.basename(p)[:3] in sys.argv[1:]]
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(mutate, patches))

    desc = {}
    for line in open(os.path.join(ROOT, "mutations", "README")):
        if line[:1] == "m":
            k, v = line.split(" ", 1)
            desc[k] = v.strip()
    killed = sum(r["killed"] for r in rows)
    sva = sorted({r["by"].split()[0] for r in rows if r["by"] and r["by"].startswith("A")})
    report = {"killed": killed, "total": len(rows), "assertions_that_killed": sva, "mutants": rows}
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "mutation.json"), "w") as f:
        json.dump(report, f, indent=1)

    lines = [f"{killed}/{len(rows)} mutants killed", ""]
    for r in rows:
        lines.append(f"{r['mutant']}  {desc.get(r['mutant'], ''):45}  "
                     + (f"killed by {r['by']} ({r['first_fail']})" if r["killed"] else "SURVIVED"))
    lines += ["", f"assertions that killed a mutant: {', '.join(sva) or 'none'}"]
    with open(os.path.join(ROOT, "results", "mutation.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(0 if killed == len(rows) else 1)


if __name__ == "__main__":
    main()
