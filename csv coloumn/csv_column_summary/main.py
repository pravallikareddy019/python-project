#!/usr/bin/env python3
"""CSV Column Summary Tool - main entry point.

    python main.py                 terminal app (menu-driven)
    python main.py --gui           Streamlit GUI (opens in your browser)
    python main.py --help          all options

Options such as --data-dir, --export-dir and --no-color are passed to the terminal app.
For the GUI, --data-dir / --export-dir are honoured too.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run_gui(data_dir: Path | None, export_dir: Path | None) -> int:
    if importlib.util.find_spec("streamlit") is None:
        print("The GUI needs Streamlit. Install it with:  pip install -r requirements.txt\n"
              "You can still use the terminal app:       python main.py")
        return 1
    env = dict(os.environ)
    if data_dir:
        env["CSV_SUMMARY_DATA_DIR"] = str(data_dir.resolve())
    if export_dir:
        env["CSV_SUMMARY_EXPORT_DIR"] = str(export_dir.resolve())
    cmd = [sys.executable, "-m", "streamlit", "run", str(ROOT / "gui_app.py")]
    try:
        return subprocess.call(cmd, cwd=ROOT, env=env)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CSV Column Summary Tool", add_help=False)
    parser.add_argument("--gui", action="store_true", help="launch the Streamlit GUI instead of the terminal app")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("-h", "--help", action="store_true")
    args, rest = parser.parse_known_args(argv)

    if args.gui:
        return run_gui(args.data_dir, args.export_dir)

    sys.path.insert(0, str(ROOT))
    import app                       # terminal application

    forwarded = list(rest)
    if args.data_dir:
        forwarded += ["--data-dir", str(args.data_dir)]
    if args.export_dir:
        forwarded += ["--export-dir", str(args.export_dir)]
    if args.help:
        print("usage: python main.py [--gui] [--data-dir DIR] [--export-dir DIR] [--no-color]\n\n"
              "  (no flag)      run the terminal menu app\n"
              "  --gui          launch the Streamlit GUI in your browser\n"
              "  --data-dir     folder holding store.json (default: ./data)\n"
              "  --export-dir   folder for reports and charts (default: ./exports)\n"
              "  --no-color     disable ANSI colours in the terminal app")
        return 0
    return app.main(forwarded)


if __name__ == "__main__":
    sys.exit(main())
