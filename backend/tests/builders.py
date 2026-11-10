"""Tiny helpers to build in-memory catalogs for tests."""

from app.catalog import (
    BomLine,
    Catalog,
    Factory,
    Finisher,
    Part,
    PartSource,
    Supplier,
    Toy,
    ToyListing,
)


def make_catalog(
    *,
    suppliers: dict[str, list[str]],
    sources: list[tuple[str, str]],
    toys: dict[str, list[tuple[str, int]]],
    finishers: list[str] = ("FIN-1",),
    listings: list[tuple[str, str, float, int]] | None = None,
) -> Catalog:
    """
    suppliers: {supplier_id: [factory_id, ...]}
    sources:   [(part_id, factory_id), ...]
    toys:      {toy_id: [(part_id, qty), ...]}
    listings:  [(toy_id, finisher_id, price, units)], default: every toy sold by first finisher
    """
    c = Catalog()
    for fid in finishers:
        c.finishers[fid] = Finisher(fid, f"Finisher {fid}", "DE")
    for sid, facs in suppliers.items():
        c.suppliers[sid] = Supplier(sid, f"Supplier {sid}", "CN")
        for fac in facs:
            c.factories[fac] = Factory(fac, sid, f"Factory {fac}", None, None, "CN")
    for pid, fac in sources:
        c.parts.setdefault(pid, Part(pid, f"Part {pid}"))
        c.sources.append(PartSource(pid, fac, c.factories[fac].supplier_id, 1.0))
    for tid, lines in toys.items():
        c.toys[tid] = Toy(tid, f"Toy {tid}")
        for pid, qty in lines:
            c.bom.append(BomLine(tid, pid, qty))
    if listings is None:
        listings = [(tid, finishers[0], 10.0, 100) for tid in toys]
    for tid, fid, price, units in listings:
        c.listings.append(ToyListing(tid, fid, price, units))
    return c.build_indexes()
