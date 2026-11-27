"""Multi-format export: Markdown report, plain-text audit log, CSV report."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import APP_NAME, __version__
from .alerts import collect_alerts
from .engine import fmt_num
from .models import DatasetRecord
from .storage import write_profiles_csv
from .summary import build_summary


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _md_table(headers: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |")
    return out


def _column_rows(ds: DatasetRecord) -> list[list]:
    return [[c.position + 1, c.name, c.dtype, c.missing, f"{c.missing_pct:.1f}%", c.unique,
             fmt_num(c.min), fmt_num(c.max), fmt_num(c.mean), fmt_num(c.median), fmt_num(c.stdev)]
            for c in ds.columns]


COLUMN_HEADERS = ["#", "Column", "Type", "Missing", "Missing %", "Unique", "Min", "Max", "Mean", "Median", "Std dev"]


def export_markdown(datasets: list[DatasetRecord], out_dir, charts: list[Path] | None = None) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    s = build_summary(datasets)
    alerts = collect_alerts(datasets)
    lines = [f"# {APP_NAME} - Report", "",
             f"_Generated {datetime.now():%Y-%m-%d %H:%M} by {APP_NAME} v{__version__}_", "",
             "## Executive summary", ""]
    lines += _md_table(["Metric", "Value"], [
        ["Datasets", s["datasets"]], ["Total rows", f"{s['rows']:,}"], ["Total columns", s["columns"]],
        ["Cells filled", f"{100 - s['overall_missing_pct']:.1f}%"],
        ["Average missing % per column", f"{s['avg_missing_pct']:.1f}%"],
        ["Overall status", s["overall_status"]],
        ["Alerts (critical / warning / info)",
         f"{s['alerts']['CRITICAL']} / {s['alerts']['WARNING']} / {s['alerts']['INFO']}"],
    ])
    if s["per_dataset"]:
        lines += ["", "### Dataset status", ""]
        lines += _md_table(["Dataset", "Rows", "Columns", "Complete", "Status"],
                           [[d["name"], d["rows"], d["columns"], f"{d['completeness_pct']:.1f}%", d["status"]]
                            for d in s["per_dataset"]])
    if s["trends"]:
        lines += ["", "### Key trends", ""] + [f"- {t}" for t in s["trends"]]
    for ds in datasets:
        lines += ["", f"## {ds.name}", "",
                  f"Source: `{ds.source}` · {ds.rows:,} rows · {ds.column_count} columns · "
                  f"{ds.completeness_pct:.1f}% complete", ""]
        lines += _md_table(COLUMN_HEADERS, _column_rows(ds))
        mine = [a for a in alerts if a.dataset == ds.name]
        if mine:
            lines += ["", "**Warnings**", ""]
            lines += [f"- **{a.severity}** {a.column or '(dataset)'}: {a.message}" for a in mine]
    if charts:
        lines += ["", "## Charts", ""]
        lines += [f"![{p.stem}]({p.name})" for p in charts]
    path = out_dir / f"report_{_stamp()}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_audit_log(datasets: list[DatasetRecord], out_dir) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    s = build_summary(datasets)
    alerts = collect_alerts(datasets)
    now = datetime.now().isoformat(timespec="seconds")
    lines = [f"{APP_NAME} v{__version__} - AUDIT LOG", f"Generated: {now}", "=" * 72,
             f"Datasets: {s['datasets']}   Rows: {s['rows']}   Columns: {s['columns']}",
             f"Missing cells: {s['missing_cells']} ({s['overall_missing_pct']}%)   Status: {s['overall_status']}",
             f"Alerts: {s['alerts']['CRITICAL']} critical, {s['alerts']['WARNING']} warning, {s['alerts']['INFO']} info",
             "=" * 72]
    for ds in datasets:
        lines += ["", f"[{now}] DATASET {ds.name}  source={ds.source}  imported={ds.imported_at}",
                  f"    rows={ds.rows} columns={ds.column_count} rejected_rows={ds.skipped_rows} "
                  f"completeness={ds.completeness_pct}%"]
        for c in ds.columns:
            stats = (f" min={fmt_num(c.min)} max={fmt_num(c.max)} mean={fmt_num(c.mean)} "
                     f"median={fmt_num(c.median)}") if c.is_numeric else ""
            lines.append(f"    COLUMN {c.name:<22} type={c.dtype:<8} missing={c.missing:<4} "
                         f"({c.missing_pct:>5.1f}%) unique={c.unique}{stats}")
    lines += ["", "-" * 72, "ALERTS"]
    lines += [f"    {a.severity:<8} {a.dataset}.{a.column or '*'}: {a.message}" for a in alerts] or ["    none"]
    path = out_dir / f"audit_{_stamp()}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def export_csv_report(datasets: list[DatasetRecord], out_dir) -> Path:
    return write_profiles_csv(datasets, Path(out_dir) / f"report_{_stamp()}.csv")


def export_all(datasets: list[DatasetRecord], out_dir, with_charts: bool = True) -> list[Path]:
    """Markdown + audit log + CSV (+ charts). Returns every file written."""
    from . import plotting   # imported lazily so exports work even without matplotlib installed
    charts: list[Path] = []
    if with_charts:
        try:
            charts = plotting.generate_report_charts(datasets, out_dir)
        except ImportError:
            charts = []
    return [export_markdown(datasets, out_dir, charts), export_audit_log(datasets, out_dir),
            export_csv_report(datasets, out_dir), *charts]
