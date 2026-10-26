#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib"]
# ///
"""Draw the README charts as SVG into plots/. Every number is read from the committed results; nothing is typed in here.

  storage.svg  stored size as a fraction of raw, per dataset         <- results/cost/matrix-10tb-30d.json (+ the web-log verify log for Cartridge)
  cost.svg     yearly cost at 10 TB/day, 30 days, per dataset        <- results/cost/matrix-10tb-30d.json
  speed.svg    web-log search time per tier, Cartridge vs Elastic    <- output of speed/lib/summarize.py over results/speed/http_logs/speed

usage: uv run --script plots/make_plots.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "plots"
MATRIX = ROOT / "results/cost/matrix-10tb-30d.json"
VERIFY = next((ROOT / "results/speed/http_logs/verify").glob("httplogs-verify-*.log"))
SPEED_LOGS = ROOT / "results/speed/http_logs/speed"

# one colour per system, the same in every chart (validated categorical palette, fixed order)
SYSTEMS = [
    ("Cartridge", "#2a78d6"),
    ("Elasticsearch logsdb", "#eb6834"),
    ("Elasticsearch standard", "#1baf7a"),
    ("OpenSearch", "#eda100"),
]
COLOR = dict(SYSTEMS)
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e3e2dd", "#ffffff"

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 10, "text.color": INK, "axes.labelcolor": MUTED,
    "axes.edgecolor": GRID, "xtick.color": MUTED, "ytick.color": MUTED, "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE, "svg.fonttype": "none", "axes.spines.top": False, "axes.spines.right": False,
})

SHORT = {"http_logs": "Web logs", "CloudTrail": "CloudTrail", "Thunderbird": "Thunderbird",
         "CockroachDB": "CockroachDB", "Alibaba": "Traces"}


def short(dataset: str) -> str:
    return next(v for k, v in SHORT.items() if dataset.startswith(k))


def pick(rows: list[dict], system: str) -> dict:
    """The one matrix row that stands for `system` in a dataset (same choices as the README's tables)."""
    def match(r: dict) -> bool:
        c = r["config"]
        if system == "Cartridge":
            return c.startswith("Cartridge, larger output") or c.startswith("Cartridge (")
        if system == "Elasticsearch standard":
            return c.startswith("ES standard")
        if system == "Elasticsearch logsdb":
            return "logsdb" in c and "Enterprise" not in c and "stock logs data stream" not in c
        return c.startswith("OpenSearch")
    hits = [r for r in rows if match(r)]
    if len(hits) > 1:
        hits = [r for r in hits if "cost-model default" in r["config"]] or hits[:1]
    if len(hits) != 1:
        sys.exit(f"expected one {system} row, found {len(hits)}: {[r['config'] for r in hits]}")
    return hits[0]


def load() -> dict:
    rows = json.loads(MATRIX.read_text())
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(short(r["dataset"]), {"rows": []})["rows"].append(r)
    for name, d in out.items():
        d["pick"] = {s: pick(d["rows"], s) for s, _ in SYSTEMS}
        d["raw"] = d["pick"]["Cartridge"]["bytes"] / d["pick"]["Cartridge"]["x_raw"]
    # web logs: the Cartridge size is the verified default press with its field index (the cart plus the field index), from the verify run
    m = re.search(r"^SIZES cart_bytes=(\d+) sidecar_bytes=(\d+)", VERIFY.read_text(), re.M)
    if not m:
        sys.exit(f"no SIZES line in {VERIFY}")
    out["Web logs"]["cart_bytes"] = int(m[1]) + int(m[2])
    return out


def style(ax, title: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", pad=34)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)


def legend(fig, ax) -> None:
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, c in SYSTEMS]
    ax.legend(handles, [n for n, _ in SYSTEMS], ncol=4, loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=9)


def grouped(ax, data: dict, value, fmt, log: bool = False) -> None:
    names = list(data)
    width = 0.2
    for i, (system, color) in enumerate(SYSTEMS):
        xs = [j + (i - 1.5) * width for j in range(len(names))]
        vals = [value(data[n], system) for n in names]
        bars = ax.bar(xs, vals, width=width * 0.9, color=color)
        for b, v in zip(bars, vals):
            ax.annotate(fmt(v), (b.get_x() + b.get_width() / 2, v), xytext=(0, 2), textcoords="offset points",
                        ha="center", va="bottom", fontsize=6.5, color=INK, rotation=90)
    ax.set_xticks(range(len(names)), names)
    if log:
        ax.set_yscale("log")


def storage(data: dict) -> None:
    def frac(d: dict, system: str) -> float:
        if system == "Cartridge" and "cart_bytes" in d:
            return d["cart_bytes"] / d["raw"]
        return d["pick"][system]["x_raw"]
    carts = [frac(d, "Cartridge") for d in data.values()]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    grouped(ax, data, frac, lambda v: f"{v:.3f}")
    ax.set_ylim(0, 1.12)
    style(ax, f"Cartridge stores each dataset in {min(carts) * 100:.0f}% to {max(carts) * 100:.0f}% of its raw size", "stored size ÷ raw size (lower is better)")
    legend(fig, ax)
    fig.tight_layout()
    fig.savefig(OUT / "storage.svg")


def cost(data: dict) -> None:
    ratios = [d["pick"][s]["cost_vs_cart"] for d in data.values() for s, _ in SYSTEMS if s != "Cartridge"]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    def money(v: float) -> str:
        return f"${v / 1e6:.2f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"
    grouped(ax, data, lambda d, s: d["pick"][s]["cart_larger_usd" if s == "Cartridge" else "usd_year"], money, log=True)
    ax.set_ylim(3e4, 1.2e7)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: money(v)))
    style(ax, f"At 10 TB a day, the others cost {min(ratios):.0f}x to {max(ratios):.0f}x more per year", "yearly cost, 30 days searchable (log scale)")
    legend(fig, ax)
    fig.tight_layout()
    fig.savefig(OUT / "cost.svg")


def speed() -> None:
    cmd = ["uv", "run", str(ROOT / "speed/lib/summarize.py"), str(SPEED_LOGS)]
    text = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    wanted = [("Hot: all 39 searches", "Hot: all 39"), ("Warm: first answer", "Warm: first answer"),
              ("Warm: all 39 once local", "Warm: all 39 once local"), ("Cold: 35 searches both answer", "Cold: 35")]
    rng = r"(\d+(?:\.\d+)?)(?: to (\d+(?:\.\d+)?))? s"
    rows = []
    for label, prefix in wanted:
        line = next((ln for ln in text.splitlines() if ln.startswith(f"| {prefix}")), None)
        if line is None:
            sys.exit(f"no '{prefix}' row in the summarize.py output")
        cells = [c.strip() for c in line.strip("|").split("|")]
        vals = []
        for cell in cells[1:3]:
            m = re.match(rng, cell)
            if not m:
                sys.exit(f"cannot read seconds from '{cell}'")
            lo, hi = float(m[1]), float(m[2] or m[1])
            vals.append((lo, hi, f"{m[1]} to {m[2]} s" if m[2] else f"{m[1]} s"))
        rows.append((label, vals))
    fig, ax = plt.subplots(figsize=(9, 3.9))
    height = 0.36
    for i, (system, color, k) in enumerate([("Cartridge", COLOR["Cartridge"], 0), ("Elasticsearch", COLOR["Elasticsearch standard"], 1)]):
        ys = [j + (i - 0.5) * height for j in range(len(rows))]
        for y, (_, vals) in zip(ys, rows):
            lo, hi, txt = vals[k]
            ax.barh(y, hi, height=height * 0.9, color=color)
            ax.annotate(txt, (hi, y), xytext=(4, 0), textcoords="offset points", va="center", fontsize=8.5, color=INK)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, 340)
    ax.set_xlabel("seconds (shorter is faster; a range is drawn to its upper end)")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_title("Hot searches match; on data in S3 Cartridge answers sooner", loc="left", fontsize=13, fontweight="bold", pad=34)
    ax.legend([plt.Rectangle((0, 0), 1, 1, color=COLOR["Cartridge"]), plt.Rectangle((0, 0), 1, 1, color=COLOR["Elasticsearch standard"])],
              ["Cartridge", "Elasticsearch"], ncol=2, loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "speed.svg")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    data = load()
    storage(data)
    cost(data)
    speed()
    for name in ("storage", "cost", "speed"):
        p = OUT / f"{name}.svg"
        if not p.stat().st_size:
            sys.exit(f"{p} is empty")
        print(p.relative_to(ROOT))


if __name__ == "__main__":
    main()
