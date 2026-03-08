FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /opt/app_defaults/pdf_template /opt/app_defaults/config \
 && cp -f /app/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf /opt/app_defaults/pdf_template/ \
 && cp -f /app/config/atgsd_n811.csv /opt/app_defaults/config/

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080

CMD ["/entrypoint.sh"]
