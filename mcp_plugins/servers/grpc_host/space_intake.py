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
CAPABILITIES_REL = (Path("brain") / "the_brain" / "data"
                    / "capabilities.yaml")


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
    ("declares neither tools nor capabilities",
     "Declare tools (a space with its own artefacts) or capabilities "
     "(a space that routes through existing ones). A contract that "
     "claims nothing cannot be measured."),
    ("needs a runtime block",
     "Add runtime with port, healthz and start - the status probe has "
     "nothing to ask otherwise."),
    ("runtime is declared without tools",
     "Either declare the tools this space serves, or drop runtime: a "
     "space with its own process owns its tools."),
    ("ui.embed is declared without tools",
     "Either declare the tools behind the surface, or set "
     "ui.embed: none."),
    ("duplicate capability claims",
     "Claim each capability once."),
    ("Field required",
     "Add that field to the contract."),
)


def _hint_for(message: str) -> str:
    for needle, hint in _HINTS:
        if needle in message:
            return hint
    return ("Fix that field so the contract validates; the message above "
            "states the rule it broke.")


# Regeln ueber mehrere Felder wirft pydantic ohne Feldangabe - der Fehler
# landete dann als "contract". Das bricht das Versprechen des Intake, dass
# jede Luecke ihr Feld nennt. Diese Zuordnung gibt sie zurueck.
_MESSAGE_FIELDS = (
    ("needs a runtime block", "runtime"),
    ("runtime is declared without tools", "runtime"),
    ("ui.embed is declared without tools", "ui"),
    ("requires ui.entry_url", "ui.entry_url"),
    ("duplicate capability claims", "capabilities"),
    ("declares neither tools nor capabilities", "tools"),
    ("duplicate tool names", "tools"),
    ("has no event bound to it", "events"),
)


def _field_of(error: Dict[str, Any], message: str = "") -> str:
    location = error.get("loc") or ()
    parts = [str(p) for p in location if p != "__root__"]
    if parts:
        return ".".join(parts)
    for needle, field in _MESSAGE_FIELDS:
        if needle in message:
            return field
    return "contract"


def _contract_gaps(raw: Dict[str, Any]) -> (Optional[SpaceContract], List[Gap]):
    try:
        return SpaceContract(**raw), []
    except ValidationError as exc:
        gaps: List[Gap] = []
        for error in exc.errors():
            message = str(error.get("msg", "")).replace("Value error, ", "")
            gaps.append(Gap(field=_field_of(error, message),
                            problem=message, needed=_hint_for(message)))
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
    if not contract.renders_artefacts:
        # Ein schlanker Vertrag BESCHREIBT einen bestehenden Space. Dass
        # seine id vergeben ist, ist dort die Voraussetzung, nicht der
        # Fehler - und ihr Fehlen ist einer.
        if contract.id not in spaces:
            gaps.append(Gap(
                field="id",
                problem=f"space id '{contract.id}' is not registered",
                needed="A contract without own tools describes an existing "
                       "space - register it first, or declare tools if this "
                       "is a new one.",
            ))
        return gaps

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


def _capability_gaps(contract: SpaceContract, target: Path) -> List[Gap]:
    """Der Anspruch des Vertrags gegen die Wirklichkeit in capabilities.yaml.

    Der Vertrag nennt nur Name und Schreib-Kennzeichen (ADR-0004). Alles
    Weitere steht hier - und genau deshalb kann hier gemessen werden, statt
    zwei Quellen zu vergleichen:

      * Gibt es die beanspruchte Capability ueberhaupt?
      * Ist sie stillgelegt?
      * Hat eine SCHREIBENDE einen unabhaengigen truth:-Validator?

    Die letzte Frage ist der Grund fuer das ganze Feld. Ein Schreibvorgang
    ohne unabhaengige Rueckfrage meldet Erfolg, ohne dass ihn jemand
    nachgeprueft hat.
    """
    if not contract.capabilities:
        return []

    path = Path(target) / CAPABILITIES_REL
    if not path.is_file():
        return [Gap(
            field="target",
            problem=f"capabilities file not found: {path}",
            needed="Point --target at a vibemind-os checkout; without it the "
                   "capability claims cannot be checked.",
        )]

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as exc:
        return [Gap(field="target",
                    problem=f"capabilities file is not valid YAML: {exc}",
                    needed="Repair it before measuring a space against it.")]

    known = {
        entry["capability"]: entry
        for entry in raw
        if isinstance(entry, dict) and entry.get("capability")
    }

    gaps: List[Gap] = []
    for claim in contract.capabilities:
        entry = known.get(claim.name)
        if entry is None:
            gaps.append(Gap(
                field=f"capabilities.{claim.name}",
                problem=f"capability '{claim.name}' does not exist",
                needed="Name a capability from capabilities.yaml, or drop "
                       "the claim.",
            ))
            continue
        if entry.get("enabled") is False:
            gaps.append(Gap(
                field=f"capabilities.{claim.name}",
                problem=f"capability '{claim.name}' is disabled",
                needed="A disabled capability never routes - drop the claim "
                       "or enable it.",
            ))
            continue
        if not entry.get("execution_target"):
            gaps.append(Gap(
                field=f"capabilities.{claim.name}",
                problem=f"capability '{claim.name}' has no execution target "
                        f"- it matches intent but cannot run",
                needed="This is often deliberate: a write capability without "
                       "a real implementation had its target removed so an "
                       "honest gap gets reported instead of a fake success "
                       "(see bubble_noop_op, 2026-07-14). Keep the claim to "
                       "record the gap, or drop it if the capability is "
                       "obsolete.",
            ))
            continue
        if not claim.writes:
            continue
        validator = entry.get("validator")
        kind = (validator or {}).get("kind", "") if isinstance(
            validator, dict) else str(validator or "")
        if not str(kind).startswith("truth:"):
            gaps.append(Gap(
                field=f"capabilities.{claim.name}",
                problem=f"capability '{claim.name}' writes but has no "
                        f"independent truth: validator"
                        + (f" (has {kind!r})" if kind else ""),
                needed="Add a truth: validator to that capability in "
                       "capabilities.yaml - a write whose result is only "
                       "self-reported cannot be verified.",
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
        gaps = (_registry_gaps(contract, Path(target))
                + _capability_gaps(contract, Path(target)))
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
