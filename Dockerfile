FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt update && apt install -y \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 8080

CMD ["python", "app.py"]
