"""Terminal presentation: banner, fixed-width tables, pagination, bars and status colours."""
from __future__ import annotations

import re
import shutil
from typing import Callable, Sequence

from . import APP_NAME, __version__
from .ansi import paint

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
STATUS_COLORS = {"Healthy": "green", "Needs attention": "yellow", "Critical": "red", "No data": "grey",
                 "CRITICAL": "red", "WARNING": "yellow", "INFO": "cyan"}


def visible_len(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def term_width() -> int:
    return max(60, min(shutil.get_terminal_size((120, 24)).columns, 140))


def status(text: str) -> str:
    return paint(text, STATUS_COLORS.get(text, "grey"), "bold")


def banner() -> str:
    art = [
        r"  ____ ______   __  ____                                          ",
        r" / ___/ ___\ \ / / / ___| _   _ _ __ ___  _ __ ___   __ _ _ __ _   _ ",
        r"| |   \___ \\ V /  \___ \| | | | '_ ` _ \| '_ ` _ \ / _` | '__| | | |",
        r"| |___ ___) || |    ___) | |_| | | | | | | | | | | | (_| | |  | |_| |",
        r" \____|____/ |_|   |____/ \__,_|_| |_| |_|_| |_| |_|\__,_|_|   \__, |",
        r"                                                               |___/ ",
    ]
    lines = [paint(line, "cyan", "bold") for line in art]
    lines.append(paint(f"  {APP_NAME}  v{__version__}", "bold"))
    lines.append(paint("  Column names · data types · missing counts · numeric summaries", "grey"))
    return "\n".join(lines)


def heading(text: str) -> str:
    return "\n" + paint(f"▌ {text}", "bold", "cyan") + "\n" + paint("─" * min(len(text) + 2, term_width()), "grey")


def bar(pct: float, width: int = 20) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * pct / 100))
    colour = "green" if pct >= 95 else "yellow" if pct >= 80 else "red"
    return paint("█" * filled, colour) + paint("░" * (width - filled), "grey")


def _cut(text: str, width: int) -> str:
    return text if visible_len(text) <= width else text[: max(1, width - 1)] + "…"


def _looks_numeric(text: str) -> bool:
    return bool(re.fullmatch(r"[+-]?[\d,]*\.?\d+%?", _ANSI_RE.sub("", text).strip()))


def table(headers: Sequence[str], rows: Sequence[Sequence], max_col: int = 30) -> list[str]:
    """Fixed-width table with column separators; numeric cells right-aligned."""
    cells = [[str(c) if c is not None else "" for c in row] for row in rows]
    widths = [min(max_col, max([len(h)] + [visible_len(r[i]) for r in cells])) for i, h in enumerate(headers)]
    while sum(widths) + 3 * len(widths) + 1 > term_width() and max(widths) > 8:
        widths[widths.index(max(widths))] -= 1
    sep = "─┼─".join("─" * w for w in widths)
    out = [" " + paint(" │ ".join(h.ljust(w) for h, w in zip(headers, widths)), "bold"), " " + paint(sep, "grey")]
    for row in cells:
        parts = []
        for text, w in zip(row, widths):
            text = _cut(text, w)
            pad = w - visible_len(text)
            parts.append(" " * pad + text if _looks_numeric(text) else text + " " * pad)
        out.append(" " + paint(" │ ", "grey").join(parts))
    return out


def paginate(lines: list[str], reader: Callable[[str], str], page_size: int = 15,
             printer: Callable[[str], None] = print) -> None:
    """Print lines in pages; the reader decides how to wait (Enter = next page, q = stop)."""
    for start in range(0, len(lines), page_size):
        chunk = lines[start:start + page_size]
        for line in chunk:
            printer(line)
        end = start + len(chunk)
        if end < len(lines):
            answer = reader(paint(f"  -- {end}/{len(lines)} lines · Enter for more, q to stop -- ", "grey"))
            if answer.strip().lower() == "q":
                break
