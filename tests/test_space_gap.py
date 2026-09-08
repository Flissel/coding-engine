"""Gap-Loop: aus einem roten Verify wird benannte Nacharbeit.

Der Abgleich selbst ist deterministisch - er liest den erzeugten Code
zurueck und vergleicht ihn mit dem Vertrag. Nur die Nacharbeit braucht ein
Modell. Und er ist begrenzt: ohne Rundenlimit dreht eine Domaene, die das
Modell nicht loesen kann, ewig im Kreis.
"""
from pathlib import Path

import pytest
import yaml

from mcp_plugins.servers.grpc_host.space_cli import main
from mcp_plugins.servers.grpc_host.space_contract import SpaceContract
from mcp_plugins.servers.grpc_host.space_gap import (
    GapLimitReached,
    open_tools,
    plan_gap_tasks,
)

FIXTURE = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"


def _contract() -> SpaceContract:
    return SpaceContract(**yaml.safe_load(FIXTURE.read_text(encoding="utf-8")))


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
    main(["render", "all", "--contract", str(FIXTURE), "--target",
          str(tmp_path)])
    return tmp_path


def _fill(target: Path, tool: str, body: str = '    return {"ok": True}'):
    path = target / "spaces" / "notes" / "server.py"
    source = path.read_text(encoding="utf-8")
    path.write_text(source.replace(
        f'    raise NotImplementedError("{tool} is not implemented yet")',
        body,
    ), encoding="utf-8")


# ---------------------------------------------------------------------
# Der Abgleich
# ---------------------------------------------------------------------

def test_a_fresh_scaffold_has_every_tool_open(tmp_path):
    target = _target(tmp_path)
    assert open_tools(target, _contract()) == ["notes_create", "notes_list"]


def test_a_filled_tool_drops_out_of_the_gap(tmp_path):
    target = _target(tmp_path)
    _fill(target, "notes_list")
    assert open_tools(target, _contract()) == ["notes_create"]


def test_nothing_open_when_all_are_filled(tmp_path):
    target = _target(tmp_path)
    _fill(target, "notes_list")
    _fill(target, "notes_create")
    assert open_tools(target, _contract()) == []


def test_a_missing_server_is_not_an_empty_gap(tmp_path):
    """Kein Server heisst nicht 'nichts offen' - sonst meldet der Loop
    fertig, weil gar nichts da ist."""
    from mcp_plugins.servers.grpc_host.space_gap import GapError

    empty = tmp_path / "leer"
    empty.mkdir()
    with pytest.raises(GapError, match="mcp server missing"):
        open_tools(empty, _contract())


# ---------------------------------------------------------------------
# Die Nacharbeit
# ---------------------------------------------------------------------

def test_one_task_per_open_tool(tmp_path):
    target = _target(tmp_path)
    _fill(target, "notes_list")
    tasks = plan_gap_tasks(_contract(), open_tools(target, _contract()),
                           round_no=1)
    assert [t.type for t in tasks] == ["space_fill_tool", "verify_space_fill"]
    assert "notes_create" in tasks[0].title
    assert "notes_list" not in tasks[0].title


def test_gap_task_ids_do_not_collide_across_rounds(tmp_path):
    """Zwei Runden erzeugen Aufgaben fuer dasselbe Tool. Gleiche ids
    wuerden die zweite Runde die erste ueberschreiben lassen."""
    target = _target(tmp_path)
    gaps = open_tools(target, _contract())
    first = {t.id for t in plan_gap_tasks(_contract(), gaps, round_no=1)}
    second = {t.id for t in plan_gap_tasks(_contract(), gaps, round_no=2)}
    assert not (first & second)


def test_the_retry_task_says_it_is_a_retry(tmp_path):
    """Das Modell hat beim ersten Mal nicht geliefert. Wer das nicht
    mitbekommt, versucht dasselbe noch einmal."""
    target = _target(tmp_path)
    task = plan_gap_tasks(_contract(), open_tools(target, _contract()),
                          round_no=2)[0]
    assert "round 2" in task.description.lower()
    assert "still" in task.description.lower()


def test_the_gate_task_waits_for_every_retry(tmp_path):
    target = _target(tmp_path)
    tasks = plan_gap_tasks(_contract(), open_tools(target, _contract()),
                           round_no=1)
    gate = tasks[-1]
    assert gate.type == "verify_space_fill"
    fill_ids = {t.id for t in tasks if t.type == "space_fill_tool"}
    assert fill_ids <= set(gate.dependencies)


def test_no_gaps_means_no_tasks():
    assert plan_gap_tasks(_contract(), [], round_no=1) == []


def test_the_loop_is_bounded(tmp_path):
    """Ohne Grenze dreht eine Domaene, die das Modell nicht loesen kann,
    ewig. Der Space gilt dann als incomplete mit benannter Luecke - nicht
    als fertig, und nicht als endloser Lauf."""
    target = _target(tmp_path)
    gaps = open_tools(target, _contract())
    with pytest.raises(GapLimitReached) as excinfo:
        plan_gap_tasks(_contract(), gaps, round_no=4, max_rounds=3)
    message = str(excinfo.value)
    assert "notes_create" in message and "notes_list" in message
    assert "incomplete" in message


# ---------------------------------------------------------------------
# Die CLI
# ---------------------------------------------------------------------

def test_gap_command_lists_the_open_tools(tmp_path, capsys):
    target = _target(tmp_path)
    _fill(target, "notes_list")
    code = main(["gap", "--contract", str(FIXTURE), "--target", str(target)])
    assert code == 1
    out = capsys.readouterr().out
    assert "notes_create" in out
    assert "notes_list" not in out


def test_gap_command_is_green_when_nothing_is_open(tmp_path, capsys):
    target = _target(tmp_path)
    _fill(target, "notes_list")
    _fill(target, "notes_create")
    assert main(["gap", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0
    assert "no gaps" in capsys.readouterr().out


def test_gap_command_refuses_past_the_round_limit(tmp_path, capsys):
    target = _target(tmp_path)
    code = main(["gap", "--contract", str(FIXTURE), "--target", str(target),
                 "--round", "4", "--max-rounds", "3"])
    assert code == 2, "erschoepfte Runden muessen sich von offenen Luecken unterscheiden"
    err = capsys.readouterr().err
    assert "incomplete" in err
    assert "notes_create" in err


def test_verify_fill_and_the_gap_command_agree(tmp_path):
    """Zwei Wege zur selben Frage duerfen nicht auseinanderlaufen."""
    target = _target(tmp_path)
    _fill(target, "notes_list")
    assert main(["verify", "fill", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1
    assert main(["gap", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 1

    _fill(target, "notes_create")
    assert main(["verify", "fill", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0
    assert main(["gap", "--contract", str(FIXTURE),
                 "--target", str(target)]) == 0
