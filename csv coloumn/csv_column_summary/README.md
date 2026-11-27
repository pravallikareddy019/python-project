# CSV Column Summary Tool

Profile any CSV (or JSON) file: **column names, data types, missing counts and numeric summaries**,
with warnings, charts and reports. Built for the FutureReady Hack brief (Project #99, Data & Visualization).

Two front ends share one engine and one data store (`data/store.json`):

| Front end | Start with | Best for |
|---|---|---|
| Terminal menu | `python main.py` | the classic demo, works anywhere |
| Streamlit GUI | `python main.py --gui` | the modern visual interface |

`main.py` is the single entry point. (`python app.py` and `streamlit run gui_app.py` also work directly.)

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # matplotlib (+ streamlit for the GUI)

python main.py                     # terminal app: choose 10 to load sample data
python main.py --gui               # GUI: Import → Load sample datasets
```

Python 3.10+. The core engine uses only the standard library; Matplotlib is needed for charts and
Streamlit only for the GUI (the terminal app works without Streamlit).

## Features (brief → where it lives)

**Must-have**

| Feature | Implementation |
|---|---|
| Interactive terminal interface | `app.py` - branded banner, numbered menu, ANSI colours, fixed-width tables, pagination (`csv_summary/display.py`) |
| Defensive input validation | `csv_summary/validation.py` - pure validators + `ask_*` loops that never crash on blank, non-numeric, out-of-range or hostile input; GUI reuses the same validators |
| Core logic engine | `csv_summary/engine.py` - type inference (integer, float, boolean, date, text, mixed), missing detection (`""`, NA, N/A, null, NaN, `-`, `?`), min/max/mean/median/std-dev/quartiles, IQR outliers |
| Local persistence | `csv_summary/storage.py` - JSON store with schema version, atomic writes, corruption recovery (backup + clean template), flat CSV mirror `data/column_profiles.csv` |
| Record query & search | `csv_summary/search.py` - keyword + type + dataset + minimum-missing-% filters |
| Executive summary | `csv_summary/summary.py` - totals, averages, status per dataset, type distribution, key trends |
| Visual data plotting | `csv_summary/plotting.py` - missing-values bars, type distribution, completeness by dataset, histogram, trend line (Matplotlib, headless-safe PNGs) |

**Stretch (all included)**

| Feature | Implementation |
|---|---|
| Multi-format export | `csv_summary/exporter.py` - Markdown report, plain-text audit log, CSV report (+ charts) |
| Threshold warnings | `csv_summary/alerts.py` - missing ≥20% warning / ≥50% critical, all-empty, mixed types, IQR outliers, constant columns, stale dates, rejected rows |
| GUI enhancement | `gui_app.py` - Streamlit multi-page app |
| Bulk dataset import | `csv_summary/importer.py` - delimiter + encoding detection, ragged-row / duplicate-header / blank-header handling, **row-by-row error log** |

Extras: JSON import (the sample is provided in both CSV and JSON), manual dataset entry, sample loader.

## Terminal menu

```
 1 Import a CSV / JSON file      7 Warnings
 2 Enter a small dataset manually 8 Charts
 3 Browse datasets               9 Export reports
 4 Column details               10 Load sample datasets
 5 Search columns               11 Delete a dataset
 6 Executive summary             0 Exit
```

## GUI pages

Overview (completeness strips, key trends) · Import (upload, paste, samples) · Datasets · Column profiles ·
Search · Charts · Warnings · Export. In the **completeness strip**, each thin bar is one column, filled to
show how complete it is: green is healthy, amber is over 20% missing, red is over 50% missing.

## Sample data (`data/`)

* `sample_data.csv` / `sample_data.json` - 40 student records: normal rows, boundary values (GPA 0.00 and 4.00,
  attendance 0 and 100), an impossible value (250), an outlier (age 61), a mixed-type cell (`twenty`), blanks / `NA` / `null`,
  a very sparse column and a constant column. The CSV also contains **three malformed lines** (an over-long row that is
  rejected, a short row that is padded, a blank line) so the import log has something to show.
* `sample_orders.csv` - 30 order records with different column shapes.
* Regenerate with `python scripts/make_sample_data.py`.

## Suggested 5-minute demo

1. `python main.py` → banner and menu.
2. Option **2**: type a bad name (`bad/name`), `abc` for the column count, a row with too few values - watch each get rejected and corrected.
3. Option **10**: load samples → the **row-by-row import log** shows rejected / padded / skipped lines.
4. Options **6** and **7**: executive summary, then threshold warnings.
5. Option **8**: draw a chart. Option **9** → *All formats* to write Markdown, audit log, CSV and PNGs to `exports/`.
6. Exit, run `python main.py` again → "Loaded 3 dataset(s)": persistence proven.
7. `python main.py --gui` → the same data, visually.

## Tests

```bash
python -m unittest discover -s tests -t .
```

61 tests: engine maths, validation loops, importer edge cases, storage corruption recovery, search, alerts
(including exact threshold boundaries), summary, exports, valid-PNG checks, a scripted end-to-end terminal
journey that mirrors the demo (including a restart and a corrupted store) and a smoke test that renders every
GUI page against a stubbed Streamlit.

## Project layout

```
main.py                 entry point (terminal app, or --gui for Streamlit)
app.py                  terminal application
gui_app.py              Streamlit GUI
csv_summary/            engine, importer, storage, validation, search, alerts, summary, plotting, exporter, display
data/                   sample files (store.json is created on first run)
exports/examples/       example report, audit log, CSV and charts
scripts/                sample data generator
tests/                  unit, end-to-end and GUI smoke tests
.streamlit/config.toml  GUI theme
```

## Notes

* Missing-value markers, thresholds and limits are in `csv_summary/config.py`.
* Numeric values (up to 2,000 per column) are stored so charts work after a restart; very large files are sampled evenly.
* Delete `data/store.json` to reset. A corrupted store is never lost silently - it is copied to `store.corrupt-<time>.bak`.
