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
