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
