#!/usr/bin/env python3
"""Perf model against RTL.

  correlate.py --calibrate   the directed tests the handoff delays were set on
  correlate.py               held-out: seeds 10000-10199 with no back-pressure,
                             plus the E1/E2 scenarios, writes results/
"""
import argparse
import json
import os
import sys

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "scripts")]
import run_regression as rr
from models.perf_model import predict

# fifo_full is left out: it's heavy back-pressure by definition and the model assumes none
CALIBRATION = ["smoke_m2p", "smoke_p2m", "single_beat", "max_burst_tail", "all_on_one_port",
               "reload", "sai_balanced", "sai_inverted"]


def rtl_runs(out, items, more=None):
    dump = os.path.join(out, "dump.jsonl")
    s = rr.run(out, items, more=dict(DUMP=dump, **(more or {})), waves=False)
    if s["failed"]:
        sys.exit(f"RTL failures in {out}: {s['failed']}")
    return [json.loads(line) for line in open(dump)]


def total(rec):
    first = min(c for _, c in rec["loads"])
    return max(c for _, c in rec["dones"]) - first


def compare(rec):
    m = predict(rec["descs"], rec["depth"], rec["fabric"])
    rtl, mod = total(rec), m["total"]
    # pair bursts by channel and order within the channel
    by_ch = {}
    for t in rec["txns"]:
        by_ch.setdefault(t[0], [[], []])[0].append(t)
    for t in m["txns"]:
        by_ch.setdefault(t[0], [[], []])[1].append(t)
    lat = []
    for a, b in by_ch.values():
        for x, y in zip(a, b):
            lat.append(abs((x[7] - x[4]) - (y[7] - y[4])))
    label = rec["name"] if rec["name"] != "sai" else f"sai_{rec['params']['map']}_bg{rec['params']['bg']}"
    return {"name": label, "seed": rec["seed"], "rtl": rtl, "model": mod,
            "err": abs(mod - rtl) / rtl, "lat_abs_err": lat}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "perf"))
    ap.add_argument("--results", default=os.path.join(ROOT, "results"))
    a = ap.parse_args()

    if a.calibrate:
        recs = rtl_runs(os.path.join(a.out, "calib"), [(t, 1) for t in CALIBRATION])
        for r in map(compare, recs):
            print(f"{r['name']:18} rtl {r['rtl']:6}  model {r['model']:6}  err {100 * r['err']:.2f}%  "
                  f"burst latency mae {np.mean(r['lat_abs_err']):.2f}")
        return

    recs = rtl_runs(os.path.join(a.out, "eval_rand"), [("rand", s) for s in range(10000, 10200)],
                    more={"BP": "none"})
    for inv in ("bal", "inv"):
        for bg in (0, 5):
            recs += rtl_runs(os.path.join(a.out, f"eval_sai_{inv}_{bg}"), [("sai", 0)],
                             more={"MAP": inv, "BG": bg})
    rows = [compare(r) for r in recs]
    errs = np.array([r["err"] for r in rows])
    lat = np.concatenate([r["lat_abs_err"] for r in rows])
    worst = max(rows, key=lambda r: r["err"])
    out = {
        "scenarios": len(rows),
        "total_cycle_error": {"mean": float(errs.mean()), "p95": float(np.percentile(errs, 95)),
                              "max": float(errs.max()), "max_at": f"{worst['name']} seed {worst['seed']}"},
        "burst_latency_mae_cycles": float(lat.mean()),
        "bursts": int(len(lat)),
        "rows": [{k: v for k, v in r.items() if k != "lat_abs_err"} for r in rows],
    }
    os.makedirs(a.results, exist_ok=True)
    with open(os.path.join(a.results, "correlation.json"), "w") as f:
        json.dump(out, f, indent=1)

    rtl = np.array([r["rtl"] for r in rows])
    mod = np.array([r["model"] for r in rows])
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(rtl, mod, s=10, alpha=0.6)
    lim = [rtl.min() * 0.8, rtl.max() * 1.2]
    ax.plot(lim, lim, "k--", lw=1, label="y = x")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("RTL total cycles")
    ax.set_ylabel("model total cycles")
    ax.set_title(f"{len(rows)} held-out scenarios, max error {100 * errs.max():.2f}%")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(a.results, "correlation.png"), dpi=120)

    t = out["total_cycle_error"]
    print(f"{len(rows)} scenarios: total-cycle error mean {100 * t['mean']:.2f}%, p95 {100 * t['p95']:.2f}%, "
          f"max {100 * t['max']:.2f}% ({t['max_at']}); burst latency MAE {out['burst_latency_mae_cycles']:.2f} cycles")


if __name__ == "__main__":
    main()
