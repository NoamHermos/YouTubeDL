import threading
import time

from .file_service import cleanup_empty_download_dirs
from .settings import CLEANUP_INTERVAL_HOURS, DOWNLOAD_RETENTION_DAYS, DOWNLOADS_DIR

_cleanup_started = False
_cleanup_lock = threading.Lock()


def remove_old_download_files(retention_days: int = DOWNLOAD_RETENTION_DAYS) -> int:
    if retention_days <= 0:
        return 0

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - (retention_days * 24 * 60 * 60)
    deleted_count = 0

    for path in DOWNLOADS_DIR.rglob("*"):
        try:
            if not path.is_file() or path.stat().st_mtime >= cutoff:
                continue
            path.relative_to(DOWNLOADS_DIR)
            path.unlink()
            deleted_count += 1
        except OSError:
            continue

    cleanup_empty_download_dirs()
    return deleted_count


def cleanup_loop() -> None:
    while True:
        try:
            deleted_count = remove_old_download_files()
            if deleted_count:
                print(
                    f"Cleanup: removed {deleted_count} download file(s) older than "
                    f"{DOWNLOAD_RETENTION_DAYS} days.",
                    flush=True,
                )
        except Exception as exc:
            print(f"Cleanup failed: {exc}", flush=True)

        time.sleep(CLEANUP_INTERVAL_HOURS * 60 * 60)


def start_cleanup_worker() -> None:
    global _cleanup_started
    with _cleanup_lock:
        if _cleanup_started or DOWNLOAD_RETENTION_DAYS <= 0:
            return
        _cleanup_started = True

    thread = threading.Thread(target=cleanup_loop, name="download-cleanup", daemon=True)
    thread.start()
