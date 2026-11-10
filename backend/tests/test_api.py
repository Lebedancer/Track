from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.flags import FlagStore
from app.ingest import load_catalog
from tests.builders import make_catalog


@pytest.fixture
def catalog():
    # SUP-A: FAC-A1, FAC-A2 · SUP-B: FAC-B1 · SUP-EMPTY: none
    # P1 <- FAC-A1 ; P2 <- FAC-A2 ; P3 <- FAC-A1 + FAC-B1 ; P4 <- FAC-B1
    return make_catalog(
        finishers=["FIN-1", "FIN-2", "FIN-3"],
        suppliers={"SUP-A": ["FAC-A1", "FAC-A2"], "SUP-B": ["FAC-B1"], "SUP-EMPTY": []},
        sources=[("P1", "FAC-A1"), ("P2", "FAC-A2"), ("P3", "FAC-A1"), ("P3", "FAC-B1"), ("P4", "FAC-B1")],
        toys={"T1": [("P1", 2), ("P4", 1)], "T2": [("P2", 1)], "T3": [("P3", 3)], "T4": [("P4", 1)]},
        listings=[
            ("T1", "FIN-1", 10.0, 100),
            ("T2", "FIN-1", 20.0, 10),
            ("T3", "FIN-1", 5.0, 1000),
            ("T4", "FIN-1", 1.0, 1),
            ("T1", "FIN-2", 12.0, 50),
        ],
    )


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "flags.db"


@pytest.fixture
def client(catalog, db_path):
    return TestClient(create_app(catalog, FlagStore(db_path)))


def flag(client, supplier, **body):
    return client.post(f"/api/suppliers/{supplier}/flags", json=body)


# --- reads ------------------------------------------------------------------

def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_finishers(client):
    rows = client.get("/api/finishers").json()
    assert [(r["id"], r["toy_count"]) for r in rows] == [("FIN-1", 4), ("FIN-2", 1), ("FIN-3", 0)]


def test_toys_of_finisher_all_clean(client):
    rows = client.get("/api/finishers/FIN-1/toys").json()
    assert {r["toy_id"]: r["status"] for r in rows} == {"T1": "clean", "T2": "clean", "T3": "clean", "T4": "clean"}
    t1 = next(r for r in rows if r["toy_id"] == "T1")
    assert t1["revenue_usd"] == 1000.0
    assert t1["other_finishers"] == ["FIN-2"]
    assert t1["part_count"] == 2


def test_finisher_without_toys(client):
    assert client.get("/api/finishers/FIN-3/toys").json() == []
    ex = client.get("/api/finishers/FIN-3/exposure").json()
    assert ex["affected"]["toy_count"] == 0


def test_unknown_finisher_404(client):
    assert client.get("/api/finishers/NOPE/toys").status_code == 404
    assert client.get("/api/finishers/NOPE/exposure").status_code == 404
    assert client.get("/api/suppliers?finisher_id=NOPE").status_code == 404


def test_unknown_toy_and_supplier_404(client):
    assert client.get("/api/toys/NOPE").status_code == 404
    assert client.get("/api/suppliers/NOPE").status_code == 404
    assert client.get("/api/suppliers/NOPE/flags").status_code == 404
    assert flag(client, "NOPE").status_code == 404


# --- flag -> trace ----------------------------------------------------------

def test_flag_whole_supplier_and_trace(client):
    r = flag(client, "SUP-A", reason="NGO audit", flagged_by="FIN-1")
    assert r.status_code == 201
    f = r.json()
    assert f["scope"] == "supplier" and f["active"] and f["factory_ids"] == []

    rows = {r["toy_id"]: r["status"] for r in client.get("/api/finishers/FIN-1/toys").json()}
    assert rows == {"T1": "confirmed", "T2": "confirmed", "T3": "potential", "T4": "clean"}

    detail = client.get("/api/toys/T3").json()
    line = detail["bom"][0]
    assert line["part_id"] == "P3" and line["status"] == "potential"
    by_factory = {s["factory_id"]: (s["status"], s["supplier_id"], s["flag_id"]) for s in line["sources"]}
    assert by_factory == {"FAC-A1": ("flagged", "SUP-A", f["id"]), "FAC-B1": ("clean", "SUP-B", None)}


def test_status_filter_and_search(client):
    flag(client, "SUP-A")
    rows = client.get("/api/finishers/FIN-1/toys?status=confirmed&status=potential").json()
    assert {r["toy_id"] for r in rows} == {"T1", "T2", "T3"}
    rows = client.get("/api/finishers/FIN-1/toys?q=t3").json()
    assert [r["toy_id"] for r in rows] == ["T3"]
    assert client.get("/api/finishers/FIN-1/toys?status=bogus").status_code == 422


def test_toy_detail_bom_sorted_by_severity(client):
    flag(client, "SUP-B")
    bom = client.get("/api/toys/T1").json()["bom"]
    assert [(l["part_id"], l["status"]) for l in bom] == [("P4", "confirmed"), ("P1", "clean")]


def test_factory_scoped_flag(client):
    r = flag(client, "SUP-A", factory_ids=["FAC-A1"])
    assert r.json()["scope"] == "factories"
    rows = {r["toy_id"]: r["status"] for r in client.get("/api/finishers/FIN-1/toys").json()}
    assert rows["T2"] == "supplier_risk"
    sup = client.get("/api/suppliers/SUP-A").json()
    assert {f["id"]: f["status"] for f in sup["factories"]} == {"FAC-A1": "flagged", "FAC-A2": "supplier_risk"}


def test_exposure_summary(client):
    flag(client, "SUP-A")
    ex = client.get("/api/finishers/FIN-1/exposure").json()
    by = {s["status"]: s for s in ex["by_status"]}
    assert by["confirmed"]["toy_count"] == 2
    assert by["confirmed"]["revenue_usd"] == 1000.0 + 200.0
    assert by["potential"]["units_per_year"] == 1000
    assert ex["affected"]["toy_count"] == 3
    assert ex["total"]["toy_count"] == 4
    [imp] = ex["suppliers"]
    assert (imp["supplier_id"], imp["toy_count"]) == ("SUP-A", 3)


def test_shared_toy_visible_to_both_finishers(client):
    flag(client, "SUP-B")
    rows = client.get("/api/finishers/FIN-2/toys").json()
    assert [(r["toy_id"], r["status"], r["revenue_usd"]) for r in rows] == [("T1", "confirmed", 600.0)]


def test_suppliers_list(client):
    flag(client, "SUP-A")
    rows = {r["id"]: r for r in client.get("/api/suppliers?finisher_id=FIN-2").json()}
    assert rows["SUP-A"]["active_flag"]["scope"] == "supplier"
    assert rows["SUP-A"]["toy_count"] == 1  # FIN-2 only sells T1
    assert rows["SUP-EMPTY"]["factory_count"] == 0
    flagged = client.get("/api/suppliers?flagged=true").json()
    assert [r["id"] for r in flagged] == ["SUP-A"]
    assert [r["id"] for r in client.get("/api/suppliers?q=empty").json()] == ["SUP-EMPTY"]


def test_supplier_detail_toys_filtered_by_finisher(client):
    sup = client.get("/api/suppliers/SUP-B?finisher_id=FIN-2").json()
    assert [t["toy_id"] for t in sup["toys"]] == ["T1"]
    assert sup["toys"][0]["via_parts"] == ["P4"]
    all_ = client.get("/api/suppliers/SUP-B").json()
    assert {t["toy_id"] for t in all_["toys"]} == {"T1", "T3", "T4"}


# --- flag lifecycle & validation ---------------------------------------------

def test_supplier_without_factories_can_be_flagged(client):
    assert flag(client, "SUP-EMPTY").status_code == 201
    assert client.get("/api/finishers/FIN-1/exposure").json()["affected"]["toy_count"] == 0


def test_second_active_flag_conflict(client):
    assert flag(client, "SUP-A").status_code == 201
    assert flag(client, "SUP-A").status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"factory_ids": ["FAC-B1"]},  # other supplier's factory
        {"factory_ids": ["FAC-ZZ"]},  # unknown factory
        {"factory_ids": ["FAC-A1", "FAC-A1"]},  # duplicate
        {"flagged_by": "FIN-NOPE"},
        {"reason": "x" * 1001},
    ],
)
def test_flag_validation(client, body):
    assert flag(client, "SUP-A", **body).status_code == 422


def test_factory_ids_for_supplier_without_factories(client):
    assert flag(client, "SUP-EMPTY", factory_ids=["FAC-A1"]).status_code == 422


def test_blank_reason_normalised_to_null(client):
    assert flag(client, "SUP-A", reason="   ").json()["reason"] is None


def test_lift_and_history(client):
    f1 = flag(client, "SUP-A", reason="first").json()
    r = client.post(f"/api/flags/{f1['id']}/lift", json={"reason": "remediated", "lifted_by": "FIN-1"})
    assert r.status_code == 200 and r.json()["active"] is False and r.json()["lift_reason"] == "remediated"
    assert client.post(f"/api/flags/{f1['id']}/lift", json={}).status_code == 409
    assert client.post("/api/flags/9999/lift", json={}).status_code == 404
    assert client.post(f"/api/flags/{f1['id']}/lift", json={"lifted_by": "NOPE"}).status_code == 422

    rows = {r["toy_id"]: r["status"] for r in client.get("/api/finishers/FIN-1/toys").json()}
    assert set(rows.values()) == {"clean"}

    f2 = flag(client, "SUP-A", factory_ids=["FAC-A2"], reason="second").json()
    hist = client.get("/api/suppliers/SUP-A/flags").json()
    assert [h["id"] for h in hist] == [f2["id"], f1["id"]]
    assert [h["active"] for h in hist] == [True, False]


def test_flags_persist_across_restart(catalog, db_path):
    c1 = TestClient(create_app(catalog, FlagStore(db_path)))
    flag(c1, "SUP-A")
    c2 = TestClient(create_app(catalog, FlagStore(db_path)))
    assert c2.get("/api/suppliers/SUP-A").json()["active_flag"] is not None


# --- data quality -------------------------------------------------------------

def test_orphan_flag_reported(tmp_path, db_path):
    full = make_catalog(suppliers={"SUP-A": ["FAC-A1"], "SUP-B": ["FAC-B1"]}, sources=[("P1", "FAC-A1")], toys={"T1": [("P1", 1)]})
    c1 = TestClient(create_app(full, FlagStore(db_path)))
    flag(c1, "SUP-B")
    flag(c1, "SUP-A", factory_ids=["FAC-A1"])

    reduced = make_catalog(suppliers={"SUP-A": []}, sources=[], toys={})
    c2 = TestClient(create_app(reduced, FlagStore(db_path)))
    dq = c2.get("/api/data-quality").json()
    orphans = {i["entity_id"] for i in dq["issues"] if i["code"] == "orphan_flag"}
    assert orphans == {"SUP-B", "SUP-A"}
    # app still works with the orphan flag present
    assert c2.get("/api/suppliers").status_code == 200


def test_data_quality_real_dataset(db_path):
    data = Path(__file__).resolve().parents[2] / "data"
    client = TestClient(create_app(load_catalog(data), FlagStore(db_path)))
    dq = client.get("/api/data-quality").json()
    summary = {(s["code"], s["severity"]): s["count"] for s in dq["summary"]}
    assert summary[("multi_sourced_part", "info")] == 22
    assert summary[("multi_listed_toy", "info")] == 5


def test_real_dataset_end_to_end(db_path):
    data = Path(__file__).resolve().parents[2] / "data"
    client = TestClient(create_app(load_catalog(data), FlagStore(db_path)))
    # PRT-0235 is multi-sourced: SUP-022/FAC-0104 and SUP-002/FAC-0008
    assert flag(client, "SUP-022", factory_ids=["FAC-0104"]).status_code == 201
    toys = [t for fin in client.get("/api/finishers").json()
            for t in client.get(f"/api/finishers/{fin['id']}/toys").json()]
    using = [t for t in toys if t["status"] != "clean"]
    assert using
    detail = client.get(f"/api/toys/{using[0]['toy_id']}").json()
    affected = [l for l in detail["bom"] if l["status"] != "clean"]
    assert affected
    assert any(s["supplier_id"] == "SUP-022" and s["status"] == "flagged" for l in affected for s in l["sources"])
