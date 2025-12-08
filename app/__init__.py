from flask import Flask
import os

def create_app():
    # Point Flask to the correct HTML folders
    base_dir = os.path.abspath(os.path.dirname(__file__))
    template_path = os.path.join(base_dir, "web", "frontend")
    static_path = os.path.join(base_dir, "web", "frontend")

    app = Flask(
        __name__,
        template_folder=template_path,
        static_folder=static_path
    )

    # Normal imports AFTER app creation
    from .routes import bp
    app.register_blueprint(bp)

    return app
