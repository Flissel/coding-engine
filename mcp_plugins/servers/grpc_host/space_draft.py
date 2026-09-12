"""Entwurf eines schlanken Vertrags für einen bestehenden Space (ADR-0004).

Der Entwurf ist ein **Vorschlag, kein Befund**. Zwei Dinge kann er nicht
wissen, und er tut nicht so:

1. **Welche Capability zu welchem Space gehört.** Capabilities tragen kein
   Space-Feld. Der Entwurf leitet den Namenspräfix aus den `prefixes` der
   Registry ab (`idea.` → `idea_`) — das ist eine begründete Vermutung, kein
   Wissen. Wer den Vertrag abnimmt, bestätigt oder korrigiert sie.

2. **Ob eine Capability schreibt.** Das steht nirgends deklariert. Aus dem
   Ausführungsziel lässt es sich oft ablesen (`supabase:idea.create`), aber
   längst nicht immer (`supabase:idea.llm` ist gemischt — `idea_expand`
   schreibt, `idea_explain` nicht).

**Was nicht ableitbar ist, bleibt leer.** `writes` hat im Vertrag keinen
Vorgabewert; ein Entwurf mit offenen Stellen validiert also nicht, und der
Intake nennt jede einzelne. Das ist Absicht: eine geratene Voreinstellung
wäre die stille Annahme, die später niemand mehr hinterfragt.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

REGISTRY_REL = Path("config") / "space_agent_registry.yml"
CAPABILITIES_REL = Path("brain") / "the_brain" / "data" / "capabilities.yaml"

# Operationen, deren Wirkung aus dem Namen des Ziels eindeutig folgt.
# Bewusst knapp gehalten: jeder Eintrag hier ist eine Behauptung, und eine
# falsche wiegt schwerer als eine fehlende. Was fehlt, fragt nach.
_WRITING_OPS = {
    "create", "update", "delete", "move", "promote", "evaluate", "score",
    "format", "auto_link", "disconnect", "connect", "to_project", "send",
    "post", "publish", "cancel", "modify", "snooze", "start", "stop",
    "import", "assign", "write", "add", "remove", "set", "apply",
}
_READING_OPS = {
    "list", "count", "find", "get", "read", "status", "show", "search",
    "explain", "overview", "summary", "inspect", "health",
}


def _operation_of(target: str) -> str:
    """Der Teil hinter dem letzten Punkt oder Doppelpunkt des Ziels."""
    if not target:
        return ""
    tail = target.split(":", 1)[1] if ":" in target else target
    tail = tail.split(":")[-1]
    return tail.split(".")[-1].strip().lower()


def _writes_of(entry: Dict[str, Any]) -> Optional[bool]:
    """True/False wenn ableitbar, sonst None — dann muss jemand nachsehen."""
    op = _operation_of(str(entry.get("execution_target") or ""))
    if not op:
        return None
    if op in _WRITING_OPS:
        return True
    if op in _READING_OPS:
        return False
    return None


def _capability_prefixes(space: Dict[str, Any]) -> List[str]:
    """`prefixes: [idea.]` → `idea_`. Abgeleitet, nicht fest verdrahtet."""
    out = []
    for prefix in space.get("prefixes") or []:
        stem = str(prefix).rstrip(".").strip()
        if not stem:
            continue
        # Beide Schreibweisen kommen vor: `idea_add` und `mirofish.simulate`.
        # Nur den Unterstrich zu pruefen liess mirofish leer aussehen,
        # obwohl es sieben Capabilities hat.
        out.append(stem + "_")
        out.append(stem + ".")
    return out


def draft(space_id: str, target: Path) -> Tuple[str, List[str]]:
    """Gibt den Entwurfstext und die Namen der offenen Stellen zurück."""
    root = Path(target)
    registry = yaml.safe_load(
        io.open(root / REGISTRY_REL, encoding="utf-8").read()) or {}
    spaces = registry.get("spaces") or {}
    if space_id not in spaces:
        raise KeyError(f"space '{space_id}' is not in the registry")
    space = spaces[space_id] if isinstance(spaces[space_id], dict) else {}

    caps = [c for c in yaml.safe_load(
        io.open(root / CAPABILITIES_REL, encoding="utf-8").read())
        if isinstance(c, dict) and c.get("capability")]

    prefixes = _capability_prefixes(space)
    mine = [c for c in caps
            if c.get("enabled") is not False
            and any(c["capability"].startswith(p) for p in prefixes)]

    lines = [
        f"# Entwurf eines schlanken Vertrags fuer '{space_id}' (ADR-0004).",
        "#",
        "# VORSCHLAG, kein Befund. Zwei Annahmen stecken darin:",
        f"#   1. Zugehoerigkeit ueber den Namenspraefix {prefixes} aus der",
        "#      Registry abgeleitet - Capabilities tragen kein Space-Feld.",
        "#   2. `writes` aus dem Ausfuehrungsziel abgelesen, wo eindeutig.",
        "#",
        "# Offene Stellen sind als TODO markiert und haben KEIN writes. Der",
        "# Vertrag validiert damit nicht - der Intake nennt jede einzelne.",
        "",
        f"id: {space_id}",
        f"description: {json.dumps(space.get('description') or space_id, ensure_ascii=False)}",
        f"prefixes: {list(space.get('prefixes') or [])}",
        "",
        "capabilities:",
    ]

    open_ones: List[str] = []
    for entry in sorted(mine, key=lambda c: c["capability"]):
        name = entry["capability"]
        verdict = _writes_of(entry)
        target_str = str(entry.get("execution_target") or "(kein Ziel)")
        if verdict is None:
            open_ones.append(name)
            lines.append(f"  # TODO writes: am Code pruefen -> {target_str}")
            lines.append(f"  - name: {name}")
        else:
            lines.append(f"  - {{name: {name}, writes: {str(verdict).lower()}}}"
                         f"   # {target_str}")

    if not mine:
        lines.append("  # keine Capability traegt einen dieser Praefixe")

    return "\n".join(lines) + "\n", open_ones


def unattributed(target: Path) -> List[Tuple[str, str]]:
    """Capabilities, die zu keinem Space passen — ein Befund für sich."""
    root = Path(target)
    registry = yaml.safe_load(
        io.open(root / REGISTRY_REL, encoding="utf-8").read()) or {}
    prefixes: List[str] = []
    for space in (registry.get("spaces") or {}).values():
        if isinstance(space, dict):
            prefixes.extend(_capability_prefixes(space))

    caps = [c for c in yaml.safe_load(
        io.open(root / CAPABILITIES_REL, encoding="utf-8").read())
        if isinstance(c, dict) and c.get("capability")]

    return [
        (c["capability"], str(c.get("execution_target") or "(kein Ziel)"))
        for c in caps
        if c.get("enabled") is not False
        and not any(c["capability"].startswith(p) for p in prefixes)
    ]
