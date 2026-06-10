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
