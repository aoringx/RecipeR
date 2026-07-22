from __future__ import annotations

import run


def test_script_forwards_command_line_arguments(monkeypatch) -> None:
    received: list[str] = []

    def fake_cli_main(args: list[str]) -> int:
        received.extend(args)
        return 0

    monkeypatch.setattr(run, "cli_main", fake_cli_main)

    assert run.main(["https://example.test/recipe", "--debug"]) == 0
    assert received == ["https://example.test/recipe", "--debug"]


def test_script_prompts_for_url(monkeypatch) -> None:
    received: list[str] = []
    monkeypatch.setattr("builtins.input", lambda _prompt: "https://example.test/recipe")
    monkeypatch.setattr(run, "cli_main", lambda args: received.extend(args) or 0)

    assert run.main([]) == 0
    assert received == ["https://example.test/recipe"]


def test_script_rejects_empty_prompt(monkeypatch, capsys) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "  ")

    assert run.main([]) == 2
    assert "a recipe URL is required" in capsys.readouterr().err
