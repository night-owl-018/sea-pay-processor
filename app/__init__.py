# app/__init__.py

import os
from flask import Flask


def create_app():
    # Absolute path to THIS file's directory: /app/app
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # This matches your structure: /app/app/web/frontend/index.html
    template_dir = os.path.join(base_dir, "web", "frontend")

    # Use that directory for both templates and static files (CSS/JS in same file)
    app = Flask(
        __name__,
        template_folder=template_dir,
        static_folder=template_dir,
    )

    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    return app
