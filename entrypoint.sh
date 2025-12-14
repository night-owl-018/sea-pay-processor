#!/bin/sh

# -------------------------------------------------
# Ensure required directories exist FIRST
# -------------------------------------------------
mkdir -p /templates
mkdir -p /config
mkdir -p /data
mkdir -p /output

# -------------------------------------------------
# Install default template if missing
# -------------------------------------------------
if [ ! -f /templates/NAVPERS_1070_613_TEMPLATE.pdf ]; then
  echo "[INIT] Installing default template PDF"
  if [ -f /app/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf ]; then
    cp /app/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf /templates/
  else
    echo "[ERROR] Template PDF not found in image!"
  fi
fi

# -------------------------------------------------
# Install default CSV if missing
# -------------------------------------------------
if [ ! -f /config/atgsd_n811.csv ]; then
  echo "[INIT] Installing default rate CSV"
  if [ -f /app/config/atgsd_n811.csv ]; then
    cp /app/config/atgsd_n811.csv /config/
  else
    echo "[ERROR] Rate CSV not found in image!"
  fi
fi

# -------------------------------------------------
# Verify critical files exist
# -------------------------------------------------
echo "[INIT] Verifying environment..."
echo "  Template: $(ls -lh /templates/NAVPERS_1070_613_TEMPLATE.pdf 2>/dev/null || echo 'MISSING')"
echo "  Rate CSV: $(ls -lh /config/atgsd_n811.csv 2>/dev/null || echo 'MISSING')"
echo "  Ships list: $(ls -lh /app/ships.txt 2>/dev/null || echo 'MISSING')"

echo "[INIT] Startup complete - starting Flask app"

exec python /app/app.py
