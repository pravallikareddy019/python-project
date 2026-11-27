"""Tiny ANSI colour helper. Colours can be switched off globally (--no-color / pipes)."""
from __future__ import annotations

import os
import sys

_CODES = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
    "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m", "grey": "\033[90m",
}
_enabled = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)


def enabled() -> bool:
    return _enabled


def paint(text: str, *styles: str) -> str:
    if not _enabled or not styles:
        return str(text)
    prefix = "".join(_CODES[s] for s in styles)
    return f"{prefix}{text}{_CODES['reset']}"
