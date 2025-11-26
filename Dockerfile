FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Fix Python import path
ENV PYTHONPATH="/app:/app/app"

# Install system libs for pdfplumber + reportlab
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libcairo2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://127.0.0.1:8080/health || exit 1

CMD ["python", "-m", "app.web"]
