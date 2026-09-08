"""The capability artefact is what makes a space's truth validator run.

Without it the chain capabilities.yaml -> capability_router.get_capability()
-> plan_executor (hop.validator) -> CapabilityValidator -> world_observer
has no first link, so a declared ground-truth re-query never happens while
the contract, the registry and the tests all report green.
"""
import yaml

from mcp_plugins.servers.grpc_host.space_contract import SpaceContract
from mcp_plugins.servers.grpc_host.space_renderers import (
    render_capability_entries,
)


def _read_only_contract() -> dict:
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


def _write_contract() -> SpaceContract:
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
    return SpaceContract(**raw)


def _entries(contract: SpaceContract) -> list:
    parsed = yaml.safe_load(render_capability_entries(contract))
    return parsed or []


def test_read_only_contract_renders_no_capability_entries():
    contract = SpaceContract(**_read_only_contract())
    assert render_capability_entries(contract) == ""


def test_rendered_fragment_is_a_yaml_list_of_capabilities():
    entries = _entries(_write_contract())
    assert isinstance(entries, list) and len(entries) == 1
    assert entries[0]["capability"] == "notes_create"


def test_capability_carries_the_truth_validator():
    validator = _entries(_write_contract())[0]["validator"]
    assert validator["kind"] == "truth:supabase_row"
    assert validator["on_fail"] == "report"
    post = validator["postcondition"]
    # check must be the bare name; world_observer._CHECKS is keyed without
    # the 'truth:' prefix, so passing the prefixed form finds nothing.
    assert post["check"] == "supabase_row"
    assert post["table"] == "notes"
    assert post["match"] == "id=eq.{result_id}"
    assert post["expect"] == "present"


def test_execution_target_points_at_the_space_mcp_tool():
    entry = _entries(_write_contract())[0]
    assert entry["execution_target"] == "mcp:brain-notes:spaces-notes:notes_create"


def test_arg_kwarg_is_the_events_first_required_param():
    entry = _entries(_write_contract())[0]
    assert entry["arg_kwarg"] == "title"


def test_read_event_with_a_truth_validator_is_rendered_too():
    """truth is mandatory for writes, but a read event may declare one."""
    raw = _read_only_contract()
    raw["events"]["notes.list"]["truth"] = {"kind": "truth:http_ok"}
    entries = _entries(SpaceContract(**raw))
    assert [e["capability"] for e in entries] == ["notes_list"]
    post = entries[0]["validator"]["postcondition"]
    assert post == {"check": "http_ok", "url": "http://127.0.0.1:8140/healthz"}

def test_capability_carries_at_least_one_compilable_pattern():
    """capability_router._load drops any entry whose match_patterns
    compile to nothing ("has no usable patterns, skipping"). Such an
    entry never enters the router, get_capability() returns None, and
    the validator is unreachable - the exact silent gap this artefact
    exists to close. Measured against the real router: without patterns
    it was skipped."""
    import re

    entry = _entries(_write_contract())[0]
    compiled = [re.compile(p, re.IGNORECASE)
                for p in entry["match_patterns"]]
    assert compiled, "the router would skip this entry"
    assert any(p.search("notes.create") for p in compiled)
    assert any(p.search("notes_create") for p in compiled)


def test_event_pattern_escapes_the_dot():
    """An unescaped dot turns the event id into a wildcard that also
    matches unrelated text."""
    import re

    entry = _entries(_write_contract())[0]
    event_pattern = re.compile(entry["match_patterns"][0], re.IGNORECASE)
    assert event_pattern.search("notes.create")
    assert not event_pattern.search("notesXcreate")
