from flask import Flask

from .cleanup_service import start_cleanup_worker
from .routes import bp


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.register_blueprint(bp)
    start_cleanup_worker()
    return app
