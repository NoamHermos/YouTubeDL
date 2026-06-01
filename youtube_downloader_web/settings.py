import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
WEB_WORKER = PROJECT_DIR / "web_worker.py"
DOWNLOADS_DIR = Path(os.environ.get("DOWNLOADS_DIR", PROJECT_DIR / "downloads")).resolve()
COOKIE_FILE = Path(os.environ.get("COOKIE_FILE", PROJECT_DIR / "cookies.txt")).resolve()
MAX_LOG_LINES = 1200
