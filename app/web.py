if request.method == "POST":
    print("DEBUG: POST RECEIVED")

    print("DEBUG: request.files keys =", list(request.files.keys()))
    if "pdf_file" not in request.files:
        print("ERROR: 'pdf_file' NOT FOUND")
        flash("Upload failed: backend did not receive file.")
        return redirect(url_for("index"))

    file = request.files["pdf_file"]
    print("DEBUG: file object =", file)
    print("DEBUG: filename =", file.filename)

    if not file:
        print("ERROR: file is None")
        flash("Upload failed: file is empty.")
        return redirect(url_for("index"))

    if file.filename == "":
        print("ERROR: filename empty")
        flash("Upload failed: filename empty.")
        return redirect(url_for("index"))

    if not file.filename.lower().endswith(".pdf"):
        print("ERROR: not a PDF")
        flash("Upload failed: not a PDF file.")
        return redirect(url_for("index"))

    # SAVE FILE
    temp_dir = tempfile.mkdtemp()
    pdf_path = os.path.join(temp_dir, file.filename)
    file.save(pdf_path)
    print("DEBUG: Saved PDF to =", pdf_path)

    # PARSE PDF
    sailors = extract_sailors_and_events(pdf_path)
    print("DEBUG: extractor output =", sailors)

    if not sailors:
        print("ERROR: extractor returned EMPTY list")
        flash("Extractor found no sailors or events.")
        return redirect(url_for("index"))

    sailor = sailors[0]
    print("DEBUG: Processing sailor =", sailor)

    # GENERATE ZIP
    zip_path = generate_pg13_zip(sailor, output_dir=temp_dir)
    print("DEBUG: ZIP path =", zip_path)

    return send_file(zip_path, as_attachment=True, download_name=os.path.basename(zip_path))
