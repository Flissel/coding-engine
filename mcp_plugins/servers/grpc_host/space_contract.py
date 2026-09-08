"""Space contract — the single source of truth about a VibeMind space.

A space is not a directory of code but a set of artefacts across Brain,
OpenFang, Electron and operations. This module describes that shape and
rejects anything incomplete, so nothing downstream has to guess.

Validation is fail-closed by design: a write operation without provenance
or without a ground-truth check is refused here, before a single file is
generated.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

# Lowercase letters, digits and underscores, starting with a letter. This
# excludes hyphens deliberately: ids are used both to build task-id prefixes
# (f"{sid}-{suffix}") and env-var stems, and hyphens break both — a hyphen in
# the id makes "{sid}-{suffix}" ambiguous (space "sales" + suffix
# "verify-tests" collides with space "sales-verify" + suffix "tests"), and a
# hyphen in an env var name is not settable in a POSIX shell.
SPACE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ContractError(ValueError):
    """Raised when a contract cannot be read at all."""


class SpaceTool(BaseModel):
    name: str
    params: List[str] = Field(default_factory=list)
    returns: Dict[str, str] = Field(default_factory=dict)
    side_effect: Literal["read", "write"]


# The checks world_observer actually implements
# (vibemind-os/brain/the_brain/core/world_observer.py, dict `_CHECKS`).
# A kind outside this set names a check that does not exist: the observer
# would find nothing, return UNVERIFIED, and the write would route with no
# ground-truth re-query while every gate stayed green.
SUPPORTED_TRUTH_CHECKS = frozenset({
    "process_running",
    "port_open",
    "file_exists",
    "http_ok",
    "supabase_row",
    "supabase_edge",
    "supabase_edge_ids",
    "supabase_node_in_bubble",
})

# The subset whose postcondition shape this contract can spell. The other
# five exist in the observer but take spec keys (node titles, bubble ids,
# edge id lists) that a space contract has no way to supply, so declaring
# one here is refused rather than rendered into a spec the observer would
# reject at runtime.
MODELLED_TRUTH_CHECKS = frozenset({"supabase_row", "http_ok", "file_exists"})


class SpaceTruth(BaseModel):
    """A ground-truth re-query, rendered into the space's capability entry.

    Field sets are per check kind: supabase_row uses table/match/expect,
    http_ok uses url, file_exists uses path.
    """

    kind: str
    on_fail: Literal["report", "retry", "block"] = "report"
    # truth:supabase_row
    table: Optional[str] = None
    match: Optional[str] = None
    expect: Optional[str] = None
    # truth:http_ok
    url: Optional[str] = None
    # truth:file_exists
    path: Optional[str] = None

    @property
    def check(self) -> str:
        """Bare check name - `_CHECKS` is keyed without the truth: prefix."""
        return self.kind.split(":", 1)[1]

    def postcondition(self) -> Dict[str, str]:
        """The spec dict world_observer.observe() consumes."""
        if self.check == "supabase_row":
            return {
                "check": "supabase_row",
                "table": self.table,
                "match": self.match,
                "expect": self.expect or "present",
            }
        if self.check == "http_ok":
            return {"check": "http_ok", "url": self.url}
        return {"check": "file_exists", "path": self.path}

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value: str) -> str:
        if not value.startswith("truth:"):
            raise ValueError(
                f"truth kind '{value}' must start with 'truth:' - "
                f"capability_validator dispatches on that prefix, so "
                f"without it the check is never reached"
            )
        check = value.split(":", 1)[1]
        if check in MODELLED_TRUTH_CHECKS:
            return value
        if check in SUPPORTED_TRUTH_CHECKS:
            raise ValueError(
                f"truth kind '{value}' exists in world_observer but its "
                f"postcondition shape is not modelled here "
                f"(modelled: {sorted(MODELLED_TRUTH_CHECKS)}) - it needs "
                f"spec keys a space contract cannot supply"
            )
        raise ValueError(
            f"truth kind '{value}' names no check world_observer "
            f"implements (available: {sorted(SUPPORTED_TRUTH_CHECKS)}) - "
            f"the re-query would silently never run"
        )


class SpaceEvent(BaseModel):
    tool: str
    required_params: List[str] = Field(default_factory=list)
    required_provenance: List[str] = Field(default_factory=list)
    truth: Optional[SpaceTruth] = None


class SpaceUI(BaseModel):
    embed: Literal["browserview", "none"] = "none"
    entry_url: Optional[str] = None


class SpaceRuntime(BaseModel):
    port: int
    healthz: str = "/healthz"
    start: str

    @field_validator("healthz")
    @classmethod
    def _validate_healthz(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError(
                f"runtime.healthz '{value}' must start with '/': "
                f"it is rendered straight into "
                f"@mcp.custom_route(healthz), and starlette's router "
                f"raises AssertionError('Routed paths must start with "
                f"\"/\"') at server load time otherwise"
            )
        return value


class SpaceContract(BaseModel):
    id: str
    description: str
    prefixes: List[str]
    tools: List[SpaceTool]
    events: Dict[str, SpaceEvent]
    ui: SpaceUI
    runtime: SpaceRuntime

    @property
    def agent_name(self) -> str:
        return f"brain-{self.id}"

    def tool_by_name(self, name: str) -> Optional[SpaceTool]:
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not SPACE_ID_PATTERN.match(value):
            raise ValueError(
                f"space id '{value}' is invalid: must be lowercase letters, "
                f"digits and underscores, starting with a letter "
                f"(pattern {SPACE_ID_PATTERN.pattern}) — hyphens are not "
                f"allowed because they make task ids ambiguous and are "
                f"unusable in env var names"
            )
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> "SpaceContract":
        names = [t.name for t in self.tools]
        duplicates = {n for n in names if names.count(n) > 1}
        if duplicates:
            raise ValueError(f"duplicate tool names: {sorted(duplicates)}")

        for event_name, event in self.events.items():
            if not any(event_name.startswith(p) for p in self.prefixes):
                raise ValueError(
                    f"event '{event_name}' does not start with any declared "
                    f"prefix {self.prefixes}"
                )
            tool = self.tool_by_name(event.tool)
            if tool is None:
                raise ValueError(
                    f"event '{event_name}' points at unknown tool "
                    f"'{event.tool}'"
                )
            unknown_params = [
                p for p in event.required_params if p not in tool.params
            ]
            if unknown_params:
                raise ValueError(
                    f"event '{event_name}' declares required_params "
                    f"{unknown_params} that are not params of tool "
                    f"'{event.tool}' (tool params: {tool.params}) - this "
                    f"would land in the registry as a routing requirement "
                    f"the tool can never satisfy"
                )
            if tool.side_effect == "write":
                if not event.required_provenance:
                    raise ValueError(
                        f"event '{event_name}' writes but declares no "
                        f"required_provenance"
                    )
                if event.truth is None:
                    raise ValueError(
                        f"event '{event_name}' writes but declares no truth "
                        f"validator"
                    )

            if event.truth is not None:
                self._complete_truth(event_name, event.truth, tool)

        wired = {e.tool for e in self.events.values()}
        for tool in self.tools:
            if tool.side_effect == "write" and tool.name not in wired:
                raise ValueError(
                    f"write tool '{tool.name}' has no event bound to it"
                )

        if self.ui.embed == "browserview" and not self.ui.entry_url:
            raise ValueError("ui.embed=browserview requires ui.entry_url")

        return self

    def _complete_truth(self, event_name: str, truth: SpaceTruth,
                        tool: SpaceTool) -> None:
        """Fill in what the contract can derive, refuse what it cannot.

        A postcondition missing its filter is not a smaller check - it is
        no check: world_observer returns UNVERIFIED for a supabase_row spec
        without `match`, so the write would route unverified.
        """
        check = truth.check
        if check == "supabase_row":
            if not truth.table:
                raise ValueError(
                    f"event '{event_name}' declares truth:supabase_row "
                    f"without a table to re-query"
                )
            if truth.match is None:
                if "id" in tool.returns:
                    # The op returns the row id, so the row can be
                    # re-queried by it (same pattern as the live
                    # bubble_create capability).
                    truth.match = "id=eq.{result_id}"
                else:
                    raise ValueError(
                        f"event '{event_name}' declares truth:supabase_row "
                        f"but tool '{tool.name}' returns no 'id' "
                        f"(returns: {sorted(tool.returns)}), so no match "
                        f"filter can be derived - give truth.match an "
                        f"explicit PostgREST filter"
                    )
            if truth.expect is None:
                truth.expect = "present"
            elif truth.expect not in ("present", "absent"):
                raise ValueError(
                    f"event '{event_name}' declares truth.expect "
                    f"'{truth.expect}'; world_observer only understands "
                    f"'present' and 'absent'"
                )
        elif check == "http_ok":
            if not truth.url:
                truth.url = (
                    f"http://127.0.0.1:{self.runtime.port}"
                    f"{self.runtime.healthz}"
                )
        elif check == "file_exists":
            if not truth.path:
                raise ValueError(
                    f"event '{event_name}' declares truth:file_exists "
                    f"without a path to stat"
                )


def load_contract(path: Path) -> SpaceContract:
    """Read and validate a contract from YAML.

    Raises ContractError if the file is unreadable, and pydantic's
    ValidationError if the content violates the contract rules.
    """
    path = Path(path)
    if not path.is_file():
        raise ContractError(f"contract not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContractError(f"contract is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ContractError(f"contract must be a mapping, got {type(raw)}")
    return SpaceContract(**raw)
