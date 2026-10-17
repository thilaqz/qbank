"""Configuration for the QBank application.

Every setting is read from the environment so that no credential is ever
committed to the repository. During development the values are loaded from a
local .env file; in production they are supplied by the systemd unit.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from a local .env file, if one exists.

    Written by hand rather than pulled in as a dependency, because the file
    format is trivial and one fewer package is one fewer thing to install on
    the server.
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


class Config:
    # --- Flask -------------------------------------------------------------
    SECRET_KEY = os.environ.get("QBANK_SECRET_KEY", "change-me-before-deploying")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set to True once the site is served over HTTPS.
    SESSION_COOKIE_SECURE = os.environ.get("QBANK_HTTPS", "false").lower() == "true"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # eight hours

    # --- Oracle ------------------------------------------------------------
    DB_USER = os.environ.get("QBANK_DB_USER", "qbank")
    DB_PASSWORD = os.environ.get("QBANK_DB_PASSWORD", "")
    DB_DSN = os.environ.get("QBANK_DB_DSN", "localhost:1521/XEPDB1")
    DB_POOL_MIN = int(os.environ.get("QBANK_DB_POOL_MIN", "1"))
    DB_POOL_MAX = int(os.environ.get("QBANK_DB_POOL_MAX", "4"))

    # --- Application -------------------------------------------------------
    RESULT_LIMIT = int(os.environ.get("QBANK_RESULT_LIMIT", "100"))
