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

## Kaushha Trivedi: final milestone
- B2 single-call baseline: file context windows around cited lines, bare-filename resolution, URL-like paths ignored, model failures recorded and abstained (`slopgate/agent_layer/baselines/b2_single.py`)
- B3 fixed pipeline: prose rule extractor shared with B1, links no longer treated as repository files, model errors and retries reported in the result (`slopgate/agent_layer/baselines/b3_fixed.py`)
- Rate-limit handling in `slopgate/agent_layer/llm.py`: 429/5xx retries with exponential backoff, `Retry-After` and "try again in Ns" hints, jitter, a 60 s cap, `RateLimitError` that the agent's throttle already recognises, `SLOPGATE_MAX_RETRIES` (default 5); `looks_like_url` rejects web addresses as file claims
- Trace viewer and figures: `slopgate/evaluation/trace_view.py`, `slopgate/evaluation/figures.py` (`docs/trace_and_figures.md`)
- Sandbox: `sandbox/Dockerfile`, `sandbox/runner.py`, `sandbox/launcher.py` (`docs/sandbox.md`)
- Tests: `tests/test_llm_backoff.py`, `tests/test_b2_context.py`, `tests/test_b3_fixes.py`, `tests/test_trace_view.py`, `tests/test_figures.py`, `tests/test_sandbox.py`
- Measured (offline `b3_rules`, regex parser), false dismissals of real reports before -> after: D1 21 -> 17, D3 10 -> 9, D4 6 -> 4. The remaining D1 ones are all the `tinyhttp` fixture and come from the regex parser: with `SLOPGATE_PARSER=treesitter` D1 B1/B3 have 0 and D4 has 0/0 (D3 B1 4, B3 3). Not measured: any live-model B2/B3 run, and the sandbox image under Docker.
- Commits / PRs: _fill in after merge_
