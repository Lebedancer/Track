# FairToy — child-labour exposure

Lets a toy **Finisher** see its toys and how they relate to parts, factories and suppliers, **flag a
supplier** (whole supplier or specific factories) as using child labour, and see which toys are affected,
traced toy → part → factory → flagged supplier.

Spec, data findings and design rationale: [`docs/spec.md`](docs/spec.md).

## Run (Docker)

```bash
docker compose up --build
```

Open http://localhost:8080 (use another port with `PORT=9000 docker compose up`).

Flags are stored in SQLite on the `flags` Docker volume and survive restarts. To reset them, run
`docker compose down -v`.

## Run locally (dev)

Requires Python 3.12+ with [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
# API on :8000
cd backend
uv sync
uv run uvicorn app.main:app --reload

# UI on :5173, proxies /api to :8000
cd frontend
npm install
npm run dev
```

Env for the API: `DATA_DIR` (CSV folder, default `../data`), `DB_PATH` (default `backend/var/flags.db`).
OpenAPI docs: http://localhost:8000/docs.

## Tests

```bash
cd backend && uv run pytest
```

The tests cover:
- the exposure rules;
- every ingest rule;
- every API error case;
- an end-to-end run on the real dataset.

## Layout

```
backend/app/
  catalog.py   normalised read-only domain model
  ingest.py    CSV -> catalog, validation, data-quality issues
  exposure.py  pure exposure engine (statuses + traces)
  flags.py     SQLite flag store (the only mutable state)
  api.py       FastAPI routes
frontend/src/  React + TanStack Query; finisher & filters live in the URL
data/          source CSVs
docs/spec.md   specification
```

## What I'd do next

See spec §11. The highest-value items:
- record which source each finisher actually uses, so `potential` can be resolved;
- what-if re-sourcing;
- flag evidence attachments;
- CSV export for compliance reporting.
