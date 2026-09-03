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


def test_required_params_outside_tool_params_is_rejected():
    """FIX 4: required_params: [titel, nonexistent] against a tool whose
    real params are [title, body] used to validate cleanly, then land in
    the live registry as a routing requirement the tool can never satisfy."""
    raw = _read_only_contract()
    raw["events"]["notes.list"]["required_params"] = ["titel", "nonexistent"]
    with pytest.raises(ValidationError, match="required_params"):
        SpaceContract(**raw)


def test_required_params_within_tool_params_is_accepted():
    raw = _read_only_contract()
    raw["tools"].append({"name": "notes_get", "params": ["id"],
                         "returns": {"item": "object"}, "side_effect": "read"})
    raw["events"]["notes.get"] = {"tool": "notes_get", "required_params": ["id"]}
    contract = SpaceContract(**raw)
    assert contract.events["notes.get"].required_params == ["id"]


def test_healthz_without_leading_slash_is_rejected():
    """FIX 5: healthz: "not-a-path" used to validate, then render straight
    into @mcp.custom_route("not-a-path") - and starlette refuses to load
    the generated server with AssertionError('Routed paths must start
    with "/"')."""
    raw = _read_only_contract()
    raw["runtime"]["healthz"] = "not-a-path"
    with pytest.raises(ValidationError, match="must start with"):
        SpaceContract(**raw)


def test_healthz_with_leading_slash_is_accepted():
    raw = _read_only_contract()
    raw["runtime"]["healthz"] = "/custom/healthz"
    contract = SpaceContract(**raw)
    assert contract.runtime.healthz == "/custom/healthz"


def test_hyphenated_id_is_rejected():
    """Hyphens make f"{sid}-{suffix}" task ids ambiguous (sales +
    verify-tests collides with sales-verify + tests) and are unusable in
    env var names, so the id grammar excludes them."""
    raw = _read_only_contract()
    raw["id"] = "my-space"
    with pytest.raises(ValidationError, match="lowercase letters, digits "
                        "and underscores"):
        SpaceContract(**raw)


def test_underscore_id_is_accepted():
    raw = _read_only_contract()
    raw["id"] = "my_space"
    contract = SpaceContract(**raw)
    assert contract.id == "my_space"
    assert contract.agent_name == "brain-my_space"


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


def test_bundled_fixture_contract_validates():
    """The fixture the renderer tests build on must itself be valid."""
    from pathlib import Path
    from mcp_plugins.servers.grpc_host.space_contract import load_contract

    path = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"
    contract = load_contract(path)

    assert contract.id == "notes"
    assert contract.agent_name == "brain-notes"
    assert contract.ui.embed == "browserview"
    assert {t.name for t in contract.tools} == {"notes_list", "notes_create"}
    create = contract.events["notes.create"]
    assert create.required_provenance == ["approval_ref", "cost_ref"]
    assert create.truth is not None
