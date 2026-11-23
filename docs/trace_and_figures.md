# Trace viewer and figures

Both read evaluation outputs and change nothing.

## `slopgate/evaluation/trace_view.py`
Shows every step behind a verdict: report text (with `--data`), the agent's trace (extract, plan, claim_na, final), the evidence ledger (tool call, arguments, status), and the rationale, with a flag when the verdict is wrong.

```
python -m slopgate.evaluation.trace_view --predictions results/reproduction/d1/b3_rules_predictions.jsonl --costly --list
python -m slopgate.evaluation.trace_view --predictions P.jsonl --id d1-tinyhttp-t3-01 --data corpus/d1/d1.jsonl
python -m slopgate.evaluation.trace_view --predictions P.jsonl --wrong --limit 5 --md > wrong.md
```
Filters: `--id`, `--verdict`, `--wrong`, `--costly` (a report that should not be dismissed was dismissed), `--tier`, `--limit` (default 20, 0 = all). Use `--costly` first: those are the 500-cost errors.

## `slopgate/evaluation/figures.py`
Standard-library SVG bar charts per metric, datasets on the x axis, one bar per system: false dismissals, mean cost, accuracy, tool calls. Deterministic output, so files can be diffed.

```
make aggregate && make figures      # -> results/reproduction/figures/*.svg and index.html
```
Input is `<results>/<dataset>/comparison/comparison.json` from `make aggregate`. A system missing from a dataset is drawn as `n/a`, not as zero.

Tests: `tests/test_trace_view.py`, `tests/test_figures.py`.
