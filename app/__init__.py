from flask import Flask, request, jsonify
import os
import shutil

from app.core.config import TEMPLATE, RATE_FILE, FONT_FILE


def _require_api_key(app: Flask):
    secret = os.environ.get("SEA_PAY_API_KEY", "").strip()
    if not secret:
        return

    exempt = {"/", "/healthz", "/signatures.html", "/signature-manager.js"}

    @app.before_request
    def _check_api_key():
        if request.method == "OPTIONS":
            return None
        path = request.path or "/"
        if path in exempt or path.startswith("/static/"):
            return None
        provided = (
            request.headers.get("X-API-Key")
            or request.args.get("api_key")
            or request.cookies.get("sea_pay_api_key")
        )
        if provided != secret:
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
        return None


def create_app():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_DIR = os.path.join(BASE_DIR, "web", "frontend")

    app = Flask(
        __name__,
        template_folder=TEMPLATE_DIR,
        static_folder=TEMPLATE_DIR
    )
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("SEA_PAY_MAX_UPLOAD_MB", "50")) * 1024 * 1024

    _require_api_key(app)

    @app.get("/healthz")
    def healthz():
        status = {
            "template_exists": os.path.exists(TEMPLATE),
            "rates_exists": os.path.exists(RATE_FILE),
            "font_exists": os.path.exists(FONT_FILE),
            "tesseract": shutil.which("tesseract") is not None,
            "pdftoppm": shutil.which("pdftoppm") is not None,
        }
        http_status = 200 if all(status.values()) else 503
        return jsonify({"status": "ok" if http_status == 200 else "degraded", "checks": status}), http_status

    from .routes import bp
    app.register_blueprint(bp)

    return app
