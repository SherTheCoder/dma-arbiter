#!/usr/bin/env python3
"""Collect the last full run into results/summary.json and print a short text
version to copy numbers from."""
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results")


def load(path):
    p = os.path.join(ROOT, path)
    return json.load(open(p)) if os.path.exists(p) else None


def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except FileNotFoundError:
        return None


def bugs():
    """Entries under '## bugs hit along the way' in docs/notes.md start with '### '."""
    notes = open(os.path.join(ROOT, "docs", "notes.md")).read()
    sec = notes.split("## bugs hit along the way", 1)[1]
    entries = sec.split("\n### ")[1:]
    missed = sum("directed tests: missed" in e for e in entries)
    return len(entries), missed


def synth():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "build", "synth", "stat_n*.json"))):
        n = re.search(r"stat_n(\d+)", f).group(1)
        m = list(json.load(open(f))["modules"].values())[0]
        out[f"num_ch_{n}"] = {"cells": m["num_cells"],
                              "flops": sum(v for k, v in m["num_cells_by_type"].items() if "DFF" in k)}
    return out


def main():
    shards = [load(f"build/regress/shard{k}.json") for k in range(4)]
    directed = load("build/regress/directed.json")
    if None in shards or directed is None:
        sys.exit("no full regression under build/regress, run make regress first")
    cov = load("results/coverage.json")
    mut = load("results/mutation.json")
    corr = load("results/correlation.json")
    mp = load("results/mapping.json")
    sw = load("results/sweep.json")
    n_bugs, n_missed = bugs()

    s = {
        "regression": {
            "seeds_run": sum(x["items"] for x in shards),
            "seeds_passed": sum(x["passed"] for x in shards),
            "port_transactions": sum(x["txns"] for x in shards),
            "directed_passed": f"{directed['passed']}/{directed['items']}",
            "failing_seeds": [f for x in shards for f in x["failed"]],
        },
        "coverage": cov and {"main_cross_hit": cov["main_cross"]["hit"], "main_cross_bins": cov["main_cross"]["bins"],
                             "lowest_hits": cov["main_cross"]["lowest"], "holes": cov["main_cross"]["holes"]},
        "assertions_live": mut and f"{len(mut['assertions_that_killed'])}/6",
        "mutants_killed": mut and f"{mut['killed']}/{mut['total']}",
        "real_bugs_found": n_bugs,
        "bugs_directed_tests_missed": n_missed,
        "model_error": corr and {k: corr["total_cycle_error"][k] for k in ("mean", "p95", "max")}
                       | {"scenarios": corr["scenarios"], "burst_latency_mae": corr["burst_latency_mae_cycles"]},
        "mapping": mp and {e: {"throughput_loss": mp[e]["loss"]["mean"],
                               "loss_min": mp[e]["loss"]["min"], "loss_max": mp[e]["loss"]["max"],
                               "tx_latency_ratio": mp[e]["tx_latency_ratio"]["mean"],
                               "rx_latency_ratio": mp[e]["rx_latency_ratio"]["mean"]} for e in ("E1", "E2")},
        "sweep": sw and {"loss_min": min(r["loss"]["mean"] for r in sw["rows"]),
                         "loss_max": max(r["loss"]["mean"] for r in sw["rows"]),
                         "pen0_bg0_loss": next(r["loss"]["mean"] for r in sw["rows"] if r["pen"] == 0 and r["bg"] == 0),
                         "inverted_beats_balanced": sw["inverted_beats_balanced"]},
        "synth": synth(),
        "tools": {"verilator": sh("verilator", "--version"), "yosys": sh("yosys", "-V"),
                  "python": sys.version.split()[0],
                  "cocotb": sh(sys.executable, "-c", "import cocotb; print(cocotb.__version__)"),
                  "pyuvm": sh(sys.executable, "-c", "import importlib.metadata as m; print(m.version('pyuvm'))")},
        "commit": sh("git", "rev-parse", "--short", "HEAD"),
    }
    with open(os.path.join(RES, "summary.json"), "w") as f:
        json.dump(s, f, indent=1)

    r = s["regression"]
    print(f"seeds {r['seeds_passed']}/{r['seeds_run']} passed, {r['port_transactions']} port transactions, "
          f"directed {r['directed_passed']}")
    if cov:
        print(f"main cross {s['coverage']['main_cross_hit']}/{s['coverage']['main_cross_bins']}, "
              f"lowest bin {s['coverage']['lowest_hits']} hits")
    if mut:
        print(f"mutants killed {s['mutants_killed']}, assertions live {s['assertions_live']}")
    print(f"real bugs {n_bugs}, directed tests would have missed {n_missed}")
    if corr:
        e = s["model_error"]
        print(f"model error over {e['scenarios']} held-out scenarios: mean {100 * e['mean']:.2f}%, "
              f"p95 {100 * e['p95']:.2f}%, max {100 * e['max']:.2f}%")
    if mp:
        for k, v in s["mapping"].items():
            print(f"{k}: inverted TX loses {100 * v['throughput_loss']:.1f}% throughput "
                  f"({100 * v['loss_min']:.1f}-{100 * v['loss_max']:.1f}), "
                  f"TX worst latency x{v['tx_latency_ratio']:.2f}, RX x{v['rx_latency_ratio']:.2f}")
    if sw:
        w = s["sweep"]
        print(f"sweep: loss {100 * w['loss_min']:.1f}% to {100 * w['loss_max']:.1f}%, "
              f"{100 * w['pen0_bg0_loss']:.1f}% at penalty 0 with no background")
    for k, v in s["synth"].items():
        print(f"synth {k}: {v['cells']} cells, {v['flops']} flops")
    print(f"commit {s['commit']}")


if __name__ == "__main__":
    main()
