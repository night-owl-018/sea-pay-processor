#!/bin/sh
set -eu

mkdir -p /app/pdf_template /app/config /app/data /app/output

chmod -R 755 /app/output 2>/dev/null || echo "[WARN] Could not set permissions on /app/output"

if [ ! -f /app/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf ]; then
  echo "[INIT] Installing default template PDF -> /app/pdf_template"
  if [ -f /opt/app_defaults/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf ]; then
    cp -f /opt/app_defaults/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf /app/pdf_template/
  else
    echo "[ERROR] Default template PDF not found in image" >&2
    exit 1
  fi
fi

if [ ! -f /app/config/atgsd_n811.csv ]; then
  echo "[INIT] Installing default rate CSV -> /app/config"
  if [ -f /opt/app_defaults/config/atgsd_n811.csv ]; then
    cp -f /opt/app_defaults/config/atgsd_n811.csv /app/config/
  else
    echo "[ERROR] Default rate CSV not found in image" >&2
    exit 1
  fi
fi

if [ -f /app/config/ships.txt ]; then
  echo "[INIT] Using ship list override from /app/config/ships.txt"
  cp -f /app/config/ships.txt /app/ships.txt
fi

echo "[INIT] Verifying environment..."
echo "  Template:   $(ls -lh /app/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf 2>/dev/null || echo 'MISSING')"
echo "  Rate CSV:   $(ls -lh /app/config/atgsd_n811.csv 2>/dev/null || echo 'MISSING')"
echo "  Ships list: $(ls -lh /app/ships.txt 2>/dev/null || echo 'MISSING')"
echo "  Data dir:   $(ls -ld /app/data 2>/dev/null || echo 'MISSING')"
echo "  Output dir: $(ls -ld /app/output 2>/dev/null || echo 'MISSING')"

echo "[INIT] Startup complete - starting Flask app"
exec python /app/app.py
