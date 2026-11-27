"""Defensive input validation.

Two layers:
* pure validators (``validate_*``) that return a clean value or raise ValidationError -
  shared by the terminal app and the GUI;
* ``ask_*`` wrappers that loop until the person types something valid - the terminal
  never crashes on blank, non-numeric or out-of-range input.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable

from . import config
from .ansi import paint

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_NAME_RE = re.compile(r"^[\w][\w .\-]*$", re.UNICODE)

_input = input   # indirection so tests can script the keyboard


class ValidationError(ValueError):
    """Input rejected; the message explains how to fix it."""


class UserAbort(Exception):
    """Input stream closed (Ctrl-D / end of piped input)."""


# --------------------------------------------------------------------------- pure validators
def sanitize(text) -> str:
    """Strip control characters and surrounding whitespace."""
    return _CONTROL_RE.sub("", str(text if text is not None else "")).strip()


def validate_int(text, lo: int | None = None, hi: int | None = None) -> int:
    s = sanitize(text)
    if not s:
        raise ValidationError("Please enter a whole number.")
    try:
        value = int(s)
    except ValueError:
        raise ValidationError(f"'{s}' is not a whole number.") from None
    _check_range(value, lo, hi)
    return value


def validate_float(text, lo: float | None = None, hi: float | None = None) -> float:
    s = sanitize(text)
    if not s:
        raise ValidationError("Please enter a number.")
    try:
        value = float(s)
    except ValueError:
        raise ValidationError(f"'{s}' is not a number.") from None
    if value != value or value in (float("inf"), float("-inf")):
        raise ValidationError("Number must be finite.")
    _check_range(value, lo, hi)
    return value


def _check_range(value, lo, hi) -> None:
    if lo is not None and value < lo:
        raise ValidationError(f"Value must be at least {lo}.")
    if hi is not None and value > hi:
        raise ValidationError(f"Value must be at most {hi}.")


def validate_text(text, min_len: int = 1, max_len: int = 200, pattern: re.Pattern | None = None,
                  label: str = "Value") -> str:
    s = sanitize(text)
    if len(s) < min_len:
        raise ValidationError(f"{label} cannot be blank." if min_len else f"{label} is too short.")
    if len(s) > max_len:
        raise ValidationError(f"{label} must be at most {max_len} characters.")
    if pattern is not None and not pattern.match(s):
        raise ValidationError(f"{label} contains characters that are not allowed.")
    return s


def validate_dataset_name(text) -> str:
    return validate_text(text, 1, config.MAX_NAME_LEN, _NAME_RE, "Dataset name")


def validate_column_name(text) -> str:
    return validate_text(text, 1, config.MAX_NAME_LEN, None, "Column name")


def validate_file_path(text, extensions: Iterable[str] = (".csv", ".json")) -> Path:
    s = sanitize(text).strip("\"'")
    if not s:
        raise ValidationError("Please enter a file path.")
    path = Path(s).expanduser()
    if not path.exists():
        raise ValidationError(f"File not found: {path}")
    if not path.is_file():
        raise ValidationError("That path is a folder, not a file.")
    if path.suffix.lower() not in tuple(extensions):
        raise ValidationError(f"Unsupported file type '{path.suffix}'. Use: {', '.join(extensions)}")
    size = path.stat().st_size
    if size == 0:
        raise ValidationError("That file is empty.")
    if size > config.MAX_FILE_MB * 1024 * 1024:
        raise ValidationError(f"File is larger than {config.MAX_FILE_MB} MB.")
    return path


# --------------------------------------------------------------------------- prompting layer
def read_line(prompt: str = "") -> str:
    try:
        return _input(prompt)
    except EOFError:
        raise UserAbort() from None


def ask(prompt: str, validator: Callable[[str], object], default=None):
    """Loop until ``validator`` accepts the answer. Blank answer uses ``default`` if given."""
    shown = f"{prompt} [{default}]: " if default not in (None, "") else f"{prompt}: "
    while True:
        raw = read_line(shown)
        if default is not None and not sanitize(raw):
            raw = str(default)
        try:
            return validator(raw)
        except ValidationError as exc:
            print(paint(f"  ✗ {exc}", "red"))


def ask_menu_choice(prompt: str, valid: Iterable[str]) -> str:
    options = {str(v).lower(): str(v) for v in valid}

    def check(raw: str) -> str:
        key = sanitize(raw).lower()
        if key not in options:
            raise ValidationError(f"Choose one of: {', '.join(options.values())}.")
        return options[key]
    return ask(prompt, check)


def ask_int(prompt: str, lo: int | None = None, hi: int | None = None, default=None) -> int:
    return ask(prompt, lambda raw: validate_int(raw, lo, hi), default)


def ask_float(prompt: str, lo: float | None = None, hi: float | None = None, default=None) -> float:
    return ask(prompt, lambda raw: validate_float(raw, lo, hi), default)


def ask_string(prompt: str, validator: Callable[[str], str] = validate_text, default=None) -> str:
    return ask(prompt, validator, default)


def ask_optional(prompt: str, validator: Callable[[str], object]):
    """Blank answer returns None."""
    def check(raw: str):
        return None if not sanitize(raw) else validator(raw)
    return ask(prompt, check)


def ask_yes_no(prompt: str, default: bool | None = None) -> bool:
    hint = {None: "y/n", True: "Y/n", False: "y/N"}[default]

    def check(raw: str) -> bool:
        s = sanitize(raw).lower()
        if not s and default is not None:
            return default
        if s in ("y", "yes"):
            return True
        if s in ("n", "no"):
            return False
        raise ValidationError("Please answer y or n.")
    return ask(f"{prompt} ({hint})", check)


def ask_choice(prompt: str, options: list[str]) -> str:
    """Pick from a list by number or by (case-insensitive) name."""
    def check(raw: str) -> str:
        s = sanitize(raw)
        if s.isdigit() and 1 <= int(s) <= len(options):
            return options[int(s) - 1]
        for opt in options:
            if opt.lower() == s.lower():
                return opt
        raise ValidationError(f"Enter a number 1-{len(options)} or a name from the list.")
    return ask(prompt, check)


def ask_path(prompt: str, extensions: Iterable[str] = (".csv", ".json")) -> Path:
    exts = tuple(extensions)
    return ask(prompt, lambda raw: validate_file_path(raw, exts))
