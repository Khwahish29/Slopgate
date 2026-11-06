# B3: fixed LLM pipeline

Baseline B3 from Milestone 1: Grok extracts the claims, every tool runs on every claim in a fixed order, and the
rule adjudicator decides. No planning, no early stopping, no model-written verdict.

1. Sanitize the report (instruction-like text is stripped and flagged).
2. One model call extracts typed claims (symbol, path, line, tag, CWE). A claim whose quoted text is not in the
   report is discarded. Malformed output gets one repair retry, then falls back to the regex extractor.
3. `fixed_order` builds the tool list from the claims alone: `find_symbol`, `git_history`, `check_reachability`
   per symbol; `check_path` per path; `symbol_in_file` per symbol-path pair; `check_line_range` per line-path
   pair; `resolve_tag` per tag. Earlier results never change the list.
4. The rule adjudicator reads the evidence ledger and returns the verdict.

Code: `baselines/b3_fixed.py` (pipeline), `llm.py` (client, extraction), `tools.py`, `ledger.py`, `verifier.py`
(deterministic verdict). `ground.py`, `adjudicate.py`, `extract.py` are the stakeholder's baseline, unchanged.

## Run

```bash
python3 -W ignore -m unittest discover -s tests          # offline tests, scripted model
python3 eval/run_b3.py                                    # b3_rules on D0 and D1 (no model)
python3 eval/run_b3.py --llm --dry-run                    # estimate Grok calls, sends nothing
export XAI_API_KEY=... XAI_BASE_URL=... XAI_MODEL=...
python3 eval/run_b3.py --llm                              # real Grok run
```

`SLOPGATE_MAX_MODEL_CALLS` (default 1000) caps real model requests. The last column of the table counts reports that
fell back to the regex extractor, so a degraded run is visible.

## Status

`b3_llm` is implemented and tested with a scripted model; it has not been run against Grok. `b3_rules` (same
pipeline, rule extractor) has been run on D0 (19 reports) and D1 (123 generated reports, `corpus/gen_sets.py`).
