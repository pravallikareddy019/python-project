"""Central configuration: paths, thresholds and constants."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1

# Values treated as "missing" (compared case-insensitively after stripping).
MISSING_TOKENS = frozenset({"", "na", "n/a", "#n/a", "nan", "null", "none", "-", "--", "?"})
BOOLEAN_TOKENS = frozenset({"true", "false", "yes", "no"})
DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
)

# Threshold warning levels
WARN_MISSING_PCT = 20.0
CRITICAL_MISSING_PCT = 50.0
OUTLIER_IQR_FACTOR = 1.5
STALE_DATE_DAYS = 365

# Dataset health (completeness %)
HEALTHY_COMPLETENESS = 95.0
ATTENTION_COMPLETENESS = 80.0

# Limits
MAX_FILE_MB = 50
MAX_STORED_VALUES = 2000      # numeric values kept per column for charts
PREVIEW_ROWS = 10
TOP_VALUES = 5
MAX_NAME_LEN = 60

SAMPLE_FILES = ("sample_data.csv", "sample_orders.csv")


def data_dir() -> Path:
    """Data directory; override with CSV_SUMMARY_DATA_DIR (used by tests)."""
    return Path(os.environ.get("CSV_SUMMARY_DATA_DIR", PROJECT_ROOT / "data"))


def export_dir() -> Path:
    return Path(os.environ.get("CSV_SUMMARY_EXPORT_DIR", PROJECT_ROOT / "exports"))


def store_file() -> Path:
    return data_dir() / "store.json"


def sample_dir() -> Path:
    return PROJECT_ROOT / "data"
