from flask import Flask, request, jsonify, g
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import shutil
import uuid

from app.core.config import (
    TEMPLATE,
    RATE_FILE,
    FONT_FILE,
    MAX_UPLOAD_MB,
    ENABLE_PROXY_FIX,
    ensure_runtime_dirs,
)
from app.core.logger import log


def _require_api_key(app: Flask):
    secret = os.environ.get("SEA_PAY_API_KEY", "").strip()
    if not secret:
        return

    exempt = {"/", "/healthz", "/readyz", "/signatures.html", "/signature-manager.js"}

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
    ensure_runtime_dirs()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(base_dir, "web", "frontend")

    app = Flask(__name__, template_folder=template_dir, static_folder=template_dir)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

    if ENABLE_PROXY_FIX:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    _require_api_key(app)

    @app.before_request
    def _attach_request_id():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]

    @app.after_request
    def _harden_response(response):
        response.headers.setdefault("X-Request-ID", getattr(g, "request_id", ""))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        csp = (
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        return response

    @app.errorhandler(413)
    def too_large(_err):
        return jsonify({"status": "error", "message": f"Upload too large. Max is {MAX_UPLOAD_MB} MB."}), 413

    @app.errorhandler(Exception)
    def unhandled(err):
        log(f"UNHANDLED ERROR [{getattr(g, 'request_id', 'unknown')}] -> {err}")
        return jsonify({"status": "error", "message": "Internal server error", "request_id": getattr(g, "request_id", "")}), 500

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

    @app.get("/readyz")
    def readyz():
        checks = {
            "template_exists": os.path.exists(TEMPLATE),
            "rates_exists": os.path.exists(RATE_FILE),
            "font_exists": os.path.exists(FONT_FILE),
        }
        ready = all(checks.values())
        return jsonify({"status": "ready" if ready else "not-ready", "checks": checks}), (200 if ready else 503)

    from .routes import bp
    app.register_blueprint(bp)
    return app
