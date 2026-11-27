import json
import unittest
from unittest import mock

from tests.helpers import Keyboard, build, tmpdir  # noqa: F401  (sets sys.path)

from csv_summary import engine, importer, storage
from csv_summary import validation as v


class EngineTests(unittest.TestCase):
    def test_classify_value(self):
        cases = {"12": "integer", "-3": "integer", "1,200": "integer", "3.14": "float", "1e3": "float",
                 "yes": "boolean", "FALSE": "boolean", "2025-03-01": "date", "31/12/2024": "date",
                 "hello": "text", "": "missing", "NA": "missing", " null ": "missing", "-": "missing",
                 "nan": "missing", "inf": "text"}
        for raw, expected in cases.items():
            self.assertEqual(engine.classify_value(raw), expected, raw)

    def test_infer_dtype(self):
        self.assertEqual(engine.infer_dtype({"integer": 3}), "integer")
        self.assertEqual(engine.infer_dtype({"integer": 3, "float": 1}), "float")
        self.assertEqual(engine.infer_dtype({"integer": 3, "text": 1}), "mixed")
        self.assertEqual(engine.infer_dtype({}), "empty")

    def test_numeric_summary_known_values(self):
        s = engine.numeric_summary([1, 2, 3, 4, 100])
        self.assertEqual((s["min"], s["max"], s["median"], s["mean"]), (1, 100, 3, 22))
        self.assertEqual((s["q1"], s["q3"]), (2, 4))
        self.assertEqual(s["outliers"], 1)
        self.assertAlmostEqual(s["stdev"], 43.6177, places=3)

    def test_numeric_summary_edge_cases(self):
        self.assertEqual(engine.numeric_summary([]), {})
        single = engine.numeric_summary([5])
        self.assertEqual((single["stdev"], single["outliers"]), (0.0, 0))
        self.assertEqual(engine.numeric_summary([2, 2, 2, 2])["outliers"], 0)   # zero IQR -> no outliers

    def test_profile_column_missing_counts(self):
        col = engine.profile_column("x", 0, ["1", "", "NA", "4", "null", "7"])
        self.assertEqual((col.total, col.missing, col.present, col.dtype), (6, 3, 3, "integer"))
        self.assertEqual(col.missing_pct, 50.0)
        self.assertEqual(col.mean, 4.0)

    def test_mixed_column_still_gets_numeric_stats(self):
        col = engine.profile_column("age", 0, ["20", "21", "twenty", "22"])
        self.assertEqual(col.dtype, "mixed")
        self.assertEqual(col.mean, 21.0)

    def test_date_and_text_columns(self):
        d = engine.profile_column("d", 0, ["2025-01-05", "2024-12-31", ""])
        self.assertEqual((d.dtype, d.min, d.max), ("date", "2024-12-31", "2025-01-05"))
        t = engine.profile_column("t", 0, ["a", "b", "a"])
        self.assertEqual(t.top_values[0], ["a", 2])
        self.assertFalse(t.is_numeric)

    def test_all_missing_column(self):
        col = engine.profile_column("e", 0, ["", "NA"])
        self.assertEqual((col.dtype, col.missing_pct), ("empty", 100.0))

    def test_profile_dataset_pads_short_rows(self):
        ds = engine.profile_dataset("t", ["a", "b"], [["1"], ["2", "3"]])
        self.assertEqual(ds.column("b").missing, 1)
        self.assertEqual(ds.completeness_pct, 75.0)

    def test_value_sampling_cap(self):
        col = engine.profile_column("n", 0, [str(i) for i in range(5000)])
        self.assertLessEqual(len(col.values), 2000)


class ValidationTests(unittest.TestCase):
    def test_int_validation(self):
        self.assertEqual(v.validate_int(" 5 ", 1, 10), 5)
        for bad in ["", "abc", "1.5", "0", "11"]:
            with self.assertRaises(v.ValidationError):
                v.validate_int(bad, 1, 10)

    def test_float_validation(self):
        self.assertEqual(v.validate_float("2.5", 0, 4), 2.5)
        for bad in ["", "x", "nan", "inf", "-1", "4.1"]:
            with self.assertRaises(v.ValidationError):
                v.validate_float(bad, 0, 4)

    def test_dataset_name(self):
        self.assertEqual(v.validate_dataset_name("  Sales 2025 "), "Sales 2025")
        for bad in ["", "   ", "a/b", "bad<name>", "x" * 61, "../etc"]:
            with self.assertRaises(v.ValidationError):
                v.validate_dataset_name(bad)

    def test_sanitize_strips_control_characters(self):
        self.assertEqual(v.sanitize("a\x00b\x1b[31m"), "ab[31m")

    def test_file_path_validation(self):
        d = tmpdir()
        good = d / "ok.csv"
        good.write_text("a,b\n1,2\n")
        empty = d / "empty.csv"
        empty.write_text("")
        other = d / "x.exe"
        other.write_text("hi")
        self.assertEqual(v.validate_file_path(f'"{good}"'), good)
        for bad in ["", str(d / "missing.csv"), str(d), str(empty), str(other)]:
            with self.assertRaises(v.ValidationError):
                v.validate_file_path(bad)

    def test_ask_loops_until_valid(self):
        kb = Keyboard(["abc", "", "50", "5"])
        with mock.patch.object(v, "_input", kb):
            self.assertEqual(v.ask_int("n", 1, 10), 5)
        self.assertEqual(len(kb.prompts), 4)

    def test_ask_default_and_yes_no_and_choice(self):
        with mock.patch.object(v, "_input", Keyboard(["", "maybe", "Y", "9", "Text"])):
            self.assertEqual(v.ask_string("name", v.validate_dataset_name, "dflt"), "dflt")
            self.assertTrue(v.ask_yes_no("ok"))
            self.assertEqual(v.ask_choice("pick", ["integer", "text"]), "text")

    def test_ask_menu_choice_case_insensitive_and_eof(self):
        with mock.patch.object(v, "_input", Keyboard(["Q", "x"])):
            self.assertEqual(v.ask_menu_choice("m", ["q", "1"]), "q")
            with self.assertRaises(v.UserAbort):
                v.ask_menu_choice("m", ["q"])     # "x" rejected, then input runs dry


class ImporterTests(unittest.TestCase):
    def test_ragged_rows_blank_rows_and_log(self):
        r = importer.parse_csv_text("a,b,c\n1,2,3\n4,5\n\n6,7,8,9\n10,11,12\n")
        self.assertEqual(len(r.rows), 3)
        self.assertEqual(r.rows[1], ["4", "5", ""])
        self.assertEqual(r.rejected, 1)
        levels = [(i.line, i.severity) for i in r.issues]
        self.assertIn((3, "WARNING"), levels)
        self.assertIn((4, "INFO"), levels)
        self.assertIn((5, "ERROR"), levels)

    def test_duplicate_and_empty_headers(self):
        r = importer.parse_csv_text("id,id,,Name\n1,2,3,4\n")
        self.assertEqual(r.headers, ["id", "id_2", "column_3", "Name"])

    def test_delimiter_detection(self):
        self.assertEqual(importer.parse_csv_text("a;b\n1;2\n3;4\n").delimiter, ";")
        self.assertEqual(importer.parse_csv_text("a\tb\n1\t2\n3\t4\n").delimiter, "\t")

    def test_encoding_fallback_and_bom(self):
        r = importer.import_bytes("name,city\nJosé,Málaga\n".encode("latin-1"), "x.csv")
        self.assertEqual(r.encoding, "latin-1")
        self.assertEqual(r.rows[0][0], "José")
        r2 = importer.import_bytes(b"\xef\xbb\xbfa,b\n1,2\n", "x.csv")
        self.assertEqual(r2.headers, ["a", "b"])

    def test_fatal_failures(self):
        for payload, name in [(b"", "e.csv"), (b"   \n\n", "e.csv"), (b"a,b\n", "e.csv"),
                              (b"\x00\x01\x02binary", "e.csv"), (b"{not json", "e.json"), (b"[]", "e.json"),
                              (b'"just a string"', "e.json")]:
            with self.assertRaises(importer.ImportFailure, msg=repr(payload)):
                importer.import_bytes(payload, name)

    def test_json_import(self):
        data = json.dumps([{"a": 1, "b": None, "c": True}, {"a": 2, "d": "x"}, "oops"])
        r = importer.import_bytes(data.encode(), "t.json")
        self.assertEqual(r.headers, ["a", "b", "c", "d"])
        self.assertEqual(r.rows[0], ["1", "", "true", ""])
        self.assertEqual(r.rejected, 1)

    def test_error_log_written(self):
        r = importer.parse_csv_text("a,b\n1,2\n3,4,5,6\n")
        out = tmpdir()
        path = importer.write_error_log(r, "My Data", out)
        text = path.read_text()
        self.assertIn("Row 3", text)
        self.assertIn("rejected", text)
        self.assertIsNone(importer.write_error_log(importer.parse_csv_text("a\n1\n"), "clean", out))

    def test_sample_files(self):
        from tests.helpers import ROOT
        csv_r = importer.import_file(ROOT / "data" / "sample_data.csv")
        json_r = importer.import_file(ROOT / "data" / "sample_data.json")
        self.assertEqual((len(csv_r.rows), csv_r.rejected), (40, 1))
        self.assertEqual(len(json_r.rows), 40)
        self.assertEqual(csv_r.headers, json_r.headers)
        self.assertEqual(len(importer.import_file(ROOT / "data" / "sample_orders.csv").rows), 30)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir()
        self.path = self.dir / "store.json"

    def make(self, name="demo"):
        return build(name, ["a", "b"], [["1", "x"], ["2", "y"], ["", "z"]])

    def test_missing_file_creates_clean_template(self):
        s = storage.Store(self.path).load()
        self.assertEqual(s.datasets, [])
        self.assertTrue(self.path.exists())
        self.assertTrue(s.notes)

    def test_roundtrip_survives_reload(self):
        s = storage.Store(self.path).load()
        s.upsert(self.make())
        again = storage.Store(self.path).load()
        self.assertEqual(again.names(), ["demo"])
        self.assertEqual(again.get("DEMO").column("a").missing, 1)
        self.assertEqual(again.notes, [])

    def test_csv_mirror_written(self):
        s = storage.Store(self.path).load()
        s.upsert(self.make())
        mirror = (self.dir / "column_profiles.csv").read_text().splitlines()
        self.assertEqual(mirror[0].split(",")[:3], ["dataset", "column", "position"])
        self.assertEqual(len(mirror), 3)

    def test_corrupted_json_is_backed_up_and_reset(self):
        self.path.write_text("{ this is not json")
        s = storage.Store(self.path).load()
        self.assertEqual(s.datasets, [])
        self.assertTrue(list(self.dir.glob("store.corrupt-*.bak")))
        self.assertIn("unreadable", s.notes[0])
        json.loads(self.path.read_text())      # a valid template was written

    def test_bad_schema_and_binary_garbage(self):
        for content in ['[1, 2]', '{"datasets": []}', '{"schema_version": 99, "datasets": []}',
                        '{"schema_version": 1, "datasets": "x"}']:
            self.path.write_text(content)
            s = storage.Store(self.path).load()
            self.assertEqual(s.datasets, [], content)
            self.assertTrue(s.notes, content)
        self.path.write_bytes(b"\xff\xfe\x00\x80")
        self.assertEqual(storage.Store(self.path).load().datasets, [])

    def test_invalid_dataset_entry_skipped_others_kept(self):
        s = storage.Store(self.path).load()
        s.upsert(self.make("good"))
        data = json.loads(self.path.read_text())
        data["datasets"].append({"name": "broken"})
        self.path.write_text(json.dumps(data))
        again = storage.Store(self.path).load()
        self.assertEqual(again.names(), ["good"])
        self.assertIn("Skipped invalid dataset", again.notes[0])

    def test_upsert_replaces_and_remove(self):
        s = storage.Store(self.path).load()
        self.assertFalse(s.upsert(self.make("A")))
        self.assertTrue(s.upsert(self.make("a")))
        self.assertEqual(len(s.datasets), 1)
        self.assertTrue(s.remove("A"))
        self.assertFalse(s.remove("A"))

    def test_no_temp_files_left_behind(self):
        s = storage.Store(self.path).load()
        s.upsert(self.make())
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
