"""D2 pilot: public curl reports, pinned to the commit current when they were submitted.

The labelled spec is committed (corpus/d2/d2_pilot.json). This script needs a local curl clone
and builds one git worktree per pin, the report files and corpus/d2/d2.jsonl:

    git clone https://github.com/curl/curl.git corpus/d2/curl
    python -m slopgate.datasets.d2 --curl corpus/d2/curl

A pin is a commit, a tag, or a date (YYYY-MM-DD: the last master commit before that day)."""
import argparse
import json
import os
import re
import subprocess


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True).stdout.strip()


def resolve_pin(curl, pin):
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", pin):
        return git(curl, "rev-list", "-1", "--before=" + pin, "HEAD")
    return git(curl, "rev-parse", pin + "^{commit}")


def build(spec_path, curl, out):
    spec = json.load(open(spec_path, encoding="utf-8"))
    wt_root = os.path.join(out, "worktrees")
    os.makedirs(os.path.join(out, "reports"), exist_ok=True)
    rows = []
    for it in spec["items"]:
        sha = resolve_pin(curl, it["pin"])
        wt = os.path.join(wt_root, sha[:12])
        if not os.path.isdir(wt):
            git(curl, "worktree", "add", "--detach", os.path.abspath(wt), sha)
        rp = os.path.join(out, "reports", it["id"] + ".md")
        with open(rp, "w", encoding="utf-8") as f:
            f.write(it["report"])
        rows.append({"id": it["id"], "report": it["report"], "repo": wt, "ref": "HEAD", "gold": it["gold"],
                     "tier": "D2-" + it["kind"], "report_path": rp, "subtype": it["kind"], "pin": it["pin"],
                     "pin_commit": sha, "source": it["src"], "truth": it["truth"], "claims_label": it["claims"],
                     "injection": None,
                     "expected_verdict": "HALLUCINATED" if it["gold"] == "HALLUCINATED" else "UNVERIFIED"})
    with open(os.path.join(out, "d2.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--spec", default=os.path.join("corpus", "d2", "d2_pilot.json"))
    ap.add_argument("--curl", default=os.path.join("corpus", "d2", "curl"))
    ap.add_argument("--out", default=os.path.join("corpus", "d2"))
    a = ap.parse_args(argv)
    rows = build(a.spec, a.curl, a.out)
    print("wrote %d D2 pilot reports (%d HALLUCINATED) to %s/d2.jsonl"
          % (len(rows), sum(r["gold"] == "HALLUCINATED" for r in rows), a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
