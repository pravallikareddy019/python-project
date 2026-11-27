import unittest
from datetime import datetime

from tests.helpers import ROOT, build, sample, tmpdir  # noqa: F401

from csv_summary import alerts, exporter, plotting
from csv_summary.search import search_columns, search_datasets
from csv_summary.summary import build_summary, status_for


def sparse_dataset():
    rows = [[str(i), "" if i % 4 else "x", "" if i < 7 else "5"] for i in range(10)]
    return build("sparse", ["id", "quarter_missing", "mostly_missing"], rows)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.ds = [sample("sample_data.csv"), sample("sample_orders.csv")]

    def test_keyword_matches_column_dataset_and_values(self):
        self.assertEqual({h.column.name for h in search_columns(self.ds, "email")}, {"email"})
        self.assertTrue(all(h.dataset.name == "sample_orders" for h in search_columns(self.ds, "orders")))
        self.assertTrue(any(h.column.name == "status" for h in search_columns(self.ds, "delivered")))

    def test_category_and_threshold_filters(self):
        self.assertTrue(all(h.column.dtype == "date" for h in search_columns(self.ds, dtype="date")))
        high = search_columns(self.ds, min_missing_pct=50)
        self.assertTrue({"mentor_id", "discount_pct"} <= {h.column.name for h in high})
        self.assertTrue(all(h.column.missing_pct >= 50 for h in high))
        self.assertEqual(search_columns(self.ds, "zzz-no-match"), [])
        self.assertTrue(all(h.column.is_numeric for h in search_columns(self.ds, numeric_only=True)))

    def test_multi_word_and_dataset_filter(self):
        hits = search_columns(self.ds, "sample_data gpa")
        self.assertEqual([h.column.name for h in hits], ["gpa"])
        self.assertTrue(all(h.dataset.name == "sample_orders"
                            for h in search_columns(self.ds, dataset_name="sample_orders")))
        self.assertEqual(len(search_datasets(self.ds, "orders")), 1)


class AlertTests(unittest.TestCase):
    def test_missing_thresholds(self):
        found = {(a.column, a.code, a.severity) for a in alerts.dataset_alerts(sparse_dataset())}
        self.assertIn(("quarter_missing", "missing_critical", "CRITICAL"), found)   # 70% missing
        self.assertIn(("mostly_missing", "missing_critical", "CRITICAL"), found)
        self.assertFalse([f for f in found if f[0] == "id"])                         # complete column is clean

    def test_warning_vs_critical_boundaries(self):
        warn = build("w", ["c"], [["1"]] * 8 + [[""]] * 2)         # exactly 20% -> WARNING
        crit = build("c", ["c"], [["1"]] * 5 + [[""]] * 5)         # exactly 50% -> CRITICAL
        ok = build("o", ["c"], [["1"], ["2"]] * 5 + [[""]])        # ~9% -> none for missing
        self.assertEqual(alerts.dataset_alerts(warn)[0].severity, "WARNING")
        self.assertEqual(alerts.dataset_alerts(crit)[0].severity, "CRITICAL")
        self.assertFalse([a for a in alerts.dataset_alerts(ok) if a.code.startswith("missing")])

    def test_all_missing_mixed_outlier_constant_stale(self):
        ds = build("t", ["empty", "mix", "num", "const", "when"],
                   [["", "1", "10", "k", "2020-01-01"], ["", "a", "11", "k", "2020-02-01"],
                    ["", "2", "12", "k", "2020-03-01"], ["", "b", "10", "k", "2020-04-01"],
                    ["", "3", "11", "k", "2020-05-01"], ["", "c", "900", "k", "2020-06-01"]], skipped_rows=2)
        codes = {(a.column, a.code) for a in alerts.dataset_alerts(ds, today=datetime(2026, 1, 1))}
        for expected in [("empty", "all_missing"), ("mix", "mixed_types"), ("num", "outliers"),
                         ("const", "constant"), ("when", "stale_dates"), ("", "rejected_rows")]:
            self.assertIn(expected, codes)

    def test_collect_sorted_by_severity(self):
        collected = alerts.collect_alerts([sample("sample_data.csv"), sample("sample_orders.csv")])
        order = [alerts.SEVERITIES.index(a.severity) for a in collected]
        self.assertEqual(order, sorted(order))
        self.assertEqual(sum(alerts.count_by_severity(collected).values()), len(collected))

    def test_clean_dataset_has_no_alerts(self):
        self.assertEqual(alerts.dataset_alerts(build("ok", ["a"], [["1"], ["2"], ["3"], ["4"]])), [])


class SummaryTests(unittest.TestCase):
    def test_status_thresholds(self):
        self.assertEqual([status_for(x) for x in (100, 95, 94.9, 80, 79.9)],
                         ["Healthy", "Healthy", "Needs attention", "Needs attention", "Critical"])

    def test_totals_and_averages(self):
        a = build("a", ["x", "y"], [["1", ""], ["2", "q"]])            # 1 missing of 4
        b = build("b", ["z"], [["1"], ["2"], ["3"], ["4"]])
        s = build_summary([a, b])
        self.assertEqual((s["datasets"], s["rows"], s["columns"], s["cells"], s["missing_cells"]), (2, 6, 3, 8, 1))
        self.assertEqual(s["overall_missing_pct"], 12.5)
        self.assertAlmostEqual(s["avg_missing_pct"], 16.67, places=2)
        self.assertEqual(s["complete_columns"], 2)
        self.assertEqual(s["type_distribution"]["integer"], 2)

    def test_trend_text_and_empty(self):
        a = build("first", ["x"], [["1"], [""]])
        b = build("second", ["x"], [["1"], ["2"]])
        a.imported_at, b.imported_at = "2026-01-01T00:00:00", "2026-02-01T00:00:00"
        trends = build_summary([a, b])["trends"]
        self.assertTrue(any("improved" in t for t in trends))
        empty = build_summary([])
        self.assertEqual((empty["datasets"], empty["overall_status"], empty["trends"]), (0, "No data", []))


class ExportAndPlotTests(unittest.TestCase):
    def setUp(self):
        self.ds = [sample("sample_data.csv"), sample("sample_orders.csv")]
        self.out = tmpdir()

    def test_all_three_formats(self):
        md = exporter.export_markdown(self.ds, self.out)
        txt = exporter.export_audit_log(self.ds, self.out)
        csv_path = exporter.export_csv_report(self.ds, self.out)
        text = md.read_text()
        for needle in ["# CSV Column Summary Tool", "Executive summary", "### Key trends", "mentor_id", "CRITICAL"]:
            self.assertIn(needle, text)
        self.assertIn("AUDIT LOG", txt.read_text())
        self.assertIn("ALERTS", txt.read_text())
        lines = csv_path.read_text().splitlines()
        self.assertEqual(len(lines), 1 + 22)

    def test_export_all_includes_charts(self):
        files = exporter.export_all(self.ds, self.out)
        names = {p.suffix for p in files}
        self.assertEqual(names, {".md", ".txt", ".csv", ".png"})
        self.assertIn("![", files[0].read_text())

    def test_charts_are_valid_png(self):
        ds = self.ds[0]
        paths = [plotting.chart_missing(ds, self.out), plotting.chart_types(self.ds, self.out),
                 plotting.chart_completeness(self.ds, self.out), plotting.chart_histogram(ds, "gpa", self.out),
                 plotting.chart_trend(ds, "gpa", self.out)]
        for p in paths:
            self.assertEqual(p.read_bytes()[:8], b"\x89PNG\r\n\x1a\n", p.name)
            self.assertGreater(p.stat().st_size, 5000)

    def test_chart_errors_are_friendly(self):
        ds = self.ds[0]
        with self.assertRaises(plotting.ChartError):
            plotting.chart_histogram(ds, "email", self.out)         # text column
        with self.assertRaises(plotting.ChartError):
            plotting.chart_histogram(ds, "nope", self.out)
        with self.assertRaises(plotting.ChartError):
            plotting.chart_trend(build("tiny", ["n"], [["1"], ["2"]]), "n", self.out)
        with self.assertRaises(plotting.ChartError):
            plotting.chart_types([], self.out)


if __name__ == "__main__":
    unittest.main()
