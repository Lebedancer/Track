"""Read-only catalog: normalised domain model built from the source CSVs.

The catalog is immutable after load. Mutable state (flags) lives elsewhere.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True)
class Finisher:
    id: str
    name: str
    hq_country: str | None


@dataclass(frozen=True)
class Supplier:
    id: str
    name: str
    hq_country: str | None


@dataclass(frozen=True)
class Factory:
    id: str
    supplier_id: str
    name: str
    address_line: str | None
    city: str | None
    country: str | None


@dataclass(frozen=True)
class Part:
    id: str
    name: str


@dataclass(frozen=True)
class PartSource:
    """One place a part can come from. Supplier is derived from the factory."""

    part_id: str
    factory_id: str
    supplier_id: str
    unit_cost_usd: float


@dataclass(frozen=True)
class Toy:
    id: str
    name: str


@dataclass(frozen=True)
class ToyListing:
    """A toy as sold by one finisher (the same toy may be sold by several)."""

    toy_id: str
    finisher_id: str
    retail_price_usd: float
    units_per_year: int

    @property
    def revenue_usd(self) -> float:
        return round(self.retail_price_usd * self.units_per_year, 2)


@dataclass(frozen=True)
class BomLine:
    toy_id: str
    part_id: str
    quantity: int


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    entity: str
    entity_id: str | None
    message: str


@dataclass
class Catalog:
    finishers: dict[str, Finisher] = field(default_factory=dict)
    suppliers: dict[str, Supplier] = field(default_factory=dict)
    factories: dict[str, Factory] = field(default_factory=dict)
    parts: dict[str, Part] = field(default_factory=dict)
    toys: dict[str, Toy] = field(default_factory=dict)
    sources: list[PartSource] = field(default_factory=list)
    listings: list[ToyListing] = field(default_factory=list)
    bom: list[BomLine] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    # Indexes, filled by build_indexes()
    sources_by_part: dict[str, list[PartSource]] = field(default_factory=dict)
    sources_by_supplier: dict[str, list[PartSource]] = field(default_factory=dict)
    factories_by_supplier: dict[str, list[Factory]] = field(default_factory=dict)
    listings_by_finisher: dict[str, list[ToyListing]] = field(default_factory=dict)
    listings_by_toy: dict[str, list[ToyListing]] = field(default_factory=dict)
    bom_by_toy: dict[str, list[BomLine]] = field(default_factory=dict)
    toys_by_part: dict[str, set[str]] = field(default_factory=dict)

    def build_indexes(self) -> "Catalog":
        def group(items, key):
            out: dict = defaultdict(list)
            for it in items:
                out[key(it)].append(it)
            return dict(out)

        self.sources_by_part = group(self.sources, lambda s: s.part_id)
        self.sources_by_supplier = group(self.sources, lambda s: s.supplier_id)
        self.factories_by_supplier = group(self.factories.values(), lambda f: f.supplier_id)
        self.listings_by_finisher = group(self.listings, lambda l: l.finisher_id)
        self.listings_by_toy = group(self.listings, lambda l: l.toy_id)
        self.bom_by_toy = group(self.bom, lambda b: b.toy_id)
        toys_by_part: dict[str, set[str]] = defaultdict(set)
        for line in self.bom:
            toys_by_part[line.part_id].add(line.toy_id)
        self.toys_by_part = dict(toys_by_part)
        return self
