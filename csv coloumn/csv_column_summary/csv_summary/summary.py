"""Executive summary: totals, averages, status indicators and key trends."""
from __future__ import annotations

from collections import Counter

from . import config
from .alerts import collect_alerts
from .models import DatasetRecord


def status_for(completeness_pct: float) -> str:
    if completeness_pct >= config.HEALTHY_COMPLETENESS:
        return "Healthy"
    if completeness_pct >= config.ATTENTION_COMPLETENESS:
        return "Needs attention"
    return "Critical"


def build_summary(datasets: list[DatasetRecord]) -> dict:
    cols = [(ds, c) for ds in datasets for c in ds.columns]
    total_cells = sum(ds.total_cells for ds in datasets)
    missing_cells = sum(ds.missing_cells for ds in datasets)
    overall_missing = round(100.0 * missing_cells / total_cells, 2) if total_cells else 0.0
    alerts = collect_alerts(datasets)

    per_dataset = []
    for ds in datasets:
        crit = sum(1 for a in alerts if a.dataset == ds.name and a.severity == "CRITICAL")
        warn = sum(1 for a in alerts if a.dataset == ds.name and a.severity == "WARNING")
        status = status_for(ds.completeness_pct)
        if crit and status == "Healthy":
            status = "Needs attention"
        per_dataset.append({
            "name": ds.name, "rows": ds.rows, "columns": ds.column_count,
            "completeness_pct": ds.completeness_pct, "status": status,
            "critical": crit, "warnings": warn, "imported_at": ds.imported_at,
        })

    most_incomplete = sorted((x for x in cols if x[1].missing), key=lambda x: -x[1].missing_pct)[:5]
    variability = []
    for ds, c in cols:
        if c.is_numeric and c.mean and c.stdev is not None and c.present >= 3:
            variability.append((abs(c.stdev / c.mean), ds, c))
    variability.sort(key=lambda t: -t[0])

    summary = {
        "datasets": len(datasets),
        "rows": sum(ds.rows for ds in datasets),
        "columns": len(cols),
        "cells": total_cells,
        "missing_cells": missing_cells,
        "overall_missing_pct": overall_missing,
        "avg_missing_pct": round(sum(c.missing_pct for _, c in cols) / len(cols), 2) if cols else 0.0,
        "avg_rows": round(sum(ds.rows for ds in datasets) / len(datasets), 1) if datasets else 0.0,
        "avg_columns": round(len(cols) / len(datasets), 1) if datasets else 0.0,
        "type_distribution": dict(Counter(c.dtype for _, c in cols).most_common()),
        "complete_columns": sum(1 for _, c in cols if c.missing == 0),
        "numeric_columns": sum(1 for _, c in cols if c.is_numeric),
        "per_dataset": per_dataset,
        "most_incomplete": [{"dataset": ds.name, "column": c.name, "missing_pct": c.missing_pct}
                            for ds, c in most_incomplete],
        "most_variable": [{"dataset": ds.name, "column": c.name, "cv": round(cv, 3)}
                          for cv, ds, c in variability[:3]],
        "alerts": {s: sum(1 for a in alerts if a.severity == s) for s in ("CRITICAL", "WARNING", "INFO")},
        "overall_status": status_for(100.0 - overall_missing) if total_cells else "No data",
    }
    summary["trends"] = _trends(summary, datasets)
    return summary


def _trends(s: dict, datasets: list[DatasetRecord]) -> list[str]:
    if not datasets:
        return []
    notes = []
    ordered = sorted(datasets, key=lambda d: d.imported_at)
    if len(ordered) >= 2:
        first, last = ordered[0], ordered[-1]
        delta = round(last.completeness_pct - first.completeness_pct, 2)
        direction = "improved" if delta > 0.5 else "declined" if delta < -0.5 else "stayed steady"
        notes.append(f"Completeness {direction} across imports: {first.name} {first.completeness_pct:.1f}% "
                     f"→ {last.name} {last.completeness_pct:.1f}% ({delta:+.1f} pts).")
    worst = min(s["per_dataset"], key=lambda d: d["completeness_pct"])
    notes.append(f"Least complete dataset: {worst['name']} ({worst['completeness_pct']:.1f}% complete).")
    notes.append(f"{s['complete_columns']} of {s['columns']} columns have no missing values.")
    if s["most_incomplete"]:
        m = s["most_incomplete"][0]
        notes.append(f"Most incomplete column: {m['dataset']}.{m['column']} ({m['missing_pct']:.1f}% missing).")
    if s["most_variable"]:
        v = s["most_variable"][0]
        notes.append(f"Most variable numeric column: {v['dataset']}.{v['column']} "
                     f"(coefficient of variation {v['cv']:.2f}).")
    if s["type_distribution"]:
        kind, count = next(iter(s["type_distribution"].items()))
        notes.append(f"Most common column type: {kind} ({count} of {s['columns']} columns).")
    return notes
