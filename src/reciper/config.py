"""Environment loading and application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from reciper.errors import ConfigurationError

DEFAULT_MODEL = "gpt-5.4-mini"


def load_environment(directory: Path | None = None) -> None:
    """Load the ignored .env file without replacing existing environment values."""

    base = directory or Path.cwd()
    candidate = base / ".env"
    if candidate.is_file():
        load_dotenv(candidate, override=False)


@dataclass(frozen=True)
class Settings:
    model: str

    @classmethod
    def from_environment(cls, model_override: str | None = None) -> Settings:
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise ConfigurationError(
                "OPENAI_API_KEY is not configured. Configure it when you are ready to use the API."
            )

        model = (model_override or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL).strip()
        if not model:
            raise ConfigurationError("The OpenAI model name must not be blank.")
        return cls(model=model)
