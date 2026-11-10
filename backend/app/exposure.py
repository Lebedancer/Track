"""Exposure engine: pure function (catalog, active flags) -> statuses.

Rules (spec §6):

Source status
  flagged        supplier has an active flag that is whole-supplier or lists this factory
  supplier_risk  supplier has an active factory-scoped flag that does not list this factory
  clean          otherwise

Part status (n sources, f flagged)
  confirmed      f == n > 0
  potential      0 < f < n
  supplier_risk  f == 0 and some source is supplier_risk
  clean          otherwise

Toy status = most severe part status over its BOM.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.catalog import BomLine, Catalog, PartSource


class SourceStatus(StrEnum):
    FLAGGED = "flagged"
    SUPPLIER_RISK = "supplier_risk"
    CLEAN = "clean"


class ExposureStatus(StrEnum):
    CONFIRMED = "confirmed"
    POTENTIAL = "potential"
    SUPPLIER_RISK = "supplier_risk"
    CLEAN = "clean"


SEVERITY: dict[ExposureStatus, int] = {
    ExposureStatus.CLEAN: 0,
    ExposureStatus.SUPPLIER_RISK: 1,
    ExposureStatus.POTENTIAL: 2,
    ExposureStatus.CONFIRMED: 3,
}


@dataclass(frozen=True)
class ActiveFlag:
    id: int
    supplier_id: str
    factory_ids: frozenset[str]  # empty = whole supplier

    @property
    def whole_supplier(self) -> bool:
        return not self.factory_ids


def factory_status(supplier_id: str, factory_id: str, flags_by_supplier: Mapping[str, ActiveFlag]) -> SourceStatus:
    flag = flags_by_supplier.get(supplier_id)
    if flag is None:
        return SourceStatus.CLEAN
    if flag.whole_supplier or factory_id in flag.factory_ids:
        return SourceStatus.FLAGGED
    return SourceStatus.SUPPLIER_RISK


def source_status(source: PartSource, flags_by_supplier: Mapping[str, ActiveFlag]) -> SourceStatus:
    return factory_status(source.supplier_id, source.factory_id, flags_by_supplier)


def combine_part_status(statuses: Sequence[SourceStatus]) -> ExposureStatus:
    n = len(statuses)
    flagged = sum(1 for s in statuses if s == SourceStatus.FLAGGED)
    if n and flagged == n:
        return ExposureStatus.CONFIRMED
    if flagged:
        return ExposureStatus.POTENTIAL
    if SourceStatus.SUPPLIER_RISK in statuses:
        return ExposureStatus.SUPPLIER_RISK
    return ExposureStatus.CLEAN


def worst(statuses: Iterable[ExposureStatus]) -> ExposureStatus:
    return max(statuses, key=SEVERITY.__getitem__, default=ExposureStatus.CLEAN)


@dataclass
class Exposure:
    catalog: Catalog
    flags_by_supplier: dict[str, ActiveFlag]
    source_status: dict[tuple[str, str], SourceStatus]
    part_status: dict[str, ExposureStatus]
    toy_status: dict[str, ExposureStatus]

    def affected_lines(self, toy_id: str) -> list[BomLine]:
        """Non-clean BOM lines of a toy, most severe first."""
        lines = [
            l for l in self.catalog.bom_by_toy.get(toy_id, [])
            if self.part_status[l.part_id] != ExposureStatus.CLEAN
        ]
        return sorted(lines, key=lambda l: (-SEVERITY[self.part_status[l.part_id]], l.part_id))

    def toys_affected_by_supplier(self, supplier_id: str) -> set[str]:
        """Toys containing a part with a non-clean source belonging to this supplier."""
        toys: set[str] = set()
        for src in self.catalog.sources_by_supplier.get(supplier_id, []):
            if self.source_status[(src.part_id, src.factory_id)] != SourceStatus.CLEAN:
                toys |= self.catalog.toys_by_part.get(src.part_id, set())
        return toys


def evaluate(catalog: Catalog, flags: Iterable[ActiveFlag]) -> Exposure:
    flags_by_supplier: dict[str, ActiveFlag] = {}
    for f in flags:
        if f.supplier_id in flags_by_supplier:
            raise ValueError(f"more than one active flag for supplier {f.supplier_id}")
        flags_by_supplier[f.supplier_id] = f

    src_status = {
        (s.part_id, s.factory_id): source_status(s, flags_by_supplier) for s in catalog.sources
    }
    part_status = {
        pid: combine_part_status([src_status[(s.part_id, s.factory_id)] for s in catalog.sources_by_part.get(pid, [])])
        for pid in catalog.parts
    }
    toy_status = {
        tid: worst(part_status[l.part_id] for l in catalog.bom_by_toy.get(tid, []))
        for tid in catalog.toys
    }
    return Exposure(catalog, flags_by_supplier, src_status, part_status, toy_status)
