"""Confidence calibration and the HALLUCINATED operating threshold.

    python -m slopgate.evaluation.calibrate --fit results/d1/b1_predictions.jsonl \
        --eval results/d3/b1_predictions.jsonl results/d4/b1_predictions.jsonl --cv repo

Input: harness prediction files (rows with verdict, expected_verdict, confidence, status).

1. Reliability. Is a stated confidence of 0.9 right 90% of the time? Equal-width bins, expected
   calibration error (ECE) and Brier score, overall and for HALLUCINATED verdicts alone (the
   verdict that closes a report, so the one whose confidence matters).
2. Isotonic map. Pool-adjacent-violators fit of P(correct | confidence) for HALLUCINATED verdicts:
   a monotone table from the system's raw confidence to observed precision.
3. Threshold. The cost model is asymmetric (scoring.py: a false dismissal costs 500, a missed
   hallucination 1). Choose tau so that a HALLUCINATED verdict with confidence < tau is downgraded to
   UNVERIFIED, minimising total cost on the fit set. --cv repo (or tier) refits tau with each group
   held out and scores it on that group, which is the honest estimate on data this small.

The threshold is a recommendation with its evidence; this module does not change any system.
apply_threshold() is exported for whoever wires it in.
"""
import argparse
import collections
import json
import os

from .scoring import FALSE_DISMISSAL_COST, MISSED_HALLUCINATION_COST

H = "HALLUCINATED"


def load_rows(paths):
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            rows += [json.loads(line) for line in f if line.strip()]
    return rows


def usable(rows):
    return [r for r in rows if r.get("status") == "ok" and isinstance(r.get("confidence"), (int, float))
            and not isinstance(r.get("confidence"), bool)]


def correct(r):
    return r["verdict"] == r["expected_verdict"]


def reliability(rows, bins=10):
    """-> {bins: [...], ece, brier, n}. Confidence is read as P(this verdict is correct)."""
    rows = usable(rows)
    if not rows:
        return {"bins": [], "ece": None, "brier": None, "n": 0}
    acc = collections.defaultdict(list)
    for r in rows:
        b = min(int(r["confidence"] * bins), bins - 1)
        acc[b].append(r)
    out, ece = [], 0.0
    for b in sorted(acc):
        rs = acc[b]
        conf = sum(r["confidence"] for r in rs) / len(rs)
        a = sum(correct(r) for r in rs) / len(rs)
        ece += len(rs) / len(rows) * abs(conf - a)
        out.append({"range": [b / bins, (b + 1) / bins], "n": len(rs), "mean_confidence": round(conf, 4),
                    "accuracy": round(a, 4)})
    brier = sum((r["confidence"] - correct(r)) ** 2 for r in rows) / len(rows)
    return {"bins": out, "ece": round(ece, 4), "brier": round(brier, 4), "n": len(rows)}


def isotonic(points):
    """Pool-adjacent-violators on [(x, y)], y in {0,1}. -> [(x_lo, x_hi, value, n)] non-decreasing.
    Equal x values form one block first: tied confidences must get one calibrated value."""
    tied = collections.OrderedDict()
    for x, y in sorted(points):
        s = tied.setdefault(x, [0.0, 0])
        s[0] += y
        s[1] += 1
    blocks = []
    for x, (ysum, n) in tied.items():
        blocks.append([x, x, ysum / n, n])
        while len(blocks) > 1 and blocks[-2][2] > blocks[-1][2]:
            lo, hi, v, n = blocks.pop()
            p = blocks[-1]
            p[2] = (p[2] * p[3] + v * n) / (p[3] + n)
            p[1], p[3] = hi, p[3] + n
    return [(lo, hi, round(v, 4), n) for lo, hi, v, n in blocks]


def apply_threshold(rows, tau):
    """Copy of rows with HALLUCINATED below tau downgraded to UNVERIFIED (rows without a
    confidence are left alone)."""
    out = []
    for r in rows:
        r = dict(r)
        c = r.get("confidence")
        if r.get("status") == "ok" and r.get("verdict") == H and isinstance(c, (int, float)) and c < tau:
            r["verdict"] = "UNVERIFIED"
            r["calibrated"] = True
        out.append(r)
    return out


def cost(rows):
    rows = [r for r in rows if r.get("status") == "ok"]
    fd = sum(r["verdict"] == H and r["expected_verdict"] != H for r in rows)
    mh = sum(r["verdict"] != H and r["expected_verdict"] == H for r in rows)
    caught = sum(r["verdict"] == H and r["expected_verdict"] == H for r in rows)
    pos = sum(r["expected_verdict"] == H for r in rows)
    return {"cost": FALSE_DISMISSAL_COST * fd + MISSED_HALLUCINATION_COST * mh, "false_dismissals": fd,
            "missed_hallucinations": mh, "hallucination_recall": round(caught / pos, 4) if pos else None,
            "auto_closed": caught + fd, "n": len(rows)}


def fit_threshold(rows):
    """tau minimising cost. Candidates: every HALLUCINATED confidence, plus 0 (keep all) and a value
    above 1 (close nothing). Ties go to the smaller tau: same cost, more reports closed automatically."""
    conf = sorted({r["confidence"] for r in usable(rows) if r["verdict"] == H})
    cands = [0.0] + conf + [1.01]
    best = None
    for t in cands:
        c = cost(apply_threshold(rows, t))["cost"]
        if best is None or c < best[1]:
            best = (t, c)
    return best[0]


def cross_validate(rows, field):
    """Leave-one-group-out: tau fitted without the group, scored on the group. -> summary."""
    groups = collections.defaultdict(list)
    for r in rows:
        groups[str(r.get(field))].append(r)
    if len(groups) < 2:
        return None
    held, per = [], {}
    for g, rs in sorted(groups.items()):
        train = [r for k, v in groups.items() if k != g for r in v]
        tau = fit_threshold(train)
        scored = apply_threshold(rs, tau)
        held += scored
        per[g] = {"tau": tau, **cost(scored)}
    return {"by_group": per, "pooled": cost(held), "uncalibrated": cost(rows)}


def calibrate(fit_rows, eval_sets=None, cv=None, bins=10):
    hall = [r for r in usable(fit_rows) if r["verdict"] == H]
    tau = fit_threshold(fit_rows)
    out = {"n_fit": len(usable(fit_rows)),
           "reliability_all": reliability(fit_rows, bins),
           "reliability_hallucinated": reliability(hall, bins),
           "isotonic_hallucinated": [{"from": a, "to": b, "precision": v, "n": n}
                                     for a, b, v, n in isotonic([(r["confidence"], correct(r)) for r in hall])],
           "threshold": tau,
           "fit": {"before": cost(fit_rows), "after": cost(apply_threshold(fit_rows, tau))},
           "costs": {"false_dismissal": FALSE_DISMISSAL_COST, "missed_hallucination": MISSED_HALLUCINATION_COST}}
    if cv:
        out["cross_validation"] = {"by": cv, **(cross_validate(fit_rows, cv) or {"note": "fewer than 2 groups"})}
    out["eval"] = {}
    for name, rows in (eval_sets or {}).items():
        out["eval"][name] = {"before": cost(rows), "after": cost(apply_threshold(rows, tau)),
                             "reliability_hallucinated": reliability([r for r in usable(rows) if r["verdict"] == H], bins)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fit", nargs="+", required=True, help="prediction files to fit on")
    ap.add_argument("--eval", nargs="*", default=[], help="prediction files to score the fitted threshold on")
    ap.add_argument("--cv", choices=["repo", "tier"], default=None)
    ap.add_argument("--bins", type=int, default=10)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    res = calibrate(load_rows(a.fit), {p: load_rows([p]) for p in a.eval}, a.cv, a.bins)
    res["fit_files"] = a.fit
    f = res["fit"]
    print("fit on %d rows: ECE %s (all), %s (HALLUCINATED); threshold tau = %s"
          % (res["n_fit"], res["reliability_all"]["ece"], res["reliability_hallucinated"]["ece"], res["threshold"]))
    print("  cost %d -> %d, false dismissals %d -> %d, recall %s -> %s"
          % (f["before"]["cost"], f["after"]["cost"], f["before"]["false_dismissals"], f["after"]["false_dismissals"],
             f["before"]["hallucination_recall"], f["after"]["hallucination_recall"]))
    cvr = res.get("cross_validation")
    if cvr and "pooled" in cvr:
        print("  leave-one-%s-out: cost %d -> %d (held-out)" % (cvr["by"], cvr["uncalibrated"]["cost"], cvr["pooled"]["cost"]))
    for name, e in res["eval"].items():
        print("  eval %s: cost %d -> %d, false dismissals %d -> %d"
              % (name, e["before"]["cost"], e["after"]["cost"], e["before"]["false_dismissals"],
                 e["after"]["false_dismissals"]))
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)
        print("wrote %s" % a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
