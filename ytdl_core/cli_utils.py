import re


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
