"""Phase-4 protocol-correctness tests (TDD red-first): SHOULD-IMPROVE refinements.

Grounded against the real RoadRunner export reality (validated on the example .xodr/.xosc):
  RD_04 - the leftmost-road origin tolerance is configurable (road_origin_tolerance_m),
          not a hardcoded 0.01 m.
  RD_06 - junction-connecting roads must carry only driving lanes (plus the structural
          'none' reference lane); a sidewalk/border/parking/shoulder lane on a connecting
          road is flagged - generalising the old shoulder-only test. Real connecting roads
          carry {driving, none} only, so they still PASS.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from lxml import etree  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

_PARSER = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)


def _root(xml: bytes):
    return etree.parse(io.BytesIO(xml), _PARSER).getroot()


@pytest.fixture(scope="module")
def config():
    from src.models import Config
    return Config.load(ROOT / "config.json")


# ============================================================
# CH_RD_04: configurable leftmost-road origin tolerance
# ============================================================

_JUNCTION_ORIGIN = b"""<?xml version="1.0"?>
<OpenDRIVE>
  <junction id="1" name="J1">
    <connection id="0" incomingRoad="1" connectingRoad="3"/>
    <connection id="1" incomingRoad="2" connectingRoad="3"/>
  </junction>
  <road id="1" length="50"><planView><geometry x="0.05" y="0" hdg="0" length="50"><line/></geometry></planView></road>
  <road id="2" length="50"><planView><geometry x="50" y="0" hdg="1.5708" length="50"><line/></geometry></planView></road>
  <road id="3" length="50"><planView><geometry x="10" y="0" hdg="0" length="50"><line/></geometry></planView></road>
</OpenDRIVE>"""


class TestRD04ConfigurableTolerance:
    def test_default_tolerance_fails_offset_origin(self, config):
        """Leftmost road at x=0.05 m fails the default 0.01 m origin tolerance."""
        from src.checks.road import check_rd_04
        assert check_rd_04(_root(_JUNCTION_ORIGIN), config).status == "FAIL"

    def test_relaxed_tolerance_passes(self, config):
        """A configured 0.1 m tolerance is honoured -> the same 0.05 m offset PASSes."""
        from src.checks.road import check_rd_04
        cfg = config.model_copy(update={"road_origin_tolerance_m": 0.1})
        assert check_rd_04(_root(_JUNCTION_ORIGIN), cfg).status == "PASS"


# ============================================================
# CH_RD_06: junction connecting roads carry only driving (+ structural none) lanes
# ============================================================

def _junction_with_connecting_lane(lane_type: str) -> bytes:
    return f"""<?xml version="1.0"?>
<OpenDRIVE>
  <junction id="1" name="J1">
    <connection id="0" incomingRoad="1" connectingRoad="3"/>
    <connection id="1" incomingRoad="2" connectingRoad="3"/>
  </junction>
  <road id="1" length="50"><planView><geometry x="0" y="0" hdg="0" length="50"><line/></geometry></planView></road>
  <road id="2" length="50"><planView><geometry x="0" y="0" hdg="1.5708" length="50"><line/></geometry></planView></road>
  <road id="3" length="50">
    <planView><geometry x="0" y="0" hdg="0" length="50"><line/></geometry></planView>
    <lanes><laneSection>
      <left><lane id="1" type="{lane_type}"><width a="2.0"/></lane></left>
      <center><lane id="0" type="none"/></center>
      <right><lane id="-1" type="driving"><width a="3.5"/></lane></right>
    </laneSection></lanes>
  </road>
</OpenDRIVE>""".encode()


CPTA_XOSC = EXAMPLES / "CPTA" / "AEB_CPTAno_10VUT_5EPTa_10Imp.xosc"


# ============================================================
# CH_SC_20: Farside/Nearside + Same/Opposite sub-variant (RAG-grounded suffix)
# ============================================================

class TestSC20SubVariant:
    def test_turn_subvariant_decoder(self):
        from src.checks.scenario import turn_subvariant
        assert turn_subvariant("CPTAfs") == ("Farside", "Same")
        assert turn_subvariant("CPTAfo") == ("Farside", "Opposite")
        assert turn_subvariant("CPTAns") == ("Nearside", "Same")
        assert turn_subvariant("CPTAno") == ("Nearside", "Opposite")
        assert turn_subvariant("CBTAns") == ("Nearside", "Same")
        # non-turning / no suffix -> empty
        assert turn_subvariant("CCFhol") == ("", "")
        assert turn_subvariant("CPNCO") == ("", "")
        assert turn_subvariant(None) == ("", "")

    def test_real_cpta_no_is_nearside_opposite(self, config):
        """CPTAno: VUT trajectory turns Nearside, EPTa travels Opposite -> PASS naming both."""
        if not CPTA_XOSC.exists():
            pytest.skip("CPTA example not present")
        from src.parsers import xosc as xp
        from src.checks.naming import parse_scenario_filename
        from src.checks.scenario import check_sc_20
        root = xp.load(CPTA_XOSC)
        pn = parse_scenario_filename("AEB_CPTAno_10VUT_5EPTa_10Imp", config)
        result = check_sc_20(root, config, parsed_name=pn)
        assert result.status == "PASS", result.comment
        assert "Nearside" in result.comment and "Opposite" in result.comment


# ============================================================
# CH_SC_01: kinematic single-path coverage caveat
# ============================================================

class TestSC01CoverageCaveat:
    def test_kinematic_pass_notes_partial_coverage(self, config):
        if not CPTA_XOSC.exists():
            pytest.skip("CPTA example not present")
        from src.parsers import xosc as xp
        from src.checks.scenario import check_sc_01
        result = check_sc_01(xp.load(CPTA_XOSC), config)
        assert result.status == "PASS", result.comment
        assert "coverage" in result.comment.lower() or "variation" in result.comment.lower()


CPNCO_XOSC = EXAMPLES / "CPNCO" / "AEB_CPNCO_30VUT_5EPTc_50Imp.xosc"


# ============================================================
# CH_SC_14: obstruction layout (spacing + lateral offset) vs protocol
# ============================================================

class TestSC14ObstructionLayout:
    def test_real_cpnco_layout_ok(self, config):
        """Real CPNCO: 2 obstructions ~5.4 m apart (~1 m bumper gap), ~1.8 m nearside edge
        offset -> matches the protocol layout -> PASS, with the measurements reported."""
        if not CPNCO_XOSC.exists():
            pytest.skip("CPNCO example not present")
        from src.parsers import xosc as xp
        from src.checks.scenario import check_sc_14
        result = check_sc_14(xp.load(CPNCO_XOSC), config)
        assert result.status == "PASS", result.comment
        assert "spacing" in result.comment.lower() and "offset" in result.comment.lower()

    def test_bad_spacing_flags_manual_review(self, config):
        """Move an obstruction far out of the 1 m bumper-gap layout -> MANUAL_REVIEW."""
        if not CPNCO_XOSC.exists():
            pytest.skip("CPNCO example not present")
        from src.parsers import xosc as xp
        from src.checks.scenario import check_sc_14
        root = xp.load(CPNCO_XOSC)
        # SmallObstructionVehicle is placed via Init WorldPosition; push it 40 m along.
        moved = False
        for priv in root.xpath("//Init//Private[@entityRef='SmallObstructionVehicle']"):
            for wp in priv.xpath(".//WorldPosition"):
                wp.set("y", str(float(wp.get("y", "0")) + 40.0))
                moved = True
        assert moved, "could not mutate SmallObstructionVehicle position"
        result = check_sc_14(root, config)
        assert result.status == "MANUAL_REVIEW", result.comment


class TestRD06DrivingLaneAllowlist:
    def test_sidewalk_on_connecting_road_fails(self, config):
        from src.checks.road import check_rd_06
        result = check_rd_06(_root(_junction_with_connecting_lane("sidewalk")), config)
        assert result.status == "FAIL", result.comment
        assert "sidewalk" in result.comment.lower()

    def test_border_on_connecting_road_fails(self, config):
        from src.checks.road import check_rd_06
        assert check_rd_06(_root(_junction_with_connecting_lane("border")), config).status == "FAIL"

    def test_driving_only_passes(self, config):
        from src.checks.road import check_rd_06
        assert check_rd_06(_root(_junction_with_connecting_lane("driving")), config).status == "PASS"

    def test_real_examples_still_pass(self, config):
        """Real connecting roads carry {driving, none} only -> still PASS."""
        from src.parsers import xodr
        from src.checks.road import check_rd_06
        for name in ("CCFtap/AEB_CCFtap_20VUT_45GVT_50Imp.xodr",
                     "CPTA/AEB_CPTAno_10VUT_5EPTa_10Imp.xodr",
                     "CPNCO/AEB_CPNCO_30VUT_5EPTc_50Imp.xodr"):
            p = EXAMPLES / name
            if not p.exists():
                continue
            assert check_rd_06(xodr.load(p), config).status == "PASS", name
