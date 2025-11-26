import os
import tempfile
from flask import Flask, render_template, request, redirect, url_for, send_file, flash

from app.extractor import extract_sailors_and_events
from app.generator import generate_pg13_zip
from app.config import SECRET_KEY


def create_app():
    """
    Application factory for the PG13 Sea Pay Processor.
    """

    # Correct template directory: /app/app/templates_web
    template_dir = os.path.join(os.path.dirname(__file__), "templates_web")

    app = Flask(
        __name__,
        template_folder=template_dir
    )

    # Load secret key from config
    app.config["SECRET_KEY"] = SECRET_KEY

    # ------------------------------
    # Home Page (Upload Form)
    # ------------------------------
    @app.route("/", methods=["GET", "POST"])
    def index():
        if request.method == "POST":

            # Handle missing or invalid file
            file = request.files.get("pdf_file")
            print("DEBUG: request.files keys =", list(request.files.keys()))
            print("DEBUG: file =", file)
            print("DEBUG: filename =", file.filename if file else None)

            if not file or not file.filename.lower().endswith(".pdf"):
                print("DEBUG: PDF VALIDATION FAILED")
                flash("Please upload a valid SEA DUTY CERTIFICATION SHEET PDF.")
                return redirect(url_for("index"))
                
            # Save uploaded PDF to a temp directory
            temp_dir = tempfile.mkdtemp()
            pdf_path = os.path.join(temp_dir, file.filename)
            file.save(pdf_path)

            # Extract sailors & events
            sailors = extract_sailors_and_events(pdf_path)

            if not sailors:
                flash("No valid sailors or events found. Check the PDF formatting.")
                return redirect(url_for("index"))

            # Currently only the first sailor is processed
            sailor = sailors[0]

            # Generate ZIP file containing PG-13 PDFs
            zip_path = generate_pg13_zip(sailor, output_dir=temp_dir)

            return send_file(
                zip_path,
                as_attachment=True,
                download_name=os.path.basename(zip_path)
            )

        return render_template("index.html")

    # ------------------------------
    # Health Check Endpoint (for Unraid)
    # ------------------------------
    @app.route("/health", methods=["GET"])
    def health():
        return {"status": "ok"}, 200

    return app


# ------------------------------
# Run App for Docker / local dev
# ------------------------------
# Must listen on 0.0.0.0 so Unraid/host can access it.
# Must use port 8080 to match Dockerfile EXPOSE and Unraid template.
if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(host="0.0.0.0", port=8080)
