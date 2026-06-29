import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
WEB_WORKER = PROJECT_DIR / "web_worker.py"
DOWNLOADS_DIR = Path(os.environ.get("DOWNLOADS_DIR", PROJECT_DIR / "downloads")).resolve()
COOKIE_FILE = Path(os.environ.get("COOKIE_FILE", PROJECT_DIR / "cookies.txt")).resolve()
MAX_LOG_LINES = 1200


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


DOWNLOAD_RETENTION_DAYS = max(0, env_int("DOWNLOAD_RETENTION_DAYS", 10))
CLEANUP_INTERVAL_HOURS = max(1, env_int("CLEANUP_INTERVAL_HOURS", 24))
