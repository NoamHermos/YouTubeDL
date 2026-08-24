import yt_dlp
from yt_dlp.utils import DownloadError


class SpeedAbortState:
    def __init__(self):
        self.aborted = False

    def check_fail(self, msg):
        if "Skipping fragment" in msg or "fragment not found" in msg or "HTTP Error 403" in msg:
            if not self.aborted:
                print(f"\n🚨 Detected issue in speed mode: '{msg}' - Triggering abort!")
            self.aborted = True

    def hook(self, _download):
        if self.aborted:
            raise DownloadError("ABORT_SPEED_MODE_TRIGGERED")


class SpeedLogger:
    def __init__(self, abort_state):
        self.abort_state = abort_state

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
        self.abort_state.check_fail(msg)


def run_download_with_fallback(ydl_opts: dict, url: str):
    # 1. Fast Mode
    abort_state = SpeedAbortState()
    fast_opts = ydl_opts.copy()
    fast_opts.update(SPEED_OPTS)
    fast_opts["logger"] = SpeedLogger(abort_state)
    
    existing_hooks = ydl_opts.get("progress_hooks", [])
    fast_opts["progress_hooks"] = existing_hooks + [abort_state.hook]
    
    print(f"🚀 Speed Download: Starting concurrent download...")
    
    try:
        with yt_dlp.YoutubeDL(fast_opts) as ydl:
            ydl.download([url])
        return
    except Exception as e:
        err_str = str(e)
        if "ABORT_SPEED_MODE_TRIGGERED" not in err_str and not abort_state.aborted:
            # A standard retry cannot repair ffmpeg, disk-space, unavailable
            # video or other deterministic failures. Re-raise instead of doing
            # the same expensive download and merge a second time.
            raise
        print(f"\n🛑 Speed mode aborted safely (Missing fragments/403 detected).")
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
}
