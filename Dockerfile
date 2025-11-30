FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    fonts-liberation \
    ttf-mscorefonts-installer \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir pytesseract pdf2image reportlab PyPDF2 pillow

CMD ["python", "app.py"]
