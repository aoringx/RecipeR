#!/usr/bin/env python3
"""Run RecipeR directly as a Python script."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

# Make the src-layout package importable without relying on an editable install.
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from reciper.cli import main as cli_main  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI, prompting for a recipe URL when none was supplied."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        try:
            url = input("Recipe URL: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.", file=sys.stderr)
            return 130

        if not url:
            print("Error: a recipe URL is required.", file=sys.stderr)
            return 2
        args.append(url)

    return cli_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
