"""Kein fremdes Modell an die Claude-CLI.

`config/llm_models.yml` nennt sich Single Source of Truth und fuehrt genau
EINEN Schluessel `cli` — laut eigenem Kommentar fuer "Claude CLI / Kilo CLI".
Zwei CLIs mit unvereinbaren Modellnamen an einem Schluessel. Steht dort ein
OpenAI-Modell, bricht jeder Claude-CLI-Aufruf ab mit
`[claude-code:unrecognized_model]`.

Am Live-Lauf 2026-09-11 aufgefallen, nicht im Test: die Engine reichte
`gpt-5.4` an `claude.exe` weiter.
"""
import yaml
from pathlib import Path

import pytest

from src.autogen.cli_wrapper import _claude_cli_model

CONFIG = Path(__file__).resolve().parents[1] / "config" / "llm_models.yml"


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    monkeypatch.delenv("LLM_MODEL_CLI", raising=False)


def test_a_foreign_model_is_not_passed_through(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_CLI", "gpt-5.4")
    assert _claude_cli_model() is None


def test_an_openrouter_style_openai_model_is_also_refused(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_CLI", "openai/gpt-5.4")
    assert _claude_cli_model() is None


@pytest.mark.parametrize("model", [
    "claude-sonnet-4-5",
    "claude-opus-4-20250514",
    "anthropic/claude-sonnet-4.5",
])
def test_a_claude_model_is_passed_through(monkeypatch, model):
    monkeypatch.setenv("LLM_MODEL_CLI", model)
    assert _claude_cli_model() == model


def test_no_model_configured_means_no_flag(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_CLI", "")
    assert _claude_cli_model() is None


def test_the_shipped_config_is_the_case_this_guards():
    """Haelt fest, warum es diese Pruefung gibt: die mitgelieferte
    Konfiguration nennt fuer die Rolle `cli` ein Nicht-Claude-Modell. Faellt
    dieser Test, wurde sie korrigiert - dann darf die Warnung weg."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    configured = str(config["models"]["cli"]["model"]).lower()
    assert "claude" not in configured, (
        "config/llm_models.yml nennt jetzt ein Claude-Modell fuer 'cli' - "
        "die Fallunterscheidung im cli_wrapper kann ueberprueft werden"
    )
