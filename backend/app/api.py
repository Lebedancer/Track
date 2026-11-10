"""HTTP API. Thin layer: validation + shaping; logic lives in exposure.py."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request

from app.catalog import Catalog, Issue, Severity, ToyListing
from app.exposure import SEVERITY, Exposure, ExposureStatus, evaluate, factory_status
from app.flags import FlagConflict, FlagNotFound, FlagRecord, FlagStore
from app.schemas import (
    BomLineOut,
    DataQualityOut,
    ExposureOut,
    FactoryOut,
    FinisherOut,
    FlagCreate,
    FlagLift,
    FlagOut,
    IssueOut,
    IssueSummary,
    ListingOut,
    SourceOut,
    StatusTotals,
    SupplierDetail,
    SupplierImpact,
    SupplierPartOut,
    SupplierRow,
    SupplierToyOut,
    ToyDetail,
    ToyRow,
    Totals,
)

router = APIRouter(prefix="/api")


# --- helpers -------------------------------------------------------------------

def _catalog(req: Request) -> Catalog:
    return req.app.state.catalog


def _store(req: Request) -> FlagStore:
    return req.app.state.store


def _exposure(req: Request) -> Exposure:
    return evaluate(_catalog(req), [f.to_active() for f in _store(req).active()])


def _not_found(what: str, id_: str) -> HTTPException:
    return HTTPException(404, f"{what} {id_!r} not found")


def _require_finisher(cat: Catalog, fid: str | None, status: int = 404) -> None:
    if fid is not None and fid not in cat.finishers:
        raise HTTPException(status, f"finisher {fid!r} not found")


def _flag_out(f: FlagRecord) -> FlagOut:
    return FlagOut(
        id=f.id, supplier_id=f.supplier_id, scope="factories" if f.factory_ids else "supplier",
        factory_ids=list(f.factory_ids), reason=f.reason, flagged_by=f.flagged_by, created_at=f.created_at,
        active=f.active, lifted_at=f.lifted_at, lifted_by=f.lifted_by, lift_reason=f.lift_reason,
    )


def _finisher_out(cat: Catalog, fid: str) -> FinisherOut:
    f = cat.finishers[fid]
    return FinisherOut(id=f.id, name=f.name, hq_country=f.hq_country, toy_count=len(cat.listings_by_finisher.get(fid, [])))


def _totals(listings: list[ToyListing], cls=Totals, **extra):
    return cls(
        toy_count=len(listings),
        units_per_year=sum(l.units_per_year for l in listings),
        revenue_usd=round(sum(l.revenue_usd for l in listings), 2),
        **extra,
    )


def _toys_using_supplier(cat: Catalog, supplier_id: str) -> dict[str, set[str]]:
    """toy_id -> part_ids sourced (possibly) from this supplier."""
    out: dict[str, set[str]] = {}
    for src in cat.sources_by_supplier.get(supplier_id, []):
        for tid in cat.toys_by_part.get(src.part_id, ()):
            out.setdefault(tid, set()).add(src.part_id)
    return out


def _finisher_toys(cat: Catalog, fid: str | None) -> set[str] | None:
    return None if fid is None else {l.toy_id for l in cat.listings_by_finisher.get(fid, [])}


# --- endpoints -------------------------------------------------------------------

@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/finishers", response_model=list[FinisherOut])
def list_finishers(req: Request):
    cat = _catalog(req)
    return [_finisher_out(cat, fid) for fid in sorted(cat.finishers)]


@router.get("/finishers/{fid}/exposure", response_model=ExposureOut)
def finisher_exposure(fid: str, req: Request):
    cat = _catalog(req)
    _require_finisher(cat, fid)
    ex = _exposure(req)
    listings = cat.listings_by_finisher.get(fid, [])
    by_status = [
        _totals([l for l in listings if ex.toy_status[l.toy_id] == s], StatusTotals, status=s)
        for s in sorted(ExposureStatus, key=SEVERITY.__getitem__, reverse=True)
    ]
    affected = [l for l in listings if ex.toy_status[l.toy_id] != ExposureStatus.CLEAN]
    active = {f.supplier_id: f for f in _store(req).active()}
    impacts = []
    for sid, flag in active.items():
        if sid not in cat.suppliers:
            continue  # orphan flag, reported in data quality
        hit = ex.toys_affected_by_supplier(sid)
        impacts.append(
            _totals([l for l in listings if l.toy_id in hit], SupplierImpact,
                    supplier_id=sid, supplier_name=cat.suppliers[sid].name, flag=_flag_out(flag))
        )
    impacts.sort(key=lambda i: (-i.revenue_usd, i.supplier_id))
    return ExposureOut(
        finisher=_finisher_out(cat, fid), total=_totals(listings), affected=_totals(affected),
        by_status=by_status, suppliers=impacts,
    )


@router.get("/finishers/{fid}/toys", response_model=list[ToyRow])
def finisher_toys(
    fid: str,
    req: Request,
    status: list[ExposureStatus] | None = Query(default=None),
    q: str | None = None,
):
    cat = _catalog(req)
    _require_finisher(cat, fid)
    ex = _exposure(req)
    needle = (q or "").strip().lower()
    rows = []
    for l in cat.listings_by_finisher.get(fid, []):
        toy = cat.toys[l.toy_id]
        st = ex.toy_status[toy.id]
        if status and st not in status:
            continue
        if needle and needle not in toy.id.lower() and needle not in toy.name.lower():
            continue
        bom = cat.bom_by_toy.get(toy.id, [])
        rows.append(ToyRow(
            toy_id=toy.id, name=toy.name, status=st, retail_price_usd=l.retail_price_usd,
            units_per_year=l.units_per_year, revenue_usd=l.revenue_usd, part_count=len(bom),
            affected_part_count=len(ex.affected_lines(toy.id)), has_bom=bool(bom),
            other_finishers=sorted(o.finisher_id for o in cat.listings_by_toy[toy.id] if o.finisher_id != fid),
        ))
    rows.sort(key=lambda r: (-SEVERITY[r.status], -r.revenue_usd, r.toy_id))
    return rows


@router.get("/toys/{tid}", response_model=ToyDetail)
def toy_detail(tid: str, req: Request):
    cat = _catalog(req)
    toy = cat.toys.get(tid)
    if toy is None:
        raise _not_found("toy", tid)
    ex = _exposure(req)
    bom = []
    for line in cat.bom_by_toy.get(tid, []):
        sources = []
        for s in cat.sources_by_part[line.part_id]:
            fac, sup = cat.factories[s.factory_id], cat.suppliers[s.supplier_id]
            st = ex.source_status[(s.part_id, s.factory_id)]
            flag = ex.flags_by_supplier.get(s.supplier_id)
            sources.append(SourceOut(
                factory_id=fac.id, factory_name=fac.name, city=fac.city, country=fac.country,
                supplier_id=sup.id, supplier_name=sup.name, unit_cost_usd=s.unit_cost_usd, status=st,
                flag_id=flag.id if flag else None,
            ))
        bom.append(BomLineOut(
            part_id=line.part_id, part_name=cat.parts[line.part_id].name, quantity=line.quantity,
            status=ex.part_status[line.part_id], sources=sources,
        ))
    bom.sort(key=lambda b: (-SEVERITY[b.status], b.part_id))
    listings = [
        ListingOut(finisher_id=l.finisher_id, finisher_name=cat.finishers[l.finisher_id].name,
                   retail_price_usd=l.retail_price_usd, units_per_year=l.units_per_year, revenue_usd=l.revenue_usd)
        for l in sorted(cat.listings_by_toy.get(tid, []), key=lambda l: l.finisher_id)
    ]
    return ToyDetail(toy_id=tid, name=toy.name, status=ex.toy_status[tid], has_bom=bool(bom), listings=listings, bom=bom)


@router.get("/suppliers", response_model=list[SupplierRow])
def list_suppliers(
    req: Request,
    finisher_id: str | None = None,
    q: str | None = None,
    flagged: bool | None = None,
):
    cat = _catalog(req)
    _require_finisher(cat, finisher_id)
    ex = _exposure(req)
    active = {f.supplier_id: f for f in _store(req).active()}
    scope = _finisher_toys(cat, finisher_id)
    needle = (q or "").strip().lower()
    rows = []
    for sid in sorted(cat.suppliers):
        sup = cat.suppliers[sid]
        if flagged is not None and (sid in active) != flagged:
            continue
        if needle and needle not in sid.lower() and needle not in sup.name.lower():
            continue
        using = set(_toys_using_supplier(cat, sid))
        hit = ex.toys_affected_by_supplier(sid)
        if scope is not None:
            using &= scope
            hit &= scope
        rows.append(SupplierRow(
            id=sid, name=sup.name, hq_country=sup.hq_country,
            factory_count=len(cat.factories_by_supplier.get(sid, [])),
            part_count=len({s.part_id for s in cat.sources_by_supplier.get(sid, [])}),
            toy_count=len(using), affected_toy_count=len(hit),
            active_flag=_flag_out(active[sid]) if sid in active else None,
        ))
    return rows


@router.get("/suppliers/{sid}", response_model=SupplierDetail)
def supplier_detail(sid: str, req: Request, finisher_id: str | None = None):
    cat = _catalog(req)
    sup = cat.suppliers.get(sid)
    if sup is None:
        raise _not_found("supplier", sid)
    _require_finisher(cat, finisher_id)
    ex = _exposure(req)
    flag = next((f for f in _store(req).active() if f.supplier_id == sid), None)
    sources = cat.sources_by_supplier.get(sid, [])
    factories = [
        FactoryOut(
            id=f.id, name=f.name, address_line=f.address_line, city=f.city, country=f.country,
            part_count=sum(1 for s in sources if s.factory_id == f.id),
            status=factory_status(sid, f.id, ex.flags_by_supplier),
        )
        for f in sorted(cat.factories_by_supplier.get(sid, []), key=lambda f: f.id)
    ]
    parts = [
        SupplierPartOut(
            part_id=s.part_id, part_name=cat.parts[s.part_id].name, factory_id=s.factory_id,
            unit_cost_usd=s.unit_cost_usd, source_count=len(cat.sources_by_part[s.part_id]),
            status=ex.part_status[s.part_id],
        )
        for s in sorted(sources, key=lambda s: (s.part_id, s.factory_id))
    ]
    scope = _finisher_toys(cat, finisher_id)
    toys = []
    for tid, via in _toys_using_supplier(cat, sid).items():
        if scope is not None and tid not in scope:
            continue
        toys.append(SupplierToyOut(
            toy_id=tid, name=cat.toys[tid].name, status=ex.toy_status[tid],
            finisher_ids=sorted(l.finisher_id for l in cat.listings_by_toy.get(tid, [])),
            via_parts=sorted(via),
        ))
    toys.sort(key=lambda t: (-SEVERITY[t.status], t.toy_id))
    return SupplierDetail(
        id=sid, name=sup.name, hq_country=sup.hq_country,
        active_flag=_flag_out(flag) if flag else None, factories=factories, parts=parts, toys=toys,
    )


@router.get("/suppliers/{sid}/flags", response_model=list[FlagOut])
def supplier_flags(sid: str, req: Request):
    if sid not in _catalog(req).suppliers:
        raise _not_found("supplier", sid)
    return [_flag_out(f) for f in _store(req).history(sid)]


@router.post("/suppliers/{sid}/flags", response_model=FlagOut, status_code=201)
def create_flag(sid: str, body: FlagCreate, req: Request):
    cat = _catalog(req)
    if sid not in cat.suppliers:
        raise _not_found("supplier", sid)
    _require_finisher(cat, body.flagged_by, status=422)
    if len(set(body.factory_ids)) != len(body.factory_ids):
        raise HTTPException(422, "factory_ids contains duplicates")
    own = {f.id for f in cat.factories_by_supplier.get(sid, [])}
    foreign = [f for f in body.factory_ids if f not in own]
    if foreign:
        raise HTTPException(422, f"factories {foreign} do not belong to supplier {sid!r}")
    try:
        rec = _store(req).create(sid, sorted(body.factory_ids), body.reason, body.flagged_by)
    except FlagConflict as e:
        raise HTTPException(409, str(e)) from None
    return _flag_out(rec)


@router.post("/flags/{flag_id}/lift", response_model=FlagOut)
def lift_flag(flag_id: int, body: FlagLift, req: Request):
    _require_finisher(_catalog(req), body.lifted_by, status=422)
    try:
        rec = _store(req).lift(flag_id, body.reason, body.lifted_by)
    except FlagNotFound:
        raise _not_found("flag", str(flag_id)) from None
    except FlagConflict as e:
        raise HTTPException(409, str(e)) from None
    return _flag_out(rec)


@router.get("/data-quality", response_model=DataQualityOut)
def data_quality(req: Request):
    cat = _catalog(req)
    issues = list(cat.issues)
    for f in _store(req).active():
        if f.supplier_id not in cat.suppliers:
            issues.append(Issue("orphan_flag", Severity.WARNING, "flags", f.supplier_id,
                                f"active flag {f.id} references supplier {f.supplier_id} missing from catalog"))
            continue
        own = {x.id for x in cat.factories_by_supplier.get(f.supplier_id, [])}
        missing = [x for x in f.factory_ids if x not in own]
        if missing:
            issues.append(Issue("orphan_flag", Severity.WARNING, "flags", f.supplier_id,
                                f"active flag {f.id} references factories {missing} missing from catalog"))
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    counts = Counter((i.code, i.severity) for i in issues)
    summary = sorted(
        (IssueSummary(code=c, severity=s, count=n) for (c, s), n in counts.items()),
        key=lambda x: (order[x.severity], x.code),
    )
    issues.sort(key=lambda i: (order[i.severity], i.code, i.entity_id or ""))
    return DataQualityOut(summary=summary, issues=[IssueOut(**i.__dict__) for i in issues])


def create_app(catalog: Catalog, store: FlagStore) -> FastAPI:
    app = FastAPI(title="FairToy Exposure API", version="0.1.0")
    app.state.catalog = catalog
    app.state.store = store
    app.include_router(router)
    return app
