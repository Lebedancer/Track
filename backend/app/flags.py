"""Persistent supplier flags (the only mutable state). SQLite, one connection per operation."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.exposure import ActiveFlag

SCHEMA = """
CREATE TABLE IF NOT EXISTS supplier_flag (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id   TEXT NOT NULL,
    reason        TEXT,
    flagged_by    TEXT,
    created_at    TEXT NOT NULL,
    lifted_at     TEXT,
    lifted_by     TEXT,
    lift_reason   TEXT
);
-- at most one active flag per supplier, enforced by the database (race-safe)
CREATE UNIQUE INDEX IF NOT EXISTS ux_one_active_flag
    ON supplier_flag(supplier_id) WHERE lifted_at IS NULL;
CREATE TABLE IF NOT EXISTS supplier_flag_factory (
    flag_id    INTEGER NOT NULL REFERENCES supplier_flag(id),
    factory_id TEXT NOT NULL,
    PRIMARY KEY (flag_id, factory_id)
);
"""


class FlagConflict(Exception):
    pass


class FlagNotFound(Exception):
    pass


@dataclass(frozen=True)
class FlagRecord:
    id: int
    supplier_id: str
    factory_ids: tuple[str, ...]  # empty = whole supplier
    reason: str | None
    flagged_by: str | None
    created_at: str
    lifted_at: str | None
    lifted_by: str | None
    lift_reason: str | None

    @property
    def active(self) -> bool:
        return self.lifted_at is None

    def to_active(self) -> ActiveFlag:
        return ActiveFlag(self.id, self.supplier_id, frozenset(self.factory_ids))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class FlagStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _select(self, conn: sqlite3.Connection, where: str = "", args: tuple = ()) -> list[FlagRecord]:
        rows = conn.execute(f"SELECT * FROM supplier_flag {where} ORDER BY id DESC", args).fetchall()
        factories: dict[int, list[str]] = {}
        for fid, fac in conn.execute("SELECT flag_id, factory_id FROM supplier_flag_factory ORDER BY factory_id"):
            factories.setdefault(fid, []).append(fac)
        return [
            FlagRecord(
                id=r["id"], supplier_id=r["supplier_id"], factory_ids=tuple(factories.get(r["id"], ())),
                reason=r["reason"], flagged_by=r["flagged_by"], created_at=r["created_at"],
                lifted_at=r["lifted_at"], lifted_by=r["lifted_by"], lift_reason=r["lift_reason"],
            )
            for r in rows
        ]

    def create(self, supplier_id: str, factory_ids: list[str], reason: str | None, flagged_by: str | None) -> FlagRecord:
        with self._conn() as c:
            try:
                cur = c.execute(
                    "INSERT INTO supplier_flag (supplier_id, reason, flagged_by, created_at) VALUES (?, ?, ?, ?)",
                    (supplier_id, reason, flagged_by, _now()),
                )
            except sqlite3.IntegrityError:
                raise FlagConflict(f"supplier {supplier_id} already has an active flag") from None
            c.executemany(
                "INSERT INTO supplier_flag_factory (flag_id, factory_id) VALUES (?, ?)",
                [(cur.lastrowid, f) for f in factory_ids],
            )
            return self._select(c, "WHERE id = ?", (cur.lastrowid,))[0]

    def lift(self, flag_id: int, reason: str | None, lifted_by: str | None) -> FlagRecord:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE supplier_flag SET lifted_at = ?, lifted_by = ?, lift_reason = ? WHERE id = ? AND lifted_at IS NULL",
                (_now(), lifted_by, reason, flag_id),
            )
            found = self._select(c, "WHERE id = ?", (flag_id,))
            if not found:
                raise FlagNotFound(flag_id)
            if cur.rowcount == 0:
                raise FlagConflict(f"flag {flag_id} is already lifted")
            return found[0]

    def active(self) -> list[FlagRecord]:
        with self._conn() as c:
            return self._select(c, "WHERE lifted_at IS NULL")

    def history(self, supplier_id: str) -> list[FlagRecord]:
        with self._conn() as c:
            return self._select(c, "WHERE supplier_id = ?", (supplier_id,))
