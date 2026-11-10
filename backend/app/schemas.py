"""API request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.catalog import Severity
from app.exposure import ExposureStatus, SourceStatus


class FinisherOut(BaseModel):
    id: str
    name: str
    hq_country: str | None
    toy_count: int


class FlagOut(BaseModel):
    id: int
    supplier_id: str
    scope: Literal["supplier", "factories"]
    factory_ids: list[str]
    reason: str | None
    flagged_by: str | None
    created_at: str
    active: bool
    lifted_at: str | None
    lifted_by: str | None
    lift_reason: str | None


def _blank_to_none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


class FlagCreate(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
    factory_ids: list[str] = Field(default_factory=list)
    flagged_by: str | None = None

    _norm = field_validator("reason", "flagged_by")(_blank_to_none)


class FlagLift(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
    lifted_by: str | None = None

    _norm = field_validator("reason", "lifted_by")(_blank_to_none)


class Totals(BaseModel):
    toy_count: int = 0
    units_per_year: int = 0
    revenue_usd: float = 0.0


class StatusTotals(Totals):
    status: ExposureStatus


class SupplierImpact(Totals):
    supplier_id: str
    supplier_name: str
    flag: FlagOut


class ExposureOut(BaseModel):
    finisher: FinisherOut
    total: Totals
    affected: Totals
    by_status: list[StatusTotals]
    suppliers: list[SupplierImpact]


class ToyRow(BaseModel):
    toy_id: str
    name: str
    status: ExposureStatus
    retail_price_usd: float
    units_per_year: int
    revenue_usd: float
    part_count: int
    affected_part_count: int
    has_bom: bool
    other_finishers: list[str]


class ListingOut(BaseModel):
    finisher_id: str
    finisher_name: str
    retail_price_usd: float
    units_per_year: int
    revenue_usd: float


class SourceOut(BaseModel):
    factory_id: str
    factory_name: str
    city: str | None
    country: str | None
    supplier_id: str
    supplier_name: str
    unit_cost_usd: float
    status: SourceStatus
    flag_id: int | None


class BomLineOut(BaseModel):
    part_id: str
    part_name: str
    quantity: int
    status: ExposureStatus
    sources: list[SourceOut]


class ToyDetail(BaseModel):
    toy_id: str
    name: str
    status: ExposureStatus
    has_bom: bool
    listings: list[ListingOut]
    bom: list[BomLineOut]


class SupplierRow(BaseModel):
    id: str
    name: str
    hq_country: str | None
    factory_count: int
    part_count: int
    toy_count: int
    affected_toy_count: int
    active_flag: FlagOut | None


class FactoryOut(BaseModel):
    id: str
    name: str
    address_line: str | None
    city: str | None
    country: str | None
    part_count: int
    status: SourceStatus


class SupplierPartOut(BaseModel):
    part_id: str
    part_name: str
    factory_id: str
    unit_cost_usd: float
    source_count: int
    status: ExposureStatus


class SupplierToyOut(BaseModel):
    toy_id: str
    name: str
    status: ExposureStatus
    finisher_ids: list[str]
    via_parts: list[str]


class SupplierDetail(BaseModel):
    id: str
    name: str
    hq_country: str | None
    active_flag: FlagOut | None
    factories: list[FactoryOut]
    parts: list[SupplierPartOut]
    toys: list[SupplierToyOut]


class IssueOut(BaseModel):
    code: str
    severity: Severity
    entity: str
    entity_id: str | None
    message: str


class IssueSummary(BaseModel):
    code: str
    severity: Severity
    count: int


class DataQualityOut(BaseModel):
    summary: list[IssueSummary]
    issues: list[IssueOut]
