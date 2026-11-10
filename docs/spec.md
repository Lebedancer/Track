# FairToy Child-Labour Exposure — Specification

Status: draft v1 · 2026-11-07

## 1. Goal

A Finisher (toy brand) can:

1. See their toys and how toys relate to parts, factories and suppliers.
2. Flag a supplier as using child labour — the whole supplier, or only specific factories of it.
3. See which of their toys are affected, with the trace toy → part → factory → flagged supplier.

Extras in scope: exposure metrics (units/year, revenue at risk), clean alternative sources for
multi-sourced parts, flag history (audit trail), data-quality report.

Out of scope: auth, multi-tenancy, notifications, real-time updates, deployment infra beyond Docker Compose.

## 2. Regulatory framing (why the model looks like this)

- **CSDDD (EU 2024/1760)** and national laws (e.g. German LkSG) attach due-diligence duties to the
  **business partner** — the supplier legal entity. Remediation, contract action and responsible
  disengagement happen at supplier level.
- **Forced Labour Regulation (EU 2024/3015)** acts on **products**; an operator can show its product
  did not come from the implicated production site. That makes **site (factory) traceability** valuable.
- In practice factory-level traceability is often incomplete (order shifting, subcontracting), so the
  default assumption is "whole supplier is at risk".

Hence: a flag is placed on a **supplier**; it may optionally be **narrowed to specific factories**.

## 3. Source data and findings

Six CSVs in `data/` (`finishers`, `suppliers`, `factories`, `parts`, `toys`, `bill_of_materials`).
No broken foreign keys, no whitespace issues, quantities are integers 1–12, BOM is flat (no sub-assemblies).

| # | Finding | Count | Interpretation / handling |
|---|---|---|---|
| D1 | `part_id` appears on 2 rows with different supplier/factory/cost | 22 parts | **Multi-sourced part**: one logical part, several sources. BOM does not say which source was used. |
| D2 | `toy_id` appears on 2 rows with different finisher/price/volume | 5 toys | **Same product sold by two finishers** (shared BOM, per-finisher price & volume). |
| D3 | Supplier with no factories and no parts | 1 (SUP-038) | Valid entity; flaggable; zero exposure. |
| D4 | Different factories sharing the same name (same supplier, different address) | 26 names, 53 factories | Always display factory id next to name. |
| D5 | Factory with empty `address_line` / `city` | 6 | Stored as null, shown as "unknown". |
| D6 | Similar supplier names (`Keyuan Works` / `Keyuan Fabrication`) | 14 groups | Treated as distinct legal entities (distinct ids). Not merged. |
| D7 | Supplier HQ country ≠ factory country | 219 / 232 | Expected; both shown. |

## 4. Domain model (normalised)

```
finisher(id, name, hq_country)
supplier(id, name, hq_country)
factory(id, supplier_id → supplier, name, address_line?, city?, country)
part(id, name)
part_source(part_id → part, factory_id → factory, unit_cost_usd)      PK(part_id, factory_id)
toy(id, name)
toy_listing(toy_id → toy, finisher_id → finisher, retail_price_usd, units_per_year)
                                                                      PK(toy_id, finisher_id)
bom_line(toy_id → toy, part_id → part, quantity > 0)                  PK(toy_id, part_id)

supplier_flag(id, supplier_id, reason?, flagged_by_finisher_id?, created_at,
              lifted_at?, lifted_by_finisher_id?, lift_reason?)
supplier_flag_factory(flag_id → supplier_flag, factory_id → factory)  -- empty set = whole supplier
```

- `part_source` stores only `factory_id`; supplier is derived via `factory.supplier_id`
  (the CSV's `parts.supplier_id` is redundant and only validated at ingest).
- At most **one active flag per supplier** (active = `lifted_at IS NULL`), enforced by a partial unique index.
- Flags are **global** (a fact about the supplier), visible to all finishers; the acting finisher is recorded.

## 5. Storage & ingestion

- **Catalog** (everything from CSV) is read-only. Loaded from CSV at startup into an immutable
  in-memory model. CSV stays the source of truth; restart = fresh deterministic import.
- **Flags** are the only mutable state → **SQLite** file on a Docker volume; survive restarts.
- Flags referencing a supplier/factory no longer present in the catalog are kept and reported as
  data-quality issues (`orphan_flag`), not deleted.

Ingest rules (each violation → a data-quality issue with severity, entity, id, message):

| Rule | Action |
|---|---|
| Read as UTF-8 with optional BOM; trim all fields; empty string → null | normalise |
| Required field missing / non-numeric number / quantity ≤ 0 / negative price | skip row, `error` |
| FK to unknown entity | skip row, `error` |
| `parts.supplier_id` ≠ `factory.supplier_id` | keep row, trust factory, `warning` |
| Same part id, different names across sources | keep first name, `warning` |
| Same toy id, different names across listings | keep first name, `warning` |
| Exact duplicate `(part_id, factory_id)` / `(toy_id, finisher_id)` / `(toy_id, part_id)` | keep first, `warning` |
| Multi-sourced part (D1), multi-listed toy (D2), supplier without factories (D3), missing address (D5) | keep, `info` |
| Toy without BOM / part not used in any BOM | keep, `info` |

## 6. Exposure rules

Evaluated against the set of **active** flags.

**Source status** (per `part_source`):

| Status | Condition |
|---|---|
| `flagged` | supplier has an active flag that is whole-supplier, or lists this source's factory |
| `supplier_risk` | supplier has an active factory-scoped flag that does **not** list this factory |
| `clean` | supplier has no active flag |

**Part status** (over all sources of the part; `n` = number of sources, `f` = flagged sources):

| Status | Condition | Meaning |
|---|---|---|
| `confirmed` | `f = n` | whichever source was used, it is flagged |
| `potential` | `0 < f < n` | may come from a flagged source; BOM does not say which |
| `supplier_risk` | `f = 0`, some source `supplier_risk` | from a flagged supplier, but a non-flagged factory |
| `clean` | otherwise | |

Severity order: `confirmed > potential > supplier_risk > clean`.

**Toy status** = most severe part status in its BOM. Each non-clean part contributes a **trace**:
`toy → part (qty) → factory → supplier (+ flag)`, plus its clean alternative sources, if any.

**Metrics** per toy listing: `units_per_year`, `revenue_usd = retail_price_usd × units_per_year`.
Per finisher: count, units and revenue grouped by toy status; per flagged supplier: affected
toy count/revenue for that finisher.

The exposure engine is a pure function `(catalog, active_flags) → result`, unit-tested in isolation.

## 7. API (FastAPI, JSON, prefix `/api`)

| Method & path | Purpose |
|---|---|
| `GET /finishers` | list finishers with toy counts |
| `GET /finishers/{fid}/exposure` | summary by status (count, units, revenue) + per flagged supplier impact |
| `GET /finishers/{fid}/toys?status=&q=` | finisher's toy listings with status, part count, metrics |
| `GET /toys/{tid}` | toy detail: listings (all finishers), BOM lines with sources & statuses (the trace), most severe first |
| `GET /suppliers?finisher_id=&q=&flagged=` | suppliers with factory/part counts, active flag, # finisher toys using them / affected via them |
| `GET /suppliers/{sid}?finisher_id=` | supplier detail: factories with status, parts supplied, active flag, toys using it (scoped to finisher if given) |
| `GET /suppliers/{sid}/flags` | flag history (active + lifted) |
| `POST /suppliers/{sid}/flags` | body `{reason?, factory_ids?: [], flagged_by?}` → create active flag |
| `POST /flags/{flag_id}/lift` | body `{reason?, lifted_by?}` → lift active flag |
| `GET /data-quality` | ingest issues + orphan flags, with counts by code/severity |
| `GET /health` | liveness |

Errors (`{"detail": ...}`):

| Case | Code |
|---|---|
| unknown finisher / toy / supplier / flag | 404 |
| supplier already has an active flag | 409 |
| lifting an already lifted flag | 409 |
| `factory_ids` contains a factory not belonging to the supplier, or duplicates | 422 |
| `factory_ids` given for a supplier with no factories | 422 |
| `flagged_by` / `lifted_by` not a known finisher | 422 |
| reason longer than 1000 chars | 422 |

Changing a flag's scope = lift + create new (keeps history honest).

## 8. Frontend (React + Vite + TypeScript)

- **Server is the source of truth.** Server data via TanStack Query; after flag/lift mutations,
  related queries are invalidated. UI state (selected finisher, filters) lives in the URL.
  No Redux/Zustand.
- Pages:
  - **Header**: finisher selector (persisted in URL `?finisher=`).
  - **Overview**: KPI cards by status (toys, units, revenue at risk), table of affected toys,
    impact by flagged supplier.
  - **Toys**: searchable/filterable list → **Toy detail**: BOM table, each line expandable into
    sources with status badges and the trace path; clean alternatives highlighted.
  - **Suppliers**: list with flag status → **Supplier detail**: factories, flag form
    (whole supplier / select factories, reason), lift action, flag history, affected toys of the
    current finisher.
  - **Data quality**: issues grouped by code/severity.
- Empty states: finisher with no toys, supplier with no factories, no active flags.
- Status shown with text + colour (not colour only).

## 9. Delivery

```
backend/   FastAPI app, ingest, exposure engine, tests (pytest)
frontend/  React app
data/      source CSVs
docs/      this spec
docker-compose.yml   api (uvicorn) + web (nginx serving build, proxy /api) ; volume for SQLite
README.md  how to run (Docker and local dev)
```

`docker compose up` → http://localhost:8080.

## 10. Testing

- Exposure engine: unit tests for every row of the status tables (single/multi source,
  whole/factory-scoped flags, lifted flags, supplier without factories).
- Ingest: fixture CSVs covering every rule in §5.
- API: happy paths + every error in §7.
- Smoke test against the real dataset (counts match §3 findings).

## 11. Next steps (if time runs out)

- Flag evidence attachments and severity levels; expiry/re-audit dates.
- Per-finisher actual sourcing data (which source was used) to resolve `potential`.
- What-if simulation: "switch part X to source Y" and see exposure drop.
- Sub-tier suppliers (multi-level BOM) with recursive trace.
- Export of affected toys (CSV) for compliance reporting.
