#!/usr/bin/env python3
"""CSV Column Summary Tool - interactive terminal application.

Run:  python app.py            (optional: --data-dir DIR  --export-dir DIR  --no-color)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from csv_summary import ansi, config, display, engine, exporter, importer, plotting, validation as v
from csv_summary.alerts import collect_alerts, count_by_severity
from csv_summary.ansi import paint
from csv_summary.search import search_columns
from csv_summary.storage import Store
from csv_summary.summary import build_summary, status_for

MENU = [
    ("1", "Import a CSV / JSON file"),
    ("2", "Enter a small dataset manually"),
    ("3", "Browse datasets"),
    ("4", "Column details"),
    ("5", "Search columns"),
    ("6", "Executive summary"),
    ("7", "Warnings"),
    ("8", "Charts"),
    ("9", "Export reports"),
    ("10", "Load sample datasets"),
    ("11", "Delete a dataset"),
    ("0", "Exit"),
]
TYPES = ["integer", "float", "boolean", "date", "text", "mixed", "empty"]


class Application:
    def __init__(self, store_path: Path, export_dir: Path):
        self.store = Store(store_path)
        self.export_dir = Path(export_dir)

    # ------------------------------------------------------------------ plumbing
    def out(self, text: str = "") -> None:
        print(text)

    def pause(self) -> None:
        v.read_line(paint("\n  Press Enter to return to the menu...", "grey"))

    def need_data(self) -> bool:
        if not self.store.datasets:
            self.out(paint("  No datasets yet. Use option 1 (import) or 10 (load samples) first.", "yellow"))
            return False
        return True

    def pick_dataset(self, prompt: str = "  Choose a dataset number (0 to cancel)"):
        names = self.store.names()
        for i, name in enumerate(names, 1):
            self.out(f"   {i:>2}. {name}")
        n = v.ask_int(prompt, 0, len(names))
        return None if n == 0 else self.store.datasets[n - 1]

    # ------------------------------------------------------------------ main loop
    def run(self) -> None:
        self.out(display.banner())
        self.store.load()
        for note in self.store.notes:
            self.out(paint(f"  ! {note}", "yellow"))
        self.out(paint(f"\n  Loaded {len(self.store.datasets)} dataset(s) from {self.store.path}", "grey"))
        sev = count_by_severity(collect_alerts(self.store.datasets))
        if sev["CRITICAL"] or sev["WARNING"]:
            self.out(paint(f"  ⚠ {sev['CRITICAL']} critical and {sev['WARNING']} warning alert(s) - see option 7.", "yellow"))
        handlers = {"1": self.import_file, "2": self.manual_entry, "3": self.browse, "4": self.column_details,
                    "5": self.search, "6": self.executive_summary, "7": self.warnings, "8": self.charts,
                    "9": self.export, "10": self.load_samples, "11": self.delete}
        while True:
            self.out(display.heading("Main menu"))
            for key, label in MENU:
                self.out(f"   {paint(key.rjust(2), 'cyan', 'bold')}  {label}")
            choice = v.ask_menu_choice("\n  Select an option", [k for k, _ in MENU])
            if choice == "0":
                self.out(paint("\n  Your data is saved. Goodbye!\n", "green"))
                return
            try:
                handlers[choice]()
            except v.UserAbort:
                raise
            except KeyboardInterrupt:
                self.out(paint("\n  Cancelled.", "yellow"))
            except Exception as exc:    # last line of defence: never crash the session
                self.out(paint(f"  ✗ Something went wrong: {exc}. Your data is unchanged.", "red"))
            self.pause()

    # ------------------------------------------------------------------ 1. import
    def import_file(self) -> None:
        self.out(display.heading("Import a CSV / JSON file"))
        path = v.ask_path("  File path (.csv or .json)")
        self.finish_import(path)

    def finish_import(self, path: Path, name: str | None = None, quiet: bool = False) -> None:
        try:
            result = importer.import_file(path)
        except importer.ImportFailure as exc:
            self.out(paint(f"  ✗ Import failed: {exc}", "red"))
            return
        self.out(f"  Detected delimiter {result.delimiter!r}, encoding {result.encoding}: "
                 f"{len(result.rows)} row(s) accepted, {result.rejected} rejected, "
                 f"{result.count('WARNING')} warning(s).")
        default = "".join(ch if ch.isalnum() or ch in " _-." else "_" for ch in Path(path).stem)[:config.MAX_NAME_LEN]
        if name is None:
            name = v.ask_string("  Dataset name", v.validate_dataset_name, default or "dataset")
        existing = self.store.get(name)
        if existing and not quiet and not v.ask_yes_no(f"  '{name}' already exists. Replace it", default=False):
            self.out(paint("  Import cancelled.", "yellow"))
            return
        issue_lines = importer.format_issues(result)
        if issue_lines:
            self.out(display.heading("Import log (row by row)"))
            display.paginate(issue_lines, v.read_line, 12)
            log = importer.write_error_log(result, name, self.export_dir)
            self.out(paint(f"  Log saved to {log}", "grey"))
        record = engine.profile_dataset(name, result.headers, result.rows, str(path), result.rejected)
        replaced = self.store.upsert(record)
        self.out(paint(f"  ✓ {'Updated' if replaced else 'Added'} '{name}': {record.rows} rows, "
                       f"{record.column_count} columns, {record.completeness_pct:.1f}% complete.", "green"))
        if not quiet:
            self.show_dataset(record)

    # ------------------------------------------------------------------ 2. manual entry
    def manual_entry(self) -> None:
        self.out(display.heading("Enter a small dataset manually"))
        name = v.ask_string("  Dataset name", v.validate_dataset_name)
        if self.store.get(name) and not v.ask_yes_no(f"  '{name}' exists. Replace it", default=False):
            self.out(paint("  Cancelled.", "yellow"))
            return
        count = v.ask_int("  Number of columns (1-30)", 1, 30)
        headers: list[str] = []
        while len(headers) < count:
            col = v.ask_string(f"  Name of column {len(headers) + 1}", v.validate_column_name)
            if col.lower() in (h.lower() for h in headers):
                self.out(paint("  ✗ Column names must be unique.", "red"))
                continue
            headers.append(col)
        self.out(f"  Enter rows as {count} comma-separated values. Use NA for unknown. Blank line to finish.")
        rows: list[list[str]] = []
        while True:
            line = v.sanitize(v.read_line(f"  row {len(rows) + 1}> "))
            if not line:
                if rows:
                    break
                self.out(paint("  ✗ Enter at least one row.", "red"))
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != count:
                self.out(paint(f"  ✗ Expected {count} values, got {len(parts)}. Try again.", "red"))
                continue
            rows.append(parts)
        record = engine.profile_dataset(name, headers, rows, "manual entry")
        self.store.upsert(record)
        self.out(paint(f"  ✓ Saved '{name}' with {len(rows)} row(s).", "green"))
        self.show_dataset(record)

    # ------------------------------------------------------------------ 3. browse
    def dataset_table(self) -> list[str]:
        rows = [[i, d.name, d.rows, d.column_count, f"{d.completeness_pct:.1f}%",
                 display.status(status_for(d.completeness_pct)),
                 d.imported_at.replace("T", " ")] for i, d in enumerate(self.store.datasets, 1)]
        return display.table(["#", "Dataset", "Rows", "Cols", "Complete", "Status", "Imported"], rows)

    def browse(self) -> None:
        self.out(display.heading("Datasets"))
        if not self.need_data():
            return
        display.paginate(self.dataset_table(), v.read_line)
        n = v.ask_int("\n  Open dataset number (0 to go back)", 0, len(self.store.datasets))
        if n:
            self.show_dataset(self.store.datasets[n - 1])

    def show_dataset(self, ds) -> None:
        self.out(display.heading(f"{ds.name}  -  {ds.rows} rows × {ds.column_count} columns"))
        self.out(f"  Completeness {display.bar(ds.completeness_pct)} {ds.completeness_pct:.1f}%   "
                 f"missing cells: {ds.missing_cells}/{ds.total_cells}   source: {ds.source}")
        rows = [[c.position + 1, c.name, c.dtype, c.missing, f"{c.missing_pct:.1f}%", c.unique,
                 engine.fmt_num(c.min), engine.fmt_num(c.max), engine.fmt_num(c.mean), engine.fmt_num(c.median)]
                for c in ds.columns]
        lines = display.table(["#", "Column", "Type", "Missing", "Miss %", "Unique", "Min", "Max", "Mean", "Median"], rows)
        display.paginate(lines, v.read_line)
        sev = count_by_severity(collect_alerts([ds]))
        if sev["CRITICAL"] or sev["WARNING"]:
            self.out(paint(f"\n  ⚠ {sev['CRITICAL']} critical / {sev['WARNING']} warning alert(s) for this dataset - see option 7.", "yellow"))

    # ------------------------------------------------------------------ 4. column details
    def column_details(self) -> None:
        self.out(display.heading("Column details"))
        if not self.need_data():
            return
        ds = self.pick_dataset()
        if ds is None:
            return
        self._list_columns(ds)
        col_name = v.ask_choice("  Column (number or name)", [c.name for c in ds.columns])
        c = ds.column(col_name)
        self.out(display.heading(f"{ds.name}.{c.name}"))
        facts = [("Type", c.dtype), ("Rows", c.total), ("Missing", f"{c.missing} ({c.missing_pct:.1f}%)"),
                 ("Unique values", c.unique)]
        if c.is_numeric:
            facts += [("Min", engine.fmt_num(c.min)), ("Q1", engine.fmt_num(c.q1)), ("Median", engine.fmt_num(c.median)),
                      ("Mean", engine.fmt_num(c.mean)), ("Q3", engine.fmt_num(c.q3)), ("Max", engine.fmt_num(c.max)),
                      ("Std deviation", engine.fmt_num(c.stdev)), ("Outliers (IQR)", c.outliers)]
        elif c.min is not None:
            facts += [("Earliest", c.min), ("Latest", c.max)]
        for label, value in facts:
            self.out(f"   {label:<16}{value}")
        if len(c.type_counts) > 1:
            self.out(f"   {'Type mix':<16}" + ", ".join(f"{k}: {n}" for k, n in c.type_counts.items()))
        if c.top_values:
            self.out(paint("\n   Most common values", "bold"))
            for value, count in c.top_values:
                self.out(f"     {str(value)[:30]:<32}{count}")

    def _list_columns(self, ds) -> None:
        for c in ds.columns:
            self.out(f"   {c.position + 1:>2}. {c.name}  ({c.dtype})")

    # ------------------------------------------------------------------ 5. search
    def search(self) -> None:
        self.out(display.heading("Search columns"))
        if not self.need_data():
            return
        keyword = v.sanitize(v.read_line("  Keyword (blank = any): "))
        dtype = v.ask_choice("  Type filter (number or name)", ["any"] + TYPES)
        pct = v.ask_optional("  Minimum % missing (blank = no filter)", lambda s: v.validate_float(s, 0, 100))
        dataset = None
        if len(self.store.datasets) > 1 and v.ask_yes_no("  Limit to one dataset", default=False):
            dataset = self.pick_dataset()
            dataset = dataset.name if dataset else None
        hits = search_columns(self.store.datasets, keyword, None if dtype == "any" else dtype, dataset, pct)
        if not hits:
            self.out(paint("  No columns match those filters.", "yellow"))
            return
        self.out(paint(f"\n  {len(hits)} match(es)", "green"))
        rows = [[h.dataset.name, h.column.name, h.column.dtype, h.column.missing, f"{h.column.missing_pct:.1f}%",
                 h.column.unique, engine.fmt_num(h.column.mean)] for h in hits]
        display.paginate(display.table(["Dataset", "Column", "Type", "Missing", "Miss %", "Unique", "Mean"], rows), v.read_line)

    # ------------------------------------------------------------------ 6. summary
    def executive_summary(self) -> None:
        self.out(display.heading("Executive summary"))
        if not self.need_data():
            return
        s = build_summary(self.store.datasets)
        self.out(f"   Datasets {s['datasets']}   Rows {s['rows']:,}   Columns {s['columns']}   "
                 f"Avg rows/dataset {s['avg_rows']}")
        self.out(f"   Cells filled {display.bar(100 - s['overall_missing_pct'])} {100 - s['overall_missing_pct']:.1f}%   "
                 f"avg missing per column {s['avg_missing_pct']:.1f}%")
        self.out(f"   Overall status: {display.status(s['overall_status'])}   "
                 f"Alerts: {s['alerts']['CRITICAL']} critical, {s['alerts']['WARNING']} warning, {s['alerts']['INFO']} info\n")
        rows = [[d["name"], d["rows"], d["columns"], f"{d['completeness_pct']:.1f}%", display.status(d["status"]),
                 d["critical"], d["warnings"]] for d in s["per_dataset"]]
        for line in display.table(["Dataset", "Rows", "Cols", "Complete", "Status", "Crit", "Warn"], rows):
            self.out(line)
        self.out(paint("\n   Column types: ", "bold") + ", ".join(f"{k} {n}" for k, n in s["type_distribution"].items()))
        self.out(paint("\n   Key trends", "bold"))
        for t in s["trends"]:
            self.out(f"    • {t}")

    # ------------------------------------------------------------------ 7. warnings
    def warnings(self) -> None:
        self.out(display.heading("Threshold warnings"))
        if not self.need_data():
            return
        alerts = collect_alerts(self.store.datasets)
        if not alerts:
            self.out(paint("  ✓ No warnings. All columns are within thresholds.", "green"))
            return
        sev = count_by_severity(alerts)
        self.out(f"  {display.status('CRITICAL')} {sev['CRITICAL']}   {display.status('WARNING')} {sev['WARNING']}   "
                 f"{display.status('INFO')} {sev['INFO']}   "
                 f"(missing: warn ≥{config.WARN_MISSING_PCT:.0f}%, critical ≥{config.CRITICAL_MISSING_PCT:.0f}%)\n")
        lines = [f"  {display.status(a.severity):<18} {paint(a.dataset + '.' + (a.column or '*'), 'bold')}: {a.message}"
                 for a in alerts]
        display.paginate(lines, v.read_line, 12)

    # ------------------------------------------------------------------ 8. charts
    def charts(self) -> None:
        self.out(display.heading("Charts"))
        if not self.need_data():
            return
        options = ["Missing values per column", "Column type distribution", "Histogram of a numeric column",
                   "Trend of a numeric column", "Completeness by dataset"]
        for i, o in enumerate(options, 1):
            self.out(f"   {i}. {o}")
        kind = v.ask_int("  Chart number (0 to cancel)", 0, len(options))
        if kind == 0:
            return
        try:
            if kind == 5:
                path = plotting.chart_completeness(self.store.datasets, self.export_dir)
            elif kind == 2:
                path = plotting.chart_types(self.store.datasets, self.export_dir)
            else:
                ds = self.pick_dataset()
                if ds is None:
                    return
                if kind == 1:
                    path = plotting.chart_missing(ds, self.export_dir)
                else:
                    nums = plotting.numeric_columns(ds)
                    if not nums:
                        self.out(paint("  ✗ This dataset has no numeric columns.", "red"))
                        return
                    self._show(nums)
                    col = v.ask_choice("  Numeric column (number or name)", nums)
                    path = (plotting.chart_histogram if kind == 3 else plotting.chart_trend)(ds, col, self.export_dir)
        except plotting.ChartError as exc:
            self.out(paint(f"  ✗ {exc}", "red"))
            return
        self.out(paint(f"  ✓ Chart saved: {path}", "green"))

    def _show(self, items) -> None:
        for i, item in enumerate(items, 1):
            self.out(f"   {i:>2}. {item}")

    # ------------------------------------------------------------------ 9. export
    def export(self) -> None:
        self.out(display.heading("Export reports"))
        if not self.need_data():
            return
        formats = ["All formats + charts", "Markdown report", "Plain-text audit log", "CSV report"]
        for i, f in enumerate(formats, 1):
            self.out(f"   {i}. {f}")
        choice = v.ask_int("  Format number (0 to cancel)", 0, len(formats))
        if choice == 0:
            return
        datasets = self.store.datasets
        if len(datasets) > 1 and v.ask_yes_no("  Export a single dataset only", default=False):
            ds = self.pick_dataset()
            if ds is None:
                return
            datasets = [ds]
        if choice == 1:
            paths = exporter.export_all(datasets, self.export_dir)
        elif choice == 2:
            paths = [exporter.export_markdown(datasets, self.export_dir)]
        elif choice == 3:
            paths = [exporter.export_audit_log(datasets, self.export_dir)]
        else:
            paths = [exporter.export_csv_report(datasets, self.export_dir)]
        for p in paths:
            self.out(paint(f"  ✓ {p}", "green"))

    # ------------------------------------------------------------------ 10/11
    def load_samples(self) -> None:
        self.out(display.heading("Load sample datasets"))
        for filename in config.SAMPLE_FILES:
            path = config.sample_dir() / filename
            if not path.exists():
                self.out(paint(f"  ✗ Sample file missing: {path}", "red"))
                continue
            self.finish_import(path, name=path.stem, quiet=True)

    def delete(self) -> None:
        self.out(display.heading("Delete a dataset"))
        if not self.need_data():
            return
        ds = self.pick_dataset()
        if ds and v.ask_yes_no(f"  Permanently delete '{ds.name}'", default=False):
            self.store.remove(ds.name)
            self.out(paint(f"  ✓ Deleted '{ds.name}'.", "green"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CSV Column Summary Tool (terminal)")
    parser.add_argument("--data-dir", type=Path, default=None, help="folder for store.json")
    parser.add_argument("--export-dir", type=Path, default=None, help="folder for reports and charts")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colours")
    args = parser.parse_args(argv)
    if args.no_color:
        ansi.set_enabled(False)
    data_dir = args.data_dir or config.data_dir()
    export_dir = args.export_dir or config.export_dir()
    app = Application(data_dir / "store.json", export_dir)
    try:
        app.run()
    except (v.UserAbort, KeyboardInterrupt):
        print("\n  Session ended. Your data is saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
