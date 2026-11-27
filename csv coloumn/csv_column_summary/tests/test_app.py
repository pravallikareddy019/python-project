"""End-to-end journey (mirrors the brief's demo) and GUI smoke tests."""
import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT, SmartKeyboard, tmpdir  # noqa: F401

import app as terminal_app
from csv_summary import ansi, config, storage
from csv_summary import validation as v


def run_session(data_dir, export_dir, answers):
    """Run one terminal session with scripted answers; returns captured stdout."""
    ansi.set_enabled(False)
    kb = SmartKeyboard(answers)
    buf = io.StringIO()
    application = terminal_app.Application(Path(data_dir) / "store.json", export_dir)
    with mock.patch.object(v, "_input", kb), contextlib.redirect_stdout(buf):
        application.run()
    assert not kb.answers, f"unused answers left: {kb.answers}"
    return buf.getvalue()


class DemoJourneyTests(unittest.TestCase):
    def setUp(self):
        self.data = tmpdir()
        self.exports = tmpdir()

    def test_full_demo_flow_with_restart(self):
        # --- session 1: bad input is caught, data is entered, analytics + export run -------
        out1 = run_session(self.data, self.exports, [
            "2", "bad/name", "Demo Sales", "abc", "0", "3", "item", "qty", "item", "price",
            "pen,2", "pen,2,1.5", "book,x,12", "ink,NA,3.25", "",       # manual entry w/ validation errors
            "10",                                                         # load both sample datasets
            "5", "email", "any", "", "n",                                 # search
            "6", "7",                                                     # summary + warnings
            "8", "1", "2",                                                # chart: missing values for dataset 2
            "9", "1", "n",                                                # export everything
            "bogus", "0",
        ])
        for needle in ["not allowed", "not a whole number", "at least 1", "must be unique",
                       "Expected 3 values", "Saved 'Demo Sales'", "row(s) accepted, 1 rejected",
                       "Row 15", "1 match(es)", "Executive summary", "Key trends", "CRITICAL",
                       "Chart saved", "Choose one of", "Goodbye"]:
            self.assertIn(needle, out1, needle)
        for suffix in (".md", ".txt", ".csv", ".png"):
            self.assertTrue(list(self.exports.glob(f"*{suffix}")), suffix)
        self.assertTrue((self.exports / "import_log_sample_data.txt").exists())
        self.assertTrue((self.exports / "sample_data_missing.png").exists())

        # --- session 2: "close and relaunch" - state must be preserved -------------------------
        out2 = run_session(self.data, self.exports, ["3", "1", "4", "2", "email", "0"])
        self.assertIn("Loaded 3 dataset(s)", out2)
        self.assertIn("Demo Sales", out2)
        self.assertIn("Most common values", out2)
        store = storage.Store(Path(self.data) / "store.json").load()
        self.assertEqual(sorted(store.names()), ["Demo Sales", "sample_data", "sample_orders"])
        demo = store.get("Demo Sales")
        self.assertEqual((demo.rows, demo.column("qty").dtype, demo.column("qty").missing), (3, "mixed", 1))

    def test_import_file_flow_replace_and_bad_paths(self):
        csv_file = self.data / "mine.csv"
        csv_file.write_text("a,b\n1,x\n2,y\n3,\n")
        out = run_session(self.data, self.exports, [
            "1", "/no/such/file.csv", str(csv_file), "", "",                 # default name 'mine'
            "1", str(csv_file), "mine", "n",                                  # exists -> decline replace
            "1", str(csv_file), "mine", "y",                                  # exists -> replace
            "11", "1", "y",                                                   # delete it
            "0"])
        self.assertIn("File not found", out)
        self.assertIn("Added 'mine'", out)
        self.assertIn("Import cancelled", out)
        self.assertIn("Updated 'mine'", out)
        self.assertIn("Deleted 'mine'", out)

    def test_corrupted_store_does_not_crash_startup(self):
        (self.data / "store.json").write_text("<<< garbage >>>")
        out = run_session(self.data, self.exports, ["3", "0"])
        self.assertIn("unreadable", out)
        self.assertIn("No datasets yet", out)
        self.assertTrue(list(self.data.glob("store.corrupt-*.bak")))

    def test_empty_store_menu_items_are_safe(self):
        out = run_session(self.data, self.exports, ["4", "5", "6", "7", "8", "9", "11", "0"])
        self.assertEqual(out.count("No datasets yet"), 7)

    def test_main_handles_closed_input(self):
        with mock.patch.object(v, "_input", SmartKeyboard([])), contextlib.redirect_stdout(io.StringIO()) as buf:
            code = terminal_app.main(["--data-dir", str(self.data), "--export-dir", str(self.exports), "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Session ended", buf.getvalue())


# ----------------------------------------------------------------------------------- GUI
class GuiSmokeTests(unittest.TestCase):
    """Runs every Streamlit page against a stub `streamlit` module (no browser needed)."""

    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("streamlit", mock.MagicMock())
        import gui_app
        cls.gui = gui_app

    def setUp(self):                      # fresh data + export folders for every test
        env = {"CSV_SUMMARY_DATA_DIR": str(tmpdir()), "CSV_SUMMARY_EXPORT_DIR": str(tmpdir())}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def fake_st(page, button=False, checkbox=False, session=None):
        st = mock.MagicMock()
        st.session_state = {} if session is None else session
        st.radio.return_value = page
        st.button.return_value = button
        st.checkbox.return_value = checkbox
        st.text_input.return_value = ""
        st.text_area.return_value = ""
        st.file_uploader.return_value = None
        st.slider.return_value = 0
        st.selectbox.side_effect = lambda label, options, **kw: options[0]
        st.multiselect.side_effect = lambda label, options, default=None, **kw: list(default or [])
        st.columns.side_effect = lambda spec, **kw: [mock.MagicMock() for _ in range(spec if isinstance(spec, int) else len(spec))]
        st.tabs.side_effect = lambda labels: [mock.MagicMock() for _ in labels]
        return st

    def run_page(self, page, **kw):
        st = self.fake_st(page, **kw)
        with mock.patch.object(self.gui, "st", st):
            self.gui.main()
        return st

    def test_pages_render_empty_then_with_data(self):
        for page in self.gui.PAGES:                                  # empty-state branch
            self.run_page(page)
        self.gui.load_samples(self.gui.get_store())
        self.assertEqual(len(self.gui.get_store().datasets), 2)
        for page in self.gui.PAGES:                                  # populated branch
            st = self.run_page(page)
            self.assertTrue(st.markdown.called or st.title.called, page)

    def test_export_page_creates_files(self):
        self.gui.load_samples(self.gui.get_store())
        session = {}
        st = self.run_page("Export", button=True, checkbox=True, session=session)
        files = [Path(p) for p in session["export_files"]]
        self.assertEqual({p.suffix for p in files}, {".md", ".txt", ".csv", ".png"})
        self.assertTrue(st.download_button.called)

    def test_import_helpers(self):
        store = self.gui.get_store()
        data = b"a,b\n1,x\n2,y\n3,z,extra\n"
        rec, result, err = self.gui.process_import(store, data, "t.csv", "gui test", replace=False)
        self.assertIsNone(err)
        self.assertEqual((rec.rows, result.rejected), (2, 1))
        _, _, err = self.gui.process_import(store, data, "t.csv", "gui test", replace=False)
        self.assertIn("already exists", err)
        self.assertIsNone(self.gui.process_import(store, data, "t.csv", "gui test", replace=True)[2])
        for bad_name in ["", "a/b"]:
            self.assertIsNotNone(self.gui.process_import(store, data, "t.csv", bad_name, True)[2])
        self.assertIn("empty", self.gui.process_import(store, b"", "t.csv", "x", True)[2])
        self.assertIsNotNone(self.gui.process_import(store, b"{bad", "t.json", "x", True)[2])
        st = self.fake_st("Import")
        with mock.patch.object(self.gui, "st", st):
            self.gui.show_import_outcome(rec, result, None)
            self.gui.show_import_outcome(None, None, "boom")
        self.assertTrue(st.error.called and st.success.called)

    def test_strip_html_is_escaped(self):
        from tests.helpers import build
        ds = build("<script>", ["<b>x</b>"], [["1"]])
        html_out = self.gui.completeness_strip(ds)
        self.assertNotIn("<script>", html_out)
        self.assertNotIn("<b>", html_out)


if __name__ == "__main__":
    unittest.main()


class MainEntryPointTests(unittest.TestCase):
    def test_default_runs_terminal_app(self):
        import main as entry
        data, exports = tmpdir(), tmpdir()
        with mock.patch.object(v, "_input", SmartKeyboard(["0"])), contextlib.redirect_stdout(io.StringIO()) as buf:
            code = entry.main(["--data-dir", str(data), "--export-dir", str(exports), "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("Goodbye", buf.getvalue())
        self.assertTrue((data / "store.json").exists())

    def test_help_and_gui_without_streamlit(self):
        import main as entry
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(entry.main(["--help"]), 0)
        self.assertIn("--gui", buf.getvalue())
        with mock.patch("importlib.util.find_spec", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(entry.main(["--gui"]), 1)
        self.assertIn("pip install", buf.getvalue())

    def test_gui_launch_command(self):
        import main as entry
        with mock.patch("importlib.util.find_spec", return_value=object()), \
                mock.patch("subprocess.call", return_value=0) as call:
            self.assertEqual(entry.main(["--gui", "--data-dir", "/tmp/xyz"]), 0)
        cmd = call.call_args[0][0]
        self.assertEqual(cmd[1:4], ["-m", "streamlit", "run"])
        self.assertTrue(cmd[4].endswith("gui_app.py"))
        self.assertEqual(call.call_args[1]["env"]["CSV_SUMMARY_DATA_DIR"], str(Path("/tmp/xyz").resolve()))
