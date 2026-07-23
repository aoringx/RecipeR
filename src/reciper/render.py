"""Deterministic plain-text recipe formatting."""

from __future__ import annotations

import textwrap

from reciper.models import Recipe

OUTPUT_WIDTH = 88


def _wrapped(text: str, *, initial: str, subsequent: str) -> str:
    wrapper = textwrap.TextWrapper(
        width=OUTPUT_WIDTH,
        initial_indent=initial,
        subsequent_indent=subsequent,
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=True,
        drop_whitespace=True,
    )
    return wrapper.fill(text)


def render_recipe(
    recipe: Recipe,
    *,
    source_url: str,
    youtube_url: str | None = None,
) -> str:
    """Render a validated recipe in the requested section order."""

    lines = [recipe.title, "=" * len(recipe.title), f"Source: {source_url}"]
    if youtube_url:
        lines.append(f"YouTube tutorial: {youtube_url}")
    for label, value in (
        ("Yield", recipe.yield_text),
        ("Prep time", recipe.prep_time),
        ("Cook time", recipe.cook_time),
        ("Total time", recipe.total_time),
    ):
        if value:
            lines.append(f"{label}: {value}")
    lines.extend(["", "INGREDIENTS"])
    lines.extend(
        _wrapped(
            ingredient.display_text,
            initial="  - ",
            subsequent="    ",
        )
        for ingredient in recipe.ingredients
    )

    lines.extend(["", "INSTRUCTIONS"])
    for index, step in enumerate(recipe.instructions, start=1):
        prefix = f"  {index}. "
        lines.append(_wrapped(step.text, initial=prefix, subsequent=" " * len(prefix)))

    if recipe.tips:
        lines.extend(["", "TIPS"])
        lines.extend(_wrapped(tip, initial="  - ", subsequent="    ") for tip in recipe.tips)

    return "\n".join(lines).rstrip() + "\n"
