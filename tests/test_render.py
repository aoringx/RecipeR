from reciper.models import Ingredient, InstructionStep, Recipe
from reciper.render import render_recipe


def sample_recipe(*, with_tips: bool = True) -> Recipe:
    return Recipe(
        title="Detailed Test Loaf",
        ingredients=[
            Ingredient(
                amount="3 1/4 cups (406 g)",
                name="bread flour",
                details="spooned and leveled",
                display_text="3 1/4 cups (406 g) bread flour, spooned and leveled",
            ),
            Ingredient(
                amount="1–2 teaspoons",
                name="sea salt",
                details="to taste",
                display_text="1–2 teaspoons fine sea salt, to taste",
            ),
        ],
        instructions=[
            InstructionStep(
                text="Preheat the oven to 450°F (232°C) for at least 30 minutes.",
                time="at least 30 minutes",
                temperature="450°F (232°C)",
            ),
            InstructionStep(
                text="Bake for 20–25 minutes, until the crust is deeply browned.",
                time="20–25 minutes",
                temperature=None,
            ),
        ],
        tips=["Cool completely before slicing so the crumb can set."] if with_tips else [],
    )


def test_render_recipe_has_requested_section_order_and_formatting() -> None:
    result = render_recipe(sample_recipe(), source_url="https://example.test/loaf")

    assert result == (
        "Detailed Test Loaf\n"
        "==================\n"
        "Source: https://example.test/loaf\n"
        "\n"
        "INGREDIENTS\n"
        "  - 3 1/4 cups (406 g) bread flour, spooned and leveled\n"
        "  - 1–2 teaspoons fine sea salt, to taste\n"
        "\n"
        "INSTRUCTIONS\n"
        "  1. Preheat the oven to 450°F (232°C) for at least 30 minutes.\n"
        "  2. Bake for 20–25 minutes, until the crust is deeply browned.\n"
        "\n"
        "TIPS\n"
        "  - Cool completely before slicing so the crumb can set.\n"
    )


def test_render_recipe_omits_empty_tips_section() -> None:
    result = render_recipe(sample_recipe(with_tips=False), source_url="https://example.test")
    assert "\nTIPS\n" not in result
    assert result.endswith("\n")


def test_render_recipe_includes_youtube_tutorial_when_available() -> None:
    result = render_recipe(
        sample_recipe(with_tips=False),
        source_url="https://example.test",
        youtube_url="https://www.youtube.com/watch?v=abc123XYZ_-",
    )

    assert (
        "Source: https://example.test\n"
        "YouTube tutorial: https://www.youtube.com/watch?v=abc123XYZ_-\n"
    ) in result


def test_render_recipe_includes_available_yield_and_timing() -> None:
    recipe = sample_recipe(with_tips=False).model_copy(
        update={
            "yield_text": "1 loaf",
            "prep_time": "2 hours 15 minutes",
            "cook_time": "25 minutes",
            "total_time": "3 hours 5 minutes",
        }
    )
    result = render_recipe(recipe, source_url="https://example.test")
    assert "Source: https://example.test\nYield: 1 loaf\n" in result
    assert "Prep time: 2 hours 15 minutes\n" in result
    assert "Cook time: 25 minutes\nTotal time: 3 hours 5 minutes\n" in result


def test_render_recipe_wraps_with_hanging_indentation() -> None:
    long_step = (
        "Fold the dough gently from each side while keeping every bubble intact, then cover the "
        "bowl and leave it in a warm place for exactly 45 minutes before checking it again."
    )
    recipe = sample_recipe(with_tips=False).model_copy(
        update={"instructions": [InstructionStep(text=long_step, time="45 minutes")]}
    )

    rendered = render_recipe(recipe, source_url="https://example.test")
    continuation = next(
        line for line in rendered.splitlines() if line.strip().startswith("the bowl")
    )
    assert continuation.startswith("     ")
