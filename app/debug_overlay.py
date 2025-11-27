from PyPDF2 import PdfReader, PdfWriter, PageObject

TEMPLATE = "app/templates_pdf/NAVPERS_1070_613_TEMPLATE.pdf"
GRID = "grid.pdf"
OUT = "grid_overlay.pdf"

def combine():
    template = PdfReader(TEMPLATE).pages[0]
    grid = PdfReader(GRID).pages[0]

    merged = PageObject.create_blank_page(
        width=template.mediabox.width,
        height=template.mediabox.height
    )
    merged.merge_page(template)
    merged.merge_page(grid)

    writer = PdfWriter()
    writer.add_page(merged)
    with open(OUT, "wb") as f:
        writer.write(f)

if __name__ == "__main__":
    combine()
