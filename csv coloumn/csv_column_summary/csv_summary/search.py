"""Keyword and category based record search over column profiles."""
from __future__ import annotations

from dataclasses import dataclass

from .models import ColumnProfile, DatasetRecord


@dataclass
class SearchHit:
    dataset: DatasetRecord
    column: ColumnProfile


def search_columns(datasets: list[DatasetRecord], keyword: str = "", dtype: str | None = None,
                   dataset_name: str | None = None, min_missing_pct: float | None = None,
                   numeric_only: bool = False) -> list[SearchHit]:
    """Return column profiles matching every given filter.

    keyword  - case-insensitive; matches dataset name, column name, type, or common values
    dtype    - category filter (integer, float, boolean, date, text, mixed, empty)
    """
    words = [w for w in keyword.lower().split() if w]
    hits = []
    for ds in datasets:
        if dataset_name and ds.name.lower() != dataset_name.lower():
            continue
        for col in ds.columns:
            if dtype and col.dtype != dtype:
                continue
            if min_missing_pct is not None and col.missing_pct < min_missing_pct:
                continue
            if numeric_only and not col.is_numeric:
                continue
            if words:
                haystack = " ".join([ds.name, col.name, col.dtype,
                                     *[str(v) for v, _ in col.top_values]]).lower()
                if not all(w in haystack for w in words):
                    continue
            hits.append(SearchHit(ds, col))
    return hits


def search_datasets(datasets: list[DatasetRecord], keyword: str = "") -> list[DatasetRecord]:
    words = [w for w in keyword.lower().split() if w]
    return [d for d in datasets
            if all(w in (d.name + " " + d.source + " " + " ".join(c.name for c in d.columns)).lower()
                   for w in words)]
