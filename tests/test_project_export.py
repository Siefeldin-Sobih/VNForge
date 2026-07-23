"""Tests for persistence, continuity links, and playable exports."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.exporters import export_playable_project
from core.project import (
    ProjectHistory,
    load_project,
    new_project,
    save_project,
    upsert_scene,
)
from core.validation import analyze_project, run_renpy_lint, validate_renpy_source
from tests.helpers import sample_plan


class ProjectExportTests(unittest.TestCase):
    """Verify creator projects survive round trips and remain playable."""

    def test_save_load_and_asset_deduplication(self) -> None:
        project = new_project("Test Project")
        upsert_scene(
            project,
            "Source",
            "romance",
            "shallow",
            "balanced",
            sample_plan(),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = save_project(project, str(Path(directory) / "story"))
            loaded = load_project(path)
        self.assertTrue(path.endswith(".vnforge"))
        self.assertEqual(loaded.title, "Test Project")
        self.assertEqual(len(loaded.asset_registry), 2)
        self.assertEqual(loaded.asset_registry[0].used_in_scenes, ["arrival"])

    def test_continuation_links_predecessor_choice(self) -> None:
        project = new_project("Linked")
        first = sample_plan("first", ("follow", "wait"))
        second = sample_plan("second", ("ask", "leave"))
        upsert_scene(project, "One", "mystery", "shallow", "balanced", first)
        upsert_scene(
            project,
            "Two",
            "mystery",
            "shallow",
            "balanced",
            second,
            continues_from=("first", "follow"),
        )
        self.assertEqual(first.choices[0].target_scene_id, "second")
        self.assertFalse(
            [item for item in analyze_project(project) if item.code == "unresolved_branch"]
        )

    def test_history_undo_and_redo(self) -> None:
        history = ProjectHistory(new_project("Before"))
        history.checkpoint()
        history.project.title = "After"
        self.assertEqual(history.undo().title, "Before")
        self.assertEqual(history.redo().title, "After")

    def test_scene_regeneration_keeps_bounded_plan_history(self) -> None:
        project = new_project("History")
        original = sample_plan()
        upsert_scene(project, "One", "romance", "shallow", "balanced", original)
        changed = sample_plan()
        changed.scene_title = "Changed"
        upsert_scene(project, "Two", "romance", "shallow", "balanced", changed)
        self.assertEqual(len(project.scenes[0].plan_history), 1)
        self.assertEqual(project.scenes[0].plan_history[0].scene_title, original.scene_title)

    def test_playable_export_creates_script_and_placeholders(self) -> None:
        project = new_project("Playable/Test")
        upsert_scene(
            project,
            "Source",
            "romance",
            "shallow",
            "balanced",
            sample_plan(),
        )
        with tempfile.TemporaryDirectory() as directory:
            root, lint_ok, lint_output = export_playable_project(project, directory)
            root_path = Path(root)
            script = (root_path / "game" / "script.rpy").read_text(encoding="utf-8")
            self.assertTrue((root_path / "game" / "images" / "bg_station.svg").exists())
            self.assertTrue((root_path / "game" / "images" / "mia.svg").exists())
            options = (root_path / "game" / "options.rpy").read_text(encoding="utf-8")
            self.assertIn("define config.rollback_enabled = True", options)
            self.assertFalse(validate_renpy_source(script))
            self.assertFalse(lint_ok)
            self.assertIn("static validation passed", lint_output)

    @patch("core.validation.subprocess.run")
    def test_configured_renpy_lint_uses_error_code(self, run: MagicMock) -> None:
        run.return_value = MagicMock(returncode=0, stdout="Lint passed", stderr="")
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "renpy.sh"
            executable.touch()
            passed, output = run_renpy_lint(directory, str(executable))
        self.assertTrue(passed)
        self.assertIn("Lint passed", output)
        self.assertEqual(run.call_args.args[0][-1], "--error-code")


if __name__ == "__main__":
    unittest.main()
