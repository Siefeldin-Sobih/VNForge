# core/schemas.py
# Defines the data structures for everything VNForge produces.
#
# These are Pydantic models — they act as both type hints and validators.
# When the compiler parses JSON from the AI model, it passes the raw dict
# into VNForgeResult(**data). Pydantic checks that every required field is
# present and has the correct type, raising ValidationError immediately if not.
#
# This is the contract between the AI output and the rest of the app.

from pydantic import BaseModel, Field
from typing import List


class VNChoice(BaseModel):
    """
    Represents one branching choice the player can make at the end of a scene.

    Fields:
        choice_text     — The line of text shown to the player in the choice menu.
                          Example: "Ask her about the letter."

        variable_change — A Ren'Py-compatible variable assignment string.
                          The compiler uses this to set game flags/state.
                          Example: "trust_alex = True"

        route_label     — The Ren'Py label the game will jump to if this choice
                          is selected. Must be snake_case (no spaces).
                          Example: "route_ask_letter"

        consequence     — A short human-readable description of what this choice
                          leads to. Used in the Production Notes tab and by the
                          writer to understand the story branching.
                          Example: "Alex opens up and shares a secret."
    """

    choice_text: str
    variable_change: str
    route_label: str
    consequence: str


class AssetCue(BaseModel):
    """
    Represents one asset that the scene requires — a background, character
    sprite, music track, or sound effect.

    These are instructions written to the art/audio team describing what
    needs to be created.

    Fields:
        cue_type    — Category of the asset. One of:
                        "background" — a scene backdrop image
                        "character"  — a character sprite
                        "music"      — a background music track
                        "sound"      — a one-shot sound effect

        name        — The identifier used in the Ren'Py script.
                      Example: "bg_train_station", "music_melancholy"

        description — A plain-English description for the artist or composer.
                      Example: "A rainy train platform at dusk, dim yellow lights."
    """

    cue_type: str
    name: str
    description: str


class VNForgeResult(BaseModel):
    """
    The complete output of one compile_scene() call.

    This is the single object passed from the compiler back to the desktop app.
    Every tab in the UI reads from a different field of this model:
        - Script tab       → renpy_script
        - Choices tab      → choices
        - Assets tab       → asset_cues
        - Notes tab        → production_notes

    Fields:
        scene_title       — Short title for the compiled scene.
                            Example: "The Last Train"

        scene_summary     — 1-2 sentence summary of what happens.
                            Used as a header in the exported markdown report.

        renpy_script      — The full Ren'Py script as a single multi-line string.
                            Contains labels, dialogue, show/play commands, and
                            a menu block for the branching choices.

        choices           — List of VNChoice objects (the branching options).
                            The number of choices depends on branching_depth.

        asset_cues        — List of AssetCue objects (what needs to be made).
                            Exported separately as the asset list.

        production_notes  — List of short strings. Developer reminders about
                            pacing, animation, voice acting, or script issues.
    """

    scene_title: str
    scene_summary: str
    renpy_script: str
    choices: List[VNChoice]
    asset_cues: List[AssetCue] = Field(default_factory=list)
    production_notes: List[str] = Field(default_factory=list)
