"""Der Skill aus TASK_SKILL_MAPPING muss wirklich der injizierte sein.

task_executor.py dokumentiert die Skill-Spalte als
"`.claude/skills/{name}/SKILL.md` injected into prompt". Tatsaechlich waehlte
ClaudeCodeTool den Skill aus `agent_type` - `general` ergab
`code-generation` ("Generate/fix TypeScript+React code"), auch fuer eine
Python-Aufgabe. Am Live-Lauf am 2026-09-08 aufgefallen, nicht im Test:
im Prompt stand die React-Regelliste ueber einer FastMCP-Datei.
"""
import inspect

import pytest
import structlog

from src.tools.claude_code_tool import ClaudeCodeTool
from mcp_plugins.servers.grpc_host.task_executor import TASK_SKILL_MAPPING


def _tool() -> ClaudeCodeTool:
    # __new__ statt __init__: die Skill-Wahl braucht weder CLI noch Pool.
    tool = ClaudeCodeTool.__new__(ClaudeCodeTool)
    tool._skill_cache = {}
    tool.skill = None
    tool.logger = structlog.get_logger()
    return tool


def test_an_explicit_skill_name_wins():
    skill = _tool()._get_skill_for_agent("general", "space-tool-implementation")
    assert skill is not None
    assert skill.name == "space-tool-implementation"


def test_without_a_name_the_agent_type_still_decides():
    """Verhalten fuer alle bestehenden Aufrufer unveraendert."""
    skill = _tool()._get_skill_for_agent("general")
    assert skill is not None
    assert skill.name == "code-generation"


def test_an_unknown_named_skill_is_refused_not_substituted():
    """Ein Verdrahtungsfehler ist kein Grund, still TypeScript-Regeln an
    eine Python-Aufgabe zu schicken."""
    assert _tool()._get_skill_for_agent("general", "gibt-es-nicht") is None


def test_the_name_beats_an_instance_wide_skill():
    """Das Spezifischste gewinnt. Vorher schloss ein instanzweiter Skill
    den expliziten Namen kurz."""
    tool = _tool()
    tool.skill = object()  # irgendein globaler Skill
    skill = tool._get_skill_for_agent("general", "space-tool-implementation")
    assert getattr(skill, "name", None) == "space-tool-implementation"


def test_the_cache_does_not_mix_two_skills_up():
    tool = _tool()
    first = tool._get_skill_for_agent("general", "space-tool-implementation")
    second = tool._get_skill_for_agent("general")
    assert first.name != second.name


@pytest.mark.parametrize("hop", ["execute", "_build_enriched_prompt"])
def test_the_name_reaches_every_hop_of_the_chain(hop):
    """Drei unabhaengige Stellen laden Skills. Fehlt der Parameter an
    einer, faellt sie stillschweigend auf den agent_type zurueck - genau
    das war der Fehler."""
    signature = inspect.signature(getattr(ClaudeCodeTool, hop))
    assert "skill_name" in signature.parameters, hop


def test_the_executor_passes_the_name_it_looked_up():
    source = inspect.getsource(
        __import__("mcp_plugins.servers.grpc_host.task_executor",
                   fromlist=["TaskExecutor"]).TaskExecutor._execute_claude)
    assert "skill_name=skill_name" in source


def test_every_named_skill_in_the_mapping_exists():
    """Ein Name in der Tabelle, den es nicht gibt, liefert jetzt None -
    also gar keinen Skill. Besser, das faellt hier auf."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    missing = sorted({
        skill for _, skill, _, _ in TASK_SKILL_MAPPING.values()
        if skill and not (root / ".claude" / "skills" / skill).is_dir()
    })
    assert not missing, f"skills named by the mapping but absent: {missing}"

def test_space_fill_does_not_use_the_typescript_agent():
    """.claude/agents/coder.md ist fuer "TypeScript, React, or NestJS".
    Ein Space-Tool ist Python in einem FastMCP-Server - der Agent waere
    nicht bloss unnoetig, sondern eine falsche Anweisung. Am Live-Lauf
    2026-09-08 aufgefallen, weil die CLI ihn gar nicht erst fand."""
    _, skill, claude_agent, _ = TASK_SKILL_MAPPING["space_fill_tool"]
    assert claude_agent is None
    assert skill == "space-tool-implementation"
