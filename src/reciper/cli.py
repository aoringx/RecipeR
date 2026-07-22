"""RecipeR command-line interface."""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from reciper.config import Settings, load_environment
from reciper.errors import RecipeRError
from reciper.extract import RecipeExtractor
from reciper.fetch import WebFetcher
from reciper.normalize import OpenAIRecipeNormalizer
from reciper.pipeline import RecipePipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reciper",
        description=(
            "Extract a recipe webpage, normalize it with OpenAI, and write a readable TXT file."
        ),
    )
    parser.add_argument("url", help="Public http:// or https:// recipe webpage URL")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output .txt file (default: outputs/<recipe-title>.txt)",
    )
    parser.add_argument(
        "--model",
        help="OpenAI model override (otherwise OPENAI_MODEL or the project default)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the output file if it already exists",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show a traceback for unexpected failures",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_environment()
        settings = Settings.from_environment(args.model)
        normalizer = OpenAIRecipeNormalizer(model=settings.model)
        with WebFetcher() as fetcher:
            pipeline = RecipePipeline(
                fetcher=fetcher,
                extractor=RecipeExtractor(),
                normalizer=normalizer,
            )
            destination = pipeline.run(
                args.url,
                output=args.output,
                overwrite=args.overwrite,
            )
    except RecipeRError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if args.debug:
            traceback.print_exc()
        return exc.exit_code
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - final CLI safety net
        print(f"Error: unexpected failure ({type(exc).__name__}).", file=sys.stderr)
        if args.debug:
            traceback.print_exc()
        return 1

    print(destination.resolve())
    return 0
