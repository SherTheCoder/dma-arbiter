#!/usr/bin/env python3
"""E3: how the inverted-TX cost moves with the cross-path penalty and background load.

Penalty 0-8 cycles on both cross paths x 0, 2 or 5 background channels, balanced
and inverted, 10 seeds each. Writes results/sweep.json and a heatmap.
"""
import json
import os

import matplotlib
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from mapping import INK, INK2, ROOT, SURFACE, compare, run_points

PENS = [0, 1, 2, 3, 4, 6, 8]
BGS = [0, 2, 5]
# blue, light to dark
RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def main():
    pts = run_points([(m, bg, pen) for pen in PENS for bg in BGS for m in ("bal", "inv")])
    rows = []
    for pen in PENS:
        for bg in BGS:
            r = compare(pts[("bal", bg, pen)], pts[("inv", bg, pen)])
            rows.append({"pen": pen, "bg": bg, "loss": r["loss"],
                         "throughput_bal": r["throughput_bal"]["mean"],
                         "throughput_inv": r["throughput_inv"]["mean"],
                         "tx_latency_ratio": r["tx_latency_ratio"], "rx_latency_ratio": r["rx_latency_ratio"]})
    inverted_wins = [(r["pen"], r["bg"]) for r in rows if r["loss"]["min"] < 0]
    out = {"pens": PENS, "bgs": BGS, "rows": rows, "inverted_beats_balanced": inverted_wins}
    with open(os.path.join(ROOT, "results", "sweep.json"), "w") as f:
        json.dump(out, f, indent=1)

    loss = np.array([[100 * next(r["loss"]["mean"] for r in rows if r["pen"] == p and r["bg"] == b)
                      for p in PENS] for b in BGS])
    fig, ax = plt.subplots(figsize=(7, 2.8), facecolor=SURFACE)
    cmap = LinearSegmentedColormap.from_list("blue", RAMP)
    im = ax.imshow(loss, cmap=cmap, vmin=0, vmax=max(1, loss.max()), aspect="auto")
    for i in range(len(BGS)):
        for j in range(len(PENS)):
            r, g, b, _ = im.cmap(im.norm(loss[i, j]))
            dark = 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.45
            ax.text(j, i, f"{loss[i, j]:.1f}", ha="center", va="center", fontsize=9,
                    color="white" if dark else INK)
    ax.set_xticks(range(len(PENS)), PENS, color=INK2)
    ax.set_yticks(range(len(BGS)), BGS, color=INK2)
    ax.set_xlabel("cross-path penalty, cycles (default 3)", color=INK2)
    ax.set_ylabel("background channels", color=INK2)
    ax.set_title("Throughput lost by inverting TX, % (mean of 10 seeds)", color=INK, fontsize=10)
    for s in ax.spines.values():
        s.set_visible(False)
    cb = fig.colorbar(im, ax=ax, shrink=0.9)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=INK2, labelsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(ROOT, "results", "sweep_heatmap.png"), dpi=130, facecolor=SURFACE)

    for b, rowv in zip(BGS, loss):
        print(f"bg {b}: " + "  ".join(f"pen{p} {v:5.1f}%" for p, v in zip(PENS, rowv)))
    print("inverted beats balanced at:", inverted_wins or "never")


if __name__ == "__main__":
    main()
