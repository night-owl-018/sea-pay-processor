FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /opt/app_defaults/pdf_template /opt/app_defaults/config \
 && cp -f /app/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf /opt/app_defaults/pdf_template/ \
 && cp -f /app/config/atgsd_n811.csv /opt/app_defaults/config/ \
 && adduser --disabled-password --gecos "" --uid 10001 appuser \
 && chown -R appuser:appuser /app /opt/app_defaults

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python - <<'PY' || exit 1
import json, sys, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/healthz", timeout=5) as r:
        data = json.loads(r.read().decode("utf-8"))
    sys.exit(0 if data.get("status") in {"ok", "degraded"} else 1)
except Exception:
    sys.exit(1)
PY

ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
