"""Tests for secure provider settings fallback behavior."""

import os
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
        # POSIX mode bits are not meaningful on Windows filesystems.
        if os.name != "nt":
            self.assertEqual(mode, 0o600)

    @patch("core.settings._keyring_module", return_value=None)
    def test_direct_provider_secrets_round_trip(self, _keyring) -> None:
        providers = (
            ("openai", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-test"),
            ("anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "claude-test"),
            ("opencode", "OPENCODE_API_KEY", "OPENCODE_MODEL", "deepseek-test"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for provider, secret_name, model_name, model in providers:
                with self.subTest(provider=provider):
                    path = Path(directory) / f"{provider}.env"
                    save_provider_settings(
                        str(path),
                        provider,
                        {secret_name: "secret", model_name: model},
                    )
                    values = load_provider_settings(str(path))
                    self.assertEqual(values[secret_name], "secret")
                    self.assertEqual(values[model_name], model)


if __name__ == "__main__":
    unittest.main()
