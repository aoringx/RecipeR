import pytest

from reciper.cli import main


def test_cli_fails_cleanly_when_key_is_not_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["https://example.test/recipe"])

    assert exit_code == 2
    assert "OPENAI_API_KEY is not configured" in capsys.readouterr().err


def test_cli_rejects_missing_url() -> None:
    with pytest.raises(SystemExit) as error:
        main([])
    assert error.value.code == 2
