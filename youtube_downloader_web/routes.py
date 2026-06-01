import ytdl
from flask import Blueprint, abort, jsonify, render_template, request, send_from_directory

from .file_service import (
    copy_file_to_clipboard,
    list_download_files,
    open_local_file,
    open_local_file_location,
    resolve_download_file,
)
from .format_service import build_video_format_options, fetch_video_info_for_formats
from .job_service import cancel_job_process, create_job_record, jobs, jobs_lock, public_job
from .settings import DOWNLOADS_DIR

bp = Blueprint("web", __name__)


@bp.get("/")
def index():
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    return render_template("index.html", downloads_dir=DOWNLOADS_DIR)


@bp.post("/api/formats")
def api_formats():
    payload = request.get_json(force=True, silent=True) or {}
    url = (payload.get("url") or "").strip()
    source = payload.get("source") or "single"

    if not url:
        return jsonify({"error": "URL is required"}), 400
    if source not in {"single", "playlist"}:
        return jsonify({"error": "Invalid source"}), 400

    try:
        info = fetch_video_info_for_formats(url, source, payload.get("range") or "")
        return jsonify({
            "title": ytdl.sanitize_filename(info.get("title", "Video")),
            "formats": build_video_format_options(info),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.post("/api/jobs")
def create_job():
    payload = request.get_json(force=True, silent=True) or {}
    url = (payload.get("url") or "").strip()
    source = payload.get("source") or "single"
    download_type = payload.get("download_type") or "video"

    if not url:
        return jsonify({"error": "URL is required"}), 400
    if source not in {"single", "playlist"}:
        return jsonify({"error": "Invalid source"}), 400
    if download_type not in {"video", "audio", "srt", "txt"}:
        return jsonify({"error": "Invalid download type"}), 400

    payload["url"] = url
    payload["source"] = source
    payload["download_type"] = download_type
    return jsonify({"id": create_job_record(payload)})


@bp.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            abort(404)
        return jsonify(public_job(job))


@bp.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    try:
        return jsonify(cancel_job_process(job_id))
    except KeyError:
        abort(404)


@bp.get("/api/files")
def api_files():
    return jsonify({"files": list_download_files()})


@bp.post("/api/files/open")
def api_open_file():
    payload = request.get_json(force=True, silent=True) or {}
    try:
        open_local_file(resolve_download_file(payload))
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/api/files/open-location")
def api_open_file_location():
    payload = request.get_json(force=True, silent=True) or {}
    try:
        open_local_file_location(resolve_download_file(payload))
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bp.post("/api/files/copy")
def api_copy_file():
    payload = request.get_json(force=True, silent=True) or {}
    try:
        copy_file_to_clipboard(resolve_download_file(payload))
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@bp.get("/files/<path:filename>")
def download_file(filename: str):
    return send_from_directory(DOWNLOADS_DIR, filename, as_attachment=False)
