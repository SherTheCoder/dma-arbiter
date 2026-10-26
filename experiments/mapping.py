#!/usr/bin/env python3
"""E1/E2: balanced vs inverted TX mapping, in RTL.

E1 is 2 RX (ch1, ch2, P2M) and 1 TX (ch0, M2P), 2048 beats each, burst 4.
E2 adds 5 balanced background channels. Each point runs 10 seeds that only
move descriptor start offsets (0-64 cycles). Writes results/mapping.json and
two charts.
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "scripts")]
import run_regression as rr

OUT = os.path.join(ROOT, "build", "exp")
SEEDS = range(10)
DEFAULT_PEN = 3

BAL, INV = "#2a78d6", "#eb6834"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def point(mapping, bg, pen):
    """RTL dumps for one (mapping, background channels, cross-path penalty), run once."""
    out = os.path.join(OUT, f"{mapping}_bg{bg}_pen{pen}")
    dump = os.path.join(out, "dump.jsonl")
    if not os.path.exists(dump):
        os.makedirs(out, exist_ok=True)
        link = os.path.join(out, "sim_build_d4")
        if not os.path.exists(link):
            os.symlink(os.path.join(OUT, "builds", "sim_build_d4"), link)
        s = rr.run(out, [("sai", s) for s in SEEDS], waves=False,
                   more={"MAP": mapping, "BG": bg, "PEN": pen, "DUMP": dump})
        if s["failed"]:
            sys.exit(f"RTL failures at {mapping} bg{bg} pen{pen}: {s['failed']}")
    return [json.loads(line) for line in open(dump)]


def run_points(points, jobs=6):
    rr.build(os.path.join(OUT, "builds"), 4)
    with ThreadPoolExecutor(jobs) as ex:
        return dict(zip(points, ex.map(lambda p: point(*p), points)))


def metrics(rec):
    first = min(c for _, c in rec["loads"])
    last = max(c for _, c in rec["dones"])
    beats = sum(d["beats"] for d in rec["descs"])
    # burst latency: last write beat minus the cycle that burst's read request went up
    worst = {}
    pending = {}
    for ch, port, write, n, rise, accept, first_beat, last_beat in rec["txns"]:
        if not write:
            pending[ch] = rise
        else:
            worst[ch] = max(worst.get(ch, 0), last_beat - pending.pop(ch))
    return {"seed": rec["seed"], "throughput": beats / (last - first), "cycles": last - first,
            "worst": worst, "tx": worst[0], "rx": max(worst[1], worst[2])}


def stats(xs):
    return {"mean": float(np.mean(xs)), "min": float(np.min(xs)), "max": float(np.max(xs))}


def compare(bal, inv):
    """Seeds are paired: seed k has the same start offsets in both mappings."""
    b = sorted(map(metrics, bal), key=lambda m: m["seed"])
    i = sorted(map(metrics, inv), key=lambda m: m["seed"])
    return {
        "throughput_bal": stats([m["throughput"] for m in b]),
        "throughput_inv": stats([m["throughput"] for m in i]),
        "loss": stats([(x["throughput"] - y["throughput"]) / x["throughput"] for x, y in zip(b, i)]),
        "tx_worst_bal": stats([m["tx"] for m in b]),
        "tx_worst_inv": stats([m["tx"] for m in i]),
        "rx_worst_bal": stats([m["rx"] for m in b]),
        "rx_worst_inv": stats([m["rx"] for m in i]),
        "tx_latency_ratio": stats([y["tx"] / x["tx"] for x, y in zip(b, i)]),
        "rx_latency_ratio": stats([y["rx"] / x["rx"] for x, y in zip(b, i)]),
        "worst_per_channel_bal": {ch: float(np.mean([m["worst"][ch] for m in b])) for ch in b[0]["worst"]},
        "worst_per_channel_inv": {ch: float(np.mean([m["worst"][ch] for m in i])) for ch in i[0]["worst"]},
    }


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def plot_throughput(res, path):
    fig, ax = plt.subplots(figsize=(6, 3.6), facecolor=SURFACE)
    style(ax)
    x = np.arange(2)
    w = 0.36
    for k, (name, color) in enumerate([("bal", BAL), ("inv", INV)]):
        vals = [res[e][f"throughput_{name}"] for e in ("E1", "E2")]
        mean = np.array([v["mean"] for v in vals])
        err = np.array([[v["mean"] - v["min"] for v in vals], [v["max"] - v["mean"] for v in vals]])
        xs = x + (k - 0.5) * (w + 0.03)
        ax.bar(xs, mean, w, color=color, label="balanced" if name == "bal" else "TX inverted",
               yerr=err, ecolor=INK2, capsize=3, error_kw={"lw": 1})
        for xx, m in zip(xs, mean):
            ax.text(xx, m * 0.5, f"{m:.3f}", ha="center", va="center", color="white", fontsize=9)
    top = max(res[e]["throughput_bal"]["max"] for e in ("E1", "E2"))
    ax.set_ylim(0, top * 1.3)
    for e, xx in zip(("E1", "E2"), x):
        pair = max(res[e]["throughput_bal"]["max"], res[e]["throughput_inv"]["max"])
        ax.text(xx, pair + top * 0.04, f"inverted: -{100 * res[e]['loss']['mean']:.1f}%", ha="center",
                va="bottom", color=INK, fontsize=9)
    ax.set_xticks(x, ["E1: 2 RX + 1 TX", "E2: + 5 background"], color=INK)
    ax.set_ylabel("beats written per cycle", color=INK2)
    ax.set_title("Aggregate throughput, mean of 10 seeds (bars span min-max)", color=INK, fontsize=10)
    ax.legend(frameon=False, fontsize=9, loc="upper left", ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def plot_latency(res, path):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), facecolor=SURFACE, sharey=True)
    names = {0: "TX", 1: "RX1", 2: "RX2"}
    for ax, e in zip(axes, ("E1", "E2")):
        style(ax)
        chans = sorted(int(c) for c in res[e]["worst_per_channel_bal"])
        x = np.arange(len(chans))
        w = 0.38
        for k, (name, color) in enumerate([("bal", BAL), ("inv", INV)]):
            v = [res[e][f"worst_per_channel_{name}"][c] for c in chans]
            ax.bar(x + (k - 0.5) * (w + 0.03), v, w, color=color,
                   label="balanced" if name == "bal" else "TX inverted")
        ax.set_xticks(x, [names.get(c, f"bg{c}") for c in chans], color=INK)
        ax.set_title(e, color=INK, fontsize=10)
    axes[0].set_ylabel("worst burst latency, cycles", color=INK2)
    axes[0].legend(frameon=False, fontsize=9, loc="upper left")
    fig.suptitle("Worst-case burst latency per channel (read request to last write beat), mean of 10 seeds",
                 color=INK, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def main():
    results = os.path.join(ROOT, "results")
    os.makedirs(results, exist_ok=True)
    pts = run_points([(m, bg, DEFAULT_PEN) for bg in (0, 5) for m in ("bal", "inv")])
    res = {e: compare(pts[("bal", bg, DEFAULT_PEN)], pts[("inv", bg, DEFAULT_PEN)])
           for e, bg in (("E1", 0), ("E2", 5))}
    res["seeds"] = len(SEEDS)
    res["cross_penalty"] = DEFAULT_PEN
    with open(os.path.join(results, "mapping.json"), "w") as f:
        json.dump(res, f, indent=1)
    plot_throughput(res, os.path.join(results, "throughput.png"))
    plot_latency(res, os.path.join(results, "latency.png"))
    for e in ("E1", "E2"):
        r = res[e]
        print(f"{e}: throughput {r['throughput_bal']['mean']:.3f} -> {r['throughput_inv']['mean']:.3f} beats/cycle, "
              f"loss {100 * r['loss']['mean']:.1f}% ({100 * r['loss']['min']:.1f}..{100 * r['loss']['max']:.1f}), "
              f"TX worst {r['tx_worst_bal']['mean']:.0f} -> {r['tx_worst_inv']['mean']:.0f} "
              f"(x{r['tx_latency_ratio']['mean']:.2f}), RX worst {r['rx_worst_bal']['mean']:.0f} -> "
              f"{r['rx_worst_inv']['mean']:.0f} (x{r['rx_latency_ratio']['mean']:.2f})")


if __name__ == "__main__":
    main()
