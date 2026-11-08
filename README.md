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
