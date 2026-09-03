from pathlib import Path

import yaml

from mcp_plugins.servers.grpc_host.space_contract import load_contract
from mcp_plugins.servers.grpc_host.space_renderers import render_registry_entry

FIXTURE = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"


def _entry() -> dict:
    """Render the fragment and parse it back as the registry would."""
    contract = load_contract(FIXTURE)
    fragment = render_registry_entry(contract)
    parsed = yaml.safe_load(fragment)
    return parsed["notes"]


def test_registry_entry_declares_agent_and_prefix():
    entry = _entry()
    assert entry["agent"] == "brain-notes"
    assert entry["prefixes"] == ["notes."]
    assert entry["enabled"] is True


def test_registry_entry_lists_mcp_tools_not_just_servers():
    """The agent's tools come only from mcp_tools (sync_openfang_agents:100)."""
    entry = _entry()
    assert entry["mcp_servers"] == ["spaces-notes"]
    assert entry["mcp_tools"] == {
        "spaces-notes": ["notes_list", "notes_create"]
    }


def test_registry_entry_carries_provenance_for_write_events():
    entry = _entry()
    assert entry["events"]["notes.create"]["required_provenance"] == [
        "approval_ref", "cost_ref"
    ]
    assert entry["events"]["notes.create"]["execution"] == {
        "kind": "mcp", "server": "spaces-notes"
    }


def test_registry_entry_read_event_has_no_provenance_key():
    entry = _entry()
    assert "required_provenance" not in entry["events"]["notes.list"]


def test_registry_fragment_is_indented_for_insertion():
    contract = load_contract(FIXTURE)
    fragment = render_registry_entry(contract)
    assert fragment.startswith("  notes:")


def test_agent_manifest_matches_brain_video_shape():
    from mcp_plugins.servers.grpc_host.space_renderers import (
        render_agent_manifest,
    )

    contract = load_contract(FIXTURE)
    manifest = yaml.safe_load(render_agent_manifest(contract))

    assert manifest["agent"] == "brain-notes"
    assert manifest["default_namespace"] == "notes"
    assert manifest["events"] == ["notes.create", "notes.list"]
    assert manifest["description"] == contract.description
    assert "notes" in manifest


def test_agent_manifest_events_are_sorted():
    from mcp_plugins.servers.grpc_host.space_renderers import (
        render_agent_manifest,
    )

    contract = load_contract(FIXTURE)
    manifest = yaml.safe_load(render_agent_manifest(contract))
    assert manifest["events"] == sorted(manifest["events"])
