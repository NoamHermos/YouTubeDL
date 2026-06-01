import yt_dlp
from yt_dlp.utils import DownloadError

abort_speed_mode = False


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


def speed_abort_hook(d):
    global abort_speed_mode
    if abort_speed_mode:
        raise DownloadError("ABORT_SPEED_MODE_TRIGGERED")


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


SPEED_OPTS = {
    "concurrent_fragment_downloads": 10,
    "http_chunk_size": 10485760,
    "skip_unavailable_fragments": False,
    "logger": SpeedLogger(),
    "progress_hooks": [speed_abort_hook],
}
