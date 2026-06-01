import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import yt_dlp

from .cli_utils import choose_index, choose_playlist_range
from .config import COOKIE_FILE, SCRIPT_DIR
from .downloader import process_video
from .formats import normalize_playlist_url, print_format_list, sanitize_filename


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
