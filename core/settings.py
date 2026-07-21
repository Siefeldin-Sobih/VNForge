"""Secure provider configuration with keyring-first secret storage."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import dotenv_values

SERVICE_NAME = "VNForge"
SECRET_FIELDS = {
    "watsonx": "WATSONX_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _keyring_module():
    """Return an operational keyring module, or ``None`` when unavailable."""
    try:
        import keyring

        try:
            keyring.get_password(SERVICE_NAME, "probe")
        except Exception:
            return None
        return keyring
    except (ImportError, RuntimeError):
        return None


def save_provider_settings(
    env_path: str,
    provider: str,
    values: dict[str, str],
) -> None:
    """Save public settings and put API secrets in the OS keyring when possible."""
    existing = dotenv_values(env_path) if Path(env_path).exists() else {}
    if existing.get("RENPY_EXECUTABLE") and "RENPY_EXECUTABLE" not in values:
        values["RENPY_EXECUTABLE"] = existing["RENPY_EXECUTABLE"] or ""
    secret_name = SECRET_FIELDS[provider]
    secret = values.pop(secret_name)
    keyring = _keyring_module()
    if keyring:
        try:
            keyring.set_password(SERVICE_NAME, secret_name, secret)
            values["SECRET_STORAGE"] = "keyring"
        except Exception:
            keyring = None
    if not keyring:
        values[secret_name] = secret
        values["SECRET_STORAGE"] = "env_fallback"
    values["PROVIDER"] = provider
    path = Path(env_path)
    lines = [
        f"{key}={json.dumps(value.replace(chr(10), '').replace(chr(13), ''))}"
        for key, value in values.items()
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_provider_settings(env_path: str) -> dict[str, str]:
    """Load public configuration and hydrate a keyring-backed API secret."""
    try:
        Path(env_path).chmod(0o600)
    except OSError:
        pass
    values = {key: value or "" for key, value in dotenv_values(env_path).items()}
    provider = values.get("PROVIDER", "")
    secret_name = SECRET_FIELDS.get(provider)
    if secret_name and values.get("SECRET_STORAGE") == "keyring":
        keyring = _keyring_module()
        try:
            secret = keyring.get_password(SERVICE_NAME, secret_name) if keyring else None
        except Exception:
            secret = None
        if secret:
            values[secret_name] = secret
    return values


def apply_provider_settings(env_path: str) -> dict[str, str]:
    """Load settings into the process environment for provider adapters."""
    values = load_provider_settings(env_path)
    for key, value in values.items():
        os.environ[key] = value
    return values
