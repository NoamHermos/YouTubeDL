import codecs
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime

from .file_service import list_download_files, prioritize_job_outputs
from .settings import COOKIE_FILE, DOWNLOADS_DIR, MAX_LOG_LINES, PROJECT_DIR, WEB_WORKER

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_log(job_id: str, text: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return

        for char in text:
            if char == "\r":
                job["_replace_log_line"] = True
                continue

            if char == "\n":
                buffer = job.get("_log_buffer", "")
                job["log"].append(f"{buffer}\n")
                job["_log_buffer"] = ""
                job["_replace_log_line"] = False
                continue

            if job.pop("_replace_log_line", False):
                job["_log_buffer"] = char
            else:
                job["_log_buffer"] = job.get("_log_buffer", "") + char

        if len(job["log"]) > MAX_LOG_LINES:
            job["log"] = job["log"][-MAX_LOG_LINES:]


def build_worker_command(payload: dict) -> list[str]:
    cmd = [
        sys.executable,
        "-u",
        str(WEB_WORKER),
        "--url",
        payload["url"],
        "--source",
        payload["source"],
        "--download-type",
        payload["download_type"],
        "--range",
        payload.get("range") or "",
        "--downloads-dir",
        str(DOWNLOADS_DIR),
        "--cookie-file",
        str(COOKIE_FILE),
        "--workers",
        str(payload["workers"]),
    ]
    if payload.get("audio_subtitles"):
        cmd.append("--audio-subtitles")
    if payload.get("with_subtitles"):
        cmd.append("--with-subtitles")
    if payload.get("format_id"):
        cmd.extend(["--format-id", payload["format_id"]])
    return cmd


def run_process(job_id: str, payload: dict) -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    started_marker = time.time()

    with jobs_lock:
        jobs[job_id]["status"] = "running"
        jobs[job_id]["started_at"] = now_text()
        jobs[job_id]["started_marker"] = started_marker

    try:
        proc = subprocess.Popen(
            build_worker_command(payload),
            cwd=str(PROJECT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=env,
        )
        with jobs_lock:
            jobs[job_id]["process"] = proc

        assert proc.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            chunk = proc.stdout.read(1024)
            if not chunk:
                break
            append_log(job_id, decoder.decode(chunk))

        remaining_text = decoder.decode(b"", final=True)
        if remaining_text:
            append_log(job_id, remaining_text)

        rc = proc.wait()
        outputs = prioritize_job_outputs(
            list_download_files(since=started_marker - 1, limit=20),
            payload["download_type"],
        )
        with jobs_lock:
            job = jobs[job_id]
            job["returncode"] = rc
            job["status"] = "finished" if rc == 0 else "failed"
            job["finished_at"] = now_text()
            job["outputs"] = outputs
            job["process"] = None
    except Exception as exc:
        append_log(job_id, f"ERROR: {exc}\n")
        with jobs_lock:
            job = jobs[job_id]
            job["status"] = "failed"
            job["finished_at"] = now_text()
            job["process"] = None


def public_job(job: dict) -> dict:
    log = list(job["log"])
    if job.get("_log_buffer"):
        log.append(job["_log_buffer"])

    return {
        "id": job["id"],
        "url": job["url"],
        "source": job["source"],
        "download_type": job["download_type"],
        "status": job["status"],
        "created_at": job["created_at"],
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "returncode": job.get("returncode"),
        "log": log,
        "outputs": job.get("outputs", []),
    }


def normalize_workers(raw_workers) -> int:
    try:
        workers = int(raw_workers or 4)
    except ValueError:
        workers = 4
    return max(1, min(workers, 16))


def create_job_record(payload: dict) -> str:
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "url": payload["url"],
        "source": payload["source"],
        "download_type": payload["download_type"],
        "range": payload.get("range") or "",
        "workers": normalize_workers(payload.get("workers")),
        "format_id": payload.get("format_id") or "",
        "audio_subtitles": bool(payload.get("audio_subtitles")),
        "with_subtitles": bool(payload.get("with_subtitles")),
        "status": "queued",
        "created_at": now_text(),
        "log": [],
        "outputs": [],
        "_log_buffer": "",
        "_replace_log_line": False,
        "process": None,
    }

    with jobs_lock:
        jobs[job_id] = job

    thread = threading.Thread(target=run_process, args=(job_id, job.copy()), daemon=True)
    thread.start()
    return job_id


def cancel_job_process(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        proc = job.get("process")
        if not proc or job["status"] != "running":
            return public_job(job)
        job["status"] = "cancelling"

    proc.terminate()
    time.sleep(1)
    if proc.poll() is None:
        proc.kill()
    append_log(job_id, "\nJob cancelled from web UI.\n")
    return {"ok": True}
