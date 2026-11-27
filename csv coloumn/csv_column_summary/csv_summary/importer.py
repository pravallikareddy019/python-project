"""Bulk dataset import with automatic format validation and a row-by-row error log."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .engine import classify_value


class ImportFailure(Exception):
    """The file cannot be imported at all (empty, undecodable, invalid JSON...)."""


@dataclass
class Issue:
    line: int          # physical line number (0 = file-level)
    severity: str      # ERROR (row rejected) | WARNING (row kept, fixed) | INFO
    message: str


@dataclass
class ImportResult:
    source: str
    headers: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    delimiter: str = ","
    encoding: str = "utf-8"

    @property
    def rejected(self) -> int:
        return sum(1 for i in self.issues if i.severity == "ERROR")

    def count(self, severity: str) -> int:
        return sum(1 for i in self.issues if i.severity == severity)


def decode_bytes(data: bytes, result: ImportResult) -> str:
    if b"\x00" in data[:4096]:
        raise ImportFailure("File looks binary (contains NUL bytes), not a text CSV.")
    try:
        text = data.decode("utf-8-sig")
        result.encoding = "utf-8"
    except UnicodeDecodeError:
        text = data.decode("latin-1")
        result.encoding = "latin-1"
        result.issues.append(Issue(0, "WARNING", "Not valid UTF-8; decoded as Latin-1."))
    return text


def detect_delimiter(text: str) -> str:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _clean_headers(raw: list[str], result: ImportResult) -> list[str]:
    headers, seen = [], {}
    for idx, cell in enumerate(raw, start=1):
        name = cell.strip()
        if not name:
            name = f"column_{idx}"
            result.issues.append(Issue(1, "WARNING", f"Empty header in position {idx}; renamed to '{name}'."))
        base, key = name, name.lower()
        if key in seen:
            seen[key] += 1
            name = f"{base}_{seen[key]}"
            result.issues.append(Issue(1, "WARNING", f"Duplicate header '{base}'; renamed to '{name}'."))
        else:
            seen[key] = 1
        headers.append(name)
    return headers


def parse_csv_text(text: str, source: str = "") -> ImportResult:
    """Parse CSV text; every problem becomes an Issue instead of an exception."""
    result = ImportResult(source=source)
    return _parse_text(text, result)


def _parse_text(text: str, result: ImportResult) -> ImportResult:
    if not text.strip():
        raise ImportFailure("The file is empty.")
    result.delimiter = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=result.delimiter)

    def next_row():
        try:
            return next(reader)
        except StopIteration:
            return None
        except csv.Error as exc:
            result.issues.append(Issue(reader.line_num, "ERROR", f"Unreadable CSV data: {exc}. Stopped reading."))
            return None

    header = next_row()
    while header is not None and not any(c.strip() for c in header):
        header = next_row()
    if header is None:
        raise ImportFailure("No header row found.")
    result.headers = _clean_headers(header, result)
    if all(classify_value(h) in ("integer", "float") for h in header if h.strip()):
        result.issues.append(Issue(1, "WARNING", "Header row looks like data (all numeric); check the first row."))
    width = len(result.headers)

    while True:
        row = next_row()
        if row is None:
            break
        line = reader.line_num
        if not any(c.strip() for c in row):
            result.issues.append(Issue(line, "INFO", "Blank row skipped."))
            continue
        if len(row) < width:
            result.issues.append(Issue(line, "WARNING", f"Row has {len(row)} of {width} cells; padded with blanks."))
            row = row + [""] * (width - len(row))
        elif len(row) > width:
            if not any(c.strip() for c in row[width:]):
                row = row[:width]
                result.issues.append(Issue(line, "WARNING", "Trailing empty cells trimmed."))
            else:
                result.issues.append(Issue(line, "ERROR", f"Row has {len(row)} cells, expected {width}; row rejected."))
                continue
        result.rows.append([c.strip() for c in row])

    if not result.rows:
        raise ImportFailure("The file has a header but no usable data rows.")
    return result


def parse_json_text(text: str, source: str = "") -> ImportResult:
    result = ImportResult(source=source, delimiter="json")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportFailure(f"Invalid JSON: {exc.msg} (line {exc.lineno}).") from exc
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        data = lists[0] if len(lists) == 1 else None
    if not isinstance(data, list) or not data:
        raise ImportFailure("JSON must be a non-empty array of objects.")
    headers: list[str] = []
    for item in data:
        if isinstance(item, dict):
            for key in item:
                if key not in headers:
                    headers.append(str(key))
    if not headers:
        raise ImportFailure("JSON array contains no objects with fields.")
    result.headers = headers
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            result.issues.append(Issue(idx, "ERROR", "Record is not an object; rejected."))
            continue
        row = []
        for key in headers:
            value = item.get(key)
            if value is None:
                row.append("")
            elif isinstance(value, bool):
                row.append("true" if value else "false")
            elif isinstance(value, (dict, list)):
                row.append(json.dumps(value))
            else:
                row.append(str(value).strip())
        result.rows.append(row)
    if not result.rows:
        raise ImportFailure("No usable JSON records.")
    return result


def import_bytes(data: bytes, filename: str) -> ImportResult:
    """Import raw file bytes (used by the GUI upload and by import_file)."""
    result = ImportResult(source=filename)
    text = decode_bytes(data, result)
    if filename.lower().endswith(".json"):
        parsed = parse_json_text(text, filename)
    else:
        parsed = _parse_text(text, result)
    # keep encoding notes found while decoding
    if parsed is not result:
        parsed.encoding = result.encoding
        parsed.issues = result.issues + parsed.issues
    return parsed


def import_file(path: str | Path) -> ImportResult:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ImportFailure(f"Cannot read file: {exc.strerror or exc}") from exc
    return import_bytes(data, str(path))


def format_issues(result: ImportResult) -> list[str]:
    lines = []
    for issue in sorted(result.issues, key=lambda i: i.line):
        where = f"Row {issue.line}" if issue.line else "File"
        lines.append(f"{where:<8} | {issue.severity:<7} | {issue.message}")
    return lines


def write_error_log(result: ImportResult, dataset_name: str, out_dir: str | Path) -> Path | None:
    """Write the row-by-row error log; returns None if there is nothing to log."""
    if not result.issues:
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in dataset_name)
    path = out_dir / f"import_log_{safe}.txt"
    header = [
        f"Import log for '{dataset_name}'",
        f"Source: {result.source}",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Delimiter: {result.delimiter!r}   Encoding: {result.encoding}",
        f"Accepted rows: {len(result.rows)}   Rejected: {result.rejected}   "
        f"Warnings: {result.count('WARNING')}",
        "-" * 70,
    ]
    path.write_text("\n".join(header + format_issues(result)) + "\n", encoding="utf-8")
    return path
