import pytest
from pydantic import ValidationError

from mcp_plugins.servers.grpc_host.space_contract import (
    SpaceContract,
    ContractError,
)


def _read_only_contract() -> dict:
    """Minimal valid contract: one read tool, one event, no writes."""
    return {
        "id": "notes",
        "description": "Notes space",
        "prefixes": ["notes."],
        "tools": [
            {"name": "notes_list", "params": [], "returns": {"items": "array"},
             "side_effect": "read"},
        ],
        "events": {
            "notes.list": {"tool": "notes_list", "required_params": []},
        },
        "ui": {"embed": "none"},
        "runtime": {"port": 8140, "healthz": "/healthz",
                    "start": "python -m spaces.notes.server"},
    }


def test_read_only_contract_validates():
    contract = SpaceContract(**_read_only_contract())
    assert contract.id == "notes"
    assert contract.agent_name == "brain-notes"


def test_write_tool_without_provenance_is_rejected():
    raw = _read_only_contract()
    raw["tools"].append({"name": "notes_create", "params": ["title"],
                         "returns": {"id": "string"}, "side_effect": "write"})
    raw["events"]["notes.create"] = {
        "tool": "notes_create",
        "required_params": ["title"],
        "truth": {"kind": "truth:supabase_row", "table": "notes",
                  "expect": "present"},
    }
    with pytest.raises(ValidationError, match="required_provenance"):
        SpaceContract(**raw)


def test_write_tool_without_truth_is_rejected():
    raw = _read_only_contract()
    raw["tools"].append({"name": "notes_create", "params": ["title"],
                         "returns": {"id": "string"}, "side_effect": "write"})
    raw["events"]["notes.create"] = {
        "tool": "notes_create",
        "required_params": ["title"],
        "required_provenance": ["approval_ref", "cost_ref"],
    }
    with pytest.raises(ValidationError, match="truth"):
        SpaceContract(**raw)


def test_event_pointing_at_unknown_tool_is_rejected():
    raw = _read_only_contract()
    raw["events"]["notes.ghost"] = {"tool": "does_not_exist",
                                    "required_params": []}
    with pytest.raises(ValidationError, match="unknown tool"):
        SpaceContract(**raw)


def test_duplicate_tool_names_are_rejected():
    raw = _read_only_contract()
    raw["tools"].append(dict(raw["tools"][0]))
    with pytest.raises(ValidationError, match="duplicate tool"):
        SpaceContract(**raw)


def test_event_outside_declared_prefix_is_rejected():
    raw = _read_only_contract()
    raw["events"]["other.list"] = {"tool": "notes_list", "required_params": []}
    with pytest.raises(ValidationError, match="prefix"):
        SpaceContract(**raw)


def test_browserview_without_entry_url_is_rejected():
    raw = _read_only_contract()
    raw["ui"] = {"embed": "browserview"}
    with pytest.raises(ValidationError, match="entry_url"):
        SpaceContract(**raw)


def test_write_tool_needs_at_least_one_event():
    raw = _read_only_contract()
    raw["tools"].append({"name": "notes_create", "params": ["title"],
                         "returns": {"id": "string"}, "side_effect": "write"})
    with pytest.raises(ValidationError, match="no event"):
        SpaceContract(**raw)


def test_load_contract_reads_yaml(tmp_path):
    import yaml
    from mcp_plugins.servers.grpc_host.space_contract import load_contract

    path = tmp_path / "contract.yaml"
    path.write_text(yaml.safe_dump(_read_only_contract()), encoding="utf-8")
    contract = load_contract(path)
    assert contract.id == "notes"


def test_load_contract_raises_contract_error_on_missing_file(tmp_path):
    from mcp_plugins.servers.grpc_host.space_contract import load_contract

    with pytest.raises(ContractError, match="not found"):
        load_contract(tmp_path / "nope.yaml")
