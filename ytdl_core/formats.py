import re
from urllib.parse import parse_qs, urlparse


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
    ext = (fmt.get("ext") or "").lower()
    is_mp4 = 1 if ext == "mp4" else 0
    proto = (fmt.get("protocol") or "").lower()
    is_efficient = 0 if ("m3u8" in proto or "http_dash_segments" in proto) else 1
    tbr = fmt.get("tbr") or 0
    fps = fmt.get("fps") or 0
    return (is_mp4, is_efficient, tbr, fps)


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
