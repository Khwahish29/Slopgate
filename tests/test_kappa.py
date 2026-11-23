"""Inter-annotator agreement tool (slopgate.datasets.kappa)."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from slopgate.datasets import kappa  # noqa: E402

H, N = "HALLUCINATED", "NOT_HALLUCINATED"


def write(d, name, labels, annotator=None):
    p = os.path.join(d, name)
    body = {"labels": [{"id": i, "gold": g} for i, g in labels.items()]}
    if annotator:
        body["annotator"] = annotator
    with open(p, "w", encoding="utf-8") as f:
        json.dump(body, f)
    return p


class Cohen(unittest.TestCase):
    def test_textbook_example(self):
        # 50 items: yes/yes 20, yes/no 5, no/yes 10, no/no 15 -> po 0.7, pe 0.5, kappa 0.4
        a = ["y"] * 25 + ["n"] * 25
        b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
        self.assertAlmostEqual(kappa.cohen_kappa(a, b), 0.4)

    def test_perfect_and_chance(self):
        self.assertEqual(kappa.cohen_kappa(["a", "b", "a"], ["a", "b", "a"]), 1.0)
        self.assertAlmostEqual(kappa.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]), 0.0)

    def test_single_label_is_undefined(self):
        self.assertIsNone(kappa.cohen_kappa([N] * 5, [N] * 5))
        self.assertIsNone(kappa.cohen_kappa([], []))

    def test_skewed_labels_one_flip(self):
        # D2 shape: 16 vs 2. One flipped HALLUCINATED drops kappa well below raw agreement.
        a = [N] * 16 + [H] * 2
        b = [N] * 17 + [H]
        self.assertAlmostEqual(sum(x == y for x, y in zip(a, b)) / 18, 17 / 18)
        self.assertLess(kappa.cohen_kappa(a, b), 0.7)

    def test_length_mismatch(self):
        with self.assertRaises(ValueError):
            kappa.cohen_kappa(["a"], ["a", "b"])


class Fleiss(unittest.TestCase):
    def test_wikipedia_example(self):
        # 10 items, 14 raters, 5 categories; published kappa 0.210
        table = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
                 [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
        rows = [[c for c, k in enumerate(r) for _ in range(k)] for r in table]
        self.assertAlmostEqual(kappa.fleiss_kappa(rows), 0.210, places=3)

    def test_unequal_raters(self):
        with self.assertRaises(ValueError):
            kappa.fleiss_kappa([["a", "b"], ["a"]])


class Agreement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kappa_")

    def test_two_files_with_missing_ids_and_disagreement(self):
        a = kappa.load_labels(write(self.tmp, "a.json", {"r1": H, "r2": N, "r3": N, "r4": N}, "A"))
        b = kappa.load_labels(write(self.tmp, "b.json", {"r1": H, "r2": H, "r3": N, "r5": N}, "B"))
        s = kappa.agreement([a, b])
        self.assertEqual(s["n_items"], 3)
        self.assertEqual(s["missing"], {"A": ["r5"], "B": ["r4"]})
        self.assertEqual(s["disagreements"], [{"id": "r2", "labels": {"A": N, "B": H}}])
        p = s["pairs"][0]
        self.assertAlmostEqual(p["agreement"], 2 / 3)
        self.assertEqual(p["confusion"][N][H], 1)
        self.assertEqual(p["confusion"][H][H], 1)
        self.assertIsNone(s["fleiss_kappa"])

    def test_three_files_get_fleiss(self):
        labs = {"r1": H, "r2": N, "r3": N}
        files = [kappa.load_labels(write(self.tmp, "%s.json" % n, labs, n)) for n in ("x", "y", "z")]
        s = kappa.agreement(files)
        self.assertEqual(len(s["pairs"]), 3)
        self.assertEqual(s["fleiss_kappa"], 1.0)

    def test_errors(self):
        with self.assertRaises(kappa.LabelError):
            kappa.agreement([("a", {"r1": H})])
        with self.assertRaises(kappa.LabelError):
            kappa.agreement([("a", {"r1": H}), ("a", {"r1": H})])
        p = os.path.join(self.tmp, "dup.json")
        with open(p, "w") as f:
            json.dump({"labels": [{"id": "r1", "gold": H}, {"id": "r1", "gold": N}]}, f)
        with self.assertRaises(kappa.LabelError):
            kappa.load_labels(p)

    def test_labels_are_normalised_and_name_defaults_to_file(self):
        name, labs = kappa.load_labels(write(self.tmp, "annot_b.json", {"r1": " hallucinated "}))
        self.assertEqual((name, labs), ("annot_b", {"r1": H}))
        _, labs = kappa.load_labels(write(self.tmp, "c.json", {"r1": "not hallucinated", "r2": "Not-Hallucinated"}))
        self.assertEqual(labs, {"r1": N, "r2": N})

    def test_non_object_row_is_a_label_error(self):
        p = os.path.join(self.tmp, "bad.json")
        with open(p, "w") as f:
            json.dump({"labels": ["r1"]}, f)
        with self.assertRaises(kappa.LabelError):
            kappa.load_labels(p)

    def test_cli(self):
        a = write(self.tmp, "a.json", {"r1": H, "r2": N}, "A")
        b = write(self.tmp, "b.json", {"r1": H, "r2": H}, "B")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(kappa.main([a, b]), 0)
        self.assertIn("A vs B", buf.getvalue())
        self.assertIn("r2", buf.getvalue())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            kappa.main([a, b, "--json"])
        self.assertEqual(json.loads(buf.getvalue())["n_items"], 2)


class D2Labels(unittest.TestCase):
    def test_pilot_labels_match_the_spec(self):
        """corpus/d2/labels_pilot.json is the export of d2_pilot.json's gold labels."""
        spec = json.load(open(os.path.join(ROOT, "corpus", "d2", "d2_pilot.json"), encoding="utf-8"))
        name, labs = kappa.load_labels(os.path.join(ROOT, "corpus", "d2", "labels_pilot.json"))
        self.assertEqual(name, "pilot")
        self.assertEqual(labs, {i["id"]: i["gold"] for i in spec["items"]})


if __name__ == "__main__":
    unittest.main()
