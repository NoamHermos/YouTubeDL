"""Import browser-exported transcripts without transferring browser credentials."""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .formats import sanitize_filename

MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")


def youtube_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    if hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"} and parsed.path == "/watch":
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
    elif hostname == "youtu.be":
        video_id = parsed.path.removeprefix("/")
    else:
        return None
    return video_id if VIDEO_ID_RE.fullmatch(video_id) else None


def default_cache_dir() -> Path:
    downloads = Path(os.environ.get("DOWNLOADS_DIR", Path(__file__).resolve().parent.parent / "downloads"))
    return downloads / ".transcript-cache"


def import_browser_transcript(input_path: Path, title: str, cache_dir: Path | None = None) -> Path:
    if input_path.stat().st_size > MAX_TRANSCRIPT_BYTES:
        raise ValueError("Transcript exceeds the 8 MB limit")
    lines = input_path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or lines[0] != "YouTube transcript":
        raise ValueError("Expected a YouTube browser transcript export")
    header, body = {}, []
    for line in lines[1:]:
        if re.match(r"^\[\d+:\d{2}(?::\d{2})?\]", line):
            body.append(re.sub(r"^\[\d+:\d{2}(?::\d{2})?\]\s*", "", line))
        elif not body and ": " in line:
            key, value = line.split(": ", 1)
            header[key] = value
        elif body and line.strip():
            body.append(line)
    video_id = header.get("Video ID", "")
    language = header.get("Language", "")
    text = " ".join(" ".join(body).split())
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("Missing or invalid video ID in transcript export")
    if not re.fullmatch(r"[A-Za-z0-9-]{2,35}", language):
        raise ValueError("Missing or invalid transcript language")
    if not text:
        raise ValueError("Transcript export contains no caption text")
    record = {
        "video_id": video_id,
        "title": sanitize_filename(title),
        "language": language,
        "source": "browser-export",
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "text": text + "\n",
    }
    destination_dir = cache_dir if cache_dir is not None else default_cache_dir()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{video_id}.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination)
    return destination


def write_cached_transcript(url: str, output_dir: Path, cache_dir: Path | None = None) -> Path | None:
    video_id = youtube_video_id(url)
    if not video_id:
        return None
    source_dir = cache_dir if cache_dir is not None else default_cache_dir()
    source = source_dir / f"{video_id}.json"
    if not source.is_file():
        return None
    try:
        if source.stat().st_size > MAX_TRANSCRIPT_BYTES:
            raise ValueError("Cached transcript exceeds the size limit")
        record = json.loads(source.read_text(encoding="utf-8"))
        language = record.get("language", "")
        if record.get("video_id") != video_id or record.get("source") != "browser-export":
            raise ValueError("Cached transcript source does not match this video")
        if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z0-9-]{2,35}", language):
            raise ValueError("Invalid cached transcript language")
        text = record.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Cached transcript is empty")
        title = sanitize_filename(record.get("title") or video_id)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(f"Ignoring unusable cached transcript: {error}", flush=True)
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{title}.{language}.txt"
    destination.write_text(text, encoding="utf-8")
    print(f"Using browser-exported transcript cached on NAS: {video_id} ({language})", flush=True)
    print(f"TXT transcript saved: {destination.name}", flush=True)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    print(import_browser_transcript(args.input, args.title, args.cache_dir))
