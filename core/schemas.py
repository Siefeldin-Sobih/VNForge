"""Validated data contracts used throughout VNForge.

The language model is only allowed to create :class:`ScenePlan` data.  Ren'Py
source is rendered locally from that constrained representation, which keeps
model output editable and prevents arbitrary script generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

RENPY_RESERVED_NAMES = {
    "default",
    "define",
    "hide",
    "image",
    "init",
    "jump",
    "label",
    "menu",
    "play",
    "python",
    "return",
    "scene",
    "screen",
    "show",
    "transform",
}


def reject_reserved_identifier(value: str) -> str:
    """Reject identifiers that are ambiguous as Ren'Py statements."""
    if value.lower() in RENPY_RESERVED_NAMES:
        raise ValueError(f"'{value}' is reserved by Ren'Py")
    return value


Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
    ),
    AfterValidator(reject_reserved_identifier),
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
AssetType = Literal["background", "character", "music", "sound"]
AssetStatus = Literal["planned", "in_progress", "ready", "approved"]
BeatKind = Literal[
    "narration",
    "dialogue",
    "scene",
    "show",
    "hide",
    "music",
    "sound",
    "pause",
]
BranchingDepth = Literal["linear", "shallow", "medium", "deep"]
CreativeMode = Literal["preserve", "balanced", "adapt"]
StateValue = bool | int | float | str


def utc_now() -> str:
    """Return a stable ISO-8601 timestamp for project metadata."""
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    """Base model that rejects unrecognized model-generated fields."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class StateChange(StrictModel):
    """A constrained store-variable update applied after a player choice."""

    name: Identifier
    value: StateValue


class VNChoice(StrictModel):
    """A player-facing choice and its intended route."""

    choice_text: NonEmptyText
    state_changes: list[StateChange] = Field(default_factory=list, max_length=8)
    route_label: Identifier
    consequence: NonEmptyText
    target_scene_id: Identifier | None = None

    @property
    def variable_change(self) -> str:
        """Return a readable compatibility summary for reports."""
        if not self.state_changes:
            return "none"
        return ", ".join(f"{change.name} = {change.value!r}" for change in self.state_changes)


class SceneBeat(StrictModel):
    """One safe, ordered instruction in a visual-novel scene."""

    kind: BeatKind
    text: str = ""
    speaker: Identifier | None = None
    speaker_name: str = ""
    asset_id: Identifier | None = None
    expression: Identifier | None = None
    transition: Literal["none", "dissolve", "fade", "moveinright", "moveinleft"] = "none"
    duration: float | None = Field(default=None, ge=0, le=30)

    @field_validator("text", "speaker_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        """Strip accidental surrounding whitespace from generated content."""
        return value.strip()


class AssetCue(StrictModel):
    """A reusable art or audio production item."""

    cue_type: AssetType
    name: Identifier
    description: NonEmptyText
    variants: list[Identifier] = Field(default_factory=list, max_length=30)
    status: AssetStatus = "planned"
    file_path: str = ""
    width: int | None = Field(default=None, ge=1, le=16384)
    height: int | None = Field(default=None, ge=1, le=16384)


class ScenePlan(StrictModel):
    """Constrained model output for a single visual-novel scene."""

    scene_id: Identifier
    scene_title: NonEmptyText
    scene_summary: NonEmptyText
    beats: list[SceneBeat] = Field(min_length=1, max_length=250)
    choices: list[VNChoice] = Field(default_factory=list, max_length=8)
    asset_cues: list[AssetCue] = Field(default_factory=list, max_length=100)
    production_notes: list[NonEmptyText] = Field(default_factory=list, max_length=30)


class Diagnostic(StrictModel):
    """A validation or continuity finding shown to the creator."""

    severity: Literal["info", "warning", "error"]
    code: Identifier
    message: NonEmptyText
    scene_id: Identifier | None = None


class VNForgeResult(ScenePlan):
    """A scene plan plus deterministic compiler output and diagnostics."""

    renpy_script: str
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class CharacterProfile(StrictModel):
    """Project-level canon used for continuity and prompt grounding."""

    character_id: Identifier
    display_name: NonEmptyText
    pronouns: str = ""
    appearance: str = ""
    personality: str = ""
    relationships: str = ""
    notes: str = ""


class ProjectScene(StrictModel):
    """A compiled scene and the creator inputs needed to regenerate it."""

    source_text: NonEmptyText
    genre: NonEmptyText
    branching_depth: BranchingDepth
    creative_mode: CreativeMode = "balanced"
    plan: ScenePlan
    continues_from_scene_id: Identifier | None = None
    continues_from_route_label: Identifier | None = None
    plan_history: list[ScenePlan] = Field(default_factory=list, max_length=20)
    locked_sections: list[Literal["beats", "choices", "asset_cues", "production_notes"]] = Field(
        default_factory=list
    )
    updated_at: str = Field(default_factory=utc_now)


class AssetRecord(AssetCue):
    """Deduplicated project asset with automatic scene usage."""

    used_in_scenes: list[Identifier] = Field(default_factory=list)


class VNProject(StrictModel):
    """Portable ``.vnforge`` project file."""

    format_version: int = 1
    project_id: Identifier = Field(default_factory=lambda: f"project_{uuid4().hex[:10]}")
    title: NonEmptyText = "Untitled Visual Novel"
    author: str = ""
    synopsis: str = ""
    world_rules: list[str] = Field(default_factory=list)
    characters: list[CharacterProfile] = Field(default_factory=list)
    scenes: list[ProjectScene] = Field(default_factory=list)
    asset_registry: list[AssetRecord] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
