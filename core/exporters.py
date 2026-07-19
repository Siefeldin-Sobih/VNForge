# core/exporters.py
# Writes compiled VNForgeResult data to files on disk.
# All three functions save into an "exports/" folder next to this file
# and return the full path so the UI can display it in the status bar.

import os
from core.schemas import VNForgeResult

_EXPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exports")


def _ensure_exports_dir() -> str:
    """Create the exports directory if it doesn't exist and return its path."""
    os.makedirs(_EXPORTS_DIR, exist_ok=True)
    return _EXPORTS_DIR


def export_rpy(scene: VNForgeResult) -> str:
    """Write the Ren'Py script to a .rpy file and return the file path."""
    dest = _ensure_exports_dir()
    slug = scene.scene_title.lower().replace(" ", "_")
    path = os.path.join(dest, f"{slug}.rpy")
    with open(path, "w", encoding="utf-8") as f:
        f.write(scene.renpy_script)
    return path


def export_asset_list(scene: VNForgeResult) -> str:
    """Write the asset cues to a plain-text file and return the file path."""
    dest = _ensure_exports_dir()
    slug = scene.scene_title.lower().replace(" ", "_")
    path = os.path.join(dest, f"{slug}_assets.txt")
    lines = []
    for a in scene.asset_cues:
        lines.append(f"[{a.cue_type.upper()}]  {a.name}")
        lines.append(f"  {a.description}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def export_markdown_report(scene: VNForgeResult) -> str:
    """Write a full markdown report of the compiled scene and return the file path."""
    dest = _ensure_exports_dir()
    slug = scene.scene_title.lower().replace(" ", "_")
    path = os.path.join(dest, f"{slug}_report.md")

    lines = [
        f"# {scene.scene_title}",
        "",
        f"> {scene.scene_summary}",
        "",
        "## Ren'Py Script",
        "",
        "```renpy",
        scene.renpy_script,
        "```",
        "",
        "## Choices",
        "",
    ]
    for c in scene.choices:
        lines.append(f"- **{c.choice_text}**")
        lines.append(f"  - Route: `{c.route_label}`")
        lines.append(f"  - Variable: `{c.variable_change}`")
        lines.append(f"  - Consequence: {c.consequence}")
        lines.append("")

    lines += ["## Asset Cues", ""]
    for a in scene.asset_cues:
        lines.append(f"- `[{a.cue_type.upper()}]` **{a.name}** — {a.description}")
    lines.append("")

    lines += ["## Production Notes", ""]
    for note in scene.production_notes:
        lines.append(f"- {note}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path
