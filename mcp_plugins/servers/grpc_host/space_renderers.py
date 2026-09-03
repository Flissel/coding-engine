"""Renderers: contract in, artefact text out.

Every function here is pure - it reads a SpaceContract and returns a string.
Nothing touches the filesystem, so each artefact can be asserted on in a
test without a scratch directory.
"""
from __future__ import annotations

import textwrap

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
    tool_names = [t.name for t in contract.tools]

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
        '    """Liveness probe used by the space status check."""',
        '    return {"ok": True, "space": "%s"}' % contract.id,
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
