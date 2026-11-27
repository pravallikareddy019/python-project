"""Matplotlib charts (headless-safe: the Agg backend writes PNG files, no display needed)."""
from __future__ import annotations

import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import config  # noqa: E402
from .models import DatasetRecord  # noqa: E402

INK, ACCENT, OK, WATCH, BAD, MUTED = "#0E1A2B", "#3B4CCA", "#2F9E6B", "#E3A008", "#D64545", "#8A94A6"


class ChartError(ValueError):
    """The requested chart cannot be drawn for this data (message explains why)."""


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower() or "chart"


def _style(ax, title: str, xlabel: str = "", ylabel: str = "") -> None:
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK, pad=12)
    ax.set_xlabel(xlabel, color=INK)
    ax.set_ylabel(ylabel, color=INK)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(MUTED)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK)
    ax.grid(axis="y", color="#E3E7EE", linewidth=0.8)
    ax.set_axisbelow(True)


def _save(fig, out_dir, filename: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)
    return path


def numeric_columns(ds: DatasetRecord) -> list[str]:
    return [c.name for c in ds.columns if c.is_numeric and c.values]


def chart_missing(ds: DatasetRecord, out_dir) -> Path:
    """Horizontal bars: % missing per column, coloured by warning threshold."""
    if not ds.columns:
        raise ChartError("Dataset has no columns.")
    cols = list(reversed(ds.columns))
    values = [c.missing_pct for c in cols]
    colors = [BAD if v >= config.CRITICAL_MISSING_PCT else WATCH if v >= config.WARN_MISSING_PCT else OK
              for v in values]
    fig, ax = plt.subplots(figsize=(8, max(3.0, 0.42 * len(cols) + 1.4)))
    bars = ax.barh([c.name for c in cols], values, color=colors, height=0.62)
    for bar, v in zip(bars, values):
        ax.text(min(v + 1.5, 97), bar.get_y() + bar.get_height() / 2, f"{v:.1f}%", va="center", fontsize=9, color=INK)
    ax.axvline(config.WARN_MISSING_PCT, color=WATCH, linestyle="--", linewidth=1)
    ax.axvline(config.CRITICAL_MISSING_PCT, color=BAD, linestyle="--", linewidth=1)
    ax.set_xlim(0, 105)
    _style(ax, f"Missing values per column - {ds.name}", "% missing")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color="#E3E7EE", linewidth=0.8)
    return _save(fig, out_dir, f"{_slug(ds.name)}_missing.png")


def chart_types(datasets: list[DatasetRecord], out_dir, label: str = "all datasets") -> Path:
    """Bar chart of how many columns have each inferred type."""
    counts: dict[str, int] = {}
    for ds in datasets:
        for c in ds.columns:
            counts[c.dtype] = counts.get(c.dtype, 0) + 1
    if not counts:
        raise ChartError("No columns to chart.")
    items = sorted(counts.items(), key=lambda kv: -kv[1])
    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar([k for k, _ in items], [v for _, v in items], color=ACCENT, width=0.6)
    for bar, (_, v) in zip(bars, items):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.1, str(v), ha="center", fontsize=10, color=INK)
    _style(ax, f"Column types - {label}", "", "columns")
    ax.yaxis.get_major_locator().set_params(integer=True)
    name = "all" if len(datasets) != 1 else _slug(datasets[0].name)
    return _save(fig, out_dir, f"{name}_types.png")


def chart_completeness(datasets: list[DatasetRecord], out_dir) -> Path:
    """Completeness % per dataset, in import order (shows the trend across imports)."""
    if not datasets:
        raise ChartError("No datasets to chart.")
    ordered = sorted(datasets, key=lambda d: d.imported_at)
    vals = [d.completeness_pct for d in ordered]
    colors = [OK if v >= config.HEALTHY_COMPLETENESS else WATCH if v >= config.ATTENTION_COMPLETENESS else BAD
              for v in vals]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar([d.name for d in ordered], vals, color=colors, width=0.55)
    ax.plot([d.name for d in ordered], vals, color=INK, marker="o", linewidth=1.2)
    for i, v in enumerate(vals):
        ax.text(i, v + 1.5, f"{v:.1f}%", ha="center", fontsize=10, color=INK)
    ax.set_ylim(0, 112)
    _style(ax, "Completeness by dataset (import order)", "", "% of cells filled")
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
    return _save(fig, out_dir, "completeness_by_dataset.png")


def _numeric(ds: DatasetRecord, column: str):
    col = ds.column(column)
    if col is None:
        raise ChartError(f"Column '{column}' not found in {ds.name}.")
    if not col.is_numeric or not col.values:
        raise ChartError(f"Column '{column}' is {col.dtype}, not numeric - pick a numeric column.")
    return col


def chart_histogram(ds: DatasetRecord, column: str, out_dir) -> Path:
    """Distribution of a numeric column with mean and median markers."""
    col = _numeric(ds, column)
    bins = min(20, max(5, int(math.sqrt(len(col.values)))))
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.hist(col.values, bins=bins, color=ACCENT, edgecolor="white")
    ax.axvline(col.mean, color=BAD, linewidth=1.6, label=f"mean {col.mean:,.2f}")
    ax.axvline(col.median, color=OK, linewidth=1.6, linestyle="--", label=f"median {col.median:,.2f}")
    ax.legend(frameon=False)
    _style(ax, f"Distribution of {column} - {ds.name}", column, "rows")
    return _save(fig, out_dir, f"{_slug(ds.name)}_{_slug(column)}_hist.png")


def chart_trend(ds: DatasetRecord, column: str, out_dir) -> Path:
    """Trend of a numeric column in row order with a rolling mean."""
    col = _numeric(ds, column)
    values = col.values
    if len(values) < 3:
        raise ChartError("Need at least 3 numeric values for a trend chart.")
    window = max(3, len(values) // 8)
    rolling = [sum(values[max(0, i - window + 1): i + 1]) / len(values[max(0, i - window + 1): i + 1])
               for i in range(len(values))]
    xs = list(range(1, len(values) + 1))
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot(xs, values, color=MUTED, marker="o", markersize=3, linewidth=1, label="value")
    ax.plot(xs, rolling, color=ACCENT, linewidth=2.2, label=f"rolling mean ({window})")
    ax.axhline(col.mean, color=BAD, linestyle="--", linewidth=1, label=f"overall mean {col.mean:,.2f}")
    ax.legend(frameon=False)
    _style(ax, f"Trend of {column} by row - {ds.name}", "row (non-missing values)", column)
    return _save(fig, out_dir, f"{_slug(ds.name)}_{_slug(column)}_trend.png")


def generate_report_charts(datasets: list[DatasetRecord], out_dir) -> list[Path]:
    """All standard charts for an export: missing/type per dataset, completeness, one trend each."""
    paths: list[Path] = []
    for ds in datasets:
        paths.append(chart_missing(ds, out_dir))
        nums = numeric_columns(ds)
        if nums:
            paths.append(chart_histogram(ds, nums[0], out_dir))
            if len(ds.column(nums[0]).values) >= 3:
                paths.append(chart_trend(ds, nums[0], out_dir))
    if datasets:
        paths.append(chart_types(datasets, out_dir))
        paths.append(chart_completeness(datasets, out_dir))
    return paths
