"""Turn a space contract into an ordered task list.

This is the deterministic counterpart to epic_task_generator: the artefacts
of a space and their order are fixed by the contract's shape, so no model is
needed to decide what to build or in which sequence.
"""
from __future__ import annotations

from typing import List

from .epic_task_generator import Task
from .space_contract import SpaceContract


def plan_space_tasks(contract: SpaceContract) -> List[Task]:
    """Produce the build and verify tasks for one space, in dependency order.

    Registry and manifest come first because they establish the space's
    identity; everything else refers back to them. The verify tasks depend on
    every build task, so a partial run cannot be mistaken for a finished one.
    """
    sid = contract.id
    epic_id = f"space-{sid}"
    tasks: List[Task] = []

    def add(suffix: str, task_type: str, title: str, description: str,
            deps: List[str], output_files: List[str],
            minutes: int = 5) -> str:
        task_id = f"{sid}-{suffix}"
        tasks.append(Task(
            id=task_id,
            epic_id=epic_id,
            type=task_type,
            title=title,
            description=description,
            dependencies=list(deps),
            estimated_minutes=minutes,
            output_files=list(output_files),
        ))
        return task_id

    registry = add(
        "registry", "space_registry",
        f"Register the {sid} space in the brain registry",
        f"Insert the contract-derived entry for '{sid}' under spaces: in "
        f"config/space_agent_registry.yml, including mcp_tools.",
        [], ["config/space_agent_registry.yml"],
    )

    manifest = add(
        "manifest", "space_manifest",
        f"Write the {contract.agent_name} agent manifest",
        f"Create brain/the_brain/configs/agents/{contract.agent_name}.yaml "
        f"owning all {sid}.* events.",
        [registry],
        [f"brain/the_brain/configs/agents/{contract.agent_name}.yaml"],
    )

    server = add(
        "mcp-server", "space_mcp_server",
        f"Create the {sid} MCP server",
        f"Generate the FastMCP server with one stub per contract tool, "
        f"bound to port {contract.runtime.port}.",
        [registry, manifest],
        [f"spaces/{sid}/server.py"],
        minutes=10,
    )

    build_deps = [registry, manifest, server]

    # Only spaces that declare a truth validator need a capability
    # entry - same shape as the electron task, which is skipped for a
    # headless space rather than emitted as a no-op.
    if any(e.truth is not None for e in contract.events.values()):
        capability = add(
            "capability", "space_capability",
            f"Carry the {sid} truth validators into the capability registry",
            f"Append one capabilities.yaml entry per {sid} event that "
            f"declares a truth validator - the only path from the "
            f"contract's truth: to a world_observer ground-truth "
            f"re-query.",
            [registry, manifest],
            ["brain/the_brain/data/capabilities.yaml"],
        )
        build_deps.append(capability)

    if contract.ui.embed != "none":
        electron = add(
            "electron", "space_electron",
            f"Embed the {sid} space in the Electron shell",
            f"Generate <id>-manager.js and <id>-preload.js for the "
            f"BrowserView at {contract.ui.entry_url}.",
            [server],
            [
                f"voice/electron-app/{sid}-manager.js",
                f"voice/electron-app/{sid}-preload.js",
            ],
        )
        build_deps.append(electron)

    space_tests = add(
        "tests", "space_tests",
        f"Write the {sid} verification tests",
        "Generate the registry, wiring and status tests for this space.",
        list(build_deps),
        [f"spaces/{sid}/tests/"],
    )
    build_deps.append(space_tests)

    add(
        "verify-contract", "verify_space_contract",
        f"Validate the generated {sid} space against its contract",
        "Re-validate the contract and check every declared artefact exists.",
        list(build_deps), [], minutes=3,
    )
    add(
        "verify-tests", "verify_space_tests",
        f"Run the {sid} space tests",
        f"Execute spaces/{sid}/tests/ and require them to pass.",
        list(build_deps), [], minutes=3,
    )
    add(
        "verify-status", "verify_space_status",
        f"Probe the {sid} space health endpoint",
        f"Call {contract.runtime.healthz} on port {contract.runtime.port} "
        f"and require a 200.",
        list(build_deps), [], minutes=3,
    )

    return tasks
