"""Fill: der Schritt, der aus dem Geruest echten Code macht.

Der Beweis dafuer darf kein Selbstbericht des Modells sein. `verify fill`
liest den erzeugten Server und stellt fest, welche Vertrags-Tools noch
`NotImplementedError` werfen - ein Tool, das der Vertrag nennt und das
weiterhin nur wirft, ist nicht gefuellt, egal was der Lauf meldet.
"""
from pathlib import Path

import pytest
import yaml

from mcp_plugins.servers.grpc_host.space_cli import main
from mcp_plugins.servers.grpc_host.space_contract import SpaceContract
from mcp_plugins.servers.grpc_host.space_task_planner import plan_space_tasks

FIXTURE = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"


def _target(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "space_agent_registry.yml").write_text(
        "version: 1\nspaces:\n  existing:\n    agent: brain-existing\n",
        encoding="utf-8",
    )
    (tmp_path / "brain" / "the_brain" / "configs" / "agents").mkdir(parents=True)
    (tmp_path / "brain" / "the_brain" / "data").mkdir(parents=True)
    (tmp_path / "brain" / "the_brain" / "data" / "capabilities.yaml").write_text(
        "# capability registry\n- capability: existing_cap\n"
        '  description: "an unrelated capability"\n'
        '  execution_target: "direct:nothing"\n',
        encoding="utf-8",
    )
    (tmp_path / "voice" / "electron-app").mkdir(parents=True)
    return tmp_path


def _server_path(target: Path) -> Path:
    return target / "spaces" / "notes" / "server.py"


# ---------------------------------------------------------------------
# Das Gate
# ---------------------------------------------------------------------

def test_freshly_scaffolded_space_is_not_filled(tmp_path, capsys):
    """Direkt nach dem Scaffold wirft jedes Tool noch - verify fill muss
    rot sein und JEDES offene Tool namentlich nennen."""
    target = _target(tmp_path)
    assert main(["render", "all", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0

    assert main(["verify", "fill", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1
    err = capsys.readouterr().err
    assert "notes_list" in err
    assert "notes_create" in err


def test_a_filled_tool_no_longer_counts_as_open(tmp_path, capsys):
    target = _target(tmp_path)
    main(["render", "all", "--contract", str(FIXTURE), "--target", str(target)])

    path = _server_path(target)
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        '    raise NotImplementedError("notes_list is not implemented yet")',
        '    return {"items": []}',
    )
    path.write_text(source, encoding="utf-8")

    assert main(["verify", "fill", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1
    err = capsys.readouterr().err
    assert "notes_create" in err
    assert "notes_list" not in err


def test_all_tools_filled_passes(tmp_path, capsys):
    target = _target(tmp_path)
    main(["render", "all", "--contract", str(FIXTURE), "--target", str(target)])

    path = _server_path(target)
    source = path.read_text(encoding="utf-8")
    for tool, body in (("notes_list", '    return {"items": []}'),
                       ("notes_create", '    return {"id": "x"}')):
        source = source.replace(
            f'    raise NotImplementedError("{tool} is not implemented yet")',
            body,
        )
    path.write_text(source, encoding="utf-8")

    assert main(["verify", "fill", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0
    assert "all 2 contract tools implemented" in capsys.readouterr().out


def test_a_tool_that_raises_deeper_still_counts_as_open(tmp_path, capsys):
    """Ein Tool, das nach etwas Beiwerk immer noch nur NotImplementedError
    wirft, ist nicht gefuellt - sonst genuegt eine Logzeile davor, um das
    Gate zu taeuschen."""
    target = _target(tmp_path)
    main(["render", "all", "--contract", str(FIXTURE), "--target", str(target)])

    path = _server_path(target)
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        '    raise NotImplementedError("notes_list is not implemented yet")',
        '    _ = 1\n    raise NotImplementedError("later")',
    )
    path.write_text(source, encoding="utf-8")

    assert main(["verify", "fill", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1
    assert "notes_list" in capsys.readouterr().err


def test_missing_tool_function_is_reported_not_silently_passed(tmp_path,
                                                               capsys):
    """Ein Tool, dessen Funktion ganz fehlt, darf nicht als gefuellt
    durchgehen - 'nicht vorhanden' ist kein 'implementiert'."""
    target = _target(tmp_path)
    main(["render", "all", "--contract", str(FIXTURE), "--target", str(target)])

    path = _server_path(target)
    source = path.read_text(encoding="utf-8")
    # Den ganzen Block entfernen, nicht nur die def-Zeile: ein
    # verwaister Rumpf waere ein Syntaxfehler und damit ein anderer Fall.
    start = source.rindex("@mcp.tool()", 0, source.index("def notes_create("))
    nxt = source.find("@mcp.tool()", start + 1)
    end = nxt if nxt != -1 else len(source)
    path.write_text(source[:start] + source[end:], encoding="utf-8")

    assert main(["verify", "fill", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1
    err = capsys.readouterr().err
    assert "notes_create" in err
    assert "no function of that name" in err

def test_verify_fill_without_a_server_fails_loudly(tmp_path, capsys):
    target = _target(tmp_path)
    assert main(["verify", "fill", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1
    assert "mcp server missing" in capsys.readouterr().err


# ---------------------------------------------------------------------
# Die Planung
# ---------------------------------------------------------------------

def _tasks():
    return plan_space_tasks(SpaceContract(
        **yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))))


def test_one_fill_task_per_contract_tool():
    fills = [t for t in _tasks() if t.type == "space_fill_tool"]
    assert len(fills) == 2
    titles = " ".join(t.title for t in fills)
    assert "notes_list" in titles and "notes_create" in titles


def test_fill_waits_for_the_scaffolded_server():
    tasks = {t.id: t for t in _tasks()}
    server = next(t for t in tasks.values() if t.type == "space_mcp_server")
    for fill in (t for t in tasks.values() if t.type == "space_fill_tool"):
        assert server.id in fill.dependencies


def test_verification_waits_for_every_fill_task():
    tasks = list(_tasks())
    fill_ids = {t.id for t in tasks if t.type == "space_fill_tool"}
    fill_gate = next(t for t in tasks if t.type == "verify_space_fill")
    assert fill_ids <= set(fill_gate.dependencies)
    for verify in (t for t in tasks if t.type == "verify_space_tests"):
        assert fill_gate.id in verify.dependencies, (
            "the tests would run against unfilled stubs"
        )


def test_fill_tasks_carry_the_contract_and_the_target_file():
    fills = [t for t in _tasks() if t.type == "space_fill_tool"]
    for task in fills:
        assert "spaces/notes/server.py" in task.output_files
        assert "notes" in task.description


def test_a_write_tool_fill_names_its_obligations():
    """Ein schreibendes Tool traegt Provenance- und Truth-Pflichten. Wer
    das beim Fuellen nicht mitbekommt, baut sie nicht ein."""
    fill = next(t for t in _tasks()
                if t.type == "space_fill_tool" and "notes_create" in t.title)
    assert "write" in fill.description
    assert "approval_ref" in fill.description
    assert "truth:supabase_row" in fill.description


# ---------------------------------------------------------------------
# Die Ausfuehrung
# ---------------------------------------------------------------------

def test_fill_is_a_model_task_not_a_bash_task():
    from mcp_plugins.servers.grpc_host.task_executor import (
        TASK_SKILL_MAPPING, VERIFICATION_COMMANDS,
    )
    agent, skill, claude_agent, _ = TASK_SKILL_MAPPING["space_fill_tool"]
    # Anything that is not one of the special names routes to _execute_claude.
    assert agent not in ("BashExecutor", "CheckpointHandler",
                         "NotificationHandler", "DockerAgent")
    # Ein claude_agent wird NICHT verlangt: das entscheidet der
    # Executor-Typ. .claude/agents/coder.md waere hier sogar falsch
    # (TypeScript/React/NestJS), also ist None die richtige Angabe.
    assert skill == "space-tool-implementation"
    assert "space_fill_tool" not in VERIFICATION_COMMANDS

    assert TASK_SKILL_MAPPING["verify_space_fill"][0] == "BashExecutor"
    assert VERIFICATION_COMMANDS["verify_space_fill"].endswith("verify fill")


def test_the_skill_the_fill_task_names_exists():
    from mcp_plugins.servers.grpc_host.task_executor import TASK_SKILL_MAPPING
    _, skill, _, _ = TASK_SKILL_MAPPING["space_fill_tool"]
    root = Path(__file__).resolve().parents[1]
    assert (root / ".claude" / "skills" / skill).is_dir(), (
        f"skill {skill!r} named by the mapping does not exist"
    )

def _space_context(task):
    from mcp_plugins.servers.grpc_host.task_executor import TaskExecutor
    # __new__ statt __init__: _gather_context braucht fuer den
    # space-Zweig nur den Task, nicht die halbe Engine.
    executor = TaskExecutor.__new__(TaskExecutor)
    return TaskExecutor._gather_context(
        executor, task, "space-tool-implementation")


def test_a_space_task_does_not_get_the_web_app_context():
    """_gather_context schreibt sonst vor, ALLER Code gehoere nach
    src/modules/<name>/ und generated/ sei nur fuer Prisma. Fuer einen
    Space ist das falsch - sein Code liegt in spaces/<id>/server.py."""
    fill = next(t for t in _tasks() if t.type == "space_fill_tool")
    context = _space_context(fill)

    # Nicht das blosse Vorkommen der Woerter - der Space-Kontext nennt
    # sie in der Verneinung. Verboten sind die VORSCHREIBENDEN Saetze.
    assert "ALL source code MUST be written" not in context
    assert "Module structure:" not in context
    assert "ONLY for Prisma client output" not in context
    assert "spaces/notes/server.py" in context


def test_the_space_context_forbids_the_silent_empty_return():
    fill = next(t for t in _tasks() if t.type == "space_fill_tool")
    context = _space_context(fill)
    assert "NotImplementedError" in context
    assert "empty result" in context


def test_the_space_context_carries_the_write_obligations():
    fill = next(t for t in _tasks()
                if t.type == "space_fill_tool"
                and "notes_create" in t.title)
    context = _space_context(fill)
    assert "approval_ref" in context
    assert "truth:supabase_row" in context
