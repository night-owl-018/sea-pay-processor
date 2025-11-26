import os
import tempfile
from flask import Flask, render_template, request, redirect, url_for, send_file, flash

from app.extractor import extract_sailors_and_events
from app.generator import generate_pg13_zip
from app.config import SECRET_KEY


def create_app():
    template_dir = os.path.join(os.path.dirname(__file__), "templates_web")

    app = Flask(__name__, template_folder=template_dir)
    app.config["SECRET_KEY"] = SECRET_KEY

    @app.route("/", methods=["GET", "POST"])
    def index():
        print("DEBUG: request.method =", request.method)

        if request.method == "POST":

            if "pdf_file" not in request.files:
                print("DEBUG: NO 'pdf_file' key in request.files")
                flash("No file uploaded.")
                return redirect(url_for("index"))

            file = request.files["pdf_file"]
            print("DEBUG: filename =", file.filename)

            if file.filename == "":
                print("DEBUG: Empty filename")
                flash("Please select a PDF file.")
                return redirect(url_for("index"))

            if not file.filename.lower().endswith(".pdf"):
                print("DEBUG: Not a PDF")
                flash("Please upload a valid PDF.")
                return redirect(url_for("index"))

            temp_dir = tempfile.mkdtemp()
            pdf_path = os.path.join(temp_dir, file.filename)
            file.save(pdf_path)

            print("DEBUG: PDF saved to", pdf_path)

            sailors = extract_sailors_and_events(pdf_path)
            print("DEBUG: Extracted sailors =", sailors)

            if not sailors:
                print("DEBUG: NO SAILORS FOUND")
                flash("No valid sailors or events found in PDF.")
                return redirect(url_for("index"))

            sailor = sailors[0]

            zip_path = generate_pg13_zip(sailor, output_dir=temp_dir)
            print("DEBUG: ZIP GENERATED =", zip_path)

            return send_file(zip_path, as_attachment=True,
                             download_name=os.path.basename(zip_path))

        return render_template("index.html")

    @app.route("/health")
    def health():
        return {"status": "ok"}, 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
