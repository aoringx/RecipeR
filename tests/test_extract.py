from pathlib import Path

import pytest

from reciper.errors import ExtractionError
from reciper.extract import RecipeExtractor
from reciper.fetch import FetchedPage

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "recipe_page.html"


def test_extracts_recipe_from_json_ld_graph_with_sections_and_tips() -> None:
    page = FetchedPage(
        requested_url="https://recipes.example/bread?ref=test",
        final_url="https://recipes.example/bread",
        html=FIXTURE_PATH.read_text(encoding="utf-8"),
    )

    recipe = RecipeExtractor().extract(page)

    assert recipe.source_url == "https://recipes.example/bread"
    assert recipe.youtube_url == "https://www.youtube.com/watch?v=abc123XYZ_-"
    assert recipe.page_title == "Detailed Artisan Bread"
    assert recipe.description == "A crusty loaf with a soft center."
    assert recipe.yield_text == "1 large loaf"
    assert recipe.timing == {
        "prep_time": "2 hours 15 minutes",
        "cook_time": "30 minutes",
        "total_time": "3 hours 5 minutes",
    }
    assert recipe.ingredient_lines == [
        "3 and 1/2 cups (438g) bread flour, spooned and leveled",
        "2 teaspoons (6g) instant yeast",
        "2 teaspoons (12g) coarse salt",
        "1 and 1/2 cups (360ml) warm water (about 100–110°F / 38–43°C)",
    ]
    assert recipe.instruction_lines == [
        "Prepare the dough: Whisk the flour, yeast, and salt together in a large bowl.",
        "Prepare the dough: Stir in water until a shaggy dough forms, about 2 minutes.",
        "Bake: Preheat the oven to 475°F (246°C) for at least 30 minutes.",
        "Bake for 25–30 minutes, then cool for 20 minutes.",
    ]
    assert recipe.note_lines == [
        "Measure the flour carefully.",
        "The dough can rest in the refrigerator overnight.",
    ]
    assert recipe.tip_sections == [
        "Success Tips\n"
        "Use an instant-read thermometer to check the water temperature.\n"
        "Let the oven preheat fully before baking.\n"
        "Cool the loaf before slicing so the center can set."
    ]
    assert "Serving Ideas\nServe the bread with soup." in recipe.article_text


def test_falls_back_to_recipe_microdata_when_json_ld_is_absent() -> None:
    html = """
    <!doctype html>
    <html>
      <head><title>Microdata fallback</title></head>
      <body>
        <main itemscope itemtype="https://schema.org/Recipe">
          <h1 itemprop="name">Skillet Potatoes</h1>
          <meta
            itemprop="recipeIngredient"
            content="2 pounds (907g) Yukon Gold potatoes, cut into 1-inch pieces"
          >
          <p itemprop="recipeIngredient">2 tablespoons extra-virgin olive oil</p>
          <ol>
            <li itemprop="recipeInstructions">
              Heat the oven to 425°F (218°C) with a rack in the center.
            </li>
            <li itemprop="recipeInstructions">
              Roast for 30–35 minutes, turning once after 20 minutes.
            </li>
          </ol>
          <p itemprop="recipeNotes">Dry the potatoes well for crisp edges.</p>
        </main>
      </body>
    </html>
    """
    page = FetchedPage(
        requested_url="https://recipes.example/potatoes",
        final_url="https://recipes.example/potatoes",
        html=html,
    )

    recipe = RecipeExtractor().extract(page)

    assert recipe.page_title == "Skillet Potatoes"
    assert recipe.ingredient_lines == [
        "2 pounds (907g) Yukon Gold potatoes, cut into 1-inch pieces",
        "2 tablespoons extra-virgin olive oil",
    ]
    assert recipe.instruction_lines == [
        "Heat the oven to 425°F (218°C) with a rack in the center.",
        "Roast for 30–35 minutes, turning once after 20 minutes.",
    ]
    assert recipe.note_lines == ["Dry the potatoes well for crisp edges."]


def test_json_ld_preserves_legitimate_repeated_lines() -> None:
    html = """
    <html><head><script type="application/ld+json">
    {
      "@type": "Recipe",
      "name": "Layered Test Recipe",
      "recipeIngredient": ["1 cup water", "1 cup water"],
      "recipeInstructions": [
        {"@type": "HowToStep", "text": "Rest for 10 minutes."},
        {"@type": "HowToStep", "text": "Rest for 10 minutes."}
      ]
    }
    </script></head><body></body></html>
    """
    page = FetchedPage(
        requested_url="https://recipes.example/layers",
        final_url="https://recipes.example/layers",
        html=html,
    )

    recipe = RecipeExtractor().extract(page)

    assert recipe.ingredient_lines == ["1 cup water", "1 cup water"]
    assert recipe.instruction_lines == ["Rest for 10 minutes.", "Rest for 10 minutes."]


def test_microdata_uses_leaf_step_text_without_nested_name_contamination() -> None:
    html = """
    <html><body>
      <main itemscope itemtype="https://schema.org/Recipe">
        <h1 itemprop="name">Nested Step Soup</h1>
        <p itemprop="recipeIngredient">2 cups vegetable stock</p>
        <div itemprop="recipeInstructions">
          <div itemprop="itemListElement" itemscope itemtype="https://schema.org/HowToStep">
            <strong itemprop="name">Simmer</strong>
            <span itemprop="text">Simmer at 190°F for 15 minutes.</span>
          </div>
          <div itemprop="itemListElement" itemscope itemtype="https://schema.org/HowToStep">
            <strong itemprop="name">Finish</strong>
            <span itemprop="text">Rest for 5 minutes before serving.</span>
          </div>
        </div>
      </main>
    </body></html>
    """
    page = FetchedPage(
        requested_url="https://recipes.example/soup",
        final_url="https://recipes.example/soup",
        html=html,
    )

    recipe = RecipeExtractor().extract(page)

    assert recipe.page_title == "Nested Step Soup"
    assert recipe.instruction_lines == [
        "Simmer at 190°F for 15 minutes.",
        "Rest for 5 minutes before serving.",
    ]


def test_generic_article_without_recipe_sections_is_rejected() -> None:
    html = """
    <html><head><title>A long food story</title></head><body><article>
      <h1>Why people enjoy bread</h1>
      <p>
        This is a long general article about food history and personal memories. It contains more
        than enough text to look substantial, but it does not contain an ingredient list or a
        cooking method and therefore should never be sent to the recipe normalizer.
      </p>
    </article></body></html>
    """
    page = FetchedPage(
        requested_url="https://recipes.example/story",
        final_url="https://recipes.example/story",
        html=html,
    )

    with pytest.raises(ExtractionError, match="No usable recipe content"):
        RecipeExtractor().extract(page)


def test_empty_recipe_headings_are_not_sufficient_evidence() -> None:
    html = """
    <html><body><article>
      <h2>Ingredients</h2><p>Coming soon.</p>
      <h2>Instructions</h2><p>Coming soon.</p>
    </article></body></html>
    """
    page = FetchedPage(
        requested_url="https://recipes.example/empty",
        final_url="https://recipes.example/empty",
        html=html,
    )
    with pytest.raises(ExtractionError, match="No usable recipe content"):
        RecipeExtractor().extract(page)


def test_heading_sections_provide_a_bounded_article_fallback() -> None:
    html = """
    <html><head><title>Plain HTML Pancakes</title></head><body><article>
      <h2>Ingredients</h2>
      <ul><li>1 cup flour</li><li>1 teaspoon baking powder</li></ul>
      <h2>Directions</h2>
      <ol><li>Whisk for 2 minutes.</li><li>Cook at 350°F for 3 minutes per side.</li></ol>
    </article></body></html>
    """
    page = FetchedPage(
        requested_url="https://recipes.example/plain",
        final_url="https://recipes.example/plain",
        html=html,
    )
    recipe = RecipeExtractor().extract(page)
    assert recipe.ingredient_lines == ["1 cup flour", "1 teaspoon baking powder"]
    assert recipe.instruction_lines == [
        "Whisk for 2 minutes.",
        "Cook at 350°F for 3 minutes per side.",
    ]


def test_known_card_does_not_duplicate_nested_paragraphs() -> None:
    html = """
    <html><body><div class="recipe-card">
      <h2>Nested Card</h2>
      <ul class="ingredients"><li><p>1 cup flour</p></li></ul>
      <ol class="instructions"><li><p>Mix for 2 minutes.</p></li></ol>
    </div></body></html>
    """
    page = FetchedPage(
        requested_url="https://recipes.example/card",
        final_url="https://recipes.example/card",
        html=html,
    )
    recipe = RecipeExtractor().extract(page)
    assert recipe.ingredient_lines == ["1 cup flour"]
    assert recipe.instruction_lines == ["Mix for 2 minutes."]


def test_json_ld_is_supplemented_with_recipe_card_notes() -> None:
    html = """
    <html><head><script type="application/ld+json">
      {
        "@type": "Recipe",
        "name": "Supplemented Recipe",
        "recipeIngredient": ["1 cup flour"],
        "recipeInstructions": ["Mix for 2 minutes."]
      }
    </script></head><body>
      <div class="tasty-recipes">
        <div class="tasty-recipes-notes"><ul>
          <li>Keep the bowl covered while the dough rests.</li>
        </ul></div>
      </div>
    </body></html>
    """
    page = FetchedPage(
        requested_url="https://recipes.example/supplement",
        final_url="https://recipes.example/supplement",
        html=html,
    )
    recipe = RecipeExtractor().extract(page)
    assert recipe.note_lines == ["Keep the bowl covered while the dough rests."]


@pytest.mark.parametrize(
    ("markup", "video_id"),
    [
        ('<a href="https://youtu.be/AbCdEf123_-?si=share">Watch the tutorial</a>', "AbCdEf123_-"),
        (
            '<iframe data-lazy-src="https://www.youtube.com/embed/ZYX987abc_-?rel=0"></iframe>',
            "ZYX987abc_-",
        ),
        ('<a href="https://www.youtube.com/shorts/Qwerty123_-">Video</a>', "Qwerty123_-"),
        (
            '<meta content="https://www.youtube.com/watch?v=Watch1234_-&amp;feature=share">',
            "Watch1234_-",
        ),
    ],
)
def test_extracts_and_normalizes_youtube_video_links(markup: str, video_id: str) -> None:
    html = f"""
    <html><head><script type="application/ld+json">
      {{
        "@type": "Recipe",
        "name": "Video Recipe",
        "recipeIngredient": ["1 cup flour"],
        "recipeInstructions": ["Mix for 2 minutes."]
      }}
    </script></head><body><article>{markup}</article></body></html>
    """
    page = FetchedPage(
        requested_url="https://recipes.example/video",
        final_url="https://recipes.example/video",
        html=html,
    )

    recipe = RecipeExtractor().extract(page)

    assert recipe.youtube_url == f"https://www.youtube.com/watch?v={video_id}"


def test_ignores_youtube_channels_and_lookalike_hosts() -> None:
    html = """
    <html><head><script type="application/ld+json">
      {
        "@type": "Recipe",
        "name": "No Tutorial Recipe",
        "recipeIngredient": ["1 cup flour"],
        "recipeInstructions": ["Mix for 2 minutes."]
      }
    </script></head><body><article>
      <a href="https://www.youtube.com/@example">Our channel</a>
      <a href="https://youtube.com.evil.example/watch?v=abc123XYZ_-">Not YouTube</a>
    </article></body></html>
    """
    page = FetchedPage(
        requested_url="https://recipes.example/no-video",
        final_url="https://recipes.example/no-video",
        html=html,
    )

    assert RecipeExtractor().extract(page).youtube_url is None
