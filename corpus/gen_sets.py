#!/usr/bin/env python3
"""Generate D1 (synthetic prose), D3 (suppression) and D4 (injection) deterministically.

    python3 corpus/gen_sets.py            # rewrites corpus/d1, corpus/d3, corpus/d4

Gold labels are known by construction (see STRATEGIES) and come from the fixture
repositories' real history, never from running any triage system. Reports are free
prose in four styles; none uses the `**Affected function:**` header the Milestone 1
extractor needs. Some styles deliberately defeat the offline prose extractor
(basename-only paths, no backticks): those are the contribution targets in
docs/ROADMAP.md and are flagged `hard` in the labels.

Limits worth stating in any report that uses this data: the reports are written by us,
for repositories we also wrote, so they test the pipeline, not the world. D2 (public
curl reports) is the held-out set that tests the world.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(HERE, "fixtures"))

import build_fixtures                                          # noqa: E402
from slopgate.agent_layer import ground                                    # noqa: E402

H, N = "HALLUCINATED", "NOT_HALLUCINATED"
C_REPO = "corpus/fixtures/out/minihttp-git"
P_REPO = "corpus/fixtures/out/pytoy-git"

MECH = {
    "CWE-787": ["writes past the end of its destination buffer",
                "copies the declared length without comparing it to the bytes actually present"],
    "CWE-125": ["reads beyond the end of its input when the string ends mid-sequence",
                "advances the read pointer without checking that enough bytes remain"],
    "CWE-190": ["multiplies two attacker-controlled sizes without an overflow check"],
    "CWE-476": ["dereferences the lookup result without a null check"],
}
CWES = list(MECH)

# (strategy, gold, repo, symbol, claimed path or None, version or None, note)
FACTS = [
    # fabricated: the name exists nowhere
    *[("fabricated", H, C_REPO, s, p, None, "invented symbol")
      for s, p in [("http_parse_trailer_ext", "lib/http_chunks.c"), ("url_decode_strict", "lib/url.c"),
                   ("chunk_verify_crc", "lib/http_chunks.c"), ("conn_pool_release", "src/main.c"),
                   ("ssl_session_resume", "lib/url.c"), ("http_header_unfold", "lib/http_chunks.c"),
                   ("url_canonicalize_path", "lib/url.c"), ("chunk_alloc_budget", "lib/http_chunks.c")]],
    *[("fabricated", H, P_REPO, s, p, None, "invented symbol")
      for s, p in [("parse_cookie", "pytoy/parser.py"), ("decode_gzip", "pytoy/parser.py"),
                   ("stream_resync", "pytoy/util.py")]],
    # comment_only: appears only in prose and comments
    ("comment_only", H, C_REPO, "curl_easy_parse_header", "lib/http_chunks.c", None, "removed long ago; only prose mentions it"),
    ("comment_only", H, C_REPO, "curl_easy_parse_header", "lib/url.c", None, "as above, other file"),
    # wrong_file: real symbol, wrong home
    ("wrong_file", H, C_REPO, "chunk_decode", "lib/url.c", None, "defined in lib/http_chunks.c"),
    ("wrong_file", H, C_REPO, "url_parse_host", "lib/http_chunks.c", None, "defined in lib/url.c"),
    ("wrong_file", H, C_REPO, "chunk_read_size", "src/main.c", None, "defined in lib/http_chunks.c"),
    ("wrong_file", H, C_REPO, "hexval", "lib/url.c", None, "defined in lib/http_chunks.c"),
    ("wrong_file", H, P_REPO, "read_exact", "pytoy/parser.py", None, "defined in pytoy/util.py"),
    # missing_file: real symbol, file does not exist
    ("missing_file", H, C_REPO, "chunk_decode", "lib/http_parser.c", None, "no such file"),
    ("missing_file", H, C_REPO, "url_parse_host", "lib/uri.c", None, "no such file"),
    ("missing_file", H, P_REPO, "parse_header", "pytoy/headers.py", None, "no such file"),
    # future_symbol: true at HEAD, false at the claimed (older) tag
    ("future_symbol", H, C_REPO, "chunk_trailer_parse", "lib/http_chunks.c", "minihttp-1_0", "added in 1.1, claimed at 1.0"),
    ("future_symbol", H, P_REPO, "parse_trailer", "pytoy/parser.py", "v1.0", "added after v1.0"),
    # real, at HEAD
    *[("real", N, C_REPO, s, p, None, "defined and reachable")
      for s, p in [("chunk_decode", "lib/http_chunks.c"), ("chunk_read_size", "lib/http_chunks.c"),
                   ("url_parse_host", "lib/url.c"), ("hexval", "lib/http_chunks.c")]],
    *[("real", N, P_REPO, s, p, None, "defined and reachable")
      for s, p in [("parse_header", "pytoy/parser.py"), ("decode_chunk", "pytoy/parser.py"),
                   ("read_exact", "pytoy/util.py")]],
    ("dead_code", N, C_REPO, "url_legacy_unescape", "lib/url.c", None, "defined, never called"),
    ("dead_code", N, P_REPO, "legacy_split", "pytoy/parser.py", None, "defined, never called"),
    # version drift and history: absent at HEAD, real at the claimed tag
    ("version_drift", N, C_REPO, "legacy_parse_header", "lib/compat.c", "minihttp-0_9", "removed in 1.0, true at 0.9"),
    ("version_drift", N, C_REPO, "url_escape_old", "lib/compat.c", "minihttp-0_9", "renamed in 1.0, true at 0.9"),
    # removed, no version stated: "removed" is not "never existed"
    ("removed_unpinned", N, C_REPO, "legacy_parse_header", "lib/compat.c", None, "existed once; report unpinned"),
    ("removed_unpinned", N, C_REPO, "url_escape_old", "lib/compat.c", None, "existed once; report unpinned"),
]

TITLES = ["Memory corruption in {sym}", "Heap overflow in {sym}()", "{cwe}: unchecked length in {sym}",
          "Security issue in the {base} component", "Possible vulnerability in {sym}"]


def head_facts(repo):
    """symbol -> (defining file, def line) and file -> length, from the real tree at HEAD."""
    full = os.path.join(ROOT, repo)
    lens = {}
    for p in ground.walk_sources(full):
        lens[os.path.relpath(p, full)] = len(open(p, errors="replace").read().splitlines())
    return full, lens


def line_for(i, path, lens, defs):
    n = lens.get(path)
    if n is None:                       # file exists only at an older tag (lib/compat.c, 31 lines)
        return 8 + i % 5
    if defs:
        return min(defs + 2 + i % 3, n)
    return 1 + (i * 11) % max(n, 1)


def render(style, d):
    sym, path, line, ver, cwe, mech, title = (d["sym"], d["path"], d["line"], d["ver"],
                                              d["cwe"], d["mech"], d["title"])
    ver_s = (" I reproduced this on %s." % ver) if ver else ""
    cwe_s = " This looks like %s." % cwe if cwe else ""
    if style == 0:
        return ("# %s\n\nWhile reviewing the parser I noticed that `%s()` in %s %s. The problem is "
                "near line %d.%s%s\n\nAn attacker who controls the input can trigger it remotely.\n"
                % (title, sym, path, mech, line, ver_s, cwe_s))
    if style == 1:
        return ("## Report\n\n- Component: `%s` (%s:%d)\n- Impact: memory safety\n- Cause: the function %s\n"
                "- Environment:%s\n- Weakness: %s\n" % (sym, path, line, mech,
                                                         (" " + ver) if ver else " current main", cwe or "unclassified"))
    if style == 2:
        return ("Hi security team,\n\nI think there is a problem with the function %s in %s. It %s, "
                "at around line %d.%s\n\nCould you confirm whether this is already known?\n\nThanks,\nA researcher\n"
                % (sym, path, mech, line, ver_s))
    base = os.path.basename(path)                      # style 3: basename only, no backticks (hard)
    return ("heap bug in %s() - see %s line %d. it %s.%s attached poc crashes it.\n"
            % (sym, base, line, mech, ver_s.lower()))


def make_d1():
    items, out_dir = [], os.path.join(HERE, "d1", "reports")
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, f))
    cache = {r: head_facts(r) for r in (C_REPO, P_REPO)}
    k = 0
    for fi, (strategy, gold, repo, sym, path, ver, note) in enumerate(FACTS):
        full, lens = cache[repo]
        defs = ground.find_symbol(full, sym)["definitions"]
        home = defs[0]["line"] if defs and defs[0]["file"] == path else None
        styles = [0, 1, 2] + ([3] if strategy in ("real", "wrong_file") and k % 2 == 0 else [])
        for si in styles:
            k += 1
            cwe = CWES[(fi + si) % len(CWES)]
            mech = MECH[cwe][(fi + si) % len(MECH[cwe])]
            d = {"sym": sym, "path": path, "ver": ver, "cwe": cwe if si != 2 else None, "mech": mech,
                 "line": line_for(fi + si, path, lens, home),
                 "title": TITLES[(fi + si) % len(TITLES)].format(
                     sym=sym, cwe=cwe, base=os.path.basename(path))}
            name = "d1_%03d_%s.md" % (k, strategy)
            open(os.path.join(out_dir, name), "w").write(render(si, d))
            items.append({"file": name, "strategy": strategy, "label": gold, "repo": repo,
                          "primary_symbol": sym, "claimed_path": path, "version": ver,
                          "style": si, "hard": si == 3, "note": note, "synthetic": True})
    vague = ["The chunk parser seems to mishandle oversized lengths and I can crash it with a long header. "
             "Please look into the HTTP parsing code.",
             "I believe the URL handling is unsafe when the host is very long. No exact location, sorry; "
             "found while fuzzing.",
             "Reading the code it feels like the trailing bytes of a body are not validated. Happy to share "
             "more details if useful.",
             "There may be an integer problem somewhere in how sizes are computed before a copy.",
             "Your header decoder looks wrong to me; could someone take a look at it?"]
    for i, text in enumerate(vague):
        k += 1
        name = "d1_%03d_prose_vague.md" % k
        open(os.path.join(out_dir, name), "w").write("# Possible memory issue\n\n" + text + "\n")
        items.append({"file": name, "strategy": "prose_vague", "label": N, "repo": C_REPO if i % 2 == 0 else C_REPO,
                      "primary_symbol": None, "claimed_path": None, "version": None, "style": 0, "hard": False,
                      "note": "no checkable claim; should abstain", "synthetic": True})
    save("d1", items, "Synthetic prose reports, gold by construction. Development and threshold tuning.")
    return items


def save(name, items, desc):
    d = os.path.join(HERE, name)
    os.makedirs(d, exist_ok=True)
    json.dump({"set": name, "description": desc, "items": items}, open(os.path.join(d, "labels.json"), "w"), indent=1)








if __name__ == "__main__":
    build_fixtures.build(force=False)
    d1 = make_d1()
    from collections import Counter
    for n, it in (("d1", d1),):
        print(n, len(it), dict(Counter(x["label"] for x in it)))
