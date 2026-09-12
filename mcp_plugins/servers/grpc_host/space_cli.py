"""Command line entry point for space generation.

Writes the artefacts a contract implies, and verifies them against it.
Every failure path returns a non-zero exit code: the executor treats these
commands as gates, so silence must never look like success.
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .space_contract import ContractError, SpaceContract, load_contract
from .space_draft import draft, unattributed
from .space_intake import analyse_file
from .space_gap import (
    DEFAULT_MAX_ROUNDS,
    GapError,
    GapLimitReached,
    open_tools,
    open_tools_detailed,
    plan_gap_tasks,
)
from .space_renderers import (
    render_agent_manifest,
    render_capability_entries,
    render_electron_manager,
    render_electron_preload,
    render_mcp_server,
    render_registry_entry,
    render_space_tests,
)

REGISTRY_REL = Path("config") / "space_agent_registry.yml"
CAPABILITIES_REL = (Path("brain") / "the_brain" / "data"
                    / "capabilities.yaml")


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

    # A second space claiming a prefix an existing space already owns would
    # silently win the routing lookup: bindings_registry builds a plain
    # prefix -> binding dict, and the later insertion always overwrites the
    # earlier one. Refuse before writing anything, rather than let the new
    # space steal traffic meant for the old one.
    claimed_by: Dict[str, str] = {}
    for other_id, other_entry in spaces.items():
        if not isinstance(other_entry, dict):
            continue
        for prefix in other_entry.get("prefixes") or []:
            claimed_by.setdefault(prefix, other_id)
    for prefix in contract.prefixes:
        if prefix in claimed_by:
            print(
                f"ERROR: prefix '{prefix}' is already claimed by space "
                f"'{claimed_by[prefix]}' in {registry_path} - refusing to "
                f"register '{contract.id}' with a colliding prefix",
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
        # isinstance guard, not just `entry is not None`: a mis-nested
        # append can land contract.id on a scalar or list rather than a
        # mapping, and entry.get(...) on that raises AttributeError - which
        # must count as "did not land", not propagate past the rollback.
        landed = isinstance(entry, dict) and entry.get("agent") == contract.agent_name
    except Exception:
        # Anything going wrong while re-reading the just-written file - a
        # transient OSError, malformed YAML, or the AttributeError above if
        # the guard above were ever bypassed - means we cannot confirm the
        # insertion landed correctly. Treat that the same as "did not
        # land" so the rollback below always runs; propagating here would
        # leave the shared registry in whatever half-written state the
        # append produced.
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


def _render_capabilities(target: Path, contract: SpaceContract) -> int:
    """Append the space's capability entries to capabilities.yaml.

    Same append-then-verify-then-rollback discipline as the registry: the
    file is a shared, comment-heavy top-level list, so a parse-and-rewrite
    would destroy the comments and a blind append can leave it broken.
    """
    fragment = render_capability_entries(contract)
    if not fragment:
        print(f"space '{contract.id}' declares no truth validators - "
              f"no capability entries")
        return 0

    path = target / CAPABILITIES_REL
    if not path.is_file():
        print(f"ERROR: capabilities file not found: {path}", file=sys.stderr)
        return 1

    original_text = path.read_text(encoding="utf-8")
    existing = yaml.safe_load(original_text) or []
    if not isinstance(existing, list):
        print(
            f"ERROR: capabilities file is not a YAML list: {path}",
            file=sys.stderr,
        )
        return 1
    known = {
        e.get("capability") for e in existing if isinstance(e, dict)
    }
    wanted = [
        e["capability"] for e in (yaml.safe_load(fragment) or [])
    ]
    clash = sorted(set(wanted) & known)
    if clash:
        print(
            f"ERROR: capability {clash} already exists in {path} - "
            f"refusing to append a second entry (capability_router takes "
            f"the first match, so the new one would never be reached)",
            file=sys.stderr,
        )
        return 1

    text = original_text
    if not text.endswith(chr(10)):
        text += chr(10)
    path.write_text(text + chr(10) + fragment, encoding="utf-8")

    try:
        written = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        by_name = {
            e.get("capability"): e
            for e in written if isinstance(e, dict)
        }
        landed = all(
            isinstance(by_name.get(name), dict)
            and isinstance(by_name[name].get("validator"), dict)
            for name in wanted
        )
    except Exception:
        # Cannot confirm the append parsed back - treat as "did not land"
        # so the rollback runs rather than leaving a shared file broken.
        landed = False

    if not landed:
        path.write_text(original_text, encoding="utf-8")
        print(
            f"ERROR: capability append for '{contract.id}' did not parse "
            f"back out of {path} (original file restored)",
            file=sys.stderr,
        )
        return 1

    print(f"added capabilities {wanted} to {path}")
    return 0


def _do_draft(space_id: Optional[str], target: Path,
              show_unattributed: bool) -> int:
    """Entwurf eines schlanken Vertrags - ein Vorschlag, kein Befund."""
    if show_unattributed:
        rows = unattributed(target)
        if not rows:
            print("every enabled capability matches some space prefix")
            return 0
        print(f"{len(rows)} capabilities match no space prefix:")
        for name, target_str in rows:
            print(f"  {name}  ->  {target_str}")
        # Kein Fehler: das ist ein Befund, keine Verletzung. Wer daraus eine
        # Luecke macht, muss erst entscheiden, ob jede Capability zu einem
        # Space gehoeren MUSS - das ist heute nicht so.
        return 0

    if not space_id:
        print("ERROR: --space is required unless --unattributed is given",
              file=sys.stderr)
        return 1
    try:
        text, open_ones = draft(space_id, target)
    except KeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(text)
    if open_ones:
        print(f"# {len(open_ones)} open: writes could not be derived from the "
              f"execution target.", file=sys.stderr)
        for name in open_ones:
            print(f"#   {name}", file=sys.stderr)
        return 1
    return 0


def _do_intake(contract_path: Path, target: Optional[Path]) -> int:
    """Pruefe einen Vertragsentwurf, bevor irgendetwas gerendert wird.

    Absichtlich NICHT ueber load_contract: der Entwurf ist noch keiner. Eine
    Ausnahme waere hier die falsche Antwort - gefragt ist die Liste dessen,
    was fehlt, damit der naechste Entwurf besser wird.
    """
    result = analyse_file(contract_path, target=target)
    if result.ok:
        print(f"contract complete: {result.contract.id}")
        return 0

    print(f"ERROR: {len(result.gaps)} gap(s) in {contract_path}:",
          file=sys.stderr)
    for gap in result.gaps:
        print(f"  - {gap.as_line()}", file=sys.stderr)
    if any(gap.field == "contract" for gap in result.gaps):
        # Der Model-Validator des Vertrags haelt beim ersten Verstoss
        # an. Ohne diesen Hinweis liest sich "1 gap" wie "nur noch
        # eine Sache" - und der naechste Entwurf scheitert erneut.
        # Die Regeln hier ein zweites Mal zu sammeln waere Drift.
        print("  (further contract rules are only checked once this "
              "one is fixed)", file=sys.stderr)
    return 1


def _do_gap(target: Path, contract: SpaceContract, round_no: int,
            max_rounds: int) -> int:
    """Vertrag gegen Ist - und was daraus an Nacharbeit folgt.

    Drei Ausgaenge, absichtlich unterscheidbar: 0 keine Luecke, 1 Luecken
    mit verbleibenden Runden, 2 Runden erschoepft. Ein Aufrufer, der 1 und
    2 nicht trennen kann, laesst den Loop entweder ewig laufen oder bricht
    zu frueh ab.
    """
    try:
        gaps = open_tools(target, contract)
    except GapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not gaps:
        print(f"no gaps: {contract.id}")
        return 0

    try:
        tasks = plan_gap_tasks(contract, gaps, round_no=round_no,
                               max_rounds=max_rounds)
    except GapLimitReached as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"round {round_no}/{max_rounds} - {len(gaps)} open:")
    for name in gaps:
        print(f"  {name}")
    print(f"{len(tasks)} follow-up tasks planned")
    return 1


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
    if artefact == "capability":
        return _render_capabilities(target, contract)
    if artefact == "all":
        for step in ("registry", "manifest", "mcp-server", "electron",
                     "tests", "capability"):
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

    # A declared truth validator only runs if it reaches world_observer,
    # and the single path there is capabilities.yaml ->
    # capability_router.get_capability()["validator"] -> plan_executor's
    # hop.validator -> CapabilityValidator. An event whose contract
    # declares truth but whose capability entry is missing or carries a
    # different postcondition would route with no ground-truth re-query
    # while every other gate reported green.
    truth_events = {
        name: event for name, event in contract.events.items()
        if event.truth is not None
    }
    if truth_events:
        cap_path = target / CAPABILITIES_REL
        if not cap_path.is_file():
            problems.append(f"capabilities file missing: {cap_path}")
        else:
            try:
                caps = yaml.safe_load(cap_path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                caps = None
                problems.append(f"capabilities file is not valid YAML: {exc}")
            by_name = {
                c.get("capability"): c
                for c in (caps or []) if isinstance(c, dict)
            }
            for name, event in sorted(truth_events.items()):
                entry = by_name.get(event.tool)
                if not isinstance(entry, dict):
                    problems.append(
                        f"event '{name}' declares a truth validator but "
                        f"capability '{event.tool}' is not in {cap_path} - "
                        f"the ground-truth re-query would never run"
                    )
                    continue
                validator = entry.get("validator")
                if not isinstance(validator, dict):
                    problems.append(
                        f"capability '{event.tool}' carries no validator "
                        f"block, so event '{name}' routes unverified"
                    )
                    continue
                if validator.get("kind") != event.truth.kind:
                    problems.append(
                        f"capability '{event.tool}' validator kind "
                        f"{validator.get('kind')!r} != contract "
                        f"{event.truth.kind!r}"
                    )
                expected_post = event.truth.postcondition()
                if validator.get("postcondition") != expected_post:
                    problems.append(
                        f"capability '{event.tool}' postcondition "
                        f"{validator.get('postcondition')!r} != contract "
                        f"{expected_post!r}"
                    )

    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print(f"contract satisfied: {contract.id}")
    return 0


def _verify_fill(target: Path, contract: SpaceContract) -> int:
    """Every contract tool must have stopped raising NotImplementedError.

    This is the gate that makes "filled" a fact instead of a claim. It
    shares its reading with the gap loop (space_gap.open_tools_detailed):
    two answers to the same question must not be able to drift apart.
    """
    try:
        gaps = open_tools_detailed(target, contract)
    except GapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if gaps:
        for name, reason in gaps:
            print(f"ERROR: contract tool not implemented: {name} ({reason})",
                  file=sys.stderr)
        return 1

    print(f"all {len(contract.tools)} contract tools implemented: "
          f"{contract.id}")
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
    if check == "fill":
        return _verify_fill(target, contract)
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
        "registry", "manifest", "mcp-server", "electron", "tests",
        "capability", "all",
    ])
    draft_p = sub.add_parser(
        "draft",
        help="propose a lean contract for an existing space")
    draft_p.add_argument("--space", default=None,
                         help="space id from the registry")
    draft_p.add_argument("--target", required=True,
                         help="vibemind-os root")
    draft_p.add_argument("--unattributed", action="store_true",
                         help="list capabilities matching no space")
    intake = sub.add_parser(
        "intake",
        help="check a contract draft and name what it still lacks")
    intake.add_argument("--contract", required=True,
                        help="path to the draft contract YAML")
    intake.add_argument("--target", default=None,
                        help="vibemind-os root; without it no id or prefix claims are checked")
    gap = sub.add_parser(
        "gap", help="contract vs. generated code, and the rework it implies")
    gap.add_argument("--round", type=int, default=1,
                     help="which gap round this is (ids derive from it)")
    gap.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS,
                     help="refuse further rounds beyond this")
    verify = sub.add_parser("verify", help="check artefacts against contract")
    verify.add_argument("check", choices=["contract", "fill", "tests", "status"])

    for p in (render, verify, gap):
        p.add_argument("--contract", required=True,
                       help="path to the space contract YAML")
        p.add_argument("--target", required=True,
                       help="vibemind-os root to write into / check")

    args = parser.parse_args(argv)

    if args.command == "draft":
        return _do_draft(args.space, Path(args.target), args.unattributed)

    if args.command == "intake":
        return _do_intake(
            Path(args.contract),
            Path(args.target) if args.target else None,
        )

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
    if args.command == "gap":
        return _do_gap(target, contract, args.round, args.max_rounds)
    return _do_verify(args.check, target, contract)


if __name__ == "__main__":
    raise SystemExit(main())
