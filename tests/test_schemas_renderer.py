"""Tests for strict contracts and deterministic Ren'Py rendering."""

import unittest

from pydantic import ValidationError

from core.project import new_project, upsert_scene
from core.renderer import render_project, render_scene, safe_filename
from core.schemas import AssetCue, ScenePlan
from core.validation import validate_renpy_source, validate_scene
from tests.helpers import sample_plan


class SchemaRendererTests(unittest.TestCase):
    """Protect the safety boundary between models and executable scripts."""

    def test_schema_rejects_invalid_identifier_and_asset_type(self) -> None:
        with self.assertRaises(ValidationError):
            AssetCue(
                cue_type="video",
                name="../../escape",
                description="Invalid asset.",
            )

    def test_schema_rejects_unknown_fields(self) -> None:
        payload = sample_plan().model_dump()
        payload["renpy_script"] = "python: dangerous()"
        with self.assertRaises(ValidationError):
            ScenePlan.model_validate(payload)

    def test_schema_rejects_renpy_reserved_identifiers(self) -> None:
        payload = sample_plan().model_dump()
        payload["beats"][2]["speaker"] = "python"
        with self.assertRaises(ValidationError):
            ScenePlan.model_validate(payload)

    def test_renderer_escapes_text_and_uses_typed_assignments(self) -> None:
        script = render_scene(sample_plan())
        self.assertIn("default mia_stayed = False", script)
        self.assertIn("$ mia_stayed = True", script)
        self.assertIn("{{b}", script)
        self.assertIn("[[/name]", script)
        self.assertNotIn("python:", script)
        self.assertFalse(validate_renpy_source(script))

    def test_choice_depth_is_enforced(self) -> None:
        findings = validate_scene(sample_plan(), "deep")
        self.assertTrue(any(item.code == "choice_count" for item in findings))

    def test_project_renderer_namespaces_duplicate_routes(self) -> None:
        project = new_project("Routes")
        upsert_scene(
            project,
            "First",
            "romance",
            "shallow",
            "balanced",
            sample_plan("first", ("accept", "refuse")),
        )
        upsert_scene(
            project,
            "Second",
            "romance",
            "shallow",
            "balanced",
            sample_plan("second", ("accept", "refuse")),
        )
        script = render_project(project)
        self.assertIn("label first_accept:", script)
        self.assertIn("label second_accept:", script)
        self.assertFalse(validate_renpy_source(script))

    def test_safe_filename_removes_paths(self) -> None:
        self.assertEqual(safe_filename("../../Chapter 1/Arrival"), "chapter_1_arrival")


if __name__ == "__main__":
    unittest.main()
