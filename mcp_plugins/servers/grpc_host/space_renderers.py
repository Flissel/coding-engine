"""Renderers: contract in, artefact text out.

Every function here is pure - it reads a SpaceContract and returns a string.
Nothing touches the filesystem, so each artefact can be asserted on in a
test without a scratch directory.
"""
from __future__ import annotations

import textwrap
from typing import Dict

import yaml

from .space_contract import SpaceContract


def mcp_server_name(contract: SpaceContract) -> str:
    """Naming convention for a space's MCP server."""
    return f"spaces-{contract.id}"


def render_registry_entry(contract: SpaceContract) -> str:
    """Render the space's entry for config/space_agent_registry.yml.

    Returned text is indented by two spaces so it can be inserted directly
    under the file's top-level `spaces:` key.
    """
    server = mcp_server_name(contract)
    # Sorted, not declaration order: two contracts with the same tools must
    # produce the same registry regardless of how they happen to list them
    # (this also keeps it consistent with render_space_tests, which asserts
    # sorted order).
    tool_names = sorted(t.name for t in contract.tools)

    events: dict = {}
    for name, event in contract.events.items():
        rendered: dict = {
            "tool": event.tool,
            "required_params": list(event.required_params),
        }
        if event.required_provenance:
            rendered["required_provenance"] = list(event.required_provenance)
            rendered["execution"] = {"kind": "mcp", "server": server}
        events[name] = rendered

    entry = {
        contract.id: {
            "agent": contract.agent_name,
            "prefixes": list(contract.prefixes),
            "enabled": True,
            "description": contract.description,
            "mcp_servers": [server],
            # The agent's tool list is derived from mcp_tools only
            # (scripts/sync_openfang_agents.py:100-105). Without this the
            # agent starts with no tools at all.
            "mcp_tools": {server: tool_names},
            "system_prompt_hint": (
                f"You operate the {contract.id} space. "
                "Use the preferred_tool hint from the intent envelope; only "
                "call other tools if the hint fails."
            ),
            "default_context": ["current_space", "session_id"],
            "events": events,
        }
    }

    body = yaml.safe_dump(entry, sort_keys=False, allow_unicode=True,
                          default_flow_style=False)
    return textwrap.indent(body, "  ")


def render_agent_manifest(contract: SpaceContract) -> str:
    """Render brain/the_brain/configs/agents/brain-<id>.yaml.

    Shape follows the existing brain-video.yaml: the agent owns every event
    in its namespace, and the notes block records where the wiring lives.
    """
    manifest = {
        "agent": contract.agent_name,
        "description": contract.description,
        "default_namespace": contract.id,
        "events": sorted(contract.events),
        "notes": (
            f"{contract.agent_name} owns all {contract.id}.* events. Tool "
            f"bindings live in config/space_agent_registry.yml, not here. "
            f"Generated from the space contract."
        ),
    }
    return yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True,
                          default_flow_style=False)


def render_mcp_server(contract: SpaceContract) -> str:
    """Render the space's FastMCP server with one stub per tool.

    Stubs raise NotImplementedError on purpose. A stub that returned an
    empty result would let the whole chain report success while doing
    nothing - the failure mode the truth validators exist to prevent.
    """
    server = mcp_server_name(contract)
    lines = [
        '"""MCP server for the %s space.' % contract.id,
        "",
        "Generated from the space contract. Tool bodies are stubs; each one",
        "raises until it is implemented.",
        '"""',
        "from __future__ import annotations",
        "",
        "import os",
        "from typing import Any, Dict",
        "",
        "from mcp.server.fastmcp import FastMCP",
        "from starlette.requests import Request",
        "from starlette.responses import JSONResponse",
        "",
        'HOST = os.environ.get("%s_HOST", "127.0.0.1")' % contract.id.upper(),
        'PORT = int(os.environ.get("%s_PORT", "%d"))'
        % (contract.id.upper(), contract.runtime.port),
        "",
        'mcp = FastMCP("%s", host=HOST, port=PORT)' % server,
        "",
        "",
        "@mcp.tool()",
        "def healthz() -> Dict[str, Any]:",
        '    """Liveness probe used by the space status check (MCP-tool form)."""',
        '    return {"ok": True, "space": "%s"}' % contract.id,
        "",
        "",
        # FastMCP only mounts /sse and /messages/ on the transport it runs;
        # @mcp.tool() alone is an MCP-protocol call, not an HTTP route, so a
        # plain GET against contract.runtime.healthz would 404. This route
        # is what actually answers that path over HTTP.
        '@mcp.custom_route("%s", methods=["GET"])' % contract.runtime.healthz,
        "async def healthz_http(request: Request) -> JSONResponse:",
        '    """HTTP liveness probe at %s (used by the status check test)."""'
        % contract.runtime.healthz,
        '    return JSONResponse({"ok": True, "space": "%s"})' % contract.id,
        "",
    ]

    for tool in contract.tools:
        params = ", ".join(f"{p}: str" for p in tool.params)
        lines += [
            "",
            "@mcp.tool()",
            f"def {tool.name}({params}) -> Dict[str, Any]:",
            f'    """{tool.side_effect} operation: {tool.name}."""',
            f'    raise NotImplementedError("{tool.name} is not implemented yet")',
            "",
        ]

    lines += [
        "",
        'if __name__ == "__main__":',
        '    mcp.run(transport="sse")',
        "",
    ]
    return "\n".join(lines)


def _camel(space_id: str) -> str:
    """notes -> Notes, my_space -> MySpace."""
    return "".join(part.capitalize() for part in space_id.replace("-", "_").split("_"))


def render_electron_manager(contract: SpaceContract) -> str:
    """Render voice/electron-app/<id>-manager.js.

    Returns an empty string for headless spaces, so the caller can simply
    skip writing the file.
    """
    if contract.ui.embed == "none":
        return ""

    name = _camel(contract.id)
    return f"""// {contract.id}-manager.js - generated from the space contract.
// Embeds the {contract.id} space as a BrowserView in the main window.
const {{ BrowserView }} = require('electron');

const ENTRY_URL = '{contract.ui.entry_url}';

let view = null;

function show{name}(mainWindow) {{
  if (!view) {{
    view = new BrowserView({{
      webPreferences: {{ contextIsolation: true, nodeIntegration: false }},
    }});
    view.webContents.loadURL(ENTRY_URL);
  }}
  mainWindow.addBrowserView(view);
  const {{ width, height }} = mainWindow.getContentBounds();
  view.setBounds({{ x: 0, y: 0, width, height }});
  view.setAutoResize({{ width: true, height: true }});
  return view;
}}

function hide{name}(mainWindow) {{
  if (view) {{
    mainWindow.removeBrowserView(view);
  }}
}}

module.exports = {{ show{name}, hide{name} }};
"""


def render_electron_preload(contract: SpaceContract) -> str:
    """Render voice/electron-app/<id>-preload.js."""
    if contract.ui.embed == "none":
        return ""

    name = _camel(contract.id)
    return f"""// {contract.id}-preload.js - generated from the space contract.
const {{ contextBridge, ipcRenderer }} = require('electron');

contextBridge.exposeInMainWorld('vibemind{name}', {{
  show{name}: () => ipcRenderer.invoke('{contract.id}:show'),
  hide{name}: () => ipcRenderer.invoke('{contract.id}:hide'),
}});
"""


def render_space_tests(contract: SpaceContract) -> Dict[str, str]:
    """Render the three tests that verify a generated space.

    They assert the space against its own contract: the registry entry is
    complete (including mcp_tools, whose absence silently leaves the agent
    without tools), the agent manifest owns the events, and the runtime
    answers its health probe.
    """
    sid = contract.id
    server = mcp_server_name(contract)
    tool_names = sorted(t.name for t in contract.tools)
    event_names = sorted(contract.events)
    write_events = sorted(
        name for name, event in contract.events.items()
        if event.required_provenance
    )

    registry = f'''"""Registry wiring for the {sid} space (generated)."""
from pathlib import Path

import yaml

REGISTRY = (
    Path(__file__).resolve().parents[3] / "config" / "space_agent_registry.yml"
)


def _entry() -> dict:
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    return data["spaces"]["{sid}"]


def test_space_is_registered_and_enabled():
    entry = _entry()
    assert entry["agent"] == "{contract.agent_name}"
    assert entry["enabled"] is True
    assert entry["prefixes"] == {contract.prefixes!r}


def test_agent_receives_its_tools():
    """Tools come from mcp_tools alone - an empty key means no tools."""
    entry = _entry()
    assert entry["mcp_tools"]["{server}"] == {tool_names!r}


def test_all_contract_events_are_registered():
    entry = _entry()
    assert sorted(entry["events"]) == {event_names!r}


def test_write_events_require_provenance():
    entry = _entry()
    for name in {write_events!r}:
        assert entry["events"][name]["required_provenance"]
'''

    wiring = f'''"""Agent manifest for the {sid} space (generated)."""
from pathlib import Path

import yaml

MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "brain" / "the_brain" / "configs" / "agents" / "{contract.agent_name}.yaml"
)


def test_manifest_exists_and_names_the_agent():
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert data["agent"] == "{contract.agent_name}"
    assert data["default_namespace"] == "{sid}"


def test_manifest_owns_every_contract_event():
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert sorted(data["events"]) == {event_names!r}
'''

    status = f'''"""Runtime health probe for the {sid} space (generated)."""
import os
import urllib.error
import urllib.request

import pytest

PORT = int(os.environ.get("{sid.upper()}_PORT", "{contract.runtime.port}"))
URL = f"http://127.0.0.1:{{PORT}}{contract.runtime.healthz}"


def test_status_probe_answers():
    """Skips when the space is not running; fails when it answers wrongly."""
    try:
        with urllib.request.urlopen(URL, timeout=3) as response:
            assert response.status == 200
    except urllib.error.URLError as exc:
        pytest.skip(f"{sid} space not running on {{PORT}}: {{exc}}")
'''

    return {
        f"test_{sid}_registry.py": registry,
        f"test_{sid}_wiring.py": wiring,
        f"test_{sid}_status.py": status,
    }
