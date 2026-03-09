# ATGSD Sea Pay Processor

Professionalized Flask service for processing NAVPERS 1070/613 sea pay documentation.

## What this package now includes

- Gunicorn-based production startup
- Health and readiness probes
- Request ID and security headers
- Safer upload validation for process jobs and signature assets
- Persistent signature library with assignment tracking
- Atomic JSON writes for critical state
- Smoke tests for core API behavior

## Runtime paths

Map host folders to these container paths:

- `/app/data`
- `/app/output`
- `/app/pdf_template`
- `/app/config`

## Quick start

```bash
docker build -t seapay-processor .
docker run --rm -p 8080:8080   -v /host/data:/app/data   -v /host/output:/app/output   -v /host/pdf_template:/app/pdf_template   -v /host/config:/app/config   -e SEA_PAY_API_KEY=change-me   seapay-processor
```

## Production recommendations

- Run only behind Gunicorn using the provided `entrypoint.sh`
- Set `SEA_PAY_API_KEY` and send it as `X-API-Key`
- Persist `/app/output`, `/app/config`, `/app/pdf_template`, and `/app/data`
- Probe `/healthz` and `/readyz`
- Keep `output/signatures.json` on persistent storage
- Set `SEA_PAY_MAX_UPLOAD_MB` and `SEA_PAY_MAX_SIGNATURE_IMAGE_MB` to match your environment
- Terminate TLS upstream and pass `X-Forwarded-*` headers

## Useful environment variables

- `SEA_PAY_API_KEY`
- `SEA_PAY_MAX_UPLOAD_MB`
- `SEA_PAY_MAX_SIGNATURE_IMAGE_MB`
- `SEA_PAY_GUNICORN_WORKERS`
- `SEA_PAY_GUNICORN_THREADS`
- `SEA_PAY_GUNICORN_TIMEOUT`
- `SEA_PAY_ENABLE_PROXY_FIX`
- `SEA_PAY_LOG_PATH`

## Notes

This package was hardened for service readiness, but the OCR/PDF workflow should still be validated with real operational input files before live deployment.
