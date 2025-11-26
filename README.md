# PG13 Sea Pay Processor

This project provides a Dockerized web application that:

- Accepts a SEA DUTY CERTIFICATION SHEET PDF
- Extracts Sailor names and SEA PAY events
- Cleans ship names and removes times, symbols, and MITE rows
- Groups events by ship and determines start/end dates
- Generates NAVPERS 1070/613 PG-13 PDFs
- Bundles all generated PG-13s into a ZIP file per Sailor

The goal is to automate Page 13 entries for Sea Pay processing.

---

## 🚀 Quick Start (Docker on Unraid or Linux)

Run the container:

```bash
docker run -d \
  -p 8092:8080 \
  -e SECRET_KEY="changeme" \
  ghcr.io/night-owl-018/stg1_nivera_atgsd-sea-pay-processor:latest
