from types import SimpleNamespace

import pytest

from reciper.errors import NormalizationError
from reciper.models import ExtractedRecipe, Ingredient, InstructionStep, Recipe
from reciper.normalize import OpenAIRecipeNormalizer


class FakeResponses:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response: object) -> None:
        self.responses = FakeResponses(response)


def detailed_source() -> ExtractedRecipe:
    return ExtractedRecipe(
        source_url="https://recipes.example.test/bread",
        page_title="Test Bread",
        ingredient_lines=["1 1/2 cups (180 g) flour", "¼ teaspoon fine salt"],
        instruction_lines=["1. Bake at 350°F for 20–25 minutes."],
    )


def detailed_recipe() -> Recipe:
    return Recipe(
        title="Test Bread",
        ingredients=[
            Ingredient(
                amount="1 1/2 cups (180 g)",
                name="flour",
                details=None,
                display_text="1 1/2 cups (180 g) flour",
            ),
            Ingredient(
                amount="¼ teaspoon",
                name="fine salt",
                details=None,
                display_text="¼ teaspoon fine salt",
            ),
        ],
        instructions=[
            InstructionStep(
                text="Bake at 350°F for 20–25 minutes.",
                time="20–25 minutes",
                temperature="350°F",
            )
        ],
        tips=[],
    )


def test_normalize_uses_responses_structured_parse_and_preserves_numbers() -> None:
    response = SimpleNamespace(output_parsed=detailed_recipe(), output=[])
    client = FakeClient(response)
    normalizer = OpenAIRecipeNormalizer(model="test-model", client=client)

    result = normalizer.normalize(detailed_source())

    assert result.title == "Test Bread"
    call = client.responses.calls[0]
    assert call["model"] == "test-model"
    assert call["text_format"] is Recipe
    assert call["store"] is False
    assert call["max_output_tokens"] == 6_000
    input_messages = call["input"]
    assert isinstance(input_messages, list)
    assert "untrusted source data" in input_messages[1]["content"]
    assert "1 1/2 cups (180 g) flour" in input_messages[1]["content"]


def test_normalize_accepts_mapping_returned_by_client() -> None:
    response = SimpleNamespace(output_parsed=detailed_recipe().model_dump(), output=[])
    result = OpenAIRecipeNormalizer(model="test-model", client=FakeClient(response)).normalize(
        detailed_source()
    )
    assert isinstance(result, Recipe)


def test_normalize_restores_lossless_source_instruction_text() -> None:
    incomplete = detailed_recipe().model_copy(
        update={
            "instructions": [InstructionStep(text="Bake until done.", time=None, temperature=None)]
        }
    )
    normalizer = OpenAIRecipeNormalizer(
        model="test-model",
        client=FakeClient(SimpleNamespace(output_parsed=incomplete, output=[])),
    )

    result = normalizer.normalize(detailed_source())
    assert result.instructions[0].text == "Bake at 350°F for 20–25 minutes."


def test_normalize_ignores_invented_tips() -> None:
    invented = detailed_recipe().model_copy(update={"tips": ["Store for 99 days."]})
    normalizer = OpenAIRecipeNormalizer(
        model="test-model",
        client=FakeClient(SimpleNamespace(output_parsed=invented, output=[])),
    )

    result = normalizer.normalize(detailed_source())
    assert result.tips == []


def test_normalize_restores_explicit_notes_and_tip_sections() -> None:
    source = detailed_source().model_copy(
        update={
            "note_lines": ["Keep the dough covered while it rests."],
            "tip_sections": [
                "Success Tips\nKeep the dough covered while it rests.\nCool fully before slicing."
            ],
        }
    )
    result = OpenAIRecipeNormalizer(
        model="test-model",
        client=FakeClient(SimpleNamespace(output_parsed=detailed_recipe(), output=[])),
    ).normalize(source)
    assert result.tips == [
        "Keep the dough covered while it rests.",
        "Cool fully before slicing.",
    ]


def test_normalize_rejects_invented_numeric_title_detail() -> None:
    invented = detailed_recipe().model_copy(update={"title": "Test Bread 99"})
    normalizer = OpenAIRecipeNormalizer(
        model="test-model",
        client=FakeClient(SimpleNamespace(output_parsed=invented, output=[])),
    )

    with pytest.raises(NormalizationError, match="unsupported numeric details.*99"):
        normalizer.normalize(detailed_source())


def test_normalize_requires_yield_and_timing_metadata() -> None:
    source = detailed_source().model_copy(
        update={
            "yield_text": "1 loaf",
            "timing": {"prep_time": "2 hours", "cook_time": "25 minutes"},
        }
    )
    complete = detailed_recipe().model_copy(
        update={"yield_text": "1 loaf", "prep_time": "2 hours", "cook_time": "25 minutes"}
    )
    result = OpenAIRecipeNormalizer(
        model="test-model",
        client=FakeClient(SimpleNamespace(output_parsed=complete, output=[])),
    ).normalize(source)
    assert result.prep_time == "2 hours"

    incomplete = complete.model_copy(
        update={"yield_text": None, "prep_time": None, "cook_time": None}
    )
    restored = OpenAIRecipeNormalizer(
        model="test-model",
        client=FakeClient(SimpleNamespace(output_parsed=incomplete, output=[])),
    ).normalize(source)
    assert restored.yield_text == "1 loaf"
    assert restored.prep_time == "2 hours"
    assert restored.cook_time == "25 minutes"


def test_normalize_rejects_changed_structured_item_count() -> None:
    missing_ingredient = detailed_recipe().model_copy(
        update={"ingredients": detailed_recipe().ingredients[:1]}
    )
    with pytest.raises(NormalizationError, match="changed the structured ingredient count"):
        OpenAIRecipeNormalizer(
            model="test-model",
            client=FakeClient(SimpleNamespace(output_parsed=missing_ingredient, output=[])),
        ).normalize(detailed_source())


def test_normalize_rejects_swapped_ingredient_associations() -> None:
    source = ExtractedRecipe(
        source_url="https://example.test",
        ingredient_lines=["1 cup flour", "2 cups water"],
        instruction_lines=["Mix for 3 minutes."],
    )
    swapped = Recipe(
        title="Test",
        ingredients=[
            Ingredient(amount="2 cups", name="flour", details=None, display_text="2 cups flour"),
            Ingredient(amount="1 cup", name="water", details=None, display_text="1 cup water"),
        ],
        instructions=[InstructionStep(text="Mix for 3 minutes.", time="3 minutes")],
        tips=[],
    )
    with pytest.raises(NormalizationError, match="Ingredient 1 introduced unsupported details"):
        OpenAIRecipeNormalizer(
            model="test-model",
            client=FakeClient(SimpleNamespace(output_parsed=swapped, output=[])),
        ).normalize(source)


def test_normalize_reports_refusal_without_echoing_it() -> None:
    response = SimpleNamespace(
        output_parsed=None,
        output=[SimpleNamespace(content=[SimpleNamespace(refusal="sensitive refusal detail")])],
    )
    normalizer = OpenAIRecipeNormalizer(model="test-model", client=FakeClient(response))

    with pytest.raises(NormalizationError, match="declined") as error:
        normalizer.normalize(ExtractedRecipe(source_url="https://example.test"))

    assert "sensitive" not in str(error.value)


def test_normalize_rejects_missing_structured_output() -> None:
    response = SimpleNamespace(output_parsed=None, output=[])
    normalizer = OpenAIRecipeNormalizer(model="test-model", client=FakeClient(response))

    with pytest.raises(NormalizationError, match="did not return"):
        normalizer.normalize(ExtractedRecipe(source_url="https://example.test"))


def test_normalize_rejects_invalid_structured_output() -> None:
    response = SimpleNamespace(output_parsed={"title": "Missing lists"}, output=[])
    normalizer = OpenAIRecipeNormalizer(model="test-model", client=FakeClient(response))

    with pytest.raises(NormalizationError, match="invalid recipe structure"):
        normalizer.normalize(ExtractedRecipe(source_url="https://example.test"))
