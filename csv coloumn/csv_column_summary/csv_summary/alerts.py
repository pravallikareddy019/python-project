"""Threshold warning indicators (missing data, anomalies, mixed types, stale dates)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import config
from .engine import fmt_num
from .models import DatasetRecord

SEVERITIES = ("CRITICAL", "WARNING", "INFO")


@dataclass(frozen=True)
class Alert:
    severity: str
    dataset: str
    column: str
    code: str
    message: str


def dataset_alerts(ds: DatasetRecord, today: datetime | None = None) -> list[Alert]:
    today = today or datetime.now()
    out: list[Alert] = []

    def add(sev, col, code, msg):
        out.append(Alert(sev, ds.name, col, code, msg))

    if ds.rows == 0:
        add("CRITICAL", "", "no_rows", "Dataset has no rows.")
    if ds.skipped_rows:
        add("WARNING", "", "rejected_rows", f"{ds.skipped_rows} row(s) were rejected during import.")

    for c in ds.columns:
        if c.total and c.missing == c.total:
            add("CRITICAL", c.name, "all_missing", "Column is entirely empty.")
        elif c.missing_pct >= config.CRITICAL_MISSING_PCT:
            add("CRITICAL", c.name, "missing_critical",
                f"{c.missing_pct:.1f}% missing ({c.missing}/{c.total}) - above {config.CRITICAL_MISSING_PCT:.0f}% limit.")
        elif c.missing_pct >= config.WARN_MISSING_PCT:
            add("WARNING", c.name, "missing_high",
                f"{c.missing_pct:.1f}% missing ({c.missing}/{c.total}) - above {config.WARN_MISSING_PCT:.0f}% limit.")

        if c.dtype == "mixed":
            parts = ", ".join(f"{k}: {v}" for k, v in sorted(c.type_counts.items(), key=lambda kv: -kv[1]))
            add("WARNING", c.name, "mixed_types", f"Mixed value types ({parts}).")

        if c.outliers:
            add("WARNING", c.name, "outliers",
                f"{c.outliers} outlier value(s) outside the IQR range "
                f"(min {fmt_num(c.min)}, max {fmt_num(c.max)}, Q1 {fmt_num(c.q1)}, Q3 {fmt_num(c.q3)}).")

        if c.present > 1 and c.unique == 1 and c.dtype != "empty":
            add("INFO", c.name, "constant", "Every non-missing value is identical (constant column).")

        if c.dtype == "date" and c.max:
            try:
                age = (today - datetime.fromisoformat(c.max)).days
            except ValueError:
                age = 0
            if age > config.STALE_DATE_DAYS:
                add("INFO", c.name, "stale_dates", f"Newest date is {age} days old ({c.max}).")
    return out


def collect_alerts(datasets: list[DatasetRecord], today: datetime | None = None) -> list[Alert]:
    alerts = [a for ds in datasets for a in dataset_alerts(ds, today)]
    return sorted(alerts, key=lambda a: (SEVERITIES.index(a.severity), a.dataset, a.column))


def count_by_severity(alerts: list[Alert]) -> dict:
    return {sev: sum(1 for a in alerts if a.severity == sev) for sev in SEVERITIES}
