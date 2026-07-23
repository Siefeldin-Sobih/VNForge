"""VNForge scene compilation pipeline."""

from __future__ import annotations

import threading

from core.prompts import build_compile_prompt, build_continue_prompt
from core.renderer import render_scene
from core.schemas import ScenePlan, VNForgeResult, VNProject
from core.validation import validate_renpy_source, validate_scene


def estimate_input_tokens(scene_text: str, project: VNProject | None = None) -> int:
    """Return a conservative provider-independent token estimate."""
    context_size = len(project.model_dump_json()) if project else 0
    return max(1, (len(scene_text) + context_size + 3200) // 4)


def compile_scene(
    scene_text: str,
    genre: str,
    branching_depth: str,
    creative_mode: str = "balanced",
    project: VNProject | None = None,
    previous_plan: ScenePlan | None = None,
    regenerate_section: str = "",
    locked_sections: list[str] | None = None,
    cancel_event: threading.Event | None = None,
    continues_from: tuple[str, str] | None = None,
) -> VNForgeResult:
    """Compile prose into a validated plan and deterministic Ren'Py source."""
    from core.model_client import call_model

    if not scene_text.strip():
        raise ValueError("Creator prose is empty. Paste prose before compiling.")

    system, user = build_compile_prompt(
        scene_text,
        genre,
        branching_depth,
        creative_mode,
        project,
        previous_plan,
        regenerate_section,
        continues_from,
    )
    plan = None
    semantic_diagnostics = []
    for semantic_attempt in range(3):
        plan = call_model(system, user, cancel_event=cancel_event)
        semantic_diagnostics = validate_scene(plan, branching_depth)
        errors = [item.message for item in semantic_diagnostics if item.severity == "error"]
        if not errors:
            break
        if semantic_attempt < 2:
            user += (
                "\n\nYour previous plan failed semantic validation. Return a corrected "
                "complete plan. ERRORS:\n- " + "\n- ".join(errors)
            )
    assert plan is not None
    for asset in plan.asset_cues:
        # File locations and approval states belong to the creator, never the model.
        asset.file_path = ""
        asset.status = "planned"
    if previous_plan:
        plan.scene_id = previous_plan.scene_id
    if previous_plan and locked_sections:
        for section in locked_sections:
            setattr(plan, section, getattr(previous_plan, section))

    diagnostics = validate_scene(plan, branching_depth)
    if any(item.severity == "error" for item in diagnostics):
        messages = "; ".join(item.message for item in diagnostics if item.severity == "error")
        raise ValueError(f"Generated scene failed semantic validation: {messages}")
    script = render_scene(plan)
    allowed_project_targets = (
        {f"scene_{item.plan.scene_id}" for item in project.scenes} if project else set()
    )
    static_diagnostics = validate_renpy_source(script, known_labels=allowed_project_targets)
    diagnostics.extend(static_diagnostics)
    if any(item.severity == "error" for item in diagnostics):
        messages = "; ".join(item.message for item in diagnostics if item.severity == "error")
        raise ValueError(f"Generated Ren'Py failed validation: {messages}")
    return VNForgeResult(
        **plan.model_dump(),
        renpy_script=script,
        diagnostics=diagnostics,
    )


def continue_scene(
    scene_text: str,
    genre: str,
    branching_depth: str,
    prev_title: str,
    prev_summary: str,
    prev_route_label: str,
    prev_consequence: str,
) -> VNForgeResult:
    """Compile a continuation for legacy API callers."""
    from core.model_client import call_model

    system, user = build_continue_prompt(
        scene_text,
        genre,
        branching_depth,
        prev_title,
        prev_summary,
        prev_route_label,
        prev_consequence,
    )
    plan = call_model(system, user)
    diagnostics = validate_scene(plan, branching_depth)
    if any(item.severity == "error" for item in diagnostics):
        messages = "; ".join(item.message for item in diagnostics if item.severity == "error")
        raise ValueError(f"Generated continuation failed validation: {messages}")
    script = render_scene(plan)
    diagnostics.extend(validate_renpy_source(script))
    if any(item.severity == "error" for item in diagnostics):
        messages = "; ".join(item.message for item in diagnostics if item.severity == "error")
        raise ValueError(f"Generated continuation script failed validation: {messages}")
    return VNForgeResult(
        **plan.model_dump(),
        renpy_script=script,
        diagnostics=diagnostics,
    )
