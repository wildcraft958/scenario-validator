"""Phase-2 protocol-correctness tests (TDD red-first) for the quick-win MUST-FIX bugs.

Each grounds a check fix against the EuroNCAP protocol + the RoadRunner export reality:
  RD_05 - junction roads must align to a CARDINAL axis within the configured tolerance
          (config.cardinal_heading_tolerance_deg), not merely within 45 deg of east/west.
          A 44-deg diagonal junction road slips through the old 45-deg east/west test.
  RD_02 - a road network with a disconnected ('blue dot') road must FAIL even when the
          raw road count is >= 2 (the old check only counted roads).
  NM_01 - actor-name matching is word-boundary, so 'VehicleX'/'VehicleTest' FAIL while
          'Vehicle2' still PASSes (the old loose startswith let any 'Vehicle*' through).
  NM_02 - the filename target-token -> OSC category cross-check accepts that EBTa/EMT
          export as <Vehicle> in RoadRunner, so a cyclist target does not false-flag,
          while a genuine pedestrian-vs-GVT mismatch still flags.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from lxml import etree  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
CPNCO_XODR = EXAMPLES / "CPNCO" / "AEB_CPNCO_30VUT_5EPTc_50Imp.xodr"

_PARSER = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)


def _root(xml: bytes):
    return etree.parse(io.BytesIO(xml), _PARSER).getroot()


@pytest.fixture(scope="module")
def config():
    from src.models import Config
    return Config.load(ROOT / "config.json")


# ============================================================
# CH_RD_05: junction roads aligned to a cardinal axis (config tolerance)
# ============================================================

# Intersection (incoming roads at 0 and 90 deg -> real junction) whose connecting road
# runs at 0.767945 rad = 44 deg. The old test (within 45 deg of east/west) PASSes this
# diagonal; the protocol wants it aligned to a cardinal axis within ~5 deg -> FAIL.
_DIAGONAL_JUNCTION = b"""<?xml version="1.0"?>
<OpenDRIVE>
  <junction id="1" name="J1">
    <connection id="0" incomingRoad="1" connectingRoad="3"/>
    <connection id="1" incomingRoad="2" connectingRoad="3"/>
  </junction>
  <road id="1" length="50"><planView><geometry x="0" y="0" hdg="0" length="50"><line/></geometry></planView></road>
  <road id="2" length="50"><planView><geometry x="0" y="0" hdg="1.5708" length="50"><line/></geometry></planView></road>
  <road id="3" length="50"><planView><geometry x="0" y="0" hdg="0.767945" length="50"><line/></geometry></planView></road>
</OpenDRIVE>"""

# Same intersection but the connecting road is axis-aligned (hdg 0) -> all cardinal -> PASS.
_CARDINAL_JUNCTION = b"""<?xml version="1.0"?>
<OpenDRIVE>
  <junction id="1" name="J1">
    <connection id="0" incomingRoad="1" connectingRoad="3"/>
    <connection id="1" incomingRoad="2" connectingRoad="3"/>
  </junction>
  <road id="1" length="50"><planView><geometry x="0" y="0" hdg="0" length="50"><line/></geometry></planView></road>
  <road id="2" length="50"><planView><geometry x="0" y="0" hdg="1.5708" length="50"><line/></geometry></planView></road>
  <road id="3" length="50"><planView><geometry x="0" y="0" hdg="0" length="50"><line/></geometry></planView></road>
</OpenDRIVE>"""


class TestRD05CardinalAlignment:
    def test_diagonal_junction_road_fails(self, config):
        from src.checks.road import check_rd_05
        result = check_rd_05(_root(_DIAGONAL_JUNCTION), config)
        assert result.status == "FAIL", result.comment
        assert "44" in result.comment

    def test_cardinal_junction_passes(self, config):
        from src.checks.road import check_rd_05
        result = check_rd_05(_root(_CARDINAL_JUNCTION), config)
        assert result.status == "PASS", result.comment

    def test_real_examples_still_pass(self, config):
        """The real junction examples are all cardinal -> must stay PASS."""
        from src.checks.road import check_rd_05
        for name in ("CCFtap/AEB_CCFtap_20VUT_45GVT_50Imp.xodr",
                     "CPTA/AEB_CPTAno_10VUT_5EPTa_10Imp.xodr",
                     "CPNCO/AEB_CPNCO_30VUT_5EPTc_50Imp.xodr"):
            p = EXAMPLES / name
            if not p.exists():
                continue
            root = etree.parse(str(p), _PARSER).getroot()
            assert check_rd_05(root, config).status == "PASS", name


# ============================================================
# CH_RD_02: >= 2 roads AND no disconnected ('blue dot') road
# ============================================================

_DISCONNECTED = b"""<?xml version="1.0"?>
<OpenDRIVE>
  <road id="1" length="50">
    <link><successor elementType="junction" elementId="999"/></link>
    <planView><geometry x="0" y="0" hdg="0" length="50"><line/></geometry></planView>
  </road>
  <road id="2" length="50">
    <link><predecessor elementType="road" elementId="1"/></link>
    <planView><geometry x="50" y="0" hdg="0" length="50"><line/></geometry></planView>
  </road>
</OpenDRIVE>"""

_CONNECTED = b"""<?xml version="1.0"?>
<OpenDRIVE>
  <road id="1" length="50">
    <link><successor elementType="road" elementId="2"/></link>
    <planView><geometry x="0" y="0" hdg="0" length="50"><line/></geometry></planView>
  </road>
  <road id="2" length="50">
    <link><predecessor elementType="road" elementId="1"/></link>
    <planView><geometry x="50" y="0" hdg="0" length="50"><line/></geometry></planView>
  </road>
</OpenDRIVE>"""


class TestRD02Disconnected:
    def test_disconnected_road_fails_despite_count(self, config):
        """Two roads (count >= 2) but road 1 points at a missing junction -> FAIL."""
        from src.checks.road import check_rd_02
        result = check_rd_02(_root(_DISCONNECTED), config)
        assert result.status == "FAIL", result.comment
        assert "1" in result.comment

    def test_connected_two_roads_pass(self, config):
        from src.checks.road import check_rd_02
        assert check_rd_02(_root(_CONNECTED), config).status == "PASS"

    def test_real_cpnco_passes(self, config):
        from src.checks.road import check_rd_02
        if not CPNCO_XODR.exists():
            pytest.skip("CPNCO example not present")
        root = etree.parse(str(CPNCO_XODR), _PARSER).getroot()
        assert check_rd_02(root, config).status == "PASS"


# ============================================================
# CH_NM_01: word-boundary actor-name matching
# ============================================================

def _write_xosc(tmp_path: Path, target_name: str) -> Path:
    xml = f"""<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader description="phase2_test"/>
  <Entities>
    <ScenarioObject name="VUT"><Vehicle name="VUT"/></ScenarioObject>
    <ScenarioObject name="{target_name}"><Vehicle name="{target_name}"/></ScenarioObject>
  </Entities>
</OpenSCENARIO>"""
    (tmp_path / "test.xosc").write_text(xml, encoding="utf-8")
    return tmp_path


class TestNM01WordBoundary:
    def test_vehiclex_fails(self, config, tmp_path):
        from src.checks.naming import check_nm_01
        result = check_nm_01(_write_xosc(tmp_path, "VehicleX"), config)
        assert result.status == "FAIL", result.comment
        assert "VehicleX" in result.comment

    def test_vehicletest_fails(self, config, tmp_path):
        from src.checks.naming import check_nm_01
        result = check_nm_01(_write_xosc(tmp_path, "VehicleTest"), config)
        assert result.status == "FAIL", result.comment

    def test_vehicle2_passes(self, config, tmp_path):
        """A digit boundary ('Vehicle2') is the legitimate numbered-actor convention."""
        from src.checks.naming import check_nm_01
        result = check_nm_01(_write_xosc(tmp_path, "Vehicle2"), config)
        assert result.status == "PASS", result.comment

    def test_exact_obstruction_name_passes(self, config, tmp_path):
        from src.checks.naming import check_nm_01
        result = check_nm_01(_write_xosc(tmp_path, "LargeObstructionVehicle"), config)
        assert result.status == "PASS", result.comment


# ============================================================
# CH_NM_04: target-token -> category cross-check tolerates RR cyclist-as-Vehicle
# ============================================================

def _write_scenario(tmp_path: Path, base: str, target_name: str, target_tag: str) -> Path:
    (tmp_path / f"{base}.rrscene").write_text("rrscene", encoding="utf-8")
    xml = f"""<?xml version="1.0"?>
<OpenSCENARIO>
  <FileHeader description="{base}"/>
  <Entities>
    <ScenarioObject name="VUT"><Vehicle name="VUT"/></ScenarioObject>
    <ScenarioObject name="{target_name}"><{target_tag} name="{target_name}"/></ScenarioObject>
  </Entities>
</OpenSCENARIO>"""
    (tmp_path / f"{base}.xosc").write_text(xml, encoding="utf-8")
    return tmp_path


class TestNM04CategorySets:
    def test_cyclist_exported_as_vehicle_does_not_flag(self, config, tmp_path):
        """RoadRunner exports EBTa as <Vehicle>; the filename token 'EBTa' must NOT be
        treated as a category mismatch -> PASS, not MANUAL_REVIEW."""
        d = _write_scenario(tmp_path, "AEB_CBTAno_20VUT_15EBTa_50Imp", "EBTa", "Vehicle")
        from src.checks.naming import check_nm_04
        result = check_nm_04(d, config)
        assert result.status == "PASS", result.comment

    def test_genuine_pedestrian_vs_gvt_still_flags(self, config, tmp_path):
        """A GVT filename token on a Pedestrian-category target is a real mistake -> flag."""
        d = _write_scenario(tmp_path, "AEB_CCFhos_30VUT_50GVT_50Imp", "GVT", "Pedestrian")
        from src.checks.naming import check_nm_04
        result = check_nm_04(d, config)
        assert result.status == "MANUAL_REVIEW", result.comment
