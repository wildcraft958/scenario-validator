"""Regression tests for the batch-run false positives (2026-07-01 stats).

Four wrong-result classes were traced to brittle logic rather than broken scenarios:
  * NM_04 rejected the legitimate longitudinal impact edges -25Imp / 125Imp.
  * SC_17 graded -25Imp geometry against a silent 50% default (its own estimate confirmed -25%).
  * MD_02 demanded a route for every parked obstruction vehicle (CPNCO 2 routes vs 4 actors).
Each fix is robust/per-class, not a one-off allow-list bump, so these tests pin the behaviour.
"""
from __future__ import annotations

import pathlib

import pytest

from src.checks.model_desk import check_md_02, check_md_03
from src.checks.naming import _split_int_suffix, check_nm_04, parse_scenario_filename
from src.checks.scenario import check_sc_17
from src.models import Config
from src.parsers import xosc as xosc_parser

CFG = Config.load()


# ---- signed impact token -----------------------------------------------------------------

@pytest.mark.parametrize("token,expected", [
    ("10VUT", 10), ("50Imp", 50), ("125Imp", 125),
    ("-25Imp", -25), ("+25Imp", 25), ("0Imp", 0),
])
def test_split_int_suffix_accepts_signed(token, expected):
    suffix = "VUT" if token.endswith("VUT") else "Imp"
    assert _split_int_suffix(token, suffix) == expected


@pytest.mark.parametrize("token", ["Imp", "-Imp", "1.5Imp", "--5Imp", "abcImp", "2 5Imp"])
def test_split_int_suffix_rejects_non_integers(token):
    assert _split_int_suffix(token, "Imp") is None


def test_negative_impact_name_is_well_formed():
    parsed = parse_scenario_filename("AEB_CCRb_100VUT_100GVT_-25Imp", CFG)
    assert parsed.well_formed, parsed.problems
    assert parsed.impact_pct == -25


# ---- per-family allowed overlaps (RAG: EuroNCAP Frontal Collisions v1.1) ------------------

@pytest.mark.parametrize("tag,expected", [
    ("CCRb", {-25, 0, 25, 50, 75, 100, 125}),   # rear car matrix
    ("CCRs", {-25, 0, 25, 50, 75, 100, 125}),
    ("CCFhos", {25, 50, 75, 100}),               # front car
    ("CPTAno", {10, 25, 50, 75, 90}),            # VRU turning
    ("CPNA", {10, 25, 50, 75, 90}),              # VRU crossing
    ("CPNCO", {25, 50, 75}),                     # child obstructed - narrower
    ("CPLA", {10, 25, 50, 75}),                  # VRU longitudinal
    ("CBTAfs", {0, 75, 100}),                    # side impact along length
    ("CCFtap", {50}),                            # turn-across synced to 50%
])
def test_impact_overlaps_match_rag_per_family(tag, expected):
    assert {int(v) for v in CFG.impact_overlaps_for(tag)} == expected


def test_family_without_grid_falls_back_to_flat():
    # CCCscp has no swept grid in the matrix -> coarse cross-family fallback.
    assert CFG.impact_overlaps_for("CCCscp") == CFG.allowed_impact_overlaps


def _scenario_dir(tmp_path: pathlib.Path, base: str) -> pathlib.Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    for ext in (".xosc", ".xodr"):
        (tmp_path / f"{base}{ext}").write_text("<x/>")
    return tmp_path


def test_nm_04_accepts_longitudinal_negative_and_125(tmp_path):
    for base in ("AEB_CCRb_100VUT_100GVT_-25Imp", "AEB_CCRb_100VUT_100GVT_125Imp"):
        d = _scenario_dir(tmp_path / base, base)
        res = check_nm_04(d, CFG)
        assert res.status == "PASS", res.comment


def test_nm_04_still_rejects_edges_for_wrong_family(tmp_path):
    # -25 is valid for rear car (CCRb) but NOT for a turning pedestrian (CPNA): the per-family
    # grid must reject it rather than a flat superset waving it through.
    base = "AEB_CPNA_50VUT_10EPTa_-25Imp"
    res = check_nm_04(_scenario_dir(tmp_path / base, base), CFG)
    assert res.status == "FAIL"
    assert "not an allowed overlap for CPNA" in res.comment


# ---- SC_17 no silent 50% default ---------------------------------------------------------

def test_sc_17_manual_when_impact_undeterminable():
    # designed_impact_pct None (unparseable Imp token) and no per-family override -> MANUAL,
    # never a FAIL graded against a guessed default. The MANUAL short-circuits before any
    # geometry, so a real root is unnecessary.
    res = check_sc_17(None, CFG, scenario_tag="CCRb", designed_impact_pct=None)
    assert res.status == "MANUAL_REVIEW"
    assert "impact % is unknown" in res.comment.lower()


# ---- MD_02 excludes parked obstructions --------------------------------------------------

_CPNCO = pathlib.Path("examples/CPNCO/AEB_CPNCO_30VUT_5EPTc_50Imp.xosc")


@pytest.mark.skipif(not _CPNCO.exists(), reason="CPNCO example not present")
def test_md_02_excludes_parked_obstructions():
    root = xosc_parser.load(_CPNCO)
    # CPNCO ships VUT + EPTc (moving) + Large/SmallObstructionVehicle (parked): 2 routes is correct.
    res = check_md_02({"routes": [1, 2], "format": "xml"}, root, CFG)
    assert res.status == "PASS", res.comment
    assert "ObstructionVehicle" in res.comment and "excluded" in res.comment


@pytest.mark.skipif(not _CPNCO.exists(), reason="CPNCO example not present")
def test_md_02_still_flags_a_genuinely_missing_route():
    root = xosc_parser.load(_CPNCO)
    res = check_md_02({"routes": [1], "format": "xml"}, root, CFG)
    assert res.status == "FAIL"
    assert "1 routes found but 2 moving actors" in res.comment


# ---- MD_03 is junction-aware -------------------------------------------------------------

_ONE_ROAD_ROUTE = {"routes": [{"roads": ["r1", "r2"]}, {"roads": ["r3"]}], "format": "xml"}


def test_md_03_single_road_route_ok_without_junction():
    # CCRs-style straight scenario: the stationary target's 1-road route is by design.
    res = check_md_03(_ONE_ROAD_ROUTE, is_junction_scenario=False)
    assert res.status == "PASS"
    assert "Non-junction" in res.comment


def test_md_03_still_flags_short_route_in_a_junction():
    res = check_md_03(_ONE_ROAD_ROUTE, is_junction_scenario=True)
    assert res.status == "FAIL"
    assert "Route 2 (1 road)" in res.comment
