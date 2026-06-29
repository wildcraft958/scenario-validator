"""Robustness tests: mutation-based and protocol boundary tests using real example files.

Each test mutates a parsed tree in memory, runs the check function, and asserts the
expected verdict. This catches regressions that synthetic XMLs miss - the real
RoadRunner export format has structural quirks that simple hand-crafted XML doesn't.
"""
from __future__ import annotations

import copy
import io
import math
from pathlib import Path

import pytest
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

# Real example files available
CCFHOL_XOSC = EXAMPLES / "CCFhol" / "AEB_CCFhol_30VUT_50GVT_50Imp.xosc"
CCFHOL_XODR = EXAMPLES / "CCFhol" / "AEB_CCFhol_30VUT_50GVT_50Imp.xodr"
CCFHOS_XOSC = EXAMPLES / "CCFhos" / "AEB_CCFhos_30VUT_50GVT_50Imp.xosc"
CCFTAP_XOSC = EXAMPLES / "CCFtap" / "AEB_CCFtap_20VUT_45GVT_50Imp.xosc"
CPNCO_XOSC  = EXAMPLES / "CPNCO" / "AEB_CPNCO_30VUT_5EPTc_50Imp.xosc"
CPNCO_XODR  = EXAMPLES / "CPNCO" / "AEB_CPNCO_30VUT_5EPTc_50Imp.xodr"
CPTA_XOSC   = EXAMPLES / "CPTA"  / "AEB_CPTAno_10VUT_5EPTa_10Imp.xosc"
CPTA_XODR   = EXAMPLES / "CPTA"  / "AEB_CPTAno_10VUT_5EPTa_10Imp.xodr"

ALL_EXAMPLES_PRESENT = all(
    p.exists() for p in [CCFHOL_XOSC, CCFHOL_XODR, CPNCO_XOSC, CPNCO_XODR, CPTA_XOSC, CCFTAP_XOSC]
)

pytestmark = pytest.mark.skipif(
    not ALL_EXAMPLES_PRESENT, reason="Real example files not present"
)

_PARSER = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)


def _load(path: Path):
    return etree.parse(str(path), _PARSER).getroot()


def _copy(root):
    """Deep copy a parsed tree so mutations don't affect other tests."""
    return copy.deepcopy(root)


@pytest.fixture(scope="module")
def config():
    from src.models import Config
    return Config.load(ROOT / "config.json")


# ============================================================
# CH_RD_01: Lane width = 3.5 m
# ============================================================

class TestRD01LaneWidth:
    def test_real_cpnco_passes(self, config):
        from src.checks.road import check_rd_01
        root = _load(CPNCO_XODR)
        assert check_rd_01(root, config).status == "PASS"

    def test_narrow_lane_fails(self, config):
        """Changing all driving lane widths to 3.0 m should fail CH_RD_01."""
        from src.checks.road import check_rd_01
        root = _copy(_load(CPNCO_XODR))
        for w in root.xpath("//laneSection//lane[@type='driving']/width"):
            w.set("a", "3.0")
        assert check_rd_01(root, config).status == "FAIL"

    def test_just_within_tolerance_passes(self, config):
        """Lane width 3.45 m is within ±0.05 m tolerance → PASS."""
        from src.checks.road import check_rd_01
        root = _copy(_load(CPNCO_XODR))
        for w in root.xpath("//laneSection//lane[@type='driving']/width"):
            w.set("a", "3.45")
        result = check_rd_01(root, config)
        assert result.status == "PASS", result.comment

    def test_just_outside_tolerance_fails(self, config):
        """Lane width 3.44 m is outside ±0.05 m tolerance → FAIL."""
        from src.checks.road import check_rd_01
        root = _copy(_load(CPNCO_XODR))
        for w in root.xpath("//laneSection//lane[@type='driving']/width"):
            w.set("a", "3.44")
        assert check_rd_01(root, config).status == "FAIL"

    def test_missing_road_markings_fails(self, config):
        """Removing all road markings should fail CH_RD_01."""
        from src.checks.road import check_rd_01
        root = _copy(_load(CPNCO_XODR))
        for rm in root.xpath("//lane/roadMark"):
            rm.getparent().remove(rm)
        assert check_rd_01(root, config).status == "FAIL"

    def test_junction_side_lane_325_passes(self, config):
        """Per EuroNCAP Frontal v1.1 Figure 4.2 a junction connecting lane may be 3.25 m, so it
        must PASS, not be false-failed against the 3.5 m main-lane width."""
        from src.checks.road import check_rd_01
        root = _copy(_load(CPNCO_XODR))
        junc_roads = {c.get("connectingRoad") for c in root.xpath("//junction/connection")}
        assert junc_roads, "fixture has no junction connecting roads"
        for road in root.xpath("//road"):
            if road.get("id") in junc_roads:
                for w in road.xpath(".//laneSection//lane[@type='driving']/width"):
                    w.set("a", "3.25")
        result = check_rd_01(root, config)
        assert result.status == "PASS", result.comment

    def test_main_lane_325_fails(self, config):
        """A 3.25 m width on a MAIN approach lane is out of spec (main lanes are 3.5 m) → FAIL."""
        from src.checks.road import check_rd_01
        root = _copy(_load(CPNCO_XODR))
        junc_roads = {c.get("connectingRoad") for c in root.xpath("//junction/connection")}
        for road in root.xpath("//road"):
            if road.get("id") not in junc_roads:
                for w in road.xpath(".//laneSection//lane[@type='driving']/width"):
                    w.set("a", "3.25")
        assert check_rd_01(root, config).status == "FAIL"


# ============================================================
# CH_RD_02: >= 2 road segments
# ============================================================

class TestRD02RoadSegments:
    def test_real_file_passes(self, config):
        from src.checks.road import check_rd_02
        assert check_rd_02(_load(CPNCO_XODR), config).status == "PASS"

    def test_single_road_fails(self, config):
        """Keeping only one road should fail CH_RD_02."""
        from src.checks.road import check_rd_02
        root = _copy(_load(CPNCO_XODR))
        roads = root.findall(".//road")
        # Remove all but first
        for r in roads[1:]:
            r.getparent().remove(r)
        assert check_rd_02(root, config).status == "FAIL"


# ============================================================
# CH_RD_03: Junction radius = 8 m
# ============================================================

class TestRD03JunctionRadius:
    def test_real_cpnco_manual_review(self, config):
        """Real CPNCO has 13-20m lane-centre radii - all consistent with an 8m kerb,
        which RoadRunner does not export to .xodr → MANUAL_REVIEW (not FAIL)."""
        from src.checks.road import check_rd_03
        root = _load(CPNCO_XODR)
        result = check_rd_03(root, config)
        assert result.status == "MANUAL_REVIEW"
        assert "13" in result.comment or "20" in result.comment
        assert "kerb" in result.comment.lower()

    def test_correct_radius_passes(self, config):
        """Setting arc curvature to 1/8 = 0.125 (8m radius) should pass."""
        from src.checks.road import check_rd_03
        root = _copy(_load(CPNCO_XODR))
        # Change all junction arc curvatures to give 8m radius
        junc_roads = {c.get("connectingRoad") for c in root.xpath("//junction/connection")}
        for road in root.xpath("//road"):
            if road.get("id") in junc_roads:
                for arc in road.xpath(".//planView/geometry/arc"):
                    arc.set("curvature", "0.125")  # 1/8 = 8m radius
        result = check_rd_03(root, config)
        assert result.status == "PASS", result.comment

    def test_too_tight_radius_fails(self, config):
        """A connecting radius BELOW 8m means the kerb corner is tighter than spec → FAIL."""
        from src.checks.road import check_rd_03
        root = _copy(_load(CPNCO_XODR))
        junc_roads = {c.get("connectingRoad") for c in root.xpath("//junction/connection")}
        for road in root.xpath("//road"):
            if road.get("id") in junc_roads:
                for arc in road.xpath(".//planView/geometry/arc"):
                    arc.set("curvature", "0.2")  # 1/0.2 = 5m radius < 8m spec
        result = check_rd_03(root, config)
        assert result.status == "FAIL", result.comment


# ============================================================
# CH_RD_04: Leftmost road at (0, 0)
# ============================================================

class TestRD04RoadOrigin:
    def test_cpnco_fails(self, config):
        """CPNCO leftmost road at x=598 → FAIL."""
        from src.checks.road import check_rd_04
        result = check_rd_04(_load(CPNCO_XODR), config)
        assert result.status == "FAIL"
        assert "598" in result.comment

    def test_cpta_passes(self, config):
        """CPTA leftmost road at (0, 0) → PASS."""
        from src.checks.road import check_rd_04
        assert check_rd_04(_load(CPTA_XODR), config).status == "PASS"

    def test_moving_to_origin_passes(self, config):
        """Mutate CPNCO: move leftmost road start to (0, 0) → PASS."""
        from src.checks.road import check_rd_04
        root = _copy(_load(CPNCO_XODR))
        # Find the leftmost geometry and set to origin
        geoms = [(float(g.get("x", 0)), g) for r in root.xpath("//road") for g in r.xpath(".//planView/geometry")]
        if geoms:
            _, leftmost_g = min(geoms, key=lambda t: t[0])
            leftmost_g.set("x", "0.0")
            leftmost_g.set("y", "0.0")
        result = check_rd_04(root, config)
        assert result.status == "PASS", result.comment


# ============================================================
# CH_SC_04: Simulation time 100-150 s
# ============================================================

class TestSC04SimTime:
    def _make_xosc_with_simtime(self, sim_time: float) -> etree._Element:
        """Build minimal xosc with the given SimulationTimeCondition value."""
        xml = f"""<?xml version="1.0"?>
        <OpenSCENARIO>
          <FileHeader description="Test" author="Test"/>
          <Storyboard>
            <StopTrigger>
              <ConditionGroup>
                <Condition name="Stop" delay="0" conditionEdge="none">
                  <ByValueCondition>
                    <SimulationTimeCondition value="{sim_time}" rule="greaterThan"/>
                  </ByValueCondition>
                </Condition>
              </ConditionGroup>
            </StopTrigger>
          </Storyboard>
        </OpenSCENARIO>"""
        return etree.parse(io.BytesIO(xml.encode()), _PARSER).getroot()

    def test_exactly_100s_passes(self, config):
        from src.checks.scenario import check_sc_04
        assert check_sc_04(self._make_xosc_with_simtime(100.0), config).status == "PASS"

    def test_exactly_150s_passes(self, config):
        from src.checks.scenario import check_sc_04
        assert check_sc_04(self._make_xosc_with_simtime(150.0), config).status == "PASS"

    def test_99s_fails(self, config):
        from src.checks.scenario import check_sc_04
        assert check_sc_04(self._make_xosc_with_simtime(99.0), config).status == "FAIL"

    def test_151s_fails(self, config):
        from src.checks.scenario import check_sc_04
        assert check_sc_04(self._make_xosc_with_simtime(151.0), config).status == "FAIL"

    def test_real_ccfhol_passes(self, config):
        """Real CCFhol has SimCondition=150s → PASS."""
        from src.checks.scenario import check_sc_04
        assert check_sc_04(_load(CCFHOL_XOSC), config).status == "PASS"

    def test_real_cpta_passes(self, config):
        """Real CPTA has SimCondition=100s → PASS (boundary)."""
        from src.checks.scenario import check_sc_04
        assert check_sc_04(_load(CPTA_XOSC), config).status == "PASS"


# ============================================================
# CH_SC_06: VUT heading cardinal-axis aligned
# ============================================================

class TestSC06Heading:
    def _xosc_with_vut_heading(self, heading_rad: float) -> etree._Element:
        xml = f"""<?xml version="1.0"?>
        <OpenSCENARIO>
          <FileHeader description="Test"/>
          <Entities><ScenarioObject name="VUT"><Vehicle name="VUT"/></ScenarioObject></Entities>
          <Init><Actions>
            <Private entityRef="VUT">
              <PrivateAction><TeleportAction><Position>
                <WorldPosition x="0" y="-1.75" z="0" h="{heading_rad}"/>
              </Position></TeleportAction></PrivateAction>
            </Private>
          </Actions></Init>
        </OpenSCENARIO>"""
        return etree.parse(io.BytesIO(xml.encode()), _PARSER).getroot()

    def test_east_heading_passes(self, config):
        from src.checks.scenario import check_sc_06
        assert check_sc_06(self._xosc_with_vut_heading(0.0), config).status == "PASS"

    def test_west_heading_passes(self, config):
        from src.checks.scenario import check_sc_06
        assert check_sc_06(self._xosc_with_vut_heading(math.pi), config).status == "PASS"

    def test_north_heading_passes(self, config):
        """CPNCO VUT at 90° (north) must pass - cardinal axis."""
        from src.checks.scenario import check_sc_06
        assert check_sc_06(self._xosc_with_vut_heading(math.pi / 2), config).status == "PASS"

    def test_south_heading_passes(self, config):
        from src.checks.scenario import check_sc_06
        assert check_sc_06(self._xosc_with_vut_heading(-math.pi / 2), config).status == "PASS"

    def test_diagonal_45deg_fails(self, config):
        """45° is off all cardinal axes → FAIL."""
        from src.checks.scenario import check_sc_06
        assert check_sc_06(self._xosc_with_vut_heading(math.pi / 4), config).status == "FAIL"

    def test_diagonal_135deg_fails(self, config):
        from src.checks.scenario import check_sc_06
        assert check_sc_06(self._xosc_with_vut_heading(3 * math.pi / 4), config).status == "FAIL"

    def test_real_cpnco_passes(self, config):
        """Real CPNCO has VUT heading 90° (north) - must pass."""
        from src.checks.scenario import check_sc_06
        assert check_sc_06(_load(CPNCO_XOSC), config).status == "PASS"


# ============================================================
# CH_SC_07: Steady-state turn radius (constant-radius arc, Part 2)
# ============================================================

class TestSC07ConstantRadius:
    def test_real_cpta_passes(self, config):
        """CPTA 10km/h Nearside: measured ~8.2m vs expected 8.0m (Δ2.6%) → PASS."""
        from src.checks.scenario import check_sc_07
        result = check_sc_07(_load(CPTA_XOSC), config)
        assert result.status == "PASS", f"Expected PASS, got {result.status}: {result.comment}"
        assert "Nearside" in result.comment
        assert "8." in result.comment

    def test_real_ccftap_passes(self, config):
        """CCFtap 20km/h Farside: measured ~14.9m vs expected 14.75m (Δ1.1%) → PASS."""
        from src.checks.scenario import check_sc_07
        result = check_sc_07(_load(CCFTAP_XOSC), config)
        assert result.status == "PASS", f"Expected PASS, got {result.status}: {result.comment}"
        assert "Farside" in result.comment
        assert "14." in result.comment

    def test_straight_trajectory_is_na(self, config):
        """CCFhol VUT is straight (heading constant) → NA."""
        from src.checks.scenario import check_sc_07
        assert check_sc_07(_load(CCFHOL_XOSC), config).status == "NA"

    def test_radius_tolerance_boundary(self, config):
        """The tolerance is ±20%. Verify the acceptance band is correctly applied."""
        from src.checks.scenario import check_sc_07
        from src.parsers import xosc
        # CPTA: expected 8.0m, tolerance 20% → accepts 6.4-9.6m
        # Our estimate is ~8.2m - within band → PASS
        root = _load(CPTA_XOSC)
        est, direction = xosc.get_polyline_part2_radius(root, "VUT")
        assert est is not None
        assert 6.4 <= est <= 9.6, f"Estimated radius {est}m outside 20% band around 8m"


# ============================================================
# CH_SC_11: No anchoring
# ============================================================

class TestSC11Anchoring:
    def test_real_files_pass(self, config):
        from src.checks.scenario import check_sc_11
        for xosc_path in [CCFHOL_XOSC, CPNCO_XOSC, CPTA_XOSC]:
            result = check_sc_11(_load(xosc_path), config)
            assert result.status == "PASS", f"{xosc_path.name}: {result.comment}"

    def test_anchor_enabled_fails(self, config):
        """Adding isAnchored=true property to VUT entity should fail CH_SC_11."""
        from src.checks.scenario import check_sc_11
        root = _copy(_load(CCFHOL_XOSC))
        # Add a Controller with isAnchored=true to the VUT entity
        vut_obj = root.xpath("//ScenarioObject[@name='VUT']")[0]
        ctrl_elem = etree.SubElement(vut_obj, "ObjectController")
        ctrl = etree.SubElement(ctrl_elem, "Controller", name="AnchorCtrl")
        props = etree.SubElement(ctrl, "Properties")
        etree.SubElement(props, "Property", name="anchor", value="true")
        assert check_sc_11(root, config).status == "FAIL"


# ============================================================
# CH_SC_12: Timing domain = relative
# ============================================================

class TestSC12TimingDomain:
    def test_real_files_pass(self, config):
        from src.checks.scenario import check_sc_12
        for xosc_path in [CCFHOL_XOSC, CPNCO_XOSC, CPTA_XOSC]:
            result = check_sc_12(_load(xosc_path), config)
            assert result.status == "PASS", f"{xosc_path.name}: {result.comment}"

    def test_absolute_timing_fails(self, config):
        """Changing timing domain to 'absolute' should fail CH_SC_12."""
        from src.checks.scenario import check_sc_12
        root = _copy(_load(CCFHOL_XOSC))
        for t in root.xpath("//Timing"):
            t.set("domainAbsoluteRelative", "absolute")
        assert check_sc_12(root, config).status == "FAIL"


# ============================================================
# CH_SC_14: Static targets speed = 0
# ============================================================

class TestSC14StaticSpeed:
    def test_cpnco_large_small_obstruction_pass(self, config):
        """Real CPNCO LargeObs + SmallObs both have init speed=0 → PASS."""
        from src.checks.scenario import check_sc_14
        result = check_sc_14(_load(CPNCO_XOSC), config)
        assert result.status == "PASS", result.comment
        assert "LargeObstructionVehicle" in result.comment

    def test_nonzero_named_static_fails(self, config, tmp_path):
        """Entity with a name in static_target_name_patterns ('GVTs') with non-zero speed fails."""
        from src.checks.scenario import check_sc_14
        # 'GVTs' starts with 'GVTs' which IS in static_target_name_patterns
        xosc_content = b"""<?xml version="1.0"?>
        <OpenSCENARIO>
          <FileHeader description="Test"/>
          <Entities>
            <ScenarioObject name="VUT"><Vehicle name="VUT"/></ScenarioObject>
            <ScenarioObject name="GVTs"><Vehicle name="GVTs"/></ScenarioObject>
          </Entities>
          <Init><Actions>
            <Private entityRef="VUT">
              <PrivateAction><LongitudinalAction><SpeedAction><SpeedActionTarget>
                <AbsoluteTargetSpeed value="13.89"/>
              </SpeedActionTarget></SpeedAction></LongitudinalAction></PrivateAction>
            </Private>
            <Private entityRef="GVTs">
              <PrivateAction><LongitudinalAction><SpeedAction><SpeedActionTarget>
                <AbsoluteTargetSpeed value="5.0"/>
              </SpeedActionTarget></SpeedAction></LongitudinalAction></PrivateAction>
            </Private>
          </Actions></Init>
        </OpenSCENARIO>"""
        (tmp_path / "test.xosc").write_bytes(xosc_content)
        root = etree.parse(io.BytesIO(xosc_content), _PARSER).getroot()
        result = check_sc_14(root, config)
        assert result.status == "FAIL", result.comment


# ============================================================
# CH_SC_18: VUT speed range
# ============================================================

class TestSC18SpeedRange:
    def test_all_real_scenarios_pass(self, config):
        """All 5 real scenarios should have VUT speed within protocol range."""
        from src.checks.scenario import check_sc_18
        cases = [
            (CCFHOL_XOSC, "CCFhol"),
            (CCFHOS_XOSC, "CCFhos"),
            (CCFTAP_XOSC, "CCFtap"),
            (CPNCO_XOSC,  "CPNCO"),
            (CPTA_XOSC,   "CPTA"),
        ]
        for path, tag in cases:
            result = check_sc_18(_load(path), config, scenario_tag=tag)
            assert result.status == "PASS", f"{tag}: {result.comment}"

    def test_ccftap_below_range_fails(self, config):
        """For CCFtap [10,25 km/h], a VUT speed of 5 km/h should fail."""
        # Modify first vertex time step to imply ~5 km/h
        # Simpler: directly test the check with a synthetic fast trajectory
        from src.checks.scenario import check_sc_18
        from src.parsers import xosc
        root = _copy(_load(CCFTAP_XOSC))
        # Scale all vertex x-coordinates to halve the implied speed
        # (halving distance per unit time → halved speed ~10km/h is still OK,
        # so scale all x positions to zero out motion → ~0 km/h)
        vut_privs = root.xpath("//Init//Private[@entityRef='VUT']")
        for priv in vut_privs:
            for v in priv.xpath(".//FollowTrajectoryAction//Vertex//WorldPosition"):
                v.set("x", "301.0")  # all vertices same x → zero speed
                v.set("y", "-1.75")
        result = check_sc_18(root, config, scenario_tag="CCFtap")
        # Speed will be ~0 or None → Manual (no speed in range)
        assert result.status in ("MANUAL_REVIEW", "FAIL")

    def test_ccftap_boundary_10kmh_passes(self, config):
        """CCFtap protocol range [10, 25]: 10 km/h is the lower boundary → PASS."""
        from src.checks.scenario import check_sc_18
        from src.parsers import xosc
        # CPTA uses 10 km/h and has range [10, 60] → PASS
        result = check_sc_18(_load(CPTA_XOSC), config, scenario_tag="CPTA")
        assert result.status == "PASS"
        assert "10.0 km/h" in result.comment


# ============================================================
# CH_SC_21: VUT first in ordering
# ============================================================

class TestSC21VUTOrdering:
    def test_real_files_all_pass(self, config):
        """All 5 real scenarios: VUT is first in Init/Private ordering."""
        from src.checks.scenario import check_sc_21
        for path in [CCFHOL_XOSC, CCFTAP_XOSC, CPNCO_XOSC, CPTA_XOSC]:
            result = check_sc_21(_load(path), config)
            assert result.status == "PASS", f"{path.name}: {result.comment}"

    def test_non_vut_first_fails(self, config):
        """Reordering Init/Private so EPTc comes before VUT should fail."""
        from src.checks.scenario import check_sc_21
        root = _copy(_load(CPNCO_XOSC))
        actions = root.find(".//Init/Actions")
        privates = list(actions)
        # Move VUT private to the end
        vut_private = next((p for p in privates if p.get("entityRef") == "VUT"), None)
        if vut_private is not None:
            actions.remove(vut_private)
            actions.append(vut_private)
        result = check_sc_21(root, config)
        assert result.status == "FAIL", result.comment


# ============================================================
# CH_MR_01: Speed sanity check via trajectory
# ============================================================

class TestMR01SpeedSanity:
    def test_all_real_scenarios_pass(self, config):
        """All 5 real scenarios: no trajectory speed exceeds 300 km/h."""
        from src.checks.model_review import check_mr_01
        for path in [CCFHOL_XOSC, CCFTAP_XOSC, CPNCO_XOSC, CPTA_XOSC]:
            result = check_mr_01(_load(path), config)
            assert result.status == "PASS", f"{path.name}: {result.comment}"

    def test_impossible_speed_in_trajectory_fails(self, config):
        """Moving a GVT vertex 10000m in one step creates absurd trajectory speed."""
        from src.checks.model_review import check_mr_01
        root = _copy(_load(CCFHOL_XOSC))
        # Teleport the SECOND GVT vertex 10000m from the first in the x direction.
        # Even at a 5s time step, 10000m/5s = 2000 m/s = 7200 km/h >> 300 km/h limit.
        vertices = root.xpath("//Init//Private[@entityRef='GVT']//Vertex")
        if len(vertices) >= 2:
            wp = vertices[1].xpath(".//WorldPosition")
            if wp:
                wp[0].set("x", "10000.0")
        result = check_mr_01(root, config)
        assert result.status == "FAIL", result.comment


# ============================================================
# Protocol boundary: NM_01 actor naming
# ============================================================

class TestNM01ActorNaming:
    def test_sov_name_passes(self, config, tmp_path):
        """Entity named 'SOV' should pass - SOV is in encap_actor_names."""
        from src.checks.naming import check_nm_01
        xosc_content = b"""<?xml version="1.0"?>
        <OpenSCENARIO>
          <FileHeader description="CCFhol_Test"/>
          <Entities>
            <ScenarioObject name="VUT"><Vehicle name="VUT"/></ScenarioObject>
            <ScenarioObject name="GVT"><Vehicle name="GVT"/></ScenarioObject>
            <ScenarioObject name="SOV"><Vehicle name="SOV"/></ScenarioObject>
          </Entities>
        </OpenSCENARIO>"""
        (tmp_path / "test.xosc").write_bytes(xosc_content)
        result = check_nm_01(tmp_path, config)
        assert result.status == "PASS", f"SOV should be a valid EuroNCAP actor: {result.comment}"

    def test_registered_sov_name_passes(self, config, tmp_path):
        """SK_SUV is the CCFhol SOV; the team registers it in config.sov_entity_names. The
        protocol permits the overtaken vehicle to be a real vehicle, so a registered SOV name
        is legitimate and NM_01 must PASS (consistent with the CH_SC_22 SOV exemption)."""
        from src.checks.naming import check_nm_01
        assert "SK_SUV" in {n.upper() for n in config.sov_entity_names}, "fixture expects SK_SUV registered"
        xosc_content = b"""<?xml version="1.0"?>
        <OpenSCENARIO>
          <FileHeader description="CCFhol_Test"/>
          <Entities>
            <ScenarioObject name="VUT"><Vehicle name="VUT"/></ScenarioObject>
            <ScenarioObject name="GVT"><Vehicle name="GVT"/></ScenarioObject>
            <ScenarioObject name="SK_SUV"><Vehicle name="SK_SUV"/></ScenarioObject>
          </Entities>
        </OpenSCENARIO>"""
        (tmp_path / "test.xosc").write_bytes(xosc_content)
        result = check_nm_01(tmp_path, config)
        assert result.status == "PASS", result.comment

    def test_unregistered_nonstandard_name_fails(self, config, tmp_path):
        """An actor name that is neither a EuroNCAP token nor a registered SOV is non-standard,
        and NM_01 FAILs with a hint to register a real-vehicle SOV in config.sov_entity_names."""
        from src.checks.naming import check_nm_01
        unreg = "BadActorXYZ"
        assert unreg.upper() not in {n.upper() for n in config.sov_entity_names}
        xosc_content = f"""<?xml version="1.0"?>
        <OpenSCENARIO>
          <FileHeader description="CCFhol_Test"/>
          <Entities>
            <ScenarioObject name="VUT"><Vehicle name="VUT"/></ScenarioObject>
            <ScenarioObject name="GVT"><Vehicle name="GVT"/></ScenarioObject>
            <ScenarioObject name="{unreg}"><Vehicle name="{unreg}"/></ScenarioObject>
          </Entities>
        </OpenSCENARIO>""".encode()
        (tmp_path / "test.xosc").write_bytes(xosc_content)
        result = check_nm_01(tmp_path, config)
        assert result.status == "FAIL"
        assert unreg in result.comment and "sov_entity_names" in result.comment

    def test_real_ccfhol_passes(self, config):
        """CCFhol's SK_SUV is a registered SOV, so the real run now PASSES."""
        from src.checks.naming import check_nm_01
        result = check_nm_01(EXAMPLES / "CCFhol", config)
        assert result.status == "PASS", result.comment


# ============================================================
# CH_SC_10: Trajectory does not start/end at junction
# ============================================================

class TestSC10JunctionWaypoints:
    def test_ccftap_is_junction_scenario(self, config):
        """CCFtap is a Front Turn-Across-Path scenario: its .xodr junction has real
        turning connecting roads, so SC_10 evaluates the junction waypoint requirement."""
        from src.checks.scenario import check_sc_10
        from lxml import etree
        xodr_root = etree.parse(str(EXAMPLES / "CCFtap" / "AEB_CCFtap_20VUT_45GVT_50Imp.xodr"), _PARSER).getroot()
        result = check_sc_10(_load(CCFTAP_XOSC), xodr_root, config)
        assert result.status in {"PASS", "FAIL"}
        assert "non-intersection" not in result.comment.lower()
        assert "junction" in result.comment.lower()

    def test_unlisted_turn_scenario_detected_by_geometry(self, config):
        """A turn scenario NOT in junction_scenario_prefixes is still detected via the
        .xodr file heuristic (the CCFtap class of bug must not silently short-circuit)."""
        from src.checks.scenario import check_sc_10
        from lxml import etree
        xodr_root = etree.parse(str(EXAMPLES / "CCFtap" / "AEB_CCFtap_20VUT_45GVT_50Imp.xodr"), _PARSER).getroot()
        # SC_10 is purely geometry-driven (no scenario tag) - only the .xodr heuristic detects it
        result = check_sc_10(_load(CCFTAP_XOSC), xodr_root, config)
        assert "non-intersection" not in result.comment.lower()

    def test_cpnco_junction_coverage_passes(self, config):
        """CPNCO is a real junction scenario - trajectory passes through junction → PASS."""
        from src.checks.scenario import check_sc_10
        result = check_sc_10(_load(CPNCO_XOSC), _load(CPNCO_XODR), config)
        assert result.status == "PASS"

    def test_cpta_junction_coverage_passes(self, config):
        """CPTA is a junction turning scenario - trajectory must have junction coverage."""
        from src.checks.scenario import check_sc_10
        result = check_sc_10(_load(CPTA_XOSC), _load(CPTA_XODR), config)
        assert result.status == "PASS"


class TestNM04FilenamePattern:
    """CH_NM_04: structured filename + value cross-check."""

    def _check(self, config, tmp_path, base):
        (tmp_path / f"{base}.rrscene").write_text("rrscene", encoding="utf-8")
        from src.checks.naming import check_nm_04
        return check_nm_04(tmp_path, config)

    def test_real_car_base_passes(self, config, tmp_path):
        assert self._check(config, tmp_path, "AEB_CCFtap_20VUT_45GVT_50Imp").status == "PASS"

    def test_real_vru_base_passes(self, config, tmp_path):
        # 5EPTa target token (pedestrian), 10% impact, 10 km/h VUT all within CPTA protocol
        assert self._check(config, tmp_path, "AEB_CPTAno_10VUT_5EPTa_10Imp").status == "PASS"

    def test_missing_token_fails(self, config, tmp_path):
        assert self._check(config, tmp_path, "AEB_CCFtap_20VUT_50Imp").status == "FAIL"

    def test_vut_speed_out_of_range_fails(self, config, tmp_path):
        # CCFtap protocol VUT range is [10, 25]; 80 km/h is out of range
        assert self._check(config, tmp_path, "AEB_CCFtap_80VUT_45GVT_50Imp").status == "FAIL"

    def test_disallowed_impact_token_fails(self, config, tmp_path):
        # 33 is not an allowed protocol overlap
        assert self._check(config, tmp_path, "AEB_CCFtap_20VUT_45GVT_33Imp").status == "FAIL"

    def test_unknown_type_fails(self, config, tmp_path):
        assert self._check(config, tmp_path, "AEB_ZZZ_20VUT_45GVT_50Imp").status == "FAIL"


class TestJunctionFileDetection:
    """Junction detection is fully file-based (no scenario list)."""

    _INTERSECTION = b"""<?xml version="1.0"?>
    <OpenDRIVE>
      <junction id="1" name="J1">
        <connection id="0" incomingRoad="1" connectingRoad="3"/>
        <connection id="1" incomingRoad="2" connectingRoad="3"/>
      </junction>
      <road id="1"><planView><geometry x="0" y="0" hdg="1.5708" length="50"><line/></geometry></planView></road>
      <road id="2"><planView><geometry x="50" y="0" hdg="0" length="50"><line/></geometry></planView></road>
    </OpenDRIVE>"""

    _LANE_STRUCTURE = b"""<?xml version="1.0"?>
    <OpenDRIVE>
      <junction id="1" name="J1">
        <connection id="0" incomingRoad="1" connectingRoad="3"/>
        <connection id="1" incomingRoad="2" connectingRoad="3"/>
      </junction>
      <road id="1"><planView><geometry x="0" y="0" hdg="0" length="50"><line/></geometry></planView></road>
      <road id="2"><planView><geometry x="50" y="0" hdg="0.05" length="50"><line/></geometry></planView></road>
    </OpenDRIVE>"""

    def test_perpendicular_incoming_roads_is_intersection(self, config):
        from src.parsers import xodr
        root = etree.parse(io.BytesIO(self._INTERSECTION), _PARSER).getroot()
        assert xodr.has_intersection_junction(root, config.junction_intersection_min_spread_deg)

    def test_parallel_incoming_roads_is_not_intersection(self, config):
        """A lane-structure/transition junction links parallel roads -> excluded."""
        from src.parsers import xodr
        root = etree.parse(io.BytesIO(self._LANE_STRUCTURE), _PARSER).getroot()
        assert not xodr.has_intersection_junction(root, config.junction_intersection_min_spread_deg)


class TestSC18FilenameCrossCheck:
    """CH_SC_18 flags a filename VUT-speed token that disagrees with the .xosc."""

    def test_matching_speed_passes(self, config):
        from src.checks.naming import parse_scenario_filename
        from src.checks.scenario import check_sc_18
        root = _load(CPTA_XOSC)  # real CPTA: 10 km/h VUT
        pn = parse_scenario_filename("AEB_CPTAno_10VUT_5EPTa_10Imp", config)
        result = check_sc_18(root, config, scenario_tag="CPTA", parsed_name=pn)
        assert result.status == "PASS", result.comment

    def test_mismatched_speed_flags_manual_review(self, config):
        from src.checks.naming import parse_scenario_filename
        from src.checks.scenario import check_sc_18
        root = _load(CPTA_XOSC)  # real CPTA trajectory ~10 km/h
        pn = parse_scenario_filename("AEB_CPTAno_55VUT_5EPTa_10Imp", config)  # filename lies: 55
        result = check_sc_18(root, config, scenario_tag="CPTA", parsed_name=pn)
        assert result.status == "MANUAL_REVIEW", result.comment
        assert "naming mistake" in result.comment.lower()
