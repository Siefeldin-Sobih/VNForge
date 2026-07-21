"""Shared validated fixtures for VNForge tests."""

from core.schemas import AssetCue, SceneBeat, ScenePlan, StateChange, VNChoice


def sample_plan(
    scene_id: str = "arrival",
    route_labels: tuple[str, str] = ("stay", "leave"),
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
                state_changes=[StateChange(name="mia_stayed", value=True)],
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
