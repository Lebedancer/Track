"""CSV -> Catalog. Validates, normalises and records data-quality issues (spec §5).

Fatal problems (missing file / missing column) raise IngestError.
Row-level problems are recorded as issues; invalid rows are skipped.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterator
from pathlib import Path

from app.catalog import (
    BomLine,
    Catalog,
    Factory,
    Finisher,
    Issue,
    Part,
    PartSource,
    Severity,
    Supplier,
    Toy,
    ToyListing,
)

# file -> (all columns expected in header, columns whose value is required)
SCHEMA: dict[str, tuple[list[str], list[str]]] = {
    "finishers": (["finisher_id", "finisher_name", "hq_country"], ["finisher_id", "finisher_name"]),
    "suppliers": (["supplier_id", "supplier_name", "hq_country"], ["supplier_id", "supplier_name"]),
    "factories": (
        ["factory_id", "supplier_id", "factory_name", "address_line", "city", "country"],
        ["factory_id", "supplier_id", "factory_name"],
    ),
    "parts": (
        ["part_id", "part_name", "supplier_id", "factory_id", "unit_cost_usd"],
        ["part_id", "part_name", "factory_id", "unit_cost_usd"],
    ),
    "toys": (
        ["toy_id", "toy_name", "finisher_id", "retail_price_usd", "units_per_year"],
        ["toy_id", "toy_name", "finisher_id", "retail_price_usd", "units_per_year"],
    ),
    "bill_of_materials": (["toy_id", "part_id", "quantity"], ["toy_id", "part_id", "quantity"]),
}


class IngestError(Exception):
    pass


class _InvalidNumber(ValueError):
    pass


def _parse_float(value: str) -> float:
    try:
        x = float(value)
    except ValueError:
        raise _InvalidNumber(value) from None
    if not math.isfinite(x) or x < 0:
        raise _InvalidNumber(value)
    return x


def _parse_int(value: str, minimum: int) -> int:
    x = _parse_float(value)
    if not x.is_integer() or x < minimum:
        raise _InvalidNumber(value)
    return int(x)


class _Loader:
    def __init__(self, data_dir: Path):
        self.dir = data_dir
        self.cat = Catalog()

    # -- helpers --------------------------------------------------------------

    def issue(self, code: str, severity: Severity, entity: str, entity_id: str | None, message: str) -> None:
        self.cat.issues.append(Issue(code, severity, entity, entity_id, message))

    def rows(self, name: str) -> Iterator[tuple[int, dict[str, str | None]]]:
        path = self.dir / f"{name}.csv"
        if not path.is_file():
            raise IngestError(f"missing file: {path.name}")
        columns, required = SCHEMA[name]
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header = [h.strip().lower() for h in next(reader, [])]
            missing = [c for c in columns if c not in header]
            if missing:
                raise IngestError(f"{path.name}: missing columns {missing}")
            idx = {c: header.index(c) for c in columns}
            for raw in reader:
                if not any(cell.strip() for cell in raw):
                    continue  # blank line
                row = {}
                for c, i in idx.items():
                    v = raw[i].strip() if i < len(raw) else ""
                    row[c] = v or None
                empty = [c for c in required if row[c] is None]
                if empty:
                    self.issue(
                        "missing_field", Severity.ERROR, name, row[columns[0]],
                        f"{path.name} line {reader.line_num}: empty {empty}; row skipped",
                    )
                    continue
                yield reader.line_num, row

    def number_error(self, name: str, line: int, entity_id: str, field: str, value: str) -> None:
        self.issue(
            "invalid_number", Severity.ERROR, name, entity_id,
            f"{name}.csv line {line}: invalid {field} {value!r}; row skipped",
        )

    def unknown_ref(self, name: str, line: int, entity_id: str, field: str, value: str) -> None:
        self.issue(
            "unknown_reference", Severity.ERROR, name, entity_id,
            f"{name}.csv line {line}: unknown {field} {value!r}; row skipped",
        )

    def duplicate(self, name: str, line: int, entity_id: str) -> None:
        self.issue(
            "duplicate_row", Severity.WARNING, name, entity_id,
            f"{name}.csv line {line}: duplicate {entity_id}; first occurrence kept",
        )

    # -- tables ---------------------------------------------------------------

    def load(self) -> Catalog:
        self.finishers()
        self.suppliers()
        self.factories()
        self.parts()
        self.toys()
        self.bom()
        self.cat.build_indexes()
        self.post_checks()
        return self.cat

    def finishers(self) -> None:
        for line, r in self.rows("finishers"):
            fid = r["finisher_id"]
            if fid in self.cat.finishers:
                self.duplicate("finishers", line, fid)
                continue
            self.cat.finishers[fid] = Finisher(fid, r["finisher_name"], r["hq_country"])

    def suppliers(self) -> None:
        for line, r in self.rows("suppliers"):
            sid = r["supplier_id"]
            if sid in self.cat.suppliers:
                self.duplicate("suppliers", line, sid)
                continue
            self.cat.suppliers[sid] = Supplier(sid, r["supplier_name"], r["hq_country"])

    def factories(self) -> None:
        for line, r in self.rows("factories"):
            fid = r["factory_id"]
            if r["supplier_id"] not in self.cat.suppliers:
                self.unknown_ref("factories", line, fid, "supplier_id", r["supplier_id"])
                continue
            if fid in self.cat.factories:
                self.duplicate("factories", line, fid)
                continue
            self.cat.factories[fid] = Factory(
                fid, r["supplier_id"], r["factory_name"], r["address_line"], r["city"], r["country"]
            )
            if r["address_line"] is None or r["city"] is None:
                self.issue("missing_address", Severity.INFO, "factories", fid, f"factory {fid} has no full address")

    def parts(self) -> None:
        seen: set[tuple[str, str]] = set()
        for line, r in self.rows("parts"):
            pid, fac_id = r["part_id"], r["factory_id"]
            factory = self.cat.factories.get(fac_id)
            if factory is None:
                self.unknown_ref("parts", line, pid, "factory_id", fac_id)
                continue
            try:
                cost = _parse_float(r["unit_cost_usd"])
            except _InvalidNumber:
                self.number_error("parts", line, pid, "unit_cost_usd", r["unit_cost_usd"])
                continue
            if (pid, fac_id) in seen:
                self.duplicate("parts", line, f"{pid}/{fac_id}")
                continue
            seen.add((pid, fac_id))
            if r["supplier_id"] is not None and r["supplier_id"] != factory.supplier_id:
                self.issue(
                    "supplier_factory_mismatch", Severity.WARNING, "parts", pid,
                    f"parts.csv line {line}: supplier {r['supplier_id']} but factory {fac_id} "
                    f"belongs to {factory.supplier_id}; factory's supplier used",
                )
            existing = self.cat.parts.get(pid)
            if existing is None:
                self.cat.parts[pid] = Part(pid, r["part_name"])
            elif existing.name != r["part_name"]:
                self.issue(
                    "conflicting_name", Severity.WARNING, "parts", pid,
                    f"parts.csv line {line}: name {r['part_name']!r} differs from {existing.name!r}; first kept",
                )
            self.cat.sources.append(PartSource(pid, fac_id, factory.supplier_id, cost))

    def toys(self) -> None:
        seen: set[tuple[str, str]] = set()
        for line, r in self.rows("toys"):
            tid, fin = r["toy_id"], r["finisher_id"]
            if fin not in self.cat.finishers:
                self.unknown_ref("toys", line, tid, "finisher_id", fin)
                continue
            try:
                price = _parse_float(r["retail_price_usd"])
            except _InvalidNumber:
                self.number_error("toys", line, tid, "retail_price_usd", r["retail_price_usd"])
                continue
            try:
                units = _parse_int(r["units_per_year"], minimum=0)
            except _InvalidNumber:
                self.number_error("toys", line, tid, "units_per_year", r["units_per_year"])
                continue
            if (tid, fin) in seen:
                self.duplicate("toys", line, f"{tid}/{fin}")
                continue
            seen.add((tid, fin))
            existing = self.cat.toys.get(tid)
            if existing is None:
                self.cat.toys[tid] = Toy(tid, r["toy_name"])
            elif existing.name != r["toy_name"]:
                self.issue(
                    "conflicting_name", Severity.WARNING, "toys", tid,
                    f"toys.csv line {line}: name {r['toy_name']!r} differs from {existing.name!r}; first kept",
                )
            self.cat.listings.append(ToyListing(tid, fin, price, units))

    def bom(self) -> None:
        seen: set[tuple[str, str]] = set()
        for line, r in self.rows("bill_of_materials"):
            tid, pid = r["toy_id"], r["part_id"]
            key = f"{tid}/{pid}"
            if tid not in self.cat.toys:
                self.unknown_ref("bill_of_materials", line, key, "toy_id", tid)
                continue
            if pid not in self.cat.parts:
                self.unknown_ref("bill_of_materials", line, key, "part_id", pid)
                continue
            try:
                qty = _parse_int(r["quantity"], minimum=1)
            except _InvalidNumber:
                self.number_error("bill_of_materials", line, key, "quantity", r["quantity"])
                continue
            if (tid, pid) in seen:
                self.duplicate("bill_of_materials", line, key)
                continue
            seen.add((tid, pid))
            self.cat.bom.append(BomLine(tid, pid, qty))

    def post_checks(self) -> None:
        c = self.cat
        for pid, sources in c.sources_by_part.items():
            if len(sources) > 1:
                sups = ", ".join(sorted({s.supplier_id for s in sources}))
                self.issue(
                    "multi_sourced_part", Severity.INFO, "parts", pid,
                    f"part {pid} has {len(sources)} sources ({sups}); BOM does not say which is used",
                )
        for tid, listings in c.listings_by_toy.items():
            if len(listings) > 1:
                fins = ", ".join(sorted(l.finisher_id for l in listings))
                self.issue("multi_listed_toy", Severity.INFO, "toys", tid, f"toy {tid} is sold by {fins}")
        for sid in c.suppliers:
            if sid not in c.factories_by_supplier:
                self.issue("supplier_without_factories", Severity.INFO, "suppliers", sid, f"supplier {sid} has no factories")
        for tid in c.toys:
            if tid not in c.bom_by_toy:
                self.issue("toy_without_bom", Severity.INFO, "toys", tid, f"toy {tid} has no bill of materials")
        for pid in c.parts:
            if pid not in c.toys_by_part:
                self.issue("unused_part", Severity.INFO, "parts", pid, f"part {pid} is not used in any toy")


def load_catalog(data_dir: str | Path) -> Catalog:
    return _Loader(Path(data_dir)).load()
