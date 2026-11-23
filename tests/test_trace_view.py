"""trace_view: selection, wrong/costly flags and the text layout. Offline."""
import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from slopgate.evaluation import trace_view as tv                         # noqa: E402


def row(i, verdict, expected, **kw):
    base = {"id": i, "system": "b3_rules", "tier": "T3", "status": "ok", "verdict": verdict, "expected_verdict": expected,
            "confidence": 0.88, "tool_calls": 2, "model_calls": 0, "tokens": 0, "latency_s": 0.0123,
            "trace": [{"step": "extract", "source": "prose-rules", "claims": 3, "discarded": 1}],
            "ledger": [{"id": "E1", "tool": "find_symbol", "args": {"name": "foo"}, "status": "MENTIONED",
                        "result": {"status": "MENTIONED", "record": {"big": "x" * 500}, "location": "lib/a.c:3"}}],
            "rationale": [{"text": "foo appears only in a comment", "cites": ["E1"]}], "error": None}
    base.update(kw)
    return base


ROWS = [row("a", "HALLUCINATED", "HALLUCINATED"),
        row("b", "HALLUCINATED", "UNVERIFIED"),                 # costly
        row("c", "UNVERIFIED", "HALLUCINATED", tier="T5"),      # wrong, cheap
        row("d", None, "UNVERIFIED", status="error", error="boom")]


def write(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    f.write("\n".join(json.dumps(r) for r in rows) + "\n")
    f.close()
    return f.name


class Select(unittest.TestCase):
    def test_flags(self):
        self.assertFalse(tv.is_wrong(ROWS[0]))
        self.assertTrue(tv.is_wrong(ROWS[1]) and tv.is_costly(ROWS[1]))
        self.assertTrue(tv.is_wrong(ROWS[2]) and not tv.is_costly(ROWS[2]))
        self.assertFalse(tv.is_wrong(ROWS[3]))                   # an errored row is not "wrong", it has no verdict

    def test_filters_combine(self):
        ids = lambda rs: [r["id"] for r in rs]                   # noqa: E731
        self.assertEqual(ids(tv.select(ROWS, wrong=True)), ["b", "c"])
        self.assertEqual(ids(tv.select(ROWS, costly=True)), ["b"])
        self.assertEqual(ids(tv.select(ROWS, ids={"a", "c"})), ["a", "c"])
        self.assertEqual(ids(tv.select(ROWS, tier="T5")), ["c"])
        self.assertEqual(ids(tv.select(ROWS, verdict="HALLUCINATED", wrong=True)), ["b"])
        self.assertEqual(ids(tv.select(ROWS, limit=2)), ["a", "b"])
        self.assertEqual(len(tv.select(ROWS, limit=0)), 4)

    def test_load_rows_reports_the_bad_line(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        f.write(json.dumps(ROWS[0]) + "\n{broken\n")
        f.close()
        with self.assertRaises(ValueError) as cm:
            tv.load_rows(f.name)
        self.assertIn("line 2", str(cm.exception))


class Render(unittest.TestCase):
    def test_layout_contains_every_part(self):
        out = tv.render_row(ROWS[1], report="# Title\nbody line")
        for needle in ("b  |  b3_rules  |  tier T3", "verdict HALLUCINATED (conf 0.88)", "expected UNVERIFIED",
                       "should not be dismissed was dismissed", "REPORT", "body line", "TRACE",
                       "extract   source=prose-rules claims=3 discarded=1", "EVIDENCE LEDGER",
                       "E1   find_symbol(name=foo)  ->  MENTIONED", "location=lib/a.c:3", "WHY",
                       "foo appears only in a comment ['E1']"):
            self.assertIn(needle, out)

    def test_bulky_result_fields_are_not_dumped(self):
        self.assertNotIn("x" * 50, tv.render_row(ROWS[0]))

    def test_error_and_status_shown(self):
        out = tv.render_row(ROWS[3])
        self.assertIn("[ERROR]", out)
        self.assertIn("error: boom", out)

    def test_long_report_is_cut_with_a_count(self):
        out = tv.render_row(ROWS[0], report="\n".join("l%d" % i for i in range(30)), report_lines=5)
        self.assertIn("... (25 more lines)", out)
        self.assertNotIn("l29", out)

    def test_agent_plan_steps(self):
        trace = [{"step": "plan", "n": 1, "decision": "tool", "thought": "check the tag first", "tool": "resolve_tag",
                  "args": {"version": "v1"}, "events": [{"event": "x"}]},
                 {"step": "claim_na", "claim_id": "C2", "why": "line without a file"},
                 {"step": "final", "stop_reason": "load_bearing_contradicted", "claim_states": {"C1": "refuted"}},
                 {"step": "custom", "a": 1}]
        text = "\n".join(tv.trace_lines(trace))
        for needle in ("plan #1  tool  resolve_tag(version=v1)", "why: check the tag first", "event:", "n/a       claim C2",
                       "final     stop=load_bearing_contradicted", "claim_states:", "custom"):
            self.assertIn(needle, text)

    def test_markdown_headings(self):
        out = tv.render_row(ROWS[0], report="r", md=True)
        self.assertTrue(out.startswith("## a  |"))
        self.assertIn("### Report", out)
        self.assertIn("### Evidence Ledger", out)


class Cli(unittest.TestCase):
    def run_cli(self, args):
        with mock.patch("sys.stdout", new=StringIO()) as out:
            code = tv.main(args)
        return code, out.getvalue()

    def test_list_and_costly(self):
        code, out = self.run_cli(["--predictions", write(ROWS), "--list", "--wrong"])
        self.assertEqual(code, 0)
        self.assertIn("COSTLY", out)
        self.assertIn("wrong", out)

    def test_no_match_returns_1(self):
        with mock.patch("sys.stderr", new=StringIO()):
            self.assertEqual(tv.main(["--predictions", write(ROWS), "--id", "zzz"]), 1)

    def test_data_adds_report(self):
        d = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        d.write(json.dumps({"id": "a", "report": "THE REPORT TEXT"}) + "\n")
        d.close()
        _, out = self.run_cli(["--predictions", write(ROWS), "--id", "a", "--data", d.name])
        self.assertIn("THE REPORT TEXT", out)


if __name__ == "__main__":
    unittest.main()
