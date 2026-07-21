"""Import prose documents and a safe subset of existing Ren'Py scripts."""

from __future__ import annotations

import re
from pathlib import Path

from core.renderer import sanitize_identifier
from core.schemas import AssetCue, SceneBeat, ScenePlan, VNChoice

QUOTED_TEXT = r'"((?:[^"\\]|\\.)*)"'


def import_document(path: str) -> tuple[str, ScenePlan | None]:
    """Import text/Markdown as prose or parse an existing ``.rpy`` scene plan."""
    source = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() != ".rpy":
        return source, None
    return source, parse_renpy(source, Path(path).stem)


def _unescape(value: str) -> str:
    """Decode the limited escapes used by quoted Ren'Py dialogue strings."""
    return value.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


def parse_renpy(source: str, fallback_title: str = "Imported Scene") -> ScenePlan:
    """Parse common Ren'Py scene, dialogue, audio, menu, and route statements.

    Unsupported Python and custom statements are intentionally omitted and
    reported in production notes; they are never copied into executable output.
    """
    label_match = re.search(r"(?m)^label\s+([A-Za-z][A-Za-z0-9_]*):", source)
    raw_label = label_match.group(1) if label_match else fallback_title
    scene_id = sanitize_identifier(raw_label.removeprefix("scene_"), "imported")
    characters = {
        match.group(1): _unescape(match.group(2))
        for match in re.finditer(
            rf"(?m)^define\s+([A-Za-z][A-Za-z0-9_]*)\s*=\s*Character\({QUOTED_TEXT}",
            source,
        )
    }
    assets: dict[str, AssetCue] = {}
    for match in re.finditer(
        rf"(?m)^image\s+([A-Za-z][A-Za-z0-9_]*)[^=]*=\s*{QUOTED_TEXT}",
        source,
    ):
        name, file_path = match.group(1), _unescape(match.group(2))
        cue_type = "background" if name.startswith("bg") else "character"
        assets[name] = AssetCue(
            cue_type=cue_type,
            name=name,
            description=f"Imported {cue_type} '{name}'.",
            file_path=file_path,
        )

    beats: list[SceneBeat] = []
    choices: list[VNChoice] = []
    in_menu = False
    pending_choice = ""
    for line in source.splitlines():
        stripped = line.strip()
        if stripped == "menu:":
            in_menu = True
            continue
        choice_match = re.match(rf"{QUOTED_TEXT}:$", stripped)
        if in_menu and choice_match:
            pending_choice = _unescape(choice_match.group(1))
            continue
        jump_match = re.match(r"jump\s+([A-Za-z][A-Za-z0-9_]*)$", stripped)
        if in_menu and pending_choice and jump_match:
            route = jump_match.group(1)
            choices.append(
                VNChoice(
                    choice_text=pending_choice,
                    route_label=route,
                    consequence=f"Imported route '{route}'.",
                )
            )
            pending_choice = ""
            continue
        stage_match = re.match(
            r"(scene|show|hide)\s+([A-Za-z][A-Za-z0-9_]*)"
            r"(?:\s+([A-Za-z][A-Za-z0-9_]*))?",
            stripped,
        )
        if stage_match:
            kind, asset_id, expression = stage_match.groups()
            if asset_id not in assets:
                cue_type = "background" if kind == "scene" else "character"
                assets[asset_id] = AssetCue(
                    cue_type=cue_type,
                    name=asset_id,
                    description=f"Imported {cue_type} '{asset_id}'.",
                )
            beats.append(SceneBeat(kind=kind, asset_id=asset_id, expression=expression))
            continue
        audio_match = re.match(rf"play\s+(music|sound)\s+{QUOTED_TEXT}", stripped)
        if audio_match:
            cue_type, file_path = audio_match.groups()
            name = sanitize_identifier(Path(file_path).stem, cue_type)
            assets[name] = AssetCue(
                cue_type=cue_type,
                name=name,
                description=f"Imported {cue_type} '{name}'.",
                file_path=_unescape(file_path),
            )
            beats.append(SceneBeat(kind=cue_type, asset_id=name))
            continue
        pause_match = re.match(r"pause(?:\s+([0-9.]+))?$", stripped)
        if pause_match:
            beats.append(SceneBeat(kind="pause", duration=float(pause_match.group(1) or 0.5)))
            continue
        dialogue_match = re.match(rf"([A-Za-z][A-Za-z0-9_]*)\s+{QUOTED_TEXT}$", stripped)
        if dialogue_match and dialogue_match.group(1) not in {"define", "image"}:
            speaker, text = dialogue_match.groups()
            beats.append(
                SceneBeat(
                    kind="dialogue",
                    speaker=speaker,
                    speaker_name=characters.get(speaker, speaker.replace("_", " ").title()),
                    text=_unescape(text),
                )
            )
            continue
        narration_match = re.match(rf"{QUOTED_TEXT}$", stripped)
        if narration_match and not in_menu:
            beats.append(SceneBeat(kind="narration", text=_unescape(narration_match.group(1))))
    if not beats:
        beats.append(
            SceneBeat(
                kind="narration",
                text="Imported script contained no supported scene or dialogue statements.",
            )
        )
    notes = ["Imported from existing Ren'Py; review all parsed content."]
    if any(token in source for token in ("python:", "init python:", "$ renpy.")):
        notes.append("Unsupported Python statements were intentionally omitted for safety.")
    title = fallback_title.replace("_", " ").strip().title() or "Imported Scene"
    return ScenePlan(
        scene_id=scene_id,
        scene_title=title,
        scene_summary="Imported from an existing Ren'Py script.",
        beats=beats,
        choices=choices,
        asset_cues=list(assets.values()),
        production_notes=notes,
    )
