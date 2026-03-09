#!/bin/sh
set -eu

log() {
  printf '%s %s\n' "[INIT]" "$*"
}

die() {
  printf '%s %s\n' "[ERROR]" "$*" >&2
  exit 1
}

copy_default_if_missing() {
  src="$1"
  dst="$2"
  name="$3"
  if [ ! -f "$dst" ]; then
    [ -f "$src" ] || die "Missing default $name at $src"
    log "Installing default $name -> $dst"
    cp -f "$src" "$dst"
  fi
}

mkdir -p /app/pdf_template /app/config /app/data /app/output
mkdir -p /opt/app_defaults/pdf_template /opt/app_defaults/config

copy_default_if_missing \
  /opt/app_defaults/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf \
  /app/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf \
  "template PDF"

copy_default_if_missing \
  /opt/app_defaults/config/atgsd_n811.csv \
  /app/config/atgsd_n811.csv \
  "rates CSV"

if [ -f /app/config/ships.txt ]; then
  log "Using ship list override from /app/config/ships.txt"
  cp -f /app/config/ships.txt /app/ships.txt
fi

command -v tesseract >/dev/null 2>&1 || die "tesseract is not installed"
command -v pdftoppm >/dev/null 2>&1 || die "pdftoppm is not installed"
[ -f /app/Times_New_Roman.ttf ] || die "Times_New_Roman.ttf is missing from image"
[ -f /app/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf ] || die "Template PDF missing after init"
[ -f /app/config/atgsd_n811.csv ] || die "Rates CSV missing after init"

export PYTHONUNBUFFERED=1
HOST="${SEA_PAY_HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
WORKERS="${SEA_PAY_GUNICORN_WORKERS:-1}"
THREADS="${SEA_PAY_GUNICORN_THREADS:-4}"
TIMEOUT="${SEA_PAY_GUNICORN_TIMEOUT:-300}"

log "Template: $(ls -lh /app/pdf_template/NAVPERS_1070_613_TEMPLATE.pdf | awk '{print $5, $9}')"
log "Rates CSV: $(ls -lh /app/config/atgsd_n811.csv | awk '{print $5, $9}')"
log "Output dir: $(ls -ld /app/output | awk '{print $1, $9}')"
log "Starting Gunicorn on ${HOST}:${PORT} (workers=${WORKERS}, threads=${THREADS}, timeout=${TIMEOUT})"

exec gunicorn \
  --bind "${HOST}:${PORT}" \
  --workers "${WORKERS}" \
  --threads "${THREADS}" \
  --timeout "${TIMEOUT}" \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  "wsgi:app"
