# SCV validation backend

Authenticated FastAPI service for SCV Review Studio. Runs the Python validation engine and the Validation Rule Testing Lab, with batched postcode lookups against the existing Supabase PostgreSQL reference.

Studio remains at its private ChatGPT Site address. Its server proxy sends authenticated requests here. No database password or service token belongs in browser code.

## Run on Render

Build: `pip install -r requirements.txt`

Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`

Keep the existing service variables and secret certificate file: `SCV_LOOKUP_TOKEN`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`, `PGSSLROOTCERT`. Database connections enforce `sslmode=verify-full`.

## Routes

- `GET /health`: service version, no authentication required.
- `POST /postcodes/lookup`: existing batched postcode API.
- `POST /api/import/inspect`: decode an uploaded CSV or TXT file.
- `POST /api/validate`: parse and validate all or selected implemented rules.
- `POST /api/lab/run`: run a Validation Rule Testing Lab case.

Every POST requires the service bearer token. Do not call these endpoints directly from browser code. Invalid footer errors retain their `FAILED_IMPORT` code for the Studio troubleshooting section.

Implemented rules: FFSTP_2D, FFSTP_9, FFSTP_10, DQ_1, FFSTP_12, DQ_24, DQ_27, plus file import checks. Catalogue entries outside this list are not implemented by this migration.

The online testing path accepts CSV/TXT files up to 20 MB. Large-file streaming, job queues and durable server-side submission history remain separate work. Uploaded records are processed in memory and are not saved by this service. The browser retains its existing submission-history behavior.

## Tests

Install `httpx==0.28.1` alongside the runtime requirements, then run `python -m unittest discover -v`.

## Local laptop

Use the separate `scv-python` package for the laptop. It uses the same engine and lab modules with the local SQLite postcode index. Publishing this service does not alter the laptop files.
