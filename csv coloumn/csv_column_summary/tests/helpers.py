"""Shared test helpers."""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csv_summary import engine, importer  # noqa: E402


class Keyboard:
    """Scripted keyboard: replaces validation._input. Running dry behaves like Ctrl-D."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="csvsum_test_"))


def build(name, headers, rows, **kw):
    return engine.profile_dataset(name, headers, rows, kw.pop("source", "test"), **kw)


def sample(name):
    path = ROOT / "data" / name
    result = importer.import_file(path)
    return build(path.stem, result.headers, result.rows, source=str(path), skipped_rows=result.rejected)


class SmartKeyboard(Keyboard):
    """Auto-answers pagination / 'press Enter' pauses so scripts only hold meaningful answers."""

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        if "Enter for more" in prompt:
            return "q"
        if "Press Enter to return" in prompt:
            return ""
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)
