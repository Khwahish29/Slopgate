# 3. Datasets and grounding (first half)

<!-- DRAFT (Meet). Numbers here are dataset statistics and the dataset author's sanity check
     (python -m slopgate.datasets.d1_sanity). System results for Section 4 come from the Step 5 harness runs.
     [TBD] marks what depends on D2 or on those runs. Krish writes the second half (baselines). -->

## 3.1 D1: generated reports with labels known by construction

D1 measures one thing: whether a system can tell a report whose concrete claims are invented from one whose claims
are real, when the answer is certain. Each report is about one of four small C repositories that we wrote for the
purpose (`corpus/fixtures/`). Each repository is a real git repository with two tagged releases (`<repo>-1_0`,
`<repo>-1_1`). One function exists in 1.0 and was removed in 1.1, so version and history checks see real data.

Three repositories use a house style with each function signature on one line. The fourth, *tinyhttp*, is written
in curl's style: the return type on its own line, function-like macros and static prototypes. We added it after
finding that our original grounding code misread exactly that style (Section 3.3). Since D2 is drawn from curl,
D1 should contain the shape D2 has.

Reports fall into five tiers. The tier fixes the gold label:

| Tier | Gold | Construction |
|---|---|---|
| T1 | HALLUCINATED | invented function (in no version). Sometimes an invented file or an unreleased version too |
| T2 | HALLUCINATED | name only mentioned: in a comment, a log string, or the docs. Never defined |
| T3 | NOT_HALLUCINATED | real but hard to ground: dead code, callback-only, or removed after the claimed release |
| T4 | NOT_HALLUCINATED | real reachable function or macro, correct file, line and version |
| T5 | HALLUCINATED | real function, real file, in-range line, but the function is not in that file |

T2 is the case a text search gets wrong: the name is in the tree. T5 is the hardest hallucination: every claim
checks out alone, and only their association is false. T3 is the safety tier. These reports are real, but a
careless system will call them hallucinated, which is the error our cost model weights 500× (Section 2).

Report text is rendered from templates in three styles, each drawn with fixed probability: a D0-like header block
(*fields*, 85), narrative *prose* (53), and a verbose model-style advisory with reference links (*slop*, 26).
Every real report describes a defect that is actually present at the cited line. Invented reports reuse the same
specific, confident language. Sixteen *injection* variants copy a T1 or T4 report and add text aimed at the
triage system, pushing towards the wrong verdict. Half use phrasing our sanitizer recognises and half do not.

**Validity.** Labels hold by construction. Every item is also re-proved before it is written, using string checks
and the fixture's own definition index, never the grounding code being evaluated (Section 3.3). Fixture metadata
is checked against the code when it loads. Tests cross-check every item against the real tools as a second
opinion. The generator is deterministic: seed 598 gives byte-identical output and identical commit ids.

**Size.** 164 reports, 41 per repository: T1 40, T2 24, T3 20, T4 48, T5 32. That is 96 hallucinated and 68 real.
129 reports claim a version, 16 carry an injection.

**Limits.** The text is templated, so D1 tests grounding and reading on controlled cases. It does not test
robustness to real prose. On the three house-style repositories, a deterministic single-pass pipeline (B1 with
the tree-sitter parser) scores perfectly. D2 is where the systems separate.

## 3.2 D2: real curl reports

[TBD: source of the reports, how they were split between Meet / Krish / Khwahish, labeling protocol and
agreement, counts by label. D3 and D4 are derived from D1 and D2 (Kaushha, Prakruti).]

## 3.3 Grounding: from line regexes to a syntax tree

Every verdict rests on a small number of read-only tools (`agent_layer/tools.py`). The most important one,
`find_symbol`, separates three states: ABSENT, MENTIONED (the name appears only in comments, strings or prose)
and DEFINED. The original implementation found definitions with line regexes after blanking comments and strings.

On curl-style C that implementation fails in a dangerous direction:

* a definition whose name starts the line (`CURLcode` on one line, `Curl_http_done(...)` on the next) is not
  recognised, so a real function is reported as MENTIONED;
* a function-like macro (`#define Curl_safefree(p) ...`) sits on a preprocessor line, which the scan blanks
  as if it were a comment. The macro becomes MENTIONED too;
* static prototypes are counted as both definitions and call sites.

MENTIONED on the report's primary symbol is a HALLUCINATED verdict under the rule adjudicator. So every one of
these misreadings auto-closes a real report.

We replaced the scan, for `.c` and `.h` files, with a tree-sitter parse (`agent_layer/ts_ground.py`).
Definitions are `function_definition` and `preproc_function_def` nodes, callers are `call_expression` nodes, and
"in code" means outside comment and string nodes. The record format is unchanged, so every caller is unaffected.
`checked_by` names the parser that produced each record. The parser is selected with `SLOPGATE_PARSER`
(`regex`, the original scan and current default, or `treesitter`), so the two can be compared as an ablation.
Without the optional dependency the system always uses regex.

Dataset author's sanity check on D1 (key-free systems only; the agent runs in Step 5):

| System / parser | Correct | T1 | T2 | T3 | T4 | T5 | False HALLUCINATED |
|---|---|---|---|---|---|---|---|
| B1 / regex | 147/164 | 40/40 | 24/24 | 15/20 | 36/48 | 32/32 | 17 |
| B1 / tree-sitter | 164/164 | 40/40 | 24/24 | 20/20 | 48/48 | 32/32 | 0 |
| B3-rules / regex | 141/164 | 40/40 | 22/24 | 15/20 | 32/48 | 32/32 | 21 |
| B3-rules / tree-sitter | 153/164 | 40/40 | 22/24 | 18/20 | 41/48 | 32/32 | 9 |

All 17 false HALLUCINATED verdicts B1 makes with the regex parser fall on tinyhttp, the curl-style repository:
every real report there. On the three house-style repositories the two parsers agree on every symbol (this is
tested). The parser change only removes errors.

B3-rules' remaining nine false HALLUCINATED verdicts are a separate reading error. Its rule extractor takes the
CWE reference link in *slop*-style reports (`cwe.mitre.org/data/definitions/787.html`) for a C header path
(`.../787.h`), then finds that the "file" does not exist. The prose extractor B1 uses does not make this mistake.
Its two missed hallucinations come from picking a real caller named in the summary as the primary symbol.

[TBD: the same parser comparison on D2 once the curl reports are labeled. This is where the upgrade should
matter most.]
