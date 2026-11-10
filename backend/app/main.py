"""ASGI entrypoint: `uvicorn app.main:app`.

Env:
  DATA_DIR  directory with the source CSVs (default: ../data)
  DB_PATH   SQLite file for flags      (default: ./var/flags.db)
"""

import logging
import os
from pathlib import Path

from app.api import create_app
from app.catalog import Severity
from app.flags import FlagStore
from app.ingest import load_catalog

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT.parent / "data"))
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "var" / "flags.db"))

log = logging.getLogger("uvicorn.error")

catalog = load_catalog(DATA_DIR)
counts = {s: sum(1 for i in catalog.issues if i.severity == s) for s in Severity}
log.info(
    "catalog loaded from %s: %d toys, %d parts, %d suppliers; issues %s",
    DATA_DIR, len(catalog.toys), len(catalog.parts), len(catalog.suppliers),
    {k.value: v for k, v in counts.items()},
)

# No CORS: the browser always talks to one origin (Vite dev proxy locally, nginx in Docker).
app = create_app(catalog, FlagStore(DB_PATH))
