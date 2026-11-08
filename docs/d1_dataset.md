# D1: generated reports over fixture repositories

Owner: Meet. Code: `slopgate/datasets/`. Fixtures: `corpus/fixtures/`. Tests: `tests/test_d1.py`.

## Build it

```bash
python -m slopgate.datasets.d1          # builds corpus/fixtures/out/<repo> (git) and corpus/d1/
python -m slopgate.datasets.d1_sanity   # optional: b1 / b3_rules on D1 under both grounding parsers
```

Both outputs are gitignored (`corpus/d1/`, `corpus/fixtures/out/`) and fully reproducible. The same seed always
gives byte-identical `d1.jsonl` and identical commit ids, because author, committer and dates are fixed.
`--seed N` gives a different but equally valid draw. `--n-t1 … --n-inj` change the per-repo counts.

## Files

| Path | What |
|---|---|
| `corpus/d1/d1.jsonl` | one report per line |
| `corpus/d1/reports/<id>.md` | the same report text, for `System.triage(report_path, ws, repo)` |
| `corpus/d1/manifest.json` | counts by tier / gold / subtype / style / repo, seed, commit ids |
| `corpus/fixtures/out/<repo>` | the git repository the report is about (tags `<repo>-1_0`, `<repo>-1_1`) |

## Record format

The six agreed fields come first. The rest are extra and can be ignored.

| Field | Meaning |
|---|---|
| `id` | `d1-<repo>-<tier>[-inj]-<nn>` |
| `report` | the report **text** (the file is at `report_path`) |
| `repo` | path to the fixture git repo, relative to the project root |
| `ref` | always `HEAD`. A report may claim an older version, which the tools resolve themselves |
| `gold` | `HALLUCINATED` or `NOT_HALLUCINATED` (the D0 vocabulary) |
| `tier` | `T1` … `T5` |
| `expected_verdict` | what a correct system returns: `HALLUCINATED`, or `UNVERIFIED` for real reports (no tool can confirm a bug) |
| `subtype` | finer case, e.g. `mention_only_string`, `removed_after_claimed_version`, `wrong_file`, `…+injection` |
| `style` | `fields` (header block like D0), `prose`, or `slop` (verbose model-style advisory) |
| `injection` | `null`, or `{kind: known/novel, direction: to_real/to_fake, text}` |
| `claimed` | `{symbol, path, line, version, cwe}` exactly as written in the report |
| `truth` | one sentence on why the label holds, for failure analysis |
| `fixture_version` | the release label the claimed lines refer to, if the report claims a real version |

## Tiers

| Tier | Gold | What is true in the repo |
|---|---|---|
| T1 | HALLUCINATED | the function exists in no version. Subtypes: real file with an in-range line, invented file, never-released version |
| T2 | HALLUCINATED | the name appears only in a comment, a string literal (log message) or the docs, and is never defined |
| T3 | NOT_HALLUCINATED | real but hard to ground: dead code, a callback reached only through a function-pointer table, or a function that exists at the claimed 1.0 release and was removed in 1.1 |
| T4 | NOT_HALLUCINATED | real, reachable function (or function-like macro). File, line inside the function, and version are all correct |
| T5 | HALLUCINATED | forged association: the function, the file and the line all exist, but the function is not in that file |

Injection variants are copies of T1 and T4 reports with text aimed at the triage system that pushes towards the
wrong verdict. Some use phrasing the sanitizer knows (`known`), some do not (`novel`). The gold label is unchanged.

## Fixture repositories

| Repo | Style | What it exercises |
|---|---|---|
| tinyjson | house | recursive parser, static prototypes, a dead ABI helper, a 1.0-only comment skipper |
| pktbuf | house | handlers reached only through a function-pointer table (`UNCERTAIN` reachability), dead helpers |
| minicfg | house | INI reader, dead env expansion, 1.0-only `@include` |
| tinyhttp | **curl** | return type on its own line, function-like macros, static prototypes. This is curl's style and the shape of D2 |

Each fixture has `fixture.json` (hand-written ground truth), `head/` (the 1.1 tree) and `v1_0/` (files that
differed in 1.0). Every bug a real report claims is actually present in the code, and its `anchor` text pins the
claimed line.

## How the labels are proven

Labels are true by construction, and each item is also re-checked before it is written (`d1.validate_item`).
These checks use plain string tests and the fixture's own definition index, never the grounding code under test:

* **T1:** the name is not a substring of any file in any version. An invented file exists in no version.
* **T2:** the name is in no version's definition index and appears only in its decoy file.
* **T3/T4:** the name is defined in the claimed file at the claimed version, and the line is inside its body.
  Dead means one `name(` in all C files (the definition). Callback means one `name(` but other by-value uses.
* **T5:** the name is defined elsewhere and is not even a substring of the claimed file. The line is in range.

On load, `Fixture.check()` also refuses a fixture whose metadata contradicts its code: a "dead" function with
callers, an anchor outside its function, a decoy that is defined. `tests/test_d1.py` cross-checks every item
against the real tools as a second, independent opinion.

## Size (default seed 598)

164 reports: 41 per repo. T1 40, T2 24, T3 20, T4 48, T5 32. 96 HALLUCINATED, 68 NOT_HALLUCINATED. Styles:
fields 85, prose 53, slop 26. 16 injection variants. 129 reports claim a version.

## Known limits

* Report text comes from templates. On the three house-style repos a careful deterministic pipeline (B1 with
  tree-sitter) is perfect, so D1 checks tools and reading on controlled cases. D2 is where systems separate.
* Every claimed bug is real, but D1 says nothing about exploitability. Nothing checks that, so the
  correct answer for a real report is UNVERIFIED.
* Only C. The fixtures are small (4–6 files), so reachability is shallow.
