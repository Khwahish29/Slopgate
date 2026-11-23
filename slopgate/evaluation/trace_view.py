"""Read a predictions file and show, for each report, every step that led to its verdict.

    python -m slopgate.evaluation.trace_view --predictions results/reproduction/d1/b3_rules_predictions.jsonl --wrong
    python -m slopgate.evaluation.trace_view --predictions P.jsonl --id d1-tinyhttp-t3-01 --data corpus/d1/d1.jsonl
    python -m slopgate.evaluation.trace_view --predictions P.jsonl --list
    python -m slopgate.evaluation.trace_view --predictions P.jsonl --costly --md > costly.md

A predictions row (see harness.make_result_row) already carries the evidence ledger, the trace
and the rationale; this module only lays them out. It never re-runs a system or changes a row.

Selection (all optional, combined with AND):
    --id ID [ID ...]   exact report ids         --verdict V   rows whose verdict is V
    --wrong            verdict != expected      --costly      a real report that was dismissed
    --tier T           tier label               --limit N     at most N rows (default 20, 0 = all)
Output: plain text, or Markdown with --md. --data adds the report text (JSONL with id and report).
"""
import argparse
import json
import sys
from pathlib import Path

DISMISS = "HALLUCINATED"
RESULT_SKIP = {"status", "tag", "record", "ref_used", "known_tags", "version"}   # shown elsewhere or too bulky


def load_rows(path):
    rows = []
    with Path(path).open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError("%s line %d: %s" % (path, n, exc)) from exc
    return rows


def load_reports(path):
    """id -> report text from a dataset JSONL (D1/D3/D4 style rows with `report`)."""
    out = {}
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                item = json.loads(line)
                if "id" in item and item.get("report") is not None:
                    out[item["id"]] = item["report"]
    return out


def is_wrong(row):
    return row.get("status") == "ok" and row.get("verdict") != row.get("expected_verdict")


def is_costly(row):
    """The expensive error: a report that should not be dismissed was dismissed."""
    return row.get("verdict") == DISMISS and row.get("expected_verdict") not in (None, DISMISS)


def select(rows, ids=None, verdict=None, wrong=False, costly=False, tier=None, limit=20):
    out = []
    for r in rows:
        if ids and r.get("id") not in ids:
            continue
        if verdict and r.get("verdict") != verdict:
            continue
        if wrong and not is_wrong(r):
            continue
        if costly and not is_costly(r):
            continue
        if tier and r.get("tier") != tier:
            continue
        out.append(r)
    return out[:limit] if limit else out


def _short(v, n=70):
    s = v if isinstance(v, str) else json.dumps(v, default=str, sort_keys=True)
    return s if len(s) <= n else s[:n - 3] + "..."


def fmt_args(args):
    return ", ".join("%s=%s" % (k, _short(v, 40)) for k, v in (args or {}).items())


def fmt_result(res):
    extra = [(k, v) for k, v in (res or {}).items() if k not in RESULT_SKIP and v not in (None, "", [], {})]
    return "; ".join("%s=%s" % (k, _short(v, 48)) for k, v in extra[:3])


def verdict_line(row):
    tag = ""
    if row.get("status") != "ok":
        tag = "  [%s]" % (row.get("status") or "no result").upper()
    elif is_costly(row):
        tag = "  WRONG: a report that should not be dismissed was dismissed"
    elif is_wrong(row):
        tag = "  WRONG"
    else:
        tag = "  correct"
    conf = row.get("confidence")
    return "verdict %s%s  expected %s%s" % (
        row.get("verdict"), " (conf %.2f)" % conf if isinstance(conf, (int, float)) else "",
        row.get("expected_verdict"), tag)


def trace_lines(trace):
    """One readable line per trace step. Known step kinds get a tailored line; others a generic one."""
    out = []
    for st in trace or []:
        kind = st.get("step", "?")
        if kind == "extract":
            if "error" in st:
                out.append("extract   ERROR %s" % _short(st["error"], 150))
            else:
                out.append("extract   source=%s claims=%s%s" % (
                    st.get("source", "?"), st.get("claims", "?"),
                    " discarded=%s" % st["discarded"] if st.get("discarded") else ""))
        elif kind == "plan":
            head = "plan #%s  %s" % (st.get("n", "?"), st.get("decision", "?"))
            if st.get("tool"):
                head += "  %s(%s)" % (st["tool"], fmt_args(st.get("args")))
            out.append(head)
            if st.get("thought"):
                out.append("          why: %s" % _short(st["thought"], 160))
            for ev in st.get("events") or []:
                out.append("          event: %s" % _short(ev, 140))
        elif kind == "claim_na":
            out.append("n/a       claim %s: %s" % (st.get("claim_id"), _short(st.get("why", ""), 140)))
        elif kind == "final":
            out.append("final     stop=%s" % st.get("stop_reason"))
            for key in ("claim_states", "verdict_events", "finalize_events"):
                if st.get(key):
                    out.append("          %s: %s" % (key, _short(st[key], 150)))
        else:
            out.append("%-9s %s" % (kind, _short({k: v for k, v in st.items() if k != "step"}, 150)))
    return out


def ledger_lines(ledger):
    return ["%-4s %s(%s)  ->  %s%s" % (
        e.get("id"), e.get("tool"), fmt_args(e.get("args")), e.get("status"),
        ("   [%s]" % fmt_result(e.get("result"))) if fmt_result(e.get("result")) else "")
        for e in ledger or []]


def render_row(row, report=None, md=False, report_lines=12):
    """Text (or Markdown) for one predictions row."""
    h = "%s  |  %s  |  tier %s" % (row.get("id"), row.get("system"), row.get("tier"))
    cost = "tool calls %s, model calls %s, tokens %s, latency %s s" % (
        row.get("tool_calls"), row.get("model_calls"), row.get("tokens"),
        round(row["latency_s"], 2) if isinstance(row.get("latency_s"), (int, float)) else "?")
    out = []
    out.append(("## " + h) if md else ("=" * 100 + "\n" + h))
    out.append(("**" + verdict_line(row) + "**") if md else verdict_line(row))
    out.append(cost)
    if row.get("error"):
        out.append("error: %s" % row["error"])
    if report:
        body = report.strip().splitlines()
        shown = body[:report_lines] + (["... (%d more lines)" % (len(body) - report_lines)] if len(body) > report_lines else [])
        out.append("\nREPORT" if not md else "\n### Report")
        out.extend(("    " + l) if not md else ("> " + l) for l in shown)
    for title, lines in (("TRACE", trace_lines(row.get("trace"))),
                         ("EVIDENCE LEDGER", ledger_lines(row.get("ledger"))),
                         ("WHY", ["- %s%s" % (r.get("text"), " %s" % r["cites"] if r.get("cites") else "")
                                  for r in row.get("rationale") or []])):
        if not lines:
            continue
        out.append(("\n" + title) if not md else ("\n### " + title.title()))
        out.extend(("    " + l) if not md else ("    " + l) for l in lines)
    return "\n".join(out)


def list_lines(rows):
    out = ["%-34s %-8s %-13s %-13s %s" % ("id", "tier", "expected", "verdict", "")]
    for r in rows:
        mark = "COSTLY" if is_costly(r) else ("wrong" if is_wrong(r) else "")
        out.append("%-34s %-8s %-13s %-13s %s" % (r.get("id"), r.get("tier"), r.get("expected_verdict"), r.get("verdict"), mark))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--data", help="dataset JSONL; adds the report text")
    ap.add_argument("--id", nargs="*")
    ap.add_argument("--verdict")
    ap.add_argument("--wrong", action="store_true")
    ap.add_argument("--costly", action="store_true")
    ap.add_argument("--tier")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--list", action="store_true", help="one line per selected row")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args(argv)
    rows = select(load_rows(args.predictions), set(args.id) if args.id else None, args.verdict,
                  args.wrong, args.costly, args.tier, args.limit)
    if not rows:
        print("no rows match", file=sys.stderr)
        return 1
    if args.list:
        print("\n".join(list_lines(rows)))
        return 0
    reports = load_reports(args.data) if args.data else {}
    print("\n\n".join(render_row(r, reports.get(r.get("id")), args.md) for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
