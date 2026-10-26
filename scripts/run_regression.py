#!/usr/bin/env python3
"""Directed tests and random seeds through the cocotb testbench.

One simulator process per batch, reset between scenarios. An assertion failure
stops Verilator, so a batch that dies is restarted after the seed that killed
it. Every failure is then rerun alone with waves to confirm it.

  run_regression.py --seeds 0:1000 --shard 2/4
  run_regression.py --directed
  run_regression.py --one rand 417
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TB = os.path.join(ROOT, "tb")
CFG = yaml.safe_load(open(os.path.join(ROOT, "config", "regression.yaml")))


def depth_for(test, seed):
    if test == "fifo_full":
        return 2
    if test == "rand" and seed % CFG["depth2_every"] == CFG["depth2_every"] - 1:
        return 2
    return 4


def make(log, *args, **env):
    cmd = ["make", "-C", TB] + list(args) + [f"{k}={v}" for k, v in env.items()]
    with open(log, "a") as f:
        f.write("$ " + " ".join(cmd) + "\n")
        f.flush()
        return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT).returncode


def sim_build(out, depth):
    return os.path.join(out, f"sim_build_d{depth}")


def build(out, depth, rtl=None):
    sb = sim_build(out, depth)
    extra = {"RTL_DIR": rtl} if rtl else {}
    rc = make(os.path.join(out, f"build_d{depth}.log"), os.path.join(sb, "Vtop"),
              DEPTH=depth, SIM_BUILD=sb, **extra)
    if rc:
        sys.exit(f"build failed, see {out}/build_d{depth}.log")


def read_results(path):
    got = {}
    if os.path.exists(path):
        for line in open(path):
            r = json.loads(line)
            got[(r["test"], r["seed"])] = r
    return got


def run_batch(out, depth, items, tag, rtl=None, stop_on_fail=False):
    """items are (test, seed) in the order cocotb will run them."""
    results = os.path.join(out, f"results_{tag}.jsonl")
    log = os.path.join(out, f"{tag}.log")
    extra = {"RTL_DIR": rtl} if rtl else {}
    crashed = []
    todo = list(items)
    n = 0
    while todo:
        directed = [t for t, _ in todo if t != "rand"]
        seeds = [s for t, s in todo if t == "rand"]
        env = dict(DEPTH=depth, SIM_BUILD=sim_build(out, depth), RESULTS=results,
                   COV=os.path.join(out, f"cov_{tag}_{n}.yml"),
                   VCOV=os.path.join(out, f"vcov_{tag}_{n}.dat"),
                   COCOTB_RESULTS_FILE=os.path.join(out, f"{tag}_{n}.xml"), **extra)
        if seeds:
            env["SEEDS"] = ",".join(map(str, seeds))
        make(log, f"TEST={'|'.join(directed + (['rand'] if seeds else []))}", **env)
        n += 1
        got = read_results(results)
        missing = [i for i in todo if i not in got]
        if not missing:
            break
        # the first one missing is the one that stopped the simulator
        crashed.append(missing[0])
        if stop_on_fail:
            break
        todo = missing[1:]
    got = read_results(results)
    return [got.get(i) for i in items], crashed


def confirm(out, depth, test, seed, rtl=None):
    """Rerun one failure alone, with an FST dump. True if it fails again."""
    name = f"fail_{test}_{seed}"
    results = os.path.join(out, name + ".jsonl")
    extra = {"RTL_DIR": rtl} if rtl else {}
    make(os.path.join(out, name + ".log"), f"TEST={test}", WAVES=1,
         WAVE_FILE=os.path.join(out, name + ".fst"), DEPTH=depth,
         SIM_BUILD=sim_build(out, depth), RESULTS=results,
         COCOTB_RESULTS_FILE=os.path.join(out, name + ".xml"),
         **({"SEEDS": seed} if test == "rand" else {"SEED": seed}), **extra)
    r = read_results(results).get((test, seed))
    return r is None or not r["ok"]


def run(out, items, rtl=None, stop_on_fail=False, waves=True):
    """Run (test, seed) items on whichever builds they need. Returns a summary dict."""
    os.makedirs(out, exist_ok=True)
    summary = {"items": len(items), "passed": 0, "failed": [], "confirmed": [], "txns": 0, "cycles": 0,
               "errors": {}}
    for depth in (4, 2):
        mine = [i for i in items if depth_for(*i) == depth]
        if not mine:
            continue
        build(out, depth, rtl)
        res, crashed = run_batch(out, depth, mine, f"d{depth}", rtl, stop_on_fail)
        for item, r in zip(mine, res):
            if r and r["ok"]:
                summary["passed"] += 1
                summary["txns"] += r["txns"]
                summary["cycles"] += r["cycles"]
            elif r or item in crashed:
                summary["failed"].append(list(item))
                summary["errors"][f"{item[0]}:{item[1]}"] = r["errors"] if r else ["simulator stopped"]
            if stop_on_fail and summary["failed"]:
                break
        if stop_on_fail and summary["failed"]:
            break
    if waves:
        for test, seed in summary["failed"]:
            if confirm(out, depth_for(test, seed), test, seed, rtl):
                summary["confirmed"].append([test, seed])
    return summary


def seed_range(s):
    a, b = s.split(":")
    return int(a), int(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", help="a:b, random seeds")
    ap.add_argument("--shard", help="k/n, run the k-th contiguous slice of the seeds")
    ap.add_argument("--directed", action="store_true")
    ap.add_argument("--jobs", type=int, default=1, help="run all n shards here, this many at once")
    ap.add_argument("--one", nargs=2, metavar=("TEST", "SEED"))
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "regress"))
    a = ap.parse_args()
    a.out = os.path.abspath(a.out)

    if a.one:
        test, seed = a.one[0], int(a.one[1])
        out = os.path.join(ROOT, "build", "test")
        s = run(out, [(test, seed)])
        ok = not s["failed"]
        print(f"{test} seed {seed}: {'pass' if ok else 'FAIL'}")
        if not ok:
            print("\n".join(s["errors"][f"{test}:{seed}"]))
            print(f"log and waves in {out}/fail_{test}_{seed}.*")
        sys.exit(0 if ok else 1)

    jobs = []
    if a.directed:
        jobs.append(("directed", [(t, 1) for t in CFG["directed"]]))
    if a.seeds:
        lo, hi = seed_range(a.seeds)
        n = int(a.shard.split("/")[1]) if a.shard else CFG["shards"]
        ks = [int(a.shard.split("/")[0])] if a.shard else range(n)
        for k in ks:
            step = -(-(hi - lo) // n)
            seeds = range(lo + k * step, min(hi, lo + (k + 1) * step))
            jobs.append((f"shard{k}", [("rand", s) for s in seeds]))

    # build each depth once up front so parallel shards don't race on it
    shared = os.path.join(a.out, "builds")
    os.makedirs(shared, exist_ok=True)
    for depth in (4, 2):
        build(shared, depth)

    def one(job):
        name, items = job
        out = os.path.join(a.out, name)
        os.makedirs(out, exist_ok=True)
        for depth in (4, 2):
            link = sim_build(out, depth)
            if not os.path.exists(link):
                os.symlink(sim_build(shared, depth), link)
        s = run(out, items)
        s["name"] = name
        if name.startswith("shard"):
            s["seeds"] = [items[0][1], items[-1][1] + 1]
        with open(os.path.join(a.out, f"{name}.json"), "w") as f:
            json.dump(s, f, indent=1)
        return s

    with ThreadPoolExecutor(max(1, a.jobs)) as ex:
        sums = list(ex.map(one, jobs))

    bad = 0
    for s in sums:
        print(f"{s['name']}: {s['passed']}/{s['items']} passed, {s['txns']} port transactions")
        for test, seed in s["failed"]:
            tag = "confirmed" if [test, seed] in s["confirmed"] else "did not repeat"
            print(f"  FAIL {test} seed {seed} ({tag}): {s['errors'][f'{test}:{seed}'][0]}")
        bad += len(s["failed"])
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
