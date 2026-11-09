# SlopGate

[![tests](https://github.com/Khwahish29/Slopgate/actions/workflows/tests.yml/badge.svg)](https://github.com/Khwahish29/Slopgate/actions/workflows/tests.yml)

SlopGate is an evidence-first triage assistant for AI-generated vulnerability reports. It sanitizes report text, extracts concrete claims, checks them against a repository checkout and ref, and produces a grounded verdict with supporting evidence.

## Project status

This repository contains the milestone 2 implementation scaffold and working triage utilities for the CSE 598 Agentic AI Capstone project. The current implementation focuses on the claim-extraction and evidence-grounding work for SlopGate.

## Features

- Report sanitization to strip injected instructions and flag suspicious text.
- Structured claim extraction from prose-like vulnerability reports.
- Repository-aware grounding checks for symbols, files, and version hints.
- Evidence ledger with stable identifiers for every fact and check.
- Deterministic verification for rationale and verdict support.
- Queue ranking based on risk and confidence.
- CLI and unit tests for local validation.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m slopgate.cli --help
```

## Example usage

```bash
python -m slopgate.cli \
  --report "The function parse_url in src/http.c at line 120 is vulnerable." \
  --repo-root /path/to/repo \
  --ref HEAD
```

## Repository layout

- `slopgate/` — Python package implementing the core system and claim extraction logic.
- `docs/` — milestone report and contribution notes.
- `tests/` — unit tests and regression checks.
- `requirements.txt` — Python dependencies.

## Milestone 2: reproduce the evaluation

```bash
pip install -r requirements.txt                      # tree-sitter is used by default (SLOPGATE_PARSER=auto)
python -W ignore -m unittest discover -s tests       # offline, no key needed
python -m slopgate.datasets.d1                       # D1: 164 generated reports over 4 fixture repos
python -m slopgate.datasets.d3_d4                    # D3 suppression (32), D4 injection (32), from D1
git clone https://github.com/curl/curl.git corpus/d2/curl
python -m slopgate.datasets.d2                       # D2 pilot: 18 public curl reports, pinned worktrees
for d in d0 d1 d2 d3 d4; do
  python -m slopgate.evaluation.harness --data corpus/$d/$d.jsonl \
    --systems b0 b1 b3_rules b2 b3_llm agent agent_no_skeptic --out results/$d
done
```

Systems: `b0` grep, `b1` rules, `b2`/`b2_alt` single model call, `b3_rules`/`b3_llm` fixed pipeline, `agent`,
and ablations `agent_no_skeptic`, `agent_same_model_skeptic`, `agent_no_citation`, `agent_no_history`.
Model systems need `XAI_API_KEY`, `XAI_BASE_URL`, `XAI_MODEL` (planner) and optionally `SKEPTIC_API_KEY`,
`SKEPTIC_BASE_URL`, `SKEPTIC_MODEL` (cross-model skeptic); without a key they are reported as skipped.
`SLOPGATE_PARSER=regex` reproduces the original grounding for the parser ablation.
