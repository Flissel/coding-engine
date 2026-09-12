"""Der Entwurf ist ein Vorschlag, kein Befund.

Zwei Annahmen stecken darin, und beide muessen sichtbar bleiben: die
Zugehoerigkeit ueber den Namenspraefix, und `writes` aus dem
Ausfuehrungsziel. Was sich nicht ableiten laesst, bleibt offen - der
Entwurf validiert dann nicht, und das ist der Zweck.
"""
from pathlib import Path

import pytest
import yaml

from mcp_plugins.servers.grpc_host.space_draft import (
    draft, unattributed, _writes_of, _capability_prefixes,
)

# tests/ -> coding-engine/ -> vibemind-os/
ROOT = Path(__file__).resolve().parents[2]


def _has_registry() -> bool:
    return (ROOT / "config" / "space_agent_registry.yml").is_file()


needs_os = pytest.mark.skipif(not _has_registry(),
                              reason="vibemind-os root not available here")


def test_a_clear_write_target_is_derived():
    assert _writes_of({"execution_target": "supabase:idea.create"}) is True
    assert _writes_of({"execution_target": "supabase:idea.delete"}) is True


def test_a_clear_read_target_is_derived():
    assert _writes_of({"execution_target": "supabase:idea.list"}) is False
    assert _writes_of({"execution_target": "supabase:idea.count"}) is False


def test_an_ambiguous_target_stays_open():
    """`supabase:idea.llm` ist gemischt - idea_expand schreibt,
    idea_explain nicht. Raten waere hier schlimmer als fragen."""
    assert _writes_of({"execution_target": "supabase:idea.llm"}) is None
    assert _writes_of({"execution_target": "openfang:brain-coder"}) is None


def test_no_target_stays_open():
    assert _writes_of({}) is None
    assert _writes_of({"execution_target": None}) is None


def test_both_naming_styles_are_covered():
    """`idea_add` und `mirofish.simulate` kommen beide vor. Nur den
    Unterstrich zu pruefen liess mirofish leer aussehen."""
    prefixes = _capability_prefixes({"prefixes": ["mirofish."]})
    assert "mirofish_" in prefixes
    assert "mirofish." in prefixes


@needs_os
def test_the_draft_names_its_open_spots():
    text, open_ones = draft("ideas", ROOT)
    assert "id: ideas" in text
    assert open_ones, "ideas has supabase:idea.llm capabilities"
    for name in open_ones:
        assert f"- name: {name}" in text
        assert "TODO writes" in text


@needs_os
def test_an_open_draft_does_not_validate():
    """Der Kern: ein Entwurf mit offenen Stellen ist kein gueltiger
    Vertrag. Erst wenn jemand entschieden hat, geht er durch."""
    from pydantic import ValidationError
    from mcp_plugins.servers.grpc_host.space_contract import SpaceContract

    text, open_ones = draft("ideas", ROOT)
    assert open_ones
    with pytest.raises(ValidationError):
        SpaceContract(**yaml.safe_load(text))


@needs_os
def test_an_unknown_space_is_refused():
    with pytest.raises(KeyError, match="not in the registry"):
        draft("gibt-es-nicht", ROOT)


@needs_os
def test_unattributed_capabilities_are_reported():
    """Capabilities, die zu keinem Space passen, sind ein eigener Befund -
    fuer 'die Spaces miteinander verdrahten' der wichtigste."""
    rows = unattributed(ROOT)
    assert rows
    names = {name for name, _ in rows}
    # component_note_write schreibt Ideen, heisst aber nicht idea_*
    assert "component_note_write" in names
