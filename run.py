# run.py
# Entry point for VNForge. Double-click this or run: python run.py
#
# Auto-installs dependencies on first run, then launches the app.
# If no credentials are configured, the setup window opens first.

import sys
import os
import subprocess


def _ensure_dependencies():
    """Install missing packages from requirements.txt if any are absent."""
    req_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
    try:
        import customtkinter  # noqa: F401
        import pydantic        # noqa: F401
        import dotenv          # noqa: F401
        import requests        # noqa: F401
    except ImportError:
        print("Installing dependencies…")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", req_path],
            stdout=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    _ensure_dependencies()
    from app import run
    run()
