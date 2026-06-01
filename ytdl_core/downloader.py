import os
import time
from pathlib import Path

import yt_dlp

from .captions import get_best_subs_config, has_subtitles_enabled
from .formats import sanitize_filename
from .speed import run_download_with_fallback
from .subtitles import auto_fix_subtitles, cleanup_subtitles, write_txt_from_srt


class DownloadTracker:
    def __init__(self):
        self.total_bytes = 0
        self.last_progress_percent = -1
        self.last_progress_time = 0
        self.current_filename = None
        self.current_label = "file"

    def progress_bar(self, percent, width=24):
        filled = int(width * max(0, min(percent, 100)) / 100)
        return "■" * filled + "□" * (width - filled)

    def format_speed(self, bytes_per_second):
        if not bytes_per_second:
            return "N/A"

        units = ["B/s", "KB/s", "MB/s", "GB/s"]
        value = float(bytes_per_second)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024

    def shorten_name(self, filename, max_len=54):
        if not filename:
            return "file"
        name = os.path.basename(filename)
        return name if len(name) <= max_len else f"{name[:max_len - 3]}..."

    def label_for_download(self, d):
        filename = d.get("filename") or ""
        suffix = Path(filename).suffix.lower()
        info = d.get("info_dict") or {}
        vcodec = info.get("vcodec")
        acodec = info.get("acodec")

        if suffix in [".vtt", ".srt", ".srv3", ".ttml", ".json3"]:
            return "subtitles"
        if vcodec == "none" and acodec and acodec != "none":
            return "audio"
        if vcodec and vcodec != "none":
            return "video"
        return "file"

    def postprocessor_label(self, key):
        labels = {
            "FFmpegExtractAudio": "extracting MP3 audio",
            "FFmpegMerger": "merging audio and video",
            "FFmpegVideoConvertor": "converting video",
            "FFmpegSubtitlesConvertor": "converting subtitles to SRT",
            "MoveFiles": "moving final files",
        }
        return labels.get(key or "", key or "post-processing")

    def hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            speed = self.format_speed(d.get("speed"))
            filename = d.get("filename")
            if filename and filename != self.current_filename:
                self.current_filename = filename
                self.current_label = self.label_for_download(d)
                self.last_progress_percent = -1
                self.last_progress_time = 0
                print(f"\nDownloading {self.current_label}: {self.shorten_name(filename)}")

            if total:
                percent = downloaded / total * 100
                now = time.time()
                if percent < 100 and percent - self.last_progress_percent < 0.5 and now - self.last_progress_time < 0.2:
                    return
                self.last_progress_percent = percent
                self.last_progress_time = now
                print(f"\rProgress: [{self.progress_bar(percent)}] {percent:5.1f}% | {speed} ", end="", flush=True)
            else:
                downloaded_mb = downloaded / (1024 * 1024)
                print(f"\rProgress: [□□□□□□□□□□□□] {downloaded_mb:.1f} MB | {speed} ", end="", flush=True)
        elif d["status"] == "finished":
            self.total_bytes += d.get("total_bytes") or 0
            filename = d.get("filename") or self.current_filename
            print(f"\nFinished downloading {self.current_label}: {self.shorten_name(filename)}")
            print("Processing: preparing downloaded file...")

    def postprocessor_hook(self, d):
        key = d.get("postprocessor") or d.get("key")
        status = d.get("status")
        label = self.postprocessor_label(key)

        if status == "started":
            print(f"Processing: {label}...")
        elif status == "finished":
            print(f"Processing complete: {label}.")


def process_video(i, entry, is_playlist, cookie_arg, target_dir, av_choice, preferred_format_id, want_subs):
    # Worker function to process a single video download.
    # Encapsulates the logic previously found inside the main loop.
    vid_url = entry.get("webpage_url") or entry.get("url")
    vid_title = sanitize_filename(entry.get("title", f"Video {i}"))
    prefix = f"{i+1:02d} - " if is_playlist else ""
    base_clean_name = f"{prefix}{vid_title}" 
    filename_tmpl = f"{base_clean_name.replace('%', '%%')}.%(ext)s"
    subtitle_only = av_choice in ["3", "4"]

    outtmpl = str(target_dir / filename_tmpl)

    vid_stat = {
        "index": i + 1,
        "title": vid_title,
        "status": "Unknown",
        "size_mb": 0,
        "time_s": 0
    }

    # Skip existing files based on numbering
    if is_playlist:
        # Look for any media files starting with the current prefix
        if av_choice == "3":
            existing_suffixes = ['.srt']
        elif av_choice == "4":
            existing_suffixes = ['.txt']
        else:
            existing_suffixes = ['.mp4', '.mp3', '.webm', '.mkv', '.m4a']

        existing_media = [
            f for f in target_dir.glob(f"{prefix}*")
            if f.suffix.lower() in existing_suffixes
        ]
        if existing_media:
            print(f"\n⏭️ Skipping: {vid_title} (Found existing file: '{existing_media[0].name}')")
            vid_stat["status"] = "⏭️ Skipped"
            return vid_stat

    print(f"\n⬇️ Processing: {vid_title}")

    try:
        # 1. Fetch metadata specifically for THIS video
        # Added remote_components to solve YouTube JS challenges
        meta_opts = {
            "quiet": True, 
            "cookiefile": cookie_arg, 
            "extractor_args": {"youtube": {"player_client": ["default"]}},
            "remote_components": ["ejs:github"]
        }
        with yt_dlp.YoutubeDL(meta_opts) as ydl_meta:
            full_info = ydl_meta.extract_info(vid_url, download=False)
        
        # 2. Smart Quality Logic
        current_formats = [f['format_id'] for f in full_info.get('formats', [])] if not subtitle_only else []
        final_format_str = ""
        
        if subtitle_only:
            final_format_str = None
        elif av_choice == "2": 
            final_format_str = preferred_format_id if preferred_format_id in current_formats else "bestaudio/best"
        else: 
            # Check if Best Quality (Auto) is selected
            if preferred_format_id == "best":
                final_format_str = "bv*+ba/best"
            # Normal check for specific quality
            elif preferred_format_id in current_formats:
                final_format_str = f"{preferred_format_id}+bestaudio/best"
            else:
                print(f"   ⚠️ Preferred format {preferred_format_id} not available. Falling back to 'best'.")
                final_format_str = "bv*+ba/best"

        # 3. Smart Subtitle Logic
        subs_config = get_best_subs_config(full_info, want_subs)
        if subtitle_only and not has_subtitles_enabled(subs_config):
            vid_stat["status"] = "❌ No subtitles"
            return vid_stat
        
        tracker = DownloadTracker()
        start_time = time.time()

        postprocessors = []
        if av_choice == "2":
            postprocessors.append({"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"})
        
        if has_subtitles_enabled(subs_config):
            # Convert to SRT
            postprocessors.append({
                'key': 'FFmpegSubtitlesConvertor',
                'format': 'srt',
            })

        # Added remote_components to download options as well
        ydl_opts = {
            "outtmpl": outtmpl,
            "cookiefile": cookie_arg,
            "quiet": False,
            "noprogress": False,
            "noplaylist": True,
            "writethumbnail": False,
            "extractor_args": {"youtube": {"player_client": ["default"]}},
            "progress_hooks": [tracker.hook],
            "postprocessor_hooks": [tracker.postprocessor_hook],
            "postprocessors": postprocessors,
            "remote_components": ["ejs:github"],
            **subs_config
        }
        if subtitle_only:
            ydl_opts["skip_download"] = True
        else:
            ydl_opts.update({
                "format": final_format_str,
                "merge_output_format": "mp4",
            })
        
        run_download_with_fallback(ydl_opts, vid_url)
        
        # 4. FIX SUBTITLES AND CLEAN INTERMEDIATE FILES
        subtitle_output_path = None
        if has_subtitles_enabled(subs_config):
            srt_path = auto_fix_subtitles(target_dir, base_clean_name)
            if av_choice == "3" and srt_path:
                subtitle_output_path = srt_path
                print(f"   ✅ SRT subtitles saved: {srt_path.name}")
            elif av_choice == "4" and srt_path:
                txt_path = write_txt_from_srt(srt_path)
                if txt_path:
                    subtitle_output_path = txt_path
                    try:
                        os.remove(srt_path)
                    except Exception as e:
                        print(f"   ⚠️ Could not remove temporary SRT file: {e}")

        cleanup_subtitles(target_dir, base_clean_name)

        if subtitle_only and not subtitle_output_path:
            vid_stat["status"] = "❌ Failed"
            vid_stat["error"] = "Subtitle output was not created"
            return vid_stat

        end_time = time.time()
        duration = end_time - start_time
        if subtitle_output_path and subtitle_output_path.exists():
            total_mb = subtitle_output_path.stat().st_size / (1024 * 1024)
        else:
            total_mb = tracker.total_bytes / (1024 * 1024)
        vid_stat["status"] = "✅ Success"
        vid_stat["size_mb"] = total_mb
        vid_stat["time_s"] = duration
        
        if duration > 0 and total_mb > 0:
            speed = total_mb / duration
            print(f"📊 Stats: {total_mb:.2f} MB downloaded in {duration:.1f}s")
            print(f"🚀 Average Speed: {speed:.2f} MB/s")

    except Exception as e:
        print(f"❌ Failed: {e}")
        vid_stat["status"] = "❌ Failed"
        vid_stat["error"] = str(e)
    
    return vid_stat
