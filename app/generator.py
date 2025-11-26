import os
import tempfile
from datetime import datetime
from PyPDF2 import PdfReader, PdfWriter

def format_navy_date(d):
    return d.strftime("%d %b %Y").upper()

def generate_pg13_zip(sailor, output_dir):
    """
    sailor = {
        "name": "LAST FIRST",
        "events": [
            ("PAUL HAMILTON", date_start, date_end),
            ("STERETT", date_start, date_end),
            ...
        ]
    }
    """
    import zipfile

    zip_path = os.path.join(output_dir, f"{sailor['name'].replace(' ', '_')}.zip")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for ship, d_start, d_end in sailor["events"]:
            pdf_path = generate_single_pg13(
                sailor_name=sailor["name"],
                ship_name=ship,
                start_date=d_start,
                end_date=d_end,
                output_dir=output_dir
            )
            zipf.write(pdf_path, os.path.basename(pdf_path))

    return zip_path


def generate_single_pg13(sailor_name, ship_name, start_date, end_date, output_dir):
    template_path = "/app/app/templates_pdf/NAVPERS_1070_613_TEMPLATE.pdf"

    reader = PdfReader(template_path)
    writer = PdfWriter()

    page = reader.pages[0]
    writer.add_page(page)

    # ----------- FIELD DATA -----------
    start_fm = format_navy_date(start_date)
    end_fm = format_navy_date(end_date)

    date_line = f"REPORT CAREER SEA PAY FROM {start_fm} TO {end_fm}"
    remarks_line = f"Member performed eight continuous hours per day on-board: {ship_name}"

    data = {
        "Subject": "ENTITLEMENT",
        "Date": date_line,
        "SHIP": remarks_line,
        "NAME": sailor_name.upper()
    }

    writer.update_page_form_field_values(writer.pages[0], data)

    out_name = f"{ship_name}.pdf".replace("/", "-").replace("  ", " ").strip()
    out_path = os.path.join(output_dir, out_name)
    with open(out_path, "wb") as f:
        writer.write(f)

    return out_path
