"""Tests for secure provider settings fallback behavior."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.settings import load_provider_settings, save_provider_settings


class SettingsTests(unittest.TestCase):
    """Ensure secrets remain retrievable when an OS keyring is unavailable."""

    @patch("core.settings._keyring_module", return_value=None)
    def test_owner_only_env_fallback_round_trip(self, _keyring) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            save_provider_settings(
                str(path),
                "gemini",
                {"GEMINI_API_KEY": 'secret"value', "GEMINI_MODEL": "flash"},
            )
            values = load_provider_settings(str(path))
            mode = path.stat().st_mode & 0o777
        self.assertEqual(values["GEMINI_API_KEY"], 'secret"value')
        self.assertEqual(values["SECRET_STORAGE"], "env_fallback")
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
