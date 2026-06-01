import yt_dlp

import ytdl

from .settings import COOKIE_FILE


def parse_range_start(raw: str, total: int) -> int:
    raw = (raw or "").strip()
    if not raw:
        return 1
    first_part = raw.replace(",", "-").split("-", 1)[0].strip()
    try:
        start = int(first_part)
    except ValueError:
        return 1
    return max(1, min(start, total))


def fetch_video_info_for_formats(url: str, source: str, range_text: str) -> dict:
    cookie_arg = str(COOKIE_FILE) if COOKIE_FILE.is_file() else None
    is_playlist = source == "playlist"
    lookup_url = ytdl.normalize_playlist_url(url) if is_playlist else url

    info_opts = {
        "quiet": True,
        "skip_download": True,
        "cookiefile": cookie_arg,
        "extractor_args": {"youtube": {"player_client": ["default"]}},
        "extract_flat": bool(is_playlist),
        "noplaylist": not is_playlist,
        "remote_components": ["ejs:github"],
    }

    with yt_dlp.YoutubeDL(info_opts) as ydl:
        info = ydl.extract_info(lookup_url, download=False)

    if not is_playlist:
        return info

    entries = list(info.get("entries") or [])
    if not entries:
        raise ValueError("No playlist entries found")

    first_index = parse_range_start(range_text, len(entries)) - 1
    first_entry = entries[first_index]
    first_url = first_entry.get("webpage_url") or first_entry.get("url")
    if not first_url:
        raise ValueError("Could not find first playlist video URL")

    first_opts = {
        "quiet": True,
        "cookiefile": cookie_arg,
        "extractor_args": {"youtube": {"player_client": ["default"]}},
        "remote_components": ["ejs:github"],
    }
    with yt_dlp.YoutubeDL(first_opts) as ydl:
        return ydl.extract_info(first_url, download=False)


def build_video_format_options(info: dict) -> list[dict]:
    clean_formats = ytdl.get_clean_format_list(info.get("formats") or [], for_audio=False)
    options = []
    for fmt in clean_formats:
        desc = ytdl.describe_format(fmt, for_audio=False)
        label_parts = [desc["quality"], desc["ext"], desc["format_id"]]
        if desc["size"] != "N/A":
            label_parts.append(f"{desc['size']} MB")
        if desc["note"]:
            label_parts.append(desc["note"])
        desc["label"] = " | ".join(str(part) for part in label_parts if part)
        options.append(desc)
    return options
