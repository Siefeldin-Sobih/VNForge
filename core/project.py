"""Project persistence, history, asset registry, and reporting helpers."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from core.schemas import AssetRecord, ProjectScene, ScenePlan, VNProject, utc_now


def new_project(title: str = "Untitled Visual Novel") -> VNProject:
    """Create an empty portable VNForge project."""
    return VNProject(title=title)


def rebuild_asset_registry(project: VNProject) -> None:
    """Deduplicate scene assets and preserve creator-managed production fields."""
    existing = {asset.name: asset for asset in project.asset_registry}
    rebuilt: dict[str, AssetRecord] = {}
    for project_scene in project.scenes:
        for cue in project_scene.plan.asset_cues:
            current = existing.get(cue.name)
            cue_data = cue.model_dump()
            cue_data["status"] = current.status if current else cue.status
            cue_data["file_path"] = current.file_path if current else cue.file_path
            record = AssetRecord(
                **cue_data,
                used_in_scenes=[],
            )
            if cue.name in rebuilt:
                record = rebuilt[cue.name]
            if project_scene.plan.scene_id not in record.used_in_scenes:
                record.used_in_scenes.append(project_scene.plan.scene_id)
            rebuilt[cue.name] = record
    project.asset_registry = sorted(rebuilt.values(), key=lambda item: item.name)
    project.updated_at = utc_now()


def upsert_scene(
    project: VNProject,
    source_text: str,
    genre: str,
    branching_depth: str,
    creative_mode: str,
    plan: ScenePlan,
    locked_sections: list[str] | None = None,
    continues_from: tuple[str, str] | None = None,
) -> None:
    """Insert or replace a project scene by its stable identifier."""
    existing_scene = next(
        (item for item in project.scenes if item.plan.scene_id == plan.scene_id),
        None,
    )
    plan_history = list(existing_scene.plan_history) if existing_scene else []
    if existing_scene and existing_scene.plan != plan:
        plan_history.append(existing_scene.plan.model_copy(deep=True))
        plan_history = plan_history[-20:]
    scene = ProjectScene(
        source_text=source_text,
        genre=genre,
        branching_depth=branching_depth,
        creative_mode=creative_mode,
        plan=plan,
        continues_from_scene_id=continues_from[0] if continues_from else None,
        continues_from_route_label=continues_from[1] if continues_from else None,
        plan_history=plan_history,
        locked_sections=locked_sections or [],
        updated_at=utc_now(),
    )
    for index, existing in enumerate(project.scenes):
        if existing.plan.scene_id == plan.scene_id:
            project.scenes[index] = scene
            break
    else:
        project.scenes.append(scene)
    if continues_from:
        source_scene_id, route_label = continues_from
        source_scene = next(
            (item for item in project.scenes if item.plan.scene_id == source_scene_id),
            None,
        )
        if source_scene:
            source_choice = next(
                (
                    choice
                    for choice in source_scene.plan.choices
                    if choice.route_label == route_label
                ),
                None,
            )
            if source_choice:
                source_choice.target_scene_id = plan.scene_id
    rebuild_asset_registry(project)


def save_project(project: VNProject, path: str) -> str:
    """Atomically save a project to a ``.vnforge`` JSON document."""
    destination = Path(path)
    if destination.suffix.lower() != ".vnforge":
        destination = destination.with_suffix(".vnforge")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = project.model_dump_json(indent=2)
    file_descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
    return str(destination.resolve())


def load_project(path: str) -> VNProject:
    """Load and validate a portable project document."""
    payload = Path(path).read_text(encoding="utf-8")
    project = VNProject.model_validate_json(payload)
    rebuild_asset_registry(project)
    return project


class ProjectHistory:
    """Bounded in-memory undo/redo history for project-changing operations."""

    def __init__(self, project: VNProject, limit: int = 30):
        self.limit = limit
        self._undo: list[VNProject] = []
        self._redo: list[VNProject] = []
        self.project = deepcopy(project)

    def checkpoint(self) -> None:
        """Record the current state before applying a mutation."""
        self._undo.append(deepcopy(self.project))
        self._undo = self._undo[-self.limit :]
        self._redo.clear()

    def undo(self) -> VNProject:
        """Restore and return the previous state."""
        if not self._undo:
            return self.project
        self._redo.append(deepcopy(self.project))
        self.project = self._undo.pop()
        return deepcopy(self.project)

    def redo(self) -> VNProject:
        """Restore and return the next state."""
        if not self._redo:
            return self.project
        self._undo.append(deepcopy(self.project))
        self.project = self._redo.pop()
        return deepcopy(self.project)

    @property
    def can_undo(self) -> bool:
        """Return whether an undo state is available."""
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        """Return whether a redo state is available."""
        return bool(self._redo)


def project_to_json(project: VNProject) -> str:
    """Return creator-editable project JSON."""
    return json.dumps(project.model_dump(mode="json"), indent=2, ensure_ascii=False)
