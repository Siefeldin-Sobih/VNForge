"""Semantic scene, project, continuity, and Ren'Py validation."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from core.schemas import Diagnostic, ScenePlan, VNProject

DEPTH_RANGES = {
    "linear": (0, 0),
    "shallow": (2, 2),
    "medium": (3, 4),
    "deep": (5, 8),
}


def validate_scene(plan: ScenePlan, branching_depth: str) -> list[Diagnostic]:
    """Return semantic findings for a generated scene plan."""
    findings: list[Diagnostic] = []
    minimum, maximum = DEPTH_RANGES.get(branching_depth, (2, 8))
    if not minimum <= len(plan.choices) <= maximum:
        findings.append(
            Diagnostic(
                severity="error",
                code="choice_count",
                scene_id=plan.scene_id,
                message=(
                    f"{branching_depth.title()} branching requires {minimum}–{maximum} "
                    f"choices; received {len(plan.choices)}."
                ),
            )
        )

    route_labels = [choice.route_label for choice in plan.choices]
    if len(route_labels) != len(set(route_labels)):
        findings.append(
            Diagnostic(
                severity="error",
                code="duplicate_route",
                scene_id=plan.scene_id,
                message="Choice route labels must be unique within a scene.",
            )
        )

    asset_names = [asset.name for asset in plan.asset_cues]
    if len(asset_names) != len(set(asset_names)):
        findings.append(
            Diagnostic(
                severity="error",
                code="duplicate_asset",
                scene_id=plan.scene_id,
                message="Asset identifiers must be unique within a scene.",
            )
        )
    known_assets = set(asset_names)
    assets_by_name = {asset.name: asset for asset in plan.asset_cues}
    for beat in plan.beats:
        if beat.kind in {"scene", "show", "hide", "music", "sound"}:
            if not beat.asset_id:
                findings.append(
                    Diagnostic(
                        severity="error",
                        code="missing_asset_id",
                        scene_id=plan.scene_id,
                        message=f"A {beat.kind} beat is missing its asset identifier.",
                    )
                )
            elif beat.asset_id not in known_assets:
                findings.append(
                    Diagnostic(
                        severity="error",
                        code="unknown_asset",
                        scene_id=plan.scene_id,
                        message=f"Beat references undeclared asset '{beat.asset_id}'.",
                    )
                )
            else:
                asset = assets_by_name[beat.asset_id]
                expected_type = {
                    "scene": "background",
                    "show": "character",
                    "hide": "character",
                    "music": "music",
                    "sound": "sound",
                }[beat.kind]
                if asset.cue_type != expected_type:
                    findings.append(
                        Diagnostic(
                            severity="error",
                            code="asset_type_mismatch",
                            scene_id=plan.scene_id,
                            message=(
                                f"A {beat.kind} beat requires a {expected_type} asset; "
                                f"'{beat.asset_id}' is {asset.cue_type}."
                            ),
                        )
                    )
                if (
                    beat.kind == "show"
                    and beat.expression
                    and beat.expression not in asset.variants
                ):
                    findings.append(
                        Diagnostic(
                            severity="error",
                            code="missing_variant",
                            scene_id=plan.scene_id,
                            message=(
                                f"Character '{beat.asset_id}' does not declare the "
                                f"'{beat.expression}' variant used by a show beat."
                            ),
                        )
                    )
        if beat.kind in {"dialogue", "narration"} and not beat.text:
            findings.append(
                Diagnostic(
                    severity="warning",
                    code="empty_text",
                    scene_id=plan.scene_id,
                    message=f"A {beat.kind} beat has no text.",
                )
            )
    return findings


def validate_renpy_source(source: str) -> list[Diagnostic]:
    """Perform fast static label and jump checks without requiring Ren'Py."""
    findings: list[Diagnostic] = []
    labels = re.findall(r"(?m)^label\s+([A-Za-z][A-Za-z0-9_]*):", source)
    jumps = re.findall(r"(?m)^\s+jump\s+([A-Za-z][A-Za-z0-9_]*)\s*$", source)
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    for label in duplicates:
        findings.append(
            Diagnostic(
                severity="error",
                code="duplicate_label",
                message=f"Ren'Py label '{label}' is defined more than once.",
            )
        )
    known = set(labels)
    for target in sorted(set(jumps) - known):
        findings.append(
            Diagnostic(
                severity="error",
                code="missing_label",
                message=f"Jump target '{target}' is not defined.",
            )
        )
    if not labels:
        findings.append(
            Diagnostic(
                severity="error",
                code="no_labels",
                message="Generated source contains no Ren'Py labels.",
            )
        )
    return findings


def analyze_project(project: VNProject) -> list[Diagnostic]:
    """Find cross-scene branch, canon, type, and asset continuity problems."""
    findings: list[Diagnostic] = []
    scene_ids = [scene.plan.scene_id for scene in project.scenes]
    if len(scene_ids) != len(set(scene_ids)):
        findings.append(
            Diagnostic(
                severity="error",
                code="duplicate_scene",
                message="Every scene must have a unique scene identifier.",
            )
        )
    known_scene_ids = set(scene_ids)
    reachable = {scene_ids[0]} if scene_ids else set()
    changed = True
    while changed:
        changed = False
        for project_scene in project.scenes:
            if project_scene.plan.scene_id not in reachable:
                continue
            targets = {
                choice.target_scene_id
                for choice in project_scene.plan.choices
                if choice.target_scene_id in known_scene_ids
            }
            if not targets.issubset(reachable):
                reachable.update(targets)
                changed = True
    for unreachable in sorted(known_scene_ids - reachable):
        findings.append(
            Diagnostic(
                severity="warning",
                code="unreachable_scene",
                scene_id=unreachable,
                message=f"Scene '{unreachable}' is unreachable from the first scene.",
            )
        )
    variable_types: dict[str, type] = {}
    asset_descriptions: dict[str, str] = {}
    asset_types: dict[str, str] = {}
    known_characters = {character.character_id for character in project.characters}
    for project_scene in project.scenes:
        plan = project_scene.plan
        for choice in plan.choices:
            if choice.target_scene_id and choice.target_scene_id not in known_scene_ids:
                findings.append(
                    Diagnostic(
                        severity="warning",
                        code="unresolved_branch",
                        scene_id=plan.scene_id,
                        message=(
                            f"Choice '{choice.choice_text}' targets missing scene "
                            f"'{choice.target_scene_id}'."
                        ),
                    )
                )
            for change in choice.state_changes:
                value_type = type(change.value)
                previous_type = variable_types.setdefault(change.name, value_type)
                if previous_type is not value_type:
                    findings.append(
                        Diagnostic(
                            severity="warning",
                            code="variable_type",
                            scene_id=plan.scene_id,
                            message=f"Variable '{change.name}' changes value type.",
                        )
                    )
        for beat in plan.beats:
            if beat.speaker and known_characters and beat.speaker not in known_characters:
                findings.append(
                    Diagnostic(
                        severity="info",
                        code="uncatalogued_character",
                        scene_id=plan.scene_id,
                        message=f"Speaker '{beat.speaker}' is not in the story bible.",
                    )
                )
        for asset in plan.asset_cues:
            if asset.file_path and not Path(asset.file_path).expanduser().is_file():
                findings.append(
                    Diagnostic(
                        severity="warning",
                        code="missing_asset_file",
                        scene_id=plan.scene_id,
                        message=(
                            f"Asset '{asset.name}' source file does not exist: {asset.file_path}"
                        ),
                    )
                )
            old_type = asset_types.setdefault(asset.name, asset.cue_type)
            if old_type != asset.cue_type:
                findings.append(
                    Diagnostic(
                        severity="error",
                        code="asset_type_drift",
                        scene_id=plan.scene_id,
                        message=f"Asset '{asset.name}' changes production type.",
                    )
                )
            old_description = asset_descriptions.setdefault(asset.name, asset.description)
            if old_description != asset.description:
                findings.append(
                    Diagnostic(
                        severity="warning",
                        code="asset_drift",
                        scene_id=plan.scene_id,
                        message=f"Asset '{asset.name}' has inconsistent descriptions.",
                    )
                )
    return findings


def find_renpy_executable(configured_path: str = "") -> str | None:
    """Locate a Ren'Py launcher script or executable."""
    candidates = [configured_path, os.getenv("RENPY_EXECUTABLE", "")]
    candidates.extend(shutil.which(name) or "" for name in ("renpy", "renpy.sh"))
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate).resolve())
    return None


def run_renpy_lint(project_dir: str, executable: str = "") -> tuple[bool, str]:
    """Run official Ren'Py lint when an SDK executable is available."""
    renpy = find_renpy_executable(executable)
    if not renpy:
        return False, "Ren'Py SDK not configured; VNForge static validation passed."
    command = [renpy, project_dir, "lint", "--error-code"]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return completed.returncode == 0, output.strip()
