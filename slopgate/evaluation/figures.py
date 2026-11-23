"""Draw the comparison results as standalone SVG charts. Standard library only.

    python -m slopgate.evaluation.figures --results results/reproduction --out results/reproduction/figures

Reads <results>/<dataset>/comparison/comparison.json (written by slopgate.evaluation.aggregate) for
every dataset found, and writes one grouped bar chart per metric (datasets on the x axis, one bar
per system) plus index.html that shows them all. The output is deterministic: the same input gives
byte-identical files, so figures can be checked in or diffed.

    false_dismissals.svg  real reports wrongly dismissed (the costly error)
    mean_cost.svg         expected cost per report under the 500 / 1 / 0.2 cost matrix
    accuracy.svg          fraction of reports given the expected verdict
    tool_calls.svg        mean tool calls per report
"""
import argparse
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

# (file, comparison.json field, title, y-axis label, number format)
CHARTS = [
    ("false_dismissals", "false_hallucinated", "Real reports wrongly dismissed (lower is better)", "reports", "%d"),
    ("mean_cost", "mean_classification_cost", "Expected cost per report (lower is better)", "cost", "%.1f"),
    ("accuracy", "accuracy", "Accuracy (higher is better)", "fraction correct", "%.2f"),
    ("tool_calls", "mean_tool_calls", "Tool calls per report", "calls", "%.1f"),
]
# Stable colours: the same system is the same colour in every chart. Unknown systems cycle the extras.
COLOURS = {"b0": "#8a94a6", "b1": "#3b6cf0", "b2": "#8e5cf0", "b2_alt": "#b79af7", "b3_rules": "#2fa264",
           "b3_llm": "#1c7a4a", "agent": "#e39b17"}
EXTRA = ["#e5484d", "#0aa5b8", "#c2438f", "#7a8b2a", "#5a6275", "#d9702a"]
W, H = 1000, 560
LEFT, RIGHT, TOP, BOTTOM = 90, 30, 70, 120


def load_comparisons(results_dir):
    """{dataset: {system: row}} from <results>/<dataset>/comparison/comparison.json."""
    out = {}
    for path in sorted(Path(results_dir).glob("*/comparison/comparison.json")):
        rows = json.loads(path.read_text(encoding="utf-8"))
        out[path.parent.parent.name] = {r["system"]: r for r in rows}
    if not out:
        raise ValueError("no comparison.json under %s/*/comparison/ (run `make aggregate` first)" % results_dir)
    return out


def colour_for(system, order):
    if system in COLOURS:
        return COLOURS[system]
    extras = [s for s in order if s not in COLOURS]
    return EXTRA[extras.index(system) % len(EXTRA)]


def axis(v):
    """(ymax, step) for a y axis that has to reach v: a round step (1, 2, 2.5, 5 times a power
    of ten), at most about five gridlines, ymax a whole number of steps."""
    if v <= 0:
        return 1.0, 0.25
    raw = v / 5.0
    mag = 1.0
    while mag * 10 <= raw:
        mag *= 10
    while mag > raw:
        mag /= 10
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    n = int(-(-v // step))                      # ceil without importing math
    return step * n, step


def grouped_bars(title, ylabel, fmt, datasets, systems, values):
    """SVG text. values[(dataset, system)] -> number or None (None = no bar, shown as n/a)."""
    present = [v for v in values.values() if v is not None]
    ymax, step = axis(max(present)) if present else (1.0, 0.25)
    ticks = int(round(ymax / step))
    pw, ph = W - LEFT - RIGHT, H - TOP - BOTTOM
    gw = pw / max(len(datasets), 1)
    bw = min(48.0, gw * 0.8 / max(len(systems), 1))
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
           'font-family="Inter, Helvetica, Arial, sans-serif">' % (W, H, W, H),
           '<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H),
           '<text x="%d" y="38" font-size="24" font-weight="700" fill="#0d1630">%s</text>' % (LEFT, escape(title))]
    for i in range(ticks + 1):                                   # gridlines and y labels
        y = TOP + ph - ph * i / ticks
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#e3e7f3" stroke-width="1"/>' % (LEFT, y, W - RIGHT, y))
        out.append('<text x="%d" y="%.1f" font-size="15" text-anchor="end" fill="#5d6685">%s</text>' % (
            LEFT - 10, y + 5, ("%g" % round(step * i, 6))))
    out.append('<text x="22" y="%.1f" font-size="15" fill="#5d6685" transform="rotate(-90 22 %.1f)" text-anchor="middle">%s</text>' % (
        TOP + ph / 2, TOP + ph / 2, escape(ylabel)))
    for gi, ds in enumerate(datasets):
        x0 = LEFT + gi * gw + (gw - bw * len(systems)) / 2
        for si, sy in enumerate(systems):
            v = values.get((ds, sy))
            x = x0 + si * bw
            if v is None:
                out.append('<text x="%.1f" y="%.1f" font-size="12" text-anchor="middle" fill="#9aa3bd">n/a</text>' % (x + bw / 2, TOP + ph - 6))
                continue
            h = ph * v / ymax
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" rx="3"><title>%s %s: %s</title></rect>' % (
                x + 2, TOP + ph - h, bw - 4, h, colour_for(sy, systems), escape(ds), escape(sy), fmt % v))
            out.append('<text x="%.1f" y="%.1f" font-size="13" text-anchor="middle" fill="#0d1630">%s</text>' % (
                x + bw / 2, TOP + ph - h - 6, fmt % v))
        out.append('<text x="%.1f" y="%d" font-size="18" font-weight="600" text-anchor="middle" fill="#0d1630">%s</text>' % (
            LEFT + gi * gw + gw / 2, TOP + ph + 28, escape(ds.upper())))
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#0d1630" stroke-width="2"/>' % (LEFT, TOP + ph, W - RIGHT, TOP + ph))
    lx = LEFT                                                    # legend
    for sy in systems:
        out.append('<rect x="%d" y="%d" width="16" height="16" fill="%s" rx="3"/>' % (lx, H - 60, colour_for(sy, systems)))
        out.append('<text x="%d" y="%d" font-size="16" fill="#0d1630">%s</text>' % (lx + 24, H - 47, escape(sy)))
        lx += 36 + 10 * len(sy)
    out.append("</svg>")
    return "\n".join(out) + "\n"


def make_figures(results_dir, out_dir):
    comps = load_comparisons(results_dir)
    datasets = sorted(comps)
    systems = sorted({s for d in comps.values() for s in d})
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, field, title, ylabel, fmt in CHARTS:
        values = {}
        for ds in datasets:
            for sy in systems:
                row = comps[ds].get(sy)
                v = row.get(field) if row else None
                values[(ds, sy)] = float(v) if isinstance(v, (int, float)) else None
        path = out_dir / (name + ".svg")
        path.write_text(grouped_bars(title, ylabel, fmt, datasets, systems, values), encoding="utf-8")
        written.append(path)
    index = out_dir / "index.html"
    index.write_text("<!DOCTYPE html><meta charset='utf-8'><title>SlopGate figures</title>"
                     "<body style='font-family:sans-serif;max-width:1040px;margin:24px auto'>%s</body>\n" % "".join(
                         "<img src='%s' alt='%s' style='width:100%%;margin-bottom:24px'>" % (p.name, p.stem) for p in written),
                     encoding="utf-8")
    return written + [index]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", required=True, help="directory holding <dataset>/comparison/comparison.json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        for p in make_figures(args.results, args.out):
            print("wrote", p)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
