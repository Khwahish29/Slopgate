# Team Contribution Notes

## Khwahish Patel
- Implemented the claim extraction module for prose-based vulnerability reports.
- Structured report statements into claim objects with identifiers, types, spans, and roles.
- Added evidence-oriented output support so extracted claims can be tracked alongside repository checks.
- Helped align the core triage workflow with the stakeholder requirement that claims must be grounded before any verdict is accepted.

## Scope for this repository
This repository is intentionally scoped to the claim extraction and evidence representation contribution for the current milestone.

## Khwahish Patel: final milestone (Section 7)
- Prose claim extractor: `slopgate/agent_layer/prose_extract.py`
- B1 baseline, registered as `b1`: `slopgate/agent_layer/baselines/b1_rules.py`
- Skeptic pass: `slopgate/agent_layer/skeptic.py`
- Tests: `tests/test_prose_extract.py`, `tests/test_b1_skeptic.py`
- Report: Section 1 (`docs/section1_introduction.md`)
- Robustness evaluation (D3 suppression, D4 injection, sanitizer): `slopgate/evaluation/robustness.py`
- Skeptic wiring: rule checks at the agent's ref, re-adjudication, cached and capped skeptic model,
  objections and skeptic model cost in the agent trace (`skeptic.py`, skeptic call site in `agent.py`)
- Extractor fixes (`prose_extract.py`): generic bullet fields, docs paths, whole-word symbol/path
  association, test/fuzz paths lose ties
- Sanitizer improvements for injection and suppression (`extract.sanitize`): Unicode normalisation,
  hidden characters, pattern families, signal `kind`
- Repro-claim extractor for the sandbox: `slopgate/agent_layer/repro_extract.py`
- Calibration and HALLUCINATED threshold: `slopgate/evaluation/calibrate.py`
- Demo driver: `slopgate/demo.py`
- Tests: `tests/test_sanitize.py`, `tests/test_repro_extract.py`, `tests/test_skeptic_wiring.py`,
  `tests/test_robustness_calibrate_demo.py`, additions to `tests/test_prose_extract.py`
- Commits / PRs: _fill in after merge_

## Meet Patel: final milestone (Section 7)
- D1 generator and fixture repositories: `slopgate/datasets/d1.py`, `slopgate/datasets/fixtures.py`,
  `corpus/fixtures/{tinyjson,pktbuf,minicfg,tinyhttp}/`; dataset card `docs/d1_dataset.md`;
  sanity check `slopgate/datasets/d1_sanity.py`
- Citation verifier and verdict stage: `slopgate/agent_layer/citation_verifier.py`, the
  `verify_and_adjudicate` hook the agent's `finalize()` already calls (no change to `agent.py`)
- Tree-sitter grounding upgrade: `slopgate/agent_layer/ts_ground.py`, parser switch in `ground.py`
  (`SLOPGATE_PARSER=regex` default | `treesitter` | `auto`), optional pins in `requirements.txt`
- Tests: `tests/test_d1.py`, `tests/test_citation_verifier.py`, `tests/test_ts_ground.py`
- Report: Section 3 first half (`docs/section3_datasets.md`)
- D2: my share of the curl reports, _after the split is agreed_
- Commits / PRs: _fill in after merge_
