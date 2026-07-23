"""Offline structural checks for compiled Ren'Py output.

These tests reproduce bugs found during manual QA. They never call a live
provider — the model layer is mocked or bypassed with fixture plans.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.compiler import compile_scene
from core.model_client import call_model
from core.project import new_project, upsert_scene
from core.renderer import render_project, render_scene
from core.schemas import VNForgeResult
from core.validation import analyze_project, validate_renpy_source
from tests.helpers import chained_project, sample_plan
from tests.renpy_checks import (
    boolean_defaults,
    near_duplicate_flag_groups,
    unresolved_jumps,
)

# Fields a successful compile must always populate with real content.
# choices / asset_cues / production_notes may legitimately be empty (e.g. linear).
REQUIRED_NONEMPTY_FIELDS = (
    "scene_id",
    "scene_title",
    "scene_summary",
    "beats",
    "renpy_script",
    "diagnostics",
)


def test_boolean_defaults_are_false_even_when_choice_sets_true() -> None:
    """Flags meaning 'the player did X' must start False before any choice."""
    plan = sample_plan(flag_name="examined_latch")
    assert plan.choices[0].state_changes[0].value is True

    script = render_scene(plan)
    defaults = boolean_defaults(script)

    assert defaults, "expected at least one boolean default declaration"
    assert all(value is False for _, value in defaults), defaults
    assert ("examined_latch", False) in defaults
    # The choice outcome may still assign True after the player picks it.
    assert "$ examined_latch = True" in script


def test_project_boolean_defaults_are_false_across_scenes() -> None:
    """Combined project scripts must also initialize every boolean flag to False."""
    script = render_project(chained_project())
    defaults = boolean_defaults(script)
    assert defaults
    assert all(value is False for _, value in defaults), defaults


def test_jump_targets_resolve_across_multi_scene_chain() -> None:
    """Every jump in a linked multi-scene project must land on a real label."""
    project = chained_project()
    script = render_project(project)

    missing = unresolved_jumps(script)
    assert not missing, f"unresolved jump targets: {sorted(missing)}"
    assert not validate_renpy_source(script)

    # Continuity links should emit cross-scene jumps, not only local routes.
    assert "jump scene_closet" in script
    assert "jump scene_ending" in script
    assert "label scene_hallway:" in script
    assert "label scene_closet:" in script
    assert "label scene_ending:" in script


def test_broken_cross_scene_jump_is_detected() -> None:
    """A jump to a missing scene label must surface as an unresolved target."""
    project = new_project("Broken")
    plan = sample_plan("start", ("go", "stay"))
    plan.choices[0].target_scene_id = "does_not_exist"
    upsert_scene(project, "Source", "mystery", "shallow", "balanced", plan)

    script = render_project(project)
    assert "scene_does_not_exist" in unresolved_jumps(script)


def test_near_duplicate_flags_are_detected_across_scenes() -> None:
    """Same concept under reordered/reshaped names should be flagged."""
    project = new_project("Renamed Flags")
    scene_three = sample_plan("scene_three", ("look", "leave"), "examined_latch")
    scene_four = sample_plan("scene_four", ("look", "leave"), "latch_examined")
    upsert_scene(project, "Three", "mystery", "shallow", "balanced", scene_three)
    upsert_scene(project, "Four", "mystery", "shallow", "balanced", scene_four)

    groups = near_duplicate_flag_groups(project)
    assert ["examined_latch", "latch_examined"] in groups
    findings = analyze_project(project)
    assert any(item.code == "variable_name_drift" for item in findings)


def test_scene_validation_accepts_known_cross_scene_labels() -> None:
    """Per-scene UI validation must resolve labels defined by other project scenes."""
    project = chained_project()
    hallway = project.scenes[0].plan
    script = render_scene(hallway)
    known_labels = {f"scene_{scene.plan.scene_id}" for scene in project.scenes}

    assert not validate_renpy_source(script, known_labels=known_labels)


def test_consistent_flag_names_are_not_reported_as_duplicates() -> None:
    """Distinct concepts and identical reuse must not raise false alarms."""
    project = chained_project()
    # Reuse the same flag name in a later scene — that is consistency, not drift.
    later = sample_plan("epilogue", ("rest", "leave"), "examined_latch")
    upsert_scene(project, "Epilogue", "mystery", "shallow", "balanced", later)

    assert near_duplicate_flag_groups(project) == []


@patch("core.model_client.call_model")
def test_compile_result_has_required_nonempty_fields(model_call) -> None:
    """A successful compile must return all six structural VNForgeResult fields."""
    model_call.return_value = sample_plan()
    result = compile_scene(
        "Mia waits on the empty platform.",
        "romance",
        "shallow",
        project=new_project("Schema"),
    )

    assert isinstance(result, VNForgeResult)
    for field_name in REQUIRED_NONEMPTY_FIELDS:
        value = getattr(result, field_name)
        assert value is not None, field_name
        if field_name == "diagnostics":
            # Present as a list; an empty list means "no findings", which is valid.
            assert isinstance(value, list)
        else:
            assert value != "" and value != [], field_name

    # Full model surface is present even when some lists may be empty in other modes.
    for field_name in VNForgeResult.model_fields:
        assert hasattr(result, field_name)


@patch("core.model_client.call_model")
def test_recompile_preserves_existing_scene_id(model_call) -> None:
    """Model-generated identifier changes cannot break inbound project links."""
    previous = sample_plan("stable_scene")
    replacement = sample_plan("different_model_id")
    model_call.return_value = replacement

    result = compile_scene(
        "Same creator source",
        "mystery",
        "shallow",
        project=new_project("Stable IDs"),
        previous_plan=previous,
    )

    assert result.scene_id == "stable_scene"


def test_compile_empty_prose_raises_clean_value_error() -> None:
    """Empty creator input must fail with a handled ValueError, not a crash."""
    with pytest.raises(ValueError, match="Creator prose is empty"):
        compile_scene("", "romance", "shallow")
    with pytest.raises(ValueError, match="Creator prose is empty"):
        compile_scene("   \n\t  ", "romance", "shallow")


@patch("core.model_client._call_provider")
def test_empty_provider_response_raises_clean_value_error(provider_call) -> None:
    """Null/empty model bodies must become ValueError, never AttributeError."""
    provider_call.return_value = ""
    with pytest.raises(ValueError, match="empty or null response|invalid scene plan"):
        call_model("system", "user")

    provider_call.return_value = None
    with pytest.raises(ValueError, match="empty or null response|invalid scene plan"):
        call_model("system", "user")


@patch("core.model_client.call_model")
def test_compile_empty_provider_plan_does_not_attribute_error(model_call) -> None:
    """If the provider path yields an empty-response error, compile stays clean."""
    model_call.side_effect = ValueError(
        "Provider returned an empty or null response body (got 'NoneType')."
    )
    with pytest.raises(ValueError, match="empty or null response"):
        compile_scene("Some prose", "mystery", "shallow", project=new_project("Errors"))
