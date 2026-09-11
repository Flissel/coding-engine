"""Intake: prueft einen Vertragsentwurf und benennt, was ihm fehlt.

Das Modell schreibt den Entwurf, dieses Modul prueft ihn. Die Regel der
Spec: kein Scaffold auf unvollstaendigem Vertrag.

Der Unterschied zu einer blossen Validierung ist der Zweck. Die Meldung
geht an jemanden - Mensch oder Modell -, der den naechsten Entwurf
schreiben soll. "ValidationError: value is not a valid dict" hilft dabei
nicht. Jede Luecke nennt deshalb drei Dinge: **welches Feld**, **was daran
falsch ist** und **was sie schliessen wuerde**.

Zwei Sorten Luecken:

* solche, die der Vertrag selbst kennt (Pflichtfelder, Schreibpflichten,
  unterstuetzte truth-Arten) - die kommen aus `SpaceContract`;
* solche, die erst der Zielbaum zeigt (id schon vergeben, Prefix schon
  beansprucht). Die fielen frueher erst beim Rendern auf, also NACH dem
  Scaffold. Sie gehoeren hierher, vor den ersten geschriebenen Byte.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import ValidationError

from .space_contract import (
    MODELLED_TRUTH_CHECKS,
    SPACE_ID_PATTERN,
    SpaceContract,
)

REGISTRY_REL = Path("config") / "space_agent_registry.yml"


@dataclass(frozen=True)
class Gap:
    """Eine Luecke im Entwurf - benannt, begruendet, mit Ausweg."""

    field: str
    problem: str
    needed: str

    def as_line(self) -> str:
        return f"{self.field}: {self.problem} -> {self.needed}"


@dataclass
class IntakeResult:
    contract: Optional[SpaceContract] = None
    gaps: List[Gap] = dc_field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.contract is not None and not self.gaps


# Hinweise fuer die Faelle, die der Vertrag selbst pruefen kann. Der
# Schluessel ist ein Stueck der pydantic-Meldung; der Wert sagt, was zu tun
# ist. Was hier nicht passt, bekommt einen allgemeinen Hinweis - nie gar
# keinen.
_HINTS = (
    ("writes but declares no required_provenance",
     "Add required_provenance to that event, e.g. [approval_ref, cost_ref]. "
     "The routing layer refuses a deterministic MCP write event without it."),
    ("writes but declares no truth",
     "Add a truth block to that event: kind plus the fields its check "
     "needs. A write without an independent read-back cannot be verified."),
    ("has no event bound to it",
     "Bind that tool to an event under events:, or drop the tool."),
    ("names no check world_observer implements",
     f"Use one of: {sorted(MODELLED_TRUTH_CHECKS)}."),
    ("is not modelled here",
     f"Use one of: {sorted(MODELLED_TRUTH_CHECKS)}."),
    ("must start with 'truth:'",
     "Prefix the kind with truth:, e.g. truth:supabase_row."),
    ("without a table to re-query",
     "Name the table the postcondition should query."),
    ("returns no 'id'",
     "Either return an id from the tool, or give truth.match an explicit "
     "PostgREST filter."),
    ("does not start with any declared prefix",
     "Rename the event so it starts with one of prefixes:, or add the "
     "prefix."),
    ("points at unknown tool",
     "Name a tool that exists under tools:."),
    ("declares required_params",
     "List only params the tool actually declares."),
    ("hyphens are not allowed",
     "Use lowercase letters, digits and underscores, starting with a "
     "letter - hyphens break task ids and env var names."),
    ("requires ui.entry_url",
     "Add ui.entry_url, or set ui.embed: none for a headless space."),
    ("duplicate tool names",
     "Give every tool a distinct name."),
    ("Field required",
     "Add that field to the contract."),
)


def _hint_for(message: str) -> str:
    for needle, hint in _HINTS:
        if needle in message:
            return hint
    return ("Fix that field so the contract validates; the message above "
            "states the rule it broke.")


def _field_of(error: Dict[str, Any]) -> str:
    location = error.get("loc") or ()
    parts = [str(p) for p in location if p != "__root__"]
    return ".".join(parts) if parts else "contract"


def _contract_gaps(raw: Dict[str, Any]) -> (Optional[SpaceContract], List[Gap]):
    try:
        return SpaceContract(**raw), []
    except ValidationError as exc:
        gaps: List[Gap] = []
        for error in exc.errors():
            message = str(error.get("msg", "")).replace("Value error, ", "")
            gaps.append(Gap(field=_field_of(error), problem=message,
                            needed=_hint_for(message)))
        return None, gaps
    except TypeError as exc:
        return None, [Gap(field="contract", problem=str(exc),
                          needed="The contract must be a mapping of the "
                                 "documented keys.")]


def _registry_gaps(contract: SpaceContract, target: Path) -> List[Gap]:
    """Was erst der Zielbaum weiss: ist die id frei, sind die Prefixe frei?"""
    registry_path = Path(target) / REGISTRY_REL
    if not registry_path.is_file():
        return [Gap(
            field="target",
            problem=f"space registry not found: {registry_path}",
            needed="Point --target at a vibemind-os checkout, or drop it to "
                   "skip the claims check.",
        )]

    try:
        data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return [Gap(field="target",
                    problem=f"space registry is not valid YAML: {exc}",
                    needed="Repair the registry before registering a space.")]

    spaces = data.get("spaces")
    if not isinstance(spaces, dict):
        return [Gap(field="target",
                    problem=f"space registry has no 'spaces' mapping: "
                            f"{registry_path}",
                    needed="Repair the registry before registering a space.")]

    gaps: List[Gap] = []
    if contract.id in spaces:
        gaps.append(Gap(
            field="id",
            problem=f"space id '{contract.id}' is already registered",
            needed="Choose an id no space uses yet.",
        ))

    claimed: Dict[str, str] = {}
    for other_id, entry in spaces.items():
        if not isinstance(entry, dict):
            continue
        for prefix in entry.get("prefixes") or []:
            claimed.setdefault(prefix, other_id)
    for prefix in contract.prefixes:
        owner = claimed.get(prefix)
        if owner and owner != contract.id:
            gaps.append(Gap(
                field="prefixes",
                problem=f"prefix '{prefix}' is already claimed by space "
                        f"'{owner}'",
                needed="Choose a prefix no space owns; a duplicate silently "
                       "steals the other space's routing.",
            ))
    return gaps


def analyse(raw: Any, target: Optional[Path] = None) -> IntakeResult:
    """Pruefe einen Vertragsentwurf und benenne, was ihm fehlt.

    `target` ist optional: ohne Zielbaum kann niemand wissen, welche ids und
    Prefixe belegt sind - dann wird darueber auch nichts behauptet.
    """
    if not isinstance(raw, dict):
        return IntakeResult(gaps=[Gap(
            field="contract",
            problem=f"contract must be a mapping, got {type(raw).__name__}",
            needed="Write the contract as YAML keys, not a list or scalar.",
        )])

    contract, gaps = _contract_gaps(raw)
    if contract is None:
        return IntakeResult(gaps=gaps)
    if target is not None:
        gaps = _registry_gaps(contract, Path(target))
    return IntakeResult(contract=contract, gaps=gaps)


def analyse_file(path: Path,
                 target: Optional[Path] = None) -> IntakeResult:
    """Wie `analyse`, aber von einer Datei - unlesbares YAML ist auch eine
    Luecke, kein Absturz."""
    path = Path(path)
    if not path.is_file():
        return IntakeResult(gaps=[Gap(
            field="contract",
            problem=f"contract draft not found: {path}",
            needed="Write the draft first; intake checks a file.",
        )])
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return IntakeResult(gaps=[Gap(
            field="contract",
            problem=f"draft is not valid YAML: {exc}",
            needed="Fix the YAML syntax; nothing else can be checked until "
                   "it parses.",
        )])
    return analyse(raw, target=target)
