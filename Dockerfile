FROM python:3.12-slim

WORKDIR /app

ENV PYTHONPATH="/app"
ENV FLASK_ENV=production

RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8080

HEALTHCHECK --interval=20s --timeout=5s --retries=3 \
  CMD python - <<'EOF' \
import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=3) \
EOF

CMD ["python", "-m", "app.web"]
