"""Validated data models shared across the pipeline."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Ingredient(StrictModel):
    """One ingredient, retaining both structured and lossless display forms."""

    amount: str | None = Field(
        default=None,
        description="Exact quantity and unit text, including ranges or dual measurements.",
    )
    name: str = Field(description="The ingredient name or type.")
    details: str | None = Field(
        default=None,
        description="Preparation, temperature, brand, substitution, or other qualifiers.",
    )
    display_text: str = Field(
        description=(
            "Complete ingredient line preserving every source detail verbatim where possible."
        )
    )

    @field_validator("name", "display_text")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be blank")
        return value


class InstructionStep(StrictModel):
    """One complete, ordered recipe instruction."""

    text: str = Field(
        description=(
            "Complete instruction text, including every stated time, temperature, quantity, "
            "dimension, equipment setting, and visual cue."
        )
    )
    time: str | None = Field(
        default=None,
        description="Exact duration or timing phrase stated for this step, if any.",
    )
    temperature: str | None = Field(
        default=None,
        description="Exact heat or temperature stated for this step, if any.",
    )

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be blank")
        return value


class Recipe(StrictModel):
    """The LLM-normalized recipe rendered to the output text file."""

    title: str
    yield_text: str | None = Field(
        default=None,
        description="Exact stated recipe yield or serving quantity, rendered readably.",
    )
    prep_time: str | None = Field(
        default=None,
        description="Exact stated preparation time, rendered readably.",
    )
    cook_time: str | None = Field(
        default=None,
        description="Exact stated cooking time, rendered readably.",
    )
    total_time: str | None = Field(
        default=None,
        description="Exact stated total time, rendered readably.",
    )
    ingredients: list[Ingredient] = Field(min_length=1)
    instructions: list[InstructionStep] = Field(min_length=1)
    tips: list[str] = Field(
        default_factory=list,
        description="Only explicit source-backed tips, notes, substitutions, or storage advice.",
    )

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("tips")
    @classmethod
    def remove_blank_tips(cls, values: list[str]) -> list[str]:
        return [value for value in values if value]


class ExtractedRecipe(StrictModel):
    """Bounded, deterministic recipe material extracted from a webpage."""

    source_url: str
    page_title: str | None = None
    description: str | None = None
    yield_text: str | None = None
    timing: dict[str, str] = Field(default_factory=dict)
    ingredient_lines: list[str] = Field(default_factory=list)
    instruction_lines: list[str] = Field(default_factory=list)
    note_lines: list[str] = Field(default_factory=list)
    tip_sections: list[str] = Field(default_factory=list)
    article_text: str = ""

    def prompt_payload(self) -> dict[str, object]:
        """Return only the source material the normalizer needs."""

        return {
            "page_title": self.page_title,
            "description": self.description,
            "yield": self.yield_text,
            "timing": self.timing,
            "ingredients": self.ingredient_lines,
            "instructions": self.instruction_lines,
            "notes": self.note_lines,
            "tip_sections": self.tip_sections,
            "article_text": self.article_text,
        }
