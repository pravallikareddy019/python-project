"""Core logic engine: type inference, missing counts and numeric summaries (stdlib only)."""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from datetime import datetime

from . import config
from .models import ColumnProfile, DatasetRecord

_INT_RE = re.compile(r"^[+-]?\d+$")
_INT_COMMA_RE = re.compile(r"^[+-]?\d{1,3}(,\d{3})+$")


def is_missing(value) -> bool:
    """True for None, blanks and common 'no data' markers (NA, null, NaN, -, ...)."""
    return value is None or str(value).strip().lower() in config.MISSING_TOKENS


def parse_date(text: str) -> datetime | None:
    s = str(text).strip()
    for fmt in config.DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def to_number(text: str) -> float | None:
    """Parse int/float text (thousands commas allowed). Returns None if not a finite number."""
    s = str(text).strip()
    if _INT_COMMA_RE.match(s):
        s = s.replace(",", "")
    if _INT_RE.match(s):
        return float(int(s))
    try:
        number = float(s)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def classify_value(raw) -> str:
    """Return one of: missing, boolean, integer, float, date, text."""
    if is_missing(raw):
        return "missing"
    s = str(raw).strip()
    if s.lower() in config.BOOLEAN_TOKENS:
        return "boolean"
    if _INT_RE.match(s) or _INT_COMMA_RE.match(s):
        return "integer"
    if to_number(s) is not None:
        return "float"
    if parse_date(s) is not None:
        return "date"
    return "text"


def infer_dtype(type_counts: dict) -> str:
    kinds = {k for k, c in type_counts.items() if c > 0 and k != "missing"}
    if not kinds:
        return "empty"
    if len(kinds) == 1:
        return next(iter(kinds))
    if kinds <= {"integer", "float"}:
        return "float"
    return "mixed"


def numeric_summary(numbers: list[float]) -> dict:
    """min, max, mean, median, stdev, quartiles and IQR-rule outlier count."""
    if not numbers:
        return {}
    ordered = sorted(numbers)
    n = len(ordered)
    if n >= 2:
        q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
        stdev = statistics.stdev(ordered)
    else:
        q1 = q3 = ordered[0]
        stdev = 0.0
    iqr = q3 - q1
    outliers = 0
    if n >= 4 and iqr > 0:
        lo = q1 - config.OUTLIER_IQR_FACTOR * iqr
        hi = q3 + config.OUTLIER_IQR_FACTOR * iqr
        outliers = sum(1 for x in ordered if x < lo or x > hi)
    return {
        "min": ordered[0], "max": ordered[-1],
        "mean": round(statistics.fmean(ordered), 4),
        "median": round(statistics.median(ordered), 4),
        "stdev": round(stdev, 4),
        "q1": round(q1, 4), "q3": round(q3, 4),
        "outliers": outliers,
    }


def _sample_values(values: list[float]) -> list[float]:
    cap = config.MAX_STORED_VALUES
    if len(values) <= cap:
        return [round(v, 6) for v in values]
    step = len(values) / cap
    return [round(values[int(i * step)], 6) for i in range(cap)]


def profile_column(name: str, position: int, raw_values: list) -> ColumnProfile:
    """Build the profile of one column from its raw cell values."""
    counts: Counter = Counter()
    present: list[str] = []
    numbers: list[float] = []
    dates: list[datetime] = []
    for raw in raw_values:
        kind = classify_value(raw)
        counts[kind] += 1
        if kind == "missing":
            continue
        text = str(raw).strip()
        present.append(text)
        if kind in ("integer", "float"):
            numbers.append(to_number(text))
        elif kind == "date":
            dates.append(parse_date(text))

    total = len(raw_values)
    missing = counts.pop("missing", 0)
    dtype = infer_dtype(counts)
    profile = ColumnProfile(
        name=name, position=position, dtype=dtype, total=total, missing=missing,
        unique=len(set(present)),
        missing_pct=round(100.0 * missing / total, 2) if total else 0.0,
        type_counts=dict(counts),
    )

    # Numeric stats for numeric columns, and for mixed columns that are mostly numeric.
    if numbers and (dtype in ("integer", "float") or len(numbers) * 2 >= len(present)):
        summary = numeric_summary(numbers)
        for key, value in summary.items():
            setattr(profile, key, value)
        profile.values = _sample_values(numbers)
    elif dates:
        profile.min = min(dates).date().isoformat()
        profile.max = max(dates).date().isoformat()

    if not profile.is_numeric:
        profile.top_values = [[v, c] for v, c in Counter(present).most_common(config.TOP_VALUES)]
    return profile


def profile_dataset(name: str, headers: list[str], rows: list[list[str]],
                    source: str = "", skipped_rows: int = 0) -> DatasetRecord:
    """Profile every column of a table (rows must already be padded to len(headers))."""
    columns = []
    for idx, header in enumerate(headers):
        values = [row[idx] if idx < len(row) else "" for row in rows]
        columns.append(profile_column(header, idx, values))
    return DatasetRecord(
        name=name, source=source,
        imported_at=datetime.now().isoformat(timespec="seconds"),
        rows=len(rows), columns=columns, skipped_rows=skipped_rows,
        preview=[list(map(str, r)) for r in rows[: config.PREVIEW_ROWS]],
    )


def fmt_num(value, digits: int = 2) -> str:
    """Human-friendly number formatting for tables ('' for None)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if float(value).is_integer() and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.{digits}f}"
