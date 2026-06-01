import yt_dlp
from yt_dlp.utils import DownloadError
from pathlib import Path
import re
import os
import time
import sys
import glob
import html
from urllib.parse import urlparse, parse_qs
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed # Added for parallel downloads

# --- CONFIGURATION ---
SCRIPT_DIR = Path(__file__).resolve().parent
COOKIE_FILE = SCRIPT_DIR / "cookies.txt"

# === GLOBAL ABORT FLAG ===
abort_speed_mode = False

# === LOGGER ===
class SpeedLogger:
    def debug(self, msg): self._check_fail(msg)
    def info(self, msg): 
        self._check_fail(msg)
        if not msg.startswith('[debug] '): print(msg)
    def warning(self, msg):
        self._check_fail(msg)
        print(f"⚠️ {msg}")
    def error(self, msg):
        print(f"❌ {msg}")
        self._check_fail(msg)

    def _check_fail(self, msg):
        global abort_speed_mode
        if "Skipping fragment" in msg or "fragment not found" in msg or "HTTP Error 403" in msg:
            if not abort_speed_mode:
                print(f"\n🚨 Detected issue in speed mode: '{msg}' - Triggering abort!")
            abort_speed_mode = True

# === PROGRESS HOOK ===
def speed_abort_hook(d):
    global abort_speed_mode
    if abort_speed_mode:
        raise DownloadError("ABORT_SPEED_MODE_TRIGGERED")

# === SPEED / FALLBACK MECHANISM ===
SPEED_OPTS = {
    "concurrent_fragment_downloads": 10,
    "http_chunk_size": 10485760,
    "skip_unavailable_fragments": False,
    "logger": SpeedLogger(),
    "progress_hooks": [speed_abort_hook]
}

# === SUBTITLE FIXER HELPERS (ADD THIS BLOCK) ===

def parse_srt_time(time_str):
    """Parses SRT timestamp into timedelta."""
    try:
        hours, minutes, rest = time_str.split(':')
        seconds, milliseconds = rest.split(',')
        return timedelta(hours=int(hours), minutes=int(minutes), seconds=int(seconds), milliseconds=int(milliseconds))
    except ValueError:
        return timedelta(0)

def format_srt_time(td):
    """Formats timedelta back to SRT timestamp."""
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    milliseconds = int(td.microseconds / 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"

def clean_subtitle_text_line(line: str) -> str:
    """Removes subtitle markup and speaker arrows from a text line."""
    line = html.unescape(line)
    line = re.sub(r"<[^>]+>", "", line)
    line = re.sub(r"^\s*(?:(?:>>|<<)\s*)+", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line

def fix_rolling_logic(content):
    """
    Core logic to fix rolling/overlapping subtitles.
    Returns the fixed SRT content string.
    """
    # Normalize newlines
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    raw_blocks = content.strip().split('\n\n')
    
    parsed_items = []
    
    # Parse blocks
    for block in raw_blocks:
        lines = block.split('\n')
        if len(lines) < 3: continue
        try:
            times = lines[1].split(' --> ')
            if len(times) != 2: continue
            
            start = parse_srt_time(times[0].strip())
            end = parse_srt_time(times[1].strip())
            text_lines = [clean_subtitle_text_line(l) for l in lines[2:] if l.strip()]
            text_lines = [line for line in text_lines if line]
            
            parsed_items.append({'start': start, 'end': end, 'lines': text_lines})
        except:
            continue

    # Filter unique lines (de-duplicate rolling effect)
    unique_lines = []
    last_text = None
    for item in parsed_items:
        for line in item['lines']:
            if line != last_text:
                unique_lines.append({'text': line, 'start': item['start'], 'end': item['end']})
                last_text = line
    
    # Re-group into pairs (static blocks)
    output_blocks = []
    for i in range(0, len(unique_lines), 2):
        line1 = unique_lines[i]
        
        if i + 1 < len(unique_lines):
            line2 = unique_lines[i+1]
            text = f"{line1['text']}\n{line2['text']}"
            start_time = line1['start']
            
            # Determine end time based on the next block to avoid gaps
            if i + 2 < len(unique_lines):
                end_time = unique_lines[i+2]['start']
            else:
                end_time = line2['end']
        else:
            # Orphan line
            text = line1['text']
            start_time = line1['start']
            end_time = line1['end']
        
        # Sanity check for duration
        if end_time <= start_time:
            end_time = start_time + timedelta(seconds=2)
            
        output_blocks.append({'start': start_time, 'end': end_time, 'text': text})

    # Generate new SRT string
    output_str = []
    for idx, block in enumerate(output_blocks, 1):
        output_str.append(str(idx))
        output_str.append(f"{format_srt_time(block['start'])} --> {format_srt_time(block['end'])}")
        output_str.append(block['text'])
        output_str.append("")
    
    return '\n'.join(output_str)

def normalize_subtitle_name(name: str) -> str:
    """Normalizes filenames for matching yt-dlp's Windows-safe character replacements."""
    return re.sub(r"\W+", "", name, flags=re.UNICODE).lower()

def vtt_timestamp_to_srt(timestamp: str) -> str:
    timestamp = timestamp.split()[0].replace(".", ",")
    if timestamp.count(":") == 1:
        timestamp = f"00:{timestamp}"
    return timestamp

def convert_vtt_to_srt(vtt_path: Path):
    """Converts a downloaded WebVTT subtitle file to SRT without requiring ffmpeg."""
    try:
        with open(vtt_path, 'r', encoding='utf-8-sig') as f:
            content = f.read()

        content = content.replace('\r\n', '\n').replace('\r', '\n')
        blocks = []
        current = []

        for raw_line in content.split('\n'):
            line = raw_line.strip()
            if not line:
                if current:
                    blocks.append(current)
                    current = []
                continue
            if line == "WEBVTT" or line.startswith(("Kind:", "Language:", "STYLE", "REGION", "NOTE")):
                continue
            current.append(line)

        if current:
            blocks.append(current)

        output = []
        cue_index = 1
        for block in blocks:
            time_line_index = next((idx for idx, line in enumerate(block) if " --> " in line), None)
            if time_line_index is None:
                continue

            start_raw, end_raw = block[time_line_index].split(" --> ", 1)
            text_lines = block[time_line_index + 1:]
            if not text_lines:
                continue

            output.append(str(cue_index))
            output.append(f"{vtt_timestamp_to_srt(start_raw)} --> {vtt_timestamp_to_srt(end_raw)}")
            output.extend(text_lines)
            output.append("")
            cue_index += 1

        if not output:
            print(f"   ⚠️ Could not parse VTT subtitles: {vtt_path.name}")
            return None

        srt_path = vtt_path.with_suffix(".srt")
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(output))

        print(f"   ✅ Converted VTT to SRT: {srt_path.name}")
        try:
            os.remove(vtt_path)
        except Exception:
            pass
        return srt_path
    except Exception as e:
        print(f"   ⚠️ Failed to convert VTT to SRT: {e}")
        return None

def find_subtitle_file(directory: Path, base_filename: str):
    """
    Finds the subtitle file associated with the video.
    Includes debug prints to help diagnose issues.
    """
    subtitle_suffixes = (".srt", ".vtt")
    base_lookup = normalize_subtitle_name(base_filename)

    # 1. Try exact match pattern first
    pattern = str(directory / f"{base_filename}*")
    print(f"   🔍 Looking for subtitles with pattern: {os.path.basename(pattern)}")

    found_files = [
        f for f in glob.glob(pattern)
        if Path(f).suffix.lower() in subtitle_suffixes
    ]

    # 2. If not found, try a fuzzy search (matching just the start of the filename)
    if not found_files:
        # Try matching just the first 15 characters of the filename to avoid issues with special chars
        short_name = base_filename[:15]
        fuzzy_pattern = str(directory / f"{short_name}*")
        print(f"   ⚠️ Exact match failed. Trying fuzzy search: {os.path.basename(fuzzy_pattern)}")
        found_files = [
            f for f in glob.glob(fuzzy_pattern)
            if Path(f).suffix.lower() in subtitle_suffixes
        ]

        # Filter to ensure it's likely the right file (created in the last 5 minutes)
        if found_files:
            found_files = [f for f in found_files if (time.time() - os.path.getmtime(f)) < 300]

    # 3. yt-dlp may replace forbidden Windows chars with fullwidth variants. Match normalized names.
    if not found_files:
        all_subtitles = [
            f for f in glob.glob(str(directory / "*"))
            if Path(f).suffix.lower() in subtitle_suffixes
        ]
        found_files = [
            f for f in all_subtitles
            if base_lookup and base_lookup in normalize_subtitle_name(Path(f).stem)
        ]
        if found_files:
            print("   ✅ Found subtitles by normalized filename match.")

    # 4. Last fallback: use a very recent subtitle file from this folder.
    if not found_files:
        found_files = [
            f for f in glob.glob(str(directory / "*"))
            if Path(f).suffix.lower() in subtitle_suffixes
            and (time.time() - os.path.getmtime(f)) < 300
        ]
        if found_files:
            print("   ✅ Found recent subtitle file fallback.")

    if not found_files:
        print("   ❌ No subtitle file found. Please check if the .srt file exists in the folder.")
        # Debug: List all SRT files in directory to show the user what exists
        all_subs = [
            f for f in glob.glob(str(directory / "*"))
            if Path(f).suffix.lower() in subtitle_suffixes
        ]
        if all_subs:
            print(f"   📂 Existing subtitle files in folder: {[os.path.basename(f) for f in all_subs]}")
        return None

    # Take the most likely file (usually the first one or the most recently modified)
    subtitle_path = Path(max(found_files, key=os.path.getmtime))
    if subtitle_path.suffix.lower() == ".vtt":
        return convert_vtt_to_srt(subtitle_path)
    return subtitle_path

def auto_fix_subtitles(directory: Path, base_filename: str):
    """
    Finds the SRT file associated with the video and applies the rolling fix.
    Returns the fixed SRT path when successful.
    """
    srt_path = find_subtitle_file(directory, base_filename)
    if not srt_path:
        return None

    print(f"   🔧 Fixing rolling subtitles for: {os.path.basename(srt_path)}...")

    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        fixed_content = fix_rolling_logic(content)

        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)

        print("   ✅ Subtitles fixed successfully.")
        return srt_path
    except Exception as e:
        print(f"   ⚠️ Failed to fix subtitles: {e}")
        return None

def srt_to_plain_text(content: str) -> str:
    """Converts fixed SRT content into one continuous text paragraph."""
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    text_lines = []
    last_line = None
    timestamp_re = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}")

    for block in content.strip().split('\n\n'):
        block_lines = [line.strip() for line in block.split('\n') if line.strip()]
        if block_lines and block_lines[0].isdigit():
            block_lines = block_lines[1:]
        if block_lines and timestamp_re.match(block_lines[0]):
            block_lines = block_lines[1:]

        for line in block_lines:
            if not line:
                continue

            line = clean_subtitle_text_line(line)
            if line and line != last_line:
                text_lines.append(line)
                last_line = line

    plain_text = " ".join(text_lines)
    plain_text = re.sub(r"\s+", " ", plain_text).strip()
    return f"{plain_text}\n" if plain_text else ""

def write_txt_from_srt(srt_path: Path):
    """Writes a continuous TXT subtitle file from a fixed SRT file."""
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        txt_path = srt_path.with_suffix(".txt")
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(srt_to_plain_text(content))

        print(f"   ✅ TXT subtitles saved: {txt_path.name}")
        return txt_path
    except Exception as e:
        print(f"   ⚠️ Failed to create TXT subtitles: {e}")
        return None

def run_download_with_fallback(ydl_opts: dict, url: str):
    global abort_speed_mode
    
    # 1. Fast Mode
    abort_speed_mode = False
    fast_opts = ydl_opts.copy()
    fast_opts.update(SPEED_OPTS)
    
    existing_hooks = ydl_opts.get("progress_hooks", [])
    fast_opts["progress_hooks"] = existing_hooks + [speed_abort_hook]
    
    print(f"🚀 Speed Download: Starting concurrent download...")
    
    try:
        with yt_dlp.YoutubeDL(fast_opts) as ydl:
            ydl.download([url])
        return
    except Exception as e:
        err_str = str(e)
        if "ABORT_SPEED_MODE_TRIGGERED" in err_str or abort_speed_mode:
            print(f"\n🛑 Speed mode aborted safely (Missing fragments/403 detected).")
        else:
            print(f"\n⚠️ Speed Download Failed: {e}")
        print("🐢 Fallback: Switching to standard download mode immediately...\n")

    # 2. Standard Mode
    standard_opts = ydl_opts.copy()
    if "logger" in standard_opts: del standard_opts["logger"]
    standard_opts["progress_hooks"] = existing_hooks
    
    standard_opts.update({
        "retries": 10,
        "fragment_retries": 10,
        "skip_unavailable_fragments": False,
    })
        
    with yt_dlp.YoutubeDL(standard_opts) as ydl:
        ydl.download([url])

# === HELPER FUNCTIONS ===

def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = " ".join(name.split())
    name = name[:230].rstrip(" .")
    return name or "download"

def normalize_playlist_url(url: str) -> str:
    p = urlparse(url)
    q = parse_qs(p.query)
    if "list" in q and q["list"]:
        return f"https://www.youtube.com/playlist?list={q['list'][0]}"
    return url

def sizeof_mb(size_bytes):
    if size_bytes is None: return None
    return size_bytes / (1024 * 1024)

def format_score(fmt) -> tuple:
    proto = (fmt.get("protocol") or "").lower()
    is_efficient = 0 if ("m3u8" in proto or "http_dash_segments" in proto) else 1
    tbr = fmt.get("tbr") or 0
    fps = fmt.get("fps") or 0
    return (is_efficient, tbr, fps)

def cleanup_subtitles(directory: Path, base_filename: str):
    patterns = [
        f"{base_filename}*.vtt",
        f"{base_filename}*.json3",
        f"{base_filename}*.ttml",
        f"{base_filename}*.srv3",
        f"{base_filename}*.orig.*"
    ]
    for pat in patterns:
        for f in glob.glob(str(directory / pat)):
            try: os.remove(f)
            except: pass

def is_hebrew_lang(lang: str) -> bool:
    return lang.startswith("he") or lang == "iw"

def is_english_lang(lang: str) -> bool:
    return lang.startswith("en")

def is_translated_caption_format(fmt: dict) -> bool:
    url = fmt.get("url") or ""
    if url:
        query = parse_qs(urlparse(url).query)
        if "tlang" in query:
            return True

    text_fields = " ".join(str(fmt.get(key, "")) for key in ("name", "format", "format_note"))
    return "auto-translated" in text_fields.lower()

def has_original_caption_format(formats: list) -> bool:
    if not formats:
        return False
    return any(not is_translated_caption_format(fmt) for fmt in formats)

def choose_lang_from_map(caption_map: dict, predicate, original_only: bool = False):
    for lang in sorted(caption_map.keys()):
        if predicate(lang) and (not original_only or has_original_caption_format(caption_map.get(lang) or [])):
            return lang
    return None

def build_subs_config(selected_lang: str | None, source: str | None) -> dict:
    if not selected_lang or not source:
        return {"writesubtitles": False, "writeautomaticsub": False}

    return {
        "writesubtitles": source == "manual",
        "writeautomaticsub": source == "auto",
        "subtitleslangs": [selected_lang],
        "subtitlesformat": "best",
    }

def has_subtitles_enabled(subs_config: dict) -> bool:
    return bool(subs_config.get("writesubtitles") or subs_config.get("writeautomaticsub"))

def get_best_subs_config(info: dict, want_subs: bool = True) -> dict:
    if not want_subs:
        return {"writesubtitles": False, "writeautomaticsub": False}

    subs = info.get("subtitles") or {}
    auto_subs = info.get("automatic_captions") or {}
    original_auto_subs = {
        lang: formats
        for lang, formats in auto_subs.items()
        if has_original_caption_format(formats or [])
    }
    translated_auto_langs = set(auto_subs.keys()) - set(original_auto_subs.keys())
    
    if not subs and not original_auto_subs:
        print("   (No subtitles found)")
        return {"writesubtitles": False, "writeautomaticsub": False}

    selected_lang = None
    selected_source = None
    
    # 1. Prefer real Hebrew subtitles over auto-translated Hebrew.
    selected_lang = choose_lang_from_map(subs, is_hebrew_lang)
    if selected_lang:
        selected_source = "manual"
        print(f"   (Found manual Hebrew subtitles: {selected_lang})")

    if not selected_lang:
        selected_lang = choose_lang_from_map(original_auto_subs, is_hebrew_lang, original_only=True)
        if selected_lang:
            selected_source = "auto"
            print(f"   (Found original Hebrew automatic subtitles: {selected_lang})")

    # 2. Then prefer English, because many videos expose fake translated iw entries.
    if not selected_lang:
        selected_lang = choose_lang_from_map(subs, is_english_lang)
        if selected_lang:
            selected_source = "manual"
            print(f"   (Found manual English subtitles: {selected_lang})")

    if not selected_lang:
        selected_lang = choose_lang_from_map(original_auto_subs, is_english_lang, original_only=True)
        if selected_lang:
            selected_source = "auto"
            print(f"   (Found original English automatic subtitles: {selected_lang})")
    
    # 3. Other real/manual or original automatic captions.
    if not selected_lang:
        selected_lang = sorted(subs.keys())[0] if subs else None
        if selected_lang:
            selected_source = "manual"
            print(f"   (Fallback manual subtitle language: {selected_lang})")

    if not selected_lang and original_auto_subs:
        selected_lang = sorted(original_auto_subs.keys())[0]
        selected_source = "auto"
        print(f"   (Fallback original automatic subtitle language: {selected_lang})")

    if not selected_lang:
        if translated_auto_langs:
            print(f"   (Only auto-translated subtitles found; skipping: {', '.join(sorted(translated_auto_langs)[:5])})")
        return {"writesubtitles": False, "writeautomaticsub": False}
    
    return build_subs_config(selected_lang, selected_source)


def get_clean_format_list(formats, for_audio=False):
    clean_list = []

    if for_audio:
        candidates = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none"]
        candidates.sort(key=lambda x: x.get("abr") or 0, reverse=True)
        seen_abr = set()
        for f in candidates:
            abr = int(f.get("abr") or 0)
            if abr not in seen_abr:
                clean_list.append(f)
                seen_abr.add(abr)
                
        # === Add Best Quality option at the top of the list ===
        best_opt = {
            "format_id": "bestaudio/best",
            "ext": "mp3",
            "format_note": "Best Available Audio",
            "abr": 99999, # High number to make it clear it is the best
            "filesize": None
        }
        clean_list.insert(0, best_opt)
    else:
        # Video Logic
        groups = {}
        for f in formats:
            if f.get("vcodec") == "none": continue
            height = f.get("height")
            if not height: continue
            note = f"{height}p"
            fps = f.get("fps")
            if fps and fps > 30: note += f" {int(fps)}fps"
            groups.setdefault(note, []).append(f)
        best_candidates = []
        for note, flist in groups.items():
            best_fmt = max(flist, key=format_score)
            best_candidates.append(best_fmt)
        clean_list = sorted(best_candidates, key=lambda x: x.get("height") or 0, reverse=True)

        # === Add Best Quality option at the top of the list ===
        best_opt = {
            "format_id": "best",
            "ext": "mp4",
            "format_note": "Best Available",
            "height": 99999, # High number to make it clear it is the best
            "filesize": None
        }
        clean_list.insert(0, best_opt)

    return clean_list

def describe_format(fmt, for_audio=False):
    fmt_id = fmt.get("format_id", "")
    ext = fmt.get("ext", "")

    if fmt_id in ["best", "bestaudio/best"]:
        quality = "Auto/Max"
        note = "Best Quality for each video"
    else:
        note = fmt.get("format_note") or ""

        if for_audio:
            abr = fmt.get("abr")
            quality = f"{abr}k" if abr else "audio"
        else:
            height = fmt.get("height")
            fps = fmt.get("fps")
            quality = f"{height}p" if height else "video"
            if fps:
                quality += f"{int(fps)}fps"

    filesize = fmt.get("filesize") or fmt.get("filesize_approx")
    size_mb = sizeof_mb(filesize)
    size_str = f"{size_mb:.1f}" if size_mb is not None else "N/A"

    return {
        "format_id": fmt_id,
        "ext": ext,
        "quality": quality,
        "note": note,
        "size_mb": size_mb,
        "size": size_str,
    }

def print_format_list(formats, for_audio=False):
    print("\nAvailable formats (Cleaned & Grouped):\n")
    print("{:<4} {:<15} {:<6} {:<12} {:<20} {:>10}".format("No.", "Format ID", "Ext", "Quality", "Note", "Size (MB)"))
    print("-" * 75)
    clean_list = get_clean_format_list(formats, for_audio=for_audio)

    formats.clear()
    formats.extend(clean_list)

    for idx, f in enumerate(formats):
        desc = describe_format(f, for_audio=for_audio)
        print("{:<4} {:<15} {:<6} {:<12} {:<20} {:>10}".format(
            idx,
            desc["format_id"],
            desc["ext"],
            desc["quality"],
            desc["note"][:20],
            desc["size"],
        ))
    print()

def choose_index(max_index):
    while True:
        choice = input(f"Enter format number (0-{max_index}): ").strip()
        if not choice.isdigit():
            print("Please enter a valid number.")
            continue
        choice_int = int(choice)
        if 0 <= choice_int <= max_index:
            return choice_int
        print("Number out of range.")

def choose_playlist_range(total_videos: int):
    if total_videos <= 1: return (1, total_videos)
    while True:
        raw = input(f"Playlist has {total_videos} videos. Choose range (e.g. 1-10) or press Enter for all: ").strip()
        if raw == "": return (1, total_videos)
        m = re.match(r"^\s*(\d+)\s*(?:[-,\s]+\s*(\d+)\s*)?$", raw)
        if not m:
            print("Invalid range.")
            continue
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if start > end: start, end = end, start
        if start < 1 or end > total_videos:
            print("Range out of bounds.")
            continue
        return (start, end)

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

# === MAIN LOGIC ===
def main():
    # Check for cookies only once when the script starts
    if COOKIE_FILE.exists():
        print(f"✅ Found cookie file at: {COOKIE_FILE}")
        cookie_arg = str(COOKIE_FILE)
    else:
        print(f"⚠️ Warning: 'cookies.txt' not found.")
        cookie_arg = None

    # Main application loop
    while True:
        print("\n" + "="*40)
        print("🎬 MAIN MENU")
        print("="*40)
        print("Download mode:")
        print("  1) Single video")
        print("  2) Playlist")
        print("  0) Exit")
        mode_choice = input("Your choice (0/1/2): ").strip()
        
        # Option to exit the script gracefully
        if mode_choice == "0":
            print("\nExiting script. Goodbye!")
            break
            
        if mode_choice not in ["1", "2"]:
            print("Invalid choice. Please try again.")
            continue

        is_playlist = (mode_choice == "2")

        url = input("Enter URL: ").strip()
        if not url: 
            input("\nNo URL provided. Press Enter to return to the main menu...")
            continue

        if is_playlist:
            url = normalize_playlist_url(url)

        print("Fetching video information...")
        
        # Added remote_components to solve YouTube JS challenges
        info_opts = {
            "quiet": True,
            "skip_download": True,
            "cookiefile": cookie_arg,
            "extractor_args": {"youtube": {"player_client": ["default"]}},
            "extract_flat": True if is_playlist else False,
            "noplaylist": False if is_playlist else True,
            "remote_components": ["ejs:github"]
        }

        with yt_dlp.YoutubeDL(info_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
            except Exception as e:
                print(f"❌ Error: {e}")
                input("\nPress Enter to return to the main menu...")
                continue

        # Set the custom base directory for all downloads
        base_download_dir = SCRIPT_DIR / "downloads"

        if is_playlist:
            title = sanitize_filename(info.get("title", "Playlist"))
            # Save playlist in a subfolder inside the custom directory
            target_dir = base_download_dir / title
            entries = info.get("entries", [])
            print(f"Playlist: {title} ({len(entries)} videos)")
        else:
            title = sanitize_filename(info.get("title", "Video"))
            # Save single video directly in the custom directory
            target_dir = base_download_dir
            entries = [info]
            print(f"Video: {title}")

        # Create the directory and any missing parent directories safely
        target_dir.mkdir(parents=True, exist_ok=True)

        print("\nChoose download type:")
        print("  1) MP4 video")
        print("  2) MP3 audio")
        print("  3) SRT subtitles")
        print("  4) TXT subtitles")
        av_choice = input("Your choice (1/2/3/4): ").strip()
        if av_choice not in ["1", "2", "3", "4"]:
            print("Invalid choice. Please try again.")
            input("\nPress Enter to return to the main menu...")
            continue
        
        want_subs = True
        if av_choice == "2":
            subs_ans = input("Do you want to download subtitles too? (y/n): ").strip().lower()
            if subs_ans == 'n':
                want_subs = False

        # Keep track of the starting index for correct numbering
        start_idx = 1
        if is_playlist:
            start_idx, end = choose_playlist_range(len(entries))
            entries = entries[start_idx-1:end]
        
        # User Preference Setup
        preferred_format_id = None

        if av_choice in ["1", "2"]:
            first_entry = entries[0]
            if is_playlist:
                print("Fetching formats from the first video to set quality for all...")
                first_url = first_entry.get("url")
                # Added remote_components here as well
                first_entry_opts = {
                    "quiet": True, 
                    "cookiefile": cookie_arg, 
                    "extractor_args": {"youtube": {"player_client": ["default"]}},
                    "remote_components": ["ejs:github"]
                }
                with yt_dlp.YoutubeDL(first_entry_opts) as ydl:
                     first_entry = ydl.extract_info(first_url, download=False)

            formats = first_entry.get("formats", [])
            
            if av_choice == "2": # Audio
                print_format_list(formats, for_audio=True)
                if formats:
                    idx = choose_index(len(formats) - 1)
                    preferred_format_id = formats[idx]['format_id']
                else:
                    preferred_format_id = "bestaudio/best"
            else: # Video
                print_format_list(formats, for_audio=False)
                if not formats:
                    preferred_format_id = "best" # Fallback if list empty
                else:
                    idx = choose_index(len(formats) - 1)
                    chosen = formats[idx]
                    preferred_format_id = chosen['format_id']
                    print(f"Selected Preferred Format ID: {preferred_format_id}")
        else:
            print("Subtitle-only mode selected. Skipping media format selection.")

        playlist_stats = []

        # Parallel Download Loop
        print(f"\n🚀 Starting parallel download (4 workers)...")
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            # Submit all tasks to the pool
            futures = []
            for i, entry in enumerate(entries, start=start_idx-1):
                futures.append(
                    executor.submit(
                        process_video, 
                        i, entry, is_playlist, cookie_arg, target_dir, av_choice, preferred_format_id, want_subs
                    )
                )
            
            # Collect results as they complete
            for future in as_completed(futures):
                try:
                    stats = future.result()
                    playlist_stats.append(stats)
                except Exception as e:
                    print(f"❌ Unexpected thread error: {e}")

        # Sort stats by index so the summary is in order
        playlist_stats.sort(key=lambda x: x["index"])

        if is_playlist and playlist_stats:
            print("\n" + "="*60)
            print(f"📑 PLAYLIST SUMMARY: {title}")
            print("="*60)
            print("{:<4} {:<40} {:<12} {:<10}".format("No.", "Title", "Status", "Size"))
            print("-" * 60)
            
            success_count = 0
            total_size = 0
            
            for stat in playlist_stats:
                short_title = (stat["title"][:37] + "...") if len(stat["title"]) > 37 else stat["title"]
                size_str = f"{stat['size_mb']:.1f} MB" if stat["size_mb"] > 0 else "-"
                print("{:<4} {:<40} {:<12} {:<10}".format(stat["index"], short_title, stat["status"], size_str))
                if "Success" in stat["status"]:
                    success_count += 1
                    total_size += stat["size_mb"]
                    
            print("-" * 60)
            item_label = "Items" if av_choice in ["3", "4"] else "Videos"
            print(f"Total: {len(playlist_stats)} {item_label} | Success: {success_count} | Total Size: {total_size:.1f} MB")
            print("="*60 + "\n")

        elif not is_playlist:
            print("\n✅ Done!")
            try:
                os.startfile(target_dir)
            except:
                print(f"Saved to: {target_dir}")

        # Pause before clearing the screen or printing the menu again
        input("\nPress Enter to return to the main menu...")

if __name__ == "__main__":
    main()
