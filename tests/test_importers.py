"""Tests for safe prose and Ren'Py imports."""

import tempfile
import unittest
from pathlib import Path

from core.importers import import_document, parse_renpy
from core.renderer import render_scene
from core.validation import validate_renpy_source, validate_scene


class ImporterTests(unittest.TestCase):
    """Verify common statements import without carrying arbitrary Python code."""

    def test_text_document_loads_as_prose(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scene.md"
            path.write_text("A quiet room.", encoding="utf-8")
            source, plan = import_document(str(path))
        self.assertEqual(source, "A quiet room.")
        self.assertIsNone(plan)

    def test_renpy_import_parses_safe_statements_and_omits_python(self) -> None:
        source = """define mia = Character("Mia")
image bg_station = "images/station.png"
label scene_arrival:
    scene bg_station
    mia "We should go."
    python:
        dangerous()
    menu:
        "Stay":
            jump stay
        "Leave":
            jump leave
"""
        plan = parse_renpy(source, "arrival")
        rendered = render_scene(plan)
        self.assertEqual(plan.scene_id, "arrival")
        self.assertEqual(len(plan.choices), 2)
        self.assertTrue(any(beat.speaker == "mia" for beat in plan.beats))
        self.assertIn("intentionally omitted", plan.production_notes[-1])
        self.assertNotIn("dangerous", rendered)
        self.assertFalse(validate_scene(plan, "shallow"))
        self.assertFalse(validate_renpy_source(rendered))

    def test_linear_import_renders_return_without_menu(self) -> None:
        plan = parse_renpy('label intro:\n    "Hello."\n', "intro")
        rendered = render_scene(plan)
        self.assertFalse(plan.choices)
        self.assertNotIn("menu:", rendered)
        self.assertIn("    return", rendered)
        self.assertFalse(validate_scene(plan, "linear"))


if __name__ == "__main__":
    unittest.main()
