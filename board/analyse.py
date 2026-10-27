#!/usr/bin/env python3
"""Turns results/board_raw.json.gz (board/run.py) into results/board.json,
results/board.txt and results/board.png, next to the RTL numbers.

Everything is converted to bus cycles (200 MHz AHB/APB, 3 CPU cycles each)
so it lines up with the RTL, whose clock stands in for the bus clock.
"""
import gzip
import json
import os
import sys
from collections import defaultdict

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "experiments"))
from mapping import BAL, INK, INK2, INV, SURFACE, style  # noqa: E402

RESULTS = os.path.join(ROOT, "results")
CPU_PER_BUS = 3
POINTS = {0: "E1", 2: "bg2", 5: "E2"}


def stats(xs):
    xs = np.asarray(xs, dtype=float)
    return {"mean": float(xs.mean()), "min": float(xs.min()), "max": float(xs.max())}


def active(j):
    return [int(c) for c in j["chans"] if int(c) != j["probe"]]


def span(j):
    a = active(j)
    return (max(j["done"][c] for c in a) - min(j["start"][c] for c in a)) / CPU_PER_BUS


def words(j):
    return sum(j["chans"][str(c)][4] for c in active(j))


def took(j, c):
    return (j["done"][c] - j["start"][c]) / CPU_PER_BUS


def paths(jobs):
    """Bus cycles per word for one channel on its own, from a straight-line fit
    over 16-1024 word blocks. Below that the poll loop's own latency hides it."""
    pts = defaultdict(list)
    for j in jobs:
        if j["kind"] == "path" and j["words"] >= 16:
            pts[(j["dir"], j["src"], j["dst"], j["burst"])].append((j["words"], span(j)))
    slope = {k: float(np.polyfit(*zip(*v), 1)[0]) for k, v in pts.items()}
    out = {}
    for d in sorted({k[0] for k in slope}):
        pick = lambda s, t: [v for k, v in slope.items() if k[0] == d and (k[1], k[2]) == (s, t)]
        same = pick(0, 0) + pick(1, 1)
        split = pick(0, 1) + pick(1, 0)
        out[d] = {"same_port": float(np.mean(same)), "split_ports": float(np.mean(split)),
                  # how far apart port 0 and port 1 are, worst case over block sizes and bursts
                  "port_asymmetry": float(max(abs(a - b) for a, b in zip(pick(0, 0) + pick(0, 1),
                                                                          pick(1, 1) + pick(1, 0)))),
                  "burst_effect": float(max(slope[(d, s, t, 4)] - slope[(d, s, t, 1)]
                                            for s in (0, 1) for t in (0, 1)))}
    return out


def mapping(jobs, kind="map"):
    groups = defaultdict(dict)
    for j in jobs:
        if j["kind"] == kind:
            groups[(j["mem"], j["burst"], j["bg"], j["gap"])][(j["seed"], j.get("rep", 0), j["map"])] = j
    out = {}
    for (mem, burst, bg, gap), g in groups.items():
        pairs = [(g[(s, r, "bal")], g[(s, r, "inv")]) for s, r, m in g if m == "bal"]
        thr = lambda j: words(j) / span(j)
        rx = lambda j: max(took(j, 1), took(j, 2))
        out[(mem, burst, bg, gap)] = {
            "runs": len(pairs),
            "throughput_bal": stats([thr(b) for b, _ in pairs]),
            "throughput_inv": stats([thr(i) for _, i in pairs]),
            "loss": stats([1 - thr(i) / thr(b) for b, i in pairs]),
            "tx_time_bal": stats([took(b, 0) for b, _ in pairs]),
            "tx_time_inv": stats([took(i, 0) for _, i in pairs]),
            "tx_time_ratio": stats([took(i, 0) / took(b, 0) for b, i in pairs]),
            "rx_time_ratio": stats([rx(i) / rx(b) for b, i in pairs]),
            "per_channel_bal": {c: float(np.mean([took(b, c) for b, _ in pairs])) for c in active(pairs[0][0])},
            "per_channel_inv": {c: float(np.mean([took(i, c) for _, i in pairs])) for c in active(pairs[0][1])},
        }
    return out


def probes(jobs):
    groups = defaultdict(dict)
    late = 0
    for j in jobs:
        if j["kind"] != "probe":
            continue
        others = active(j)
        # only counts if everything else was still streaming when the last probe ended
        if others and min(j["done"][c] for c in others) <= j["probe_end"]:
            late += 1
        groups[(j["burst"], j["side"], j["bg"])][(j["seed"], j["map"])] = j
    out = {}
    for key, g in groups.items():
        lat = {m: np.array([x for (s, mm), j in g.items() if mm == m for x in j["lat"]]) / CPU_PER_BUS
               for m in ("bal", "inv")}
        r = {m: {"mean": float(v.mean()), "p95": float(np.percentile(v, 95)), "max": float(v.max())}
             for m, v in lat.items()}
        seeds = sorted({s for s, _ in g})
        if len(seeds) > 1:
            r["worst_ratio"] = stats([max(g[(s, "inv")]["lat"]) / max(g[(s, "bal")]["lat"]) for s in seeds])
            r["mean_ratio"] = stats([np.mean(g[(s, "inv")]["lat"]) / np.mean(g[(s, "bal")]["lat"]) for s in seeds])
        out[key] = r
    return out, late


def diff(a, b, keys=("loss", "tx_time_ratio", "rx_time_ratio")):
    return max(abs(a[k]["mean"] - b[k]["mean"]) for k in keys)


def plot(res, rtl, path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.8), facecolor=SURFACE)
    for ax in (ax1, ax2):
        style(ax)
    names = ["E1", "bg2", "E2"]
    x = np.arange(len(names))
    w = 0.36
    model = [100 * rtl[n]["loss"] for n in names]
    board = [100 * res["mapping"]["axi"][n]["loss"]["mean"] for n in names]
    ax1.bar(x - w / 2 - 0.015, model, w, facecolor="none", edgecolor=INV, hatch="////", lw=1,
            label="RTL model (3-cycle cross paths)")
    ax1.bar(x + w / 2 + 0.015, board, w, color=INV, label="STM32N657 board")
    for xx, v in zip(x - w / 2 - 0.015, model):
        ax1.text(xx, v + 0.6, f"{v:.1f}%", ha="center", va="bottom", color=INK, fontsize=9)
    for xx, v in zip(x + w / 2 + 0.015, board):
        ax1.text(xx, max(v, 0) + 0.6, f"{v:+.1f}%", ha="center", va="bottom", color=INK, fontsize=9)
    ax1.axhline(0, color=INK2, lw=0.8)
    ax1.set_ylim(-2, 30)
    ax1.set_xticks(x, ["E1: 2 RX + 1 TX", "+ 2 background", "E2: + 5 background"], color=INK)
    ax1.set_ylabel("aggregate throughput lost, %", color=INK2)
    ax1.set_title("Throughput lost by inverting TX", color=INK, fontsize=10)
    ax1.legend(frameon=False, fontsize=8.5, loc="upper right")

    loads = [("alone", None), ("E1 load", 0), ("E2 load", 5)]
    p = res["probes"]["tx"]
    x = np.arange(len(loads))
    for k, (m, color, label) in enumerate([("bal", BAL, "balanced"), ("inv", INV, "TX inverted")]):
        xs = x + (k - 0.5) * (w + 0.03)
        mean = [p[name][m]["mean"] for name, _ in loads]
        worst = [p[name][m]["max"] for name, _ in loads]
        ax2.bar(xs, mean, w, color=color, label=label)
        ax2.scatter(xs, worst, marker="_", s=160, color=INK, lw=1.5, zorder=3,
                    label="worst of 320" if k == 1 else None)
        for xx, v in zip(xs, mean):
            ax2.text(xx, v - 10, f"{v:.0f}", ha="center", va="top", color="white", fontsize=9)
    ax2.set_ylim(0, max(p["E2 load"]["inv"]["max"], 1) * 1.15)
    ax2.set_xticks(x, [name for name, _ in loads], color=INK)
    ax2.set_ylabel("bus cycles", color=INK2)
    ax2.set_title("One 4-word SAI TX block, start to done", color=INK, fontsize=10)
    h, l = ax2.get_legend_handles_labels()
    order = [l.index(n) for n in ("balanced", "TX inverted", "worst of 320")]
    ax2.legend([h[i] for i in order], [l[i] for i in order], frameon=False, fontsize=8.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=130, facecolor=SURFACE)
    plt.close(fig)


def main():
    raw = json.load(gzip.open(os.path.join(RESULTS, "board_raw.json.gz")))
    jobs = raw["jobs"]
    b = raw["board"]
    if any(j["flags"] for j in jobs):
        sys.exit("raw data has jobs with error flags")

    m = mapping(jobs)
    g = mapping(jobs, "gap")
    p, late = probes(jobs)
    # bursts of 4/8 and of 1 come out the same on channels 0-7, so report the RTL ones
    burst_diff = max(diff(m[(mem, "bsp", bg, 200)], m[(mem, "rtl", bg, 200)]) for mem in ("axi", "ahb")
                     for bg in POINTS)
    res = {
        "board": {"idcode": f"{b['idcode']:#010x}", "device_id": f"{b['idcode'] & 0xFFF:#x}",
                  "cpu_mhz": b["cpu_hz"] / 1e6, "axi_mhz": b["axi_hz"] / 1e6, "ahb_mhz": b["ahb_hz"] / 1e6,
                  "apb2_mhz": b["apb2_hz"] / 1e6},
        "jobs": len(jobs),
        "paths": paths(jobs),
        "mapping": {mem: {POINTS[bg]: m[(mem, "rtl", bg, 200)] for bg in POINTS} for mem in ("axi", "ahb")},
        "burst_1_vs_4_8_max_difference": burst_diff,
        "poll_gap": {POINTS[bg]: {gap: (m if gap == 200 else g)[("axi", "rtl", bg, gap)]["loss"]["mean"]
                                  for gap in (0, 200, 2000)} for bg in (0, 5)},
        "probes": {side: {name: p[("rtl", side, bg)] for name, bg in (("alone", None), ("E1 load", 0),
                                                                      ("E2 load", 5))}
                   for side in ("tx", "rx")},
        "probes_with_background_done_early": late,
    }
    sweep = json.load(open(os.path.join(RESULTS, "sweep.json")))
    rtl = {POINTS[r["bg"]]: {"loss": r["loss"]["mean"], "tx_latency_ratio": r["tx_latency_ratio"]["mean"],
                             "rx_latency_ratio": r["rx_latency_ratio"]["mean"]}
           for r in sweep["rows"] if r["pen"] == 3}
    res["rtl_model"] = rtl
    for mem in res["mapping"]:
        for v in res["mapping"][mem].values():
            v["per_channel_bal"] = {str(c): t for c, t in v["per_channel_bal"].items()}
            v["per_channel_inv"] = {str(c): t for c, t in v["per_channel_inv"].items()}
    with open(os.path.join(RESULTS, "board.json"), "w") as f:
        json.dump(res, f, indent=1)
    plot(res, rtl, os.path.join(RESULTS, "board.png"))

    lines = [f"STM32N657 (idcode {res['board']['idcode']}), cpu {b['cpu_hz'] / 1e6:.0f} MHz, "
             f"bus {b['ahb_hz'] / 1e6:.0f} MHz, {len(jobs)} jobs", "",
             "one channel alone, bus cycles per word (same port / split ports, port 0 vs 1 worst gap):"]
    for d, v in res["paths"].items():
        lines.append(f"  {d:8s} {v['same_port']:6.2f} / {v['split_ports']:6.2f}   {v['port_asymmetry']:.3f}")
    lines += ["", "TX inverted vs balanced, 10 seeds x 3 runs, poll gap 200 cpu cycles:"]
    for mem, pts in res["mapping"].items():
        for name, v in pts.items():
            lines.append(f"  {mem} {name:3s}: throughput {v['throughput_bal']['mean']:.4f} -> "
                         f"{v['throughput_inv']['mean']:.4f} words/cycle, loss {100 * v['loss']['mean']:+.2f}% "
                         f"({100 * v['loss']['min']:+.2f}..{100 * v['loss']['max']:+.2f}), "
                         f"TX time x{v['tx_time_ratio']['mean']:.2f}, RX time x{v['rx_time_ratio']['mean']:.2f}"
                         + (f"   [RTL: {100 * rtl[name]['loss']:.1f}%]" if mem == "axi" else ""))
    lines.append(f"  bursts of 1 instead of 4/8: largest change in any ratio {burst_diff:.5f}")
    lines.append("  loss by poll gap 0/200/2000: " + ", ".join(
        f"{k} " + "/".join(f"{100 * x:+.2f}%" for x in v.values()) for k, v in res["poll_gap"].items()))
    lines += ["", "4-word block latency, bus cycles (mean / worst), bal -> inv:"]
    for side, pts in res["probes"].items():
        for name, v in pts.items():
            extra = ""
            if "worst_ratio" in v:
                extra = f"   worst x{v['worst_ratio']['mean']:.2f}, mean x{v['mean_ratio']['mean']:.2f}"
                key = "tx_latency_ratio" if side == "tx" else "rx_latency_ratio"
                extra += f"   [RTL worst x{rtl[{'E1 load': 'E1', 'E2 load': 'E2'}[name]][key]:.2f}]"
            lines.append(f"  {side} {name:8s}: {v['bal']['mean']:6.1f} / {v['bal']['max']:6.1f} -> "
                         f"{v['inv']['mean']:6.1f} / {v['inv']['max']:6.1f}{extra}")
    lines.append(f"  probe jobs where the background ran out early: {late}")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(RESULTS, "board.txt"), "w") as f:
        f.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
