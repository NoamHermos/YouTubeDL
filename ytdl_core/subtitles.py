import glob
import html
import os
import re
import time
from datetime import timedelta
from pathlib import Path


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
