"""Local JSON persistence with schema checks and corruption recovery (+ flat CSV mirror)."""
from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from . import config
from .models import DatasetRecord

PROFILE_CSV_COLUMNS = [
    "dataset", "column", "position", "type", "rows", "missing", "missing_pct", "unique",
    "min", "max", "mean", "median", "stdev", "q1", "q3", "outliers",
]


class SchemaError(ValueError):
    pass


def profile_rows(datasets: list[DatasetRecord]) -> list[list]:
    """Flat, one-row-per-column representation (CSV report / mirror / tables)."""
    rows = []
    for ds in datasets:
        for c in ds.columns:
            rows.append([ds.name, c.name, c.position + 1, c.dtype, c.total, c.missing, c.missing_pct,
                         c.unique, c.min, c.max, c.mean, c.median, c.stdev, c.q1, c.q3, c.outliers])
    return rows


def write_profiles_csv(datasets: list[DatasetRecord], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(PROFILE_CSV_COLUMNS)
        for row in profile_rows(datasets):
            writer.writerow(["" if v is None else v for v in row])
    return path


def _validate_schema(data) -> list:
    if not isinstance(data, dict):
        raise SchemaError("top level must be an object")
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise SchemaError("missing schema_version")
    if version > config.SCHEMA_VERSION:
        raise SchemaError(f"store was written by a newer version (schema {version})")
    datasets = data.get("datasets")
    if not isinstance(datasets, list):
        raise SchemaError("'datasets' must be a list")
    return datasets


class Store:
    """All profiled datasets, persisted as JSON so they survive restarts."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else config.store_file()
        self.datasets: list[DatasetRecord] = []
        self.notes: list[str] = []

    # ---- loading -----------------------------------------------------------------
    def load(self) -> "Store":
        self.notes = []
        self.datasets = []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            raw = _validate_schema(data)
        except FileNotFoundError:
            self.notes.append("No data file found - starting with an empty store.")
            self.save()
        except (json.JSONDecodeError, UnicodeDecodeError, SchemaError, OSError) as exc:
            backup = self._backup()
            where = f" Backup saved as {backup.name}." if backup else ""
            self.notes.append(f"Data file was unreadable ({exc}).{where} Started a clean store.")
            self.save()
        else:
            for idx, item in enumerate(raw, start=1):
                try:
                    self.datasets.append(DatasetRecord.from_dict(item))
                except (ValueError, KeyError, TypeError) as exc:
                    self.notes.append(f"Skipped invalid dataset #{idx}: {exc}")
        return self

    def _backup(self) -> Path | None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = self.path.with_name(f"{self.path.stem}.corrupt-{stamp}.bak")
        try:
            shutil.copy2(self.path, target)
            return target
        except OSError:
            return None

    # ---- saving ------------------------------------------------------------------
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": config.SCHEMA_VERSION,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "datasets": [d.to_dict() for d in self.datasets],
        }
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=1)
            os.replace(tmp, self.path)          # atomic: never leaves a half-written file
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        write_profiles_csv(self.datasets, self.path.with_name("column_profiles.csv"))

    # ---- records -----------------------------------------------------------------
    def names(self) -> list[str]:
        return [d.name for d in self.datasets]

    def get(self, name: str) -> DatasetRecord | None:
        for ds in self.datasets:
            if ds.name.lower() == name.lower():
                return ds
        return None

    def upsert(self, record: DatasetRecord) -> bool:
        """Add or replace (same name, case-insensitive). Saves. Returns True if replaced."""
        existing = self.get(record.name)
        replaced = existing is not None
        if replaced:
            self.datasets[self.datasets.index(existing)] = record
        else:
            self.datasets.append(record)
        self.save()
        return replaced

    def remove(self, name: str) -> bool:
        existing = self.get(name)
        if existing is None:
            return False
        self.datasets.remove(existing)
        self.save()
        return True
