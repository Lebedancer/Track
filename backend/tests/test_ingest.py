from pathlib import Path

import pytest

from app.ingest import IngestError, load_catalog

HEADERS = {
    "finishers": "finisher_id,finisher_name,hq_country",
    "suppliers": "supplier_id,supplier_name,hq_country",
    "factories": "factory_id,supplier_id,factory_name,address_line,city,country",
    "parts": "part_id,part_name,supplier_id,factory_id,unit_cost_usd",
    "toys": "toy_id,toy_name,finisher_id,retail_price_usd,units_per_year",
    "bill_of_materials": "toy_id,part_id,quantity",
}

BASE = {
    "finishers": ["FIN-1,Fin One,UK", "FIN-2,Fin Two,DE"],
    "suppliers": ["SUP-1,Sup One,CN", "SUP-2,Sup Two,IN"],
    "factories": ["FAC-1,SUP-1,F1,1 Rd,Shenzhen,China", "FAC-2,SUP-2,F2,2 Rd,Delhi,India"],
    "parts": ["PRT-1,wheel,SUP-1,FAC-1,1.5"],
    "toys": ["TOY-1,Car,FIN-1,10,100"],
    "bill_of_materials": ["TOY-1,PRT-1,4"],
}


def write(tmp_path: Path, **overrides: list[str]) -> Path:
    for name, header in HEADERS.items():
        rows = overrides.get(name, BASE[name])
        (tmp_path / f"{name}.csv").write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return tmp_path


def codes(cat):
    return {(i.code, i.entity_id) for i in cat.issues}


def test_happy_path(tmp_path):
    cat = load_catalog(write(tmp_path))
    assert set(cat.finishers) == {"FIN-1", "FIN-2"}
    assert cat.sources[0].supplier_id == "SUP-1"
    assert cat.listings[0].revenue_usd == 1000.0
    assert cat.bom[0].quantity == 4


def test_utf8_bom_whitespace_and_empty_to_null(tmp_path):
    write(tmp_path, factories=["  FAC-1 , SUP-1 , F1 ,, ,China", "FAC-2,SUP-2,F2,2 Rd,Delhi,India"])
    p = tmp_path / "finishers.csv"
    p.write_bytes("﻿".encode() + p.read_bytes())
    cat = load_catalog(tmp_path)
    assert "FIN-1" in cat.finishers
    f = cat.factories["FAC-1"]
    assert (f.name, f.address_line, f.city) == ("F1", None, None)
    assert ("missing_address", "FAC-1") in codes(cat)


def test_missing_file_is_fatal(tmp_path):
    write(tmp_path)
    (tmp_path / "toys.csv").unlink()
    with pytest.raises(IngestError):
        load_catalog(tmp_path)


def test_missing_column_is_fatal(tmp_path):
    write(tmp_path)
    (tmp_path / "toys.csv").write_text("toy_id,toy_name\nTOY-1,Car\n")
    with pytest.raises(IngestError):
        load_catalog(tmp_path)


def test_extra_columns_ignored_and_header_case_insensitive(tmp_path):
    write(tmp_path)
    (tmp_path / "suppliers.csv").write_text("Supplier_ID,SUPPLIER_NAME,hq_country,extra\nSUP-1,S,CN,x\nSUP-2,T,IN,y\n")
    cat = load_catalog(tmp_path)
    assert set(cat.suppliers) == {"SUP-1", "SUP-2"}


@pytest.mark.parametrize(
    "toys_row, code",
    [
        ("TOY-1,,FIN-1,10,100", "missing_field"),
        ("TOY-1,Car,FIN-1,abc,100", "invalid_number"),
        ("TOY-1,Car,FIN-1,-1,100", "invalid_number"),
        ("TOY-1,Car,FIN-1,10,1.5", "invalid_number"),
        ("TOY-1,Car,FIN-1,nan,100", "invalid_number"),
        ("TOY-1,Car,FIN-9,10,100", "unknown_reference"),
    ],
)
def test_invalid_toy_rows_skipped(tmp_path, toys_row, code):
    cat = load_catalog(write(tmp_path, toys=[toys_row]))
    assert cat.listings == []
    assert any(i.code == code and i.severity == "error" for i in cat.issues)
    # dependent BOM line now references an unknown toy -> skipped as well
    assert cat.bom == []


@pytest.mark.parametrize("qty", ["0", "-2", "x", "2.5"])
def test_invalid_quantity_skipped(tmp_path, qty):
    cat = load_catalog(write(tmp_path, bill_of_materials=[f"TOY-1,PRT-1,{qty}"]))
    assert cat.bom == []
    assert ("invalid_number", "TOY-1/PRT-1") in codes(cat)


def test_integer_valued_float_quantity_accepted(tmp_path):
    cat = load_catalog(write(tmp_path, bill_of_materials=["TOY-1,PRT-1,4.0"]))
    assert cat.bom[0].quantity == 4


def test_unknown_references_skipped(tmp_path):
    cat = load_catalog(
        write(
            tmp_path,
            factories=["FAC-1,SUP-1,F1,1 Rd,S,China", "FAC-X,SUP-9,FX,1 Rd,S,China"],
            parts=["PRT-1,wheel,SUP-1,FAC-1,1.5", "PRT-2,axle,SUP-1,FAC-9,1"],
            bill_of_materials=["TOY-1,PRT-1,4", "TOY-1,PRT-9,1", "TOY-9,PRT-1,1"],
        )
    )
    assert "FAC-X" not in cat.factories
    assert "PRT-2" not in cat.parts
    assert len(cat.bom) == 1
    unknown = {i.entity_id for i in cat.issues if i.code == "unknown_reference"}
    assert unknown == {"FAC-X", "PRT-2", "TOY-1/PRT-9", "TOY-9/PRT-1"}


def test_part_supplier_mismatch_trusts_factory(tmp_path):
    cat = load_catalog(write(tmp_path, parts=["PRT-1,wheel,SUP-2,FAC-1,1.5"]))
    assert cat.sources[0].supplier_id == "SUP-1"
    assert ("supplier_factory_mismatch", "PRT-1") in codes(cat)


def test_part_supplier_column_may_be_empty(tmp_path):
    cat = load_catalog(write(tmp_path, parts=["PRT-1,wheel,,FAC-1,1.5"]))
    assert cat.sources[0].supplier_id == "SUP-1"


def test_multi_sourced_part(tmp_path):
    cat = load_catalog(write(tmp_path, parts=["PRT-1,wheel,SUP-1,FAC-1,1.5", "PRT-1,wheel,SUP-2,FAC-2,1.4"]))
    assert len(cat.sources_by_part["PRT-1"]) == 2
    assert ("multi_sourced_part", "PRT-1") in codes(cat)


def test_conflicting_part_name_keeps_first(tmp_path):
    cat = load_catalog(write(tmp_path, parts=["PRT-1,wheel,SUP-1,FAC-1,1.5", "PRT-1,tyre,SUP-2,FAC-2,1.4"]))
    assert cat.parts["PRT-1"].name == "wheel"
    assert ("conflicting_name", "PRT-1") in codes(cat)


def test_duplicate_source_keeps_first(tmp_path):
    cat = load_catalog(write(tmp_path, parts=["PRT-1,wheel,SUP-1,FAC-1,1.5", "PRT-1,wheel,SUP-1,FAC-1,9"]))
    assert len(cat.sources) == 1 and cat.sources[0].unit_cost_usd == 1.5
    assert ("duplicate_row", "PRT-1/FAC-1") in codes(cat)


def test_duplicate_entity_id_keeps_first(tmp_path):
    cat = load_catalog(write(tmp_path, suppliers=["SUP-1,Sup One,CN", "SUP-1,Other,IN", "SUP-2,Sup Two,IN"]))
    assert cat.suppliers["SUP-1"].name == "Sup One"
    assert ("duplicate_row", "SUP-1") in codes(cat)


def test_toy_sold_by_two_finishers(tmp_path):
    cat = load_catalog(write(tmp_path, toys=["TOY-1,Car,FIN-1,10,100", "TOY-1,Car,FIN-2,12,50"]))
    assert len(cat.toys) == 1
    assert {l.finisher_id for l in cat.listings_by_toy["TOY-1"]} == {"FIN-1", "FIN-2"}
    assert ("multi_listed_toy", "TOY-1") in codes(cat)


def test_conflicting_toy_name_and_duplicate_listing(tmp_path):
    cat = load_catalog(write(tmp_path, toys=["TOY-1,Car,FIN-1,10,100", "TOY-1,Truck,FIN-2,12,50", "TOY-1,Car,FIN-1,11,1"]))
    assert cat.toys["TOY-1"].name == "Car"
    assert len(cat.listings) == 2
    assert {("conflicting_name", "TOY-1"), ("duplicate_row", "TOY-1/FIN-1")} <= codes(cat)


def test_duplicate_bom_line_keeps_first(tmp_path):
    cat = load_catalog(write(tmp_path, bill_of_materials=["TOY-1,PRT-1,4", "TOY-1,PRT-1,7"]))
    assert [b.quantity for b in cat.bom] == [4]
    assert ("duplicate_row", "TOY-1/PRT-1") in codes(cat)


def test_info_issues(tmp_path):
    cat = load_catalog(
        write(
            tmp_path,
            suppliers=["SUP-1,Sup One,CN", "SUP-2,Sup Two,IN", "SUP-3,Lonely,PL"],
            parts=["PRT-1,wheel,SUP-1,FAC-1,1.5", "PRT-2,spare,SUP-1,FAC-1,1"],
            toys=["TOY-1,Car,FIN-1,10,100", "TOY-2,Empty,FIN-1,5,5"],
        )
    )
    c = codes(cat)
    assert ("supplier_without_factories", "SUP-3") in c
    assert ("toy_without_bom", "TOY-2") in c
    assert ("unused_part", "PRT-2") in c


def test_real_dataset_smoke():
    data = Path(__file__).resolve().parents[2] / "data"
    cat = load_catalog(data)
    assert (len(cat.finishers), len(cat.suppliers), len(cat.factories)) == (8, 50, 232)
    assert (len(cat.parts), len(cat.sources)) == (400, 422)
    assert (len(cat.toys), len(cat.listings), len(cat.bom)) == (300, 305, 10463)
    by_code = {}
    for i in cat.issues:
        by_code[i.code] = by_code.get(i.code, 0) + 1
    assert by_code.get("multi_sourced_part") == 22
    assert by_code.get("multi_listed_toy") == 5
    assert by_code.get("supplier_without_factories") == 1
    assert by_code.get("missing_address") == 6
    assert not [i for i in cat.issues if i.severity == "error"]
