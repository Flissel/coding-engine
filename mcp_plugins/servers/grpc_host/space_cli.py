"""Command line entry point for space generation.

Writes the artefacts a contract implies, and verifies them against it.
Every failure path returns a non-zero exit code: the executor treats these
commands as gates, so silence must never look like success.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

import yaml

from .space_contract import ContractError, SpaceContract, load_contract
from .space_renderers import (
    render_agent_manifest,
    render_electron_manager,
    render_electron_preload,
    render_mcp_server,
    render_registry_entry,
    render_space_tests,
)

REGISTRY_REL = Path("config") / "space_agent_registry.yml"


def _manifest_path(target: Path, contract: SpaceContract) -> Path:
    return (target / "brain" / "the_brain" / "configs" / "agents"
            / f"{contract.agent_name}.yaml")


def _server_path(target: Path, contract: SpaceContract) -> Path:
    return target / "spaces" / contract.id / "server.py"


def _tests_dir(target: Path, contract: SpaceContract) -> Path:
    return target / "spaces" / contract.id / "tests"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path}")


def _render_registry(target: Path, contract: SpaceContract) -> int:
    """Insert the contract's entry into config/space_agent_registry.yml.

    The insertion is a raw textual append under the assumption that
    `spaces:` is the last top-level block in the file - deliberately, since
    a parse-and-rewrite would destroy the comments the real registry
    carries. That assumption does not always hold (no `spaces:` key at all,
    or another top-level key after the spaces block), so every append is
    checked afterwards and rolled back if it did not land where expected.
    """
    registry_path = target / REGISTRY_REL
    if not registry_path.is_file():
        print(f"ERROR: registry not found: {registry_path}", file=sys.stderr)
        return 1

    original_text = registry_path.read_text(encoding="utf-8")
    data = yaml.safe_load(original_text) or {}
    spaces = data.get("spaces")
    if not isinstance(spaces, dict):
        print(
            f"ERROR: registry has no 'spaces' mapping: {registry_path}",
            file=sys.stderr,
        )
        return 1
    if contract.id in spaces:
        print(
            f"ERROR: space '{contract.id}' already registered - refusing to "
            f"overwrite",
            file=sys.stderr,
        )
        return 1

    fragment = render_registry_entry(contract)
    text = original_text
    if not text.endswith("\n"):
        text += "\n"
    registry_path.write_text(text + fragment, encoding="utf-8")

    # Verify the append actually landed under `spaces:` rather than trusting
    # the textual append blindly - it silently mis-nests when a top-level
    # key follows the spaces block, or produces broken YAML when there was
    # no `spaces:` key to begin with.
    try:
        written = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        entry = (written.get("spaces") or {}).get(contract.id)
        landed = entry is not None and entry.get("agent") == contract.agent_name
    except yaml.YAMLError:
        landed = False

    if not landed:
        registry_path.write_text(original_text, encoding="utf-8")
        print(
            f"ERROR: registry insertion for '{contract.id}' did not land "
            f"under 'spaces:' in {registry_path} (original file restored) "
            f"- the append assumes 'spaces:' is the last top-level block, "
            f"which does not hold here",
            file=sys.stderr,
        )
        return 1

    print(f"registered '{contract.id}' in {registry_path}")
    return 0


def _render_electron(target: Path, contract: SpaceContract) -> int:
    manager = render_electron_manager(contract)
    if not manager:
        print(f"space '{contract.id}' is headless - no electron artefacts")
        return 0
    base = target / "voice" / "electron-app"
    _write(base / f"{contract.id}-manager.js", manager)
    _write(base / f"{contract.id}-preload.js",
           render_electron_preload(contract))
    return 0


def _render_tests(target: Path, contract: SpaceContract) -> int:
    tests_dir = _tests_dir(target, contract)
    for filename, source in render_space_tests(contract).items():
        _write(tests_dir / filename, source)
    return 0


def _do_render(artefact: str, target: Path, contract: SpaceContract) -> int:
    if artefact == "registry":
        return _render_registry(target, contract)
    if artefact == "manifest":
        _write(_manifest_path(target, contract), render_agent_manifest(contract))
        return 0
    if artefact == "mcp-server":
        _write(_server_path(target, contract), render_mcp_server(contract))
        return 0
    if artefact == "electron":
        return _render_electron(target, contract)
    if artefact == "tests":
        return _render_tests(target, contract)
    if artefact == "all":
        for step in ("registry", "manifest", "mcp-server", "electron", "tests"):
            code = _do_render(step, target, contract)
            if code != 0:
                return code
        return 0
    print(f"ERROR: unknown artefact '{artefact}'", file=sys.stderr)
    return 1


def _verify_contract(target: Path, contract: SpaceContract) -> int:
    """Every artefact the contract implies must exist and be consistent."""
    problems: List[str] = []

    registry_path = target / REGISTRY_REL
    if not registry_path.is_file():
        problems.append(f"registry missing: {registry_path}")
    else:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        entry = (data.get("spaces") or {}).get(contract.id)
        if entry is None:
            problems.append(f"space '{contract.id}' not in registry")
        else:
            server_key = f"spaces-{contract.id}"
            tools = (entry.get("mcp_tools") or {}).get(server_key) or []
            expected = sorted(t.name for t in contract.tools)
            if sorted(tools) != expected:
                problems.append(
                    f"mcp_tools mismatch: {sorted(tools)} != {expected}"
                )
            if sorted(entry.get("events") or {}) != sorted(contract.events):
                problems.append("registry events do not match the contract")
            if entry.get("agent") != contract.agent_name:
                problems.append(
                    f"registry agent mismatch: {entry.get('agent')!r} != "
                    f"{contract.agent_name!r}"
                )
            if list(entry.get("prefixes") or []) != list(contract.prefixes):
                problems.append(
                    f"registry prefixes mismatch: "
                    f"{entry.get('prefixes')!r} != {contract.prefixes!r}"
                )
            entry_events = entry.get("events") or {}
            for name, event in contract.events.items():
                bound = (entry_events.get(name) or {}).get("tool")
                if bound != event.tool:
                    problems.append(
                        f"event '{name}' bound to tool {bound!r} in "
                        f"registry, contract expects {event.tool!r}"
                    )

    manifest_path = _manifest_path(target, contract)
    if not manifest_path.is_file():
        problems.append(f"agent manifest missing: {manifest_path}")

    server_path = _server_path(target, contract)
    if not server_path.is_file():
        problems.append(f"mcp server missing: {server_path}")

    if contract.ui.embed != "none":
        base = target / "voice" / "electron-app"
        for name in (f"{contract.id}-manager.js", f"{contract.id}-preload.js"):
            if not (base / name).is_file():
                problems.append(f"electron artefact missing: {base / name}")

    tests_dir = _tests_dir(target, contract)
    for name in render_space_tests(contract):
        if not (tests_dir / name).is_file():
            problems.append(f"test missing: {tests_dir / name}")

    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print(f"contract satisfied: {contract.id}")
    return 0


def _verify_tests(target: Path, contract: SpaceContract) -> int:
    tests_dir = _tests_dir(target, contract)
    if not tests_dir.is_dir():
        print(f"ERROR: no tests at {tests_dir}", file=sys.stderr)
        return 1
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tests_dir), "-q"],
        cwd=str(target), capture_output=True, text=True,
    )
    print(result.stdout[-4000:])
    if result.returncode != 0:
        print(result.stderr[-2000:], file=sys.stderr)
    return result.returncode


def _verify_status(target: Path, contract: SpaceContract) -> int:
    url = (f"http://127.0.0.1:{contract.runtime.port}"
           f"{contract.runtime.healthz}")
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status != 200:
                print(f"ERROR: {url} answered {response.status}",
                      file=sys.stderr)
                return 1
    except urllib.error.HTTPError as exc:
        # HTTPError is a URLError subclass, so it must be caught first: the
        # server is up and answering, just with an error status - a
        # different failure than "not running" and worth telling apart.
        print(f"ERROR: {url} answered HTTP {exc.code}: {exc.reason}",
              file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"ERROR: {url} unreachable: {exc}", file=sys.stderr)
        return 1
    print(f"status ok: {url}")
    return 0


def _do_verify(check: str, target: Path, contract: SpaceContract) -> int:
    if check == "contract":
        return _verify_contract(target, contract)
    if check == "tests":
        return _verify_tests(target, contract)
    if check == "status":
        return _verify_status(target, contract)
    print(f"ERROR: unknown check '{check}'", file=sys.stderr)
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="space_cli",
        description="Render and verify VibeMind space artefacts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render", help="write artefacts")
    render.add_argument("artefact", choices=[
        "registry", "manifest", "mcp-server", "electron", "tests", "all",
    ])
    verify = sub.add_parser("verify", help="check artefacts against contract")
    verify.add_argument("check", choices=["contract", "tests", "status"])

    for p in (render, verify):
        p.add_argument("--contract", required=True,
                       help="path to the space contract YAML")
        p.add_argument("--target", required=True,
                       help="vibemind-os root to write into / check")

    args = parser.parse_args(argv)

    try:
        contract = load_contract(Path(args.contract))
    except ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pydantic ValidationError and anything else
        print(f"ERROR: invalid contract: {exc}", file=sys.stderr)
        return 1

    target = Path(args.target)
    if args.command == "render":
        return _do_render(args.artefact, target, contract)
    return _do_verify(args.check, target, contract)


if __name__ == "__main__":
    raise SystemExit(main())
