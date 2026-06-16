"""Tests for the Eval_Data benchmark features:

  * CH_NM_02 (reference-canonical): the .rrscene name must equal the .rrscenario name.
  * the automation-level registry + the Automation columns on CheckResult.
  * the --checklist reviewer export (Summary / ChecklistFinal / Prequisites).
  * the .rd parser reading the dSPACE ModelDesk RouteSection schema (CH_MD_03 data).
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def config():
    from src.models import Config
    return Config.load(ROOT / "config.json")


def _write_rd(tmp_path: Path, content: bytes) -> Path:
    p = tmp_path / "x.rd"
    p.write_bytes(content)
    return p


# ---------------------------------------------------------------------------
# CH_NM_02: .rrscene name equals .rrscenario name
# ---------------------------------------------------------------------------

class TestNM02RrsceneMatchesRrscenario:
    def test_matching_names_pass(self, tmp_path):
        base = "AEB_CCFtap_10VUT_30GVT_50Imp"
        (tmp_path / f"{base}.rrscene").write_text("x", encoding="utf-8")
        (tmp_path / f"{base}.rrscenario").write_text("y", encoding="utf-8")
        from src.checks.naming import check_nm_02
        result = check_nm_02(tmp_path)
        assert result.check_id == "CH_NM_02"
        assert result.status == "PASS", result.comment

    def test_mismatched_names_fail(self, tmp_path):
        (tmp_path / "scene_A.rrscene").write_text("x", encoding="utf-8")
        (tmp_path / "scenario_B.rrscenario").write_text("y", encoding="utf-8")
        from src.checks.naming import check_nm_02
        assert check_nm_02(tmp_path).status == "FAIL"

    def test_missing_one_defers_to_manual(self, tmp_path):
        (tmp_path / "only.rrscene").write_text("x", encoding="utf-8")
        from src.checks.naming import check_nm_02
        assert check_nm_02(tmp_path).status == "MANUAL_REVIEW"


# ---------------------------------------------------------------------------
# Automation-level registry
# ---------------------------------------------------------------------------

_ALL_CHECK_IDS = (
    [f"CH_NM_0{i}" for i in range(1, 7)]
    + [f"CH_RD_0{i}" for i in range(1, 7)]
    + [f"CH_SC_{i:02d}" for i in range(1, 23)]
    + [f"CH_MD_{i:02d}" for i in range(1, 12)]
    + ["CH_MR_01", "CH_MR_02", "CH_FB_01", "CH_FB_02"]
)


class TestAutomationRegistry:
    def test_every_check_id_is_classified(self):
        from src.automation import AUTOMATION_LEVEL
        missing = [c for c in _ALL_CHECK_IDS if c not in AUTOMATION_LEVEL]
        assert not missing, f"unclassified check ids: {missing}"

    def test_levels_and_reasons_are_valid(self):
        from src.automation import AUTOMATION_LEVEL
        allowed = {"Fully Automated", "Partially Automated", "Manual"}
        for cid, (level, note) in AUTOMATION_LEVEL.items():
            assert level in allowed, f"{cid} has bad level {level!r}"
            assert note.strip(), f"{cid} has empty reason"

    def test_checkresult_autopopulates_level_and_row(self):
        from src.models import CheckResult
        r = CheckResult(check_id="CH_SC_16", category="Scenario", description="d", status="MANUAL_REVIEW")
        assert r.automation_level == "Partially Automated"
        assert r.automation_note
        # Validation row carries the two new columns at the end.
        assert len(r.as_validation_row()) == 9
        assert r.as_validation_row()[7] == "Partially Automated"


# ---------------------------------------------------------------------------
# Reviewer checklist export
# ---------------------------------------------------------------------------

class TestReferenceChecklistExport:
    def _build(self, tmp_path):
        from src.models import CheckResult, SummaryStats
        from src.reporter import write_reference_checklist
        results = [
            CheckResult(check_id="CH_NM_01", category="Naming", description="naming", status="PASS"),
            CheckResult(check_id="CH_MD_03", category="ModelDesk", description="routes", status="FAIL"),
        ]
        stats = SummaryStats.from_results(results, "scn", "2026-01-01 00:00:00", "proto")
        out = tmp_path / "Review_Checklist.xlsx"
        write_reference_checklist(results, stats, out)
        return openpyxl.load_workbook(out)

    def test_three_reference_sheets(self, tmp_path):
        wb = self._build(tmp_path)
        assert wb.sheetnames == ["Summary", "ChecklistFinal", "Prequisites"]

    def test_table_header_and_verdicts(self, tmp_path):
        wb = self._build(tmp_path)
        ws = wb["ChecklistFinal"]
        assert ws.cell(row=8, column=2).value == "Category"
        assert ws.cell(row=8, column=5).value == "Self Review"
        assert ws.cell(row=8, column=8).value == "Automation Level"

        verdict = {}
        for r in range(9, ws.max_row + 1):
            cid = ws.cell(row=r, column=3).value
            if cid:
                verdict[cid] = ws.cell(row=r, column=5).value
        # full reference list (NM 6 + RD 6 + SC 22 + MD 11 + MR 2 + FB 2)
        assert len(verdict) == 49
        # our computed checks carry their verdict
        assert verdict["CH_NM_01"] == "Yes"
        assert verdict["CH_MD_03"] == "No"
        # a reference-only check we do not compute exports as Manual
        assert verdict["CH_MD_07"] == "Manual"
        assert verdict["CH_FB_02"] == "Manual"


# ---------------------------------------------------------------------------
# .rd parser - dSPACE ModelDesk schema
# ---------------------------------------------------------------------------

class TestSC22ObstructionScope:
    """CH_SC_22 is N/A when there is no static obstruction; an obstruction's asset path is
    still validated (PASS in the NCAP folder, FAIL outside it)."""

    def _root(self, body: bytes):
        from lxml import etree
        xml = b'<?xml version="1.0"?><OpenSCENARIO><Entities>' + body + b"</Entities></OpenSCENARIO>"
        return etree.parse(__import__("io").BytesIO(xml),
                           etree.XMLParser(no_network=True)).getroot()

    _VUT = b'<ScenarioObject name="VUT"><Vehicle name="VUT" model3d="Vehicles/MyCar.rrvehicle"/></ScenarioObject>'

    def test_no_obstruction_is_na(self, config):
        from src.checks.scenario import check_sc_22
        body = self._VUT + b'<ScenarioObject name="GVT"><Vehicle name="GVT" model3d="NCAP Assets/GVT.rrvehicle"/></ScenarioObject>'
        assert check_sc_22(self._root(body), config).status == "NA"

    def test_obstruction_in_ncap_folder_passes(self, config):
        from src.checks.scenario import check_sc_22
        body = self._VUT + b'<ScenarioObject name="Obstruction1"><Vehicle name="Obstruction1" model3d="NCAP Assets/obs.rrvehicle"/></ScenarioObject>'
        assert check_sc_22(self._root(body), config).status == "PASS"

    def test_obstruction_outside_ncap_folder_fails(self, config):
        from src.checks.scenario import check_sc_22
        body = self._VUT + b'<ScenarioObject name="Obstruction1"><Vehicle name="Obstruction1" model3d="Props/box.rrvehicle"/></ScenarioObject>'
        assert check_sc_22(self._root(body), config).status == "FAIL"


class TestRD04ObstructionPrecondition:
    """CH_RD_04's (0,0,0) origin rule only applies to scenarios with static objects at the
    intersection, applied at the run level where the .xosc entities are known."""

    def test_no_obstruction_scenario_is_na(self):
        from validator import run_validation
        results, _ = run_validation(ROOT / "examples" / "CCFtap", skip_rd=True)
        rd04 = {r.check_id: r for r in results}["CH_RD_04"]
        assert rd04.status == "NA", rd04.comment

    def test_obstruction_scenario_still_evaluated(self):
        from validator import run_validation
        results, _ = run_validation(ROOT / "examples" / "CPNCO", skip_rd=True)
        rd04 = {r.check_id: r for r in results}["CH_RD_04"]
        assert rd04.status in ("PASS", "FAIL"), rd04.comment


class TestRdSegmentCounts:
    def test_dspace_routesection_counted(self, tmp_path):
        xml = (
            b'<RoadNetwork xmlns="dSPACE.ModelDesk.RoadGenerator.Data">'
            b'<Route><Name>VUT_Trajectory</Name><Sections>'
            b'<RouteSection/><RouteSection/><RouteSection/>'
            b'</Sections></Route></RoadNetwork>'
        )
        from src.parsers import rd
        d = rd.load(_write_rd(tmp_path, xml))
        assert rd.get_route_segment_counts(d) == [3]
        assert d["routes"][0]["name"] == "VUT_Trajectory"

    def test_generic_road_ids_counted(self, tmp_path):
        xml = b'<Routes><Route name="Ego"><Road id="1"/><Road id="2"/></Route></Routes>'
        from src.parsers import rd
        d = rd.load(_write_rd(tmp_path, xml))
        assert rd.get_route_segment_counts(d) == [2]

    def test_single_segment_route_is_short(self, tmp_path):
        xml = (
            b'<RoadNetwork xmlns="dSPACE.ModelDesk.RoadGenerator.Data">'
            b'<Route><Name>R</Name><Sections><RouteSection/></Sections></Route></RoadNetwork>'
        )
        from src.parsers import rd
        from src.checks.model_desk import check_md_03
        d = rd.load(_write_rd(tmp_path, xml))
        assert check_md_03(d).status == "FAIL"
