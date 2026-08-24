from flask import Flask, abort, request

from .cleanup_service import start_cleanup_worker
from .routes import bp


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    @app.before_request
    def protect_mutating_api_requests():
        if (
            request.path.startswith("/api/")
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.headers.get("X-YouTube-Downloader") != "1"
        ):
            abort(403)

    app.register_blueprint(bp)
    start_cleanup_worker()
    return app
