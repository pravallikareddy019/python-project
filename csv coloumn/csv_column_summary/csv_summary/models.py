"""Data structures: ColumnProfile and DatasetRecord (JSON-serialisable dataclasses)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

DTYPES = ("integer", "float", "boolean", "date", "text", "mixed", "empty")


def _require(data: dict, key: str, types: tuple) -> Any:
    if key not in data:
        raise ValueError(f"missing field '{key}'")
    value = data[key]
    if isinstance(value, bool) and bool not in types:
        raise ValueError(f"field '{key}' has wrong type")
    if not isinstance(value, types):
        raise ValueError(f"field '{key}' has wrong type")
    return value


@dataclass
class ColumnProfile:
    name: str
    position: int
    dtype: str
    total: int
    missing: int
    unique: int
    missing_pct: float = 0.0
    min: Any = None
    max: Any = None
    mean: float | None = None
    median: float | None = None
    stdev: float | None = None
    q1: float | None = None
    q3: float | None = None
    outliers: int = 0
    type_counts: dict = field(default_factory=dict)
    top_values: list = field(default_factory=list)   # [[value, count], ...]
    values: list = field(default_factory=list)       # numeric values (row order, capped)

    @property
    def present(self) -> int:
        return self.total - self.missing

    @property
    def is_numeric(self) -> bool:
        return self.mean is not None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ColumnProfile":
        if not isinstance(data, dict):
            raise ValueError("column profile must be an object")
        num = (int, float)
        dtype = _require(data, "dtype", (str,))
        if dtype not in DTYPES:
            raise ValueError(f"unknown dtype '{dtype}'")
        return cls(
            name=_require(data, "name", (str,)),
            position=_require(data, "position", (int,)),
            dtype=dtype,
            total=_require(data, "total", (int,)),
            missing=_require(data, "missing", (int,)),
            unique=_require(data, "unique", (int,)),
            missing_pct=float(_require(data, "missing_pct", num)),
            min=data.get("min"), max=data.get("max"),
            mean=data.get("mean"), median=data.get("median"), stdev=data.get("stdev"),
            q1=data.get("q1"), q3=data.get("q3"),
            outliers=int(data.get("outliers", 0)),
            type_counts=dict(data.get("type_counts", {})),
            top_values=list(data.get("top_values", [])),
            values=list(data.get("values", [])),
        )


@dataclass
class DatasetRecord:
    name: str
    source: str
    imported_at: str
    rows: int
    columns: list = field(default_factory=list)      # list[ColumnProfile]
    skipped_rows: int = 0
    preview: list = field(default_factory=list)      # first rows as list[list[str]]

    @property
    def column_count(self) -> int:
        return len(self.columns)

    @property
    def total_cells(self) -> int:
        return self.rows * self.column_count

    @property
    def missing_cells(self) -> int:
        return sum(c.missing for c in self.columns)

    @property
    def missing_pct(self) -> float:
        return round(100.0 * self.missing_cells / self.total_cells, 2) if self.total_cells else 0.0

    @property
    def completeness_pct(self) -> float:
        return round(100.0 - self.missing_pct, 2) if self.total_cells else 0.0

    def column(self, name: str) -> ColumnProfile | None:
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["columns"] = [c.to_dict() for c in self.columns]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "DatasetRecord":
        if not isinstance(data, dict):
            raise ValueError("dataset must be an object")
        cols = _require(data, "columns", (list,))
        return cls(
            name=_require(data, "name", (str,)),
            source=_require(data, "source", (str,)),
            imported_at=_require(data, "imported_at", (str,)),
            rows=_require(data, "rows", (int,)),
            columns=[ColumnProfile.from_dict(c) for c in cols],
            skipped_rows=int(data.get("skipped_rows", 0)),
            preview=list(data.get("preview", [])),
        )
