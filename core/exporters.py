"""Safe scene reports and complete playable Ren'Py project exports."""

from __future__ import annotations

import csv
import html
import math
import shutil
import struct
import wave
from copy import deepcopy
from pathlib import Path

from core.renderer import escape_text, render_project, safe_filename
from core.schemas import AssetRecord, VNForgeResult, VNProject
from core.validation import run_renpy_lint, validate_renpy_source

DEFAULT_EXPORTS_DIR = Path(__file__).resolve().parent.parent / "exports"


def _exports_dir(destination: str = "") -> Path:
    """Create and return the selected exports directory."""
    path = Path(destination).expanduser() if destination else DEFAULT_EXPORTS_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def export_rpy(scene: VNForgeResult, destination: str = "") -> str:
    """Write one deterministic scene script using a safe filename."""
    path = _exports_dir(destination) / f"{safe_filename(scene.scene_title)}.rpy"
    path.write_text(scene.renpy_script, encoding="utf-8")
    return str(path)


def export_asset_list(scene: VNForgeResult, destination: str = "") -> str:
    """Write a readable scene asset list."""
    path = _exports_dir(destination) / (f"{safe_filename(scene.scene_title)}_assets.txt")
    lines = []
    for asset in scene.asset_cues:
        lines.extend(
            [
                f"[{asset.cue_type.upper()}] {asset.name}",
                f"  {asset.description}",
                f"  Variants: {', '.join(asset.variants) or 'none'}",
                f"  Status: {asset.status}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def export_markdown_report(scene: VNForgeResult, destination: str = "") -> str:
    """Write a full scene report for writers, artists, and developers."""
    path = _exports_dir(destination) / (f"{safe_filename(scene.scene_title)}_report.md")
    lines = [
        f"# {scene.scene_title}",
        "",
        f"> {scene.scene_summary}",
        "",
        "## Ren'Py Script",
        "",
        "```renpy",
        scene.renpy_script.rstrip(),
        "```",
        "",
        "## Choices",
        "",
    ]
    for choice in scene.choices:
        lines.extend(
            [
                f"- **{choice.choice_text}**",
                f"  - Route: `{choice.route_label}`",
                f"  - State: `{choice.variable_change}`",
                f"  - Consequence: {choice.consequence}",
                f"  - Target scene: `{choice.target_scene_id or 'route stub'}`",
                "",
            ]
        )
    lines.extend(["## Asset Cues", ""])
    for asset in scene.asset_cues:
        lines.append(
            f"- `[{asset.cue_type.upper()}]` **{asset.name}** — "
            f"{asset.description} ({asset.status})"
        )
    lines.extend(["", "## Production Notes", ""])
    lines.extend(f"- {note}" for note in scene.production_notes)
    if scene.diagnostics:
        lines.extend(["", "## Validation", ""])
        lines.extend(
            f"- **{item.severity.upper()}** `{item.code}` — {item.message}"
            for item in scene.diagnostics
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def export_asset_csv(project: VNProject, destination: str = "") -> str:
    """Export the project production board for spreadsheet collaboration."""
    path = _exports_dir(destination) / "asset_production_board.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "type",
                "identifier",
                "description",
                "variants",
                "status",
                "file_path",
                "dimensions",
                "used_in_scenes",
            ]
        )
        for asset in project.asset_registry:
            dimensions = f"{asset.width}x{asset.height}" if asset.width and asset.height else ""
            writer.writerow(
                [
                    asset.cue_type,
                    asset.name,
                    asset.description,
                    ", ".join(asset.variants),
                    asset.status,
                    asset.file_path,
                    dimensions,
                    ", ".join(asset.used_in_scenes),
                ]
            )
    return str(path)


def _placeholder_svg(asset: AssetRecord, path: Path) -> None:
    """Create a clearly labeled SVG placeholder for visual playtesting."""
    width = asset.width or (1920 if asset.cue_type == "background" else 900)
    height = asset.height or 1080
    color = "#26324a" if asset.cue_type == "background" else "#633b73"
    label = html.escape(asset.name)
    description = html.escape(asset.description[:100])
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="{color}"/>
<rect x="40" y="40" width="{width - 80}" height="{height - 80}" fill="none" stroke="#9aa6c4" stroke-width="4" stroke-dasharray="16 12"/>
<text x="50%" y="47%" fill="white" text-anchor="middle" font-family="sans-serif" font-size="48">{label}</text>
<text x="50%" y="54%" fill="#d7dded" text-anchor="middle" font-family="sans-serif" font-size="24">{description}</text>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def _placeholder_wav(path: Path, duration: float = 0.5) -> None:
    """Create a short silent WAV accepted by Ren'Py audio channels."""
    sample_rate = 22050
    frame_count = math.ceil(sample_rate * duration)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(struct.pack("<h", 0) * frame_count)


def _materialize_asset(asset: AssetRecord, game_dir: Path) -> str:
    """Copy a creator asset when available, otherwise create a placeholder."""
    folder = "images" if asset.cue_type in {"background", "character"} else "audio"
    extension = ".svg" if folder == "images" else ".wav"
    destination = game_dir / folder / f"{asset.name}{extension}"
    source = Path(asset.file_path).expanduser() if asset.file_path else None
    if source and source.is_file():
        destination = destination.with_suffix(source.suffix.lower())
        shutil.copy2(source, destination)
        return f"{folder}/{destination.name}"
    if folder == "images":
        _placeholder_svg(asset, destination)
    else:
        _placeholder_wav(destination)
    return f"{folder}/{destination.name}"


def export_playable_project(
    project: VNProject,
    destination: str = "",
    renpy_executable: str = "",
) -> tuple[str, bool, str]:
    """Export a complete Ren'Py project with placeholders and optional lint."""
    root = _exports_dir(destination) / f"{safe_filename(project.title)}_renpy"
    game_dir = root / "game"
    (game_dir / "images").mkdir(parents=True, exist_ok=True)
    (game_dir / "audio").mkdir(parents=True, exist_ok=True)
    export_project = deepcopy(project)
    exported_paths = {
        asset.name: _materialize_asset(asset, game_dir) for asset in export_project.asset_registry
    }
    for project_scene in export_project.scenes:
        for cue in project_scene.plan.asset_cues:
            cue.file_path = exported_paths.get(cue.name, cue.file_path)
    script = render_project(export_project)
    static_findings = validate_renpy_source(script)
    errors = [item.message for item in static_findings if item.severity == "error"]
    if errors:
        raise ValueError("Project export failed static validation: " + "; ".join(errors))
    (game_dir / "script.rpy").write_text(script, encoding="utf-8")
    options = f'''define config.name = "{escape_text(project.title)}"
define build.name = "{safe_filename(project.title)}"
define config.version = "1.0"
'''
    (game_dir / "options.rpy").write_text(options, encoding="utf-8")
    lint_ok, lint_output = run_renpy_lint(str(root), renpy_executable)
    (root / "VNFORGE_EXPORT.txt").write_text(
        "This project was generated by VNForge. Placeholder assets are clearly "
        "labeled and may be replaced in game/images and game/audio.\n\n" + lint_output,
        encoding="utf-8",
    )
    return str(root), lint_ok, lint_output
