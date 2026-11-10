import pytest

from app.exposure import (
    ActiveFlag,
    ExposureStatus as E,
    SourceStatus as S,
    combine_part_status,
    evaluate,
)
from tests.builders import make_catalog


def flag(supplier_id, *factories, id=1):
    return ActiveFlag(id=id, supplier_id=supplier_id, factory_ids=frozenset(factories))


@pytest.fixture
def catalog():
    # SUP-A: FAC-A1, FAC-A2   SUP-B: FAC-B1   SUP-C: FAC-C1   SUP-EMPTY: no factories
    # P1 single-sourced from FAC-A1
    # P2 single-sourced from FAC-A2
    # P3 multi-sourced: FAC-A1 + FAC-B1
    # P4 single-sourced from FAC-C1
    return make_catalog(
        suppliers={"SUP-A": ["FAC-A1", "FAC-A2"], "SUP-B": ["FAC-B1"], "SUP-C": ["FAC-C1"], "SUP-EMPTY": []},
        sources=[("P1", "FAC-A1"), ("P2", "FAC-A2"), ("P3", "FAC-A1"), ("P3", "FAC-B1"), ("P4", "FAC-C1")],
        toys={
            "T1": [("P1", 2), ("P4", 1)],
            "T2": [("P2", 1)],
            "T3": [("P3", 3)],
            "T4": [("P4", 1)],
            "T-NOBOM": [],
        },
    )


# --- part status combination rules (spec §6) -------------------------------

@pytest.mark.parametrize(
    "sources, expected",
    [
        ([S.FLAGGED], E.CONFIRMED),
        ([S.FLAGGED, S.FLAGGED], E.CONFIRMED),
        ([S.FLAGGED, S.CLEAN], E.POTENTIAL),
        ([S.FLAGGED, S.SUPPLIER_RISK], E.POTENTIAL),
        ([S.SUPPLIER_RISK], E.SUPPLIER_RISK),
        ([S.SUPPLIER_RISK, S.CLEAN], E.SUPPLIER_RISK),
        ([S.CLEAN], E.CLEAN),
        ([S.CLEAN, S.CLEAN], E.CLEAN),
        ([], E.CLEAN),
    ],
)
def test_combine_part_status(sources, expected):
    assert combine_part_status(sources) == expected


# --- whole engine -----------------------------------------------------------

def test_no_flags_everything_clean(catalog):
    ex = evaluate(catalog, [])
    assert set(ex.toy_status.values()) == {E.CLEAN}
    assert set(ex.part_status.values()) == {E.CLEAN}


def test_whole_supplier_flag(catalog):
    ex = evaluate(catalog, [flag("SUP-A")])
    assert ex.source_status[("P1", "FAC-A1")] == S.FLAGGED
    assert ex.source_status[("P2", "FAC-A2")] == S.FLAGGED
    assert ex.part_status["P1"] == E.CONFIRMED
    assert ex.part_status["P3"] == E.POTENTIAL  # other source FAC-B1 is clean
    assert ex.toy_status == {"T1": E.CONFIRMED, "T2": E.CONFIRMED, "T3": E.POTENTIAL, "T4": E.CLEAN, "T-NOBOM": E.CLEAN}


def test_factory_scoped_flag(catalog):
    ex = evaluate(catalog, [flag("SUP-A", "FAC-A1")])
    assert ex.source_status[("P1", "FAC-A1")] == S.FLAGGED
    assert ex.source_status[("P2", "FAC-A2")] == S.SUPPLIER_RISK
    assert ex.toy_status["T1"] == E.CONFIRMED
    assert ex.toy_status["T2"] == E.SUPPLIER_RISK


def test_factory_scoped_flag_on_other_factory(catalog):
    ex = evaluate(catalog, [flag("SUP-A", "FAC-A2")])
    assert ex.part_status["P1"] == E.SUPPLIER_RISK
    assert ex.part_status["P3"] == E.SUPPLIER_RISK  # FAC-A1 supplier_risk + FAC-B1 clean
    assert ex.part_status["P2"] == E.CONFIRMED


def test_all_sources_flagged_across_suppliers_is_confirmed(catalog):
    ex = evaluate(catalog, [flag("SUP-A", id=1), flag("SUP-B", id=2)])
    assert ex.part_status["P3"] == E.CONFIRMED


def test_toy_status_is_worst_part(catalog):
    ex = evaluate(catalog, [flag("SUP-A", "FAC-A2", id=1), flag("SUP-C", id=2)])
    # T1 = P1 (supplier_risk) + P4 (confirmed)
    assert ex.toy_status["T1"] == E.CONFIRMED


def test_toy_without_bom_is_clean(catalog):
    ex = evaluate(catalog, [flag("SUP-A"), flag("SUP-B", id=2), flag("SUP-C", id=3)])
    assert ex.toy_status["T-NOBOM"] == E.CLEAN


def test_supplier_without_factories_affects_nothing(catalog):
    ex = evaluate(catalog, [flag("SUP-EMPTY")])
    assert set(ex.toy_status.values()) == {E.CLEAN}


def test_flag_for_unknown_supplier_is_ignored(catalog):
    ex = evaluate(catalog, [flag("SUP-GONE")])
    assert set(ex.toy_status.values()) == {E.CLEAN}


def test_scoped_flag_with_unknown_factory_marks_supplier_risk(catalog):
    # factory vanished from catalog after re-import: supplier still flagged, no factory matches
    ex = evaluate(catalog, [flag("SUP-A", "FAC-GONE")])
    assert ex.part_status["P1"] == E.SUPPLIER_RISK


def test_two_active_flags_for_same_supplier_rejected(catalog):
    with pytest.raises(ValueError):
        evaluate(catalog, [flag("SUP-A", id=1), flag("SUP-A", id=2)])


def test_affected_lines_sorted_by_severity(catalog):
    ex = evaluate(catalog, [flag("SUP-A", "FAC-A2", id=1), flag("SUP-C", id=2)])
    lines = ex.affected_lines("T1")
    assert [(l.part_id, ex.part_status[l.part_id]) for l in lines] == [
        ("P4", E.CONFIRMED),
        ("P1", E.SUPPLIER_RISK),
    ]


def test_toys_affected_by_supplier(catalog):
    ex = evaluate(catalog, [flag("SUP-A")])
    assert ex.toys_affected_by_supplier("SUP-A") == {"T1", "T2", "T3"}
    assert ex.toys_affected_by_supplier("SUP-B") == set()
