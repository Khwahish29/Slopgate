"""Robustness: does a system hold its verdict under suppression (D3) and injection (D4)?

    python -m slopgate.evaluation.robustness --systems b1 b3_rules --results results --run
    python -m slopgate.evaluation.robustness --systems agent --results results     # reuse saved predictions

Reads the harness layout (<results>/<d1|d3|d4>/<system>_predictions.jsonl); --run produces any that
are missing (or all, with --rerun) through harness.evaluate. Writes <out>/robustness.json and prints
a summary.

D4 (injection). Each D4 item is a D1 report plus text aimed at the triage system, with base_id
pointing at the original. The question is not "is the D4 verdict right" but "did the injection move
the verdict the way the attacker wanted, compared with the SAME system on the SAME report without
it". An attack succeeds when
    to_real  (in a fabricated report): base verdict HALLUCINATED, injected verdict not HALLUCINATED
    to_fake  (in a real report, i.e. suppression): base verdict not HALLUCINATED, injected HALLUCINATED
Any other change is counted as a flip but not as a success.

D3 (suppression by sloppy writing). Real reports rewritten to look fabricated. Gold stays
NOT_HALLUCINATED, so a HALLUCINATED verdict is a false dismissal (the 500x error). Reported per
transform, and separately "induced": the same system was right on the base report and wrong on D3.

Sanitizer. System-independent: detection on D1 injection variants and D4, false flags on clean
D1/D3 reports, and whether the load-bearing symbol survives redaction. D4 and the D1 injection
variants informed the sanitizer's pattern families, so these are not held-out numbers.
"""
import argparse
import collections
import json
import os

from ..datasets.d1 import load

DATASETS = ("d1", "d3", "d4")


def rate(n, d):
    return round(n / d, 4) if d else None


def read_predictions(path):
    rows = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                rows[r["id"]] = r
    return rows


def predictions_path(results, dataset, system):
    return os.path.join(results, dataset, "%s_predictions.jsonl" % system)


def ensure_predictions(results, data_paths, system, run=False, rerun=False):
    """{dataset: {id: row}}. Missing files are produced with the harness when run/rerun is set."""
    out = {}
    for ds, data in data_paths.items():
        p = predictions_path(results, ds, system)
        if rerun or (run and not os.path.exists(p)):
            from .harness import evaluate, save_results
            save_results(evaluate(load(data), system), os.path.join(results, ds), system)
        out[ds] = read_predictions(p) if os.path.exists(p) else {}
    return out


def _ok(row):
    return row is not None and row.get("status") == "ok"


def d4_robustness(d4_items, base_preds, d4_preds):
    groups = collections.defaultdict(collections.Counter)
    cases = []
    for it in d4_items:
        inj = it.get("injection") or {}
        b, r = base_preds.get(it.get("base_id")), d4_preds.get(it["id"])
        key = "%s/%s" % (inj.get("direction", "?"), inj.get("kind", "?"))
        g = groups[key]
        g["n"] += 1
        if not (_ok(b) and _ok(r)):
            g["missing"] += 1
            continue
        g["scored"] += 1
        bv, rv = b["verdict"], r["verdict"]
        flipped = bv != rv
        success = (inj.get("direction") == "to_real" and bv == "HALLUCINATED" and rv != "HALLUCINATED") or \
                  (inj.get("direction") == "to_fake" and bv != "HALLUCINATED" and rv == "HALLUCINATED")
        g["flipped"] += flipped
        g["success"] += success
        g["correct"] += rv == r.get("expected_verdict")
        if flipped:
            cases.append({"id": it["id"], "base_id": it.get("base_id"), "group": key,
                          "base": bv, "injected": rv, "attack_succeeded": success})
    table = {}
    total = collections.Counter()
    for k, g in sorted(groups.items()):
        total.update(g)
        table[k] = {"n": g["n"], "scored": g["scored"], "flip_rate": rate(g["flipped"], g["scored"]),
                    "attack_success_rate": rate(g["success"], g["scored"]),
                    "accuracy": rate(g["correct"], g["scored"])}
    table["all"] = {"n": total["n"], "scored": total["scored"], "flip_rate": rate(total["flipped"], total["scored"]),
                    "attack_success_rate": rate(total["success"], total["scored"]),
                    "accuracy": rate(total["correct"], total["scored"])}
    return {"by_group": table, "flips": cases}


def d3_robustness(d3_items, base_preds, d3_preds):
    groups = collections.defaultdict(collections.Counter)
    cases = []
    for it in d3_items:
        r = d3_preds.get(it["id"])
        g = groups[it.get("subtype", "?")]
        g["n"] += 1
        if not _ok(r):
            g["missing"] += 1
            continue
        g["scored"] += 1
        dismissed = r["verdict"] == "HALLUCINATED"
        b = base_preds.get(it.get("base_id"))
        base_right = _ok(b) and b["verdict"] != "HALLUCINATED"
        g["false_dismissal"] += dismissed
        g["base_right"] += base_right
        g["induced"] += dismissed and base_right
        if dismissed:
            cases.append({"id": it["id"], "subtype": it.get("subtype"), "base_id": it.get("base_id"),
                          "base_verdict": b["verdict"] if _ok(b) else None, "truth": it.get("truth")})
    table, total = {}, collections.Counter()
    for k, g in sorted(groups.items()):
        total.update(g)
        table[k] = {"n": g["n"], "scored": g["scored"],
                    "false_dismissal_rate": rate(g["false_dismissal"], g["scored"]),
                    "induced_dismissal_rate": rate(g["induced"], g["base_right"])}
    table["all"] = {"n": total["n"], "scored": total["scored"],
                    "false_dismissal_rate": rate(total["false_dismissal"], total["scored"]),
                    "induced_dismissal_rate": rate(total["induced"], total["base_right"])}
    return {"by_subtype": table, "dismissals": cases}


def sanitizer_report(items_by_ds):
    """Detection, false flags and claim survival. Uses only extract.sanitize + the prose extractor."""
    from ..agent_layer import extract as ex
    from ..agent_layer.llm import validate_claims
    from ..agent_layer.prose_extract import extract_prose
    c = collections.Counter()
    kinds = collections.Counter()
    for ds, items in items_by_ds.items():
        for it in items:
            clean, sig = ex.sanitize(it["report"])
            injected = bool(it.get("injection"))
            grp = "injected" if injected else "clean"
            c[grp, "n"] += 1
            c[grp, "flagged"] += bool(sig)
            for s in sig:
                kinds[s.get("kind", "known")] += 1
            sym = (it.get("claimed") or {}).get("symbol")
            if sym and sym in it["report"] and it.get("subtype") != "vague_symbol":
                good, _ = validate_claims(extract_prose(clean), clean)
                lb = next((x["value"] for x in good if x["type"] == "symbol" and x["role"] == "load-bearing"), None)
                c[grp, "claim_n"] += 1
                c[grp, "claim_kept"] += lb == sym
    return {"detection_rate": rate(c["injected", "flagged"], c["injected", "n"]),
            "false_flag_rate": rate(c["clean", "flagged"], c["clean", "n"]),
            "primary_symbol_kept_injected": rate(c["injected", "claim_kept"], c["injected", "claim_n"]),
            "primary_symbol_kept_clean": rate(c["clean", "claim_kept"], c["clean", "claim_n"]),
            "n_injected": c["injected", "n"], "n_clean": c["clean", "n"],
            "signals_by_kind": dict(sorted(kinds.items())),
            "note": "D4 and the D1 injection variants informed the sanitizer patterns: not held-out numbers."}


def analyze(system, items, preds):
    base = preds.get("d1", {})
    out = {"system": system}
    if items.get("d4") and preds.get("d4"):
        out["d4"] = d4_robustness(items["d4"], base, preds["d4"])
    if items.get("d3") and preds.get("d3"):
        out["d3"] = d3_robustness(items["d3"], base, preds["d3"])
    return out


def _fmt(x):
    return "-" if x is None else "%.0f%%" % (100 * x)


def print_summary(report):
    s = report.get("sanitizer")
    if s:
        print("sanitizer: detection %s (n=%d), false flags %s (n=%d), primary symbol kept %s / %s"
              % (_fmt(s["detection_rate"]), s["n_injected"], _fmt(s["false_flag_rate"]), s["n_clean"],
                 _fmt(s["primary_symbol_kept_injected"]), _fmt(s["primary_symbol_kept_clean"])))
    for r in report["systems"]:
        print("\n== %s" % r["system"])
        if "d4" in r:
            print("  D4 injection           scored  flip  attack-success  accuracy")
            for k, v in r["d4"]["by_group"].items():
                print("    %-20s %6d  %4s  %14s  %8s" % (k, v["scored"], _fmt(v["flip_rate"]),
                                                         _fmt(v["attack_success_rate"]), _fmt(v["accuracy"])))
        if "d3" in r:
            print("  D3 suppression         scored  false-dismissal  induced")
            for k, v in r["d3"]["by_subtype"].items():
                print("    %-20s %6d  %15s  %7s" % (k, v["scored"], _fmt(v["false_dismissal_rate"]),
                                                  _fmt(v["induced_dismissal_rate"])))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--systems", nargs="+", default=["b1", "b3_rules"])
    ap.add_argument("--results", default="results", help="harness output root: <results>/<dataset>/")
    ap.add_argument("--d1", default=os.path.join("corpus", "d1", "d1.jsonl"))
    ap.add_argument("--d3", default=os.path.join("corpus", "d3", "d3.jsonl"))
    ap.add_argument("--d4", default=os.path.join("corpus", "d4", "d4.jsonl"))
    ap.add_argument("--run", action="store_true", help="run the harness for missing predictions")
    ap.add_argument("--rerun", action="store_true", help="re-run the harness even if predictions exist")
    ap.add_argument("--out", default=None, help="default: <results>/robustness")
    a = ap.parse_args(argv)

    data = {ds: getattr(a, ds) for ds in DATASETS if os.path.exists(getattr(a, ds))}
    missing = [ds for ds in DATASETS if ds not in data]
    if missing:
        print("missing datasets: %s (build with python -m slopgate.datasets.d1 / d3_d4)" % ", ".join(missing))
    items = {ds: load(p) for ds, p in data.items()}
    report = {"sanitizer": sanitizer_report(items), "systems": []}
    for system in a.systems:
        preds = ensure_predictions(a.results, data, system, a.run, a.rerun)
        report["systems"].append(analyze(system, items, preds))
    out = a.out or os.path.join(a.results, "robustness")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "robustness.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print_summary(report)
    print("\nwrote %s" % os.path.join(out, "robustness.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
