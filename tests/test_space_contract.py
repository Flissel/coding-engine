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


def _write_contract() -> dict:
    """Valid contract with one write tool carrying full obligations."""
    raw = _read_only_contract()
    raw["tools"].append({"name": "notes_create", "params": ["title"],
                         "returns": {"id": "string"}, "side_effect": "write"})
    raw["events"]["notes.create"] = {
        "tool": "notes_create",
        "required_params": ["title"],
        "required_provenance": ["approval_ref"],
        "truth": {"kind": "truth:supabase_row", "table": "notes",
                  "expect": "present"},
    }
    return raw


def test_unsupported_truth_kind_is_rejected():
    """An invented kind passes yaml but never runs: world_observer would find
    no check by that name, so the write would route unverified while every
    gate stayed green."""
    raw = _write_contract()
    raw["events"]["notes.create"]["truth"]["kind"] = "truth:notes_exist"
    with pytest.raises(ValidationError, match="supabase_row"):
        SpaceContract(**raw)


def test_truth_kind_without_prefix_is_rejected():
    raw = _write_contract()
    raw["events"]["notes.create"]["truth"]["kind"] = "supabase_row"
    with pytest.raises(ValidationError, match="truth:"):
        SpaceContract(**raw)


def test_modelled_checks_are_accepted():
    from mcp_plugins.servers.grpc_host.space_contract import (
        MODELLED_TRUTH_CHECKS,
    )
    payloads = {
        "supabase_row": {"table": "notes", "match": "id=eq.{result_id}"},
        "http_ok": {"url": "http://127.0.0.1:8140/healthz"},
        "file_exists": {"path": "/tmp/notes.json"},
    }
    assert set(payloads) == set(MODELLED_TRUTH_CHECKS)
    for check, extra in payloads.items():
        raw = _write_contract()
        raw["events"]["notes.create"]["truth"] = dict(
            kind=f"truth:{check}", **extra
        )
        SpaceContract(**raw)  # must not raise


def test_supported_but_unmodelled_check_is_refused_by_name():
    """world_observer has the check, but this contract cannot spell its
    postcondition - refusing beats emitting a spec the observer rejects."""
    raw = _write_contract()
    raw["events"]["notes.create"]["truth"] = {"kind": "truth:supabase_edge_ids"}
    with pytest.raises(ValidationError, match="not modelled"):
        SpaceContract(**raw)


def test_http_ok_url_is_derived_from_the_runtime_block():
    raw = _write_contract()
    raw["events"]["notes.create"]["truth"] = {"kind": "truth:http_ok"}
    contract = SpaceContract(**raw)
    truth = contract.events["notes.create"].truth
    assert truth.url == "http://127.0.0.1:8140/healthz"


def test_file_exists_without_path_is_refused():
    raw = _write_contract()
    raw["events"]["notes.create"]["truth"] = {"kind": "truth:file_exists"}
    with pytest.raises(ValidationError, match="path"):
        SpaceContract(**raw)


def test_supabase_row_truth_without_table_is_rejected():
    raw = _write_contract()
    del raw["events"]["notes.create"]["truth"]["table"]
    with pytest.raises(ValidationError, match="table"):
        SpaceContract(**raw)


def test_supabase_row_match_is_derived_from_the_id_return():
    """The tool returns an id, so the row can be re-queried by it without
    the contract having to spell out postgrest syntax."""
    contract = SpaceContract(**_write_contract())
    assert contract.events["notes.create"].truth.match == "id=eq.{result_id}"


def test_supabase_row_without_id_return_requires_an_explicit_match():
    raw = _write_contract()
    raw["tools"][1]["returns"] = {"ok": "boolean"}
    with pytest.raises(ValidationError, match="match"):
        SpaceContract(**raw)


def test_explicit_match_is_kept():
    raw = _write_contract()
    raw["events"]["notes.create"]["truth"]["match"] = "title=eq.{result_title}"
    contract = SpaceContract(**raw)
    assert contract.events["notes.create"].truth.match == "title=eq.{result_title}"


def test_truth_on_fail_defaults_to_report():
    contract = SpaceContract(**_write_contract())
    assert contract.events["notes.create"].truth.on_fail == "report"
