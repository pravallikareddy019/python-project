"""CSV Column Summary Tool - Streamlit GUI.

Run:  streamlit run gui_app.py
Shares the same data store (data/store.json) as the terminal app, so a file imported in one
shows up in the other.
"""
from __future__ import annotations

import html
import tempfile
from pathlib import Path

import streamlit as st

from csv_summary import APP_NAME, __version__, config, engine, exporter, importer, plotting
from csv_summary import validation as v
from csv_summary.alerts import SEVERITIES, collect_alerts, count_by_severity
from csv_summary.search import search_columns
from csv_summary.storage import Store
from csv_summary.summary import build_summary, status_for

INK, ACCENT, OK, WATCH, BAD = "#0E1A2B", "#3B4CCA", "#2F9E6B", "#E3A008", "#D64545"
PAGES = ["Overview", "Import", "Datasets", "Column profiles", "Search", "Charts", "Warnings", "Export"]
TYPES = ["integer", "float", "boolean", "date", "text", "mixed", "empty"]
STATUS_COLOR = {"Healthy": OK, "Needs attention": WATCH, "Critical": BAD, "No data": "#8A94A6",
                "CRITICAL": BAD, "WARNING": WATCH, "INFO": ACCENT}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stApp {{ font-family: 'Plus Jakarta Sans', system-ui, sans-serif; color: {INK}; }}
h1, h2, h3 {{ letter-spacing: -0.02em; font-weight: 800; }}
h1 {{ font-size: 2rem !important; }}
[data-testid="stSidebar"] {{ background: {INK}; }}
[data-testid="stSidebar"] * {{ color: #E7ECF4 !important; }}
[data-testid="stSidebar"] .brand {{ font-size: 1.15rem; font-weight: 800; line-height: 1.2; margin-bottom: .2rem; }}
[data-testid="stSidebar"] .sub {{ color: #9AA7BD !important; font-size: .8rem; }}
[data-testid="stMetric"] {{ background: #fff; border: 1px solid #E3E7EE; border-radius: 10px; padding: .8rem 1rem; }}
[data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; font-weight: 700; }}
.ds-card {{ background: #fff; border: 1px solid #E3E7EE; border-radius: 10px; padding: 1rem 1.2rem; margin-bottom: .8rem; }}
.ds-head {{ display: flex; align-items: center; gap: .7rem; flex-wrap: wrap; }}
.ds-name {{ font-weight: 700; font-size: 1.05rem; }}
.ds-meta {{ color: #5B6677; font-size: .85rem; margin-top: .25rem; font-variant-numeric: tabular-nums; }}
.pill {{ display: inline-block; padding: .1rem .6rem; border-radius: 999px; font-size: .75rem; font-weight: 700;
        color: #fff; white-space: nowrap; }}
.strip {{ display: flex; flex-wrap: wrap; gap: 4px; margin: .7rem 0 .2rem 0; }}
.cell {{ position: relative; width: 14px; height: 44px; background: #E3E7EE; border-radius: 3px; overflow: hidden;
        display: inline-block; }}
.cell::after {{ content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: var(--fill); background: var(--c); }}
.legend {{ color: #5B6677; font-size: .78rem; }}
.alert-row {{ display: flex; gap: .7rem; align-items: baseline; padding: .55rem 0; border-bottom: 1px solid #E3E7EE; }}
.alert-row .where {{ font-weight: 700; min-width: 14rem; }}
.empty {{ background: #fff; border: 1px dashed #B8C1D1; border-radius: 10px; padding: 1.6rem; }}
:focus-visible {{ outline: 3px solid {ACCENT} !important; outline-offset: 2px; }}
</style>
"""


# ----------------------------------------------------------------------------- helpers
def get_store() -> Store:
    return Store(config.store_file()).load()


def chart_dir() -> Path:
    path = config.export_dir() / "gui_charts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pill(text: str) -> str:
    return f'<span class="pill" style="background:{STATUS_COLOR.get(text, "#8A94A6")}">{html.escape(text)}</span>'


def completeness_strip(ds) -> str:
    """One thin gauge per column: how much of the column is filled. The page's signature element."""
    cells = []
    for c in ds.columns:
        filled = 100.0 - c.missing_pct
        colour = BAD if c.missing_pct >= config.CRITICAL_MISSING_PCT else WATCH if c.missing_pct >= config.WARN_MISSING_PCT else OK
        label = html.escape(f"{c.name}: {filled:.0f}% filled ({c.dtype})", quote=True)
        cells.append(f'<span class="cell" title="{label}" style="--fill:{filled:.1f}%;--c:{colour}"></span>')
    return f'<div class="strip" role="img" aria-label="Column completeness for {html.escape(ds.name, quote=True)}">{"".join(cells)}</div>'


def column_rows(ds) -> list[dict]:
    return [{"#": c.position + 1, "Column": c.name, "Type": c.dtype, "Missing": c.missing,
             "Missing %": c.missing_pct, "Unique": c.unique, "Min": engine.fmt_num(c.min), "Max": engine.fmt_num(c.max),
             "Mean": engine.fmt_num(c.mean), "Median": engine.fmt_num(c.median), "Std dev": engine.fmt_num(c.stdev),
             "Outliers": c.outliers} for c in ds.columns]


def process_import(store: Store, data: bytes, filename: str, name: str, replace: bool):
    """Validate, parse, profile and save one upload. Returns (record, result, error_message)."""
    try:
        name = v.validate_dataset_name(name)
    except v.ValidationError as exc:
        return None, None, str(exc)
    if len(data) == 0:
        return None, None, "That file is empty."
    if len(data) > config.MAX_FILE_MB * 1024 * 1024:
        return None, None, f"File is larger than {config.MAX_FILE_MB} MB."
    if store.get(name) and not replace:
        return None, None, f"'{name}' already exists. Tick 'Replace if it exists' or choose another name."
    try:
        result = importer.import_bytes(data, filename)
    except importer.ImportFailure as exc:
        return None, None, str(exc)
    record = engine.profile_dataset(name, result.headers, result.rows, filename, result.rejected)
    store.upsert(record)
    return record, result, None


def show_import_outcome(record, result, error) -> None:
    if error:
        st.error(f"Import failed: {error}")
        return
    st.success(f"Imported “{record.name}”: {record.rows} rows, {record.column_count} columns, "
               f"{record.completeness_pct:.1f}% complete.")
    if result.issues:
        st.warning(f"{result.rejected} row(s) rejected, {result.count('WARNING')} warning(s). Row-by-row log below.")
        st.dataframe([{"Row": i.line or "file", "Level": i.severity, "Message": i.message}
                      for i in sorted(result.issues, key=lambda i: i.line)], hide_index=True)
        log = "\n".join(importer.format_issues(result))
        st.download_button("Download error log", log, file_name=f"import_log_{record.name}.txt")
    st.markdown(completeness_strip(record), unsafe_allow_html=True)


def need_data(store: Store) -> bool:
    if store.datasets:
        return True
    st.markdown('<div class="empty"><b>No datasets yet.</b><br>Open <b>Import</b> to add a CSV or JSON file, '
                'or load the sample datasets to explore the tool.</div>', unsafe_allow_html=True)
    if st.button("Load sample datasets", key="load_samples_empty"):
        load_samples(store)
        st.rerun()
    return False


def load_samples(store: Store) -> None:
    for filename in config.SAMPLE_FILES:
        path = config.sample_dir() / filename
        if path.exists():
            process_import(store, path.read_bytes(), path.name, path.stem, replace=True)


# ----------------------------------------------------------------------------- pages
def page_overview(store: Store) -> None:
    st.title("Data quality overview")
    if not need_data(store):
        return
    s = build_summary(store.datasets)
    a, b, c, d = st.columns(4)
    a.metric("Datasets", s["datasets"])
    b.metric("Rows", f"{s['rows']:,}")
    c.metric("Columns", s["columns"])
    d.metric("Cells filled", f"{100 - s['overall_missing_pct']:.1f}%")
    st.markdown(f"Overall status {pill(s['overall_status'])} &nbsp; "
                f"{s['alerts']['CRITICAL']} critical · {s['alerts']['WARNING']} warnings · {s['alerts']['INFO']} notes",
                unsafe_allow_html=True)
    st.subheader("Datasets")
    st.caption("Each bar is one column, filled to show how complete it is. Hover for details.")
    for ds, info in zip(store.datasets, s["per_dataset"]):
        st.markdown(
            f'<div class="ds-card"><div class="ds-head"><span class="ds-name">{html.escape(ds.name)}</span>'
            f'{pill(info["status"])}</div>'
            f'<div class="ds-meta">{ds.rows:,} rows · {ds.column_count} columns · {ds.completeness_pct:.1f}% complete · '
            f'{info["critical"]} critical, {info["warnings"]} warnings</div>{completeness_strip(ds)}</div>',
            unsafe_allow_html=True)
    st.subheader("Key trends")
    for t in s["trends"]:
        st.markdown(f"- {t}")
    left, right = st.columns(2)
    try:
        left.image(str(plotting.chart_types(store.datasets, chart_dir())))
        right.image(str(plotting.chart_completeness(store.datasets, chart_dir())))
    except plotting.ChartError as exc:
        st.info(str(exc))


def page_import(store: Store) -> None:
    st.title("Import data")
    st.write("Add a CSV or JSON file. The tool detects the delimiter and encoding, fixes small problems, "
             "and logs every row it changes or rejects.")
    tab_upload, tab_paste = st.tabs(["Upload a file", "Paste data"])
    with tab_upload:
        upload = st.file_uploader("Choose a file", type=["csv", "tsv", "txt", "json"])
        default = Path(upload.name).stem if upload is not None else ""
        name = st.text_input("Dataset name", value=default, key="upload_name")
        replace = st.checkbox("Replace if it exists", key="upload_replace")
        if st.button("Import file", key="upload_go"):
            if upload is None:
                st.error("Choose a file first.")
            else:
                show_import_outcome(*process_import(store, upload.getvalue(), upload.name, name, replace))
    with tab_paste:
        text = st.text_area("Paste CSV text (first line = column names)", height=180, key="paste_text")
        pname = st.text_input("Dataset name", key="paste_name")
        preplace = st.checkbox("Replace if it exists", key="paste_replace")
        if st.button("Import pasted data", key="paste_go"):
            if not text.strip():
                st.error("Paste some CSV text first.")
            else:
                show_import_outcome(*process_import(store, text.encode("utf-8"), "pasted.csv", pname, preplace))
    st.divider()
    st.subheader("Try it with sample data")
    st.caption("Loads 40 student records (with deliberately malformed rows) and 30 orders.")
    if st.button("Load sample datasets", key="load_samples"):
        load_samples(store)
        st.success("Sample datasets loaded. Open Overview to see them.")


def page_datasets(store: Store) -> None:
    st.title("Datasets")
    if not need_data(store):
        return
    name = st.selectbox("Dataset", store.names())
    ds = store.get(name)
    a, b, c, d = st.columns(4)
    a.metric("Rows", f"{ds.rows:,}")
    b.metric("Columns", ds.column_count)
    c.metric("Complete", f"{ds.completeness_pct:.1f}%")
    d.metric("Rows rejected", ds.skipped_rows)
    st.markdown(f"{pill(status_for(ds.completeness_pct))}&nbsp; Imported {ds.imported_at.replace('T', ' ')} from "
                f"`{html.escape(ds.source)}`", unsafe_allow_html=True)
    st.markdown(completeness_strip(ds), unsafe_allow_html=True)
    st.subheader("Column summary")
    st.dataframe(column_rows(ds), hide_index=True)
    if ds.preview:
        st.subheader("First rows")
        st.dataframe([dict(zip([c.name for c in ds.columns], row)) for row in ds.preview], hide_index=True)
    with st.expander("Delete this dataset"):
        sure = st.checkbox(f"Yes, permanently delete “{ds.name}”", key=f"del_{ds.name}")
        if st.button("Delete dataset", key=f"delbtn_{ds.name}") and sure:
            store.remove(ds.name)
            st.success("Deleted.")
            st.rerun()


def page_columns(store: Store) -> None:
    st.title("Column profiles")
    if not need_data(store):
        return
    ds = store.get(st.selectbox("Dataset", store.names()))
    col = ds.column(st.selectbox("Column", [c.name for c in ds.columns]))
    a, b, c, d = st.columns(4)
    a.metric("Type", col.dtype)
    b.metric("Missing", f"{col.missing} ({col.missing_pct:.1f}%)")
    c.metric("Unique values", col.unique)
    d.metric("Rows", col.total)
    if len(col.type_counts) > 1:
        st.warning("Mixed value types: " + ", ".join(f"{k} {n}" for k, n in col.type_counts.items()))
    if col.is_numeric:
        st.subheader("Numeric summary")
        cols = st.columns(4)
        for slot, (label, value) in zip(cols * 2, [("Min", col.min), ("Q1", col.q1), ("Median", col.median),
                                                    ("Mean", col.mean), ("Q3", col.q3), ("Max", col.max),
                                                    ("Std deviation", col.stdev), ("Outliers (IQR)", col.outliers)]):
            slot.metric(label, engine.fmt_num(value))
        left, right = st.columns(2)
        try:
            left.image(str(plotting.chart_histogram(ds, col.name, chart_dir())))
            right.image(str(plotting.chart_trend(ds, col.name, chart_dir())))
        except plotting.ChartError as exc:
            st.info(str(exc))
    elif col.min is not None:
        st.write(f"Earliest {col.min} · latest {col.max}")
    if col.top_values:
        st.subheader("Most common values")
        st.dataframe([{"Value": val, "Count": n} for val, n in col.top_values], hide_index=True)


def page_search(store: Store) -> None:
    st.title("Search columns")
    if not need_data(store):
        return
    keyword = st.text_input("Keyword", placeholder="e.g. email, date, gpa")
    c1, c2, c3 = st.columns(3)
    dtype = c1.selectbox("Type", ["Any"] + TYPES)
    dataset = c2.selectbox("Dataset", ["All"] + store.names())
    min_missing = c3.slider("Minimum % missing", 0, 100, 0, 5)
    hits = search_columns(store.datasets, keyword, None if dtype == "Any" else dtype,
                          None if dataset == "All" else dataset, float(min_missing) if min_missing else None)
    st.caption(f"{len(hits)} matching column(s)")
    if hits:
        st.dataframe([{"Dataset": h.dataset.name, "Column": h.column.name, "Type": h.column.dtype,
                       "Missing": h.column.missing, "Missing %": h.column.missing_pct, "Unique": h.column.unique,
                       "Mean": engine.fmt_num(h.column.mean)} for h in hits], hide_index=True)
    else:
        st.info("No columns match. Try a shorter keyword or clear a filter.")


def page_charts(store: Store) -> None:
    st.title("Charts")
    if not need_data(store):
        return
    kind = st.selectbox("Chart", ["Missing values per column", "Column type distribution", "Completeness by dataset",
                                  "Histogram of a numeric column", "Trend of a numeric column"])
    try:
        if kind == "Completeness by dataset":
            path = plotting.chart_completeness(store.datasets, chart_dir())
        elif kind == "Column type distribution":
            path = plotting.chart_types(store.datasets, chart_dir())
        else:
            ds = store.get(st.selectbox("Dataset", store.names()))
            if kind == "Missing values per column":
                path = plotting.chart_missing(ds, chart_dir())
            else:
                nums = plotting.numeric_columns(ds)
                if not nums:
                    st.info("This dataset has no numeric columns.")
                    return
                column = st.selectbox("Numeric column", nums)
                draw = plotting.chart_histogram if kind.startswith("Histogram") else plotting.chart_trend
                path = draw(ds, column, chart_dir())
    except plotting.ChartError as exc:
        st.error(str(exc))
        return
    st.image(str(path))
    st.download_button("Download PNG", Path(path).read_bytes(), file_name=Path(path).name, mime="image/png")


def page_warnings(store: Store) -> None:
    st.title("Warnings")
    if not need_data(store):
        return
    alerts = collect_alerts(store.datasets)
    counts = count_by_severity(alerts)
    cols = st.columns(3)
    for slot, sev in zip(cols, SEVERITIES):
        slot.metric(sev.title(), counts[sev])
    st.caption(f"Missing data: warning at {config.WARN_MISSING_PCT:.0f}%, critical at {config.CRITICAL_MISSING_PCT:.0f}%. "
               f"Outliers use the {config.OUTLIER_IQR_FACTOR}×IQR rule.")
    chosen = st.multiselect("Show", list(SEVERITIES), default=list(SEVERITIES))
    shown = [a for a in alerts if a.severity in chosen]
    if not shown:
        st.success("No warnings to show. Every column is within its thresholds.")
        return
    rows = "".join(
        f'<div class="alert-row">{pill(a.severity)}<span class="where">{html.escape(a.dataset)}'
        f'{"." + html.escape(a.column) if a.column else ""}</span><span>{html.escape(a.message)}</span></div>'
        for a in shown)
    st.markdown(rows, unsafe_allow_html=True)


MIME = {".md": "text/markdown", ".txt": "text/plain", ".csv": "text/csv", ".png": "image/png"}


def page_export(store: Store) -> None:
    st.title("Export reports")
    if not need_data(store):
        return
    scope = st.selectbox("Include", ["All datasets"] + store.names())
    datasets = store.datasets if scope == "All datasets" else [store.get(scope)]
    c1, c2, c3, c4 = st.columns(4)
    want_md = c1.checkbox("Markdown report", value=True)
    want_txt = c2.checkbox("Audit log (.txt)", value=True)
    want_csv = c3.checkbox("CSV report", value=True)
    want_png = c4.checkbox("Charts (PNG)", value=True)
    if st.button("Create export"):
        out = config.export_dir()
        charts = plotting.generate_report_charts(datasets, out) if want_png else []
        files = []
        if want_md:
            files.append(exporter.export_markdown(datasets, out, charts))
        if want_txt:
            files.append(exporter.export_audit_log(datasets, out))
        if want_csv:
            files.append(exporter.export_csv_report(datasets, out))
        st.session_state["export_files"] = [str(p) for p in files + charts]
    files = [Path(p) for p in st.session_state.get("export_files", [])]
    if files:
        st.success(f"{len(files)} file(s) saved in {config.export_dir()}")
        for i, path in enumerate(files):
            if path.exists():
                st.download_button(f"Download {path.name}", path.read_bytes(), file_name=path.name,
                                   mime=MIME.get(path.suffix, "application/octet-stream"), key=f"dl_{i}")


PAGE_FUNCS = {"Overview": page_overview, "Import": page_import, "Datasets": page_datasets,
              "Column profiles": page_columns, "Search": page_search, "Charts": page_charts,
              "Warnings": page_warnings, "Export": page_export}


def main() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="▦", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    store = get_store()
    with st.sidebar:
        st.markdown(f'<div class="brand">{APP_NAME}</div><div class="sub">v{__version__}</div>', unsafe_allow_html=True)
        page = st.radio("Navigate", PAGES, label_visibility="collapsed")
        st.caption(f"{len(store.datasets)} dataset(s) · {store.path}")
    for note in store.notes:
        if "starting with an empty store" not in note:
            st.warning(note)
    PAGE_FUNCS[page](store)


if __name__ == "__main__":
    main()
