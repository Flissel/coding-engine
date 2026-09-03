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


class SpaceTruth(BaseModel):
    kind: str
    table: Optional[str] = None
    expect: Optional[str] = None


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

        wired = {e.tool for e in self.events.values()}
        for tool in self.tools:
            if tool.side_effect == "write" and tool.name not in wired:
                raise ValueError(
                    f"write tool '{tool.name}' has no event bound to it"
                )

        if self.ui.embed == "browserview" and not self.ui.entry_url:
            raise ValueError("ui.embed=browserview requires ui.entry_url")

        return self


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
