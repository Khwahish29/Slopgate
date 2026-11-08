# 1. Introduction

<!-- DRAFT (Khwahish). Numbers marked [TBD] come from the Step 5 runs; do not fill them from D0 alone. -->

Open-source maintainers now receive vulnerability reports written, in whole or in part, by language models. Many
of these reports are fluent, well formatted and wrong: they name functions that do not exist, cite files and line
numbers that do not match the tree, or claim versions that were never released. Each one still costs a maintainer
time to read, reproduce and refute. The curl project's public experience with AI-generated bug-bounty submissions
is the motivating case for this work.

SlopGate is an evidence-first triage assistant for this setting. Given a report and a repository checkout, it
extracts the concrete, checkable claims the report makes (symbols, paths, line numbers, version tags, CWE ids),
checks each one against the code with read-only tools, and returns one of three verdicts: HALLUCINATED (a
load-bearing claim is contradicted by the repository), UNVERIFIED (needs a human), or REPRODUCIBLE. Every verdict
comes with an evidence ledger, and every sentence of the rationale must cite ledger rows that a tool actually
produced.

Two design commitments shape the system:

1. **Cost asymmetry.** Auto-closing a real vulnerability is far worse than wasting a reviewer's time. We weight a
   false HALLUCINATED at 500 times a wasted review, so the system abstains unless the contradiction is
   unambiguous. A dedicated skeptic pass tries to find an innocent explanation (renamed or removed code, a
   different release, a macro) before any HALLUCINATED verdict is accepted.
2. **Untrusted input.** Report text is data, not instructions. It is sanitized before any component reads it,
   injection attempts are recorded as signals, and no model output can set the verdict directly.

Real reports are mostly prose rather than templated fields, so claim extraction has to work on free text. We
compare a deterministic prose extractor with model-based extraction, and a fixed pipeline with an agent that plans
its tool calls.

**Contributions.**
- An evidence-ledger architecture in which verdicts are re-derived by a deterministic adjudicator and rationales
  are checked for citations (Section 2).
- Datasets: D1 (generated reports over fixture repositories), D2 (real curl reports), and derived sets D3/D4
  (Section 3).
- A baseline ladder, B0 to B3, that isolates what reading, grounding, planning and model calls each contribute
  (Section 3).
- Results: [TBD: headline accuracy / false-HALLUCINATED rate of the agent vs. the best baseline on D1 and D2,
  tool calls and cost per report] (Section 4), plus failure analysis (Section 5).

The rest of the report is organized as follows. Section 2 describes the system, Section 3 the data and evaluation
setup, Section 4 results, Section 5 failure analysis, Section 6 limitations and future work, and Section 7 team
contributions.
