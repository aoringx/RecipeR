from pathlib import Path

import pytest

from reciper.errors import OutputError
from reciper.extract import RecipeExtractor
from reciper.fetch import FetchedPage
from reciper.models import Ingredient, InstructionStep, Recipe
from reciper.pipeline import RecipePipeline, slugify, write_text_atomic

HTML = """
<html><head><title>Fallback title</title>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Recipe",
  "name": "Simple & Detailed Bread",
  "video": {"@type": "VideoObject", "url": "https://youtu.be/abc123XYZ_-"},
  "recipeIngredient": ["2 cups (250 g) flour"],
  "recipeInstructions": [{"@type": "HowToStep", "text": "Bake at 400°F for 25 minutes."}]
}
</script></head><body><article>
<p>A short recipe article with enough useful context.</p>
</article></body></html>
"""


class FakeFetcher:
    def fetch(self, url: str) -> FetchedPage:
        return FetchedPage(requested_url=url, final_url="https://example.test/bread", html=HTML)


class FakeNormalizer:
    def __init__(self) -> None:
        self.received = None

    def normalize(self, source: object) -> Recipe:
        self.received = source
        return Recipe(
            title="Simple & Detailed Bread",
            ingredients=[
                Ingredient(
                    amount="2 cups (250 g)",
                    name="flour",
                    details=None,
                    display_text="2 cups (250 g) flour",
                )
            ],
            instructions=[
                InstructionStep(
                    text="Bake at 400°F for 25 minutes.",
                    time="25 minutes",
                    temperature="400°F",
                )
            ],
            tips=[],
        )


def test_pipeline_runs_end_to_end_with_injected_normalizer(tmp_path: Path) -> None:
    normalizer = FakeNormalizer()
    pipeline = RecipePipeline(
        fetcher=FakeFetcher(),  # type: ignore[arg-type]
        extractor=RecipeExtractor(),
        normalizer=normalizer,
    )
    requested = tmp_path / "my-recipe"

    destination = pipeline.run("https://example.test/bread", output=requested)

    assert destination == tmp_path / "my-recipe.txt"
    assert destination.read_text(encoding="utf-8").startswith("Simple & Detailed Bread\n")
    assert "INGREDIENTS\n  - 2 cups (250 g) flour" in destination.read_text(encoding="utf-8")
    assert (
        "YouTube tutorial: https://www.youtube.com/watch?v=abc123XYZ_-"
        in destination.read_text(encoding="utf-8")
    )
    assert normalizer.received.ingredient_lines == ["2 cups (250 g) flour"]


def test_pipeline_refuses_to_overwrite_by_default(tmp_path: Path) -> None:
    pipeline = RecipePipeline(
        fetcher=FakeFetcher(),  # type: ignore[arg-type]
        extractor=RecipeExtractor(),
        normalizer=FakeNormalizer(),
    )
    output = tmp_path / "recipe.txt"
    output.write_text("keep me", encoding="utf-8")

    with pytest.raises(OutputError, match="already exists"):
        pipeline.run("https://example.test/bread", output=output)

    assert output.read_text(encoding="utf-8") == "keep me"


def test_atomic_writer_overwrites_only_when_requested(tmp_path: Path) -> None:
    output = tmp_path / "recipe.txt"
    write_text_atomic(output, "first\n", overwrite=False)
    with pytest.raises(OutputError):
        write_text_atomic(output, "second\n", overwrite=False)
    write_text_atomic(output, "second\n", overwrite=True)
    assert output.read_text(encoding="utf-8") == "second\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_slugify_is_safe_and_bounded() -> None:
    assert slugify("  Crème brûlée / Loaf! ") == "creme-brulee-loaf"
    assert slugify("💡") == "recipe"
    assert len(slugify("a" * 200)) == 80


def test_pipeline_rejects_non_txt_output(tmp_path: Path) -> None:
    pipeline = RecipePipeline(
        fetcher=FakeFetcher(),  # type: ignore[arg-type]
        extractor=RecipeExtractor(),
        normalizer=FakeNormalizer(),
    )
    with pytest.raises(OutputError, match="must end in .txt"):
        pipeline.run("https://example.test/bread", output=tmp_path / "recipe.md")
