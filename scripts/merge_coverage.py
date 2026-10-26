#!/usr/bin/env python3
"""Merge the coverage dumps under a regression dir.

  merge_coverage.py build/regress results

Sums the cocotb-coverage yml files and the Verilator cover counts, writes
coverage.json and coverage.txt, and exits 1 if the main cross isn't 128/128.
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

import yaml

MAIN = "txn.cross"


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "build/regress"
    out = sys.argv[2] if len(sys.argv) > 2 else "results"

    files = glob.glob(os.path.join(src, "**", "cov_*.yml"), recursive=True)
    hits = defaultdict(Counter)
    for f in files:
        for name, item in (yaml.safe_load(open(f)) or {}).items():
            for b, n in (item.get("bins:_hits") or {}).items():
                hits[name][str(b)] += n

    sva = Counter()
    for f in glob.glob(os.path.join(src, "**", "vcov_*.dat"), recursive=True):
        for line in open(f):
            m = re.search(r"\x01o\x02(\w+)", line)
            if line.startswith("C ") and m:
                sva[m.group(1)] += int(line.split()[-1])

    cross = hits[MAIN]
    holes = sorted(b for b, n in cross.items() if n == 0)
    main_cov = {"bins": len(cross), "hit": len(cross) - len(holes),
                "lowest": min(cross.values()) if cross else 0,
                "lowest_bin": min(cross, key=cross.get) if cross else None,
                "samples": sum(cross.values()), "holes": holes}
    report = {"files": len(files), "main_cross": main_cov,
              "points": {k: dict(v) for k, v in sorted(hits.items()) if k != MAIN},
              "sva_covers": dict(sva)}

    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "coverage.json"), "w") as f:
        json.dump(report, f, indent=1)

    lines = [f"merged {len(files)} coverage files",
             f"main cross {main_cov['hit']}/{main_cov['bins']} bins, {main_cov['samples']} samples, "
             f"lowest {main_cov['lowest']} hits ({main_cov['lowest_bin']})"]
    lines += [f"  hole {h}" for h in holes]
    for name, bins in report["points"].items():
        if name.startswith("txn."):
            continue
        lines.append(f"{name}: " + ", ".join(f"{b}={n}" for b, n in bins.items()))
    lines.append("sva covers: " + ", ".join(f"{k}={v}" for k, v in sorted(sva.items())))
    with open(os.path.join(out, "coverage.txt"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    sys.exit(0 if cross and not holes else 1)


if __name__ == "__main__":
    main()
