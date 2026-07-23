"""End-to-end webpage-to-text orchestration and safe output writing."""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from contextlib import suppress
from pathlib import Path

from reciper.errors import OutputError
from reciper.extract import RecipeExtractor
from reciper.fetch import WebFetcher
from reciper.normalize import RecipeNormalizer
from reciper.render import render_recipe


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug[:80].rstrip("-") or "recipe"


def _output_path(requested: Path | None, *, title: str) -> Path:
    if requested is None:
        return Path("outputs") / f"{slugify(title)}.txt"
    if requested.exists() and requested.is_dir():
        raise OutputError("The output path points to a directory; provide a .txt filename.")
    if requested.suffix and requested.suffix.casefold() != ".txt":
        raise OutputError("The output filename must end in .txt.")
    return requested if requested.suffix else requested.with_suffix(".txt")


def write_text_atomic(path: Path, content: str, *, overwrite: bool) -> None:
    """Write UTF-8 text atomically, refusing replacement unless explicitly allowed."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(f"Could not create the output directory: {path.parent}") from exc

    if path.exists() and not overwrite:
        raise OutputError(f"The output file already exists: {path}. Use --overwrite to replace it.")

    temporary_name: str | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

        if overwrite:
            os.replace(temporary_name, path)
            temporary_name = None
        else:
            try:
                os.link(temporary_name, path)
            except FileExistsError as exc:
                raise OutputError(
                    f"The output file already exists: {path}. Use --overwrite to replace it."
                ) from exc
    except OutputError:
        raise
    except OSError as exc:
        raise OutputError(f"Could not write the output file: {path}") from exc
    finally:
        if temporary_name:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)


class RecipePipeline:
    def __init__(
        self,
        *,
        fetcher: WebFetcher,
        extractor: RecipeExtractor,
        normalizer: RecipeNormalizer,
    ) -> None:
        self._fetcher = fetcher
        self._extractor = extractor
        self._normalizer = normalizer

    def run(
        self,
        url: str,
        *,
        output: Path | None = None,
        overwrite: bool = False,
    ) -> Path:
        page = self._fetcher.fetch(url)
        source = self._extractor.extract(page)
        recipe = self._normalizer.normalize(source)
        destination = _output_path(output, title=recipe.title)
        rendered = render_recipe(
            recipe,
            source_url=source.source_url,
            youtube_url=source.youtube_url,
        )
        write_text_atomic(destination, rendered, overwrite=overwrite)
        return destination
