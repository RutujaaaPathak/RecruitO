import os
from pathlib import Path
from dotenv import load_dotenv

# Absolute path to the .env file at the backend project root, so environment
# variables load correctly regardless of the current working directory.
BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"

# Frontend origins allowed to call the API. Defaults to the Vite dev server;
# override with a comma-separated CORS_ORIGINS value in .env for other
# environments.
DEFAULT_CORS_ORIGINS = ["http://localhost:5173"]


def load_env():
    """Load the backend .env file into the process environment.

    Anchored to the project root so it works no matter where uvicorn is
    started from (e.g. ``uvicorn app.main:app`` run from backend/ or from
    another directory). Existing environment variables take precedence and
    are never overridden.
    """
    load_dotenv(dotenv_path=ENV_FILE, override=False)


def cors_origins() -> list[str]:
    """Return the CORS allow-list parsed from the ``CORS_ORIGINS`` env var.

    The value is a comma-separated list of origins (whitespace-trimmed, empty
    entries dropped). When unset, falls back to the local Vite dev server origin
    so localhost development keeps working out of the box.
    """
    raw = os.getenv("CORS_ORIGINS")
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
