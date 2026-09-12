"""Der schlanke Vollständigkeitsgrad: ein Vertrag für bestehende Spaces.

ADR-0004. Ein bestehender Space hat keine eigenen Tools, keinen eigenen
Prozess und keine UI — er routet über Capabilities, die anderswo definiert
sind. Sein Vertrag trägt deshalb nur den **Anspruch**: welche Capability
gehört zu diesem Space, und schreibt sie.

Ziel und Validator werden NICHT wiederholt. Sie stehen in
capabilities.yaml, und das Gate liest sie dort. Ein Vertrag, der sie
mitführte, wäre die zweite Quelle — genau die Drift, gegen die der ADR
argumentiert.
"""
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from mcp_plugins.servers.grpc_host.space_contract import SpaceContract

FIXTURE = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"


def _generated() -> dict:
    """Der volle Grad: eigene Tools, UI, Laufzeit."""
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def _lean() -> dict:
    """Der schlanke Grad: nur der Anspruch auf Capabilities."""
    return {
        "id": "ideas",
        "description": "Ideen sammeln, verbinden, in Projekte überführen",
        "prefixes": ["idea."],
        "capabilities": [
            {"name": "idea_add", "writes": True},
            {"name": "idea_connect", "writes": True},
            {"name": "idea_explain", "writes": False},
        ],
    }


# ---------------------------------------------------------------------
# Beide Grade sind gültig
# ---------------------------------------------------------------------

def test_the_generated_degree_still_validates():
    """Der volle Grad darf sich nicht ändern - 154 Tests hängen daran."""
    contract = SpaceContract(**_generated())
    assert contract.id == "notes"
    assert len(contract.tools) == 2
    assert contract.runtime is not None


def test_the_lean_degree_validates_without_tools_ui_runtime():
    contract = SpaceContract(**_lean())
    assert contract.id == "ideas"
    assert contract.tools == []
    assert contract.runtime is None
    assert [c.name for c in contract.capabilities] == [
        "idea_add", "idea_connect", "idea_explain"]


def test_a_lean_contract_knows_it_renders_nothing():
    """Ohne eigene Artefakte gibt es nichts zu erzeugen. Der Vertrag muss
    das selbst sagen koennen, sonst muss jeder Aufrufer raten."""
    assert SpaceContract(**_lean()).renders_artefacts is False
    assert SpaceContract(**_generated()).renders_artefacts is True


# ---------------------------------------------------------------------
# Kein Schlupfloch
# ---------------------------------------------------------------------

def test_a_contract_must_declare_something():
    """Weder Tools noch Capabilities heisst: der Vertrag sagt nichts aus.
    Das ist kein schlanker Grad, das ist eine leere Huelle."""
    raw = _lean()
    raw["capabilities"] = []
    with pytest.raises(ValidationError, match="tools|capabilities"):
        SpaceContract(**raw)


def test_omitting_tools_is_not_a_way_around_the_write_obligations():
    """Das Gegenargument aus ADR-0004: ein Space koennte `tools` weglassen,
    um der Pflicht 'Write braucht Provenance und Truth' zu entgehen. Die
    Pflicht gilt deshalb auf Capability-Ebene weiter - nur wird sie dort
    gegen capabilities.yaml geprueft, nicht im Modell. Das Modell muss die
    schreibende Capability wenigstens als solche festhalten."""
    contract = SpaceContract(**_lean())
    writers = [c.name for c in contract.capabilities if c.writes]
    assert writers == ["idea_add", "idea_connect"]


def test_a_lean_contract_may_not_smuggle_in_a_runtime():
    """Wer Laufzeit deklariert, deklariert einen eigenen Dienst - dann sind
    auch Tools faellig. Halbe Formen sind der Weg, auf dem Gates ins Leere
    laufen."""
    raw = _lean()
    raw["runtime"] = {"port": 8140, "healthz": "/healthz", "start": "x"}
    with pytest.raises(ValidationError, match="tools"):
        SpaceContract(**raw)


def test_events_still_need_a_tool_when_tools_are_declared():
    """Der volle Grad behaelt seine Regeln unveraendert."""
    raw = _generated()
    raw["events"]["notes.create"]["tool"] = "gibt_es_nicht"
    with pytest.raises(ValidationError, match="unknown tool"):
        SpaceContract(**raw)


def test_a_lean_contract_needs_no_events():
    raw = _lean()
    assert SpaceContract(**raw).events == {}


def test_duplicate_capability_claims_are_refused():
    raw = _lean()
    raw["capabilities"].append({"name": "idea_add", "writes": False})
    with pytest.raises(ValidationError, match="duplicate"):
        SpaceContract(**raw)


def test_a_capability_claim_needs_a_name():
    raw = _lean()
    raw["capabilities"] = [{"writes": True}]
    with pytest.raises(ValidationError):
        SpaceContract(**raw)


def test_writes_must_be_stated_not_guessed():
    """`writes` hat keinen Vorgabewert. Wer den Vertrag schreibt, muss sich
    festlegen - eine geratene Voreinstellung waere genau die stille Annahme,
    die spaeter niemand mehr hinterfragt."""
    raw = _lean()
    raw["capabilities"] = [{"name": "idea_add"}]
    with pytest.raises(ValidationError, match="writes"):
        SpaceContract(**raw)
