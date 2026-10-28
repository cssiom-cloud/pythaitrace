"""
PyThaiTrace v2.0 - CLI Entrypoint (cli.py)
Command-line interface: thpy <script.py> [args...]
"""
from __future__ import annotations
import os
import sys
from typing import List, Optional

from pythaitrace.hooks import configure_streams
from pythaitrace.runner import run_script

HELP_TEXT = """\
usage: thpy [-h] [-v] [script.py] [args ...]

PyThaiTrace v2.0 - Zero-crash bilingual Python developer diagnostic runner.

positional arguments:
  script.py      Target Python script to execute.
  args           Arguments passed transparently to the target script.

options:
  -h, --help     Show this help message and exit.
  -v, --version  Show program's version number and exit.
"""


def main(argv: Optional[List[str]] = None) -> int:
    """CLI main entry point for thpy."""
    configure_streams()

    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        sys.stderr.write(HELP_TEXT)
        sys.stderr.flush()
        return 0

    first_arg = argv[0]

    # Handle thpy CLI flags when no script is specified
    if first_arg in ("-h", "--help"):
        sys.stdout.write(HELP_TEXT)
        sys.stdout.flush()
        return 0

    if first_arg in ("-v", "--version"):
        sys.stdout.write("PyThaiTrace 2.0.0\n")
        sys.stdout.flush()
        return 0

    # Support POSIX '--' delimiter
    if first_arg == "--":
        if len(argv) < 2:
            sys.stderr.write(HELP_TEXT)
            sys.stderr.flush()
            return 0
        script_path = argv[1]
        script_args = argv[2:]
    else:
        script_path = first_arg
        script_args = argv[1:]

    # Validate target file exists
    if not os.path.isfile(script_path):
        sys.stderr.write(f"Error: Script '{script_path}' not found.\n")
        sys.stderr.flush()
        return 1

    return run_script(script_path, script_args)


if __name__ == "__main__":
    sys.exit(main())
