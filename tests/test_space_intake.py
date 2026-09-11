"""Intake: aus einer Beschreibung wird ein Vertrag - oder eine benannte Luecke.

Das Modell schreibt den Entwurf, dieses Gate prueft ihn. Die Regel der Spec:
kein Scaffold auf unvollstaendigem Vertrag. Eine Luecke muss deshalb nicht
nur erkannt, sondern **benutzbar** gemeldet werden - Feld, Problem, und was
sie schliessen wuerde. "ValidationError" allein hilft niemandem weiter, der
den naechsten Entwurf schreiben soll.
"""
from pathlib import Path

import pytest
import yaml

from mcp_plugins.servers.grpc_host.space_cli import main
from mcp_plugins.servers.grpc_host.space_intake import Gap, analyse

FIXTURE = Path(__file__).parent / "fixtures" / "space_notes_contract.yaml"


def _complete() -> dict:
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def _registry_target(tmp_path: Path, existing_prefix: str = "bubbles.") -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "space_agent_registry.yml").write_text(
        "version: 1\n"
        "spaces:\n"
        "  bubbles:\n"
        "    agent: brain-bubbles\n"
        f"    prefixes: [{existing_prefix}]\n",
        encoding="utf-8",
    )
    return tmp_path


def _fields(gaps) -> set:
    return {g.field for g in gaps}


# ---------------------------------------------------------------------
# Der vollstaendige Fall
# ---------------------------------------------------------------------

def test_a_complete_contract_has_no_gaps():
    result = analyse(_complete())
    assert result.gaps == []
    assert result.contract is not None
    assert result.contract.id == "notes"


def test_every_gap_is_actionable():
    """Eine Luecke ohne Hinweis ist nur eine Absage. Jede muss sagen, was
    sie schliessen wuerde."""
    raw = _complete()
    del raw["id"]
    raw["events"]["notes.create"].pop("required_provenance")
    for gap in analyse(raw).gaps:
        assert isinstance(gap, Gap)
        assert gap.field.strip()
        assert gap.problem.strip()
        assert gap.needed.strip()


# ---------------------------------------------------------------------
# Die Luecken, die der Vertrag selbst kennt
# ---------------------------------------------------------------------

def test_a_missing_id_is_named():
    raw = _complete()
    del raw["id"]
    assert "id" in _fields(analyse(raw).gaps)


def test_a_missing_runtime_is_named():
    raw = _complete()
    del raw["runtime"]
    assert "runtime" in _fields(analyse(raw).gaps)


def test_a_write_event_without_provenance_names_the_event():
    raw = _complete()
    raw["events"]["notes.create"].pop("required_provenance")
    gaps = analyse(raw).gaps
    text = " ".join(g.problem + g.needed for g in gaps)
    assert "notes.create" in text
    assert "required_provenance" in text


def test_a_write_event_without_truth_names_the_event():
    raw = _complete()
    raw["events"]["notes.create"].pop("truth")
    text = " ".join(g.problem + g.needed for g in analyse(raw).gaps)
    assert "notes.create" in text
    assert "truth" in text


def test_an_unsupported_truth_kind_lists_what_is_supported():
    """Wer 'truth:notes_exist' schreibt, muss erfahren, was es stattdessen
    gibt - sonst raet der naechste Entwurf erneut."""
    raw = _complete()
    raw["events"]["notes.create"]["truth"]["kind"] = "truth:notes_exist"
    text = " ".join(g.needed for g in analyse(raw).gaps)
    assert "supabase_row" in text


def test_a_write_tool_without_an_event_names_the_tool():
    raw = _complete()
    del raw["events"]["notes.create"]
    text = " ".join(g.problem + g.needed for g in analyse(raw).gaps)
    assert "notes_create" in text


def test_an_invalid_id_explains_the_rule():
    raw = _complete()
    raw["id"] = "my-notes"
    text = " ".join(g.needed for g in analyse(raw).gaps)
    assert "hyphen" in text.lower() or "bindestrich" in text.lower()


# ---------------------------------------------------------------------
# Die Luecken, die erst der Zielbaum zeigt
# ---------------------------------------------------------------------

def test_a_taken_id_is_a_gap_not_a_later_render_failure(tmp_path):
    """Frueher fiel das erst beim Rendern auf - nach dem Scaffold. Der
    Intake muss es sagen, bevor irgendetwas geschrieben wird."""
    target = _registry_target(tmp_path)
    raw = _complete()
    raw["id"] = "bubbles"
    raw["prefixes"] = ["bubbles2."]
    raw["events"] = {
        "bubbles2." + k.split(".", 1)[1]: v for k, v in raw["events"].items()
    }
    gaps = analyse(raw, target=target).gaps
    text = " ".join(g.problem for g in gaps)
    assert "bubbles" in text
    assert "id" in _fields(gaps)


def test_a_claimed_prefix_names_its_owner(tmp_path):
    target = _registry_target(tmp_path)
    raw = _complete()
    raw["prefixes"] = ["bubbles."]
    raw["events"] = {
        "bubbles." + k.split(".", 1)[1]: v for k, v in raw["events"].items()
    }
    text = " ".join(g.problem for g in analyse(raw, target=target).gaps)
    assert "bubbles" in text


def test_without_a_target_no_registry_claims_are_invented():
    """Ohne Zielbaum kann niemand wissen, was belegt ist - dann darf auch
    nichts behauptet werden."""
    raw = _complete()
    raw["id"] = "bubbles"
    raw["prefixes"] = ["bubbles."]
    raw["events"] = {
        "bubbles." + k.split(".", 1)[1]: v for k, v in raw["events"].items()
    }
    assert analyse(raw).gaps == []


def test_a_missing_registry_is_reported_not_ignored(tmp_path):
    raw = _complete()
    text = " ".join(g.problem for g in analyse(raw, target=tmp_path).gaps)
    assert "registry" in text.lower()


# ---------------------------------------------------------------------
# Die CLI
# ---------------------------------------------------------------------

def test_intake_command_accepts_a_complete_contract(capsys):
    assert main(["intake", "--contract", str(FIXTURE)]) == 0
    assert "contract complete" in capsys.readouterr().out


def test_intake_command_refuses_and_names_the_gaps(tmp_path, capsys):
    raw = _complete()
    del raw["runtime"]
    draft = tmp_path / "draft.yaml"
    draft.write_text(yaml.safe_dump(raw), encoding="utf-8")

    assert main(["intake", "--contract", str(draft)]) == 1
    err = capsys.readouterr().err
    assert "runtime" in err


def test_intake_command_reads_unparsable_yaml_as_a_gap(tmp_path, capsys):
    draft = tmp_path / "broken.yaml"
    draft.write_text("id: notes\n  bad indent\n", encoding="utf-8")
    assert main(["intake", "--contract", str(draft)]) == 1
    assert "yaml" in capsys.readouterr().err.lower()


def test_intake_is_a_model_task_and_its_gate_is_not():
    from mcp_plugins.servers.grpc_host.task_executor import (
        TASK_SKILL_MAPPING, VERIFICATION_COMMANDS,
    )
    agent, skill, claude_agent, _ = TASK_SKILL_MAPPING["space_intake"]
    assert agent not in ("BashExecutor", "CheckpointHandler",
                         "NotificationHandler", "DockerAgent")
    assert skill == "space-intake"
    # coder.md ist fuer TypeScript/React - fuer einen Vertragsentwurf falsch.
    assert claude_agent is None

    assert TASK_SKILL_MAPPING["verify_space_intake"][0] == "BashExecutor"
    assert VERIFICATION_COMMANDS["verify_space_intake"].endswith("intake")


def test_the_intake_skill_exists():
    root = Path(__file__).resolve().parents[1]
    assert (root / ".claude" / "skills" / "space-intake" / "SKILL.md").is_file()

def test_a_contract_level_gap_says_more_may_follow(tmp_path, capsys):
    """Der Model-Validator haelt beim ersten Verstoss an. "1 gap" liest
    sich sonst wie "nur noch eine Sache" - und der naechste Entwurf
    scheitert wieder. Die Regeln ein zweites Mal zu sammeln waere Drift,
    also wird die Eigenschaft benannt."""
    raw = _complete()
    raw["events"]["notes.create"].pop("truth")
    raw["events"]["notes.create"].pop("required_provenance")
    draft = tmp_path / "thin.yaml"
    draft.write_text(yaml.safe_dump(raw), encoding="utf-8")

    assert main(["intake", "--contract", str(draft)]) == 1
    err = capsys.readouterr().err
    assert "further contract rules" in err


def test_a_registry_gap_does_not_claim_more_may_follow(tmp_path, capsys):
    """Registry-Anspruechen werden alle auf einmal geprueft - dort waere
    der Hinweis irrefuehrend."""
    target = _registry_target(tmp_path)
    raw = _complete()
    raw["id"] = "bubbles"
    raw["prefixes"] = ["bubbles2."]
    raw["events"] = {
        "bubbles2." + k.split(".", 1)[1]: v for k, v in raw["events"].items()
    }
    draft = tmp_path / "clash.yaml"
    draft.write_text(yaml.safe_dump(raw), encoding="utf-8")

    assert main(["intake", "--contract", str(draft),
                 "--target", str(target)]) == 1
    assert "further contract rules" not in capsys.readouterr().err
