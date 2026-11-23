"""figures: input discovery, axis maths, valid and deterministic SVG. Offline."""
import json
import os
import sys
import tempfile
import unittest
import xml.dom.minidom
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from slopgate.evaluation import figures as fg                            # noqa: E402


def results(spec):
    """spec: {dataset: {system: {field: value}}} -> a results directory like aggregate writes."""
    root = Path(tempfile.mkdtemp())
    for ds, systems in spec.items():
        d = root / ds / "comparison"
        d.mkdir(parents=True)
        (d / "comparison.json").write_text(json.dumps([dict(system=s, **row) for s, row in systems.items()]))
    return root


ROW = lambda fd, cost, acc, calls: {"false_hallucinated": fd, "mean_classification_cost": cost,   # noqa: E731
                                    "accuracy": acc, "mean_tool_calls": calls}
SPEC = {"d1": {"b1": ROW(17, 51.8, 0.9, 6.0), "b3_rules": ROW(0, 0.1, 0.99, 8.1)},
        "d3": {"b1": ROW(4, 62.5, 0.88, 5.3), "b3_rules": ROW(3, 46.9, 0.91, 8.0)}}


class Axis(unittest.TestCase):
    def test_round_steps_that_cover_the_value(self):
        for v in (0.4, 1, 3, 21, 99, 166.7, 1234):
            ymax, step = fg.axis(v)
            self.assertGreaterEqual(ymax, v)
            self.assertLessEqual(ymax / step, 6)
            self.assertAlmostEqual(ymax / step, round(ymax / step))
        self.assertEqual(fg.axis(21), (25.0, 5.0))

    def test_zero_gives_a_usable_axis(self):
        ymax, step = fg.axis(0)
        self.assertGreater(ymax, 0)


class Load(unittest.TestCase):
    def test_discovers_datasets_and_systems(self):
        comps = fg.load_comparisons(results(SPEC))
        self.assertEqual(sorted(comps), ["d1", "d3"])
        self.assertEqual(comps["d1"]["b3_rules"]["false_hallucinated"], 0)

    def test_missing_aggregate_is_a_clear_error(self):
        with self.assertRaises(ValueError) as cm:
            fg.load_comparisons(tempfile.mkdtemp())
        self.assertIn("make aggregate", str(cm.exception))


class Draw(unittest.TestCase):
    def test_writes_four_valid_svgs_and_an_index(self):
        out = Path(tempfile.mkdtemp())
        files = fg.make_figures(results(SPEC), out)
        self.assertEqual(sorted(p.name for p in files),
                         ["accuracy.svg", "false_dismissals.svg", "index.html", "mean_cost.svg", "tool_calls.svg"])
        for p in files:
            if p.suffix == ".svg":
                xml.dom.minidom.parse(str(p))                   # raises if not well-formed
        svg = (out / "false_dismissals.svg").read_text()
        for needle in ("D1", "D3", "b1", "b3_rules", ">17<", ">0<", "Real reports wrongly dismissed"):
            self.assertIn(needle, svg)

    def test_output_is_deterministic(self):
        r = results(SPEC)
        a, b = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        fg.make_figures(r, a)
        fg.make_figures(r, b)
        for name in ("false_dismissals.svg", "mean_cost.svg", "index.html"):
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes())

    def test_missing_system_in_one_dataset_shows_n_a(self):
        spec = {"d1": {"b1": ROW(1, 1, 1, 1), "b2": ROW(0, 0, 1, 0)}, "d3": {"b1": ROW(2, 2, 1, 1)}}
        out = Path(tempfile.mkdtemp())
        fg.make_figures(results(spec), out)
        self.assertIn("n/a", (out / "accuracy.svg").read_text())

    def test_all_zero_values_do_not_crash(self):
        out = Path(tempfile.mkdtemp())
        fg.make_figures(results({"d1": {"b1": ROW(0, 0, 0, 0)}}), out)
        xml.dom.minidom.parse(str(out / "false_dismissals.svg"))

    def test_names_are_escaped(self):
        spec = {"d1": {"a<b&c": ROW(1, 1, 1, 1)}}
        out = Path(tempfile.mkdtemp())
        fg.make_figures(results(spec), out)
        xml.dom.minidom.parse(str(out / "accuracy.svg"))

    def test_same_system_same_colour(self):
        order = ["b1", "b3_rules", "zzz"]
        self.assertEqual(fg.colour_for("b1", order), fg.colour_for("b1", ["b0", "b1"]))
        self.assertIn(fg.colour_for("zzz", order), fg.EXTRA)


if __name__ == "__main__":
    unittest.main()
