import base64
import binascii
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .settings import DOWNLOADS_DIR


def format_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def encode_file_id(relative_path: str) -> str:
    return base64.urlsafe_b64encode(relative_path.encode("utf-8")).decode("ascii").rstrip("=")


def decode_file_id(file_id: str) -> str:
    padding = "=" * (-len(file_id) % 4)
    try:
        return base64.urlsafe_b64decode((file_id + padding).encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("Invalid file id") from exc


def list_download_files(since: float | None = None, limit: int = 200) -> list[dict]:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    allowed_suffixes = {".mp4", ".mp3", ".webm", ".mkv", ".m4a", ".srt", ".txt"}
    files = []
    for path in DOWNLOADS_DIR.rglob("*"):
        if path.suffix.lower() not in allowed_suffixes:
            continue
        try:
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            continue

        if since is not None and stat.st_mtime < since:
            continue

        rel = path.relative_to(DOWNLOADS_DIR).as_posix()
        files.append({
            "id": encode_file_id(rel),
            "name": rel,
            "path": str(path),
            "size": format_size(stat.st_size),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "mtime": stat.st_mtime,
            "url": f"/files/{quote(rel)}",
        })
    files.sort(key=lambda item: item["mtime"], reverse=True)
    return files[:limit]


def prioritize_job_outputs(outputs: list[dict], download_type: str) -> list[dict]:
    preferred_suffixes = {
        "video": [".mp4", ".mkv", ".webm"],
        "audio": [".mp3", ".m4a", ".webm"],
        "srt": [".srt"],
        "txt": [".txt"],
    }.get(download_type, [])

    def score(item: dict) -> tuple[int, float]:
        suffix = Path(item["name"]).suffix.lower()
        rank = preferred_suffixes.index(suffix) if suffix in preferred_suffixes else len(preferred_suffixes) + 1
        return (rank, -float(item.get("mtime") or 0))

    return sorted(outputs, key=score)


def resolve_path_inside_downloads(raw_path: str) -> Path:
    if not raw_path:
        raise ValueError("File path is required")

    path = Path(raw_path)
    if not path.is_absolute():
        path = DOWNLOADS_DIR / path
    path = path.resolve()

    try:
        path.relative_to(DOWNLOADS_DIR)
    except ValueError:
        raise ValueError("Invalid file path")

    if not path.is_file():
        raise FileNotFoundError("File not found")
    return path


def resolve_download_file(payload: dict) -> Path:
    file_id = (payload.get("id") or "").strip()
    if file_id:
        return resolve_path_inside_downloads(decode_file_id(file_id))

    raw_path = (payload.get("path") or "").strip()
    if raw_path:
        return resolve_path_inside_downloads(raw_path)

    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("File id, path, or name is required")
    return resolve_path_inside_downloads(name)


def open_local_file(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return

    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(path)])


def bring_windows_explorer_to_front(folder: Path) -> None:
    if os.name != "nt":
        return

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    target_title = folder.name.lower()
    matches: list[int] = []
    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True

        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        if class_buffer.value not in {"CabinetWClass", "ExploreWClass"}:
            return True

        title_buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        if target_title and target_title in title_buffer.value.lower():
            matches.append(hwnd)
        return True

    user32.EnumWindows(enum_proc_type(enum_proc), 0)
    if not matches:
        return

    hwnd = matches[-1]
    shell32.SetCurrentProcessExplicitAppUserModelID("youtube-downloader")
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    user32.SetForegroundWindow(hwnd)


def open_local_file_location(path: Path) -> None:
    if os.name == "nt":
        import ctypes

        params = f'/select,"{path}"'
        result = ctypes.windll.shell32.ShellExecuteW(None, "open", "explorer.exe", params, None, 1)
        if result <= 32:
            raise RuntimeError(f"Explorer failed to open file location: error {result}")
        time.sleep(0.35)
        bring_windows_explorer_to_front(path.parent)
        return

    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
        return

    subprocess.Popen(["xdg-open", str(path.parent)])


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def copy_file_to_clipboard(path: Path) -> None:
    if os.name != "nt":
        raise RuntimeError("File clipboard copy is only available on Windows in this local app")

    command = f"Set-Clipboard -LiteralPath {powershell_quote(str(path))}"
    encoded = base64.b64encode(command.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Clipboard copy failed").strip())
