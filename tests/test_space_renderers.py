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
        "spaces-notes": ["notes_create", "notes_list"]
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


def test_mcp_server_scaffold_is_valid_python():
    import ast
    from mcp_plugins.servers.grpc_host.space_renderers import render_mcp_server

    contract = load_contract(FIXTURE)
    source = render_mcp_server(contract)
    tree = ast.parse(source)  # raises SyntaxError if malformed

    functions = {n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)}
    assert {"notes_list", "notes_create", "healthz"} <= functions


def test_mcp_server_scaffold_carries_tool_params():
    import ast
    from mcp_plugins.servers.grpc_host.space_renderers import render_mcp_server

    contract = load_contract(FIXTURE)
    tree = ast.parse(render_mcp_server(contract))
    create = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "notes_create")
    assert [a.arg for a in create.args.args] == ["title", "body"]


def test_mcp_server_scaffold_leaves_holes_not_fake_results():
    """A stub must fail loudly, never return a plausible empty result."""
    from mcp_plugins.servers.grpc_host.space_renderers import render_mcp_server

    source = render_mcp_server(load_contract(FIXTURE))
    assert source.count("raise NotImplementedError") == 2


def test_mcp_server_scaffold_binds_contract_port():
    from mcp_plugins.servers.grpc_host.space_renderers import render_mcp_server

    source = render_mcp_server(load_contract(FIXTURE))
    assert "8140" in source
    assert "spaces-notes" in source


def test_electron_manager_exposes_show_and_hide():
    from mcp_plugins.servers.grpc_host.space_renderers import (
        render_electron_manager,
    )

    source = render_electron_manager(load_contract(FIXTURE))
    assert "showNotes" in source
    assert "hideNotes" in source
    assert "BrowserView" in source
    assert "http://127.0.0.1:8140/" in source


def test_electron_preload_bridges_show_and_hide():
    from mcp_plugins.servers.grpc_host.space_renderers import (
        render_electron_preload,
    )

    source = render_electron_preload(load_contract(FIXTURE))
    assert "contextBridge" in source
    assert "showNotes" in source
    assert "hideNotes" in source


def test_electron_renderers_skip_spaces_without_ui():
    from mcp_plugins.servers.grpc_host.space_contract import SpaceContract
    from mcp_plugins.servers.grpc_host.space_renderers import (
        render_electron_manager,
        render_electron_preload,
    )

    contract = load_contract(FIXTURE)
    headless = SpaceContract(
        **{**contract.model_dump(), "ui": {"embed": "none"}}
    )
    assert render_electron_manager(headless) == ""
    assert render_electron_preload(headless) == ""


def test_space_tests_cover_registry_wiring_and_status():
    from mcp_plugins.servers.grpc_host.space_renderers import (
        render_space_tests,
    )

    rendered = render_space_tests(load_contract(FIXTURE))
    assert set(rendered) == {
        "test_notes_registry.py",
        "test_notes_wiring.py",
        "test_notes_status.py",
    }


def test_rendered_space_tests_are_valid_python():
    import ast
    from mcp_plugins.servers.grpc_host.space_renderers import (
        render_space_tests,
    )

    for filename, source in render_space_tests(load_contract(FIXTURE)).items():
        tree = ast.parse(source)
        tests = [n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        assert tests, f"{filename} contains no test function"


def test_status_test_fails_on_http_error_not_just_skips():
    """FIX 3: urllib.error.HTTPError subclasses URLError, and urlopen only
    returns for a 2xx status - so a bare `except URLError: skip` (with an
    unreachable `assert response.status == 200` below it) means a live
    server answering 500 is misreported as "not running" and the test can
    only ever pass or skip, never fail. The rendered template must catch
    HTTPError ahead of URLError and fail on it, mirroring the fix already
    applied to space_cli._verify_status."""
    from mcp_plugins.servers.grpc_host.space_renderers import render_space_tests

    source = render_space_tests(load_contract(FIXTURE))["test_notes_status.py"]

    assert "urllib.error.HTTPError" in source
    assert "pytest.fail" in source
    # HTTPError is-a URLError, so its except clause must appear first in
    # source order to actually be reached.
    http_idx = source.index("except urllib.error.HTTPError")
    url_idx = source.index("except urllib.error.URLError")
    assert http_idx < url_idx

    import ast
    ast.parse(source)  # still renders to valid python


def test_registry_test_asserts_mcp_tools_present():
    """The generated test must catch the toolless-agent trap."""
    from mcp_plugins.servers.grpc_host.space_renderers import (
        render_space_tests,
    )

    source = render_space_tests(load_contract(FIXTURE))["test_notes_registry.py"]
    assert "mcp_tools" in source
    assert "notes_create" in source
