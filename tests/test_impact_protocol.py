"""Protocol-grounded impact-location tests (EuroNCAP Frontal Collisions v1.1).

Grounds the impact estimator against the real reference-point definitions, which vary by
ACTOR and MOTION TYPE (§1.2.5 figures, §1.4.1 virtual boxes, §1.3.1 VUT profile):
  - GVT: rear for Car-to-Car Rear (CCR), front for Car-to-Car Front (CCF), front for turning/crossing.
  - EPTa/EPTc: hip (turning) / back-centreline (longitudinal & crossing).
  - EBTa: front wheel (turning) / rear wheel (longitudinal) / crank shaft (crossing).
  - EMT: front wheel (turning/crossing/long-front) / rear wheel (long-rear).
The current estimator used the target bbox CENTRE for everything — wrong for the long
cyclist/motorcyclist boxes at an angle. These tests are written RED-first.
"""
import math

import pytest


# ---------------------------------------------------------------------------
# Pure decoders (EuroNCAP motion taxonomy, verification table pp60-61)
# ---------------------------------------------------------------------------

def test_scenario_motion_type():
    from src.checks.scenario import scenario_motion_type
    assert scenario_motion_type("CCRs") == "longitudinal"
    assert scenario_motion_type("CCRb") == "longitudinal"
    assert scenario_motion_type("CCFhos") == "longitudinal"
    assert scenario_motion_type("CCFhol") == "longitudinal"
    assert scenario_motion_type("CMRb") == "longitudinal"
    assert scenario_motion_type("CPLA") == "longitudinal"
    assert scenario_motion_type("CBLA") == "longitudinal"
    assert scenario_motion_type("CCFtap") == "turning"
    assert scenario_motion_type("CMFtap") == "turning"
    assert scenario_motion_type("CPTAfs") == "turning"
    assert scenario_motion_type("CPTAno") == "turning"
    assert scenario_motion_type("CBTAns") == "turning"
    assert scenario_motion_type("CCCscp") == "crossing"
    assert scenario_motion_type("CMCscp") == "crossing"
    assert scenario_motion_type("CPNCO") == "crossing"
    assert scenario_motion_type("CPNA") == "crossing"
    assert scenario_motion_type("CBNA") == "crossing"
    assert scenario_motion_type("CBFA") == "crossing"


def test_is_rear_approach():
    from src.checks.scenario import is_rear_approach
    # VUT approaches the target from behind → struck point is the target REAR
    assert is_rear_approach("CCRs") and is_rear_approach("CCRm") and is_rear_approach("CCRb")
    assert is_rear_approach("CMRs") and is_rear_approach("CMRb")
    assert is_rear_approach("CPLA") and is_rear_approach("CBLA")
    # head-on / turning / crossing strike the target FRONT
    assert not is_rear_approach("CCFhos")
    assert not is_rear_approach("CCFhol")
    assert not is_rear_approach("CCFtap")
    assert not is_rear_approach("CMCscp")


# ---------------------------------------------------------------------------
# Actor resolver — OSC category is Vehicle for GVT/EBTa/EMT, so name/filename token decides
# ---------------------------------------------------------------------------

def test_resolve_actor_from_name_token():
    from src.checks.scenario import resolve_actor
    assert resolve_actor("EPTc_Trajectory", None, (0, 0, 0.5, 0.5), "Pedestrian") == "EPTc"
    assert resolve_actor("EPTa", None, (0, 0, 0.5, 0.5), "Pedestrian") == "EPTa"
    assert resolve_actor("GVT", None, (0, 0, 4.5, 1.8), "Vehicle") == "GVT"
    assert resolve_actor("EBTa", None, (0, 0, 1.8, 0.6), "Vehicle") == "EBTa"
    assert resolve_actor("EMT", None, (0, 0, 2.2, 0.8), "Vehicle") == "EMT"
    assert resolve_actor("SOV", None, (0, 0, 4.5, 1.8), "Vehicle") == "SOV"


def test_resolve_actor_filename_fallback():
    from src.checks.scenario import resolve_actor
    # generic entity name → fall back to the filename target token
    assert resolve_actor("Vehicle2", "EBTa", (0, 0, 1.8, 0.6), "Vehicle") == "EBTa"
    assert resolve_actor("Target", "EMT", (0, 0, 2.2, 0.8), "Vehicle") == "EMT"


def test_resolve_actor_bbox_fallback():
    from src.checks.scenario import resolve_actor
    # no token anywhere → bbox aspect-ratio heuristic
    assert resolve_actor("Target", None, (0, 0, 1.8, 0.6), "Vehicle") == "EBTa"   # L/W=3.0
    assert resolve_actor("Target", None, (0, 0, 4.5, 1.8), "Vehicle") == "GVT"    # L/W=2.5


# ---------------------------------------------------------------------------
# (actor × motion) → target reference-point offset (fraction of L along target centreline)
# ---------------------------------------------------------------------------

def test_target_reference_offset_matrix():
    from src.checks.scenario import target_reference_offset
    # GVT: longitudinal rear (CCR) → rear; longitudinal front (CCF) → front; turning/crossing → front
    assert target_reference_offset("GVT", "longitudinal", True)[0] < -0.3
    assert target_reference_offset("GVT", "longitudinal", False)[0] > 0.3
    assert target_reference_offset("GVT", "turning", False)[0] > 0.3
    assert target_reference_offset("GVT", "crossing", False)[0] > 0.3
    # EBTa cyclist: turning → front wheel; crossing → crank (centre); longitudinal → rear wheel
    assert target_reference_offset("EBTa", "turning", False)[0] > 0.3
    assert abs(target_reference_offset("EBTa", "crossing", False)[0]) < 0.1
    assert target_reference_offset("EBTa", "longitudinal", True)[0] < -0.3
    # EMT motorcyclist: front wheel for turning/crossing; rear wheel for longitudinal-rear
    assert target_reference_offset("EMT", "turning", False)[0] > 0.3
    assert target_reference_offset("EMT", "crossing", False)[0] > 0.3
    assert target_reference_offset("EMT", "longitudinal", True)[0] < -0.3
    # Pedestrian: hip (≈ centre) for turning; back for longitudinal/crossing
    assert abs(target_reference_offset("EPTa", "turning", False)[0]) < 0.2
    assert target_reference_offset("EPTa", "longitudinal", True)[0] < -0.15
    # lateral offset is on the centreline for frontal references
    assert target_reference_offset("GVT", "turning", False)[1] == 0.0


# ---------------------------------------------------------------------------
# Geometry: the reference offset materially shifts the impact % for an angled target
# ---------------------------------------------------------------------------

def _perpendicular_crossing():
    """VUT eastbound through the origin; target northbound through the origin, colliding ~t=2."""
    vut = [{"time": t, "x": -20.0 + 10.0 * t, "y": 0.0, "h": 0.0} for t in range(0, 6)]
    tgt = [{"time": t, "x": 0.0, "y": -10.0 + 5.0 * t, "h": math.pi / 2} for t in range(0, 6)]
    return vut, tgt


def test_reference_offset_shifts_impact_for_angled_target():
    """KEYSTONE: for a target crossing at 90°, the front reference point (offset +0.4·L,
    i.e. ~0.72 m north of centre for a 1.8 m box) projects to a very different VUT-width %
    than the centre — proving the per-actor reference point is not a cosmetic detail."""
    from src.geometry import estimate_trajectory_impact
    vut_bbox = (0.0, 0.0, 4.5, 1.8)
    tgt_bbox = (0.0, 0.0, 1.8, 0.6)  # cyclist-like long box
    vut, tgt = _perpendicular_crossing()
    est_centre = estimate_trajectory_impact(vut, tgt, vut_bbox, tgt_bbox, ref_offset=(0.0, 0.0))
    est_front = estimate_trajectory_impact(vut, tgt, vut_bbox, tgt_bbox, ref_offset=(0.4, 0.0))
    assert est_centre is not None and est_centre.contact, est_centre
    assert est_front is not None and est_front.contact, est_front
    assert est_centre.impact_pct_width is not None and est_front.impact_pct_width is not None
    assert abs(est_front.impact_pct_width - est_centre.impact_pct_width) > 15.0, (
        est_centre.impact_pct_width, est_front.impact_pct_width)


def test_side_impact_uses_length_axis():
    """side_impact=True grades across the VUT LENGTH (0%=rear, 100%=front), per §1.2.5."""
    from src.geometry import estimate_trajectory_impact
    vut_bbox = (0.0, 0.0, 4.5, 1.8)
    tgt_bbox = (0.0, 0.0, 2.2, 0.8)  # motorcyclist-like
    # target crosses into the VUT's left side as the VUT passes
    vut = [{"time": t, "x": -20.0 + 10.0 * t, "y": 0.0, "h": 0.0} for t in range(0, 6)]
    tgt = [{"time": t, "x": 0.0, "y": 5.0 - 2.5 * t, "h": -math.pi / 2} for t in range(0, 6)]
    est = estimate_trajectory_impact(vut, tgt, vut_bbox, tgt_bbox, ref_offset=(0.4, 0.0), side_impact=True)
    assert est is not None and est.contact, est
    assert est.impact_pct_length is not None and math.isfinite(est.impact_pct_length)


def test_real_ccftap_turn_across_is_manual_review():
    """Real CCFtap (Car-to-Car Turn-Across-Path): near head-on while the VUT is mid-turn →
    the estimate is sensitive to the exact contact instant (§1.2.5.2), so SC_16 returns
    MANUAL_REVIEW (via the geometry-derived sensitivity gate, NOT a tag match)."""
    import pathlib
    xosc_path = pathlib.Path("examples/CCFtap/AEB_CCFtap_20VUT_45GVT_50Imp.xosc")
    if not xosc_path.exists():
        pytest.skip("CCFtap example not present")
    from src.models import Config
    from src.parsers import xosc as xosc_parser
    from src.checks.scenario import check_sc_16
    root = xosc_parser.load(xosc_path)
    result = check_sc_16(root, Config.load(), scenario_tag="CCFtap", designed_impact_pct=50)
    assert result.status == "MANUAL_REVIEW", result.comment
    assert "uncertainty" in result.comment.lower() and "GVT" in result.comment


def test_real_ccfhol_head_on_passes():
    """Real CCFhol head-on (GVT front reference) must still PASS at ~50% (§1.2.5.3)."""
    import pathlib
    xosc_path = pathlib.Path("examples/CCFhol/AEB_CCFhol_30VUT_50GVT_50Imp.xosc")
    if not xosc_path.exists():
        pytest.skip("CCFhol example not present")
    from src.models import Config
    from src.parsers import xosc as xosc_parser
    from src.checks.scenario import check_sc_16
    root = xosc_parser.load(xosc_path)
    result = check_sc_16(root, Config.load(), scenario_tag="CCFhol", designed_impact_pct=50)
    assert result.status == "PASS", result.comment
    assert "GVT longitudinal" in result.comment and "reference=front" in result.comment


def test_full_width_denominator_not_inset():
    """§1.2.5 scales the % to the vehicle WIDTH edges (0%=outer right, 100%=outer left) —
    the §1.3.1 profiled-line 50 mm inset is contact geometry, NOT the % denominator.
    A target centre on the VUT centreline must read 50.0%, not ~51.4% (which a width-100mm
    denominator would give)."""
    from src.geometry import estimate_trajectory_impact
    bbox = (0.0, 0.0, 4.5, 1.8)
    vut = [{"time": t, "x": 10.0 * t, "y": 0.0, "h": 0.0} for t in range(0, 11)]
    tgt = [{"time": t, "x": 100.0 - 10.0 * t, "y": 0.0, "h": math.pi} for t in range(0, 11)]
    est = estimate_trajectory_impact(vut, tgt, bbox, bbox, ref_offset=(0.0, 0.0))
    assert est is not None and est.contact and est.impact_pct_width is not None
    assert abs(est.impact_pct_width - 50.0) < 1.0, est.impact_pct_width
