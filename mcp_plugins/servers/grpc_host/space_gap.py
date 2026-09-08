"""Gap-Loop: der Abgleich zwischen Vertrag und erzeugtem Code.

Der Abgleich ist deterministisch - er liest den erzeugten Server zurueck
und stellt fest, welche Vertrags-Tools noch offen sind. Nur die Nacharbeit
braucht ein Modell. Das ist der "semantische Abgleich" aus der
Fragestellung: die Semantik steckt im Vertrag, der Vergleich ist Rechnen.

Und er ist begrenzt. Ohne Rundenlimit dreht eine Domaene, die das Modell
nicht loesen kann, unbegrenzt weiter; mit Limit gilt der Space danach als
`incomplete` mit benannter Luecke - was fail-closed ist, nicht fertig.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from .space_contract import SpaceContract

# Derselbe Task wie im Planer (epic_task_generator), NICHT das
# SQLAlchemy-Modell aus src.models.task - der Gap-Loop plant, er
# schreibt nicht in die Datenbank.
from .epic_task_generator import Task

DEFAULT_MAX_ROUNDS = 3


class GapError(RuntimeError):
    """Der Abgleich konnte nicht durchgefuehrt werden."""


class GapLimitReached(RuntimeError):
    """Die Runden sind erschoepft und es sind Luecken offen."""


def _raises_not_implemented(node: ast.Raise) -> bool:
    exc = node.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"


def server_path(target: Path, contract: SpaceContract) -> Path:
    return Path(target) / "spaces" / contract.id / "server.py"


def open_tools(target: Path, contract: SpaceContract) -> List[str]:
    """Nur die Namen - die uebliche Frage des Gap-Loops."""
    return [name for name, _ in open_tools_detailed(target, contract)]


def open_tools_detailed(target: Path,
                        contract: SpaceContract) -> List[tuple]:
    """Die Vertrags-Tools, die noch nicht implementiert sind, sortiert.

    Ein fehlender Server ist keine leere Luecke, sondern ein Fehler: sonst
    meldete der Loop "fertig", weil gar nichts da ist. Ein Tool, dessen
    Funktion fehlt, zaehlt als offen - "nicht vorhanden" ist kein
    "implementiert".
    """
    path = server_path(target, contract)
    if not path.is_file():
        raise GapError(f"mcp server missing: {path}")

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        raise GapError(f"generated server does not parse: {exc}") from exc

    bodies = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    gaps: List[tuple] = []
    for tool in contract.tools:
        node = bodies.get(tool.name)
        if node is None:
            gaps.append((tool.name, "no function of that name"))
            continue
        # Im ganzen Rumpf, nicht nur in der ersten Anweisung: eine Logzeile
        # vor dem raise wuerde sonst genuegen, um als gefuellt zu gelten.
        if any(isinstance(inner, ast.Raise) and _raises_not_implemented(inner)
               for inner in ast.walk(node)):
            gaps.append((tool.name, "still raises NotImplementedError"))
    return sorted(gaps)


def plan_gap_tasks(contract: SpaceContract, gaps: List[str], round_no: int,
                   max_rounds: int = DEFAULT_MAX_ROUNDS) -> List["Task"]:
    """Je offenem Tool eine neue Fuell-Aufgabe, plus das Gate darueber.

    `round_no` geht in die Task-ids ein: gleiche ids liessen die zweite
    Runde die erste ueberschreiben, statt sie zu ergaenzen.
    """
    if not gaps:
        return []
    if round_no > max_rounds:
        raise GapLimitReached(
            f"space '{contract.id}' is incomplete after {max_rounds} "
            f"rounds - still open: {', '.join(gaps)}. Refusing another "
            f"round; a gap the model cannot close does not become "
            f"closeable by trying again."
        )

    epic_id = f"space-{contract.id}"
    tasks: List["Task"] = []
    fill_ids: List[str] = []

    for name in gaps:
        tool = contract.tool_by_name(name)
        events = sorted(
            event_name for event_name, event in contract.events.items()
            if event.tool == name
        )
        duties = ""
        if tool is not None and tool.side_effect == "write":
            obligations = []
            for event_name in events:
                event = contract.events[event_name]
                if event.required_provenance:
                    obligations.append(
                        "required_provenance "
                        + ", ".join(event.required_provenance))
                if event.truth is not None:
                    obligations.append(f"truth {event.truth.kind}")
            if obligations:
                duties = " Obligations: " + "; ".join(obligations) + "."

        task_id = f"{contract.id}-gap{round_no}-{name}"
        fill_ids.append(task_id)
        tasks.append(Task(
            id=task_id,
            epic_id=epic_id,
            type="space_fill_tool",
            title=f"Implement {name} in the {contract.id} space",
            description=(
                f"Round {round_no}: {name} is STILL raising "
                f"NotImplementedError after the previous attempt. Replace "
                f"its stub in spaces/{contract.id}/server.py. "
                f"side_effect={tool.side_effect if tool else 'unknown'}, "
                f"params={tool.params if tool else []}, "
                f"returns={tool.returns if tool else {}}, "
                f"events={events or '[]'}.{duties}"
            ),
            dependencies=[],
            estimated_minutes=15,
            output_files=[f"spaces/{contract.id}/server.py"],
        ))

    tasks.append(Task(
        id=f"{contract.id}-gap{round_no}-verify",
        epic_id=epic_id,
        type="verify_space_fill",
        title=f"Re-check the {contract.id} tools after round {round_no}",
        description=("Read the generated server back and refuse while any "
                     "contract tool still raises NotImplementedError."),
        dependencies=list(fill_ids),
        estimated_minutes=3,
        output_files=[],
    ))
    return tasks
