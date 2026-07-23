"""Shared validated fixtures for VNForge tests."""

from __future__ import annotations

from core.project import new_project, upsert_scene
from core.schemas import (
    AssetCue,
    SceneBeat,
    ScenePlan,
    StateChange,
    VNChoice,
    VNProject,
)


def sample_plan(
    scene_id: str = "arrival",
    route_labels: tuple[str, str] = ("stay", "leave"),
    flag_name: str = "mia_stayed",
) -> ScenePlan:
    """Return a small representative scene plan."""
    return ScenePlan(
        scene_id=scene_id,
        scene_title="Chapter 1/Arrival",
        scene_summary="Mia reaches the final train and must decide what to do.",
        beats=[
            SceneBeat(kind="scene", asset_id="bg_station", transition="fade"),
            SceneBeat(
                kind="show",
                asset_id="mia",
                expression="worried",
                transition="dissolve",
            ),
            SceneBeat(
                kind="dialogue",
                speaker="mia",
                speaker_name="Mia",
                text='What if {b}this[/name] is "wrong"?',
            ),
        ],
        choices=[
            VNChoice(
                choice_text="Stay",
                route_label=route_labels[0],
                consequence="Mia stays on the platform.",
                state_changes=[StateChange(name=flag_name, value=True)],
            ),
            VNChoice(
                choice_text="Leave",
                route_label=route_labels[1],
                consequence="Mia boards the train.",
            ),
        ],
        asset_cues=[
            AssetCue(
                cue_type="background",
                name="bg_station",
                description="An empty station at night.",
                width=1920,
                height=1080,
            ),
            AssetCue(
                cue_type="character",
                name="mia",
                description="Mia in a travel coat.",
                variants=["worried"],
            ),
        ],
        production_notes=["Pause before the choice menu."],
    )


def chained_project() -> VNProject:
    """Return a three-scene project with continuation links between choices."""
    project = new_project("Latch Mystery")
    hallway = sample_plan("hallway", ("examine_latch", "walk_away"), "examined_latch")
    closet = sample_plan("closet", ("open_door", "retreat"), "door_opened")
    ending = sample_plan("ending", ("confess", "conceal"), "secret_known")
    upsert_scene(project, "Hallway prose", "mystery", "shallow", "balanced", hallway)
    upsert_scene(
        project,
        "Closet prose",
        "mystery",
        "shallow",
        "balanced",
        closet,
        continues_from=("hallway", "examine_latch"),
    )
    upsert_scene(
        project,
        "Ending prose",
        "mystery",
        "shallow",
        "balanced",
        ending,
        continues_from=("closet", "open_door"),
    )
    return project
