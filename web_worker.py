import argparse
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yt_dlp

import ytdl

MAX_PLAYLIST_RETRIES = 2


def parse_playlist_range(raw: str, total: int) -> tuple[int, int]:
    if total <= 0:
        return (1, 0)

    raw = (raw or "").strip()
    if not raw:
        return (1, total)

    parts = raw.replace(",", "-").split("-", 1)
    try:
        start = int(parts[0].strip())
        end = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else start
    except ValueError:
        raise ValueError("Range must look like 1-10 or 7")

    if start > end:
        start, end = end, start
    if start < 1 or end > total:
        raise ValueError(f"Range must be between 1 and {total}")
    return (start, end)


def fetch_info(url: str, is_playlist: bool, cookie_arg: str | None) -> dict:
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
        return ydl.extract_info(url, download=False)


def print_summary(title: str, stats: list[dict], subtitle_only: bool) -> None:
    if not stats:
        return

    print("\n" + "=" * 60)
    print(f"SUMMARY: {title}")
    print("=" * 60)
    print("{:<4} {:<40} {:<12} {:<10}".format("No.", "Title", "Status", "Size"))
    print("-" * 60)

    success_count = 0
    total_size = 0.0
    for stat in sorted(stats, key=lambda item: item["index"]):
        short_title = (stat["title"][:37] + "...") if len(stat["title"]) > 37 else stat["title"]
        size_str = f"{stat['size_mb']:.1f} MB" if stat["size_mb"] > 0 else "-"
        print("{:<4} {:<40} {:<12} {:<10}".format(stat["index"], short_title, stat["status"], size_str))
        if "Success" in stat["status"]:
            success_count += 1
            total_size += stat["size_mb"]

    print("-" * 60)
    item_label = "Items" if subtitle_only else "Videos"
    print(f"Total: {len(stats)} {item_label} | Success: {success_count} | Total Size: {total_size:.1f} MB")
    print("=" * 60)


def download_entries(
    indexed_entries: list[tuple[int, dict]],
    is_playlist: bool,
    cookie_arg: str | None,
    target_dir: Path,
    av_choice: str,
    preferred_format_id: str | None,
    want_subs: bool,
    workers: int,
) -> list[dict]:
    # Runs the (unchanged) per-video download function across the given entries.
    stats: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                ytdl.process_video,
                i,
                entry,
                is_playlist,
                cookie_arg,
                target_dir,
                av_choice,
                preferred_format_id,
                want_subs,
            )
            for i, entry in indexed_entries
        ]

        for future in as_completed(futures):
            stats.append(future.result())
    return stats


def is_missed(stat: dict) -> bool:
    # A "miss" is an item that failed to download (transient errors worth retrying).
    # "No subtitles" is a deterministic content issue, so it is not retried.
    return "Failed" in stat["status"]


def verify_and_retry_playlist(
    stats: list[dict],
    indexed_entries: list[tuple[int, dict]],
    is_playlist: bool,
    cookie_arg: str | None,
    target_dir: Path,
    av_choice: str,
    preferred_format_id: str | None,
    want_subs: bool,
    workers: int,
) -> list[dict]:
    # After a playlist run, verify everything downloaded and retry the misses.
    stats_by_index = {stat["index"]: stat for stat in stats}

    for attempt in range(1, MAX_PLAYLIST_RETRIES + 1):
        missed_indices = {idx for idx, stat in stats_by_index.items() if is_missed(stat)}
        if not missed_indices:
            break

        retry_targets = [
            (i, entry) for i, entry in indexed_entries if (i + 1) in missed_indices
        ]
        print(
            f"\n🔄 Verification: {len(retry_targets)} item(s) missed. "
            f"Retry attempt {attempt}/{MAX_PLAYLIST_RETRIES}...",
            flush=True,
        )

        retry_stats = download_entries(
            retry_targets,
            is_playlist,
            cookie_arg,
            target_dir,
            av_choice,
            preferred_format_id,
            want_subs,
            workers,
        )
        for stat in retry_stats:
            stats_by_index[stat["index"]] = stat

    final_stats = list(stats_by_index.values())
    still_missing = [stat for stat in final_stats if is_missed(stat)]
    if still_missing:
        print(
            f"\n⚠️ Verification complete: {len(still_missing)} item(s) still failed "
            f"after {MAX_PLAYLIST_RETRIES} retr{'y' if MAX_PLAYLIST_RETRIES == 1 else 'ies'}.",
            flush=True,
        )
    else:
        print("\n✅ Verification complete: all playlist items downloaded.", flush=True)
    return final_stats


def create_playlist_zip(target_dir: Path, downloads_dir: Path, title: str) -> Path | None:
    # Packages everything downloaded for the playlist into a single ZIP for download.
    media_files = [path for path in target_dir.rglob("*") if path.is_file()]
    if not media_files:
        print("\n📦 No files to package into a ZIP.", flush=True)
        return None

    zip_base = downloads_dir / title
    stale_zip = zip_base.with_suffix(".zip")
    if stale_zip.exists():
        try:
            stale_zip.unlink()
        except OSError:
            pass

    archive_path = Path(shutil.make_archive(str(zip_base), "zip", root_dir=str(target_dir)))
    size_mb = archive_path.stat().st_size / (1024 * 1024)
    print(
        f"\n📦 Packaged {len(media_files)} file(s) into: {archive_path.name} ({size_mb:.1f} MB)",
        flush=True,
    )
    return archive_path


def find_playlist_txt_file(target_dir: Path, index: int) -> Path | None:
    prefix = f"{index:02d} - "
    txt_files = [path for path in target_dir.glob(f"{prefix}*.txt") if path.is_file()]
    if not txt_files:
        return None
    return max(txt_files, key=lambda path: path.stat().st_mtime)


def create_combined_playlist_txt(target_dir: Path, title: str, indexed_entries: list[tuple[int, dict]]) -> Path | None:
    combined_path = target_dir / f"COMBINED - {title}.txt"
    blocks = []
    if combined_path.exists():
        try:
            combined_path.unlink()
        except OSError:
            pass

    for zero_based_index, entry in indexed_entries:
        index = zero_based_index + 1
        txt_path = find_playlist_txt_file(target_dir, index)
        if not txt_path:
            continue

        raw_title = (entry.get("title") or f"Video {index}").strip()
        try:
            text = txt_path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            text = txt_path.read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            print(f"   ⚠️ Could not read TXT for combined file: {txt_path.name} ({exc})", flush=True)
            continue

        if text:
            blocks.append(f"{index}. {raw_title}\n{'=' * 80}\n{text}")

    if not blocks:
        print("\n📄 No TXT files available for combined playlist transcript.", flush=True)
        return None

    combined_path.write_text("\n\n\n".join(blocks) + "\n", encoding="utf-8")
    size_kb = combined_path.stat().st_size / 1024
    print(f"\n📄 Created combined TXT transcript: {combined_path.name} ({size_kb:.1f} KB)", flush=True)
    return combined_path


def run_job(args: argparse.Namespace) -> int:
    cookie_file = Path(args.cookie_file)
    cookie_arg = str(cookie_file) if cookie_file.is_file() else None
    if cookie_arg:
        print(f"Using cookie file: {cookie_arg}", flush=True)
    else:
        print("No cookies.txt file found. Public videos should still work.", flush=True)

    url = args.url.strip()
    is_playlist = args.source == "playlist"
    if is_playlist:
        url = ytdl.normalize_playlist_url(url)

    print("Fetching video information...", flush=True)
    info = fetch_info(url, is_playlist, cookie_arg)

    downloads_dir = Path(args.downloads_dir)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    if is_playlist:
        title = ytdl.sanitize_filename(info.get("title", "Playlist"))
        target_dir = downloads_dir / title
        entries = list(info.get("entries") or [])
        print(f"Playlist: {title} ({len(entries)} videos)", flush=True)
    else:
        title = ytdl.sanitize_filename(info.get("title", "Video"))
        target_dir = downloads_dir
        entries = [info]
        print(f"Video: {title}", flush=True)

    target_dir.mkdir(parents=True, exist_ok=True)
    if not entries:
        print("No entries found.", flush=True)
        return 1

    start_idx = 1
    if is_playlist:
        start_idx, end = parse_playlist_range(args.range, len(entries))
        entries = entries[start_idx - 1:end]

    if args.download_type == "video":
        av_choice = "1"
        preferred_format_id = args.format_id or "best"
        want_subs = args.with_subtitles
    elif args.download_type == "audio":
        av_choice = "2"
        preferred_format_id = "bestaudio/best"
        want_subs = args.with_subtitles or args.audio_subtitles
    elif args.download_type == "srt":
        av_choice = "3"
        preferred_format_id = None
        want_subs = True
    else:
        av_choice = "4"
        preferred_format_id = None
        want_subs = True

    print(f"Output folder: {target_dir}", flush=True)
    if av_choice == "1":
        print(f"Selected video format: {preferred_format_id}", flush=True)
    print(f"Starting job with {args.workers} worker(s)...", flush=True)

    indexed_entries = list(enumerate(entries, start=start_idx - 1))
    stats = download_entries(
        indexed_entries,
        is_playlist,
        cookie_arg,
        target_dir,
        av_choice,
        preferred_format_id,
        want_subs,
        args.workers,
    )

    if is_playlist:
        stats = verify_and_retry_playlist(
            stats,
            indexed_entries,
            is_playlist,
            cookie_arg,
            target_dir,
            av_choice,
            preferred_format_id,
            want_subs,
            args.workers,
        )

    print_summary(title, stats, av_choice in ["3", "4"])

    if is_playlist:
        if av_choice == "4":
            create_combined_playlist_txt(target_dir, title, indexed_entries)
        create_playlist_zip(target_dir, downloads_dir, title)

    failures = [stat for stat in stats if "Failed" in stat["status"] or "No subtitles" in stat["status"]]
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a youtube-downloader web job.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--source", choices=["single", "playlist"], default="single")
    parser.add_argument("--download-type", choices=["video", "audio", "srt", "txt"], default="video")
    parser.add_argument("--range", default="")
    parser.add_argument("--downloads-dir", default="downloads")
    parser.add_argument("--cookie-file", default="cookies.txt")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--format-id", default="")
    parser.add_argument("--with-subtitles", action="store_true")
    parser.add_argument("--audio-subtitles", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.workers = max(1, min(args.workers, 16))

    try:
        return run_job(args)
    except KeyboardInterrupt:
        print("\nJob cancelled.", flush=True)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
