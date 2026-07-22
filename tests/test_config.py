from pathlib import Path

import pytest

from reciper.config import DEFAULT_MODEL, Settings, load_environment
from reciper.errors import ConfigurationError


def test_settings_require_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="not configured"):
        Settings.from_environment()


def test_settings_use_default_and_override_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert Settings.from_environment().model == DEFAULT_MODEL
    assert Settings.from_environment("custom-model").model == "custom-model"


def test_load_environment_reads_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=env-value\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("OPENAI_API_KEY=unused-local-value\n", encoding="utf-8")

    load_environment(tmp_path)

    assert Settings.from_environment().model == DEFAULT_MODEL
    assert __import__("os").environ["OPENAI_API_KEY"] == "env-value"
