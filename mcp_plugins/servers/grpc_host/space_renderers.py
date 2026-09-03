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
